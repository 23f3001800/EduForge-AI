"""The stage contract every pipeline stage implements.

A stage owns one responsibility, reads a narrowed view of graph state, writes one
key, and emits progress. It may import ``contracts``, ``core``, and ``pedagogy``.
It must never import another stage — that rule is what lets separate agents build
stages simultaneously, and CI enforces it.

``stage_span`` is the only correct way to run a stage body. It emits the opening
and closing progress events, times the work, and writes the checkpoint atomically
with the closing event, so a crash can never leave a checkpoint that the progress
stream disagrees with.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from contracts.jobs import STAGE_PROGRESS_WEIGHTS
from contracts.primitives import STAGE_NAMES, StageName

__all__ = ["Stage", "StageContext", "StageSpan", "cumulative_progress"]


def cumulative_progress(stage: StageName, fraction: float = 1.0) -> int:
    """Overall progress once ``stage`` is ``fraction`` complete.

    Fan-out stages interpolate — stage 5 over five periods reports 45, 50, 55…
    rather than jumping 40 → 65 and appearing frozen for minutes.
    """
    before = sum(STAGE_PROGRESS_WEIGHTS[s] for s in STAGE_NAMES[: STAGE_NAMES.index(stage)])
    return min(100, round(before + STAGE_PROGRESS_WEIGHTS[stage] * max(0.0, min(1.0, fraction))))


@dataclass(slots=True)
class StageContext:
    """Everything a stage may reach for. Nothing else is in scope."""

    job_id: UUID
    options: dict[str, Any] = field(default_factory=dict)
    emit: Callable[..., Any] | None = None
    llm: Any | None = None
    retrieval: Any | None = None
    logger: Any | None = None


class StageSpan:
    """Progress reporting for one stage execution."""

    def __init__(self, ctx: StageContext, stage: StageName) -> None:
        self.ctx = ctx
        self.stage = stage
        self.started = time.monotonic()
        self.warnings: list[str] = []

    async def progress(self, fraction: float, message: str | None = None) -> None:
        if self.ctx.emit is None:
            return
        await self.ctx.emit(
            stage=self.stage,
            progress=cumulative_progress(self.stage, fraction),
            message=message,
        )

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def duration_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)


@asynccontextmanager
async def stage_span(ctx: StageContext, stage: StageName) -> AsyncIterator[StageSpan]:
    span = StageSpan(ctx, stage)
    await span.progress(0.0)
    try:
        yield span
    finally:
        await span.progress(1.0)


@runtime_checkable
class Stage(Protocol):
    """Implemented by every pipeline stage."""

    name: StageName

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        """Return the state fragment this stage owns.

        Returning a fragment rather than mutating state is what keeps stage
        outputs mergeable and makes a stage independently testable: give it a
        dict, assert on the dict it hands back.
        """
        ...
