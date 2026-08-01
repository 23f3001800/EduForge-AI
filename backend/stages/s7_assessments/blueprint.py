"""Stage 7's deterministic half — the blueprint, and the arithmetic around it.

An assessment bank that is *accumulated* rather than *designed* is the normal
failure: ask a model for twelve questions and it returns nine recall MCQs on the
first concept, nothing on the last two, and a mark total nobody chose. So the
blueprint is computed first, in Python, and it decides every structural property
of every item before a model is called:

* **How many items**, derived from concept and objective count — never fixed.
* **Which kinds**, from the profile's ``assessment_mix``. A narrative profile
  weights ``numerical`` at zero, so no numerical spec is ever created and the
  model is never asked for one. Zero numerical items in a humanities package is
  the designed outcome, not a gap.
* **What each item covers**, by cycling through the objectives so every objective
  is assessed, then sweeping up any concept no objective reached. An objective
  nothing measures is decoration; a concept nothing measures is a coverage hole
  stage 9 will report.
* **Bloom level and marks**, so the distribution is chosen rather than emergent
  and ``total_marks`` is exact by construction.

What the model contributes is the part that is actually writing: the stem, the
distractors and why each is tempting, the answer, and the rubric language.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from contracts.primitives import BloomLevel
from pedagogy.curriculum import CurriculumProfile
from pedagogy.registry import ProfileStrategy

__all__ = [
    "MARKS_BY_KIND",
    "Blueprint",
    "ItemSpec",
    "build_blueprint",
    "rubric_ladder",
]

#: Marks by item kind. A one-mark long answer and a one-mark MCQ would tell a
#: teacher that recall and extended reasoning are worth the same.
MARKS_BY_KIND: Mapping[str, int] = {
    "mcq": 1,
    "short_answer": 3,
    "numerical": 4,
    "long_answer": 6,
}
DEFAULT_MARKS = 2

#: Bank size bounds. Below the floor a bank cannot cover a chapter; above the
#: ceiling nobody sets it, and the generation cost is real.
MIN_ITEMS = 6
MAX_ITEMS = 24

_BLOOM_ORDER: tuple[BloomLevel, ...] = (
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
)

#: A four-option MCQ can test application honestly. It cannot test `create`, and
#: claiming it does inflates the Bloom profile of the whole bank.
MCQ_BLOOM_CEILING = "apply"


def _cap_bloom(level: str, ceiling: str) -> str:
    try:
        return (
            level
            if _BLOOM_ORDER.index(level) <= _BLOOM_ORDER.index(ceiling)  # type: ignore[arg-type]
            else ceiling
        )
    except ValueError:
        return "understand"


@dataclass(frozen=True, slots=True)
class ItemSpec:
    """One item's structure, fixed before the model writes a word of it."""

    item_id: str
    kind: str
    marks: int
    bloom_level: str
    concept_ids: list[str] = field(default_factory=list)
    objective_id: str | None = None
    objective_statement: str = ""


@dataclass(frozen=True, slots=True)
class Blueprint:
    """The designed bank: what will exist, before any of it is written."""

    specs: list[ItemSpec]

    @property
    def total_marks(self) -> int:
        return sum(spec.marks for spec in self.specs)

    def by_kind(self) -> dict[str, list[ItemSpec]]:
        grouped: dict[str, list[ItemSpec]] = {}
        for spec in self.specs:
            grouped.setdefault(spec.kind, []).append(spec)
        return grouped

    def counts(self) -> dict[str, int]:
        return {kind: len(specs) for kind, specs in self.by_kind().items()}


def _scaled_marks(kind: str, board: CurriculumProfile | None) -> int:
    """Marks for one item, scaled by the board's convention.

    Floored at 1: a scale must never produce a zero-mark question, which
    ``AssessmentItem`` rejects and which would be meaningless anyway.
    """
    base = MARKS_BY_KIND.get(kind, DEFAULT_MARKS)
    scale = board.marks_scale if board else 1.0
    return max(1, round(base * scale))


def _item_budget(concept_count: int, objective_count: int) -> int:
    """Bank size from content volume. A fixed count is wrong at both extremes."""
    derived = 2 * concept_count + objective_count
    return max(MIN_ITEMS, min(derived, MAX_ITEMS))


