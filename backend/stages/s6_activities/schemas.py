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

from pydantic import Field

from stages.base import Draft

__all__ = ["ActivityDraft"]


class ActivityDraft(Draft):
    """The written half of one classroom activity."""

    title: str = ""
    materials: list[str] = Field(default_factory=list)
    teacher_instructions: list[str] = Field(default_factory=list)
    student_instructions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    support: str = Field(default="", description="Scaffolding for students who need it.")
    extension: str = Field(default="", description="For students who finish early.")
