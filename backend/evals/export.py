"""Render an evaluation document to PDF and to Markdown.

Both renderers take the dictionary :func:`evals.service.evaluate_package`
returns and compute nothing. A report that re-derived a score while formatting
it could disagree with the screen it was exported from, and a PDF a reviewer
cannot trust to match the dashboard is worse than no PDF.

The page shell comes from :class:`stages.s10_publishing.render.document.TkpDocument`
— A4 margins, numbered footers, and the Devanagari font fallback already wired
up. That is page furniture, not grading logic; the harness's independence from
the artifacts it scores is about *measurement*, and nothing measured crosses
this import.

**What the layout is for.** A reviewer opening this wants three answers in
order: what did it score, what should be fixed, and what could not be checked.
The unmeasurable section is not an appendix — it is placed before the per-stage
detail, because a reader who sees ten green stages and finds out on the last
page that four metrics were never measurable has been misled by the layout even
though every number in it was true.
"""

from __future__ import annotations

from typing import Any

__all__ = ["to_markdown", "to_pdf"]

_SEVERITY_ORDER = ("high", "medium", "low", "info")


def _fmt(score: float | None) -> str:
    return "n/a" if score is None else f"{score:.1f}"


def _band(score: float | None) -> str:
    if score is None:
        return "not measured"
    for floor, label in (
        (85, "exemplary"),
        (70, "classroom-ready"),
        (55, "usable with edits"),
        (35, "needs rework"),
    ):
        if score >= floor:
            return label
    return "not classroom-usable"


# ─────────────────────────────────────────────────────────────────── markdown


