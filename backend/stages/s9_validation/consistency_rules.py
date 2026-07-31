"""Rule class 3 — consistency (SRS-6.3).

``contracts.plan.TeachingPlan`` and ``contracts.tkp.TeacherKnowledgePackage``
already refuse to *construct* a plan with a concept in two periods, a period
outside its time tolerance, or an activity reference that does not resolve
(docs/03 § "cross-reference validators are the last line of defence"). That
overlap with this module is deliberate, not redundant: those validators raise
and abort construction, which is right for a machine boundary but wrong for a
report a teacher needs to read. This module walks the same raw state and turns
each finding into a ``ConsistencyReport`` entry and a ``ValidationIssue`` with an
owning stage, and it does this whether or not the corresponding section is
itself schema-valid — a check here must not depend on ``schema_rules`` having
succeeded first.

The one check with no contract-level counterpart is prerequisite ordering:
nothing at construction time cross-references ``concept_graph`` against period
assignment, so this is the only place a prerequisite inversion is ever caught.
"""

from __future__ import annotations

from typing import Any

from contracts.plan import TIME_TOLERANCE
from contracts.validation import ConsistencyReport
from stages.s9_validation.issues import IssueDict, make_issue

__all__ = ["check_consistency"]


def _duplicate_concepts(periods: list[dict[str, Any]]) -> tuple[list[str], list[IssueDict]]:
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    issues: list[IssueDict] = []

    for period in periods:
        period_no = period.get("period_no")
        for concept_id in period.get("concept_ids") or []:
            first_period = seen.get(concept_id)
            if first_period is not None and first_period != period_no:
                duplicates.append(concept_id)
                issues.append(
                    make_issue(
                        code="CONSISTENCY_DUPLICATE_CONCEPT",
                        message=(
                            f"concept {concept_id!r} is taught in both period "
                            f"{first_period} and period {period_no}; a concept must "
                            "belong to exactly one period"
                        ),
                        path="/teaching_plan/periods",
                        stage="teaching-planner",
                    )
                )
            else:
                seen.setdefault(concept_id, period_no)

    return sorted(set(duplicates)), issues


def _prerequisite_violations(
    knowledge: dict[str, Any], periods: list[dict[str, Any]]
) -> tuple[list[str], list[IssueDict]]:
    period_of: dict[str, int] = {
        concept_id: period.get("period_no")
        for period in periods
        for concept_id in (period.get("concept_ids") or [])
    }
    edges = (knowledge.get("concept_graph") or {}).get("edges") or []

    messages: list[str] = []
    issues: list[IssueDict] = []
    for edge in edges:
        if edge.get("relation") != "prerequisite_of":
            continue
        prerequisite_id = edge.get("from_id")
        dependent_id = edge.get("to_id")
        prereq_period = period_of.get(prerequisite_id)
        dependent_period = period_of.get(dependent_id)
        if prereq_period is None or dependent_period is None:
            continue  # unassigned concepts are reported by the coverage rule instead

        # A period can legitimately teach a prerequisite and its dependent in the
        # same session, so only a *later* prerequisite is a violation.
        if dependent_period < prereq_period:
            message = (
                f"concept {dependent_id!r} taught in period {dependent_period} but "
                f"its prerequisite {prerequisite_id!r} is taught in period {prereq_period}"
            )
            messages.append(message)
            issues.append(
                make_issue(
                    code="CONSISTENCY_PREREQUISITE_VIOLATION",
                    message=message,
                    path="/teaching_plan/periods",
                    stage="teaching-planner",
                )
            )

    return messages, issues


def _timing(
    periods: list[dict[str, Any]], period_duration_minutes: int
) -> tuple[bool, list[IssueDict]]:
    if not period_duration_minutes:
        return True, []

    lo = period_duration_minutes * (1 - TIME_TOLERANCE)
    hi = period_duration_minutes * (1 + TIME_TOLERANCE)
    issues: list[IssueDict] = []
    ok = True

    for period in periods:
        allocated = sum(slot.get("minutes", 0) for slot in period.get("time_allocation") or [])
        if not lo <= allocated <= hi:
            ok = False
            issues.append(
                make_issue(
                    code="CONSISTENCY_TIMING_MISMATCH",
                    message=(
                        f"period {period.get('period_no')} allocates {allocated} min, "
                        f"outside {period_duration_minutes} min "
                        f"±{int(TIME_TOLERANCE * 100)}%"
                    ),
                    path="/teaching_plan/periods",
                    stage="teaching-planner",
                )
            )

    return ok, issues


def _dangling_activity_refs(
    period_contents: list[dict[str, Any]], activities: list[dict[str, Any]]
) -> tuple[list[str], list[IssueDict]]:
    activity_ids = {activity.get("activity_id") for activity in activities}
    dangling: set[str] = set()
    issues: list[IssueDict] = []

    for index, period_content in enumerate(period_contents):
        for ref in period_content.get("activity_refs") or []:
            if ref not in activity_ids:
                dangling.add(ref)
                issues.append(
                    make_issue(
                        code="CONSISTENCY_DANGLING_ACTIVITY_REF",
                        message=f"activity_ref {ref!r} does not resolve to any activity",
                        path=f"/classroom_content/{index}/activity_refs",
                        stage="lesson-generation",
                    )
                )

    return sorted(dangling), issues


def check_consistency(
    *,
    knowledge: dict[str, Any],
    teaching_plan: dict[str, Any],
    period_contents: list[dict[str, Any]],
    activities: list[dict[str, Any]],
) -> tuple[ConsistencyReport, list[IssueDict]]:
    periods = teaching_plan.get("periods") or []
    period_duration_minutes = teaching_plan.get("period_duration_minutes") or 0

    duplicate_concept_ids, duplicate_issues = _duplicate_concepts(periods)
    prerequisite_violations, prereq_issues = _prerequisite_violations(knowledge, periods)
    timing_ok, timing_issues = _timing(periods, period_duration_minutes)
    dangling_activity_refs, dangling_issues = _dangling_activity_refs(period_contents, activities)

    report = ConsistencyReport(
        duplicate_concept_ids=duplicate_concept_ids,
        prerequisite_violations=prerequisite_violations,
        dangling_activity_refs=dangling_activity_refs,
        timing_ok=timing_ok,
    )
    issues = [*duplicate_issues, *prereq_issues, *timing_issues, *dangling_issues]
    return report, issues
