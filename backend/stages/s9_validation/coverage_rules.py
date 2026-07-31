"""Rule class 2 — coverage (SRS-6.2) and profile-conditioned completeness.

Two questions, both answered by walking the raw state dicts directly rather than
through validated contract objects — so this still produces a full report even
when a section failed schema conformance:

1. Did the plan actually teach what extraction found, and did assessment
   actually cover what the plan set out to teach?
2. Did the package deliver what *this document's pedagogy profile* demands —
   and, just as important, did it correctly deliver *nothing* where the profile
   demands nothing?

``AssessmentItem`` carries no ``objective_id`` field (contracts.assessment), so
"objective N was assessed" is necessarily determined by concept overlap: an
objective is assessed if some assessment item's ``concept_ids`` intersects the
objective's own ``concept_ids``. An objective with no concept ids of its own
cannot be verified this way and is reported unassessed — that is itself useful
information about the objective, not a false positive.
"""

from __future__ import annotations

from typing import Any

from contracts.validation import CoverageReport
from pedagogy.registry import ProfileStrategy
from stages.s9_validation.issues import IssueDict, make_issue

__all__ = ["check_coverage", "check_profile_requirements"]


def check_coverage(
    *,
    knowledge: dict[str, Any],
    teaching_plan: dict[str, Any],
    assessments: dict[str, Any],
) -> tuple[CoverageReport, list[IssueDict]]:
    issues: list[IssueDict] = []

    concepts = knowledge.get("concepts") or []
    objectives = knowledge.get("learning_objectives") or []
    periods = teaching_plan.get("periods") or []
    items = assessments.get("items") or []

    taught_concept_ids: set[str] = {
        cid for period in periods for cid in (period.get("concept_ids") or [])
    }
    planned_objective_ids: set[str] = {
        oid for period in periods for oid in (period.get("objective_ids") or [])
    }
    assessed_concept_ids: set[str] = {
        cid for item in items for cid in (item.get("concept_ids") or [])
    }

    untaught_concept_ids: list[str] = []
    for index, concept in enumerate(concepts):
        concept_id = concept.get("concept_id")
        if concept_id not in taught_concept_ids:
            untaught_concept_ids.append(concept_id)
            issues.append(
                make_issue(
                    code="COVERAGE_CONCEPT_UNTAUGHT",
                    message=f"concept {concept_id!r} is never taught in any period",
                    path=f"/knowledge/concepts/{index}",
                    stage="teaching-planner",
                )
            )

    unassessed_objective_ids: list[str] = []
    objectives_planned = 0
    objectives_assessed = 0
    for index, objective in enumerate(objectives):
        objective_id = objective.get("objective_id")
        objective_concepts = set(objective.get("concept_ids") or [])

        planned = objective_id in planned_objective_ids
        assessed = bool(objective_concepts & assessed_concept_ids)
        objectives_planned += int(planned)
        objectives_assessed += int(assessed)

        if not planned:
            issues.append(
                make_issue(
                    code="COVERAGE_OBJECTIVE_UNPLANNED",
                    message=f"objective {objective_id!r} is not mapped to any period",
                    path=f"/knowledge/learning_objectives/{index}",
                    stage="teaching-planner",
                )
            )
        if not assessed:
            issues.append(
                make_issue(
                    code="COVERAGE_OBJECTIVE_UNASSESSED",
                    message=f"objective {objective_id!r} is not covered by any assessment item",
                    path=f"/knowledge/learning_objectives/{index}",
                    stage="assessment-generation",
                )
            )
        if not (planned and assessed):
            unassessed_objective_ids.append(objective_id)

    report = CoverageReport(
        concepts_total=len(concepts),
        concepts_taught=len(concepts) - len(untaught_concept_ids),
        objectives_total=len(objectives),
        objectives_planned=objectives_planned,
        objectives_assessed=objectives_assessed,
        untaught_concept_ids=untaught_concept_ids,
        unassessed_objective_ids=unassessed_objective_ids,
    )
    return report, issues


def check_profile_requirements(
    *,
    knowledge: dict[str, Any],
    assessments: dict[str, Any],
    strategy: ProfileStrategy,
) -> list[IssueDict]:
    """The versatility gate (H-07, Q1).

    ``strategy.required_fields`` and ``strategy.expects_numerical_items`` are the
    *entire* condition. A narrative profile's ``required_fields`` never includes
    ``formulae`` and its ``expects_numerical_items`` is ``False``, so this
    function does not even look at those fields for a narrative document — the
    absence of formulae there is not a gap being forgiven, it is a check that was
    never asked. That is what keeps this rule from ever failing a humanities
    document for lacking numbers.
    """
    issues: list[IssueDict] = []

    for field in strategy.required_fields:
        if not (knowledge.get(field) or []):
            issues.append(
                make_issue(
                    code="COVERAGE_PROFILE_REQUIRED_FIELD_EMPTY",
                    message=(
                        f"pedagogy profile {strategy.name!r} expects `{field}` "
                        "and the knowledge base has none"
                    ),
                    path=f"/knowledge/{field}",
                    stage="knowledge-extraction",
                    severity="warning",
                )
            )

    if strategy.expects_numerical_items:
        items = assessments.get("items") or []
        if not any(item.get("kind") == "numerical" for item in items):
            issues.append(
                make_issue(
                    code="COVERAGE_PROFILE_NUMERICAL_ITEMS_MISSING",
                    message=(
                        f"pedagogy profile {strategy.name!r} expects at least one "
                        "numerical assessment item and none were produced"
                    ),
                    path="/assessments/items",
                    stage="assessment-generation",
                    severity="warning",
                )
            )

    return issues
