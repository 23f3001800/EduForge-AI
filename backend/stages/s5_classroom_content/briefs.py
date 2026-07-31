"""The narrowed per-period context.

Stage 5 never sees the whole knowledge base. Each period gets a brief containing
its own concepts and objectives, the definitions, examples, formulae, and
misconceptions attached to those concepts, and one line about the periods either
side of it.

Three things follow from that, and all three are the reason the narrowing exists:

* **Prompts stay small**, so a small model has budget left to write with.
* **A period cannot teach another period's material**, because it is never shown
  it. Cross-period bleed is the failure that makes generated packages read as
  repetitive, and it is prevented structurally here rather than asked for in a
  prompt.
* **Formula fidelity is checkable.** The brief carries exactly the formulae the
  document actually contained for these concepts, which is what lets assembly
  reject invented LaTeX later — and what makes a formula-free period the correct
  output for formula-free material.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = ["PeriodBrief", "build_briefs"]

#: Caps on the supporting material carried into one period's prompt. A brief that
#: grows with the document defeats the point of narrowing it.
MAX_DEFINITIONS = 4
MAX_EXAMPLES = 4
MAX_FORMULAE = 3
MAX_MISCONCEPTIONS = 3


@dataclass(frozen=True, slots=True)
class PeriodBrief:
    """Everything one period's generation is allowed to know."""

    period_no: int
    title: str
    duration_minutes: int
    sequence_rationale: str
    time_allocation: list[dict[str, Any]]
    concepts: list[dict[str, Any]] = field(default_factory=list)
    objectives: list[dict[str, Any]] = field(default_factory=list)
    definitions: list[dict[str, Any]] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    formulae: list[dict[str, Any]] = field(default_factory=list)
    misconceptions: list[dict[str, Any]] = field(default_factory=list)
    previous_title: str | None = None
    previous_concepts: list[str] = field(default_factory=list)
    next_concepts: list[str] = field(default_factory=list)

    @property
    def concept_ids(self) -> list[str]:
        return [str(c.get("concept_id")) for c in self.concepts]

    @property
    def concept_names(self) -> list[str]:
        return [str(c.get("name") or c.get("concept_id")) for c in self.concepts]

    @property
    def objective_ids(self) -> list[str]:
        return [str(o.get("objective_id")) for o in self.objectives]

    def as_prompt(self) -> str:
        """The brief as the model sees it.

        Wrapped by the caller in ``document_block`` — everything below is derived
        from an uploaded file, so it is data, never instruction.
        """
        lines = [
            f"PERIOD {self.period_no}: {self.title}",
            f"LENGTH: {self.duration_minutes} minutes",
            f"WHY THIS PERIOD SITS HERE: {self.sequence_rationale}",
            "",
            "PLANNED SHAPE OF THE PERIOD (keep to these proportions):",
            *(
                f"  - {slot.get('label')} — {slot.get('minutes')} min"
                for slot in self.time_allocation
            ),
            "",
            "CONCEPTS TO TEACH (all of them, and nothing beyond them):",
            *(
                f"  - {c.get('name')} [{c.get('importance', 'supporting')}]: {c.get('summary')}"
                for c in self.concepts
            ),
            "",
            "OBJECTIVES THIS PERIOD MUST LEAVE STUDENTS ABLE TO DO:",
            *(f"  - {o.get('statement')} (Bloom: {o.get('bloom_level')})" for o in self.objectives),
        ]

        if self.definitions:
            lines += [
                "",
                "DEFINITIONS FROM THE SOURCE (use this wording):",
                *(f"  - {d.get('term')}: {d.get('definition')}" for d in self.definitions),
            ]
        if self.formulae:
            lines += [
                "",
                "FORMULAE THE SOURCE STATES (the only ones that may go on the board):",
                *(
                    f"  - {f.get('name') or f.get('plain')}: {f.get('latex')}"
                    for f in self.formulae
                ),
            ]
        else:
            lines += [
                "",
                "FORMULAE: the source states none for these concepts. Do not write any "
                "on the board — an invented formula is worse than a blank board.",
            ]
        if self.examples:
            lines += [
                "",
                "EXAMPLES FROM THE SOURCE:",
                *(f"  - {e.get('title') or 'Example'}: {e.get('body')}" for e in self.examples),
            ]
        if self.misconceptions:
            lines += [
                "",
                "MISCONCEPTIONS STUDENTS BRING TO THIS MATERIAL (anticipate these explicitly):",
                *(
                    f"  - believes: {m.get('statement')} | because: "
                    f"{m.get('why_it_happens')} | correction: {m.get('correction')}"
                    for m in self.misconceptions
                ),
            ]

        lines += [
            "",
            f"TAUGHT BEFORE THIS PERIOD: {', '.join(self.previous_concepts) or 'nothing'}",
        ]
        if self.previous_title:
            lines.append(f"  (the previous period was titled: {self.previous_title})")
        lines.append(f"TAUGHT AFTER THIS PERIOD: {', '.join(self.next_concepts) or 'nothing'}")
        return "\n".join(lines)


