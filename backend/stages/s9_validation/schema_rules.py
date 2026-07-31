"""Rule class 1 — schema conformance (SRS-6.1).

Each section of the in-progress package is validated against the exact Pydantic
model that section occupies in ``contracts.tkp.TeacherKnowledgePackage`` — the
published contract, not a re-description of it. A stage that produced its own
output validates it before returning (H-04), so in the healthy path every one of
these calls is a no-op; this exists for the case a stage's own check missed
something, or a checkpoint was hand-edited, or a repair cycle wrote a partial
fragment.

Deliberately *not* assembled into a full ``TeacherKnowledgePackage`` here: that
model also requires ``tkp_id``, ``generated_at``, ``generator``, ``source``, and
``provenance``, none of which stage 9 owns or can honestly fabricate — those
belong to stage 10. The cross-reference checks that model performs (dangling
``activity_refs``, teaching-plan references to unknown concepts and objectives)
are instead reproduced directly against the raw state in
:mod:`stages.s9_validation.consistency_rules` and
:mod:`stages.s9_validation.coverage_rules`, which can run whether or not the
individual sections are themselves schema-valid.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.assessment import AssessmentBank
from contracts.classification import Classification
from contracts.content import Activity, PeriodContent
from contracts.gaps import LearningGap
from contracts.knowledge import KnowledgeBase
from contracts.plan import TeachingPlan
from stages.s9_validation.issues import IssueDict, make_issue

__all__ = ["SECTION_OWNER", "check_schema"]

#: Which stage must regenerate a section that fails to validate.
SECTION_OWNER: dict[str, str] = {
    "classification": "educational-classification",
    "knowledge": "knowledge-extraction",
    "teaching_plan": "teaching-planner",
    "period_contents": "lesson-generation",
    "activities": "activity-generation",
    "assessments": "assessment-generation",
    "learning_gaps": "gap-analysis",
}

_ERROR_PREVIEW_CHARS = 300


def _validate_one(
    *, model: type[Any], payload: Any, key: str, path: str, issues: list[IssueDict]
) -> bool:
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        issues.append(
            make_issue(
                code=f"SCHEMA_{key.upper()}_INVALID",
                message=f"{key} does not conform to its contract: "
                f"{str(exc)[:_ERROR_PREVIEW_CHARS]}",
                path=path,
                stage=SECTION_OWNER[key],
            )
        )
        return False
    return True


def check_schema(
    *,
    classification: dict[str, Any],
    knowledge: dict[str, Any],
    teaching_plan: dict[str, Any],
    period_contents: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    assessments: dict[str, Any],
    learning_gaps: list[dict[str, Any]],
) -> tuple[bool, list[IssueDict]]:
    """Validate every section against its own contract type.

    Returns ``(schema_ok, issues)``. ``schema_ok`` is ``False`` if any section
    failed — that always yields at least one ``error``-severity issue, which is
    what keeps ``ValidationReport``'s own ``schema_ok=False`` / ``status="pass"``
    combination unreachable (see ``contracts.validation``).
    """
    issues: list[IssueDict] = []
    ok = True

    ok &= _validate_one(
        model=Classification,
        payload=classification,
        key="classification",
        path="/classification",
        issues=issues,
    )
    ok &= _validate_one(
        model=KnowledgeBase, payload=knowledge, key="knowledge", path="/knowledge", issues=issues
    )
    ok &= _validate_one(
        model=TeachingPlan,
        payload=teaching_plan,
        key="teaching_plan",
        path="/teaching_plan",
        issues=issues,
    )
    ok &= _validate_one(
        model=AssessmentBank,
        payload=assessments,
        key="assessments",
        path="/assessments",
        issues=issues,
    )

    for index, period_content in enumerate(period_contents):
        ok &= _validate_one(
            model=PeriodContent,
            payload=period_content,
            key="period_contents",
            path=f"/classroom_content/{index}",
            issues=issues,
        )
    for index, activity in enumerate(activities):
        ok &= _validate_one(
            model=Activity,
            payload=activity,
            key="activities",
            path=f"/activities/{index}",
            issues=issues,
        )
    for index, gap in enumerate(learning_gaps):
        ok &= _validate_one(
            model=LearningGap,
            payload=gap,
            key="learning_gaps",
            path=f"/learning_gaps/{index}",
            issues=issues,
        )

    return ok, issues
