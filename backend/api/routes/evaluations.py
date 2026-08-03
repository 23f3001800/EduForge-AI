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

import asyncio
import threading
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

#: Guards the lazy construction of `_history` above. Two concurrent cold
#: requests can both read `_history is None` as true before either acquires
#: this, race to construct their own `EvaluationStore`, and the second
#: assignment silently replaces the first — along with any run the first
#: store had already recorded between the two constructions. Reproduced 5/5
#: under concurrent cold requests before this lock existed.
_init_lock = threading.Lock()

#: Guards the single `sqlite3.Connection` `EvaluationStore` wraps
#: (`check_same_thread=False`). That flag only disables sqlite3's own
#: same-thread assertion; it does not make the connection safe for concurrent
#: use from multiple threads at once. `evaluate_package`/`to_pdf` below run on
#: a worker thread (`asyncio.to_thread`) precisely because they are CPU-bound
#: enough to block the event loop — which means they can now run at the same
#: instant as a plain `async def` route reading `history` synchronously on the
#: loop thread. Serializing every call that touches `history` behind this lock
#: is what keeps that safe; without it two threads can interleave writes to
#: the same sqlite connection and corrupt it.
_db_lock = threading.Lock()


def get_history() -> EvaluationStore:
    global _history
    if _history is None:
        with _init_lock:
            if _history is None:  # re-check inside the lock, see comment above
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


def _evaluate_locked(
    tkp: dict[str, Any],
    chunks: list[dict[str, Any]],
    run_id: str,
    history: EvaluationStore,
    persist: bool,
) -> dict[str, Any]:
    """``evaluate_package`` under the connection lock, for the worker thread.

    Scoring itself needs no lock — it touches no shared state — but
    ``persist=True`` calls ``history.record()``, which does, and the lock has
    to span the whole call rather than wrap ``history`` internally: this
    module does not own ``evals/store.py`` and must not change it, so
    serialization is enforced here, at every call site that reaches the
    connection.
    """
    with _db_lock:
        return evaluate_package(tkp, chunks=chunks, run_id=run_id, store=history, persist=persist)


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
    # Off the event loop: scoring walks every stage of the package, and stage 10
    # proved fpdf2-scale work inline here would stall every other job's SSE
    # stream and every other request in the process for the duration.
    return await asyncio.to_thread(
        _evaluate_locked, record.tkp, chunks, str(package_id), history, persist
    )


async def evaluate_sample(record: PackageRecord, history: EvaluationStore) -> dict[str, Any]:
    """Score a seeded sample into the history at startup.

    Shares the worker-thread and lock discipline of the route above rather than
    reimplementing it — the point of exposing this is that startup scoring and
    on-demand scoring cannot drift apart. No chunks: a sample has no stage-1
    checkpoint to resolve them from.
    """
    return await asyncio.to_thread(
        _evaluate_locked, record.tkp, [], str(record.id), history, True
    )


@router.get("/evaluations")
async def list_evaluations(
    profile: str | None = Query(None),
    subject: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    history: EvaluationStore = Depends(get_history),
) -> dict[str, Any]:
    """The stored series, most recent first."""
    with _db_lock:
        records = history.history(profile=profile, subject=subject, limit=limit)
        total = history.count()
    return {
        "durable": history.path is not None,
        "total": total,
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
    with _db_lock:
        return history.benchmark(profile=profile)


@router.get("/evaluations/{run_id}")
async def get_evaluation(
    run_id: str,
    history: EvaluationStore = Depends(get_history),
) -> dict[str, Any]:
    with _db_lock:
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
    # persist=False, so this call never touches the sqlite connection — but it
    # still runs on a worker thread, both for consistency with `evaluate_one`
    # and because `to_pdf` right below it is the actually expensive half: it
    # drives the same fpdf2 renderer stage 10 offloads for the same reason.
    document = await asyncio.to_thread(
        _evaluate_locked, record.tkp, chunks, str(package_id), history, False
    )
    pdf_bytes = await asyncio.to_thread(to_pdf, document)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="evaluation-{package_id}.pdf"',
        },
    )
