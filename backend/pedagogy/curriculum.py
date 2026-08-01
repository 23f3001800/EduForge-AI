"""Curriculum board registry.

Resolves a ``curriculum_board`` option into the period length, assessment
emphasis, mark scale, and vocabulary that downstream stages use — so naming a
board changes the *output*, not just a label on it.

The composition rule is the whole design. A ``ProfileStrategy`` says what the
content demands; a board says what the institution expects. They multiply:

    effective mix = profile.assessment_mix * board.assessment_bias   (renormalised)

Multiplying rather than overriding is what keeps a board from conjuring content
the material does not support. A narrative chapter has ``numerical: 0`` in its
profile mix, and zero times any bias is still zero — so a history chapter under
CBSE yields no numerical questions no matter how the board weights them. A board
shifts emphasis within what the content affords; it cannot contradict it.

An unknown board resolves to ``generic`` rather than raising. A teacher typing
"cbse " or "State Board" should get a good package, not a failed job nine stages
in, and the board is an optional hint in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = ["CURRICULA_PATH", "CurriculumProfile", "get_board", "known_boards", "load_boards"]

CURRICULA_PATH = Path(__file__).parent / "curricula.yaml"


@dataclass(frozen=True, slots=True)
class CurriculumProfile:
    """One board's conventions."""

    name: str
    label: str
    description: str
    period_minutes: int
    unit_word: str
    assessment_bias: dict[str, float]
    marks_scale: float
    emphasis: tuple[str, ...]

    @property
    def is_generic(self) -> bool:
        return self.name == "generic"

    def prompt_guidance(self) -> str:
        """Board conventions rendered for a system prompt.

        Empty for ``generic``: an empty string appends cleanly, and saying "no
        particular board applies" would spend tokens telling a model to ignore
        something it was never told.
        """
        if not self.emphasis:
            return ""
        bullets = "\n".join(f"- {line}" for line in self.emphasis)
        return f"Curriculum conventions ({self.label}):\n{bullets}"

    def blend(self, profile_mix: dict[str, float]) -> dict[str, float]:
        """Apply this board's bias to a profile's assessment mix, renormalised.

        Renormalising matters: without it a board whose biases average above 1.0
        would quietly inflate the whole bank, and the item budget is decided
        elsewhere on purpose.
        """
        biased = {
            kind: share * self.assessment_bias.get(kind, 1.0) for kind, share in profile_mix.items()
        }
        total = sum(biased.values())
        if total <= 0:
            # Every kind the content affords was weighted to nothing. Better to
            # hand back the profile's own mix than an empty bank.
            return dict(profile_mix)
        return {kind: value / total for kind, value in biased.items()}

    def period_length(self, requested: int | None = None) -> int:
        """The teacher's own answer wins; the board is the default they did not give."""
        return requested if requested else self.period_minutes


@lru_cache(maxsize=1)
def load_boards(path: Path = CURRICULA_PATH) -> dict[str, CurriculumProfile]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = document.get("boards") or {}
    if "generic" not in raw:
        raise ValueError(f"{path} must define a 'generic' board to fall back to")

    boards: dict[str, CurriculumProfile] = {}
    for name, block in raw.items():
        boards[name] = CurriculumProfile(
            name=name,
            label=(block.get("label") or name).strip(),
            description=(block.get("description") or "").strip(),
            period_minutes=int(block.get("period_minutes") or 40),
            unit_word=(block.get("unit_word") or "chapter").strip(),
            assessment_bias={k: float(v) for k, v in (block.get("assessment_bias") or {}).items()},
            marks_scale=float(block.get("marks_scale") or 1.0),
            emphasis=tuple(block.get("emphasis") or ()),
        )
    return boards


def known_boards() -> list[str]:
    """Selectable board names, generic first. The UI renders this."""
    boards = load_boards()
    rest = sorted(name for name in boards if name != "generic")
    return ["generic", *rest]


def get_board(board: str | None) -> CurriculumProfile:
    """Resolve a board name, tolerantly.

    Matching is case- and whitespace-insensitive because this value is typed by a
    teacher, not chosen from an enum: "cbse", "CBSE " and "Cbse" are the same
    board, and failing on the shift key would be absurd.
    """
    boards = load_boards()
    if not board:
        return boards["generic"]
    wanted = board.strip().casefold()
    for name, profile in boards.items():
        if name.casefold() == wanted:
            return profile
    return boards["generic"]
