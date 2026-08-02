"""The per-stage framework — can it be made to lie, and does it catch real bugs?

Two questions, and the first is the unusual one. This framework's central claim
is that it never reports a number it cannot defend, and a claim like that is only
worth anything if the type system enforces it. So the first block here tries to
construct the forbidden states directly and asserts that construction fails.
A guard nobody has attacked is a comment.

The second block sabotages a package one defect at a time and checks that the
score drops **on the stage that owns the defect and not on its neighbours**. A
framework where every metric moves together is measuring one thing under eleven
names.

Everything is deterministic and offline — no model, no key, no network.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from evals.context import build_context
from evals.framework import (
    Measurability,
    MetricResult,
    StageEvaluation,
    aggregate,
    judged,
    measured,
    not_measurable,
)
from evals.service import evaluate_package
from evals.stagewise import evaluate_stage, evaluate_stages
from evals.store import MIN_BASELINE_RUNS, EvaluationRecord, EvaluationStore, compare
from tests.fixtures import factories as fx


def _package() -> dict[str, Any]:
    return fx.teacher_knowledge_package().model_dump(mode="json")


def _chunks() -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in fx.chunks()]


def _ctx(package: dict[str, Any], *, with_chunks: bool = True):
    return build_context(package, chunks=_chunks() if with_chunks else None)


def _score(package: dict[str, Any], stage: str, *, with_chunks: bool = True) -> float | None:
    return evaluate_stage(stage, _ctx(package, with_chunks=with_chunks)).score


def _metric(package: dict[str, Any], stage: str, key: str) -> MetricResult:
    evaluation = evaluate_stage(stage, _ctx(package))
    return next(m for m in evaluation.metrics if m.key == key)


# ─────────────────────────────────────────── the guards against fabrication


def test_an_unmeasurable_metric_cannot_carry_a_score() -> None:
    """The whole framework rests on this one refusal.

    "Teacher satisfaction: 85" is the failure mode being designed against. It
    must be impossible to express, not merely discouraged in a docstring.
    """
    with pytest.raises(ValidationError, match="NOT_MEASURABLE"):
        MetricResult(
            key="teacher_satisfaction",
            label="Teacher satisfaction",
            measurability=Measurability.NOT_MEASURABLE,
            score=85.0,
            reasoning="feels about right",
        )


def test_a_measurable_metric_must_actually_carry_one() -> None:
    """The mirror of the rule above: claiming to have measured something and
    then reporting nothing is the same dishonesty facing the other way."""
    with pytest.raises(ValidationError, match="has no score"):
        MetricResult(
            key="coverage",
            label="Coverage",
            measurability=Measurability.MEASURED,
            score=None,
            reasoning="counted them",
        )


def test_a_judged_metric_may_not_claim_certainty() -> None:
    """A model reading an explanation is an instrument with error. Reporting its
    verdict at confidence 1.0 presents a reading as a measurement."""
    with pytest.raises(ValidationError, match="not certain"):
        MetricResult(
            key="pitch",
            label="Pitched at grade level",
            measurability=Measurability.JUDGED,
            score=80.0,
            confidence=0.99,
            reasoning="the judge was sure",
        )


def test_the_judged_helper_caps_confidence_rather_than_failing() -> None:
    """Callers pass a confidence they got from a judge; clamping is kinder than
    raising, as long as the cap is not silently above the limit."""
    assert judged("k", "Label", 80.0, "reasoned", confidence=1.0).confidence == 0.9


def test_every_metric_must_say_why() -> None:
    """A score with no reasoning cannot be argued with, which makes it useless
    to the person whose job it is to act on it."""
    with pytest.raises(ValidationError):
        measured("k", "Label", 90.0, "")


def test_an_unmeasurable_metric_is_excluded_not_zeroed() -> None:
    """Counting "we could not measure this" as zero would make a stage look
    broken for a gap in the *evaluator*."""
    stage = StageEvaluation(
        stage="s",
        label="S",
        metrics=[
            measured("a", "A", 90.0, "counted"),
            not_measurable("b", "B", "no ground truth exists"),
        ],
    )
    assert stage.score == 90.0, "the unmeasurable metric dragged the score down"
    assert stage.confidence < 1.0, "confidence must record that half the stage was unseen"


def test_a_stage_that_measured_nothing_scores_none_not_zero() -> None:
    """Zero says "this is bad". None says "we do not know". They are different
    claims and only one of them is true here."""
    stage = StageEvaluation(
        stage="s",
        label="S",
        metrics=[not_measurable("a", "A", "needs a labelled corpus")],
    )
    assert stage.score is None
    assert aggregate([stage])["score"] is None


def test_aggregate_reports_how_much_of_the_pipeline_it_saw() -> None:
    """An overall computed from six of eleven stages is a different claim from
    one computed from all eleven, and a reader must be able to tell."""
    rolled = aggregate(
        [
            StageEvaluation(stage="a", label="A", metrics=[measured("m", "M", 80.0, "x")]),
            StageEvaluation(stage="b", label="B", metrics=[not_measurable("m", "M", "no data")]),
        ]
    )
    assert rolled["stages_scored"] == 1
    assert rolled["stages_total"] == 2
    assert rolled["score"] == 80.0


# ────────────────────────────────────────────────── does it catch real bugs


def test_the_reference_package_passes_every_stage() -> None:
    """The floor. If the reference fixture fails a stage check, the check is
    wrong — this fixture is what the contracts were written against."""
    evaluations = evaluate_stages(_ctx(_package()))
    weak = [(e.stage, e.score) for e in evaluations if e.score is not None and e.score < 90]
    assert not weak, f"reference package fails its own stage checks: {weak}"


def test_a_fabricated_citation_is_caught_without_a_model() -> None:
    """The single most valuable measurement here: a quote that is not in the
    chunk it cites. It needs no judge, and a teacher trusting a fake citation is
    the worst failure this system can ship."""
    package = _package()
    package["knowledge"]["concepts"][0]["evidence"][0]["quote"] = (
        "Newton personally wrote this sentence in 1687 and it appears nowhere in the source."
    )
    metric = _metric(package, "knowledge-extraction", "citation_integrity")
    assert metric.measurability is Measurability.MEASURED
    assert metric.score is not None and metric.score < 100
    assert metric.evidence, "a failed citation check must point at the citation"
    assert metric.recommendations


def test_citation_integrity_is_unmeasurable_without_the_source() -> None:
    """Not zero. Without chunks the quote cannot be checked, and reporting a
    failure would blame the package for the evaluator's missing input."""
    metric = next(
        m
        for m in evaluate_stage("knowledge-extraction", _ctx(_package(), with_chunks=False)).metrics
        if m.key == "citation_integrity"
    )
    assert metric.measurability is Measurability.NOT_MEASURABLE
    assert metric.score is None
    assert "chunk" in metric.reasoning.lower()


