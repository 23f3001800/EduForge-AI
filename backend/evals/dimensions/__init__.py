"""The rubric: which dimensions exist, what each is worth, and in what order.

Weights sum to 1.0 and are asserted to, at import time. A rubric whose weights
drift is a rubric that silently re-prioritises what the project is optimising for,
and that is precisely the change nobody notices in a diff.

The weighting says what this project believes matters. Coverage and grounding lead
at 0.15 each — a package that teaches something it never assesses, or cites a
source that does not say what it claims, fails a teacher in a way no amount of
polish elsewhere repairs. Activities follow at 0.14, because activities are what
the class actually experiences. Bloom, sequencing, differentiation and classroom
readiness are lighter individually but total 0.38 together, which is where the
craft is.

Every dimension module exposes the same four constants and one function, so adding
a dimension is a one-line change here and no change anywhere else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from evals.context import EvalContext
from evals.dimensions import (
    activities,
    assessment_integrity,
    bloom,
    classroom,
    coverage,
    differentiation,
    grounding,
    objectives,
    sequencing,
)
from evals.types import DimensionScore, Method

__all__ = ["DIMENSIONS", "Dimension", "run_all"]


@dataclass(frozen=True, slots=True)
class Dimension:
    key: str
    label: str
    weight: float
    method: Method
    run: Callable[[EvalContext], DimensionScore]


#: Order is the order a reviewer should read them in: what the package is for,
#: how it is measured, whether it covers itself, then how well it is made.
_MODULES = (
    objectives,
    bloom,
    coverage,
    sequencing,
    grounding,
    activities,
    differentiation,
    assessment_integrity,
    classroom,
)

DIMENSIONS: tuple[Dimension, ...] = tuple(
    Dimension(
        key=module.KEY,
        label=module.LABEL,
        weight=module.WEIGHT,
        method=module.METHOD,
        run=module.score,
    )
    for module in _MODULES
)

_TOTAL = sum(d.weight for d in DIMENSIONS)
if abs(_TOTAL - 1.0) > 1e-9:  # pragma: no cover - a wiring error, not a runtime path
    raise ValueError(f"dimension weights must sum to 1.0, got {_TOTAL}")


def run_all(ctx: EvalContext) -> tuple[DimensionScore, ...]:
    return tuple(dimension.run(ctx) for dimension in DIMENSIONS)
