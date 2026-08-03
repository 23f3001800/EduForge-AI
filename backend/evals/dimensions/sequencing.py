"""Sequencing — prerequisites before dependents, load spread, an arc per period.

Order is not a matter of taste. If concept B is declared a prerequisite of C, then
a plan that teaches C first is wrong however good the prose around it is, and the
concept graph makes that checkable rather than arguable.

The other two checks are about what a teacher experiences rather than what a
validator sees. **Load balance**: three concepts in period one and one in period
two is a front-loaded package, and front-loading is the default failure of
generated plans because the model writes the interesting material first.
**Arc**: each period should activate prior knowledge, introduce, practise, check,
and consolidate — measured structurally (slot count, an activity, a checkpoint, a
script that reaches the bell) rather than by matching English words in headings,
which would break the first time a package is generated in another language.

Period *count* is not scored against a number. There is no correct number of
periods for a document, only a correct number given its concept load, so what is
scored is whether any single period is carrying more than a class can hold.

**On absent edges.** ``prerequisites_respected`` used to average an empty list to
1.0, which made deleting the entire concept graph the cheapest route to perfect
sequencing: no edges, no violations, full marks. Absence of a constraint is not
satisfaction of it. The metric is now reported at weight zero when there is
nothing to check, and the *presence* of an ordering claim is scored separately —
a package with several concepts and no declared prerequisite anywhere has an
order nobody can defend, and that is a real deficiency in stage 3's output rather
than a free pass for stage 4.
"""

from __future__ import annotations

from evals.context import EvalContext, coerce_int
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "sequencing"
LABEL = "Sequencing and load"
WEIGHT = 0.06
METHOD = "deterministic"

#: At or above this many concepts *spread across more than one period*, the plan
#: has made an ordering decision, and a package that declares no prerequisite
#: relation anywhere is asserting that every idea is independent of every other.
#: Occasionally true; usually a graph the extractor did not build. Below it —
#: one concept, or everything taught in a single period — no ordering was chosen
#: and there is nothing to defend.
MIN_CONCEPTS_EXPECTING_AN_ORDER = 2

#: How close the teacher script must come to the period's actual length before it
#: counts as covering the lesson. A script that ends at minute 22 of a 40-minute
#: period leaves the teacher to improvise the rest.
SCRIPT_COVERAGE = 0.85


