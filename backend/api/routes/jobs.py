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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from api.deps import RosterBuilder, get_app_settings, get_roster_builder, get_store
from contracts.jobs import JobOptions
from core.config import Settings
from core.progress.emitter import ProgressEmitter
from core.storage.base import JobRecord, Store
from worker.runner import run_job

API_PREFIX = "/api/v1"

router = APIRouter(tags=["jobs"])

_background: set[asyncio.Task[Any]] = set()


class _CreateJob(JobOptions):
    """Options plus the document to run them against."""

    document_id: UUID


async def _fail_job(store: Store, job_id: UUID, exc: Exception) -> None:
    """Record a pre-pipeline failure the same way ``run_job`` records its own."""
    job = await store.get_job(job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = {"type": type(exc).__name__, "message": str(exc)}
    job.finished_at = datetime.now(UTC)
    await store.update_job(job)
    await ProgressEmitter(store, job_id)(
        stage="failed", progress=0, level="error", message=f"{type(exc).__name__}: {exc}"
    )


def _spawn(store: Store, job: JobRecord, settings: Settings, roster: RosterBuilder) -> None:
    async def _run() -> None:
        try:
            stages = await roster(store, job, settings)
        except Exception as exc:
            # Roster construction happens before run_job, so nothing else would
            # record this. Left unhandled it is the worst failure mode available:
            # the job sits at `queued` forever and the client's SSE stream waits
            # on events that will never arrive.
            await _fail_job(store, job.id, exc)
            return
        # From here run_job owns the lifecycle and records its own failures;
        # suppressing only silences an unretrieved-exception warning.
        with contextlib.suppress(Exception):
            await run_job(store=store, job_id=job.id, stages=stages)

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
    settings: Settings = Depends(get_app_settings),
    roster: RosterBuilder = Depends(get_roster_builder),
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
        _spawn(store, job, settings, roster)

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
    settings: Settings = Depends(get_app_settings),
    roster: RosterBuilder = Depends(get_roster_builder),
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
    _spawn(store, job, settings, roster)

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


#: What each artifact kind is served as, and what a browser should call it.
ARTIFACT_MEDIA: dict[str, tuple[str, str]] = {
    "tkp_json": ("application/json", "teacher-knowledge-package.json"),
    "lesson_plan_pdf": ("application/pdf", "lesson-plan.pdf"),
    "teacher_guide_pdf": ("application/pdf", "teacher-guide.pdf"),
    "assessment_book_pdf": ("application/pdf", "assessment-book.pdf"),
    "markdown_bundle": ("text/markdown; charset=utf-8", "teaching-materials.md"),
}


@router.get("/packages/{package_id}/artifacts")
async def list_artifacts(package_id: UUID, store: Store = Depends(get_store)) -> dict[str, Any]:
    """What was actually rendered for this package, with a download url each.

    ``bytes`` is read from the stored blob rather than remembered at render time,
    so a listing can never advertise a size for something that is no longer
    there — the row says ``failed`` instead, and the UI can grey it out rather
    than offering a link that 404s.
    """
    package = await store.get_package(package_id)
    if package is None:
        raise HTTPException(404, detail={"code": "package_not_found"})

    artifacts: list[dict[str, Any]] = []
    for kind, uri in sorted(package.artifacts.items()):
        mime, _ = ARTIFACT_MEDIA.get(kind, ("application/octet-stream", kind))
        payload = await store.get_blob(uri)
        artifacts.append(
            {
                "kind": kind,
                "mime": mime,
                "bytes": len(payload) if payload else 0,
                "status": "ready" if payload else "failed",
                "url": f"{API_PREFIX}/packages/{package_id}/artifacts/{kind}",
            }
        )
    return {"artifacts": artifacts}


@router.get("/packages/{package_id}/artifacts/{kind}")
async def download_artifact(
    package_id: UUID, kind: str, store: Store = Depends(get_store)
) -> Response:
    package = await store.get_package(package_id)
    if package is None:
        raise HTTPException(404, detail={"code": "package_not_found"})

    uri = package.artifacts.get(kind)
    payload = await store.get_blob(uri) if uri else None
    if payload is None:
        raise HTTPException(
            404,
            detail={
                "code": "artifact_not_found",
                "message": f"{kind!r} was not rendered for this package.",
                "details": {"available": sorted(package.artifacts)},
            },
        )

    mime, filename = ARTIFACT_MEDIA.get(kind, ("application/octet-stream", kind))
    return Response(
        content=payload,
        media_type=mime,
        # `attachment` so a PDF downloads under a meaningful name instead of
        # opening inline as a uuid the teacher then has to rename.
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
