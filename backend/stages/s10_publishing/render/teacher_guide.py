"""Teacher Guide PDF — the in-classroom document (ArtifactKind `teacher_guide_pdf`).

Where the lesson plan is read once before the unit, this is read again before
every period: the entry ticket, the minute-by-minute script, what goes on the
board, the activities that period runs, the checkpoint questions, and how to
differentiate — everything FR-06/FR-07 ask a generated package to carry so a
teacher can walk in and teach without having pre-read the source chapter.

Learning gaps close the document rather than opening it: a teacher wants the
period content first and the "what will go wrong and how do I fix it" briefing
as reference material behind it, not ahead of the thing they are about to teach.
"""

from __future__ import annotations

from contracts.content import Activity, PeriodContent
from contracts.tkp import TeacherKnowledgePackage
from stages.s10_publishing.render.document import TkpDocument

__all__ = ["render_teacher_guide_pdf"]


def _activities_for(period_no: int, activities: list[Activity]) -> list[Activity]:
    return [a for a in activities if a.period_no == period_no]


def _render_period(doc: TkpDocument, content: PeriodContent, activities: list[Activity]) -> None:
    doc.h1(f"Period {content.period_no}")

    # The two tickets and the mentor moment are set in tinted blocks rather
    # than run in with everything else. All three are things a teacher reaches
    # for at a specific moment — the first two minutes, the last two, and the
    # point where the class needs a story — so they have to be findable without
    # reading the page. The bulk of the period is script, which is read in
    # order and needs no such marker.
    doc.callout("Entry ticket", content.entry_ticket.prompt)
    doc.muted(f"Expected response: {content.entry_ticket.expected_response}")
    doc.spacer()

    doc.h2("Teacher Script")
    for segment in content.teacher_script:
        doc.h3(f"{segment.minute_start}-{segment.minute_end} min: {segment.heading}")
        doc.body(segment.speaker_notes)
        if segment.board_action:
            doc.muted(f"Board: {segment.board_action}")
        if segment.anticipated_questions:
            for question in segment.anticipated_questions:
                doc.bullet(f"Anticipate: {question}")
        doc.spacer(2)

    doc.h2("Blackboard Notes")
    notes = content.blackboard_notes
    for heading in notes.headings:
        doc.bullet(heading)
    for point in notes.bullet_points:
        doc.bullet(point)
    for diagram in notes.diagrams_to_draw:
        doc.bullet(f"Diagram: {diagram}")
    for formula in notes.formulae_latex:
        doc.bullet(f"Formula: {formula}")
    doc.spacer()

    period_activities = _activities_for(content.period_no, activities)
    if period_activities:
        doc.h2("Activities")
        for activity in period_activities:
            doc.h3(f"{activity.title} ({activity.duration_minutes} min, {activity.type})")
            if activity.materials:
                doc.muted("Materials: " + ", ".join(activity.materials))
            for step in activity.teacher_instructions:
                doc.bullet(step)
            if activity.student_instructions:
                doc.muted("Student instructions:")
                for step in activity.student_instructions:
                    doc.bullet(step)
            doc.muted("Success looks like: " + "; ".join(activity.success_criteria))
            doc.muted(f"Support: {activity.differentiation.support}")
            doc.muted(f"Extension: {activity.differentiation.extension}")
            doc.spacer(2)

    doc.h2("Checkpoint Questions")
    for question in content.checkpoint_questions:
        doc.bullet(f"[{question.bloom_level}] {question.question}")
        doc.muted(f"   Expected: {question.expected_answer}")
    doc.spacer()

    doc.callout("Exit ticket", content.exit_ticket.prompt)
    doc.muted(f"Success indicator: {content.exit_ticket.success_indicator}")
    doc.spacer()

    doc.h2("Homework")
    for task in content.homework.tasks:
        doc.bullet(task)
    doc.muted(f"Estimated time: {content.homework.estimated_minutes} min")
    doc.spacer()

    doc.callout(
        f"Mentor moment — {content.mentor_moment.title}", content.mentor_moment.story
    )
    doc.muted(f"Takeaway: {content.mentor_moment.takeaway}")


def render_teacher_guide_pdf(tkp: TeacherKnowledgePackage) -> bytes:
    classification = tkp.classification
    doc = TkpDocument(
        title=f"Teacher Guide — {classification.topic}",
        subtitle=f"{classification.subject} | Grade {classification.grade_band}",
    )

    periods_by_no = sorted(tkp.classroom_content, key=lambda c: c.period_no)
    if not periods_by_no:
        doc.muted("No classroom content was generated for this package.")
    for content in periods_by_no:
        doc.new_section_page()
        _render_period(doc, content, tkp.activities)

    if tkp.learning_gaps:
        doc.new_section_page()
        doc.h1("Learning Gaps & Misconceptions")
        for gap in tkp.learning_gaps:
            doc.h2(f"[{gap.severity}] {gap.misconception}")
            for diagnostic in gap.diagnostic_questions:
                doc.bullet(f"Diagnostic: {diagnostic.question}")
                doc.muted(f"   Reveals: {diagnostic.reveals}")
            for step in gap.remediation:
                doc.bullet(f"Remediation: {step.action}")
                doc.muted(f"   Why: {step.rationale}")
            doc.spacer()

    return doc.bytes()