def test_a_concept_taught_before_its_prerequisite_is_caught() -> None:
    """Stage 4's one hard ordering obligation. The finished package looks fine —
    every concept is scheduled, the timing adds up — and it is still wrong."""
    package = _package()
    periods = package["teaching_plan"]["periods"]
    # Swap the concept assignments so the dependent idea is taught first.
    periods[0]["concept_ids"], periods[1]["concept_ids"] = (
        periods[1]["concept_ids"],
        periods[0]["concept_ids"],
    )
    metric = _metric(package, "teaching-planner", "prerequisite_order")
    assert metric.score == 0.0
    assert "prerequisite" in metric.evidence[0].observation.lower()


def test_a_dangling_activity_reference_is_caught() -> None:
    """A lesson telling the teacher to run activity `act_9` when no such activity
    exists. Every schema check passes; the package is unusable at that moment."""
    package = _package()
    package["classroom_content"][0]["activity_refs"] = ["act_does_not_exist"]
    metric = _metric(package, "lesson-generation", "activity_ref_integrity")
    assert metric.score is not None and metric.score < 100
    assert metric.recommendations[0].severity == "high"


def test_an_mcq_with_two_right_answers_is_caught() -> None:
    """Marked wrong for whichever half of the class picked the other one."""
    package = _package()
    for option in package["assessments"]["items"][0]["options"]:
        option["is_correct"] = True
    metric = _metric(package, "assessment-generation", "mcq_integrity")
    assert metric.score == 0.0


