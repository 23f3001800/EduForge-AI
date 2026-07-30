"""The Teacher Knowledge Package — the master artifact (FR-11).

This is what the assignment is ultimately asking for: everything the pipeline
learned and produced about one document, in one self-describing, versioned,
traceable object.

The cross-reference validators here are the last line of defence. Stage 9 checks
these same relationships and reports them richly; this model refuses to construct
a package whose internal references are simply broken. The overlap is deliberate —
stage 9 explains *what is wrong for a teacher*, this explains *what is malformed
for a machine*, and neither substitutes for the other.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from contracts.assessment import AssessmentBank
from contracts.classification import Classification
from contracts.content import Activity, PeriodContent
from contracts.document import DocumentMetadata
from contracts.gaps import LearningGap
from contracts.knowledge import KnowledgeBase
from contracts.plan import TeachingPlan
from contracts.primitives import SCHEMA_VERSION, Identifier, StageName, StrictModel
from contracts.validation import ValidationReport

__all__ = ["Citation", "GeneratorInfo", "Provenance", "StageTiming", "TeacherKnowledgePackage"]


class StageTiming(StrictModel):
    stage: StageName
    duration_ms: int = Field(ge=0)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    tokens_cached: int = Field(default=0, ge=0)
    attempts: int = Field(default=1, ge=1)
    degraded: bool = False


class GeneratorInfo(StrictModel):
    """What produced this package. Required for reproducibility (NFR-12) and for
    honest comparison between eval runs — scores are meaningless without knowing
    which provider and models produced them."""

    app_version: str = Field(min_length=1)
    models_by_stage: dict[str, str] = Field(
        default_factory=dict, description='e.g. {"knowledge-extraction": "claude-opus-5"}.'
    )
    providers_by_stage: dict[str, str] = Field(default_factory=dict)


class Citation(StrictModel):
    """A source reference surfaced to the teacher (BR-02)."""

    chunk_id: Identifier
    page: int | None = Field(default=None, ge=1)
    section_path: list[str] = Field(default_factory=list)
    quote: str = Field(min_length=1)
    referenced_by: list[str] = Field(
        default_factory=list, description="JSON pointers to the claims citing this span."
    )


class Provenance(StrictModel):
    citations: list[Citation] = Field(default_factory=list)
    stage_timings: list[StageTiming] = Field(default_factory=list)
    total_tokens_in: int = Field(default=0, ge=0)
    total_tokens_out: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    total_duration_ms: int = Field(default=0, ge=0)


class TeacherKnowledgePackage(StrictModel):
    """The complete, classroom-ready output for one source document."""

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    tkp_id: UUID
    generated_at: datetime
    generator: GeneratorInfo

    source: DocumentMetadata
    classification: Classification
    knowledge: KnowledgeBase
    teaching_plan: TeachingPlan
    classroom_content: list[PeriodContent] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    assessments: AssessmentBank
    learning_gaps: list[LearningGap] = Field(default_factory=list)
    validation: ValidationReport
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def _cross_references_resolve(self) -> TeacherKnowledgePackage:
        plan_period_nos = {p.period_no for p in self.teaching_plan.periods}

        content_nos = [c.period_no for c in self.classroom_content]
        if len(content_nos) != len(set(content_nos)):
            dupes = sorted({n for n in content_nos if content_nos.count(n) > 1})
            raise ValueError(f"duplicate classroom_content for period(s): {dupes}")

        orphan_content = sorted(set(content_nos) - plan_period_nos)
        if orphan_content:
            raise ValueError(f"classroom_content for periods not in the plan: {orphan_content}")

        orphan_activities = sorted({a.period_no for a in self.activities} - plan_period_nos)
        if orphan_activities:
            raise ValueError(f"activities reference periods not in the plan: {orphan_activities}")

        activity_ids = {a.activity_id for a in self.activities}
        dangling = sorted(
            {ref for c in self.classroom_content for ref in c.activity_refs} - activity_ids
        )
        if dangling:
            raise ValueError(f"activity_refs do not resolve: {dangling[:5]}")

        concept_ids = {c.concept_id for c in self.knowledge.concepts}
        planned = {cid for p in self.teaching_plan.periods for cid in p.concept_ids}
        unknown = sorted(planned - concept_ids)
        if unknown:
            raise ValueError(f"teaching_plan references unknown concept ids: {unknown[:5]}")

        objective_ids = {o.objective_id for o in self.knowledge.learning_objectives}
        planned_objs = {oid for p in self.teaching_plan.periods for oid in p.objective_ids}
        unknown_objs = sorted(planned_objs - objective_ids)
        if unknown_objs:
            raise ValueError(f"teaching_plan references unknown objective ids: {unknown_objs[:5]}")

        return self