def _attached(
    items: Sequence[Mapping[str, Any]], concept_ids: set[str], limit: int
) -> list[dict[str, Any]]:
    """Items whose ``concept_ids`` intersect this period. Order preserved, capped."""
    picked = [
        dict(item)
        for item in items
        if concept_ids & {str(cid) for cid in (item.get("concept_ids") or [])}
    ]
    return picked[:limit]


def build_briefs(knowledge: Mapping[str, Any], plan: Mapping[str, Any]) -> list[PeriodBrief]:
    """One brief per period, narrowed from the knowledge base by the plan."""
    concepts_by_id = {str(c["concept_id"]): dict(c) for c in (knowledge.get("concepts") or [])}
    objectives_by_id = {
        str(o["objective_id"]): dict(o) for o in (knowledge.get("learning_objectives") or [])
    }
    periods = list(plan.get("periods") or [])
    duration = int(plan.get("period_duration_minutes") or 40)

    names_by_period = [
        [
            str(concepts_by_id.get(str(cid), {}).get("name") or cid)
            for cid in (period.get("concept_ids") or [])
        ]
        for period in periods
    ]

    briefs: list[PeriodBrief] = []
    for index, period in enumerate(periods):
        # Ordered ids drive the brief, the set only drives lookups. Iterating a
        # set here would reorder the concepts between runs and make an otherwise
        # deterministic package non-reproducible.
        ordered_ids = [str(cid) for cid in (period.get("concept_ids") or [])]
        ids = set(ordered_ids)
        briefs.append(
            PeriodBrief(
                period_no=int(period.get("period_no") or index + 1),
                title=str(period.get("title") or f"Period {index + 1}"),
                duration_minutes=duration,
                sequence_rationale=str(period.get("sequence_rationale") or ""),
                time_allocation=[dict(slot) for slot in (period.get("time_allocation") or [])],
                concepts=[concepts_by_id[cid] for cid in ordered_ids if cid in concepts_by_id],
                objectives=[
                    objectives_by_id[oid]
                    for oid in (period.get("objective_ids") or [])
                    if oid in objectives_by_id
                ],
                definitions=_attached(knowledge.get("definitions") or [], ids, MAX_DEFINITIONS),
                examples=_attached(knowledge.get("examples") or [], ids, MAX_EXAMPLES),
                formulae=_attached(knowledge.get("formulae") or [], ids, MAX_FORMULAE),
                misconceptions=_attached(
                    knowledge.get("misconceptions") or [], ids, MAX_MISCONCEPTIONS
                ),
                previous_title=(str(periods[index - 1].get("title") or "") if index > 0 else None),
                previous_concepts=names_by_period[index - 1] if index > 0 else [],
                next_concepts=(names_by_period[index + 1] if index + 1 < len(periods) else []),
            )
        )
    return briefs
