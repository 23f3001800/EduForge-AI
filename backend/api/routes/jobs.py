"""Job lifecycle and package reads.

``POST /jobs`` returns 202 immediately and never blocks on the pipeline. The work
outlives the request by design (docs/00 H-01) — a multi-minute run tied to an
open HTTP connection dies to the first proxy timeout.

For the skeleton the job is executed as an in-process background task. The real
worker claims jobs from the store with a lease, which is what allows it to run as
a separate process and to recover a crashed run. The API contract is identical
either way, so nothing here changes when the worker lands.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException

from api.deps import get_store
from contracts.jobs import JobOptions
from core.storage.base import JobRecord, Store
from stages.stubs import STUB_STAGES
from worker.runner import run_job

router = APIRouter(tags=["jobs"])

_background: set[asyncio.Task[Any]] = set()


class _CreateJob(JobOptions):
    """Options plus the document to run them against."""

    document_id: UUID


def _spawn(store: Store, job_id: UUID) -> None:
    async def _run() -> None:
        # Failures are already recorded on the job record by run_job; swallowing
        # here only stops an unretrieved-exception warning on the task.
        with contextlib.suppress(Exception):
            await run_job(store=store, job_id=job_id, stages=STUB_STAGES)

    task = asyncio.create_task(_run())
    # Hold a reference; without one the event loop may garbage-collect a running
    # task mid-flight and the job silently disappears.
    _background.add(task)
    task.add_done_callback(_background.discard)


@router.post("/jobs", status_code=202)
async def create_job(
    body: _CreateJob,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if await store.get_document(body.document_id) is None:
        raise HTTPException(404, detail={"code": "document_not_found"})

    options = body.model_dump(mode="json", exclude={"document_id"})
    candidate = JobRecord(
        id=uuid4(),
        document_id=body.document_id,
        options=options,
        idempotency_key=idempotency_key,
    )
    job = await store.create_job(candidate)

    if job.id == candidate.id:
        _spawn(store, job.id)

    return {
        "job_id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "events_url": f"/api/v1/jobs/{job.id}/events",
        "created_at": job.created_at.isoformat(),
        "deduplicated": job.id != candidate.id,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, store: Store = Depends(get_store)) -> dict[str, Any]:
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "job_not_found"})

    checkpoints = await store.get_checkpoints(job_id)
    return {
        "job_id": str(job.id),
        "document_id": str(job.document_id),
        "status": job.status,
        "current_stage": job.current_stage,
        "progress": job.progress,
        "completed_stages": sorted(checkpoints),
        "package_id": str(job.package_id) if job.package_id else None,
        "usage": {"tokens": job.tokens_used, "cost_usd": job.cost_usd},
        "warnings": job.warnings,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(
    job_id: UUID,
    from_stage: str | None = None,
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Resume from the first incomplete stage.

    Completed stages are restored from checkpoints, so a retry neither re-executes
    nor re-bills work that already succeeded (H-03).
    """
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "job_not_found"})
    if job.status not in {"failed", "cancelled", "succeeded_partial"}:
        raise HTTPException(
            409,
            detail={
                "code": "job_not_retryable",
                "message": f"status {job.status!r} cannot be retried",
            },
        )

    if from_stage:
        from contracts.primitives import STAGE_NAMES

        if from_stage not in STAGE_NAMES:
            raise HTTPException(422, detail={"code": "unknown_stage", "stage": from_stage})
        index = STAGE_NAMES.index(from_stage)  # type: ignore[arg-type]
        await store.clear_checkpoints(job_id, list(STAGE_NAMES[index:]))

    job.status = "queued"
    job.error = None
    await store.update_job(job)
    _spawn(store, job.id)

    return {"job_id": str(job.id), "status": job.status}


@router.get("/packages/{package_id}")
async def get_package(package_id: UUID, store: Store = Depends(get_store)) -> dict[str, Any]:
    package = await store.get_package(package_id)
    if package is None:
        raise HTTPException(404, detail={"code": "package_not_found"})
    return package.tkp


@router.get("/packages/{package_id}/validation")
async def get_validation(package_id: UUID, store: Store = Depends(get_store)) -> dict[str, Any]:
    package = await store.get_package(package_id)
    if package is None:
        raise HTTPException(404, detail={"code": "package_not_found"})
    return package.tkp.get("validation", {})
