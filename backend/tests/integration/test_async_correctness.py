"""Correctness under concurrency — the fixes in the backend review.

Five defects, all about what happens when a job shares a process (and an event
loop) with everything else running in it:

1. **Terminal event ordering.** ``job.status`` used to flip to a terminal value
   *before* the terminal SSE event was persisted, so an SSE reader polling
   ``GET /jobs`` right at that instant could see "succeeded" with no "completed"
   frame to show for it, and — worse — could disconnect having decided the job
   would never finish. Proved here with a store that inserts a real ``await``
   between recording each write and returning from it, so the race is a
   scheduling fact a concurrent reader can actually land in, not an argument
   about source order.
2. **``succeeded_partial`` was never assigned.** A package that failed
   validation reported the clean ``succeeded`` status, which also made it
   permanently unretryable — ``retry_job`` 409s on ``succeeded``.
3. **Job usage was never written.** ``tokens_used``, ``cost_usd`` and
   ``warnings`` were declared, read by ``GET /jobs/{id}``, and set by nothing.
4. **Blocking work ran inline on the event loop.** Stage 10's PDFs and the
   evaluation endpoints' scoring/PDF export are CPU-bound enough to stall every
   other job's SSE stream for their duration if not offloaded — and offloading
   the evaluation history's SQLite calls onto worker threads is only safe if the
   one connection it wraps is serialized, which it was not.
5. **``asyncio.gather`` did not cancel siblings.** A failed period in stage 5
   left every other in-flight period's model call running — and billing —
   after the job had already failed and would never look at the result.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from api.routes.events import _stream
from api.routes.jobs import _fail_job, retry_job
from contracts import ConsistencyReport, CoverageReport, ValidationIssue, ValidationReport
from contracts.classification import Classification
from contracts.llm import LLMUsage, ModelSpec, ProviderRouting
from core.llm.base import RawCompletion
from core.llm.client import LLMClient
from core.storage.base import DocumentRecord, JobEvent, JobRecord, Store
from core.storage.memory import InMemoryStore
from orchestration.pipeline import Roster
from stages.base import StageContext, stage_span
from stages.s5_classroom_content.stage import ClassroomContentStage
from stages.s10_publishing.stage import PublishingStage
from stages.stubs import STUB_STAGES
from tests.fixtures import factories as fx
from worker.runner import run_job

_TERMINAL_JOB_STATUSES = {"succeeded", "succeeded_partial", "failed", "cancelled"}
_TERMINAL_EVENT_STAGES = {"completed", "failed", "cancelled"}


async def _seed(store: Store) -> JobRecord:
    doc = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="d" * 64,
            filename="x.pdf",
            mime="application/pdf",
            size_bytes=10,
            blob_uri="mem://x",
        )
    )
    return await store.create_job(JobRecord(id=uuid4(), document_id=doc.id, options={}))


# ══════════════════════════════════ 1. terminal event ordering ══════════════


class _OrderRecordingStore(InMemoryStore):
    """Records the true order of terminal writes, with a genuine yield point.

    Each override performs the real write *first* — so the store's state is
    already updated when a concurrent reader could observe it — then records
    the call and yields with ``await asyncio.sleep(0)``. That yield is not
    decoration: it is the exact moment a concurrently scheduled task (a poller,
    another request) gets to run, so if the write order were ever wrong again,
    a reader really could interleave there and see it, not just in theory.
    """

    def __init__(self) -> None:
        super().__init__()
        self.call_order: list[tuple[str, str]] = []

    async def update_job(self, job: JobRecord) -> JobRecord:
        result = await super().update_job(job)
        self.call_order.append(("update_job", job.status))
        await asyncio.sleep(0)
        return result

    async def append_event(self, event: JobEvent) -> JobEvent:
        result = await super().append_event(event)
        self.call_order.append(("append_event", event.stage))
        await asyncio.sleep(0)
        return result


def _first_terminal_update(order: list[tuple[str, str]]) -> int:
    return next(
        i
        for i, (op, val) in enumerate(order)
        if op == "update_job" and val in _TERMINAL_JOB_STATUSES
    )


def _first_terminal_event(order: list[tuple[str, str]]) -> int:
    return next(
        i
        for i, (op, val) in enumerate(order)
        if op == "append_event" and val in _TERMINAL_EVENT_STAGES
    )


async def test_terminal_event_is_persisted_before_status_flips_terminal_on_success() -> None:
    store = _OrderRecordingStore()
    job = await _seed(store)

    await run_job(
        store=store, job_id=job.id, stages=[*STUB_STAGES[:9], PublishingStage()], llm=None
    )

    update_index = _first_terminal_update(store.call_order)
    event_index = _first_terminal_event(store.call_order)
    assert event_index < update_index, (
        "job.status flipped to a terminal value before the terminal event was "
        f"persisted: {store.call_order}"
    )


class _RaisingStage:
    """Stands in for any stage that dies mid-pipeline."""

    name = "educational-classification"

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name):
            raise RuntimeError("boom")


async def test_terminal_event_is_persisted_before_status_flips_terminal_on_failure() -> None:
    store = _OrderRecordingStore()
    job = await _seed(store)

    with pytest.raises(RuntimeError):
        await run_job(
            store=store, job_id=job.id, stages=[STUB_STAGES[0], _RaisingStage()], llm=None
        )

    update_index = _first_terminal_update(store.call_order)
    event_index = _first_terminal_event(store.call_order)
    assert event_index < update_index, (
        f"the failure path flipped status before persisting the event: {store.call_order}"
    )


async def test_fail_job_persists_the_event_before_the_terminal_status() -> None:
    """``jobs._fail_job`` — the pre-pipeline failure path (roster construction) —
    must follow the identical ordering rule ``run_job`` follows."""
    store = _OrderRecordingStore()
    job = await _seed(store)

    await _fail_job(store, job.id, RuntimeError("roster construction blew up"))

    update_index = _first_terminal_update(store.call_order)
    event_index = _first_terminal_event(store.call_order)
    assert event_index < update_index, store.call_order


async def test_a_concurrent_reader_never_observes_terminal_status_without_the_event() -> None:
    """The scenario the ordering fix exists for, reproduced rather than argued.

    A poller task runs *alongside* the job, sharing the same event loop, reading
    the same store. It has many chances to interleave — the recording store
    yields after every write the job makes. If it ever observes a terminal
    ``job.status`` with no terminal event behind it, that is exactly the SSE
    client that would have seen "succeeded" and no "completed" frame, and
    disconnected having decided the job hung.
    """
    store = _OrderRecordingStore()
    job = await _seed(store)
    violations: list[str] = []

    async def poll() -> None:
        while True:
            snapshot = await store.get_job(job.id)
            if snapshot is not None and snapshot.status in _TERMINAL_JOB_STATUSES:
                events = await store.events_since(job.id, 0)
                if not any(e.stage in _TERMINAL_EVENT_STAGES for e in events):
                    violations.append(snapshot.status)
                return
            await asyncio.sleep(0)

    poller = asyncio.create_task(poll())
    await run_job(
        store=store, job_id=job.id, stages=[*STUB_STAGES[:9], PublishingStage()], llm=None
    )
    await poller

    assert not violations, f"observed terminal status with no terminal event: {violations}"


class _NeverDisconnected:
    async def is_disconnected(self) -> bool:
        return False


class _LateArrivalStore:
    """The SSE-side half of the same race: the terminal event exists, but the
    reader's ``events_since`` happened to run in the instant before it landed.

    The first call returns nothing (a genuine "caught up, nothing new" read);
    every call after that returns the event — simulating it having been
    persisted in the gap between that first read and the ``get_job`` status
    check that follows it. Without the defensive re-check in ``_stream``, the
    loop sees a terminal status, gives up, and the client never gets the frame
    it is waiting on.
    """

    def __init__(self, status: str, event: JobEvent) -> None:
        self._status = status
        self._event = event
        self.events_since_calls = 0

    async def get_job(self, job_id: UUID) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(status=self._status)

    async def events_since(self, job_id: UUID, after_seq: int = 0) -> list[JobEvent]:
        self.events_since_calls += 1
        if self.events_since_calls == 1:
            return []
        return [self._event] if self._event.seq > after_seq else []

    async def wait_for_events(self, job_id: UUID, after_seq: int, timeout: float) -> None:
        return


async def test_sse_rechecks_events_before_giving_up_on_a_terminal_job() -> None:
    job_id = uuid4()
    event = JobEvent(seq=1, job_id=job_id, stage="completed", progress=100, message="done")
    store = _LateArrivalStore("succeeded", event)

    frames = [frame async for frame in _stream(store, job_id, 0, _NeverDisconnected())]

    assert store.events_since_calls >= 2, "the stream gave up after a single events_since read"
    assert any("event: completed" in frame for frame in frames), (
        "the trailing terminal event was silently dropped instead of being replayed"
    )


# ══════════════════════════════════ 2. succeeded_partial ═════════════════════


class _FailingValidationStage:
    """Stands in for stage 9 reporting a real validation failure."""

    name = "validation"

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name):
            report = ValidationReport(
                status="fail",
                schema_ok=True,
                coverage=CoverageReport(),
                consistency=ConsistencyReport(),
                grounding_score=0.4,
                issues=[
                    ValidationIssue(
                        code="COVERAGE_CONCEPT_UNTAUGHT",
                        severity="error",
                        message="a concept the source defines is never taught",
                        path="/knowledge/concepts/0",
                        stage="knowledge-extraction",
                    )
                ],
                profile_ruleset="quantitative",
                checked_at=fx.FIXED_TIME,
            )
            return {"validation": report.model_dump(mode="json")}


async def test_a_failed_validation_report_produces_succeeded_partial_not_succeeded() -> None:
    store = InMemoryStore()
    job = await _seed(store)

    stages = [*STUB_STAGES[:8], _FailingValidationStage(), PublishingStage()]
    result = await run_job(store=store, job_id=job.id, stages=stages, llm=None)

    saved = await store.get_job(job.id)
    assert saved is not None
    assert saved.status == "succeeded_partial", (
        "a package that failed validation must not report the clean 'succeeded' "
        "status — that status also 409s on retry, so a package stuck failing "
        "validation would have no route back to a clean one"
    )
    assert (result.package or {})["validation"]["status"] == "fail"


async def test_succeeded_partial_is_retryable_but_succeeded_is_not() -> None:
    """The consequence that made this a real defect, not a cosmetic one."""
    from core.config import get_settings

    async def _roster(store: Store, job: JobRecord, settings: Any) -> Roster:
        return Roster(stages=STUB_STAGES, llm=None)

    store = InMemoryStore()
    doc = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="e" * 64,
            filename="x.pdf",
            mime="application/pdf",
            size_bytes=10,
            blob_uri="mem://x",
        )
    )

    partial = await store.create_job(
        JobRecord(id=uuid4(), document_id=doc.id, status="succeeded_partial")
    )
    response = await retry_job(
        job_id=partial.id, store=store, settings=get_settings(), roster=_roster
    )
    assert response["status"] == "queued"

    clean = await store.create_job(JobRecord(id=uuid4(), document_id=doc.id, status="succeeded"))
    with pytest.raises(HTTPException) as exc_info:
        await retry_job(job_id=clean.id, store=store, settings=get_settings(), roster=_roster)
    assert exc_info.value.status_code == 409


# ══════════════════════════════════ 3. job usage & warnings ══════════════════


class _UsageAdapter:
    name = "openrouter"

    def __init__(self, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd

    async def complete(
        self, *, spec: Any, system: str, user_content: str, output_model: Any, extra: Any = None
    ) -> RawCompletion:
        return RawCompletion(
            text=fx.classification().model_dump_json(),
            model=spec.model,
            usage=LLMUsage(
                tokens_in=self.tokens_in, tokens_out=self.tokens_out, cost_usd=self.cost_usd
            ),
        )


def _usage_client(
    *, tokens_in: int = 100, tokens_out: int = 50, cost_usd: float = 0.01
) -> LLMClient:
    return LLMClient(
        routing=ProviderRouting(default=ModelSpec(provider="openrouter", model="demo-model")),
        adapters={"openrouter": _UsageAdapter(tokens_in, tokens_out, cost_usd)},
    )


class _CallingClassificationStage:
    """A real stage 2: one model call, one warning, and a valid fixture back."""

    name = "educational-classification"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            await self._llm.parse(
                stage=self.name, output_model=Classification, system="s", user_content="u"
            )
            span.warn("classification ran thin on evidence")
            return {"classification": fx.classification().model_dump(mode="json")}


class _CallingThenFailingStage(_CallingClassificationStage):
    """Spends tokens, then dies — the case that used to report zero spend."""

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name):
            await self._llm.parse(
                stage=self.name, output_model=Classification, system="s", user_content="u"
            )
            raise RuntimeError("boom")


async def test_job_usage_is_populated_from_what_the_llm_actually_spent() -> None:
    store = InMemoryStore()
    job = await _seed(store)
    llm = _usage_client(tokens_in=100, tokens_out=50, cost_usd=0.01)

    stages = [
        STUB_STAGES[0],
        _CallingClassificationStage(llm),
        *STUB_STAGES[2:9],
        PublishingStage(),
    ]
    await run_job(store=store, job_id=job.id, stages=stages, llm=llm)

    saved = await store.get_job(job.id)
    assert saved is not None
    assert saved.tokens_used == 150, "GET /jobs must report what the run actually spent, not zero"
    assert saved.cost_usd == pytest.approx(0.01)
    assert any("classification ran thin on evidence" in w for w in saved.warnings), saved.warnings


async def test_job_usage_reflects_partial_spend_when_a_stage_fails_after_calling_the_model() -> (
    None
):
    """A job that dies mid-pipeline still spent what it spent before it died."""
    store = InMemoryStore()
    job = await _seed(store)
    llm = _usage_client(tokens_in=40, tokens_out=10, cost_usd=0.002)

    stages = [STUB_STAGES[0], _CallingThenFailingStage(llm)]
    with pytest.raises(RuntimeError):
        await run_job(store=store, job_id=job.id, stages=stages, llm=llm)

    saved = await store.get_job(job.id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.tokens_used == 50, "the failed stage's own spend must not be reported as zero"
    assert saved.cost_usd == pytest.approx(0.002)


# ══════════════════════════════════ 4. offloaded blocking work ═══════════════


async def test_publishing_offloads_pdf_rendering_from_the_event_loop() -> None:
    """fpdf2 is synchronous; stage 10 must not run it inline on the loop."""
    import time

    from stages.s10_publishing.render import RENDERERS

    original = dict(RENDERERS)

    def _blocking(_tkp: Any) -> bytes:
        time.sleep(0.05)
        return b"%PDF-1.7\n" + b"x" * 32

    for kind in list(RENDERERS):
        RENDERERS[kind] = _blocking  # type: ignore[assignment]

    ticks = 0

    async def _ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    try:
        store = InMemoryStore()
        job = await _seed(store)
        ticker = asyncio.create_task(_ticker())
        started = asyncio.get_event_loop().time()
        await run_job(
            store=store, job_id=job.id, stages=[*STUB_STAGES[:9], PublishingStage()], llm=None
        )
        elapsed = asyncio.get_event_loop().time() - started
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker
    finally:
        RENDERERS.clear()
        RENDERERS.update(original)

    # Five renders x 50ms of *synchronous* work is 250ms that, run inline,
    # would stall the loop solid — the ticker could only advance a handful of
    # times, once between renders. Offloaded to threads, the loop keeps
    # serving it on schedule throughout.
    assert ticks >= elapsed / 0.02, f"only {ticks} ticks fired in {elapsed:.2f}s — the loop stalled"


# ══════════════════════════════════ 5. stage 5 cancels its siblings ══════════


class _CancelSensingLLM:
    """One `LessonClose` call fails; every other stays in flight far longer
    than the failure takes to happen, so a sibling that is allowed to keep
    running has every opportunity to.
    """

    def __init__(self, delay: float = 0.03) -> None:
        self.delay = delay
        self.close_started = 0
        self.close_finished = 0
        self._raised = False

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        class _Result:
            degraded = False
            value = output_model.model_construct()

        if output_model.__name__ != "LessonClose":
            await asyncio.sleep(self.delay)
            return _Result()

        self.close_started += 1
        if not self._raised:
            self._raised = True
            await asyncio.sleep(self.delay)
            raise RuntimeError("boom")

        await asyncio.sleep(self.delay * 8)
        self.close_finished += 1
        return _Result()


def _classroom_state(periods: int = 6) -> dict[str, Any]:
    plan = fx.teaching_plan().model_dump(mode="json")
    template = plan["periods"][0]
    plan["periods"] = [
        {**template, "period_no": index + 1, "title": f"Period {index + 1}"}
        for index in range(periods)
    ]
    plan["total_periods"] = periods
    return {
        "knowledge": fx.knowledge_base().model_dump(mode="json"),
        "teaching_plan": plan,
        "classification": fx.classification().model_dump(mode="json"),
    }


async def test_a_failing_period_cancels_its_siblings_instead_of_letting_them_keep_calling() -> None:
    llm = _CancelSensingLLM(delay=0.03)
    stage = ClassroomContentStage(llm)  # type: ignore[arg-type]
    ctx = StageContext(job_id=uuid4(), options={})

    with pytest.raises(Exception):  # noqa: B017 - TaskGroup raises an ExceptionGroup
        await stage.run(ctx, _classroom_state(periods=6))

    assert llm.close_started >= 2, "not enough overlap in flight to prove anything"
    assert llm.close_finished == 0, (
        f"{llm.close_finished} sibling call(s) ran to completion after the first one "
        "failed — asyncio.gather does not cancel them, and each one is a billable "
        "model call for a job that had already failed"
    )


# ══════════════════════════ 4 (continued) — evaluations offload & locking ════


async def test_get_history_lazy_init_is_race_safe() -> None:
    """Concurrent cold requests must build exactly one store, not one each.

    A reviewer reproduced 5/5 concurrent cold requests building 7-8 separate
    stores and silently losing whichever ones lost the race to be the last
    assignment to the module-level singleton.
    """
    import api.routes.evaluations as evaluations_module

    original = evaluations_module._history
    evaluations_module._history = None
    try:

        async def cold_call() -> Any:
            return await asyncio.to_thread(evaluations_module.get_history)

        results = await asyncio.gather(*(cold_call() for _ in range(16)))
        assert len({id(r) for r in results}) == 1, (
            "concurrent cold requests built more than one store"
        )
    finally:
        evaluations_module._history = original


async def test_evaluation_requests_run_concurrently_without_losing_any() -> None:
    """The offload (item 4) and the connection lock it requires, together.

    ``evaluate_package``/``to_pdf`` now run on worker threads rather than the
    event loop. Nothing about that is worth anything if concurrent calls can
    corrupt or drop writes to the one sqlite connection the history wraps —
    which is exactly what an unserialized connection touched from multiple
    threads at once risks. Firing several concurrent, persisting evaluations
    for *distinct* packages and checking every single one landed is the
    functional proof that the lock is doing its job.

    Distinct packages, deliberately: ``evaluate_one`` derives ``run_id`` from
    the package id, and history recording is ``INSERT OR REPLACE`` keyed on
    that id — evaluating the *same* package eight times concurrently would
    collapse into one row by primary-key semantics alone, which would pass
    whether or not the connection were serialized and would prove nothing
    about the lock either way.
    """
    import httpx

    from api.deps import set_store
    from api.main import create_app
    from api.routes.evaluations import set_history
    from core.storage.base import PackageRecord
    from evals.store import EvaluationStore

    store = InMemoryStore()
    set_store(store)
    set_history(EvaluationStore())

    tkp = fx.teacher_knowledge_package().model_dump(mode="json")
    package_ids = [uuid4() for _ in range(8)]
    for package_id in package_ids:
        await store.save_package(
            PackageRecord(
                id=package_id,
                job_id=uuid4(),
                document_id=uuid4(),
                schema_version=str(tkp.get("schema_version") or ""),
                tkp=tkp,
                status="pass",
            )
        )

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *(client.get(f"/api/v1/packages/{pid}/evaluation") for pid in package_ids)
        )
        for response in responses:
            assert response.status_code == 200

        listed = (await client.get("/api/v1/evaluations")).json()

    assert listed["total"] == len(package_ids), (
        f"expected {len(package_ids)} recorded evaluations, found {listed['total']} — a "
        "lost write under concurrency is exactly what an unserialized sqlite connection risks"
    )