def test_a_blueprint_that_disagrees_with_its_own_bank_is_caught() -> None:
    """The blueprint is what a teacher checks coverage against. This check
    already found a real defect in the narrative sample builder, which claimed a
    numerical item the narrative profile designs away."""
    package = _package()
    package["assessments"]["blueprint"]["items_by_kind"] = {"mcq": 7, "essay": 3}
    metric = _metric(package, "assessment-generation", "blueprint_consistency")
    assert metric.score is not None and metric.score < 50
    assert "claims" in metric.reasoning


def test_a_validator_whose_coverage_report_is_wrong_is_caught() -> None:
    """The check with the most leverage: stage 9's own account of its work,
    independently recomputed. A validator nobody re-derives is a validator
    nobody has checked."""
    package = _package()
    package["validation"]["coverage"]["concepts_total"] = 99
    metric = _metric(package, "validation", "coverage_report_accuracy")
    assert metric.score == 0.0
    assert "recount" in metric.reasoning.lower()


def test_a_defect_lands_on_its_own_stage_and_spares_the_others() -> None:
    """A framework where one defect moves every stage is measuring one thing
    under eleven names."""
    clean = {e.stage: e.score for e in evaluate_stages(_ctx(_package()))}

    package = _package()
    for option in package["assessments"]["items"][0]["options"]:
        option["is_correct"] = True
    broken = {e.stage: e.score for e in evaluate_stages(_ctx(package))}

    assert (broken["assessment-generation"] or 0) < (clean["assessment-generation"] or 0)
    unchanged = {
        stage: (clean[stage], broken[stage])
        for stage in clean
        if stage != "assessment-generation" and clean[stage] != broken[stage]
    }
    assert not unchanged, f"an assessment defect moved unrelated stages: {unchanged}"


def test_every_recommendation_says_what_it_buys() -> None:
    """A list of fixes with no stated impact is a list nobody prioritises."""
    package = _package()
    package["classroom_content"][0]["activity_refs"] = ["nope"]
    package["assessments"]["blueprint"]["items_by_kind"] = {"essay": 4}

    document = evaluate_package(package, chunks=_chunks())
    assert document["recommendations"]
    for rec in document["recommendations"]:
        assert rec["action"] and rec["impact"]
    severities = [r["severity"] for r in document["recommendations"]]
    assert severities == sorted(severities, key=["high", "medium", "low", "info"].index)


def test_no_stage_key_names_a_subject() -> None:
    """The same rule the pipeline lives under (NFR-01): nothing branches on a
    subject name. An evaluator that rewarded STEM shape would push the generator
    toward it one score at a time."""
    banned = {"physics", "chemistry", "biology", "history", "maths", "math", "science"}
    for evaluation in evaluate_stages(_ctx(_package())):
        for metric in evaluation.metrics:
            assert not banned & set(metric.key.lower().split("_"))


# ─────────────────────────────────────────────── history, and its honesty


def test_a_thin_history_declines_to_call_a_regression() -> None:
    """Regression detection over three runs is astrology. The correct answer for
    most of a project's life is "not enough history", said plainly."""
    store = EvaluationStore()
    record = EvaluationRecord(
        run_id="r1",
        package_id="p",
        subject="Physics",
        grade_band="9-10",
        profile="quantitative",
        overall=90.0,
        confidence=0.9,
        stage_scores={"validation": 40.0},
    )
    verdict = compare(record, store.benchmark(profile="quantitative"))
    assert verdict["status"] == "insufficient_history"
    assert verdict["needed"] == MIN_BASELINE_RUNS
    assert verdict["regressions"] == []


def test_a_real_regression_is_called_once_there_is_a_baseline() -> None:
    store = EvaluationStore()
    for i in range(MIN_BASELINE_RUNS):
        store.record(
            EvaluationRecord(
                run_id=f"base-{i}",
                package_id="p",
                subject="Physics",
                grade_band="9-10",
                profile="quantitative",
                overall=95.0,
                confidence=0.9,
                stage_scores={"validation": 95.0, "publishing": 90.0},
            )
        )

    regressed = EvaluationRecord(
        run_id="new",
        package_id="p",
        subject="Physics",
        grade_band="9-10",
        profile="quantitative",
        overall=80.0,
        confidence=0.9,
        stage_scores={"validation": 60.0, "publishing": 91.0},
    )
    verdict = compare(regressed, store.benchmark(profile="quantitative"))
    assert verdict["status"] == "regression"
    assert [r["stage"] for r in verdict["regressions"]] == ["validation"]
    assert verdict["overall_delta"] == -15.0