def _kind_plan(
    strategy: ProfileStrategy, budget: int, board: CurriculumProfile | None = None
) -> list[str]:
    """Kinds expanded to one entry per item, interleaved so the bank alternates.

    Interleaving is not cosmetic: an assessment book with every MCQ first and
    every long answer last is harder to sit and harder to mark, and the ordering
    is free to get right here.
    """
    mix = board.blend(strategy.assessment_mix) if board else strategy.assessment_mix
    counts = {kind: round(budget * share) for kind, share in mix.items() if share > 0}
    counts = {k: v for k, v in counts.items() if v > 0}
    if not counts:
        counts = {"short_answer": max(1, budget)}

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    remaining = dict(ordered)
    plan: list[str] = []
    while any(remaining.values()):
        for kind, _ in ordered:
            if remaining.get(kind, 0) > 0:
                plan.append(kind)
                remaining[kind] -= 1
    return plan


def _coverage_targets(
    objectives: Sequence[Mapping[str, Any]],
    concepts: Sequence[Mapping[str, Any]],
) -> list[tuple[str | None, str, list[str], str]]:
    """(objective_id, statement, concept_ids, bloom) in the order items should cover them.

    Objectives come first because every objective must be assessable by at least
    one item. Concepts no objective mentions are appended so they are not silently
    untested — that is a real coverage hole and stage 9 reports it either way.
    """
    known = {str(c["concept_id"]) for c in concepts}
    targets: list[tuple[str | None, str, list[str], str]] = []
    covered: set[str] = set()

    for objective in objectives:
        ids = [str(cid) for cid in (objective.get("concept_ids") or []) if str(cid) in known]
        covered.update(ids)
        targets.append(
            (
                str(objective.get("objective_id")),
                str(objective.get("statement") or ""),
                ids,
                str(objective.get("bloom_level") or "understand"),
            )
        )

    for concept in concepts:
        cid = str(concept["concept_id"])
        if cid not in covered:
            targets.append(
                (None, f"Assess understanding of {concept.get('name', cid)}", [cid], "understand")
            )

    if not targets:
        targets.append((None, "Assess the material covered", [], "understand"))
    return targets


def build_blueprint(
    knowledge: Mapping[str, Any],
    strategy: ProfileStrategy,
    board: CurriculumProfile | None = None,
) -> Blueprint:
    """Design the bank: count, kinds, coverage, Bloom levels, and marks.

    ``board`` shifts emphasis within what the profile already allows, and
    scales the marks. It can never introduce a kind the content does not
    support: the blend multiplies through a profile share of zero, so a
    narrative chapter still yields no numerical items under any board.
    """
    concepts = list(knowledge.get("concepts") or [])
    objectives = list(knowledge.get("learning_objectives") or [])

    budget = _item_budget(len(concepts), len(objectives))
    kinds = _kind_plan(strategy, budget, board)
    targets = _coverage_targets(objectives, concepts)

    specs: list[ItemSpec] = []
    for index, kind in enumerate(kinds):
        objective_id, statement, concept_ids, bloom = targets[index % len(targets)]
        level = _cap_bloom(bloom, MCQ_BLOOM_CEILING) if kind == "mcq" else bloom
        specs.append(
            ItemSpec(
                item_id=f"item_{index + 1:02d}",
                kind=kind,
                marks=_scaled_marks(kind, board),
                bloom_level=level,
                concept_ids=list(concept_ids),
                objective_id=objective_id,
                objective_statement=statement,
            )
        )
    return Blueprint(specs=specs)


def rubric_ladder(marks: int, answer: str) -> list[dict[str, Any]]:
    """A mark ladder whose descriptors discriminate, derived from the expected answer.

    ``Rubric`` rejects levels that all award the same marks, and rightly: a rubric
    that cannot separate two performances is a restatement of the question. This
    is the fallback used when the model's levels collapse — it still has to tell a
    marker what each level looks like, so the descriptors reference the answer
    rather than saying "good", "adequate", "poor".
    """
    gist = answer.strip().rstrip(".")
    short = gist if len(gist) <= 90 else gist[:87].rstrip() + "..."
    if marks <= 1:
        return [
            {"label": "Correct", "descriptor": f"States that {short}.", "marks": 1},
            {"label": "Incorrect", "descriptor": "States something else, or nothing.", "marks": 0},
        ]
    if marks == 2:
        return [
            {"label": "Complete", "descriptor": f"States that {short}, with a reason.", "marks": 2},
            {
                "label": "Partial",
                "descriptor": f"States that {short} without a reason.",
                "marks": 1,
            },
        ]
    return [
        {
            "label": "Complete",
            "descriptor": f"States that {short}, and justifies it correctly throughout.",
            "marks": marks,
        },
        {
            "label": "Partial",
            "descriptor": f"Reaches {short} but the justification is incomplete or has one error.",
            "marks": max(1, marks // 2),
        },
        {
            "label": "Minimal",
            "descriptor": "Makes a relevant start — a correct first step or a correct term — "
            "but does not reach the answer.",
            "marks": 1,
        },
    ]
