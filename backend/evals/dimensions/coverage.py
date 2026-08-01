"""Coverage — is everything extracted actually taught, practised, and assessed?

Three separate questions that a single "coverage" number usually blurs together:

* **Taught** — a period claims the concept.
* **Practised** — an activity or a checkpoint question puts the student to work on
  it. A concept that is lectured and never rehearsed is a concept the class will
  not retain, and this is the check most packages quietly fail.
* **Assessed** — an item in the bank carries marks for it.

And the objective-side pair: every objective planned into a period, and every
objective measured by something. An objective nothing measures is decoration.

Objective-to-item linkage has to be inferred through concept ids, because
``AssessmentItem`` carries ``concept_ids`` but no ``objective_ids``. That is a
real limitation of the contract rather than of this metric — noted in the report,
since the fix belongs upstream.

Profile conditioning enters once, and decisively: ``required_knowledge_fields``
comes from the pedagogy registry, so a narrative package is asked for concepts and
examples while a quantitative one is additionally asked for formulae. Missing
formulae in narrative content is not a coverage hole and is not counted as one.
"""

from __future__ import annotations

from evals.context import EvalContext
from evals.types import DimensionScore, Finding, Metric

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "coverage"
LABEL = "Coverage"
WEIGHT = 0.15
METHOD = "deterministic"


def _share(hit: set[str], total: set[str]) -> float:
    return len(hit & total) / len(total) if total else 1.0


