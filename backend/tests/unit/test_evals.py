"""The quality harness — does it actually discriminate?

An eval that scores everything 0.8 is worse than no eval: it converts "we did not
measure this" into "we measured this and it was fine". So the tests here are not
"does a good package score well". They are:

* does a deliberately bad package score *materially* worse, on the dimensions
  that were sabotaged and not on the ones that were not, and
* does a humanities package escape the STEM-shaped expectations — because a
  harness that rewards formulae and numerical questions would push the whole
  system toward producing them whether the source document supports it or not.
  That failure would be invisible in every other test in this repo.

**Why the degradation suite exists.** The intent above was already stated when
this file was first written, and the harness failed it anyway. Measured against a
shipped package, the rubric scored vacuous rubric descriptors at 0.9210 and filler
speaker notes at 0.9217 against a baseline of 0.9167 — both sabotages *improved*
the score — while deleting the entire concept graph changed nothing at all. Total
spread across every degradation: 0.011.

The reason the existing tests did not catch it is instructive: they sabotage four
things at once and assert the total moved by 0.15. A compound sabotage passes as
long as *something* in it lands, so a metric that inverts is hidden by three that
work. :mod:`evals.degradations` breaks one thing at a time and asserts a minimum
drop for each, which is the only shape of test that can find an inversion.

Everything here is deterministic and offline: ``evaluate`` is called without
``judgements``, so no model is involved and no key is needed.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from evals.degradations import DEGRADATIONS, MIN_ANY_DEGRADATION, MIN_DELTA, render, run_suite
from evals.dimensions import DIMENSIONS
from evals.harness import evaluate
from tests.fixtures import exemplar as ex
from tests.fixtures import factories as fx


def _chunks() -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in fx.chunks()]


def _good() -> dict[str, Any]:
    return fx.teacher_knowledge_package().model_dump(mode="json")


def _exemplar() -> dict[str, Any]:
    return ex.build(_good())


def _scores(report: Any) -> dict[str, float | None]:
    return {d.key: d.score for d in report.dimensions}


# ────────────────────────────────────────────────────────────── sanity


def test_the_reference_package_scores_well() -> None:
    """Not the point of the suite, but the floor everything else is measured from."""
    report = evaluate(_good(), chunks=_chunks())
    assert report.overall > 0.8
    assert report.judged is False, "no model call may be needed to score a package"


def test_grounding_reports_itself_inapplicable_without_source_chunks() -> None:
    """Scoring zero would say "ungrounded"; the truth is "not checkable here"."""
    grounding = next(d for d in evaluate(_good()).dimensions if d.key == "grounding")
    assert grounding.score is None
    assert grounding.applicable is False
    assert grounding.reason


def test_the_rubric_weights_sum_to_one() -> None:
    """Asserted at import too. Repeated here so the failure names the rubric
    rather than surfacing as an unrelated import error three modules away."""
    assert abs(sum(d.weight for d in DIMENSIONS) - 1.0) < 1e-9


# ───────────────────────────────────────────── the degradation suite
#
# The deliverable that keeps everything above honest.


def _suite() -> list[Any]:
    return run_suite(_exemplar(), chunks=ex.chunk_texts())


def test_no_degradation_ever_improves_the_score() -> None:
    """The property the instrument failed twice over.

    Filler speaker notes and vacuous rubric descriptors both scored *above* the
    content they replaced, because the only substance test was word count and
    padding is long by construction. A sabotage that raises a score does not
    merely fail to penalise bad work — it actively teaches the generator to
    produce it, and every point of that gradient looks like progress.
    """
    results = _suite()
    improved = [r for r in results if r.delta < MIN_ANY_DEGRADATION]
    assert not improved, "sabotage did not reduce the score:\n" + render(results)


def test_every_degradation_costs_at_least_its_severity_demands() -> None:
    """A severe defect that costs two points of the total is a defect the harness
    is telling the generator not to bother fixing."""
    results = _suite()
    short = [r for r in results if not r.meets_minimum]
    assert not short, "degradation cost less than its severity demands:\n" + render(results)


def test_every_degradation_is_noticed_by_the_dimension_that_owns_it() -> None:
    """A drop of the right size in the wrong place is a coincidence, not a
    measurement. Without this a single over-sensitive dimension could satisfy
    every threshold above while measuring nothing anyone named."""
    results = _suite()
    misplaced = [
        f"{r.key}: expected {r.lands_on}, noticed by {r.noticed_by}"
        for r in results
        if not r.landed_where_expected
    ]
    assert not misplaced, "\n".join(misplaced)


def test_the_suite_spans_a_real_range() -> None:
    """The original instrument spanned 0.011 across every degradation it had.

    A spread that narrow means the dimensions are not measuring different things:
    whatever you break, the number lands in the same place. This asserts the
    spread rather than any individual drop, because a suite where every sabotage
    cost exactly 0.05 would pass every other test here and still be flat.
    """
    deltas = [r.delta for r in _suite()]
    assert max(deltas) - min(deltas) > 0.04, f"deltas cluster: {sorted(deltas)}"


@pytest.mark.parametrize("degradation", DEGRADATIONS, ids=lambda d: d.key)
def test_each_degradation_individually(degradation: Any) -> None:
    """One test per sabotage, so a failure names the sabotage in its own id.

    The aggregate tests above catch the same failures, but a run that reports
    ``test_each_degradation_individually[vacuous_rubrics]`` tells whoever broke it
    what they broke without reading a table.
    """
    result = run_suite(_exemplar(), chunks=ex.chunk_texts(), only=[degradation.key])[0]
    assert result.delta >= MIN_DELTA[degradation.severity], result.as_row()
    assert result.landed_where_expected, result.as_row()


# ──────────────────────────────── the two inversions, named directly


def test_padding_a_rubric_cannot_raise_its_score() -> None:
    """``MIN_DESCRIPTOR_WORDS = 5`` accepted any descriptor of five words as
    substantive, so "The response demonstrates an excellent overall understanding"
    (eight words, says nothing) outscored "Correct value with units." (four words,
    markable). Length is not substance and must not stand in for it."""
    good = evaluate(_exemplar(), chunks=ex.chunk_texts()).dimension("assessment_integrity")
    padded = evaluate(
        next(d for d in DEGRADATIONS if d.key == "vacuous_rubrics").apply(_exemplar()),
        chunks=ex.chunk_texts(),
    ).dimension("assessment_integrity")

    assert good.score is not None and padded.score is not None
    assert padded.score < good.score
    # And specifically on the metric that owns it, not by luck elsewhere.
    before = next(m for m in good.metrics if m.key == "rubric_discrimination")
    after = next(m for m in padded.metrics if m.key == "rubric_discrimination")
    assert after.value < before.value - 0.5


def test_padding_a_script_cannot_raise_its_score() -> None:
    """The same inversion in the classroom dimension: notes under eight words were
    thin and anything longer passed, so one long filler sentence repeated through
    every segment read as a fuller script than the twelve different notes it
    replaced."""
    good = evaluate(_exemplar(), chunks=ex.chunk_texts()).dimension("classroom")
    padded = evaluate(
        next(d for d in DEGRADATIONS if d.key == "filler_speaker_notes").apply(_exemplar()),
        chunks=ex.chunk_texts(),
    ).dimension("classroom")

    assert good.score is not None and padded.score is not None
    assert padded.score < good.score
    after = next(m for m in padded.metrics if m.key == "script_actionability")
    assert after.value < 0.3, "filler prose is still reading as a usable script"


def test_a_longer_note_does_not_beat_a_shorter_specific_one() -> None:
    """The inversion stated as the property rather than as a scenario.

    Two packages, identical but for their speaker notes: one terse and anchored,
    one three times the length and generic. The short one must win. If this ever
    flips, some length threshold has crept back in.
    """
    terse = _exemplar()
    verbose = _exemplar()
    for package, note in (
        (terse, "Write the inertia statement on the board and ask for one counter-example."),
        (
            verbose,
            "At this stage of the lesson it is important to take a moment to engage the "
            "students in a meaningful way, ensuring that everyone in the classroom is "
            "following along carefully with all of the material that is being covered here.",
        ),
    ):
        for period in package["classroom_content"]:
            for segment in period["teacher_script"]:
                segment["speaker_notes"] = note

    terse_score = evaluate(terse, chunks=ex.chunk_texts()).dimension("classroom").score
    verbose_score = evaluate(verbose, chunks=ex.chunk_texts()).dimension("classroom").score
    assert terse_score is not None and verbose_score is not None
    assert terse_score > verbose_score


# ──────────────────────────────── absence is not the same as correctness


def test_deleting_every_prerequisite_does_not_score_perfect_sequencing() -> None:
    """``mean([]) == 1.0`` made the cheapest route to perfect sequencing the
    removal of all sequencing: no declared edges, no violated edges, full marks.
    Absence of a constraint is not satisfaction of it."""
    stripped = _exemplar()
    stripped["knowledge"]["concept_graph"] = {"node_ids": [], "edges": []}

    before = evaluate(_exemplar(), chunks=ex.chunk_texts()).dimension("sequencing")
    after = evaluate(stripped, chunks=ex.chunk_texts()).dimension("sequencing")
    assert before.score is not None and after.score is not None
    assert after.score < before.score

    respected = next(m for m in after.metrics if m.key == "prerequisites_respected")
    assert respected.weight == 0.0, "an unchecked metric must not carry weight"
    assert "not scored" in respected.note


def test_citing_nothing_does_not_score_perfect_citation_integrity() -> None:
    """The same arithmetic in grounding: integrity averaged over zero spans was
    1.0, so the cheapest citation was no citation."""
    stripped = next(d for d in DEGRADATIONS if d.key == "stripped_citations").apply(_exemplar())

    before = evaluate(_exemplar(), chunks=ex.chunk_texts()).dimension("grounding")
    after = evaluate(stripped, chunks=ex.chunk_texts()).dimension("grounding")
    assert before.score is not None and after.score is not None
    assert after.score < 0.2, "a package that cites nothing is not a grounded package"

    integrity = next(m for m in after.metrics if m.key == "citation_integrity")
    assert integrity.weight == 0.0
    assert next(m for m in after.metrics if m.key == "claims_cited").value == 0.0


def test_absence_that_is_genuinely_correct_still_scores_one() -> None:
    """The counterweight, and the more important half.

    An activity that needs no materials is runnable everywhere. A bank with no
    constructed responses has no rubrics to disagree about. Turning every empty
    list into a deduction would be the same error facing the other way, and it is
    the error that would punish humanities packages hardest.
    """
    package = _exemplar()
    for activity in package["activities"]:
        activity["materials"] = []
    package["assessments"]["items"] = [
        item for item in package["assessments"]["items"] if item["kind"] == "mcq"
    ]

    report = evaluate(package, chunks=ex.chunk_texts())
    activities = report.dimension("activities")
    materials = next(m for m in activities.metrics if m.key == "materials_realism")
    assert materials.value == 1.0, "an activity needing nothing was penalised for needing nothing"

    assessments = report.dimension("assessment_integrity")
    rubric = next(m for m in assessments.metrics if m.key == "rubric_discrimination")
    assert rubric.weight == 0.0, "a bank with no rubrics was scored on rubrics it does not owe"


# ──────────────────────────────────────────────────── content fidelity


def test_a_package_about_the_wrong_topic_is_caught() -> None:
    """The failure that shipped: a package labelled History, topic "The Partition
    of Bengal", teaching Newton's Laws in every concept, activity and item. It
    scored 0.874 and banded exemplary, because no dimension read the label."""
    mislabelled = _exemplar()
    mislabelled["classification"]["subject"] = "History"
    mislabelled["classification"]["topic"] = "The Partition of Bengal"

    fidelity = evaluate(mislabelled, chunks=ex.chunk_texts()).dimension("content_fidelity")
    assert fidelity.score is not None and fidelity.score < 0.55
    assert any(f.code == "FID_TOPIC_MISMATCH" for f in fidelity.findings)


def test_a_concept_id_that_resolves_to_nothing_is_caught() -> None:
    """The pointer form of the same failure. Every id is well-formed, every field
    is populated, and the material the ids point at does not exist."""
    dangling = _exemplar()
    for item in dangling["assessments"]["items"]:
        item["concept_ids"] = ["concept_that_was_never_extracted"]

    fidelity = evaluate(dangling, chunks=ex.chunk_texts()).dimension("content_fidelity")
    integrity = next(m for m in fidelity.metrics if m.key == "concept_reference_integrity")
    assert integrity.value < 1.0
    assert any(f.code == "FID_CONCEPT_UNRESOLVED" for f in fidelity.findings)


def test_a_topic_that_names_no_content_is_reported_not_punished() -> None:
    """ "Chapter 5" and "Unit II" are stage-2 outputs this dimension cannot grade.
    Scoring them down would penalise a package for how its chapter was numbered."""
    numbered = _exemplar()
    numbered["classification"]["topic"] = "Chapter 5"

    fidelity = evaluate(numbered, chunks=ex.chunk_texts()).dimension("content_fidelity")
    alignment = next(m for m in fidelity.metrics if m.key == "topic_alignment")
    assert alignment.weight == 0.0
    assert "not scored" in alignment.note


def test_the_subject_name_is_reported_and_never_scored() -> None:
    """ "Physics" appears nowhere in a chapter about Newton's Laws and "History"
    appears nowhere in a chapter about the Partition. Scoring a subject name's
    presence would reward packages for naming their own discipline in the prose —
    a subject-shaped incentive smuggled in through a fidelity check."""
    fidelity = evaluate(_exemplar(), chunks=ex.chunk_texts()).dimension("content_fidelity")
    subject = next(m for m in fidelity.metrics if m.key == "declared_subject")
    assert subject.weight == 0.0

    renamed = _exemplar()
    renamed["classification"]["subject"] = "Applied Mechanics"
    after = evaluate(renamed, chunks=ex.chunk_texts()).dimension("content_fidelity")
    assert after.score == fidelity.score, "the subject label moved a score"


# ──────────────────────────────────────────────────── period integrity


def test_a_period_that_checks_another_period_s_concept_is_caught() -> None:
    """Observed in a shipped sample: period 2 kept period 1's entry ticket, exit
    ticket, board bullets and homework, so it checked the objective it was not
    aimed at. Every field was populated and every id resolved."""
    duplicated = _exemplar()
    second = copy.deepcopy(duplicated["classroom_content"][0])
    second["period_no"] = 2
    duplicated["classroom_content"][1] = second

    integrity = evaluate(duplicated, chunks=ex.chunk_texts()).dimension("period_integrity")
    assert integrity.score is not None and integrity.score < 0.8
    codes = {f.code for f in integrity.findings}
    assert "PER_DUPLICATED" in codes or "PER_CHECKPOINT_OFF_PERIOD" in codes


def test_period_integrity_is_inapplicable_without_a_plan_to_compare_against() -> None:
    """It measures content against the plan it was written for. With no plan
    there is no claim to check, which is not the same as a failed check."""
    unplanned = _exemplar()
    unplanned["teaching_plan"]["periods"] = []

    integrity = evaluate(unplanned, chunks=ex.chunk_texts()).dimension("period_integrity")
    assert integrity.applicable is False
    assert integrity.score is None
    assert integrity.reason


# ──────────────────────────────────────────────────── discrimination
#
# The compound sabotage kept from the original suite. It no longer carries the
# weight of the argument — the per-degradation tests do that — but it is still
# the check that several independent failures compose rather than cancel.


def _poor() -> dict[str, Any]:
    """The same package, sabotaged four independent ways.

    Each sabotage is a real failure mode of generated teaching material, not
    noise: objectives that restate the topic, an all-recall bank, boilerplate
    differentiation with unobservable success criteria, and a fabricated citation.
    """
    poor = copy.deepcopy(_good())

    for objective in poor["knowledge"]["learning_objectives"]:
        objective["statement"] = "Understand the topic"
        objective["bloom_level"] = "remember"

    for item in poor["assessments"]["items"]:
        item["bloom_level"] = "remember"
        if item.get("rubric"):
            item["rubric"]["levels"] = [
                {"label": "Good", "descriptor": "Good answer", "marks": item["marks"]},
                {"label": "Poor", "descriptor": "Poor answer", "marks": 0},
            ]

    for activity in poor["activities"]:
        activity["differentiation"] = {
            "support": "Give extra help",
            "extension": "Give more work",
        }
        activity["success_criteria"] = ["Students understand the concept"]
        activity["teacher_instructions"] = ["Facilitate discussion"]

    for concept in poor["knowledge"]["concepts"]:
        concept["evidence"] = [
            {"chunk_id": "c_0001", "quote": "Newton discovered this watching an apple fall."}
        ]

    return poor


def test_a_sabotaged_package_scores_materially_worse() -> None:
    good = evaluate(_good(), chunks=_chunks())
    poor = evaluate(_poor(), chunks=_chunks())
    # A gap this size cannot come from scoring noise. If this ever narrows to a
    # few points, the harness has stopped measuring and started flattering.
    assert good.overall - poor.overall > 0.15


def test_each_sabotage_lands_on_the_dimension_that_owns_it() -> None:
    """A single collapsing score could be one over-sensitive metric doing all the work."""
    good, poor = (
        _scores(evaluate(_good(), chunks=_chunks())),
        _scores(evaluate(_poor(), chunks=_chunks())),
    )
    for key in ("objectives", "bloom", "differentiation", "activities", "grounding"):
        assert good[key] is not None and poor[key] is not None
        assert poor[key] < good[key], f"{key} did not notice its sabotage"


def test_untouched_dimensions_are_not_dragged_down() -> None:
    """Sabotaging prose must not move structural scores — otherwise nothing localises."""
    good, poor = (
        _scores(evaluate(_good(), chunks=_chunks())),
        _scores(evaluate(_poor(), chunks=_chunks())),
    )
    # Concept/objective coverage and teaching order were left intact.
    assert poor["coverage"] == good["coverage"]
    assert poor["sequencing"] == good["sequencing"]


def test_a_fabricated_citation_is_caught_by_grounding_specifically() -> None:
    quoted = copy.deepcopy(_good())
    for concept in quoted["knowledge"]["concepts"]:
        concept["evidence"] = [
            {"chunk_id": "c_0001", "quote": "Newton discovered this watching an apple fall."}
        ]
    before = _scores(evaluate(_good(), chunks=_chunks()))["grounding"]
    after = _scores(evaluate(quoted, chunks=_chunks()))["grounding"]
    assert before is not None and after is not None and after < before


# ─────────────────────────────────────────── the profile-fairness guarantee


def _narrative() -> dict[str, Any]:
    """A humanities package: no formulae, no numerical items, nothing else changed.

    Numerical items are *substituted* rather than deleted. Deleting them would
    shrink the bank and depress coverage and Bloom spread for reasons that have
    nothing to do with the profile, which would make this test prove the opposite
    of what it claims.

    The classification keeps its original subject and topic and takes only the
    narrative *profile*. Swapping in a history topic over mechanics content would
    now — correctly — be caught by ``content_fidelity`` as the mislabelled package
    it is, and the subject of these tests is the profile, not the label.
    """
    narrative = copy.deepcopy(_good())
    source = fx.narrative_classification().model_dump(mode="json")
    narrative["classification"] = {
        **source,
        "subject": narrative["classification"]["subject"],
        "topic": narrative["classification"]["topic"],
        "chapter": narrative["classification"]["chapter"],
    }
    narrative["knowledge"]["formulae"] = []

    for item in narrative["assessments"]["items"]:
        if item["kind"] != "numerical":
            continue
        item["kind"] = "short_answer"
        item["working"] = None
        item["options"] = None
        item.setdefault("rubric", None)
        if not item["rubric"]:
            item["rubric"] = {
                "criteria": "Whether the answer names the cause and justifies it.",
                "levels": [
                    {
                        "label": "Complete",
                        "descriptor": "Names the cause and justifies it from the source.",
                        "marks": item["marks"],
                    },
                    {
                        "label": "Partial",
                        "descriptor": "Names the cause without justifying it.",
                        "marks": max(1, item["marks"] // 2),
                    },
                ],
            }
    return narrative


def test_absent_stem_content_is_reported_as_designed_not_as_a_gap() -> None:
    report = evaluate(_narrative(), chunks=_chunks())
    excused = " ".join(report.absent_by_design)
    assert "formulae" in excused
    assert "numerical" in excused


def test_a_humanities_package_is_not_marked_down_for_having_no_formulae() -> None:
    """The single most important property of this harness.

    Coverage is the dimension that would punish absent content hardest — it asks
    whether everything the package teaches is also practised and assessed. If
    removing every formula and every numerical item moved it, the harness would
    be scoring subject shape instead of teaching quality, and optimising against
    it would make the system worse on exactly the documents the brief cares about.
    """
    quantitative = _scores(evaluate(_good(), chunks=_chunks()))
    narrative = _scores(evaluate(_narrative(), chunks=_chunks()))
    assert narrative["coverage"] == quantitative["coverage"]
    assert narrative["grounding"] is not None
    assert quantitative["grounding"] is not None
    assert abs(narrative["grounding"] - quantitative["grounding"]) < 0.05


def test_content_fidelity_does_not_require_the_topic_to_sound_quantitative() -> None:
    """The new dimension gets the same guarantee as the old ones.

    Fidelity compares two fields of the same package against each other. A
    package whose topic and content agree scores the same whether they agree
    about mechanics or about a partition, and this asserts it by relabelling
    both sides together rather than one of them.
    """
    relabelled = _exemplar()
    relabelled["classification"] = {
        **relabelled["classification"],
        "subject": "History",
        "topic": "Inertia, acceleration and momentum",
        "pedagogy_profile": "narrative",
    }
    before = evaluate(_exemplar(), chunks=ex.chunk_texts()).dimension("content_fidelity")
    after = evaluate(relabelled, chunks=ex.chunk_texts()).dimension("content_fidelity")
    assert before.score == after.score


def test_no_dimension_key_names_a_subject() -> None:
    """The versatility rule, applied to the grader as well as the generator.

    The pipeline is forbidden from branching on a subject name; a harness that
    did so would reintroduce the same bias one layer up, where no existing test
    is looking for it.
    """
    banned = {"physics", "history", "maths", "math", "chemistry", "biology", "science"}
    report = evaluate(_good(), chunks=_chunks())
    for dimension in report.dimensions:
        haystack = f"{dimension.key} {dimension.label} {dimension.reason}".casefold()
        assert not any(word in haystack.split() for word in banned)


def test_no_degradation_names_a_subject() -> None:
    """The same rule for the adversarial suite. A degradation that had to know
    what physics was would only sabotage physics packages, and the suite would
    quietly stop protecting everything else."""
    banned = {"physics", "history", "chemistry", "biology", "geography", "literature"}
    for degradation in DEGRADATIONS:
        haystack = f"{degradation.key} {degradation.describes}".casefold()
        assert not banned & set(haystack.replace(",", " ").split())
