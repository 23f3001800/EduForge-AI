"""Progress emission.

Persist first, notify second. A dropped notification costs a reader some latency;
a dropped *event* costs correctness, because the SSE endpoint replays from the
persisted log and a gap there is permanent.

Every emitted payload carries ``stage`` and ``progress`` — the two keys the
assignment specifies for FR-14. Anything else is additive.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from core.storage.base import JobEvent, Store

__all__ = ["ProgressEmitter"]


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
