"""Lesson Plan PDF — the schedule-level document (FR-11 / ArtifactKind `lesson_plan_pdf`).

This is the document a teacher hands to a coordinator or keeps as a syllabus
record: what the unit covers, how it is paced across periods, and what a
student should be able to do by the end. It is deliberately NOT the minute-by-
minute script — that is the teacher guide (`teacher_guide.py`). Splitting them
mirrors how the two are actually used: the plan is read once before the unit
starts, the guide is read again before every single period.

Formulae are rendered only when the knowledge base has any. A narrative
document legitimately has zero (`KnowledgeBase.formulae` docstring), and
printing an empty "Formulae" heading followed by nothing would look like a
missing section rather than an absent one.
"""

from __future__ import annotations

from contracts.tkp import TeacherKnowledgePackage
from stages.s10_publishing.render.document import TkpDocument

__all__ = ["render_lesson_plan_pdf"]


def render_lesson_plan_pdf(tkp: TeacherKnowledgePackage) -> bytes:
    classification = tkp.classification
    doc = TkpDocument(
        title=f"Lesson Plan — {classification.topic}",
        subtitle=(
            f"{classification.subject} | Grade {classification.grade_band} | "
            f"{classification.difficulty.capitalize()}"
            + (f" | {classification.chapter}" if classification.chapter else "")
        ),
    )

    doc.h1("Overview")
    doc.key_value("Subject", classification.subject)
    doc.key_value("Grade band", classification.grade_band)
    doc.key_value("Topic", classification.topic)
    if classification.chapter:
        doc.key_value("Chapter", classification.chapter)
    doc.key_value("Source document", tkp.source.title or tkp.source.filename)
    doc.key_value(
        "Periods",
        f"{tkp.teaching_plan.total_periods} x {tkp.teaching_plan.period_duration_minutes} min",
    )
    doc.spacer()

    doc.h1("Learning Objectives")
    if tkp.knowledge.learning_objectives:
        for objective in tkp.knowledge.learning_objectives:
            doc.bullet(f"[{objective.bloom_level}] {objective.statement}")
    else:
        doc.muted("No learning objectives were extracted for this document.")
    doc.spacer()

    doc.h1("Period-by-Period Plan")
    concepts_by_id = {c.concept_id: c for c in tkp.knowledge.concepts}
    objectives_by_id = {o.objective_id: o for o in tkp.knowledge.learning_objectives}
    for period in tkp.teaching_plan.periods:
        doc.h2(f"Period {period.period_no}: {period.title}")
        concept_names = ", ".join(
            concepts_by_id[cid].name if cid in concepts_by_id else cid for cid in period.concept_ids
        )
        doc.key_value("Concepts", concept_names or "—")
        objective_lines = "; ".join(
            objectives_by_id[oid].statement if oid in objectives_by_id else oid
            for oid in period.objective_ids
        )
        doc.key_value("Objectives", objective_lines or "—")
        doc.key_value(
            "Time allocation",
            ", ".join(f"{slot.label} ({slot.minutes} min)" for slot in period.time_allocation),
        )
        doc.key_value("Why this order", period.sequence_rationale)
        doc.spacer()

    if tkp.teaching_plan.unmapped_objective_ids:
        doc.muted(
            "Objectives not mapped to any period: "
            + ", ".join(tkp.teaching_plan.unmapped_objective_ids)
        )
        doc.spacer()

    doc.h1("Concepts Taught")
    with doc.table(headings_style=doc.table_style()) as table:
        header = table.row()
        for label in ("Concept", "Importance", "Summary"):
            header.cell(label)
        for concept in tkp.knowledge.concepts:
            row = table.row()
            row.cell(concept.name)
            row.cell(concept.importance)
            row.cell(concept.summary)

    # Legitimately absent for narrative content (KnowledgeBase.formulae docstring):
    # omitted entirely rather than rendered as an empty heading.
    if tkp.knowledge.formulae:
        doc.spacer()
        doc.h1("Formulae")
        for formula in tkp.knowledge.formulae:
            label = formula.name or formula.plain
            doc.h3(label)
            doc.body(formula.plain)
            if formula.variables:
                doc.muted(
                    "where "
                    + "; ".join(
                        f"{v.symbol} = {v.meaning}" + (f" ({v.unit})" if v.unit else "")
                        for v in formula.variables
                    )
                )
            doc.spacer(2)

    return doc.bytes()
