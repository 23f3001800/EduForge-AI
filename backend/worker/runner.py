"""Job execution.

The worker claims a job, runs the pipeline, and records the outcome. It is the
only component that mutates job status, which keeps the lifecycle in one place
instead of scattered across ten stages.

Failure policy: a job that dies mid-pipeline keeps its checkpoints. Retry resumes
at the first incomplete stage and neither re-executes nor re-bills what already
succeeded — the reason checkpointing exists at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from contracts.jobs import JobStatus
from contracts.primitives import SCHEMA_VERSION
from core.obs import metrics
from core.obs.logging import get_logger
from core.progress.emitter import ProgressEmitter
from core.storage.base import PackageRecord, Store
from orchestration.graph import PipelineResult, run_pipeline

__all__ = ["run_job"]

logger = get_logger("worker.runner")


def _usage_and_warnings(
    llm: Any | None, reports: list[dict[str, Any]]
) -> tuple[int, float, list[str]]:
    """What this job actually spent and warned about, from what it produced.

    ``llm.usage`` is the source of truth for tokens and cost: it accounts for
    every attempt including retries that spent tokens and produced nothing,
    which is exactly what a job's own accounting must not hide (the same
    reasoning stage reports already follow, see ``orchestration.graph._usage_of``).
    It stays in scope through both the success and the failure path, so a job
    that dies mid-pipeline still reports what the stages that *did* run cost —
    ``llm=None`` only happens when a roster genuinely made no model calls.

    Warnings are not on the client at all, so they come from the per-stage
    reports instead, each one prefixed with the stage that raised it.
    """
    if llm is not None:
        usage = llm.usage
        tokens_used = usage.tokens_in + usage.tokens_out
        cost_usd = usage.cost_usd
    else:
        tokens_used = sum(
            int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in reports
        )
        cost_usd = sum(float(r.get("cost_usd") or 0.0) for r in reports)

    warnings = [
        f"{r.get('stage', 'unknown')}: {message}"
        for r in reports
        for message in (r.get("warnings") or [])
    ]
    return tokens_used, round(cost_usd, 6), warnings


async def _reports_from_checkpoints(store: Store, job_id: UUID) -> list[dict[str, Any]]:
    """Every stage report recorded so far, read back from checkpoints.

    Used on the failure path, where there is no ``result.state`` to read from —
    the pipeline raised before ``run_pipeline`` could return one — but the
    stages that completed before the failure already checkpointed their
    ``stage_reports`` fragment, and that is what a partially-run job actually
    cost.
    """
    checkpoints = await store.get_checkpoints(job_id)
    return [
        report
        for checkpoint in checkpoints.values()
        for report in (checkpoint.output.get("stage_reports") or [])
    ]


async def run_job(
    *,
    store: Store,
    job_id: UUID,
    stages: list[Any],
    llm: Any | None = None,
) -> PipelineResult:
    job = await store.get_job(job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")

    emit = ProgressEmitter(store, job_id)
    logger.info("job started", extra={"document_id": str(job.document_id)})
    job.status = "running"
    job.started_at = job.started_at or datetime.now(UTC)
    await store.update_job(job)
    await emit(stage="queued", progress=0, message="job started")

    try:
        result = await run_pipeline(
            job_id=job_id,
            document_id=job.document_id,
            options=job.options,
            stages=stages,
            store=store,
            emit=emit,
            llm=llm,
        )
    except Exception as exc:  # the boundary that records failure before re-raising
        metrics.record_job("failed")
        logger.exception("job failed")
        reports = await _reports_from_checkpoints(store, job_id)
        tokens_used, cost_usd, warnings = _usage_and_warnings(llm, reports)

        # Persist the terminal event before the job flips to a terminal status.
        # The SSE endpoint replays from the event log; a reader that polls
        # GET /jobs right after `update_job` returns must always find the
        # terminal event already there, never a terminal status with nothing to
        # show for it. Reversing this order is exactly the race this ordering
        # exists to close (see the identical comment on the success path below).
        await emit(
            stage="failed",
            progress=job.progress,
            level="error",
            message=f"{type(exc).__name__}: {exc}",
        )
        job.status = "failed"
        job.error = {"type": type(exc).__name__, "message": str(exc)}
        job.tokens_used = tokens_used
        job.cost_usd = cost_usd
        job.warnings = warnings
        job.finished_at = datetime.now(UTC)
        await store.update_job(job)
        raise

    package_payload = result.package
    if package_payload is None:
        raise RuntimeError("pipeline finished without producing a package")

    validation_status = (package_payload.get("validation") or {}).get("status", "pass")
    record = PackageRecord(
        id=uuid4(),
        job_id=job_id,
        document_id=job.document_id,
        schema_version=package_payload.get("schema_version", SCHEMA_VERSION),
        tkp=package_payload,
        status=validation_status,
        artifacts=dict(result.state.get("artifacts") or {}),
    )
    await store.save_package(record)

    reports = result.state.get("stage_reports") or []
    tokens_used, cost_usd, warnings = _usage_and_warnings(llm, reports)

    # A package that failed validation is not a package a teacher can trust
    # unreviewed: `succeeded` promises the run is done and clean, so anything
    # short of a clean pass reports `succeeded_partial` instead. That is also
    # what makes it retryable — `succeeded` 409s on retry, and a package stuck
    # at "fail" with no route back to "clean" cannot be repaired.
    final_status: JobStatus = "succeeded" if validation_status == "pass" else "succeeded_partial"
    metrics.record_job(final_status)
    logger.info("job finished", extra={"package_id": str(record.id), "status": final_status})

    # Persist the terminal event before the job flips to a terminal status
    # (job.status = ...; store.update_job(...)). `_advance_job` never sets
    # `status`, only `progress`/`current_stage`, so calling `emit` first cannot
    # race the fields set below — but it does mean an SSE reader can never
    # observe a terminal job snapshot before the terminal event that explains
    # it exists in the log it replays from.
    await emit(
        stage="completed",
        progress=100,
        message="package published",
        package_id=str(record.id),
        status=validation_status,
    )

    job.package_id = record.id
    job.status = final_status
    job.progress = 100
    job.current_stage = "publishing"
    job.tokens_used = tokens_used
    job.cost_usd = cost_usd
    job.warnings = warnings
    job.finished_at = datetime.now(UTC)
    await store.update_job(job)

    return result
