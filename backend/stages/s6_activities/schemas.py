"""Stage 6's model-facing schema — one activity per call.

``Activity`` carries an id, a period number, a type, a duration, and a nested
``Differentiation``. None of that is a writing task, so none of it is asked for:
``selection.py`` fixes the structure and this schema requests only prose. What is
left is seven shallow fields, which is small enough that the call is never the
thing that fails.

``differentiation`` is flattened to ``support`` and ``extension`` for the same
reason. One less level of nesting is measurably more reliable on a small model,
and the nested object is rebuilt on the way out — where it is also given a real
fallback, because differentiation is required by the contract and is exactly the
field a model drops first when it is running out of output budget.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from contracts.primitives import StrictModel

__all__ = ["ActivityDraft", "Draft"]


class Draft(StrictModel):
    """Base for model-facing draft types: lenient in, strict out.

    Unknown keys are dropped rather than rejected — models echo the ids and types
    they were shown, and losing a whole activity to a courtesy key is a bad trade.
    Everything survives to be re-validated against ``contracts.content.Activity``.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_unknown_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key in cls.model_fields}
        return value


class ActivityDraft(Draft):
    """The written half of one classroom activity."""

    title: str = ""
    materials: list[str] = Field(default_factory=list)
    teacher_instructions: list[str] = Field(default_factory=list)
    student_instructions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    support: str = Field(default="", description="Scaffolding for students who need it.")
    extension: str = Field(default="", description="For students who finish early.")
