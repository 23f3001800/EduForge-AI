"""Renderers, keyed by the `ArtifactKind` they produce.

`stage.py` reads `RENDERERS` rather than importing each function by name so
that "which artifacts exist" and "which artifacts were asked for" are both
just set operations against the same dict — adding a fifth artifact kind later
is one new entry here, not a new branch in the stage.
"""

from __future__ import annotations

from collections.abc import Callable

from contracts.jobs import ArtifactKind
from contracts.tkp import TeacherKnowledgePackage
from stages.s10_publishing.render.assessment_book import render_assessment_book_pdf
from stages.s10_publishing.render.lesson_plan import render_lesson_plan_pdf
from stages.s10_publishing.render.markdown_bundle import render_markdown_bundle
from stages.s10_publishing.render.teacher_guide import render_teacher_guide_pdf

__all__ = ["RENDERERS", "render_tkp_json"]


def render_tkp_json(tkp: TeacherKnowledgePackage) -> bytes:
    return tkp.model_dump_json(indent=2).encode("utf-8")


#: Every kind `JobOptions.include_artifacts` can name, mapped to the function
#: that renders it from an assembled package. `tkp_json` needs no PDF/markdown
#: layout of its own — it is the package's own validated JSON.
RENDERERS: dict[ArtifactKind, Callable[[TeacherKnowledgePackage], bytes]] = {
    "tkp_json": render_tkp_json,
    "lesson_plan_pdf": render_lesson_plan_pdf,
    "teacher_guide_pdf": render_teacher_guide_pdf,
    "assessment_book_pdf": render_assessment_book_pdf,
    "markdown_bundle": render_markdown_bundle,
}
