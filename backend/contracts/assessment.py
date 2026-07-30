"""Stage 7 contracts — assessments, answer keys, and rubrics.

Two constraints are enforced structurally because they are the two ways generated
assessments most often fail while still looking fine:

* An MCQ with zero or two correct options is unusable and is trivially produced by
  a model that loses track mid-generation. Exactly one is required here.
* A non-MCQ item without a rubric cannot be marked consistently, which makes the
  whole assessment decorative. Required by validator, not by convention.

``numerical`` items are legitimately absent from narrative content. Nothing in
this module requires them; the profile-conditioned ruleset in stage 9 decides
what a given document actually owes (docs/00 § H-07).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from contracts.primitives import BloomLevel, Identifier, StrictModel

__all__ = [
    "AssessmentBank",
    "AssessmentBlueprint",
    "AssessmentItem",
    "ItemKind",
    "MCQOption",
    "Rubric",
    "RubricLevel",
]

ItemKind = Literal["mcq", "short_answer", "long_answer", "numerical"]


class MCQOption(StrictModel):
    label: str = Field(min_length=1, description='e.g. "A".')
    text: str = Field(min_length=1)
    is_correct: bool = False
    rationale: str | None = Field(
        default=None,
        description="Why this distractor is tempting. Distractors that trace to a "
        "real misconception both teach and diagnose; random wrong answers do neither.",
    )


class RubricLevel(StrictModel):
    label: str = Field(min_length=1, description='e.g. "Proficient".')
    descriptor: str = Field(
        min_length=1, description="What work at this level looks like — must discriminate."
    )
    marks: int = Field(ge=0)


class Rubric(StrictModel):
    criteria: str = Field(min_length=1)
    levels: list[RubricLevel] = Field(min_length=2)

    @model_validator(mode="after")
    def _levels_discriminate(self) -> Rubric:
        marks = [lvl.marks for lvl in self.levels]
        if len(set(marks)) == 1:
            raise ValueError(
                "all rubric levels award identical marks, so the rubric cannot "
                "discriminate between performance levels"
            )
        return self


class AssessmentItem(StrictModel):
    item_id: Identifier
    kind: ItemKind
    stem: str = Field(min_length=1)
    options: list[MCQOption] | None = None
    answer: str = Field(min_length=1)
    working: str | None = Field(
        default=None, description="Worked solution. Expected on numerical items."
    )
    marks: int = Field(ge=1)
    bloom_level: BloomLevel
    concept_ids: list[Identifier] = Field(default_factory=list)
    rubric: Rubric | None = None
    linked_misconception_id: Identifier | None = Field(
        default=None, description="Provenance for a distractor or a diagnostic item."
    )

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> AssessmentItem:
        if self.kind == "mcq":
            if not self.options:
                raise ValueError("mcq item must carry `options`")
            if len(self.options) != 4:
                raise ValueError(f"mcq item must have exactly 4 options, got {len(self.options)}")
            correct = [o for o in self.options if o.is_correct]
            if len(correct) != 1:
                raise ValueError(
                    f"mcq item must have exactly one correct option, got {len(correct)}"
                )
            labels = [o.label for o in self.options]
            if len(set(labels)) != len(labels):
                raise ValueError(f"duplicate option labels: {labels}")
        else:
            if self.options is not None:
                raise ValueError("`options` is only valid on an mcq item")
            if self.rubric is None:
                raise ValueError(
                    f"{self.kind} item requires a rubric; without one it cannot be "
                    "marked consistently"
                )
        return self


class AssessmentBlueprint(StrictModel):
    """Coverage plan. Built first, so the bank is designed rather than accumulated."""

    items_by_kind: dict[str, int] = Field(default_factory=dict)
    items_by_bloom: dict[str, int] = Field(default_factory=dict)
    marks_by_concept: dict[str, int] = Field(default_factory=dict)


class AssessmentBank(StrictModel):
    items: list[AssessmentItem] = Field(min_length=1)
    blueprint: AssessmentBlueprint = Field(default_factory=AssessmentBlueprint)
    total_marks: int = Field(ge=1)

    @model_validator(mode="after")
    def _ids_unique_and_marks_add_up(self) -> AssessmentBank:
        ids = [i.item_id for i in self.items]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate item_id(s): {dupes[:5]}")

        actual = sum(i.marks for i in self.items)
        if actual != self.total_marks:
            raise ValueError(f"total_marks={self.total_marks} but items sum to {actual}")
        return self
