"""Resolve a pedagogy profile into what the harness should expect of a package.

Two sources, joined here and nowhere else:

* ``pedagogy.registry`` — the same strategy the *generator* used. Which item kinds
  belong in the bank, which activity types suit the material, which knowledge
  fields the profile owes. Reading it rather than restating it is what guarantees
  the eval cannot disagree with the pipeline about what a narrative package is
  supposed to contain.
* ``expectations.yaml`` — the reviewer-side thresholds the generator has no use
  for: recall ceilings, higher-order floors, cognitive load per period.

The rule this module enforces on itself is the same one the stages live under: no
branch on a subject name, ever. The only input is the profile string, and an
unrecognised one degrades to ``mixed`` rather than raising — an eval that refuses
to score a package because stage 2 emitted something unexpected has failed at its
one job.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from pedagogy.registry import ProfileStrategy, get_strategy

__all__ = ["EXPECTATIONS_PATH", "Expectations", "ReadabilityWindow", "resolve"]

EXPECTATIONS_PATH = Path(__file__).parent / "expectations.yaml"

_FALLBACK_PROFILE = "mixed"


@dataclass(frozen=True, slots=True)
class ReadabilityWindow:
    """Sentence-length window for a grade band. Reported, never scored."""

    max_words_per_sentence: float
    max_long_word_share: float


@dataclass(frozen=True, slots=True)
class Expectations:
    """Everything the harness expects of one package, given its profile."""

    profile: str
    strategy: ProfileStrategy

    min_distinct_bloom_levels: int
    max_recall_mark_share: float
    higher_order_from: str
    min_higher_order_mark_share: float
    objective_spread_threshold: int

    max_concepts_per_period: int
    min_concepts_per_period: int
    min_time_slots_per_period: int

    min_distinct_activity_types: int
    min_teacher_steps: int

    min_distractor_rationale_share: float
    min_rubric_levels_for_extended: int
    extended_response_marks: int

    @property
    def expected_item_kinds(self) -> dict[str, float]:
        """Kind -> intended share, dropping kinds this profile weights at zero.

        The dropped kinds are the whole point. A narrative profile yields no
        ``numerical`` entry, so the mix metric never looks for one and their
        absence costs nothing.
        """
        mix = self.strategy.assessment_mix
        total = sum(share for share in mix.values() if share > 0)
        if total <= 0:
            return {}
        return {kind: share / total for kind, share in mix.items() if share > 0}

    @property
    def unexpected_item_kinds(self) -> frozenset[str]:
        """Kinds this profile deliberately weights at zero."""
        return frozenset(k for k, share in self.strategy.assessment_mix.items() if share <= 0)

    @property
    def preferred_activity_types(self) -> frozenset[str]:
        return frozenset(k for k, weight in self.strategy.activity_weights.items() if weight > 0)

    @property
    def required_knowledge_fields(self) -> tuple[str, ...]:
        """Knowledge fields this profile owes. Anything else absent is a pass."""
        return self.strategy.required_fields


def _grade_ceiling(grade_band: str) -> int | None:
    """Highest grade named in a band string, or ``None`` if it names none.

    ``"9-10"`` -> 10, ``"6"`` -> 6, ``"UG-1"`` -> None. A band with no numeral is
    not an error; it means the readability window does not apply, and the metric
    reports rather than guesses.
    """
    digits: list[int] = []
    current = ""
    for char in grade_band:
        if char.isdigit():
            current += char
            continue
        if current:
            digits.append(int(current))
            current = ""
    if current:
        digits.append(int(current))
    if not digits:
        return None
    # "UG-1" would otherwise read as grade 1 and impose a primary-school window on
    # undergraduate material, so only plausible school grades count.
    plausible = [d for d in digits if 1 <= d <= 13]
    return max(plausible) if plausible else None


@lru_cache(maxsize=1)
def _document(path: Path = EXPECTATIONS_PATH) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not loaded.get("defaults"):
        raise ValueError(f"no defaults defined in {path}")
    return loaded


@lru_cache(maxsize=8)
def resolve(profile: str) -> Expectations:
    """Expectations for one profile: registry strategy plus reviewer thresholds."""
    document = _document()
    defaults: dict[str, Any] = dict(document["defaults"])
    profiles: dict[str, Any] = document.get("profiles") or {}

    strategy = get_strategy(profile)
    # The registry already degraded an unknown profile to `mixed`; follow it, so a
    # single profile name cannot mean two different things in two files.
    overrides = profiles.get(strategy.name) or profiles.get(_FALLBACK_PROFILE) or {}
    merged = {**defaults, **overrides}

    return Expectations(
        profile=strategy.name,
        strategy=strategy,
        min_distinct_bloom_levels=int(merged["min_distinct_bloom_levels"]),
        max_recall_mark_share=float(merged["max_recall_mark_share"]),
        higher_order_from=str(merged["higher_order_from"]),
        min_higher_order_mark_share=float(merged["min_higher_order_mark_share"]),
        objective_spread_threshold=int(merged["objective_spread_threshold"]),
        max_concepts_per_period=int(merged["max_concepts_per_period"]),
        min_concepts_per_period=int(merged["min_concepts_per_period"]),
        min_time_slots_per_period=int(merged["min_time_slots_per_period"]),
        min_distinct_activity_types=int(merged["min_distinct_activity_types"]),
        min_teacher_steps=int(merged["min_teacher_steps"]),
        min_distractor_rationale_share=float(merged["min_distractor_rationale_share"]),
        min_rubric_levels_for_extended=int(merged["min_rubric_levels_for_extended"]),
        extended_response_marks=int(merged["extended_response_marks"]),
    )


def readability_window(grade_band: str) -> ReadabilityWindow | None:
    """The sentence-length window for a band, or ``None`` when it names no grade."""
    ceiling = _grade_ceiling(grade_band)
    if ceiling is None:
        return None
    for row in _document().get("grade_readability") or []:
        if ceiling <= int(row["up_to_grade"]):
            return ReadabilityWindow(
                max_words_per_sentence=float(row["max_words_per_sentence"]),
                max_long_word_share=float(row["max_long_word_share"]),
            )
    return None
