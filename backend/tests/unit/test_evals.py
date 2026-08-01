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

Everything here is deterministic and offline: ``evaluate`` is called without
``judgements``, so no model is involved and no key is needed.
"""

from __future__ import annotations

import copy
from typing import Any

from evals.harness import evaluate
from tests.fixtures import factories as fx


def _chunks() -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in fx.chunks()]


def _good() -> dict[str, Any]:
    return fx.teacher_knowledge_package().model_dump(mode="json")


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


# ──────────────────────────────────────────────────── discrimination


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
    """
    narrative = copy.deepcopy(_good())
    narrative["classification"] = fx.narrative_classification().model_dump(mode="json")
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
