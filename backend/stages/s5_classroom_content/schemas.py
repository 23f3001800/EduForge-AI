"""Stage 5's model-facing schemas — two narrow calls per period.

``PeriodContent`` is eight fields deep with three nested lists and a set of
arithmetic constraints (segments must not overlap, tickets must fit in 15
minutes). Asking a small model for the whole of it in one call reproduces the
failure stage 3 measured: the strict schema alone eats the output budget and the
call returns ``json_validate_failed`` with an *empty* generation, so nothing at
all is produced for that period.

So each period is two calls over halves that a teacher would recognise as
separate jobs:

* :class:`LessonCore` — the taught part: how the period opens, what the teacher
  says and does minute by minute, and what ends up on the board.
* :class:`LessonClose` — the checking part: comprehension checks, the exit
  ticket, homework, and the mentor moment.

Splitting there rather than arbitrarily matters for degradation. A failed second
call costs the checks and keeps a runnable script; a failed first call costs the
script and keeps the exit ticket. Losing a whole period because one call was weak
is the outcome the split exists to avoid.

Every type here is a *draft*, not the contract type. The contract's arithmetic —
non-overlapping script windows, ticket durations inside their bounds, at least one
checkpoint question — is repaired deterministically in ``assembly.py`` and
validated against the real contract there. Enforcing it at parse time instead
would throw away an entire good lesson over a model that wrote ``minute_end: 45``
in a 40-minute period, which is a thing models do constantly.
"""

from __future__ import annotations

from typing import Any, get_args

from pydantic import Field, field_validator, model_validator

from contracts.primitives import BloomLevel, StrictModel

__all__ = [
    "BlackboardDraft",
    "CheckpointDraft",
    "Draft",
    "EntryTicketDraft",
    "ExitTicketDraft",
    "HomeworkDraft",
    "LessonClose",
    "LessonCore",
    "MentorMomentDraft",
    "ScriptSegmentDraft",
]

_BLOOM: frozenset[str] = frozenset(get_args(BloomLevel))
#: Where an unrecognised Bloom verb lands. Not `remember`: defaulting to recall
#: quietly lowers the cognitive demand of the whole package, which is the exact
#: quality failure the level is meant to make visible.
_BLOOM_FALLBACK = "understand"


class Draft(StrictModel):
    """Base for model-facing draft types: lenient in, strict out.

    Unknown keys are dropped rather than rejected. Models echo the keys they were
    shown — ``period_no``, ``concept_ids`` — and failing the parse over a courtesy
    key spends a repair attempt that should have been spent on content. Nothing
    unchecked escapes: every draft is re-validated against its contract type once
    the deterministic half has repaired it.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_unknown_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key in cls.model_fields}
        return value


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else default


class _Timed(Draft):
    """Shared minute coercion. ``"10 minutes"`` is a string, and it arrives often."""

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_minutes(cls, value: Any, info: Any) -> Any:
        if info.field_name and "minutes" in info.field_name:
            return _as_int(value)
        return value


class EntryTicketDraft(_Timed):
    prompt: str = ""
    expected_response: str = ""
    duration_minutes: int = 5


class ScriptSegmentDraft(_Timed):
    """One beat of the lesson, as a *duration* rather than a window.

    The contract wants ``minute_start`` and ``minute_end`` and rejects overlaps.
    Models produce overlapping and over-running windows reliably, so they are not
    asked for one: they say how long a beat takes, and the timeline is laid out in
    Python where it cannot come out wrong.
    """

    heading: str = ""
    speaker_notes: str = ""
    board_action: str | None = None
    anticipated_questions: list[str] = Field(default_factory=list)
    minutes: int = 0


class BlackboardDraft(Draft):
    """What ends up written on the board.

    ``formulae_latex`` is accepted but not trusted: ``assembly.py`` keeps only
    formulae the knowledge base actually extracted for this period's concepts. A
    model asked for board notes will happily invent an equation for a poetry
    lesson, and a plausible invented formula is worse than a blank board.
    """

    headings: list[str] = Field(default_factory=list)
    bullet_points: list[str] = Field(default_factory=list)
    diagrams_to_draw: list[str] = Field(default_factory=list)
    formulae_latex: list[str] = Field(default_factory=list)


class CheckpointDraft(Draft):
    question: str = ""
    expected_answer: str = ""
    bloom_level: str = _BLOOM_FALLBACK
    concept_ids: list[str] = Field(default_factory=list)

    @field_validator("bloom_level", mode="before")
    @classmethod
    def _known_bloom(cls, value: Any) -> Any:
        text = str(value or "").strip().lower()
        return text if text in _BLOOM else _BLOOM_FALLBACK


class ExitTicketDraft(_Timed):
    prompt: str = ""
    success_indicator: str = ""
    duration_minutes: int = 5


class HomeworkDraft(_Timed):
    tasks: list[str] = Field(default_factory=list)
    estimated_minutes: int = 20
    submission_format: str | None = None


class MentorMomentDraft(Draft):
    """The one deliberately ungrounded artifact (docs/01 § SRS-5.2).

    ``grounded`` is not a field here. It is a frozen ``Literal[False]`` on the
    contract type, so a model cannot mark its own output exempt from the grounding
    check by claiming to be a mentor moment.
    """

    title: str = ""
    story: str = ""
    takeaway: str = ""


class LessonCore(Draft):
    """Call 1 — how the period opens, runs, and looks on the board."""

    entry_ticket: EntryTicketDraft = Field(default_factory=EntryTicketDraft)
    teacher_script: list[ScriptSegmentDraft] = Field(default_factory=list)
    blackboard_notes: BlackboardDraft = Field(default_factory=BlackboardDraft)


class LessonClose(Draft):
    """Call 2 — how the period checks, closes, and carries over."""

    checkpoint_questions: list[CheckpointDraft] = Field(default_factory=list)
    exit_ticket: ExitTicketDraft = Field(default_factory=ExitTicketDraft)
    homework: HomeworkDraft = Field(default_factory=HomeworkDraft)
    mentor_moment: MentorMomentDraft = Field(default_factory=MentorMomentDraft)