def score(ctx: EvalContext) -> DimensionScore:
    findings: list[Finding] = []
    concepts = ctx.concept_ids

    if not concepts:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            metrics=(Metric("concepts_present", 0.0, 1.0, "no concepts extracted"),),
            findings=(
                Finding(
                    "COV_NO_CONCEPTS",
                    "/knowledge/concepts",
                    "the package extracted no concepts, so there is nothing for the "
                    "plan, the activities, or the bank to cover",
                ),
            ),
        )

    # --- taught ---------------------------------------------------------------
    taught = {str(cid) for period in ctx.periods for cid in (period.get("concept_ids") or [])}
    taught_share = _share(taught, concepts)
    for cid in sorted(concepts - taught):
        findings.append(
            Finding(
                "COV_CONCEPT_UNTAUGHT",
                "/teaching_plan/periods",
                f"{ctx.concept_name(cid)!r} ({cid}) is extracted but no period teaches it",
            )
        )

    # --- practised ------------------------------------------------------------
    practised = {str(cid) for a in ctx.activities for cid in (a.get("concept_ids") or [])}
    for content in ctx.classroom_content:
        for question in content.get("checkpoint_questions") or []:
            practised.update(str(cid) for cid in (question.get("concept_ids") or []))
    practised_share = _share(practised, concepts)
    for cid in sorted(concepts - practised):
        findings.append(
            Finding(
                "COV_CONCEPT_UNPRACTISED",
                "/activities",
                f"{ctx.concept_name(cid)!r} ({cid}) is taught but no activity or "
                "checkpoint puts a student to work on it",
            )
        )

    # --- assessed -------------------------------------------------------------
    assessed = {str(cid) for item in ctx.items for cid in (item.get("concept_ids") or [])}
    assessed_share = _share(assessed, concepts)
    for cid in sorted(concepts - assessed):
        findings.append(
            Finding(
                "COV_CONCEPT_UNASSESSED",
                "/assessments/items",
                f"{ctx.concept_name(cid)!r} ({cid}) carries no marks anywhere in the bank",
            )
        )

    # --- objectives -----------------------------------------------------------
    objectives = ctx.objectives
    objective_ids = {str(o.get("objective_id")) for o in objectives if o.get("objective_id")}
    planned = {str(oid) for period in ctx.periods for oid in (period.get("objective_ids") or [])}
    planned_share = _share(planned, objective_ids)
    for oid in sorted(objective_ids - planned):
        findings.append(
            Finding(
                "COV_OBJECTIVE_UNPLANNED",
                "/teaching_plan/periods",
                f"objective {oid} is stated but no period is aimed at it",
            )
        )

    item_concepts = [{str(c) for c in (item.get("concept_ids") or [])} for item in ctx.items]
    measured: set[str] = set()
    for objective in objectives:
        oid = str(objective.get("objective_id") or "")
        ids = {str(c) for c in (objective.get("concept_ids") or [])}
        if ids and any(ids & covered for covered in item_concepts):
            measured.add(oid)
        else:
            findings.append(
                Finding(
                    "COV_OBJECTIVE_UNASSESSED",
                    "/assessments/items",
                    f"objective {oid} is measured by no item "
                    f"({'it links to no concept' if not ids else 'no item shares its concepts'}); "
                    "an objective nothing measures is decoration",
                )
            )
    measured_share = _share(measured, objective_ids)

    # --- what this profile owes ----------------------------------------------
    required = ctx.expectations.required_knowledge_fields
    present = []
    for field in required:
        filled = bool(ctx.knowledge.get(field))
        present.append(1.0 if filled else 0.0)
        if not filled:
            findings.append(
                Finding(
                    "COV_PROFILE_FIELD_MISSING",
                    f"/knowledge/{field}",
                    f"the {ctx.profile} profile requires {field!r} and the package has none",
                )
            )
    required_share = sum(present) / len(present) if present else 1.0

    # --- marks follow importance ---------------------------------------------
    marks_by_concept: dict[str, int] = {}
    for item in ctx.items:
        for cid in item.get("concept_ids") or []:
            marks_by_concept[str(cid)] = marks_by_concept.get(str(cid), 0) + int(
                item.get("marks") or 0
            )
    core = {str(c.get("concept_id")) for c in ctx.concepts if str(c.get("importance")) == "core"}
    core_marked = [1.0 if marks_by_concept.get(cid, 0) > 0 else 0.0 for cid in sorted(core)]
    core_share = sum(core_marked) / len(core_marked) if core_marked else 1.0
    for cid in sorted(core):
        if marks_by_concept.get(cid, 0) == 0:
            findings.append(
                Finding(
                    "COV_CORE_CONCEPT_UNMARKED",
                    "/assessments/blueprint/marks_by_concept",
                    f"{ctx.concept_name(cid)!r} is marked core but carries zero marks",
                )
            )

    # --- misconceptions reach the gap analysis --------------------------------
    gap_concepts = {str(cid) for gap in ctx.learning_gaps for cid in (gap.get("concept_ids") or [])}
    misconceptions = ctx.misconceptions
    carried = [
        1.0 if {str(c) for c in (m.get("concept_ids") or [])} & gap_concepts else 0.0
        for m in misconceptions
    ]
    carried_share = sum(carried) / len(carried) if carried else 1.0
    if misconceptions and carried_share < 1.0:
        findings.append(
            Finding(
                "COV_MISCONCEPTION_DROPPED",
                "/learning_gaps",
                f"{carried.count(0.0)} of {len(misconceptions)} extracted misconceptions "
                "reach no learning gap, so no diagnostic would ever surface them",
            )
        )

    metrics = (
        Metric("concepts_taught", taught_share, 0.16, "a period claims each concept"),
        Metric("concepts_practised", practised_share, 0.14, "an activity or checkpoint uses it"),
        Metric("concepts_assessed", assessed_share, 0.16, "the bank carries marks for it"),
        Metric("objectives_planned", planned_share, 0.12, "a period is aimed at it"),
        Metric("objectives_assessed", measured_share, 0.18, "an item measures it"),
        Metric(
            "profile_required_fields",
            required_share,
            0.12,
            f"{ctx.profile} requires {', '.join(required) or 'nothing in particular'}",
        ),
        Metric("core_concepts_marked", core_share, 0.06, "core concepts carry marks"),
        Metric("misconceptions_carried", carried_share, 0.06, "extracted errors reach a gap"),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
