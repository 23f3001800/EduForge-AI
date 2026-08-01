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

from contracts.primitives import SCHEMA_VERSION
from core.progress.emitter import ProgressEmitter
from core.storage.base import PackageRecord, Store
from orchestration.graph import PipelineResult, run_pipeline

__all__ = ["run_job"]


async def run_job(
    *,
    store: Store,
    job_id: UUID,
    stages: list[Any],
) -> PipelineResult:
    job = await store.get_job(job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")

    emit = ProgressEmitter(store, job_id)
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
        )
    except Exception as exc:  # the boundary that records failure before re-raising
        job.status = "failed"
        job.error = {"type": type(exc).__name__, "message": str(exc)}
        job.finished_at = datetime.now(UTC)
        await store.update_job(job)
        await emit(
            stage="failed",
            progress=job.progress,
            level="error",
            message=f"{type(exc).__name__}: {exc}",
        )
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

    job.package_id = record.id
    job.status = "succeeded"
    job.progress = 100
    job.current_stage = "publishing"
    job.finished_at = datetime.now(UTC)
    await store.update_job(job)

    await emit(
        stage="completed",
        progress=100,
        message="package published",
        package_id=str(record.id),
        status=validation_status,
    )
    return result
