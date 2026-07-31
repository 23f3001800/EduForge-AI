"""Stage 6's deterministic half — which activity, of what type, for how long.

The model writes the activity. It does not choose the *kind* of activity, and
that separation is what makes two properties provable rather than hoped for:

**Variety.** Left to itself a model returns five variations of "discuss in pairs"
across five periods and each one validates. Here the type for each slot is drawn
by round-robin from the profile's weighted pool, so a five-period package gets
five different types by construction, and a test can assert it.

**Profile conditioning.** The pool and its order come from
``pedagogy.registry`` — ``activity_weights`` in ``profiles.yaml``. A narrative
package opens with debate and role play, a quantitative one with problem sets and
experiments, and neither outcome involves a stage knowing what subject it is
looking at. There is no subject name anywhere in this module, and there cannot be
one: the only inputs are the plan and the profile strategy.

Round-robin rather than sampling by weight, deliberately. Sampling proportionally
gives the heaviest type twice in the first five slots and drops a type that a real
teacher would have wanted; the weights are better read as "which types belong to
this material, best first" than as a distribution to reproduce.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pedagogy.registry import ProfileStrategy

__all__ = ["PRIMARY_ACTIVITY_INDEX", "ActivitySlot", "activity_id", "plan_slots"]

#: Mirrors ``stages.s5_classroom_content.assembly``. Stage 5 writes
#: ``activity_refs`` before stage 6 has run, so the id scheme has to be known to
#: both — and the two stages may not import each other. The mirror is pinned by
#: ``test_activity_refs_resolve_against_generated_activities``; if one side
#: changes and the other does not, that test fails.
PRIMARY_ACTIVITY_INDEX = 1

#: A second activity is only worth the minutes when the period genuinely carries
#: enough distinct material to need one.
SECOND_ACTIVITY_CONCEPT_THRESHOLD = 3

#: Floor and share of the period an activity may occupy. An activity shorter than
#: this cannot be set up, run, and debriefed; one longer than the share leaves no
#: time to introduce or consolidate anything.
MIN_ACTIVITY_MINUTES = 8
MAX_ACTIVITY_SHARE = 0.45


def activity_id(period_no: int, index: int = PRIMARY_ACTIVITY_INDEX) -> str:
    """Deterministic activity id. Mirrored in ``stages/s5_classroom_content/assembly.py``."""
    return f"act_p{period_no}_{index}"


@dataclass(frozen=True, slots=True)
class ActivitySlot:
    """One activity's structure, decided before any model is called."""

    activity_id: str
    period_no: int
    activity_type: str
    duration_minutes: int
    period_title: str
    concept_ids: list[str] = field(default_factory=list)
    objective_ids: list[str] = field(default_factory=list)


def _activity_minutes(period: Mapping[str, Any], duration: int, share: int) -> int:
    """Minutes from the plan's own arc, not a guess.

    The period's middle slots are where practice lives — the first is the entry
    ticket and the last is consolidation — so the longest of those is the slot an
    activity actually occupies. Falling back to a share of the period only matters
    when the plan has fewer than three slots.
    """
    slots = list(period.get("time_allocation") or [])
    middle = slots[1:-1] if len(slots) >= 3 else []
    if middle:
        longest = max(int(slot.get("minutes") or 0) for slot in middle)
    else:
        longest = round(duration * MAX_ACTIVITY_SHARE)

    ceiling = max(MIN_ACTIVITY_MINUTES, int(duration * MAX_ACTIVITY_SHARE))
    return max(MIN_ACTIVITY_MINUTES, min(longest // share if share > 1 else longest, ceiling))


def type_cycle(strategy: ProfileStrategy, count: int) -> list[str]:
    """``count`` activity types, weighted pool first, no repeat until exhausted.

    The pool is every type the profile weights above zero, ordered by weight. A
    package shorter than the pool therefore never repeats a type at all.
    """
    pool = [
        name
        for name, weight in sorted(
            strategy.activity_weights.items(), key=lambda kv: (-kv[1], kv[0])
        )
        if weight > 0
    ]
    if not pool:  # a profile with no weights at all; the registry never ships one
        pool = ["group_discussion"]
    return [pool[index % len(pool)] for index in range(count)]


def plan_slots(plan: Mapping[str, Any], strategy: ProfileStrategy) -> list[ActivitySlot]:
    """Every activity the package will contain, structurally complete but unwritten."""
    periods: Sequence[Mapping[str, Any]] = plan.get("periods") or []
    duration = int(plan.get("period_duration_minutes") or 40)

    # A second activity needs both enough material to justify it and enough
    # minutes to run it. Splitting a 12-minute practice slot in two produces two
    # activities neither of which can be set up, run, and debriefed.
    counts = [
        2
        if (
            len(period.get("concept_ids") or []) >= SECOND_ACTIVITY_CONCEPT_THRESHOLD
            and _activity_minutes(period, duration, 1) >= 2 * MIN_ACTIVITY_MINUTES
        )
        else 1
        for period in periods
    ]
    types = type_cycle(strategy, sum(counts))

    slots: list[ActivitySlot] = []
    cursor = 0
    for period, per_period in zip(periods, counts, strict=True):
        period_no = int(period.get("period_no") or len(slots) + 1)
        minutes = _activity_minutes(period, duration, per_period)
        for offset in range(per_period):
            slots.append(
                ActivitySlot(
                    activity_id=activity_id(period_no, PRIMARY_ACTIVITY_INDEX + offset),
                    period_no=period_no,
                    activity_type=types[cursor],
                    duration_minutes=minutes,
                    period_title=str(period.get("title") or f"Period {period_no}"),
                    concept_ids=[str(cid) for cid in (period.get("concept_ids") or [])],
                    objective_ids=[str(oid) for oid in (period.get("objective_ids") or [])],
                )
            )
            cursor += 1
    return slots
