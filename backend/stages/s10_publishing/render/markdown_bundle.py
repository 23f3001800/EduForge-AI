"""Markdown bundle — a plain-text export of the whole package (ArtifactKind `markdown_bundle`).

The PDFs are for printing and handing out; this is for everything else a
teacher or a downstream tool might do with the package — paste into a Google
Doc, diff between two regenerations, feed to another program. One file, in
reading order: overview, plan, classroom content, assessments (questions then
answer key, same separation the PDF enforces), and gaps.

Plain string building, not a template engine: the codebase does not use one
elsewhere (`jinja2` sits in an unused optional extra), and a package this
shaped is a handful of loops, not a page layout — a template buys nothing here.
"""

from __future__ import annotations

from contracts.tkp import TeacherKnowledgePackage

__all__ = ["render_markdown_bundle"]


def _heading(level: int, text: str) -> str:
    return f"{'#' * level} {text}\n"


def render_markdown_bundle(tkp: TeacherKnowledgePackage) -> bytes:
    c = tkp.classification
    lines: list[str] = []
    add = lines.append

    add(_heading(1, f"{c.topic} — Teacher Knowledge Package"))
    add(f"*{c.subject} | Grade {c.grade_band} | {c.difficulty}*")
    if c.chapter:
        add(f"\n**Chapter:** {c.chapter}")
    add(f"\n**Source:** {tkp.source.title or tkp.source.filename}\n")

    add(_heading(2, "Learning Objectives"))
    for objective in tkp.knowledge.learning_objectives:
        add(f"- [{objective.bloom_level}] {objective.statement}")
    add("")

    add(_heading(2, "Teaching Plan"))
    concepts_by_id = {concept.concept_id: concept for concept in tkp.knowledge.concepts}
    for period in tkp.teaching_plan.periods:
        add(_heading(3, f"Period {period.period_no}: {period.title}"))
        names = ", ".join(
            concepts_by_id[cid].name if cid in concepts_by_id else cid for cid in period.concept_ids
        )
        add(f"- **Concepts:** {names}")
        add(
            "- **Time:** "
            + ", ".join(f"{slot.label} ({slot.minutes} min)" for slot in period.time_allocation)
        )
        add(f"- **Rationale:** {period.sequence_rationale}\n")

    if tkp.knowledge.formulae:
        add(_heading(2, "Formulae"))
        for formula in tkp.knowledge.formulae:
            add(f"- **{formula.name or formula.plain}**: `{formula.latex}` — {formula.plain}")
        add("")

    add(_heading(2, "Classroom Content"))
    activities_by_period: dict[int, list[str]] = {}
    for activity in tkp.activities:
        activities_by_period.setdefault(activity.period_no, []).append(activity.title)
    for content in sorted(tkp.classroom_content, key=lambda item: item.period_no):
        add(_heading(3, f"Period {content.period_no}"))
        add(f"- **Entry ticket:** {content.entry_ticket.prompt}")
        for segment in content.teacher_script:
            add(f"  - {segment.minute_start}-{segment.minute_end} min: {segment.heading}")
        titles = activities_by_period.get(content.period_no) or []
        if titles:
            add(f"- **Activities:** {', '.join(titles)}")
        add(f"- **Exit ticket:** {content.exit_ticket.prompt}")
        add("")

    add(_heading(2, "Assessment — Questions"))
    for index, item in enumerate(tkp.assessments.items, start=1):
        add(f"{index}. ({item.marks} marks) {item.stem}")
        if item.kind == "mcq" and item.options:
            for label, option in zip("ABCDEFGH", item.options, strict=False):
                add(f"   - {label}. {option.text}")
    add("")

    add(_heading(2, "Assessment — Answer Key"))
    add("*Teacher copy — not for distribution to students.*\n")
    for index, item in enumerate(tkp.assessments.items, start=1):
        if item.kind == "mcq" and item.options:
            correct = next((o for o in item.options if o.is_correct), None)
            add(f"{index}. {correct.label}. {correct.text}" if correct else f"{index}. —")
        else:
            add(f"{index}. {item.answer}")
    add("")

    if tkp.learning_gaps:
        add(_heading(2, "Learning Gaps & Misconceptions"))
        for gap in tkp.learning_gaps:
            add(f"- **[{gap.severity}]** {gap.misconception}")
            for step in gap.remediation:
                add(f"  - Remediation: {step.action}")
        add("")

    return "\n".join(lines).encode("utf-8")
