"""Pedagogy strategy registry.

Resolves a ``pedagogy_profile`` into the prompt emphasis, activity weighting,
assessment mix, and validation ruleset that every downstream stage uses.

The rule this package exists to enforce: **no stage may branch on a subject
name.** "Physics" and "History" are labels a human reads; the profile is what the
code acts on. A subject-name conditional anywhere in `stages/` is a defect, and
``test_no_subject_names_in_stage_code`` fails the build for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from contracts.primitives import PedagogyProfile

__all__ = ["PROFILES_PATH", "ProfileStrategy", "get_strategy", "load_profiles"]

PROFILES_PATH = Path(__file__).parent / "profiles.yaml"


@dataclass(frozen=True, slots=True)
class ProfileStrategy:
    """Everything the pipeline needs to adapt to one kind of content."""

    name: PedagogyProfile
    description: str
    emphasis: tuple[str, ...]
    activity_weights: dict[str, int]
    assessment_mix: dict[str, float]
    required_fields: tuple[str, ...]
    expects_numerical_items: bool

    def prompt_guidance(self) -> str:
        """Emphasis rendered for a system prompt."""
        bullets = "\n".join(f"- {line}" for line in self.emphasis)
        return f"Pedagogical approach for this material:\n{bullets}"

    def preferred_activities(self, limit: int = 5) -> list[str]:
        """Activity types in descending suitability for this content."""
        ranked = sorted(self.activity_weights.items(), key=lambda kv: (-kv[1], kv[0]))
        return [name for name, _ in ranked[:limit]]

    def target_item_counts(self, total: int) -> dict[str, int]:
        """Split an item budget across kinds, dropping kinds weighted at zero.

        A narrative profile yields no numerical items at all — that absence is
        the correct output, not a gap to be filled.
        """
        counts = {
            kind: round(total * share) for kind, share in self.assessment_mix.items() if share > 0
        }
        return {k: v for k, v in counts.items() if v > 0}


@lru_cache(maxsize=1)
def load_profiles(path: Path = PROFILES_PATH) -> dict[str, ProfileStrategy]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = document.get("profiles") or {}
    if not raw:
        raise ValueError(f"no profiles defined in {path}")

    strategies: dict[str, ProfileStrategy] = {}
    for name, block in raw.items():
        validation = block.get("validation") or {}
        strategies[name] = ProfileStrategy(
            name=name,  # type: ignore[arg-type]
            description=(block.get("description") or "").strip(),
            emphasis=tuple(block.get("emphasis") or ()),
            activity_weights=dict(block.get("activity_weights") or {}),
            assessment_mix=dict(block.get("assessment_mix") or {}),
            required_fields=tuple(validation.get("requires") or ()),
            expects_numerical_items=bool(validation.get("expects_numerical_items", False)),
        )
    return strategies


def get_strategy(profile: str) -> ProfileStrategy:
    """Resolve a profile, falling back to ``mixed`` for anything unrecognised.

    Falling back rather than raising is deliberate: an unexpected profile should
    degrade to the least-assertive strategy, not fail a job nine stages deep.
    """
    profiles = load_profiles()
    return profiles.get(profile) or profiles["mixed"]
