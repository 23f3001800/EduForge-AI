"""Pipeline integration — the MS-1 gate.

These prove the guarantees that make a twelve-minute job survivable: progress
reaches the client, a crash does not discard completed work, and the published
package is a real TKP rather than a shape that merely looks like one.

No model calls anywhere. Stages return fixtures, which is the point — the
orchestration must be provable without spending a token.
"""

from __future__ import annotations

import contextlib
from typing import Any
from uuid import UUID, uuid4

import pytest

from contracts import TeacherKnowledgePackage
from contracts.primitives import STAGE_NAMES
from core.storage.base import DocumentRecord, JobRecord
from core.storage.memory import InMemoryStore
from stages.base import StageContext, cumulative_progress, stage_span
from stages.stubs import STUB_STAGES
from worker.runner import run_job


async def _seed(store: InMemoryStore, **job_kwargs: Any) -> tuple[UUID, UUID]:
    doc = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="a" * 64,
            filename="newtons-laws.pdf",
            mime="application/pdf",
            size_bytes=184_320,
            blob_uri="mem://newtons-laws.pdf",
        )
    )
    job = await store.create_job(
        JobRecord(
            id=uuid4(),
            document_id=doc.id,
            options={"period_duration_minutes": 40},
            **job_kwargs,
        )
    )
    return job.id, doc.id


# ---------------------------------------------------------------- happy path


async def test_pipeline_runs_every_stage_and_publishes() -> None:
    store = InMemoryStore()
    job_id, _ = await _seed(store)

    result = await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    assert result.executed == list(STAGE_NAMES)
    assert result.skipped == []
    job = await store.get_job(job_id)
    assert job is not None
    assert job.status == "succeeded"
    assert job.package_id is not None


async def test_published_package_is_a_valid_tkp() -> None:
    """The skeleton must emit the real artifact, not a plausible-looking dict."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    job = await store.get_job(job_id)
    assert job is not None and job.package_id is not None
    package = await store.get_package(job.package_id)
    assert package is not None

    TeacherKnowledgePackage.model_validate(package.tkp)


# ------------------------------------------------------------------ progress


async def test_every_event_carries_stage_and_progress() -> None:
    """The exact wire contract the assignment specifies for FR-14."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    events = await store.events_since(job_id)
    assert events
    for event in events:
        assert isinstance(event.stage, str) and event.stage
        assert isinstance(event.progress, int)
        assert 0 <= event.progress <= 100


async def test_progress_reaches_one_hundred_and_never_goes_backwards() -> None:
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    progress = [e.progress for e in await store.events_since(job_id)]
    assert progress[-1] == 100
    assert progress == sorted(progress), f"progress went backwards: {progress}"


async def test_every_stage_reports_progress() -> None:
    """A stage that runs silently looks like a hang to whoever is watching."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    seen = {e.stage for e in await store.events_since(job_id)}
    assert set(STAGE_NAMES) <= seen


async def test_event_sequence_numbers_are_strictly_monotonic() -> None:
    """`seq` is the SSE event id; a duplicate or gap breaks Last-Event-ID replay."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    seqs = [e.seq for e in await store.events_since(job_id)]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))


async def test_fanout_stage_interpolates_rather_than_jumping() -> None:
    """Stage 5 is the longest stage; a frozen bar there reads as a crash."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    lesson = [e for e in await store.events_since(job_id) if e.stage == "lesson-generation"]
    per_period = [e for e in lesson if e.message and "period" in e.message]
    assert len(per_period) >= 2, "expected one progress event per period"
    assert len({e.progress for e in per_period}) > 1, "progress did not move between periods"


def test_cumulative_progress_spans_the_whole_range() -> None:
    assert cumulative_progress(STAGE_NAMES[0], 0.0) == 0
    assert cumulative_progress(STAGE_NAMES[-1], 1.0) == 100
    ordered = [cumulative_progress(s, 1.0) for s in STAGE_NAMES]
    assert ordered == sorted(ordered)


# ------------------------------------------------------- durability & resume


async def test_resume_skips_completed_stages_and_does_not_rerun_them() -> None:
    """NFR-02. The whole reason checkpoints exist: a crash must not cost the run."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)

    # First attempt dies partway through.
    class BoomError(Exception):
        pass

    class ExplodingStage:
        name = "teaching-planner"

        async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
            raise BoomError("simulated worker crash")

    partial = [*STUB_STAGES[:3], ExplodingStage()]
    with pytest.raises(BoomError):
        await run_job(store=store, job_id=job_id, stages=partial)

    checkpoints = await store.get_checkpoints(job_id)
    assert set(checkpoints) == set(STAGE_NAMES[:3])

    job = await store.get_job(job_id)
    assert job is not None and job.status == "failed"
    job.status = "queued"
    await store.update_job(job)

    result = await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    assert result.skipped == list(STAGE_NAMES[:3]), "completed stages were re-executed"
    assert "teaching-planner" in result.executed
    job = await store.get_job(job_id)
    assert job is not None and job.status == "succeeded"