def test_a_run_is_never_benchmarked_against_itself() -> None:
    """Including the run in its own baseline pulls the median toward it and
    hides exactly the drop the comparison exists to find."""
    store = EvaluationStore()
    for i in range(MIN_BASELINE_RUNS):
        store.record(
            EvaluationRecord(
                run_id=f"base-{i}",
                package_id="p",
                subject="Physics",
                grade_band="9-10",
                profile="quantitative",
                overall=95.0,
                confidence=0.9,
                stage_scores={"validation": 95.0},
            )
        )
    store.record(
        EvaluationRecord(
            run_id="self",
            package_id="p",
            subject="Physics",
            grade_band="9-10",
            profile="quantitative",
            overall=50.0,
            confidence=0.9,
            stage_scores={"validation": 50.0},
        )
    )
    benchmark = store.benchmark(profile="quantitative", exclude="self")
    assert benchmark["runs"] == MIN_BASELINE_RUNS
    assert benchmark["stages"]["validation"]["median"] == 95.0


def test_history_is_partitioned_by_profile() -> None:
    """A narrative package does not regress because it scores below a corpus of
    quantitative ones. Comparing across profiles compares different jobs."""
    store = EvaluationStore()
    for i in range(MIN_BASELINE_RUNS):
        store.record(
            EvaluationRecord(
                run_id=f"q-{i}",
                package_id="p",
                subject="Physics",
                grade_band="9-10",
                profile="quantitative",
                overall=95.0,
                confidence=0.9,
                stage_scores={},
            )
        )
    assert store.benchmark(profile="narrative")["runs"] == 0
    assert store.benchmark(profile="narrative")["sufficient"] is False
    assert store.benchmark(profile="quantitative")["sufficient"] is True


def test_history_survives_a_restart_when_given_a_path(tmp_path: Any) -> None:
    path = tmp_path / "evals.sqlite3"
    store = EvaluationStore(path)
    store.record(
        EvaluationRecord(
            run_id="r1",
            package_id="p",
            subject="Physics",
            grade_band="9-10",
            profile="quantitative",
            overall=91.0,
            confidence=0.9,
            stage_scores={"validation": 91.0},
        )
    )
    store.close()

    reopened = EvaluationStore(path)
    assert reopened.count() == 1
    assert (reopened.get("r1") or EvaluationRecord("", "", "", "", "", None, 0, {})).overall == 91.0


# ───────────────────────────────────────────────────────── the whole document


def test_the_document_keeps_its_two_scores_apart() -> None:
    """ "Did the machinery work" and "is this good teaching" are different
    questions. Averaging them produces a third number that answers neither."""
    document = evaluate_package(_package(), chunks=_chunks())
    summary = document["summary"]
    assert summary["stage_score"] is not None
    assert summary["rubric_score"] is not None
    assert "overall" not in summary, "the two scores must not be collapsed into one"


def test_the_document_surfaces_what_it_could_not_measure() -> None:
    """Buried in a footnote these read as caveats; collected they read as the
    roadmap they are."""
    document = evaluate_package(_package(), chunks=_chunks())
    blocked = {entry["metric"] for entry in document["not_measurable"]}
    assert {"teacher_satisfaction", "student_learning_effectiveness"} <= blocked
    for entry in document["not_measurable"]:
        assert entry["reason"], "an unmeasurable metric must say why"


def test_evaluation_needs_no_model_no_key_and_no_network() -> None:
    """The property that lets this run on every commit. A metric that costs a
    model call is a metric nobody runs on a pull request."""
    document = evaluate_package(_package(), chunks=_chunks())
    assert document["summary"]["judged"] is False


def test_evaluating_the_same_package_twice_gives_the_same_numbers() -> None:
    """Reproducibility is what makes a trend line meaningful. A score that moves
    on its own cannot be used to detect that a change moved it."""
    first = evaluate_package(_package(), chunks=_chunks())
    second = evaluate_package(copy.deepcopy(_package()), chunks=_chunks())
    assert first["summary"]["stage_score"] == second["summary"]["stage_score"]
    assert [s["score"] for s in first["stages"]] == [s["score"] for s in second["stages"]]
