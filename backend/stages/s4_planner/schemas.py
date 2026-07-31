"""Stage 4's model-facing schema — one period's decoration, nothing more.

The plan itself is already built when this schema is used. ``banding.py`` has
decided the period count, the concept ordering, the band boundaries, and the
objective mapping. What is left is the part an algorithm cannot write: a title a
teacher recognises, a rationale that reads like a human wrote it, and a sensible
split of the period's minutes.

So the schema is three fields. That is deliberate and it is the lesson stage 3
paid for: a wide schema on a small model fails with an *empty* generation, and the
whole call is lost. Three shallow fields fit in any output budget, and a period
whose model call fails costs one title rather than the plan.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from contracts.primitives import StrictModel

__all__ = ["BandDraft", "Draft", "TimeSlotDraft"]


class Draft(StrictModel):
    """Base for model-facing draft types: lenient in, strict out.

    ``StrictModel`` forbids unknown fields, which is right for a published
    contract and wrong for the object a model hands back. Models echo the keys
    they were shown — ``period_no`` here, ``concept_ids`` there — and rejecting
    the whole response over an extra key spends a repair attempt on a courtesy
    rather than on a content problem.

    Drafts only have to survive the trip. Everything they carry is re-validated
    against the real contract type once the deterministic half has fixed it up,
    so nothing unchecked reaches the package.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_unknown_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key in cls.model_fields}
        return value


def _as_minutes(value: Any) -> float:
    """Coerce whatever the model called a duration into a number.

    ``"12"``, ``"12 min"``, ``12.0`` and ``None`` all arrive in practice. A
    ``ValidationError`` on any of them would cost the title and the rationale too,
    which is a poor trade for a unit suffix.
    """
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
    try:
        return float(digits)
    except ValueError:
        return 0.0


class TimeSlotDraft(Draft):
    """One proposed slot. Minutes are advisory — stage 4 rescales them to the bell."""

    label: str = ""
    minutes: float = 0.0

    @field_validator("minutes", mode="before")
    @classmethod
    def _coerce_minutes(cls, value: Any) -> Any:
        return _as_minutes(value)


class BandDraft(Draft):
    """Everything the model is permitted to contribute to one period."""

    title: str = ""
    sequence_rationale: str = ""
    time_allocation: list[TimeSlotDraft] = Field(default_factory=list)
