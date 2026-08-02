"""The evaluation framework: one shape for every metric, at every stage.

The brief for this framework contains one requirement that governs all the
others: **never generate arbitrary numbers**. That is the right instruction, and
holding to it means confronting something the metric list does not say out loud
— a large share of the metrics anyone would want cannot be measured from the
artifact alone.

Three kinds of thing get asked for, and they are not the same kind of thing:

* **Measured.** Computable from the package with arithmetic. "What fraction of
  concepts carry a citation whose quote appears in the chunk it cites" is a
  number, reproducible, and needs no model. Most of what matters is here.

* **Judged.** Needs reading, not counting. "Is this explanation pitched at grade
  9" cannot be computed, but a model can read it and say why. A judged score
  carries the judge's reasoning as evidence and a lower confidence, because a
  judge is a measurement instrument with error.

* **Not measurable.** No ground truth exists, or the data is not there. "Subject
  accuracy" needs a labelled corpus this project does not have. "Student
  learning effectiveness" needs students. "OCR accuracy" needs OCR, which the
  pipeline deliberately does not do — it rejects scanned pages instead.

The third class is why this module exists rather than a dict of floats. A
framework that reports 0.85 for "teacher satisfaction" has not measured teacher
satisfaction; it has invented a number and dressed it as evidence, and every
downstream average it feeds is then partly fiction. Here, an unmeasurable metric
returns :class:`MetricResult` with ``measurability=NOT_MEASURABLE``, a stated
reason, and **no score at all** — and it is excluded from every aggregate rather
than counted as zero or as perfect.

Saying "we cannot measure this, and here is what it would take" is more useful
to a reviewer than a confident number nobody can defend.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from contracts.primitives import StrictModel

__all__ = [
    "Evidence",
    "Measurability",
    "MetricResult",
    "Recommendation",
    "Severity",
    "StageEvaluation",
    "judged",
    "measured",
    "not_measurable",
]


class Measurability(StrEnum):
    """How a number was arrived at. Reported, never inferred."""

    MEASURED = "measured"
    """Computed from the artifact. Reproducible, no model involved."""

    JUDGED = "judged"
    """A model read it. Carries reasoning; confidence is capped accordingly."""

    NOT_MEASURABLE = "not_measurable"
    """No ground truth, or the data does not exist. Carries no score."""


Severity = Literal["info", "low", "medium", "high"]


class Evidence(StrictModel):
    """What the score was computed from.

    A pointer plus the observation. `path` is a JSON pointer into the package,
    so a reader can go and look — a score whose evidence cannot be located is an
    assertion.
    """

    path: str = Field(description="JSON pointer into the package, e.g. /knowledge/concepts/0.")
    observation: str = Field(min_length=1, description="What was found there.")


class Recommendation(StrictModel):
    """What to change, and what it would buy.

    ``impact`` is stated because a list of twenty improvements with no ordering
    is a list nobody works through.
    """

    action: str = Field(min_length=1)
    impact: str = Field(min_length=1, description="What improves if this is done.")
    severity: Severity = "medium"


class MetricResult(StrictModel):
    """One metric, with everything needed to defend or dispute it.

    ``score`` is 0-100 and **optional**: a metric that could not be measured has
    no score, and the absence is the honest answer. Constructing one with
    ``NOT_MEASURABLE`` and a score is rejected outright — that combination is
    precisely the fabrication this framework exists to prevent.
    """

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    measurability: Measurability
    score: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="How much to trust this score. A judged metric is never 1.0.",
    )
    reasoning: str = Field(min_length=1, description="Why this score, in one or two sentences.")
    evidence: list[Evidence] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    weight: float = Field(default=1.0, ge=0, description="Share of its stage's score.")

    @model_validator(mode="after")
    def _score_matches_measurability(self) -> MetricResult:
        if self.measurability is Measurability.NOT_MEASURABLE:
            if self.score is not None:
                raise ValueError(
                    f"{self.key!r} is NOT_MEASURABLE but carries a score of {self.score}. "
                    "An unmeasurable metric must report no number — inventing one is the "
                    "failure this type exists to make impossible."
                )
            return self

        if self.score is None:
            raise ValueError(f"{self.key!r} is {self.measurability.value} but has no score")

        # A judge is an instrument with error. Claiming certainty for a reading
        # that came from a model misrepresents what kind of number it is.
        if self.measurability is Measurability.JUDGED and self.confidence > 0.9:
            raise ValueError(
                f"{self.key!r} is judged but claims confidence {self.confidence}; "
                "a model's reading is not certain and must not be reported as such"
            )
        return self

    @property
    def counts_toward_score(self) -> bool:
        return self.measurability is not Measurability.NOT_MEASURABLE


class StageEvaluation(StrictModel):
    """Every metric for one stage, and what they add up to."""

    stage: str = Field(min_length=1)
    label: str = Field(min_length=1)
    metrics: list[MetricResult] = Field(default_factory=list)
    #: Things the stage should have produced and did not. Named separately from
    #: recommendations because "missing" and "improvable" are different jobs.
    missing: list[str] = Field(default_factory=list)

    @property
    def scored(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.counts_toward_score]

    @property
    def score(self) -> float | None:
        """Confidence-weighted mean of what could actually be measured.

        Weighting by confidence as well as by declared weight means a judged
        metric pulls less than a measured one of the same nominal weight —
        which is the honest arithmetic, since it is a less certain reading.

        ``None`` when nothing in this stage was measurable. That is not a zero:
        a zero says "this stage is bad", and the truth is "we do not know".
        """
        scored = self.scored
        total = sum(m.weight * m.confidence for m in scored)
        if total <= 0:
            return None
        return sum((m.score or 0.0) * m.weight * m.confidence for m in scored) / total

    @property
    def confidence(self) -> float:
        """How much of this stage we could actually see.

        Deliberately penalised by the metrics we could NOT measure: a stage
        where three of ten metrics are unmeasurable is a stage we know less
        about, and a reader deserves to be told that rather than shown a
        confident average of the seven that worked.
        """
        if not self.metrics:
            return 0.0
        scored = self.scored
        if not scored:
            return 0.0
        mean_confidence = sum(m.confidence for m in scored) / len(scored)
        coverage = len(scored) / len(self.metrics)
        return round(mean_confidence * coverage, 4)

    @property
    def unmeasured(self) -> list[MetricResult]:
        return [m for m in self.metrics if not m.counts_toward_score]


# ─────────────────────────────────────────────────────── constructors
#
# Thin helpers, so the common cases read as what they are at the call site and
# a metric cannot be built half-populated.


def measured(
    key: str,
    label: str,
    score: float,
    reasoning: str,
    *,
    weight: float = 1.0,
    evidence: Sequence[Evidence] = (),
    recommendations: Sequence[Recommendation] = (),
    confidence: float = 1.0,
) -> MetricResult:
    """A metric computed from the artifact."""
    return MetricResult(
        key=key,
        label=label,
        measurability=Measurability.MEASURED,
        score=max(0.0, min(100.0, score)),
        confidence=confidence,
        reasoning=reasoning,
        evidence=list(evidence),
        recommendations=list(recommendations),
        weight=weight,
    )


def not_measurable(key: str, label: str, reason: str, *, needed: str = "") -> MetricResult:
    """A metric this system cannot honestly produce.

    ``needed`` says what would make it measurable — a labelled corpus, a
    classroom trial, an OCR stage. That turns a gap into a next step instead of
    a shrug.
    """
    reasoning = reason if not needed else f"{reason} Measuring it would need: {needed}"
    return MetricResult(
        key=key,
        label=label,
        measurability=Measurability.NOT_MEASURABLE,
        score=None,
        confidence=0.0,
        reasoning=reasoning,
        weight=0.0,
    )


def judged(
    key: str,
    label: str,
    score: float,
    reasoning: str,
    *,
    confidence: float = 0.7,
    weight: float = 1.0,
    evidence: Sequence[Evidence] = (),
    recommendations: Sequence[Recommendation] = (),
) -> MetricResult:
    """A metric a model read and scored. Confidence is capped below certainty."""
    return MetricResult(
        key=key,
        label=label,
        measurability=Measurability.JUDGED,
        score=max(0.0, min(100.0, score)),
        confidence=min(confidence, 0.9),
        reasoning=reasoning,
        evidence=list(evidence),
        recommendations=list(recommendations),
        weight=weight,
    )


def aggregate(evaluations: Sequence[StageEvaluation]) -> dict[str, Any]:
    """Roll stage scores into the cross-system view.

    Stages that measured nothing are excluded rather than counted as zero, and
    the count of excluded stages is reported — an overall score computed from
    six of ten stages is a different claim from one computed from all ten, and a
    reader must be able to tell which they are looking at.
    """
    scored = [e for e in evaluations if e.score is not None]
    if not scored:
        return {
            "score": None,
            "confidence": 0.0,
            "stages_scored": 0,
            "stages_total": len(evaluations),
        }

    weights = [e.confidence or 0.01 for e in scored]
    total = sum(weights)
    return {
        "score": round(
            sum((e.score or 0) * w for e, w in zip(scored, weights, strict=True)) / total, 2
        ),
        "confidence": round(sum(e.confidence for e in scored) / len(scored), 4),
        "stages_scored": len(scored),
        "stages_total": len(evaluations),
    }
