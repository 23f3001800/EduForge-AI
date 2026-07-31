"""Job lifecycle and progress-streaming contracts.

:class:`ProgressEvent` is the wire format for FR-14. The assignment specifies the
shape ``{"stage": "lesson-generation", "progress": 60}``; those two keys are
required here and every other field is additive. ``seq`` doubles as the SSE event
id, which is what makes ``Last-Event-ID`` replay work and therefore what makes a
mid-run browser refresh survivable (docs/00 § H-02).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.primitives import StageName, StrictModel

__all__ = [
    "STAGE_PROGRESS_WEIGHTS",
    "ArtifactKind",
    "DocumentKind",
    "JobOptions",
    "JobStatus",
    "ProgressEvent",
    "ProgressLevel",
    "TeachingStyle",
]

JobStatus = Literal["queued", "running", "succeeded", "succeeded_partial", "failed", "cancelled"]
ProgressLevel = Literal["info", "warning", "error"]

ArtifactKind = Literal[
    "tkp_json",
    "lesson_plan_pdf",
    "teacher_guide_pdf",
    "assessment_book_pdf",
    "markdown_bundle",
]

#: What the uploader says the document contains, so parsing can be routed by cost
#: (FAQ Q7). The brief explicitly encourages this: a text-only chapter should not
#: pay for the pipeline a diagram-heavy one needs.
#:
#: Advisory, never trusted blindly — stage 1 combines it with its own heuristics
#: (embedded image count, extractable-text ratio, equation density), because an
#: uploader guessing wrong must degrade the routing, not the result.
DocumentKind = Literal[
    "mostly_text",
    "text_with_tables",
    "text_with_diagrams",
    "text_with_equations",
    "scanned_pdf",
    "unknown",
]

#: How the teacher wants the material delivered (FAQ Q5). Distinct from
#: ``pedagogy_profile``, which is what the *content* demands: a narrative chapter
#: stays narrative whether the teacher lectures or runs a discussion.
TeachingStyle = Literal[
    "balanced",
    "lecture_led",
    "discussion_led",
    "activity_led",
    "inquiry_led",
    "exam_focused",
]

#: Share of overall progress each stage represents. Must sum to 100 — asserted in
#: the contract test suite so a new stage cannot silently break the progress bar.
STAGE_PROGRESS_WEIGHTS: dict[StageName, int] = {
    "document-intelligence": 8,
    "educational-classification": 5,
    "knowledge-extraction": 17,
    "teaching-planner": 10,
    "lesson-generation": 25,
    "activity-generation": 10,
    "assessment-generation": 10,
    "gap-analysis": 5,
    "validation": 5,
    "publishing": 5,
}


class JobOptions(StrictModel):
    """Run configuration.

    Every field is optional with a working default, which is the point: the brief
    asks for "a small number of clarifying questions" up front (FAQ Q5), not an
    interrogation. A teacher who answers nothing still gets a good package; each
    answer they do give measurably sharpens it.
    """

    period_duration_minutes: int = Field(default=40, ge=5, le=240)

    teaching_style: TeachingStyle = Field(
        default="balanced",
        description="How the teacher wants to deliver it. Shifts activity mix and "
        "script emphasis; does not override what the content itself demands.",
    )
    learning_goals: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Teacher-stated goals for this unit. Merged with the objectives "
        "extracted from the document rather than replacing them — a teacher's goal "
        "the source cannot support is reported, not silently dropped.",
    )
    document_kind: DocumentKind = Field(
        default="unknown",
        description="Uploader's hint for cost-aware parse routing (FAQ Q7). "
        "'unknown' means let the system decide, which is always safe.",
    )
    target_period_count: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="None means derive from concept load. Prefer None — a caller "
        "guessing this is usually worse than the derivation.",
    )
    output_language: str = Field(
        default="en",
        min_length=2,
        description="BCP-47. Values are translated; JSON keys stay English (BR-06).",
    )
    curriculum_board: str | None = None
    include_artifacts: list[ArtifactKind] = Field(
        default_factory=lambda: [
            "tkp_json",
            "lesson_plan_pdf",
            "teacher_guide_pdf",
            "assessment_book_pdf",
        ]
    )


class ProgressEvent(StrictModel):
    """One SSE frame.

    ``stage`` and ``progress`` are the two keys the assignment names, and the
    contract test asserts both are present on every emitted event.
    """

    stage: str = Field(
        min_length=1,
        description="A StageName, or a terminal marker: 'queued', 'completed', 'failed'.",
    )
    progress: int = Field(ge=0, le=100)
    seq: int = Field(default=0, ge=0, description="Monotonic per job; the SSE event id.")
    level: ProgressLevel = "info"
    message: str | None = None
    substage: str | None = Field(default=None, description='Fan-out detail, e.g. "period 3 of 5".')
    ts: datetime | None = None
    data: dict[str, str | int | float | bool] = Field(default_factory=dict)


class JobSnapshot(StrictModel):
    """Point-in-time job state, as returned by ``GET /jobs/{id}``."""

    job_id: UUID
    document_id: UUID
    status: JobStatus
    current_stage: StageName | None = None
    progress: int = Field(default=0, ge=0, le=100)
    package_id: UUID | None = None
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, str] | None = None
    created_at: datetime
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def _terminal_states_are_consistent(self) -> JobSnapshot:
        if self.status in ("succeeded", "succeeded_partial") and self.package_id is None:
            raise ValueError(f"status {self.status!r} requires a package_id")
        if self.status == "failed" and not self.error:
            raise ValueError("status 'failed' requires an error payload")
        return self