async def test_resume_restores_every_key_a_stage_wrote_not_just_the_mapped_one() -> None:
    """Stage 1 writes `structured_document` AND `chunks`.

    ``STAGE_STATE_KEY`` names the key a stage owns for invalidation, which is not
    the same as everything it writes. Restoring only the mapped key left stage 3
    verifying citations against no chunks after any retry — invisible while every
    stage was a single-key stub, and wrong the moment stage 1 became real.
    """
    store = InMemoryStore()
    job_id, _ = await _seed(store)

    class TwoKeyStage:
        name = "document-intelligence"

        async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
            return {
                "structured_document": {"doc_id": "d1"},
                "chunks": [{"chunk_id": "c_0001", "text": "grounding depends on this"}],
            }

    seen: dict[str, Any] = {}

    class Downstream:
        name = "educational-classification"

        async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
            seen["chunks"] = state.get("chunks")
            return {"classification": {"subject": "x"}}

    # First run completes stage 1 and checkpoints both keys. Neither roster here
    # ends in publishing, so run_job raises after the stages have run — which is
    # irrelevant to what this test asserts.
    with contextlib.suppress(RuntimeError):
        await run_job(store=store, job_id=job_id, stages=[TwoKeyStage()])
    checkpoint = (await store.get_checkpoints(job_id))["document-intelligence"]
    assert set(checkpoint.output) == {"structured_document", "chunks"}

    # Second run restores stage 1 from that checkpoint; the next stage must still
    # see the chunks.
    job = await store.get_job(job_id)
    assert job is not None
    job.status = "queued"
    await store.update_job(job)
    with contextlib.suppress(RuntimeError):  # no publishing stage in this roster
        await run_job(store=store, job_id=job_id, stages=[TwoKeyStage(), Downstream()])

    assert seen["chunks"], "chunks were dropped when stage 1 was restored"


async def test_targeted_regeneration_reruns_only_the_named_stages() -> None:
    """Validation-driven repair must not restart the pipeline from stage 1."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)
    await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    await store.clear_checkpoints(job_id, ["assessment-generation", "publishing"])

    job = await store.get_job(job_id)
    assert job is not None
    job.status = "queued"
    await store.update_job(job)

    result = await run_job(store=store, job_id=job_id, stages=STUB_STAGES)
    assert set(result.executed) == {"assessment-generation", "publishing"}


async def test_a_crashed_worker_lease_is_reclaimable() -> None:
    """Lease expiry is the recovery mechanism; without it a crash strands the job."""
    store = InMemoryStore()
    job_id, _ = await _seed(store)

    first = await store.claim_job("worker-a", lease_seconds=0)
    assert first is not None and first.id == job_id

    second = await store.claim_job("worker-b")
    assert second is not None and second.id == job_id
    assert second.worker_id == "worker-b"


# ------------------------------------------------------------- idempotency


async def test_duplicate_upload_returns_the_existing_document() -> None:
    """An evaluator uploading the same file twice must not create two documents."""
    store = InMemoryStore()
    first = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="b" * 64,
            filename="a.pdf",
            mime="application/pdf",
            size_bytes=10,
            blob_uri="mem://a",
        )
    )
    second = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="b" * 64,
            filename="a-copy.pdf",
            mime="application/pdf",
            size_bytes=10,
            blob_uri="mem://a-copy",
        )
    )
    assert first.id == second.id


async def test_repeated_job_creation_with_the_same_key_returns_one_job() -> None:
    """A double-clicked Generate button must not start two twelve-minute runs."""
    store = InMemoryStore()
    doc = await store.add_document(
        DocumentRecord(
            id=uuid4(),
            sha256="c" * 64,
            filename="a.pdf",
            mime="application/pdf",
            size_bytes=10,
            blob_uri="mem://a",
        )
    )
    first = await store.create_job(
        JobRecord(id=uuid4(), document_id=doc.id, idempotency_key="key-1")
    )
    second = await store.create_job(
        JobRecord(id=uuid4(), document_id=doc.id, idempotency_key="key-1")
    )
    assert first.id == second.id


# ------------------------------------------------------------- stage hygiene


async def test_stage_span_reports_both_ends_even_when_the_body_raises() -> None:
    """Otherwise a failing stage leaves the bar stuck with no closing event."""
    emitted: list[tuple[str, int]] = []

    async def emit(*, stage: str, progress: int, **_: Any) -> None:
        emitted.append((stage, progress))

    ctx = StageContext(job_id=uuid4(), emit=emit)
    with pytest.raises(ValueError, match="boom"):
        async with stage_span(ctx, "validation"):
            raise ValueError("boom")

    assert len(emitted) == 2
    assert emitted[0][1] < emitted[1][1]


def test_stub_roster_covers_every_stage_exactly_once() -> None:
    names = [s.name for s in STUB_STAGES]
    assert names == list(STAGE_NAMES)
