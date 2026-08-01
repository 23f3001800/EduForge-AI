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

from pydantic import model_validator

from contracts.jobs import STAGE_PROGRESS_WEIGHTS
from contracts.primitives import STAGE_NAMES, StageName, StrictModel

__all__ = [
    "Decision",
    "Draft",
    "Stage",
    "StageContext",
    "StageSpan",
    "cumulative_progress",
]


class Draft(StrictModel):
    """Base for model-facing draft types: lenient in, strict out.

    Unknown keys are dropped rather than rejected — models echo back the ids and
    types they were shown, and losing a whole generated item to a courtesy key is
    a bad trade. Everything here survives to be re-validated against the real
    contract, which is where strictness belongs.

    It lives in ``stages.base`` rather than in whichever stage needed it first,
    because the alternative is one stage importing another's schemas module and
    the independence rule exists precisely to stop that.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_unknown_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key in cls.model_fields}
        return value


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
    #: ``async (kind, payload) -> uri``. How a stage persists bytes it produced.
    #:
    #: A callable rather than the ``Store`` itself, so a stage can write a blob
    #: without gaining the ability to read jobs, mutate checkpoints, or publish
    #: packages — and so a test can pass a dict-backed sink instead of a store.
    #: ``None`` means nothing is collecting artifacts, which is why stage 10
    #: treats it as "render and report" rather than an error.
    put_artifact: Callable[[str, bytes], Any] | None = None
    #: ``(stage, duration_ms, warnings, decisions) -> None``. Called by
    #: ``stage_span`` when a stage finishes.
    #:
    #: A sink rather than a return value, so every stage contributes its
    #: warnings and decisions without a single stage having to know it is being
    #: observed — and so adding a stage cannot forget to.
    record: Callable[..., Any] | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    """One choice the pipeline made, and the reason it made it.

    The deterministic halves of these stages decide a great deal — how many
    periods, which assessment kinds, how severe a gap is — and a teacher looking
    at the result has no way to tell a derived number from an arbitrary one.
    "5 periods" invites the question; "5 periods, because 9 concepts at core
    weighting need 210 minutes and a period is 40" answers it.

    Recorded rather than logged, because it belongs in the package a teacher
    reads, not only in a file an operator greps.
    """

    what: str
    because: str


class StageSpan:
    """Progress reporting for one stage execution."""

    def __init__(self, ctx: StageContext, stage: StageName) -> None:
        self.ctx = ctx
        self.stage = stage
        self.started = time.monotonic()
        self.warnings: list[str] = []
        self.decisions: list[Decision] = []

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

    def decide(self, what: str, because: str) -> None:
        """Record a decision and its reason, for the package's decision log."""
        self.decisions.append(Decision(what=what, because=because))

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
        # Reported in `finally`, so a stage that raised still surrenders what it
        # decided and warned about before it failed. That is precisely the run
        # where the reasoning is worth the most.
        if ctx.record is not None:
            ctx.record(
                stage=stage,
                duration_ms=span.duration_ms,
                warnings=list(span.warnings),
                decisions=[{"what": d.what, "because": d.because} for d in span.decisions],
            )


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
