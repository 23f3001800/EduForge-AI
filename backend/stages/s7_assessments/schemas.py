"""Stage 7's model-facing schemas — one item per call, split by shape.

Two schemas rather than one union, for the reason stage 3 was split: a schema
carrying every field both shapes might need is mostly inapplicable on any given
call, and a model handed inapplicable fields fills them in. An MCQ draft that
also offers ``rubric_levels`` gets rubric levels.

The important design choice is ``correct_index`` instead of a per-option
``is_correct`` flag. ``AssessmentItem`` requires exactly one correct option, and a
model setting four independent booleans produces zero or two often enough to
matter — it is the single most common way a generated MCQ is unusable while
looking fine. One integer cannot express "none correct" or "two correct", so the
invariant is carried by the shape of the request rather than checked afterwards.

Everything here is lenient: unknown keys dropped, every field defaulted. Strictness
belongs at the ``contracts.assessment`` boundary, where the item is rebuilt.
"""

from __future__ import annotations

from pydantic import Field

from contracts.primitives import StrictModel
from stages.base import Draft

__all__ = ["ConstructedResponseDraft", "MCQDraft", "RubricLevelDraft"]


class MCQDraft(Draft):
    """A four-option multiple-choice item.

    ``rationales`` is positional — it lines up with ``options`` — because asking
    for a mapping keyed by option text invites the model to paraphrase the option
    on the way into the key, and then nothing joins.
    """

    stem: str = ""
    options: list[str] = Field(
        default_factory=list,
        description="Exactly 4 answer texts, without letter labels.",
    )
    correct_index: int = Field(
        default=0,
        description="0-based index into `options` of the single correct answer.",
    )
    rationales: list[str] = Field(
        default_factory=list,
        description="Positional, one per option: why a student might pick it. "
        "For the correct option, why it is right.",
    )
    answer: str = Field(
        default="",
        description="The correct answer restated, with the reasoning a marker needs.",
    )


class RubricLevelDraft(StrictModel):
    """One rung of a mark ladder."""

    label: str = ""
    descriptor: str = ""
    marks: int = 0


class ConstructedResponseDraft(Draft):
    """A short-answer, long-answer, or numerical item."""

    stem: str = ""
    answer: str = Field(default="", description="The model answer a marker marks against.")
    working: str = Field(
        default="",
        description="Step-by-step solution. Expected on numerical items, empty otherwise.",
    )
    rubric_criteria: str = Field(
        default="", description="What this item is judged on, in one line."
    )
    rubric_levels: list[RubricLevelDraft] = Field(
        default_factory=list,
        description="2-3 levels awarding DIFFERENT marks, highest first.",
    )
