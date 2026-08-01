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

from api.deps import set_roster_builder, set_store
from api.main import FRONTEND_DIST, create_app
from api.samples import seed_samples
from contracts import TeacherKnowledgePackage
from contracts.primitives import STAGE_NAMES
from core.storage.memory import InMemoryStore
from stages.s10_publishing.stage import PublishingStage
from stages.stubs import STUB_STAGES

PDF = b"%PDF-1.7\n" + b"x" * 512


async def _stub_roster(*_args: Any) -> Any:
    """Every stage served from a fixture.

    These tests are about the plumbing — upload, enqueue, progress, replay,
    package read — and that has to be provable with no network, no API key, and
    no real document. The production roster is exercised against real documents
    in the stage suites and against live providers in the smoke script.
    """
    return STUB_STAGES


@pytest.fixture
async def client() -> Any:
    set_store(InMemoryStore())
    set_roster_builder(_stub_roster)
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
    job_id = (await client.post("/api/v1/jobs", json={"document_id": document_id})).json()["job_id"]
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
    job_id = (await client.post("/api/v1/jobs", json={"document_id": document_id})).json()["job_id"]
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
    job_id = (await client.post("/api/v1/jobs", json={"document_id": document_id})).json()["job_id"]
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
    job_id = (await client.post("/api/v1/jobs", json={"document_id": document_id})).json()["job_id"]
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
    job_id = (await client.post("/api/v1/jobs", json={"document_id": document_id})).json()["job_id"]
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
    assert response.json()["error"]["code"] == "document_too_large"


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

    first = await client.post("/api/v1/jobs", json={"document_id": document_id}, headers=headers)
    second = await client.post("/api/v1/jobs", json={"document_id": document_id}, headers=headers)

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


# ------------------------------------------------------------- static SPA


@pytest.mark.skipif(
    not (FRONTEND_DIST / "index.html").is_file(),
    reason="frontend not built; the deployed image always builds it",
)
async def test_the_spa_mount_never_shadows_the_api(client: httpx.AsyncClient) -> None:
    """The catch-all route matches everything, so its ordering is load-bearing.

    Registered last on purpose. If it ever moves ahead of the routers, every API
    call starts returning HTML with a 200 — which a JSON client reports as a
    parse error somewhere far away from the cause.
    """
    for path in ("/healthz", "/readyz", "/api/v1/openapi.json"):
        response = await client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json"), path

    # An unknown API path must 404 as JSON, not hand back the SPA shell.
    unknown = await client.get("/api/v1/not-a-route")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")


