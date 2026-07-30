"""Stage 4 contracts — the multi-period teaching plan.

Period count is *derived* from concept load and period duration (docs/03 § 4.3),
never fixed at 5. The PDF's "e.g. 5, 40-minute periods" is an example, and a
hardcoded 5 is wrong for both a 3-page handout and a 40-page chapter.

Ordering is deterministic: stage 4 topologically sorts the prerequisite DAG in
code and partitions it into balanced bands. The model titles the bands, writes the
rationale, and allocates time within them — it does not get to reorder
prerequisites. That split is what makes cross-period consistency verifiable in
stage 9 instead of merely hoped for.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from contracts.primitives import Identifier, StrictModel

__all__ = ["Period", "TeachingPlan", "TimeSlot"]

#: Tolerance on a period's time budget. Teaching plans that do not add up to the
#: bell are not usable, but demanding exactness produces absurd 37-minute slots.
TIME_TOLERANCE = 0.05


class TimeSlot(StrictModel):
    label: str = Field(min_length=1, description='e.g. "Entry ticket", "Guided practice".')
    minutes: int = Field(ge=1)


class Period(StrictModel):
    """One teachable session."""

    period_no: int = Field(ge=1)
    title: str = Field(min_length=1)
    objective_ids: list[Identifier] = Field(
        min_length=1, description="Subset of the knowledge base's learning objectives."
    )
    concept_ids: list[Identifier] = Field(
        min_length=1,
        description="Concepts taught in this period. Each concept belongs to exactly "
        "one period across the plan — stage 9 enforces that globally.",
    )
    time_allocation: list[TimeSlot] = Field(min_length=1)
    sequence_rationale: str = Field(
        min_length=1,
        description="Why this period sits here — what it builds on, what it enables.",
    )

    @property
    def allocated_minutes(self) -> int:
        return sum(slot.minutes for slot in self.time_allocation)


class TeachingPlan(StrictModel):
    total_periods: int = Field(ge=1, le=20)
    period_duration_minutes: int = Field(ge=5, le=240)
    periods: list[Period] = Field(min_length=1)
    unmapped_objective_ids: list[Identifier] = Field(
        default_factory=list,
        description="Objectives no period covers. Reported honestly rather than "
        "dropped silently, so the gap is visible in the validation report.",
    )

    @model_validator(mode="after")
    def _periods_are_coherent(self) -> TeachingPlan:
        if len(self.periods) != self.total_periods:
            raise ValueError(
                f"total_periods={self.total_periods} but {len(self.periods)} periods supplied"
            )

        numbers = [p.period_no for p in self.periods]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"period_no must be contiguous from 1; got {numbers}")

        # A concept taught in two periods is the classic incoherence this plan
        # exists to prevent, so it fails here rather than surviving to stage 9.
        seen: dict[str, int] = {}
        for period in self.periods:
            for cid in period.concept_ids:
                if cid in seen:
                    raise ValueError(
                        f"concept {cid!r} assigned to periods {seen[cid]} and "
                        f"{period.period_no}; each concept belongs to exactly one period"
                    )
                seen[cid] = period.period_no

        lo = self.period_duration_minutes * (1 - TIME_TOLERANCE)
        hi = self.period_duration_minutes * (1 + TIME_TOLERANCE)
        for period in self.periods:
            if not lo <= period.allocated_minutes <= hi:
                raise ValueError(
                    f"period {period.period_no} allocates {period.allocated_minutes} min, "
                    f"outside {self.period_duration_minutes} min ±{int(TIME_TOLERANCE * 100)}%"
                )
        return self
