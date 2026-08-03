"""Bloom distribution — does the bank span levels, or is it all recall?

Measured in **marks, not items**. Twelve one-mark recall MCQs and one twelve-mark
essay is not a balanced bank, and counting items says it is. Marks are what a
student's grade is actually made of, so marks are what the distribution is
computed over.

The profile conditioning here is the whole reason this dimension is safe to run on
humanities content. "Higher order" is measured from a floor the profile declares:
quantitative material earns it at ``apply``, because a multi-step problem *is* the
thinking; interpretive material earns it at ``analyze``, because there is nothing
to calculate and demanding ``apply`` would mark down a well-built essay bank for
being the wrong shape. Both routes reach the same score for equally good work —
that property is asserted directly in the test suite.

The recall ceiling is a cap, not a target. A bank with no ``remember`` items is
fine; recall is what entry and exit tickets are for.
"""

from __future__ import annotations

from collections import Counter

from evals.context import EvalContext, coerce_int
from evals.lexicons import bloom_index
from evals.types import DimensionScore, Finding, Metric

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "bloom"
LABEL = "Bloom distribution"
WEIGHT = 0.05
METHOD = "deterministic"

#: A level holding less than this share of the marks is a token gesture, not
#: coverage of that level. Counting it would let one stray item claim a spread the
#: bank does not have.
PRESENCE_SHARE = 0.05

#: A four-option MCQ can honestly test application. It cannot test `create`, and a
#: bank that claims it does has inflated its own profile. Mirrors
#: ``stages/s7_assessments/blueprint.MCQ_BLOOM_CEILING`` — stated here rather than
#: imported, so the eval does not inherit the generator's opinion of itself.
MCQ_BLOOM_CEILING = "apply"


def score(ctx: EvalContext) -> DimensionScore:
    items = ctx.items
    expects = ctx.expectations

    if not items:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            applicable=False,
            reason="no assessment items to distribute",
        )

    marks_by_level: Counter[str] = Counter()
    for item in items:
        marks_by_level[str(item.get("bloom_level") or "")] += coerce_int(item.get("marks"))
    total_marks = sum(marks_by_level.values()) or 1

    findings: list[Finding] = []

    # --- spread ---------------------------------------------------------------
    present = [
        level for level, marks in marks_by_level.items() if marks / total_marks >= PRESENCE_SHARE
    ]
    distinct = len(present)
    spread = min(1.0, distinct / max(1, expects.min_distinct_bloom_levels))
    if distinct < expects.min_distinct_bloom_levels:
        findings.append(
            Finding(
                "BLOOM_NARROW_SPREAD",
                "/assessments/items",
                f"marks land on {distinct} Bloom level(s) ({', '.join(sorted(present))}); "
                f"the {expects.profile} profile expects at least "
                f"{expects.min_distinct_bloom_levels}",
            )
        )

    # --- recall ceiling -------------------------------------------------------
    recall_share = marks_by_level.get("remember", 0) / total_marks
    cap = expects.max_recall_mark_share
    if recall_share <= cap:
        recall = 1.0
    else:
        recall = max(0.0, (1.0 - recall_share) / max(1e-6, 1.0 - cap))
        findings.append(
            Finding(
                "BLOOM_RECALL_HEAVY",
                "/assessments/items",
                f"{recall_share:.0%} of marks are pure recall against a "
                f"{cap:.0%} ceiling for the {expects.profile} profile; the bank tests "
                "memory where it should be testing reasoning",
            )
        )

    # --- higher-order floor ---------------------------------------------------
    floor_index = bloom_index(expects.higher_order_from)
    higher_marks = sum(
        marks for level, marks in marks_by_level.items() if bloom_index(level) >= floor_index >= 0
    )
    higher_share = higher_marks / total_marks
    target = expects.min_higher_order_mark_share
    higher = min(1.0, higher_share / target) if target > 0 else 1.0
    if higher_share < target:
        findings.append(
            Finding(
                "BLOOM_LOW_HIGHER_ORDER",
                "/assessments/items",
                f"{higher_share:.0%} of marks sit at {expects.higher_order_from} or above, "
                f"against a {target:.0%} floor for this profile",
            )
        )

    # --- credible claims ------------------------------------------------------
    ceiling = bloom_index(MCQ_BLOOM_CEILING)
    mcqs = [i for i in items if str(i.get("kind")) == "mcq"]
    overclaimed = [i for i in mcqs if bloom_index(str(i.get("bloom_level") or "")) > ceiling >= 0]
    credible = 1.0 - (len(overclaimed) / len(mcqs)) if mcqs else 1.0
    for item in overclaimed:
        findings.append(
            Finding(
                "BLOOM_MCQ_OVERCLAIM",
                f"/assessments/items/{items.index(item)}",
                f"a four-option MCQ is tagged {item.get('bloom_level')!r}; nothing above "
                f"{MCQ_BLOOM_CEILING!r} can be tested by choosing one of four",
            )
        )

    # --- objectives ladder ----------------------------------------------------
    objective_levels = {str(o.get("bloom_level") or "") for o in ctx.objectives}
    enough_objectives = len(ctx.objectives) >= expects.objective_spread_threshold
    if enough_objectives and len(objective_levels) < 2:
        objective_spread = 0.3
        findings.append(
            Finding(
                "BLOOM_FLAT_OBJECTIVES",
                "/knowledge/learning_objectives",
                f"all {len(ctx.objectives)} objectives sit on one rung "
                f"({', '.join(objective_levels)}); a package with no progression in "
                "demand has no arc across its periods",
            )
        )
    else:
        objective_spread = 1.0

    metrics = (
        Metric("level_spread", spread, 0.25, f"{distinct} level(s) carry real marks"),
        Metric("recall_ceiling", recall, 0.25, f"{recall_share:.0%} of marks are recall"),
        Metric(
            "higher_order_floor",
            higher,
            0.25,
            f"{higher_share:.0%} of marks at {expects.higher_order_from}+",
        ),
        Metric("credible_claims", credible, 0.15, "no MCQ claims a level it cannot test"),
        Metric("objective_ladder", objective_spread, 0.10, "objectives span more than one level"),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
