"""The rubric: which dimensions exist, what each is worth, and in what order.

The weighting says what this project believes matters, and it was re-derived after
the rubric was measured against deliberately broken packages rather than reasoned
about in the abstract. The previous split spent 0.08 on classroom readiness and
0.12 on assessment integrity, which meant the two dimensions that decide whether a
teacher can walk into a room and teach the material carried a fifth of the score
between them — while a package could pass every other check by being well-formed
about the wrong content.

What leads now:

* **Assessment integrity and classroom readiness at 0.15 each.** These are where
  a package is used or abandoned, and they are where padding hides.
* **Coverage and grounding at 0.13 each.** A package that teaches something it
  never assesses, or cites a source that does not say what it claims, fails a
  teacher in a way no amount of polish elsewhere repairs.
* **Content fidelity at 0.10, new.** Nothing else in this rubric reads what the
  package says it is about. A package labelled History that taught Newton's Laws
  scored 0.874 and banded exemplary; that is the hole this closes.
* **Bloom down to 0.05.** It was over-weighted for what it measures — the mark
  distribution across levels is a real property but a narrow one, and it moved
  more than the entire teachability of the classroom content.
* **Period integrity at 0.04, new.** Small on purpose: it catches one specific
  failure precisely rather than a broad one vaguely.

Weights sum to 1.0 and are asserted to, at import time. A rubric whose weights
drift is a rubric that silently re-prioritises what the project is optimising for,
and that is precisely the change nobody notices in a diff.

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
    content_fidelity,
    coverage,
    differentiation,
    grounding,
    objectives,
    period_integrity,
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


#: Order is the order a reviewer should read them in: what the package is about,
#: what it is for, how it is measured, whether it covers itself, then how well it
#: is made. Content fidelity leads because every dimension after it presumes an
#: answer to "is this package about the right document at all?"
_MODULES = (
    content_fidelity,
    objectives,
    bloom,
    coverage,
    sequencing,
    grounding,
    activities,
    differentiation,
    assessment_integrity,
    classroom,
    period_integrity,
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
