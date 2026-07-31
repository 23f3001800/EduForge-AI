"""Stage 7 — blueprint design and item reconstruction.

The tests worth having here are about the two failure modes that produce an
assessment bank which passes schema validation and is still unusable in a
classroom: an MCQ with the wrong number of correct answers, and an answer key
that was invented to fill a required field.
"""

from __future__ import annotations

import pytest

from pedagogy.registry import get_strategy
from stages.s7_assessments.blueprint import MAX_ITEMS, MIN_ITEMS, build_blueprint, rubric_ladder
from stages.s7_assessments.schemas import ConstructedResponseDraft, MCQDraft, RubricLevelDraft
from stages.s7_assessments.stage import build_constructed, build_mcq, summarise

QUANT = get_strategy("quantitative")
NARRATIVE = get_strategy("narrative")


def _knowledge(concepts: int = 4, objectives: int = 3) -> dict:
    return {
        "concepts": [
            {
                "concept_id": f"c{i}",
                "name": f"Concept {i}",
                "summary": "s",
                "importance": "core",
            }
            for i in range(concepts)
        ],
        "learning_objectives": [
            {"objective_id": f"o{i}", "statement": f"Objective {i}", "bloom_level": "understand"}
            for i in range(objectives)
        ],
    }


def _spec():
    """One real spec from a real blueprint — the builders only read its fields."""
    return build_blueprint(_knowledge(), QUANT).specs[0]


# ────────────────────────────────────────────────────────────── blueprint


def test_bank_size_scales_with_content_and_is_never_fixed() -> None:
    small = len(build_blueprint(_knowledge(1, 1), QUANT).specs)
    large = len(build_blueprint(_knowledge(8, 6), QUANT).specs)
    assert small < large
    assert small >= MIN_ITEMS and large <= MAX_ITEMS


def test_a_narrative_profile_designs_no_numerical_items() -> None:
    """Zero numerical questions on a humanities chapter is the design, not a gap.

    The model is never even asked for one, so this cannot regress by prompt drift.
    """
    kinds = {spec.kind for spec in build_blueprint(_knowledge(6, 4), NARRATIVE).specs}
    assert "numerical" not in kinds
    assert kinds, "a narrative bank must still contain items"


def test_every_objective_is_assessed_by_something() -> None:
    blueprint = build_blueprint(_knowledge(4, 3), QUANT)
    assessed = {spec.objective_id for spec in blueprint.specs}
    assert {"o0", "o1", "o2"} <= assessed


def test_total_marks_is_exact_by_construction() -> None:
    blueprint = build_blueprint(_knowledge(), QUANT)
    assert blueprint.total_marks == sum(spec.marks for spec in blueprint.specs)


def test_an_mcq_is_never_credited_with_testing_creation() -> None:
    """A four-option question cannot assess `create`; claiming so inflates the bank."""
    blueprint = build_blueprint(_knowledge(6, 5), QUANT)
    assert all(
        spec.bloom_level not in {"evaluate", "create"}
        for spec in blueprint.specs
        if spec.kind == "mcq"
    )


# ──────────────────────────────────────────────────────────────── MCQ build


def test_exactly_one_option_is_correct() -> None:
    spec = _spec()
    draft = MCQDraft(
        stem="Which force acts?",
        options=["Friction", "Gravity", "Tension", "Normal"],
        correct_index=2,
        rationales=["a", "b", "c", "d"],
        answer="Tension, because the string is taut.",
    )
    item, _ = build_mcq(spec, draft, None)
    assert item is not None
    assert sum(o.is_correct for o in item.options) == 1
    assert next(o for o in item.options if o.is_correct).text == "Tension"


def test_out_of_range_correct_index_does_not_mark_a_wrong_option() -> None:
    spec = _spec()
    draft = MCQDraft(
        stem="Q?",
        options=["A one", "B two", "C three", "D four"],
        correct_index=9,
        answer="A one",
    )
    item, notes = build_mcq(spec, draft, None)
    assert item is not None
    assert sum(o.is_correct for o in item.options) == 1
    assert any("out of range" in n for n in notes)


def test_duplicate_options_degrade_rather_than_ship_a_three_option_mcq() -> None:
    """Two identical options make a 3-option question wearing a 4-option shape."""
    spec = _spec()
    draft = MCQDraft(
        stem="Q?",
        options=["Same", "same", "Other", "Third"],
        correct_index=0,
        answer="Same",
    )
    item, notes = build_mcq(spec, draft, None)
    assert item is None
    assert any("4 distinct options" in n for n in notes)


def test_an_mcq_with_no_answer_is_not_shipped() -> None:
    spec = _spec()
    draft = MCQDraft(stem="Q?", options=["a", "b", "c", "d"], answer="   ")
    item, _ = build_mcq(spec, draft, None)
    assert item is None


# ──────────────────────────────────────────────── constructed-response build


def test_a_collapsed_rubric_is_replaced_by_one_that_discriminates() -> None:
    """All levels at the same marks is a rubric that restates the question."""
    spec = _spec()
    draft = ConstructedResponseDraft(
        stem="Explain inertia.",
        answer="A body resists a change in its state of motion.",
        rubric_criteria="Accuracy",
        rubric_levels=[
            RubricLevelDraft(label="Good", descriptor="Good answer", marks=3),
            RubricLevelDraft(label="Fine", descriptor="Fine answer", marks=3),
        ],
    )
    item, notes = build_constructed(spec, draft, "short_answer", 3)
    assert item is not None
    assert item.rubric is not None
    assert len({lvl.marks for lvl in item.rubric.levels}) > 1
    assert any("did not discriminate" in n for n in notes)


def test_a_rubric_cannot_award_more_than_the_item_is_worth() -> None:
    spec = _spec()
    draft = ConstructedResponseDraft(
        stem="Explain.",
        answer="Because the net force is zero.",
        rubric_levels=[
            RubricLevelDraft(label="Top", descriptor="All of it", marks=99),
            RubricLevelDraft(label="Part", descriptor="Some of it", marks=1),
        ],
    )
    item, notes = build_constructed(spec, draft, "short_answer", 3)
    assert item is not None
    assert item.rubric is not None
    assert max(lvl.marks for lvl in item.rubric.levels) <= 3
    assert any("more than the item" in n for n in notes)


def test_an_item_with_no_answer_key_is_dropped_not_invented() -> None:
    """A fabricated answer key is worse than a shorter bank — a teacher marks against it."""
    spec = _spec()
    draft = ConstructedResponseDraft(stem="Explain inertia.", answer="")
    item, notes = build_constructed(spec, draft, "short_answer", 3)
    assert item is None
    assert any("empty" in n for n in notes)


@pytest.mark.parametrize("marks", [1, 2, 6])
def test_a_derived_rubric_ladder_always_discriminates(marks: int) -> None:
    levels = rubric_ladder(marks, "the net force is zero")
    assert len(levels) >= 2
    assert len({lvl["marks"] for lvl in levels}) > 1


# ───────────────────────────────────────────────────────────────── summary


def test_the_realised_blueprint_reports_what_survived() -> None:
    spec = _spec()
    item, _ = build_mcq(
        spec,
        MCQDraft(
            stem="Q?",
            options=["a", "b", "c", "d"],
            correct_index=1,
            answer="b",
        ),
        None,
    )
    assert item is not None
    summary = summarise([item])
    assert summary.items_by_kind == {"mcq": 1}
    assert summary.items_by_bloom[item.bloom_level] == 1