def score(ctx: EvalContext) -> DimensionScore:
    periods = ctx.periods
    expects = ctx.expectations
    findings: list[Finding] = []

    if not periods:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            metrics=(Metric("plan_present", 0.0, 1.0, "no periods planned"),),
            findings=(
                Finding("SEQ_NO_PLAN", "/teaching_plan/periods", "the plan contains no periods"),
            ),
        )

    period_of = ctx.period_of_concept()

    # --- prerequisites before dependents --------------------------------------
    edges = [
        edge
        for edge in (ctx.concept_graph.get("edges") or [])
        if str(edge.get("relation")) == "prerequisite_of"
    ]
    ordered: list[float] = []
    for edge in edges:
        before, after = str(edge.get("from_id")), str(edge.get("to_id"))
        if before not in period_of or after not in period_of:
            continue  # an untaught concept is a coverage hole, not an ordering one
        respected = period_of[before] <= period_of[after]
        ordered.append(1.0 if respected else 0.0)
        if not respected:
            findings.append(
                Finding(
                    "SEQ_PREREQUISITE_INVERTED",
                    "/teaching_plan/periods",
                    f"{ctx.concept_name(after)!r} is taught in period {period_of[after]} but "
                    f"its prerequisite {ctx.concept_name(before)!r} not until period "
                    f"{period_of[before]}",
                )
            )
    prerequisite_score = mean(ordered)

    # Is there an ordering claim at all? Scored separately from whether it was
    # honoured, because "no edges" and "no violations" must not be the same
    # number. Only asserted where a graph is genuinely owed: a two-concept
    # package with one edge, or a one-concept package with none, is not a defect.
    concept_count = len(ctx.concept_ids)
    if concept_count >= MIN_CONCEPTS_EXPECTING_AN_ORDER and len(periods) > 1:
        graph_present = 1.0 if edges else 0.0
        # Weighted level with `prerequisites_respected` on purpose: declaring an
        # order and honouring it are worth the same, because a package that
        # declares none cannot be caught breaking one.
        graph_weight = 0.35
        if not edges:
            findings.append(
                Finding(
                    "SEQ_NO_PREREQUISITE_GRAPH",
                    "/knowledge/concept_graph/edges",
                    f"{concept_count} concepts are taught in a fixed order and not one "
                    "prerequisite relation is declared between them; the order the plan "
                    "chose cannot be checked, defended, or re-derived",
                )
            )
    else:
        graph_present = 1.0
        graph_weight = 0.0

    # --- load balance ---------------------------------------------------------
    counts = [len(period.get("concept_ids") or []) for period in periods]
    ideal = sum(counts) / len(counts)
    imbalance = (max(counts) - min(counts)) / ideal if ideal > 0 else 0.0
    balance = max(0.0, 1.0 - imbalance / 2)
    if imbalance > 1.0:
        findings.append(
            Finding(
                "SEQ_UNBALANCED_LOAD",
                "/teaching_plan/periods",
                f"concepts per period run {min(counts)}-{max(counts)} against an average of "
                f"{ideal:.1f}; the heavy period will overrun and the light one will drift",
            )
        )

    within: list[float] = []
    for period, count in zip(periods, counts, strict=True):
        ok = expects.min_concepts_per_period <= count <= expects.max_concepts_per_period
        within.append(1.0 if ok else 0.0)
        if not ok:
            heavy = count > expects.max_concepts_per_period
            findings.append(
                Finding(
                    "SEQ_PERIOD_OVERLOADED" if heavy else "SEQ_PERIOD_EMPTY",
                    f"/teaching_plan/periods/{periods.index(period)}",
                    f"period {period.get('period_no')} carries {count} concepts; the "
                    f"workable range for this profile is {expects.min_concepts_per_period}"
                    f"-{expects.max_concepts_per_period}",
                )
            )

    # --- arc ------------------------------------------------------------------
    content_by_period = {coerce_int(c.get("period_no")): c for c in ctx.classroom_content}
    activity_periods = {coerce_int(a.get("period_no")) for a in ctx.activities}
    duration = ctx.period_minutes or 0

    arcs: list[float] = []
    for period in periods:
        number = coerce_int(period.get("period_no"))
        content = content_by_period.get(number, {})
        script = list(content.get("teacher_script") or [])
        reach = max((coerce_int(s.get("minute_end")) for s in script), default=0)

        beats = {
            "slots": len(period.get("time_allocation") or []) >= expects.min_time_slots_per_period,
            "practice": number in activity_periods or bool(content.get("activity_refs")),
            "check": bool(content.get("checkpoint_questions")),
            "consolidation": duration <= 0 or reach >= duration * SCRIPT_COVERAGE,
        }
        arcs.append(sum(beats.values()) / len(beats))
        missing = sorted(name for name, ok in beats.items() if not ok)
        if missing:
            findings.append(
                Finding(
                    "SEQ_INCOMPLETE_ARC",
                    f"/classroom_content/{number - 1}",
                    f"period {number} is missing {', '.join(missing)}"
                    + (
                        f" (script reaches minute {reach} of {duration})"
                        if "consolidation" in missing
                        else ""
                    ),
                )
            )

    metrics = (
        Metric(
            "prerequisites_respected",
            prerequisite_score,
            0.35 if ordered else 0.0,
            f"{len(ordered)} prerequisite edge(s) checked"
            if ordered
            else "no prerequisite edge connects two scheduled concepts; reported, not "
            "scored — an unconstrained order is not a correct one",
        ),
        Metric(
            "prerequisite_graph_present",
            graph_present,
            graph_weight,
            "the package declares an ordering it can be held to"
            if graph_weight
            else f"{len(ctx.concept_ids)} concept(s) across {len(periods)} period(s): no "
            "ordering decision was made, so none is owed a justification",
        ),
        Metric("load_balance", balance, 0.15, f"concepts per period: {counts}"),
        Metric("period_load", mean(within), 0.15, "no period over- or under-filled"),
        Metric("period_arc", mean(arcs), 0.25, "introduce, practise, check, consolidate"),
        Metric(
            "periods_per_concept",
            0.0,
            0.0,
            f"{len(periods)} period(s) for {len(ctx.concept_ids)} concepts "
            "(reported, not scored: there is no correct ratio)",
        ),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
