"""Assessment Book PDF — questions and answer key (ArtifactKind `assessment_book_pdf`).

A teacher hands the *questions* to a class; they do not hand out the answers.
So this document is two separable sections rather than one interleaved list:

1. **Questions** — stem, options (for MCQs, unmarked and in the stored order),
   marks, and blank working space for numerical items. Nothing here reveals
   which option is correct, what the model answer is, or how the rubric marks.
2. **Answer Key** — starts on its own page behind a banner, and is the only
   place `AssessmentItem.answer`, `.working`, `.rubric`, and each option's
   `is_correct`/`rationale` appear.

The split is enforced structurally (`_render_questions` never touches
`item.answer`/`item.working`/`item.rubric`/`option.is_correct`; only
`_render_answer_key` does), not just by page order, so a future edit to one
function cannot leak the other's fields onto the wrong page without an
obvious, single-function diff.
"""

from __future__ import annotations

from contracts.assessment import AssessmentItem
from contracts.tkp import TeacherKnowledgePackage
from stages.s10_publishing.render.document import TkpDocument

__all__ = ["ANSWER_KEY_HEADING", "render_assessment_book_pdf"]

ANSWER_KEY_HEADING = "Answer Key"

_OPTION_LABELS = "ABCDEFGH"


def _render_questions(doc: TkpDocument, items: list[AssessmentItem]) -> None:
    doc.h1("Questions")
    doc.key_value("Total marks", str(sum(item.marks for item in items)))
    doc.spacer()
    for index, item in enumerate(items, start=1):
        # Bold carries the question number and its mark value — the two things a
        # student scans for — while the stem stays regular weight and readable.
        doc.labelled(
            f"Q{index}. ({item.marks} mark{'s' if item.marks != 1 else ''})", item.stem
        )
        if item.kind == "mcq" and item.options:
            for label, option in zip(_OPTION_LABELS, item.options, strict=False):
                doc.bullet(f"{label}. {option.text}")
        elif item.kind == "numerical":
            doc.muted("Working:")
            doc.body("\n".join(["_" * 60] * 3))
        doc.spacer(3)


def _render_answer_key(doc: TkpDocument, items: list[AssessmentItem]) -> None:
    doc.new_section_page()
    doc.banner(f"{ANSWER_KEY_HEADING} — teacher copy, not for distribution to students")
    doc.h1(ANSWER_KEY_HEADING)
    for index, item in enumerate(items, start=1):
        doc.h3(f"Q{index}.")
        if item.kind == "mcq" and item.options:
            correct = next((o for o in item.options if o.is_correct), None)
            if correct is not None:
                doc.body(f"Correct: {correct.label}. {correct.text}")
            for label, option in zip(_OPTION_LABELS, item.options, strict=False):
                if option.rationale:
                    doc.muted(f"{label}. {option.rationale}")
        else:
            doc.body(f"Answer: {item.answer}")
            if item.working:
                doc.muted(f"Working: {item.working}")
            if item.rubric:
                doc.muted(f"Rubric — {item.rubric.criteria}")
                for level in item.rubric.levels:
                    doc.muted(f"  {level.label} ({level.marks} marks): {level.descriptor}")
        doc.spacer(3)


def render_assessment_book_pdf(tkp: TeacherKnowledgePackage) -> bytes:
    classification = tkp.classification
    doc = TkpDocument(
        title=f"Assessment Book — {classification.topic}",
        subtitle=f"{classification.subject} | Grade {classification.grade_band}",
    )
    items = tkp.assessments.items
    _render_questions(doc, items)
    _render_answer_key(doc, items)
    return doc.bytes()
