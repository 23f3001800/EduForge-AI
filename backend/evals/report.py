"""Render a report a human will actually read.

Two audiences, two formats. JSON is for diffing scores between runs — that is how
you tell whether a prompt change improved anything, and "I read one output and it
looked good" is not an answer. Markdown is for the reviewer who opens
``samples/`` first: the number, then what moved it, then the findings with a JSON
pointer each so every criticism is actionable.

The ``absent by design`` block is not decoration. A reviewer scanning a narrative
package sees ``formulae: 0`` and reasonably wonders whether something failed; the
report says, in words, that it did not.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from evals.types import DimensionScore, EvalReport

__all__ = ["to_json", "to_markdown", "to_table"]

_BAR_WIDTH = 20


def _bar(value: float) -> str:
    filled = round(value * _BAR_WIDTH)
    return "#" * filled + "." * (_BAR_WIDTH - filled)


def _fmt(score: float | None) -> str:
    return "  n/a" if score is None else f"{score:5.2f}"


def to_json(report: EvalReport, *, indent: int = 2) -> str:
    return json.dumps(report.as_dict(), indent=indent, sort_keys=True, ensure_ascii=False) + "\n"


def to_table(reports: Iterable[EvalReport]) -> str:
    """One line per package — the view for comparing runs at a glance."""
    rows = ["  overall  band                  profile       subject"]
    for report in reports:
        rows.append(
            f"  {report.overall:5.2f}    {report.band:<20}  {report.profile:<12}  {report.subject}"
        )
    return "\n".join(rows)


def _dimension_rows(dimensions: Iterable[DimensionScore]) -> list[str]:
    rows = [
        "| Dimension | Score | Weight | Method | Notes |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for dimension in dimensions:
        note = dimension.reason if not dimension.applicable else ""
        rows.append(
            f"| {dimension.label} | {_fmt(dimension.score)} | {dimension.weight:.2f} "
            f"| {dimension.method} | {note} |"
        )
    return rows


def to_markdown(report: EvalReport, *, title: str | None = None) -> str:
    """The reviewer's view: verdict, breakdown, what is correctly absent, findings."""
    lines: list[str] = []
    heading = title or f"Quality evaluation — {report.subject} ({report.profile})"
    lines.append(f"# {heading}")
    lines.append("")
    lines.append(f"**{report.overall:.2f} / 1.00 — {report.band}**")
    lines.append("")
    lines.append(
        f"`{_bar(report.overall)}`  profile `{report.profile}`, grade band "
        f"`{report.grade_band}`, package `{report.package_id}`"
    )
    lines.append("")
    lines.append(
        "Deterministic metrics only."
        if not report.judged
        else f"Includes judged metrics (LLM profile `{report.llm_profile}`)."
    )
    if report.judged and not report.transferable:
        lines.append("")
        lines.append(
            "> **Not comparable.** Judged under a non-evaluation profile; these "
            "numbers do not transfer to a production run."
        )
    lines.append("")

    lines += _dimension_rows(report.dimensions)
    lines.append("")

    lines.append("## Sub-metrics")
    lines.append("")
    for dimension in report.dimensions:
        if not dimension.applicable:
            lines.append(f"**{dimension.label}** — not applicable: {dimension.reason}")
            lines.append("")
            continue
        lines.append(f"**{dimension.label}** — {_fmt(dimension.score)}")
        lines.append("")
        for metric in dimension.metrics:
            scored = f"weight {metric.weight:.2f}" if metric.weight else "reported, not scored"
            value = "     " if not metric.weight else f"{metric.value:.2f}"
            lines.append(f"- `{metric.key}` {value} ({scored}) — {metric.note}")
        lines.append("")

    if report.absent_by_design:
        lines.append("## Absent by design")
        lines.append("")
        lines.append(
            "Content this profile does not owe. Each line below is a **pass**, "
            "recorded so that an empty field is not mistaken for a failure."
        )
        lines.append("")
        for note in report.absent_by_design:
            lines.append(f"- {note}")
        lines.append("")

    findings = report.findings()
    lines.append(f"## Findings ({len(findings)})")
    lines.append("")
    if not findings:
        lines.append("None.")
        lines.append("")
    for dimension in report.dimensions:
        if not dimension.findings:
            continue
        lines.append(f"### {dimension.label}")
        lines.append("")
        for finding in dimension.findings:
            lines.append(f"- **{finding.code}** `{finding.path}` — {finding.detail}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
