"""API integration — the rest of the MS-1 gate.

Proves the full evaluator path end to end with no model calls:
upload -> enqueue -> watch progress -> read the package.

The SSE replay tests are the important ones. An evaluator refreshing the tab
during a multi-minute run is not an edge case, it is the expected behaviour, and
losing the timeline there makes a working pipeline look broken.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from api.deps import set_store
from api.main import create_app
from contracts import TeacherKnowledgePackage
from contracts.primitives import STAGE_NAMES
from core.storage.memory import InMemoryStore

PDF = b"%PDF-1.7\n" + b"x" * 512


@pytest.fixture
async def client() -> Any:
    set_store(InMemoryStore())
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _upload(client: httpx.AsyncClient, content: bytes = PDF, name: str = "a.pdf") -> str:
    response = await client.post(
        "/api/v1/documents", files={"file": (name, content, "application/pdf")}
    )
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


async def _await_job(client: httpx.AsyncClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        body = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        if body["status"] in {"succeeded", "succeeded_partial", "failed"}:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish in time")


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    frames = []
    for block in raw.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        record: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                record["id"] = int(line[4:])
            elif line.startswith("event: "):
                record["event"] = line[7:]
            elif line.startswith("data: "):
                record["data"] = json.loads(line[6:])
        if "data" in record:
            frames.append(record)
    return frames


# ---------------------------------------------------------------- happy path


async def test_full_evaluator_path(client: httpx.AsyncClient) -> None:
    """Upload, enqueue, wait, read the package — the whole product in one test."""
    document_id = await _upload(client)

    created = await client.post("/api/v1/jobs", json={"document_id": document_id})
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    job = await _await_job(client, job_id)
    assert job["status"] == "succeeded"
    assert job["progress"] == 100
    assert sorted(job["completed_stages"]) == sorted(STAGE_NAMES)

    package = await client.get(f"/api/v1/packages/{job['package_id']}")
    assert package.status_code == 200
    TeacherKnowledgePackage.model_validate(package.json())


async def test_validation_report_is_exposed(client: httpx.AsyncClient) -> None:
    document_id = await _upload(client)
    job_id = (
        await client.post("/api/v1/jobs", json={"document_id": document_id})
    ).json()["job_id"]
    job = await _await_job(client, job_id)

    report = await client.get(f"/api/v1/packages/{job['package_id']}/validation")
    assert report.status_code == 200
    assert report.json()["status"] in {"pass", "pass_with_warnings", "fail"}


# ----------------------------------------------------------------------- SSE


async def test_sse_replays_the_whole_timeline_for_a_finished_job(
    client: httpx.AsyncClient,
) -> None:
    """A client arriving after the job finished still renders a complete run."""
    document_id = await _upload(client)
    job_id = (
        await client.post("/api/v1/jobs", json={"document_id": document_id})
    ).json()["job_id"]
    await _await_job(client, job_id)

    stream = await client.get(f"/api/v1/jobs/{job_id}/events")
    frames = _parse_sse(stream.text)

    assert frames, "stream returned nothing"
    assert frames[-1]["event"] == "completed"
    assert frames[-1]["data"]["progress"] == 100
    seen = {f["data"]["stage"] for f in frames}
    assert set(STAGE_NAMES) <= seen


async def test_every_sse_frame_has_stage_and_progress(client: httpx.AsyncClient) -> None:
    """The exact wire shape the assignment specifies."""
    document_id = await _upload(client)
    job_id = (
        await client.post("/api/v1/jobs", json={"document_id": document_id})
    ).json()["job_id"]
    await _await_job(client, job_id)

    for frame in _parse_sse((await client.get(f"/api/v1/jobs/{job_id}/events")).text):
        assert isinstance(frame["data"]["stage"], str)
        assert isinstance(frame["data"]["progress"], int)


async def test_last_event_id_resumes_without_gap_or_duplicate(
    client: httpx.AsyncClient,
) -> None:
    """The refresh-mid-run guarantee (H-02).

    Read the stream, cut it at an arbitrary point, reconnect with the last id,
    and assert the two halves join exactly — no event lost, none repeated.
    """
    document_id = await _upload(client)
    job_id = (
        await client.post("/api/v1/jobs", json={"document_id": document_id})
    ).json()["job_id"]
    await _await_job(client, job_id)

    full = _parse_sse((await client.get(f"/api/v1/jobs/{job_id}/events")).text)
    assert len(full) > 6

    cut = len(full) // 2
    resumed = _parse_sse(
        (
            await client.get(
                f"/api/v1/jobs/{job_id}/events",
                headers={"Last-Event-ID": str(full[cut - 1]["id"])},
            )
        ).text
    )

    assert [f["id"] for f in full[:cut] + resumed] == [f["id"] for f in full]


async def test_malformed_last_event_id_replays_rather_than_failing(
    client: httpx.AsyncClient,
) -> None:
    """Losing the timeline is worse than re-sending events a client can dedupe."""
    document_id = await _upload(client)
    job_id = (
        await client.post("/api/v1/jobs", json={"document_id": document_id})
    ).json()["job_id"]
    await _await_job(client, job_id)

    response = await client.get(
        f"/api/v1/jobs/{job_id}/events", headers={"Last-Event-ID": "not-a-number"}
    )
    assert response.status_code == 200
    assert _parse_sse(response.text)


async def test_sse_for_unknown_job_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/jobs/11111111-1111-4111-8111-111111111111/events")
    assert response.status_code == 404


# ------------------------------------------------------------ upload guards


async def test_oversized_upload_is_rejected(client: httpx.AsyncClient) -> None:
    from core.config import get_settings

    oversized = b"%PDF-1.7\n" + b"x" * (get_settings().max_upload_bytes + 1)
    response = await client.post(
        "/api/v1/documents", files={"file": ("big.pdf", oversized, "application/pdf")}
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "document_too_large"


async def test_unsupported_type_is_rejected_by_content_not_extension(
    client: httpx.AsyncClient,
) -> None:
    """A binary renamed to .pdf must not be accepted on the strength of its name."""
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("evil.pdf", b"\x00\x01\x02\xff\xfe", "application/pdf")},
    )
    assert response.status_code == 415


async def test_empty_upload_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents", files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    assert response.status_code == 422


async def test_plain_text_is_accepted(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", b"Chapter 1\nInertia.", "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["mime"] == "text/plain"


async def test_duplicate_upload_is_deduplicated(client: httpx.AsyncClient) -> None:
    first = await client.post(
        "/api/v1/documents", files={"file": ("a.pdf", PDF, "application/pdf")}
    )
    second = await client.post(
        "/api/v1/documents", files={"file": ("a-copy.pdf", PDF, "application/pdf")}
    )
    assert first.json()["document_id"] == second.json()["document_id"]
    assert second.json()["deduplicated"] is True


# ------------------------------------------------------------- idempotency


async def test_idempotency_key_prevents_a_duplicate_run(client: httpx.AsyncClient) -> None:
    """A double-clicked Generate button must not start two runs."""
    document_id = await _upload(client)
    headers = {"Idempotency-Key": "abc-123"}

    first = await client.post(
        "/api/v1/jobs", json={"document_id": document_id}, headers=headers
    )
    second = await client.post(
        "/api/v1/jobs", json={"document_id": document_id}, headers=headers
    )

    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["deduplicated"] is True


async def test_job_for_unknown_document_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/jobs", json={"document_id": "11111111-1111-4111-8111-111111111111"}
    )
    assert response.status_code == 404


# -------------------------------------------------------------------- ops


async def test_health_and_readiness(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json()["status"] == "ok"
    ready = await client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["schema_version"]


async def test_openapi_is_published(client: httpx.AsyncClient) -> None:
    spec = await client.get("/api/v1/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/v1/documents" in paths
    assert "/api/v1/jobs/{job_id}/events" in paths
