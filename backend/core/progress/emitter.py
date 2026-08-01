"""Progress emission.

Persist first, notify second. A dropped notification costs a reader some latency;
a dropped *event* costs correctness, because the SSE endpoint replays from the
persisted log and a gap there is permanent.

Every emitted payload carries ``stage`` and ``progress`` — the two keys the
assignment specifies for FR-14. Anything else is additive.

The same call also advances the job record. Those are two views of one fact, and
letting them drift produced a job that streamed correct progress over SSE while
``GET /jobs/{id}`` reported ``0%`` and ``current_stage: null`` for six minutes —
a client that polls, or that reads the snapshot once before subscribing, sees a
run that looks hung while it is working.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from contracts.primitives import STAGE_NAMES
from core.storage.base import JobEvent, Store

__all__ = ["ProgressEmitter"]

#: Once a job reaches one of these the runner owns its fields; a late event must
#: not drag a finished job back to "running at 87%".
_TERMINAL = frozenset({"succeeded", "succeeded_partial", "failed", "cancelled"})


class ProgressEmitter:
    def __init__(self, store: Store, job_id: UUID) -> None:
        self._store = store
        self._job_id = job_id
        self._last_progress = -1

    async def __call__(
        self,
        *,
        stage: str,
        progress: int,
        message: str | None = None,
        level: str = "info",
        **data: Any,
    ) -> None:
        # Progress must never appear to move backwards. Fan-out completions can
        # arrive out of order, and a bar that jumps 60 -> 55 reads as a fault.
        progress = max(progress, self._last_progress) if level == "info" else progress
        self._last_progress = max(self._last_progress, progress)

        # Persist the event first: the SSE endpoint replays from this log, and a
        # gap there is permanent in a way a stale snapshot is not.
        await self._store.append_event(
            JobEvent(
                seq=0,  # assigned by the store, monotonic
                job_id=self._job_id,
                stage=stage,
                progress=progress,
                level=level,
                message=message,
                data=data,
            )
        )
        await self._advance_job(stage, progress)

    async def _advance_job(self, stage: str, progress: int) -> None:
        """Bring the job snapshot up to date with the event just written."""
        job = await self._store.get_job(self._job_id)
        if job is None or job.status in _TERMINAL:
            return

        changed = False
        if progress > job.progress:
            job.progress = progress
            changed = True
        # `stage` is also used for the terminal markers "queued", "completed" and
        # "failed", which are not stages and must not land in `current_stage`.
        if stage in STAGE_NAMES and job.current_stage != stage:
            job.current_stage = stage  # type: ignore[assignment]
            changed = True

        if changed:
            await self._store.update_job(job)
