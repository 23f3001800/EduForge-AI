"""Score shapes for the quality harness.

Plain dataclasses rather than contract models: nothing here crosses a process
boundary or comes back from a model, and the harness must stay independent of the
artifacts it grades. A metric that imported the code it measures would drift with
it silently, which is the one thing an eval may not do.

Three ideas are load-bearing:

* A :class:`DimensionScore` is a *weighted bundle of sub-metrics*, not a single
  number a reviewer has to take on faith. Every score decomposes into named
  measurements, and every deduction carries a JSON pointer to the thing that
  caused it, so "activities scored 0.62" is always answerable with "because of
  these four activities".
* ``applicable=False`` is not zero. A dimension that cannot be measured (no source
  chunks supplied, no assessment bank) drops out of the weighted mean instead of
  dragging it down — scoring an absent input as a failure is how a harness starts
  punishing content for being a different shape.
* A metric with ``weight=0.0`` is reported but does not score. That is where
  proxies live (readability, for one): visible to a reviewer, never silently
  deciding a grade.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "BANDS",
    "DimensionScore",
    "EvalReport",
    "Finding",
    "Judgements",
    "Method",
    "Metric",
    "band_for",
]

#: How a dimension was measured. ``hybrid`` means deterministic by default with an
#: optional judged component that only engages when judgements are supplied.
Method = Literal["deterministic", "hybrid", "judged"]

#: Score bands, high to low. Named for what a teacher would do with the package
#: rather than for a letter grade — "0.63" means nothing without this ladder.
BANDS: tuple[tuple[float, str], ...] = (
    (0.85, "exemplary"),
    (0.70, "classroom-ready"),
    (0.55, "usable with edits"),
    (0.35, "needs rework"),
    (0.00, "not classroom-usable"),
)


def band_for(score: float) -> str:
    for floor, label in BANDS:
        if score >= floor:
            return label
    return BANDS[-1][1]


@dataclass(frozen=True, slots=True)
class Finding:
    """One concrete thing wrong, addressed to whoever has to fix it.

    ``path`` is a JSON pointer into the package. A finding without one is an
    opinion; a finding with one is a work item.
    """

    code: str
    path: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Metric:
    """One named measurement in ``[0, 1]``, with the weight it carries."""

    key: str
    value: float
    weight: float = 1.0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": round(self.value, 4),
            "weight": self.weight,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class DimensionScore:
    """One rubric dimension: its sub-metrics, its findings, and its verdict."""

    key: str
    label: str
    method: Method
    weight: float
    metrics: tuple[Metric, ...] = ()
    findings: tuple[Finding, ...] = ()
    applicable: bool = True
    reason: str = ""

    @property
    def score(self) -> float | None:
        """Weighted mean of the scoring metrics, or ``None`` when not applicable."""
        if not self.applicable:
            return None
        scoring = [m for m in self.metrics if m.weight > 0]
        total = sum(m.weight for m in scoring)
        if total <= 0:
            return None
        return sum(m.value * m.weight for m in scoring) / total

    def as_dict(self) -> dict[str, Any]:
        score = self.score
        return {
            "key": self.key,
            "label": self.label,
            "method": self.method,
            "weight": self.weight,
            "score": None if score is None else round(score, 4),
            "applicable": self.applicable,
            "reason": self.reason,
            "metrics": [m.as_dict() for m in self.metrics],
            "findings": [f.as_dict() for f in self.findings],
        }


@dataclass(frozen=True, slots=True)
class Judgements:
    """Optional verdicts from the LLM judge, keyed by the thing they judged.

    Absent keys mean "not judged" and leave the deterministic estimate in place.
    Keeping this a plain mapping — rather than letting the judge write scores
    directly — is what stops a model call from quietly becoming load-bearing: the
    deterministic result is always computed first and is always the fallback.
    """

    objective_measurable: Mapping[str, bool] = field(default_factory=dict)
    criterion_observable: Mapping[str, bool] = field(default_factory=dict)
    differentiation_specific: Mapping[str, bool] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(
            self.objective_measurable or self.criterion_observable or self.differentiation_specific
        )


@dataclass(frozen=True, slots=True)
class EvalReport:
    """The whole verdict on one package."""

    package_id: str
    profile: str
    subject: str
    grade_band: str
    dimensions: tuple[DimensionScore, ...]
    absent_by_design: tuple[str, ...] = ()
    llm_profile: str = "unknown"
    judged: bool = False

    @property
    def overall(self) -> float:
        applicable = [d for d in self.dimensions if d.score is not None]
        total = sum(d.weight for d in applicable)
        if total <= 0:
            return 0.0
        return sum((d.score or 0.0) * d.weight for d in applicable) / total

    @property
    def band(self) -> str:
        return band_for(self.overall)

    @property
    def transferable(self) -> bool:
        """Whether these numbers may be compared against another run's.

        Deterministic metrics transfer anywhere. Anything the judge touched only
        transfers within the profile it was produced under, which is why the flag
        is recorded on the report rather than argued about later.
        """
        from core.llm.router import EVAL_PROFILE

        return (not self.judged) or self.llm_profile == EVAL_PROFILE

    def dimension(self, key: str) -> DimensionScore:
        for dimension in self.dimensions:
            if dimension.key == key:
                return dimension
        raise KeyError(f"no such dimension: {key!r}; have {[d.key for d in self.dimensions]}")

    def findings(self) -> list[Finding]:
        return [f for d in self.dimensions for f in d.findings]

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "profile": self.profile,
            "subject": self.subject,
            "grade_band": self.grade_band,
            "overall": round(self.overall, 4),
            "band": self.band,
            "judged": self.judged,
            "llm_profile": self.llm_profile,
            "transferable": self.transferable,
            "absent_by_design": list(self.absent_by_design),
            "dimensions": [d.as_dict() for d in self.dimensions],
        }


def mean(values: Sequence[float]) -> float:
    """Mean that answers 1.0 for an empty sequence.

    Used where "nothing to check" means "nothing wrong" — an activity list with no
    materials has no unrealistic materials in it.
    """
    return sum(values) / len(values) if values else 1.0
