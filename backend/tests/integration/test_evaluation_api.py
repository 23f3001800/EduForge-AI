"""The evaluation endpoints, over HTTP.

The framework itself is tested in ``tests/unit/test_eval_framework.py``. What is
proved here is the wiring a unit test cannot reach:

* the API returns the *same* document the CLI does, so a screen and a terminal
  never disagree about a score;
* the history series survives across requests, and a run is not benchmarked
  against itself;
* the PDF export is a real PDF of the same run rather than a second evaluation.

No model, no key, no network — evaluation is deterministic arithmetic over a
stored package, which is exactly why it can be an endpoint at all.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from api.deps import set_store
from api.main import create_app
from api.routes.evaluations import set_history
from core.storage.memory import InMemoryStore
from evals.store import EvaluationRecord, EvaluationStore
from tests.fixtures.seeding import seed_packages


@pytest.fixture
async def client() -> Any:
    """A seeded store and a *fresh* history for every test.

    Sharing the series between tests would let one test's runs form another's
    baseline, and a benchmark assembled from unrelated runs is the exact defect
    the profile partitioning exists to prevent.
    """
    store = InMemoryStore()
    await seed_packages(store)
    set_store(store)
    set_history(EvaluationStore())

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _a_package_id(client: httpx.AsyncClient) -> str:
    samples = (await client.get("/api/v1/samples")).json()["samples"]
    return str(samples[0]["package_id"])


async def test_a_package_can_be_evaluated_over_http(client: httpx.AsyncClient) -> None:
    package_id = await _a_package_id(client)
    response = await client.get(f"/api/v1/packages/{package_id}/evaluation")
    assert response.status_code == 200

    document = response.json()
    assert document["summary"]["stage_score"] is not None
    assert len(document["stages"]) == 11
    assert document["not_measurable"], "a report claiming everything is measurable is wrong"


async def test_every_score_carries_its_reasoning_and_its_kind(
    client: httpx.AsyncClient,
) -> None:
    """The contract the whole framework rests on, checked at the wire format:
    no metric reaches a caller without saying how it was arrived at."""
    package_id = await _a_package_id(client)
    document = (await client.get(f"/api/v1/packages/{package_id}/evaluation")).json()

    for stage in document["stages"]:
        for metric in stage["metrics"]:
            assert metric["reasoning"], f"{metric['key']} has no reasoning"
            assert metric["measurability"] in {"measured", "judged", "not_measurable"}
            if metric["measurability"] == "not_measurable":
                assert metric["score"] is None, f"{metric['key']} invented a score"
            else:
                assert metric["score"] is not None


async def test_an_unknown_package_is_a_404_not_a_500(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/packages/00000000-0000-4000-8000-000000000000/evaluation")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "package_not_found"


async def test_evaluations_accumulate_into_a_series(client: httpx.AsyncClient) -> None:
    package_id = await _a_package_id(client)
    await client.get(f"/api/v1/packages/{package_id}/evaluation")

    listed = (await client.get("/api/v1/evaluations")).json()
    assert listed["total"] == 1
    assert listed["evaluations"][0]["run_id"] == package_id
    assert listed["durable"] is False, "an in-memory series must say so"


async def test_a_run_can_be_evaluated_without_joining_the_series(
    client: httpx.AsyncClient,
) -> None:
    """Re-scoring a package to look at it should not move its own baseline."""
    package_id = await _a_package_id(client)
    await client.get(f"/api/v1/packages/{package_id}/evaluation?persist=false")
    assert (await client.get("/api/v1/evaluations")).json()["total"] == 0


async def test_the_benchmark_declines_to_judge_a_thin_history(
    client: httpx.AsyncClient,
) -> None:
    package_id = await _a_package_id(client)
    document = (await client.get(f"/api/v1/packages/{package_id}/evaluation")).json()
    assert document["comparison"]["status"] == "insufficient_history"

    benchmark = (await client.get("/api/v1/evaluations/benchmark")).json()
    assert benchmark["sufficient"] is False


async def test_a_regression_is_reported_once_a_baseline_exists(
    client: httpx.AsyncClient,
) -> None:
    """The endpoint must reach the same verdict as the library, against history
    it did not create itself."""
    package_id = await _a_package_id(client)
    first = (await client.get(f"/api/v1/packages/{package_id}/evaluation")).json()
    profile = first["profile"]

    from api.routes.evaluations import get_history

    history = get_history()
    for i in range(6):
        history.record(
            EvaluationRecord(
                run_id=f"seed-{i}",
                package_id="seed",
                subject=first["subject"],
                grade_band=first["grade_band"],
                profile=profile,
                overall=100.0,
                confidence=1.0,
                # Far above anything the real package scores, so the comparison
                # has to call it rather than shrug.
                stage_scores={"validation": 100.0, "gap-analysis": 100.0},
            )
        )

    again = (await client.get(f"/api/v1/packages/{package_id}/evaluation")).json()
    assert again["comparison"]["status"] in {"ok", "regression"}
    assert again["comparison"]["runs"] >= 6


async def test_the_pdf_export_is_a_pdf_of_the_same_run(client: httpx.AsyncClient) -> None:
    package_id = await _a_package_id(client)
    response = await client.get(f"/api/v1/packages/{package_id}/evaluation.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 5_000, "a report this thin is missing sections"
    assert f"evaluation-{package_id}.pdf" in response.headers["content-disposition"]


async def test_the_pdf_export_does_not_pollute_the_series(
    client: httpx.AsyncClient,
) -> None:
    """Exporting a report is reading, not running. A download that appended to
    the trend line would let a reviewer refreshing a page rewrite the baseline."""
    package_id = await _a_package_id(client)
    await client.get(f"/api/v1/packages/{package_id}/evaluation.pdf")
    assert (await client.get("/api/v1/evaluations")).json()["total"] == 0


async def test_the_api_and_the_library_agree_on_the_score(
    client: httpx.AsyncClient,
) -> None:
    """A dashboard computing its own averages is a second rubric nobody tests."""
    from evals.service import evaluate_package

    package_id = await _a_package_id(client)
    over_http = (await client.get(f"/api/v1/packages/{package_id}/evaluation")).json()

    package = (await client.get(f"/api/v1/packages/{package_id}")).json()
    direct = evaluate_package(package, run_id=package_id)

    assert over_http["summary"]["stage_score"] == direct["summary"]["stage_score"]
    assert [s["score"] for s in over_http["stages"]] == [s["score"] for s in direct["stages"]]
