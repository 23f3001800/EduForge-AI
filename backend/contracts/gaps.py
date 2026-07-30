"""Stage 8 contracts — learning gap analysis.

A gap is only useful if it comes with a way to detect it and a way to fix it.
Both are required fields rather than optional extras, because a list of
misconceptions with no diagnostic and no remediation is an observation, not a
teaching artifact.

``evidence`` is optional here, unlike the stage 3 knowledge types: a genuine
misconception is often *predicted* from how students fail at this topic rather
than stated in the source document. Where the document does name it, cite it.
"""

from __future__ import annotations

from pydantic import Field

from contracts.primitives import Evidence, Identifier, Severity, StrictModel

__all__ = ["DiagnosticQuestion", "LearningGap", "RemediationStep"]


class DiagnosticQuestion(StrictModel):
    """A question whose wrong answer reveals this specific gap."""

    question: str = Field(min_length=1)
    reveals: str = Field(
        min_length=1,
        description="What a wrong answer tells the teacher — the diagnostic value.",
    )
    expected_wrong_answer: str | None = Field(
        default=None, description="What a student holding the misconception would say."
    )


class RemediationStep(StrictModel):
    action: str = Field(min_length=1)
    rationale: str = Field(
        min_length=1, description="Why this addresses the cause, not the symptom."
    )
    estimated_minutes: int | None = Field(default=None, ge=1)


class LearningGap(StrictModel):
    gap_id: Identifier
    misconception: str = Field(min_length=1)
    concept_ids: list[Identifier] = Field(default_factory=list)
    severity: Severity = Field(
        description="Drives remediation priority. `high` means downstream concepts "
        "will fail if this is not addressed first."
    )
    diagnostic_questions: list[DiagnosticQuestion] = Field(min_length=1)
    remediation: list[RemediationStep] = Field(min_length=1)
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Optional: present when the misconception is named in the source.",
    )