def to_markdown(document: dict[str, Any]) -> str:
    """The report as Markdown — for a PR comment or a terminal."""
    summary = document["summary"]
    lines: list[str] = []

    lines.append(f"# Evaluation — {document['subject']} ({document['profile']})")
    lines.append("")
    lines.append(
        f"**Stage score {_fmt(summary['stage_score'])} / 100** "
        f"({_band(summary['stage_score'])}), confidence "
        f"{summary['stage_confidence']:.0%} over {summary['stages_scored']} of "
        f"{summary['stages_total']} stages."
    )
    lines.append("")
    lines.append(
        f"**Rubric score {_fmt(summary['rubric_score'])} / 100** ({summary['rubric_band']}) — "
        "teaching quality, scored separately and deliberately not averaged in."
    )
    lines.append("")
    lines.append(f"Package `{document['package_id']}` · evaluated {document['evaluated_at']}")
    lines.append("")

    comparison = document["comparison"]
    lines.append("## Against history")
    lines.append("")
    lines.append(f"`{comparison['status']}` — {comparison['detail']}")
    lines.append("")
    for entry in comparison.get("regressions", []):
        lines.append(
            f"- **{entry['stage']}** {entry['score']} vs baseline median "
            f"{entry['baseline_median']} ({entry['delta']:+.1f})"
        )
    if comparison.get("regressions"):
        lines.append("")

    lines.append("## Stages")
    lines.append("")
    lines.append("| Stage | Score | Confidence | Measured | Not measurable |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for stage in document["stages"]:
        lines.append(
            f"| {stage['label']} | {_fmt(stage['score'])} | {stage['confidence']:.0%} "
            f"| {stage['measured']} | {stage['not_measurable']} |"
        )
    lines.append("")

    blocked = document["not_measurable"]
    lines.append(f"## Not measurable ({len(blocked)})")
    lines.append("")
    lines.append(
        "These carry no score. Each states what it would take to measure it — a gap in "
        "available data, not in effort."
    )
    lines.append("")
    for entry in blocked:
        lines.append(f"- **{entry['label']}** (`{entry['stage']}`) — {entry['reason']}")
    lines.append("")

    recommendations = document["recommendations"]
    lines.append(f"## Recommendations ({len(recommendations)})")
    lines.append("")
    if not recommendations:
        lines.append("None — every measured metric is at or near its ceiling.")
        lines.append("")
    for rec in recommendations:
        lines.append(
            f"- **[{rec['severity']}]** `{rec['stage']}` / {rec['metric']} "
            f"({_fmt(rec['score'])}) — {rec['action']}"
        )
        lines.append(f"  - *Why it matters:* {rec['impact']}")
    lines.append("")

    lines.append("## Metric detail")
    lines.append("")
    for stage in document["stages"]:
        lines.append(f"### {stage['label']} — {_fmt(stage['score'])}")
        lines.append("")
        for metric in stage["metrics"]:
            score = _fmt(metric["score"])
            lines.append(
                f"- `{metric['key']}` **{score}** ({metric['measurability']}, "
                f"confidence {metric['confidence']:.2f}, weight {metric['weight']:g}) — "
                f"{metric['reasoning']}"
            )
            for ev in metric["evidence"]:
                lines.append(f"  - `{ev['path']}` → {ev['observation']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ──────────────────────────────────────────────────────────────────────── pdf


def to_pdf(document: dict[str, Any]) -> bytes:
    """The report as a PDF, laid out for someone reading it once."""
    from stages.s10_publishing.render.document import TkpDocument

    summary = document["summary"]
    pdf = TkpDocument(
        title="Evaluation report",
        subtitle=f"{document['subject']} · {document['profile']} · "
        f"grade band {document['grade_band']}",
    )

    # ── verdict
    pdf.h1("Verdict")
    pdf.key_value(
        "Stage score",
        f"{_fmt(summary['stage_score'])} / 100  ({_band(summary['stage_score'])})",
    )
    pdf.key_value("Confidence", f"{summary['stage_confidence']:.0%}")
    pdf.key_value("Stages scored", f"{summary['stages_scored']} of {summary['stages_total']}")
    pdf.key_value(
        "Rubric score", f"{_fmt(summary['rubric_score'])} / 100  ({summary['rubric_band']})"
    )
    pdf.key_value("Package", str(document["package_id"]))
    pdf.key_value("Evaluated", str(document["evaluated_at"]))
    pdf.spacer()
    pdf.muted(
        "Two scores, not one. The stage score asks whether each pipeline stage met its "
        "contract; the rubric score asks whether the result is good teaching. They are "
        "reported separately because averaging them would produce a number that answers "
        "neither question."
    )
    pdf.spacer()

    # ── history
    comparison = document["comparison"]
    pdf.h2("Against history")
    pdf.body(comparison["detail"])
    for entry in comparison.get("regressions", []):
        pdf.bullet(
            f"{entry['stage']}: {entry['score']} against a baseline median of "
            f"{entry['baseline_median']} ({entry['delta']:+.1f})"
        )
    pdf.spacer()

    # ── stage table
    pdf.h2("Stages")
    rows = [("Stage", "Score", "Conf.", "Measured", "Unmeasurable")]
    for stage in document["stages"]:
        rows.append(
            (
                stage["label"],
                _fmt(stage["score"]),
                f"{stage['confidence']:.0%}",
                str(stage["measured"]),
                str(stage["not_measurable"]),
            )
        )
    with pdf.table(headings_style=pdf.table_style(), col_widths=(70, 22, 22, 30, 34)) as table:
        for row in rows:
            line = table.row()
            for cell in row:
                line.cell(cell)
    pdf.spacer()

    # ── what could not be measured, before the detail rather than after it
    blocked = document["not_measurable"]
    pdf.h2(f"Not measurable ({len(blocked)})")
    pdf.muted(
        "These metrics carry no score. Each one states what it would take to measure — "
        "a labelled corpus, a classroom trial, response data. Reporting a number here "
        "would mean inventing one."
    )
    pdf.spacer(2)
    for entry in blocked:
        pdf.h3(f"{entry['label']}  ({entry['stage']})")
        pdf.body(entry["reason"])
        pdf.spacer(1)

    # ── recommendations
    recommendations = document["recommendations"]
    pdf.new_section_page()
    pdf.h1(f"Recommendations ({len(recommendations)})")
    if not recommendations:
        pdf.body("None. Every measured metric is at or near its ceiling.")
    for severity in _SEVERITY_ORDER:
        group = [r for r in recommendations if r["severity"] == severity]
        if not group:
            continue
        pdf.h2(severity.title())
        for rec in group:
            pdf.h3(f"{rec['stage_label']} — {rec['metric_label']} ({_fmt(rec['score'])})")
            pdf.body(rec["action"])
            pdf.muted(f"Why it matters: {rec['impact']}")
            pdf.spacer(1)

    # ── per-metric detail
    pdf.new_section_page()
    pdf.h1("Metric detail")
    for stage in document["stages"]:
        pdf.h2(f"{stage['label']} — {_fmt(stage['score'])}")
        for metric in stage["metrics"]:
            pdf.h3(
                f"{metric['label']} — {_fmt(metric['score'])} "
                f"({metric['measurability']}, confidence {metric['confidence']:.2f})"
            )
            pdf.body(metric["reasoning"])
            for ev in metric["evidence"]:
                pdf.bullet(f"{ev['path']} — {ev['observation']}")
            pdf.spacer(1)

    return pdf.bytes()
