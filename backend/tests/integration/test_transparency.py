"""What the package says about how it was made.

`Provenance` and `GeneratorInfo` existed in the contract from the start and were
empty in every package the system produced, because nothing threaded usage back
into graph state. That made the cost of a package invisible to the person who
ran it and the reasoning invisible to the teacher who has to trust it.

These tests are about the two questions that transparency has to answer: what
did this cost, and why did it choose that.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from uuid import uuid4

import httpx

from api.deps import set_roster_builder, set_store
from api.main import create_app
from contracts.classification import Classification
from contracts.llm import LLMUsage, ModelSpec, ProviderRouting
from core.llm.base import RawCompletion
from core.llm.client import LLMClient
from core.storage.base import DocumentRecord, JobRecord
from core.storage.memory import InMemoryStore
from orchestration.pipeline import Roster
from stages.base import StageContext, stage_span
from stages.s10_publishing.stage import PublishingStage
from stages.stubs import STUB_STAGES
from tests.fixtures import factories as fx
from worker.runner import run_job


class _Adapter:
    """Reports fixed usage, so attribution arithmetic is checkable."""

    name = "openrouter"

    def __init__(self, tokens_in: int = 100, tokens_out: int = 50) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.calls = 0

    async def complete(
        self, *, spec: Any, system: str, user_content: str, output_model: Any, extra: Any = None
    ) -> RawCompletion:
        self.calls += 1
        # A *valid* payload, so the client does not spend a repair attempt. An
        # invalid one would be counted too — which is correct, and is what
        # `test_a_retry_is_counted_not_hidden` asserts deliberately.
        return RawCompletion(
            text=fx.classification().model_dump_json(),
            model=spec.model,
            usage=LLMUsage(tokens_in=self.tokens_in, tokens_out=self.tokens_out, cost_usd=0.002),
        )


def _client() -> LLMClient:
    return LLMClient(
        routing=ProviderRouting(default=ModelSpec(provider="openrouter", model="demo-model")),
        adapters={"openrouter": _Adapter()},
    )


class _CallingStage:
    """A stage that makes one model call and records one decision."""

    name = "educational-classification"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            await self._llm.parse(
                stage=self.name,
                output_model=Classification,
                system="s",
                user_content="u",
            )
            span.decide("chose the narrative profile", "the content carries no quantities")
            span.warn("something was thin")
            # The reference classification, so the run still publishes a valid
            # package — this stage exists to prove usage attribution, not to
            # test what happens to a malformed one.
            return {"classification": fx.classification().model_dump(mode="json")}


def _roster(llm: LLMClient) -> list[Any]:
    """The full pipeline with stage 2 swapped for one that really calls a model.

    Swapped rather than prepended: `_CallingStage` *is* stage 2, and adding it
    alongside the stub would register the same graph node twice.
    """
    return [STUB_STAGES[0], _CallingStage(llm), *STUB_STAGES[2:9], PublishingStage()]


async def _seed(store: InMemoryStore) -> Any:
    doc = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="b" * 64,
            filename="x.pdf",
            mime="application/pdf",
            size_bytes=10,
            blob_uri="mem://x",
        )
    )
    return await store.create_job(JobRecord(id=uuid4(), document_id=doc.id, options={}))


# ─────────────────────────────────────────────── usage attribution


async def test_a_stage_reports_the_tokens_it_actually_spent() -> None:
    """Attribution is by call-log delta, so it cannot drift from reality.

    No stage declares its own token count — which is the kind of bookkeeping
    that goes stale the first time someone adds a second call to a stage.
    """
    store = InMemoryStore()
    job = await _seed(store)
    llm = _client()

    result = await run_job(store=store, job_id=job.id, stages=_roster(llm), llm=llm)

    reports = result.state["stage_reports"]
    report = next(r for r in reports if r["stage"] == "educational-classification")
    assert report["tokens_in"] == 100
    assert report["tokens_out"] == 50
    assert report["model"] == "demo-model"
    assert report["provider"] == "openrouter"
    assert report["attempts"] == 1
    assert report["duration_ms"] >= 0


async def test_a_stage_that_calls_nothing_reports_no_tokens() -> None:
    """Parsing and publishing use no model; reporting tokens for them would be a lie."""
    store = InMemoryStore()
    job = await _seed(store)
    llm = _client()

    result = await run_job(
        store=store, job_id=job.id, stages=[*STUB_STAGES[:9], PublishingStage()], llm=llm
    )

    for report in result.state["stage_reports"]:
        assert report["tokens_in"] == 0
        assert report.get("model") is None


async def test_warnings_and_decisions_survive_even_when_a_stage_raises() -> None:
    """The run where the reasoning matters most is the one that failed."""

    class _Failing:
        name = "educational-classification"

        async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
            async with stage_span(ctx, self.name) as span:
                span.decide("attempted a narrow retry", "the first schema came back empty")
                raise RuntimeError("boom")

    captured: list[dict[str, Any]] = []
    ctx = StageContext(job_id=uuid4(), options={}, record=lambda **f: captured.append(f))

    with contextlib.suppress(RuntimeError):
        await _Failing().run(ctx, {})

    assert captured, "a failing stage reported nothing"
    assert captured[0]["decisions"][0]["what"] == "attempted a narrow retry"


# ──────────────────────────────────────────── the published package


async def test_the_package_reports_what_it_cost() -> None:
    """Empty provenance is what this whole mechanism exists to end."""
    store = InMemoryStore()
    job = await _seed(store)
    llm = _client()

    result = await run_job(
        store=store, job_id=job.id, stages=[*STUB_STAGES[:9], PublishingStage()], llm=llm
    )
    provenance = (result.package or {})["provenance"]

    # Every stage that ran before publishing is accounted for. Publishing itself
    # cannot appear: it assembles the package, so its own duration is not known
    # until after the object it would be recorded in has been built.
    stages = [t["stage"] for t in provenance["stage_timings"]]
    assert len(stages) == 9
    assert "publishing" not in stages
    assert provenance["total_duration_ms"] >= 0
    assert provenance["citations"]


async def test_the_package_names_the_model_behind_each_stage() -> None:
    """ "Which model wrote this?" must be answerable from the package alone.

    Read from the calls that happened, not from the routing config — config says
    what a stage was *configured* to use, which diverges the moment a fallback
    fires.
    """
    store = InMemoryStore()
    job = await _seed(store)
    llm = _client()

    result = await run_job(store=store, job_id=job.id, stages=_roster(llm), llm=llm)

    generator = (result.package or {})["generator"]
    assert generator["models_by_stage"]["educational-classification"] == "demo-model"
    assert generator["providers_by_stage"]["educational-classification"] == "openrouter"
    # Stages that called nothing are absent rather than blank.
    assert "document-intelligence" not in generator["models_by_stage"]


async def test_a_retry_is_counted_not_hidden() -> None:
    """A stage that succeeded on its second try cost two calls.

    A package reporting one would quote a price nobody paid, and a retry rate
    trending upward is the earliest signal that a prompt or a provider has
    degraded — hiding the failed attempt removes the signal.
    """

    class _FlakyAdapter(_Adapter):
        async def complete(self, **kwargs: Any) -> RawCompletion:
            self.calls += 1
            if self.calls == 1:
                # Schema-invalid, so the client spends a repair attempt.
                return RawCompletion(
                    text="{}",
                    model=kwargs["spec"].model,
                    usage=LLMUsage(tokens_in=10, tokens_out=5),
                )
            return RawCompletion(
                text=fx.classification().model_dump_json(),
                model=kwargs["spec"].model,
                usage=LLMUsage(tokens_in=self.tokens_in, tokens_out=self.tokens_out),
            )

    adapter = _FlakyAdapter()
    llm = LLMClient(
        routing=ProviderRouting(default=ModelSpec(provider="openrouter", model="demo-model")),
        adapters={"openrouter": adapter},
    )
    store = InMemoryStore()
    job = await _seed(store)

    result = await run_job(store=store, job_id=job.id, stages=_roster(llm), llm=llm)
    report = next(
        r for r in result.state["stage_reports"] if r["stage"] == "educational-classification"
    )

    assert adapter.calls == 2
    assert report["attempts"] == 2, "the failed attempt was not counted"
    assert report["tokens_in"] == 110, "the failed attempt's tokens were not counted"


# ──────────────────────────────────────── the wiring, not just the mechanism


async def test_the_api_path_hands_the_call_log_to_the_runner() -> None:
    """Attribution has to survive the path a real request actually takes.

    Every test above calls ``run_job(llm=...)`` by hand. That proves the
    arithmetic and proves nothing about whether anything passes the client in
    production — and nothing did: ``roster_for_job`` built the client, handed it
    to the stages, and dropped it, so the API's spawn path called ``run_job``
    with ``llm=None``. Attribution then took the no-calls branch and every
    package the deployed app produced shipped zero tokens, zero cost and an
    empty ``models_by_stage``.

    It stayed invisible because the fixtures hardcode those fields and every
    unit test injects the client by hand. What caught it was scoring a live run:
    stage 10 reported "0 of 8 model-calling stages record which model produced
    their output".
    """
    store = InMemoryStore()
    set_store(store)
    llm = _client()

    async def roster(*_args: Any) -> Roster:
        return Roster(stages=_roster(llm), llm=llm)

    set_roster_builder(roster)

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        upload = await client.post(
            "/api/v1/documents",
            files={"file": ("x.txt", b"a physics chapter about force", "text/plain")},
        )
        created = await client.post(
            "/api/v1/jobs", json={"document_id": upload.json()["document_id"]}
        )
        job_id = created.json()["job_id"]

        for _ in range(200):
            snapshot = (await client.get(f"/api/v1/jobs/{job_id}")).json()
            if snapshot["status"] in {"succeeded", "succeeded_partial", "failed"}:
                break
            await asyncio.sleep(0.05)

        assert snapshot["status"] == "succeeded", snapshot.get("error")
        package = (await client.get(f"/api/v1/packages/{snapshot['package_id']}")).json()

    generator = package["generator"]
    provenance = package["provenance"]

    assert generator["models_by_stage"], "no stage recorded the model that ran it"
    assert generator["models_by_stage"]["educational-classification"] == "demo-model"
    assert generator["providers_by_stage"]["educational-classification"] == "openrouter"
    assert provenance["total_tokens_in"] == 100, "token attribution was lost in the API path"
    assert provenance["total_tokens_out"] == 50
    assert provenance["total_cost_usd"] > 0
