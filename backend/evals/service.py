"""One entry point that runs everything and returns one document.

Three things exist independently and are useless apart: the rubric
(:mod:`evals.dimensions`, "is this good teaching?"), the per-stage checks
(:mod:`evals.stagewise`, "did stage *n* do its job?"), and the history
(:mod:`evals.store`, "is this better or worse than before?"). A caller that has
to assemble those itself will assemble them three different ways, so it is
assembled once here.

The returned document is the single shape everything downstream renders — the
REST API returns it verbatim, the dashboard reads it, the PDF is a rendering of
it. That is deliberate: a dashboard computing its own averages is a second
implementation of the rubric that nobody tests.

Storage is optional. Evaluation must work on a machine that has never stored a
run, because that is every reviewer's first minute with this project.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from evals.context import build_context
from evals.framework import Measurability, StageEvaluation, aggregate
from evals.harness import evaluate as evaluate_rubric
from evals.stagewise import evaluate_stages
from evals.store import EvaluationRecord, EvaluationStore, compare, trend
from evals.types import Judgements, band_for

__all__ = ["evaluate_package", "stage_payload"]


def stage_payload(evaluation: StageEvaluation) -> dict[str, Any]:
    """One stage, serialised. Unmeasurable metrics are kept, not filtered.

    Dropping them would produce a document where every metric has a score, which
    is exactly the impression this framework exists not to give.
    """
    return {
        "stage": evaluation.stage,
        "label": evaluation.label,
        "score": None if evaluation.score is None else round(evaluation.score, 2),
        "confidence": evaluation.confidence,
        "measured": sum(1 for m in evaluation.metrics if m.measurability is Measurability.MEASURED),
        "judged": sum(1 for m in evaluation.metrics if m.measurability is Measurability.JUDGED),
        "not_measurable": len(evaluation.unmeasured),
        "missing": list(evaluation.missing),
        "metrics": [
            {
                "key": m.key,
                "label": m.label,
                "measurability": m.measurability.value,
                "score": None if m.score is None else round(m.score, 2),
                "confidence": round(m.confidence, 4),
                "weight": m.weight,
                "reasoning": m.reasoning,
                "evidence": [{"path": e.path, "observation": e.observation} for e in m.evidence],
                "recommendations": [
                    {"action": r.action, "impact": r.impact, "severity": r.severity}
                    for r in m.recommendations
                ],
            }
            for m in evaluation.metrics
        ],
    }


def _recommendations(evaluations: Sequence[StageEvaluation]) -> list[dict[str, Any]]:
    """Every recommendation from every stage, worst first.

    Ordered by severity then by how far the owning metric fell, because a list
    of twenty fixes in emission order is a list nobody works through. Ties break
    on stage order, so two equally urgent fixes appear in pipeline order — the
    order they should be fixed in, since an early stage's defect propagates.
    """
    rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    rows: list[dict[str, Any]] = []
    for position, evaluation in enumerate(evaluations):
        for metric in evaluation.metrics:
            for rec in metric.recommendations:
                rows.append(
                    {
                        "stage": evaluation.stage,
                        "stage_label": evaluation.label,
                        "metric": metric.key,
                        "metric_label": metric.label,
                        "score": None if metric.score is None else round(metric.score, 2),
                        "severity": rec.severity,
                        "action": rec.action,
                        "impact": rec.impact,
                        "_order": (rank.get(rec.severity, 9), metric.score or 0.0, position),
                    }
                )
    rows.sort(key=lambda r: r.pop("_order"))
    return rows


def _blocked(evaluations: Sequence[StageEvaluation]) -> list[dict[str, str]]:
    """What could not be measured, gathered in one place.

    Scattered through ten stages these read as footnotes; collected, they read as
    the roadmap they are — and a reviewer can see at a glance that the gaps are
    missing *data*, not missing effort.
    """
    return [
        {
            "stage": evaluation.stage,
            "metric": metric.key,
            "label": metric.label,
            "reason": metric.reasoning,
        }
        for evaluation in evaluations
        for metric in evaluation.unmeasured
    ]


def evaluate_package(
    package: Mapping[str, Any] | Any,
    *,
    chunks: Sequence[Mapping[str, Any]] | None = None,
    judgements: Judgements | None = None,
    run_id: str | None = None,
    store: EvaluationStore | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Evaluate one package every way this project knows how.

    ``chunks`` unlock the checks that need the source — citation integrity above
    all. Without them those metrics report themselves unmeasurable rather than
    scoring zero, because "we could not check" and "it failed" are different
    findings and only one of them is a defect.
    """
    payload = package.model_dump(mode="json") if hasattr(package, "model_dump") else dict(package)

    rubric = evaluate_rubric(payload, chunks=chunks, judgements=judgements)
    stages = evaluate_stages(build_context(payload, chunks=chunks, judgements=judgements))
    rolled = aggregate(stages)

    record = EvaluationRecord.build(
        run_id=run_id or str(uuid4()),
        package=payload,
        evaluations=stages,
        payload={"rubric_overall": round(rubric.overall, 4), "band": rubric.band},
    )

    comparison: dict[str, Any]
    history: list[dict[str, Any]]
    if store is not None:
        if persist:
            store.record(record)
        benchmark = store.benchmark(profile=record.profile, exclude=record.run_id)
        comparison = compare(record, benchmark)
        history = trend(store.history(profile=record.profile, limit=30))
    else:
        benchmark = {
            "profile": record.profile,
            "runs": 0,
            "sufficient": False,
            "overall": {"n": 0, "median": None, "min": None, "max": None, "p25": None, "p75": None},
            "stages": {},
        }
        comparison = compare(record, benchmark)
        history = []

    return {
        "run_id": record.run_id,
        "package_id": record.package_id,
        "evaluated_at": record.evaluated_at,
        "subject": record.subject,
        "grade_band": record.grade_band,
        "profile": record.profile,
        "summary": {
            # Two numbers, and they answer different questions. The stage score
            # is "did the machinery work"; the rubric score is "is the teaching
            # any good". Averaging them together would produce a third number
            # that answers neither.
            "stage_score": rolled["score"],
            "stage_confidence": rolled["confidence"],
            "stages_scored": rolled["stages_scored"],
            "stages_total": rolled["stages_total"],
            "rubric_score": round(100 * rubric.overall, 2),
            "rubric_band": rubric.band,
            "band": band_for((rolled["score"] or 0) / 100),
            "judged": rubric.judged,
            "transferable": rubric.transferable,
        },
        "stages": [stage_payload(s) for s in stages],
        "rubric": rubric.as_dict(),
        "recommendations": _recommendations(stages),
        "not_measurable": _blocked(stages),
        "benchmark": benchmark,
        "comparison": comparison,
        "history": history,
    }
