"""Stage 8's model-facing schema — one gap per call.

``gap_id``, ``concept_ids`` and ``severity`` are decided in ``severity.py`` from
the concept graph, so none of them are asked for. What is left is the part that
is genuinely writing: the misconception in student language, a question that
detects it, and steps that fix it.

``diagnostic_questions`` and ``remediation`` are both ``min_length=1`` in the
contract, deliberately — a gap with neither is an observation, not a teaching
artifact. They are optional here and defaulted, because the failure to handle is
a model returning three good fields and one empty list, not a malformed call.
"""

from __future__ import annotations

from pydantic import Field

from contracts.primitives import StrictModel
from stages.base import Draft

__all__ = ["DiagnosticDraft", "GapDraft", "RemediationDraft"]


class DiagnosticDraft(StrictModel):
    question: str = ""
    reveals: str = ""
    expected_wrong_answer: str = ""


class RemediationDraft(StrictModel):
    action: str = ""
    rationale: str = ""
    estimated_minutes: int = 0


class GapDraft(Draft):
    """One learning gap: what students get wrong, how to spot it, how to fix it."""

    misconception: str = Field(
        default="", description="The incorrect belief, stated as a student would hold it."
    )
    why_it_happens: str = Field(
        default="", description="The cause — where the reasoning goes wrong."
    )
    diagnostic_questions: list[DiagnosticDraft] = Field(default_factory=list)
    remediation: list[RemediationDraft] = Field(default_factory=list)
