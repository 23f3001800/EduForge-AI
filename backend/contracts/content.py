"""Stages 5 & 6 contracts — classroom content and activities.

This is the material a teacher actually reads in the room, and it carries the
largest single share of the grade. The constraints below encode what makes
generated content *usable* rather than merely well-formed: scripts have timings
and board actions, activities have real materials and observable success criteria,
and differentiation is required rather than optional.

One deliberate exception to the grounding rule: :class:`MentorMoment` is a
motivational anecdote permitted to draw on general knowledge. It is flagged so
stage 9 does not penalise it as an unsupported claim (docs/01 § SRS-5.2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from contracts.primitives import BloomLevel, Identifier, StrictModel

__all__ = [
    "Activity",
    "ActivityType",
    "BlackboardNotes",
    "CheckpointQuestion",
    "Differentiation",
    "EntryTicket",
    "ExitTicket",
    "Homework",
    "MentorMoment",
    "PeriodContent",
    "ScriptSegment",
]

#: Weighted per pedagogy profile — narrative content favours debate and role play,
#: quantitative content favours problem sets and experiments. The weighting lives
#: in `pedagogy/profiles/*.yaml`, never in a subject-name branch.
ActivityType = Literal[
    "demonstration",
    "role_play",
    "experiment",
    "group_discussion",
    "think_pair_share",
    "problem_set",
    "field_task",
    "simulation",
    "debate",
    "gallery_walk",
]


class EntryTicket(StrictModel):
    """Opening diagnostic. Activates prior knowledge; must be answerable in minutes."""

    prompt: str = Field(min_length=1)
    expected_response: str = Field(min_length=1)
    duration_minutes: int = Field(default=5, ge=1, le=15)


class ScriptSegment(StrictModel):
    """One timed beat of the lesson, usable aloud by a teacher who has not pre-read it."""

    minute_start: int = Field(ge=0)
    minute_end: int = Field(ge=1)
    heading: str = Field(min_length=1)
    speaker_notes: str = Field(min_length=1, description="What the teacher says or does.")
    board_action: str | None = Field(
        default=None, description="What goes on the board during this segment."
    )
    anticipated_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered(self) -> ScriptSegment:
        if self.minute_end <= self.minute_start:
            raise ValueError("minute_end must be greater than minute_start")
        return self


class BlackboardNotes(StrictModel):
    """What ends up written on the board — not a prose summary of the lesson."""

    headings: list[str] = Field(default_factory=list)
    bullet_points: list[str] = Field(default_factory=list)
    diagrams_to_draw: list[str] = Field(default_factory=list)
    formulae_latex: list[str] = Field(default_factory=list)


class CheckpointQuestion(StrictModel):
    """Mid-lesson comprehension check."""

    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    bloom_level: BloomLevel
    concept_ids: list[Identifier] = Field(default_factory=list)


class ExitTicket(StrictModel):
    prompt: str = Field(min_length=1)
    success_indicator: str = Field(
        min_length=1, description="What a correct response looks like, so it can be marked fast."
    )
    duration_minutes: int = Field(default=5, ge=1, le=15)


class Homework(StrictModel):
    tasks: list[str] = Field(min_length=1)
    estimated_minutes: int = Field(ge=1)
    submission_format: str | None = None


class MentorMoment(StrictModel):
    """Short motivational anecdote tied to the period's concepts.

    Not grounded by design. ``grounded`` is a frozen literal rather than a mutable
    flag so no stage can quietly mark other content as exempt from the grounding
    check by copying this pattern.
    """

    title: str = Field(min_length=1)
    story: str = Field(min_length=1)
    takeaway: str = Field(min_length=1)
    grounded: Literal[False] = False


class Differentiation(StrictModel):
    support: str = Field(min_length=1, description="For students who need scaffolding.")
    extension: str = Field(min_length=1, description="For students who finish early.")


class Activity(StrictModel):
    """A classroom activity specific enough to run without interpretation (FR-07)."""

    activity_id: Identifier
    period_no: int = Field(ge=1)
    type: ActivityType
    title: str = Field(min_length=1)
    duration_minutes: int = Field(ge=1)
    materials: list[str] = Field(
        default_factory=list, description="Things a real classroom has. Empty is valid."
    )
    teacher_instructions: list[str] = Field(min_length=1)
    student_instructions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(
        min_length=1, description="Observable in the moment, not after marking."
    )
    differentiation: Differentiation
    concept_ids: list[Identifier] = Field(default_factory=list)


class PeriodContent(StrictModel):
    """Everything needed to teach one period (FR-06)."""

    period_no: int = Field(ge=1)
    entry_ticket: EntryTicket
    teacher_script: list[ScriptSegment] = Field(min_length=1)
    blackboard_notes: BlackboardNotes
    activity_refs: list[Identifier] = Field(
        default_factory=list, description="Resolve against the package's `activities`."
    )
    checkpoint_questions: list[CheckpointQuestion] = Field(min_length=1)
    exit_ticket: ExitTicket
    homework: Homework
    mentor_moment: MentorMoment

    @model_validator(mode="after")
    def _script_is_monotonic(self) -> PeriodContent:
        segments = self.teacher_script
        for prev, nxt in zip(segments, segments[1:], strict=False):
            if nxt.minute_start < prev.minute_end:
                raise ValueError(
                    f"teacher_script segments overlap: {prev.heading!r} ends at "
                    f"{prev.minute_end} but {nxt.heading!r} starts at {nxt.minute_start}"
                )
        return self
