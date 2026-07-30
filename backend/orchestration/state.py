"""Graph state.

Keys are written by exactly one stage each. That single-writer rule is what makes
the graph safe to fan out and safe to resume: merging two partial states can never
produce a conflict, because no two nodes ever claim the same key.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

__all__ = ["STAGE_STATE_KEY", "GraphState"]


def merge_period_contents(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fan-in reducer for per-period generation.

    Accepts results in any order, keys on ``period_no``, and lets a later result
    replace an earlier one for the same period — which is what makes regenerating
    a single failed period safe rather than duplicating it.
    """
    merged: dict[int, dict[str, Any]] = {item["period_no"]: item for item in left}
    for item in right:
        merged[item["period_no"]] = item
    return [merged[k] for k in sorted(merged)]


class GraphState(TypedDict, total=False):
    # identity
    job_id: str
    document_id: str
    options: dict[str, Any]

    # stage outputs — one writer each
    structured_document: dict[str, Any]
    chunks: list[dict[str, Any]]
    classification: dict[str, Any]
    knowledge: dict[str, Any]
    teaching_plan: dict[str, Any]
    period_contents: Annotated[list[dict[str, Any]], merge_period_contents]
    activities: list[dict[str, Any]]
    assessments: dict[str, Any]
    learning_gaps: list[dict[str, Any]]
    validation: dict[str, Any]
    package: dict[str, Any]

    # control
    warnings: Annotated[list[str], operator.add]
    validation_attempts: int
    stages_to_regenerate: list[str]


#: Which state key each stage writes. Used to restore checkpoints on resume and
#: to invalidate precisely the right keys during targeted regeneration.
STAGE_STATE_KEY: dict[str, str] = {
    "document-intelligence": "structured_document",
    "educational-classification": "classification",
    "knowledge-extraction": "knowledge",
    "teaching-planner": "teaching_plan",
    "lesson-generation": "period_contents",
    "activity-generation": "activities",
    "assessment-generation": "assessments",
    "gap-analysis": "learning_gaps",
    "validation": "validation",
    "publishing": "package",
}