@pytest.mark.skipif(
    not (FRONTEND_DIST / "index.html").is_file(),
    reason="frontend not built; the deployed image always builds it",
)
async def test_a_deep_link_refresh_returns_the_spa_shell(client: httpx.AsyncClient) -> None:
    """H-02, from the server side.

    The frontend routes client-side, so refreshing on /run/<job-id> mid-run
    arrives as a real GET the server has no route for. Without this the refresh
    404s at exactly the moment the resumable progress stream is meant to prove
    it survives one.
    """
    response = await client.get("/run/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


# ------------------------------------------------------- artifact download


async def test_rendered_artifacts_are_listed_and_downloadable() -> None:
    """The download buttons the frontend already renders must resolve.

    Run with the real publishing stage over stub upstream stages: the stubs make
    no model calls, and stage 10 never did, so this exercises the whole
    render -> store -> list -> download path for free.
    """
    set_store(InMemoryStore())

    async def real_publishing_roster(*_args: Any) -> Any:
        return [*STUB_STAGES[:9], PublishingStage()]

    set_roster_builder(real_publishing_roster)
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        document_id = await _upload(client)
        created = await client.post("/api/v1/jobs", json={"document_id": document_id})
        job = await _await_job(client, created.json()["job_id"])
        assert job["status"] == "succeeded", job.get("error")

        listing = await client.get(f"/api/v1/packages/{job['package_id']}/artifacts")
        assert listing.status_code == 200
        artifacts = listing.json()["artifacts"]
        assert artifacts, "nothing was published"
        assert all(a["status"] == "ready" and a["bytes"] > 0 for a in artifacts)

        pdf = next(a for a in artifacts if a["kind"] == "lesson_plan_pdf")
        downloaded = await client.get(pdf["url"])
        assert downloaded.status_code == 200
        assert downloaded.content[:4] == b"%PDF"
        assert downloaded.headers["content-type"].startswith("application/pdf")
        assert "attachment" in downloaded.headers["content-disposition"]

        missing = await client.get(f"/api/v1/packages/{job['package_id']}/artifacts/nope")
        assert missing.status_code == 404


# ---------------------------------------------------------- error envelope


async def test_every_failure_uses_one_error_envelope(client: httpx.AsyncClient) -> None:
    """One shape for every failure, whatever raised it.

    The UI builds its error from ``body.error.message``. When a raised
    HTTPException returned FastAPI's ``{"detail": ...}`` instead, that read
    ``undefined.message`` and the real cause was replaced by "Cannot read
    properties of undefined (reading 'message')" — the error path throwing its
    own error, which is the one path that must not.

    Covers all three producers: a raised HTTPException, a request-validation
    failure, and a route that does not exist.
    """
    document_id = await _upload(client)

    responses = [
        await client.get("/api/v1/jobs/11111111-1111-4111-8111-111111111111"),
        await client.post("/api/v1/jobs", json={"document_id": "not-a-uuid"}),
        await client.post("/api/v1/jobs", json={"document_id": document_id, "nope": 1}),
        await client.get("/api/v1/definitely-not-a-route"),
    ]

    for response in responses:
        assert response.status_code >= 400
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert "error" in body, f"{response.url} returned {body}"
        error = body["error"]
        assert isinstance(error.get("code"), str) and error["code"]
        assert isinstance(error.get("message"), str) and error["message"]


async def test_a_validation_error_names_the_field_that_failed(
    client: httpx.AsyncClient,
) -> None:
    """Pydantic's raw list is JSON; a person needs to know which field broke."""
    response = await client.post("/api/v1/jobs", json={"document_id": "not-a-uuid"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert "document_id" in error["message"]
    # The raw list stays available for anyone who wants it.
    assert error["details"]["errors"]


async def test_a_route_error_code_survives_into_the_envelope(
    client: httpx.AsyncClient,
) -> None:
    """Routes raise with a machine-readable code; the UI branches on it."""
    response = await client.post(
        "/api/v1/jobs", json={"document_id": "11111111-1111-4111-8111-111111111111"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "document_not_found"


# ---------------------------------------------------------------- samples


@pytest.fixture
async def seeded_client() -> Any:
    """A client whose store has the reference packages loaded.

    Seeded explicitly rather than through the app's lifespan because
    ``ASGITransport`` does not run lifespan events — under uvicorn it does, which
    is why the deployed app has samples and this fixture has to say so out loud.
    """
    store = InMemoryStore()
    set_store(store)
    set_roster_builder(_stub_roster)
    await seed_samples(store)
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_samples_are_listed(seeded_client: httpx.AsyncClient) -> None:
    """The route the frontend has always called, which did not exist until now.

    Without it the physics-vs-history comparison — the clearest demonstration
    this product has — had no live path into the UI at all.
    """
    response = await seeded_client.get("/api/v1/samples")
    assert response.status_code == 200
    samples = response.json()["samples"]
    assert len(samples) == 2

    profiles = {s["pedagogy_profile"] for s in samples}
    assert profiles == {"quantitative", "narrative"}
    for sample in samples:
        assert sample["package_id"] and sample["subject"] and sample["title"]
        assert sample["periods"] >= 1


async def test_a_sample_opens_without_running_anything(
    seeded_client: httpx.AsyncClient,
) -> None:
    """A full run costs 5-7 minutes and a slice of a 50/day quota.

    An evaluator must be able to read a finished package on the first click.
    """
    listed = (await seeded_client.get("/api/v1/samples")).json()["samples"]
    for sample in listed:
        package = await seeded_client.get(f"/api/v1/packages/{sample['package_id']}")
        assert package.status_code == 200
        TeacherKnowledgePackage.model_validate(package.json())


async def test_sample_pdfs_download(seeded_client: httpx.AsyncClient) -> None:
    listed = (await seeded_client.get("/api/v1/samples")).json()["samples"]
    for sample in listed:
        artifacts = (
            await seeded_client.get(f"/api/v1/packages/{sample['package_id']}/artifacts")
        ).json()["artifacts"]
        assert artifacts, sample["subject"]
        assert all(a["status"] == "ready" and a["bytes"] > 0 for a in artifacts)

        pdf = next(a for a in artifacts if a["kind"] == "lesson_plan_pdf")
        downloaded = await seeded_client.get(pdf["url"])
        assert downloaded.status_code == 200
        assert downloaded.content[:4] == b"%PDF"


async def test_sample_ids_are_stable_across_restarts() -> None:
    """A bookmarked sample URL must survive a redeploy.

    Random ids per boot would break every link to a sample on every restart, and
    App Service restarts on each deployment.
    """
    first, second = InMemoryStore(), InMemoryStore()
    await seed_samples(first)
    await seed_samples(second)
    assert {p.id for p in await first.list_samples()} == {p.id for p in await second.list_samples()}


async def test_a_missing_samples_directory_does_not_stop_the_app(tmp_path: Any) -> None:
    """The samples are a demonstration, never a dependency."""
    store = InMemoryStore()
    assert await seed_samples(store, tmp_path / "nope") == 0
    assert await store.list_samples() == []


async def test_options_serves_the_boards_the_pipeline_actually_reads(
    client: httpx.AsyncClient,
) -> None:
    """A UI holding its own board list offers choices the backend ignores."""
    body = (await client.get("/api/v1/options")).json()
    values = [b["value"] for b in body["curriculum_boards"]]
    assert values[0] == "generic", "the common case must not be last in the list"
    assert {"CBSE", "ICSE"} <= set(values)
    assert body["teaching_styles"] and body["artifact_kinds"]
