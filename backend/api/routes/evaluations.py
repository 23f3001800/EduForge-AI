"""Evaluation endpoints: score a package, compare it, export the report.

The scoring itself lives in :mod:`evals.service`; these routes are transport.
That separation is what lets ``make evals`` and the dashboard report identical
numbers — the alternative, a route that assembles its own view of quality, is a
second rubric that drifts from the first and is never noticed.

**Chunks matter here.** Citation integrity — the one check that can catch a
fabricated quote — needs the source text the package was generated from. It is
recovered from the job's stage-1 checkpoint. When the checkpoint is gone (an old
job, a restarted in-memory store) the metric reports itself unmeasurable rather
than scoring zero, because "we could not check" is a different finding from "it
failed" and only one of them is a defect.

Evaluation is deterministic and cheap — no model calls, no network — so results
are recomputed per request rather than cached. The history that *is* stored is
the series, which is the part a cache could not reconstruct.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.deps import get_store
from core.storage.base import PackageRecord, Store
from evals.service import evaluate_package
from evals.store import EvaluationStore

router = APIRouter(tags=["evaluations"])

#: One process-wide history. In-memory by default, which means a restart loses
#: the series — stated in the payload rather than hidden, the same way `/stats`
#: reports `since_restart`. Pointing `EVAL_HISTORY_PATH` at a mounted volume
#: makes it durable without a code change.
_history: EvaluationStore | None = None


def get_history() -> EvaluationStore:
    global _history
    if _history is None:
        from core.config import get_settings

        path = getattr(get_settings(), "eval_history_path", None)
        _history = EvaluationStore(path)
    return _history


def set_history(store: EvaluationStore) -> None:
    """Swap the history store. Used by tests, which must not share a series."""
    global _history
    _history = store


async def _load(package_id: UUID, store: Store) -> PackageRecord:
    package = await store.get_package(package_id)
    if package is None:
        raise HTTPException(404, detail={"code": "package_not_found"})
    return package


async def _chunks_for(record: PackageRecord, store: Store) -> list[dict[str, Any]]:
    """The source chunks, from the job's stage-1 checkpoint, or none.

    Never raises. A missing checkpoint degrades the report — it does not fail
    it — and the metrics that needed the chunks say so themselves.
    """
    try:
        checkpoints = await store.get_checkpoints(record.job_id)
    except Exception:  # pragma: no cover - a store that cannot answer is not an error here
        return []
    stage1 = checkpoints.get("document-intelligence")
    if stage1 is None:
        return []
    chunks = stage1.output.get("chunks")
    return [c for c in chunks if isinstance(c, dict)] if isinstance(chunks, list) else []


@router.get("/packages/{package_id}/evaluation")
async def evaluate_one(
    package_id: UUID,
    persist: bool = Query(True, description="Append this run to the history series."),
    store: Store = Depends(get_store),
    history: EvaluationStore = Depends(get_history),
) -> dict[str, Any]:
    """Score one package: per-stage metrics, rubric, recommendations, benchmark."""
    record = await _load(package_id, store)
    chunks = await _chunks_for(record, store)
    return evaluate_package(
        record.tkp,
        chunks=chunks,
        run_id=str(package_id),
        store=history,
        persist=persist,
    )


@router.get("/evaluations")
async def list_evaluations(
    profile: str | None = Query(None),
    subject: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    history: EvaluationStore = Depends(get_history),
) -> dict[str, Any]:
    """The stored series, most recent first."""
    records = history.history(profile=profile, subject=subject, limit=limit)
    return {
        "durable": history.path is not None,
        "total": history.count(),
        "evaluations": [r.as_dict() for r in records],
    }


@router.get("/evaluations/benchmark")
async def get_benchmark(
    profile: str | None = Query(None),
    history: EvaluationStore = Depends(get_history),
) -> dict[str, Any]:
    """Score distribution across history, for positioning a single run.

    ``sufficient`` is the field to read first. Below the baseline minimum the
    percentiles are still returned — they are the honest summary of what little
    is on record — but nothing should be called a regression against them.
    """
    return history.benchmark(profile=profile)


@router.get("/evaluations/{run_id}")
async def get_evaluation(
    run_id: str,
    history: EvaluationStore = Depends(get_history),
) -> dict[str, Any]:
    record = history.get(run_id)
    if record is None:
        raise HTTPException(404, detail={"code": "evaluation_not_found"})
    return record.as_dict()


@router.get("/packages/{package_id}/evaluation.pdf")
async def export_evaluation_pdf(
    package_id: UUID,
    store: Store = Depends(get_store),
    history: EvaluationStore = Depends(get_history),
) -> Response:
    """The same report as a PDF, for attaching to a review.

    Rendered from the identical document the JSON endpoint returns — a PDF that
    recomputed anything could disagree with the screen it was exported from.
    """
    from evals.export import to_pdf

    record = await _load(package_id, store)
    chunks = await _chunks_for(record, store)
    document = evaluate_package(
        record.tkp, chunks=chunks, run_id=str(package_id), store=history, persist=False
    )
    return Response(
        content=to_pdf(document),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-{package_id}.pdf"',
        },
    )
