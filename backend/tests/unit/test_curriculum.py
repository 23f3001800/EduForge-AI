"""Curriculum board configuration.

A board must change the *output*, not just label it — otherwise "supports CBSE"
means nothing. But it must change it only within what the content supports. Those
two requirements pull against each other, and the tests that matter are the ones
holding the second line: a board that could conjure numerical questions for a
poetry chapter would have quietly undone the whole pedagogy-profile mechanism.
"""

from __future__ import annotations

import pytest

from pedagogy.curriculum import get_board, known_boards, load_boards
from pedagogy.registry import get_strategy
from stages.s7_assessments.blueprint import build_blueprint

QUANT = get_strategy("quantitative")
NARRATIVE = get_strategy("narrative")


def _knowledge(concepts: int = 5, objectives: int = 4) -> dict:
    return {
        "concepts": [
            {"concept_id": f"c{i}", "name": f"Concept {i}", "summary": "s", "importance": "core"}
            for i in range(concepts)
        ],
        "learning_objectives": [
            {"objective_id": f"o{i}", "statement": f"Objective {i}", "bloom_level": "understand"}
            for i in range(objectives)
        ],
    }


def _kinds(strategy, board=None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for spec in build_blueprint(_knowledge(), strategy, board).specs:
        counts[spec.kind] = counts.get(spec.kind, 0) + 1
    return counts


# ─────────────────────────────────────────────────────────────── resolution


def test_every_declared_board_loads() -> None:
    boards = load_boards()
    assert "generic" in boards
    assert {"CBSE", "ICSE"} <= set(boards)
    for profile in boards.values():
        assert profile.period_minutes >= 5
        assert profile.marks_scale > 0


def test_generic_is_offered_first() -> None:
    """A teacher who has no board must not have to scroll past four to find that."""
    assert known_boards()[0] == "generic"


@pytest.mark.parametrize("typed", ["CBSE", "cbse", " CBSE ", "Cbse"])
def test_a_board_name_is_matched_tolerantly(typed: str) -> None:
    """This value is typed by a teacher, not picked from an enum."""
    assert get_board(typed).name == "CBSE"


def test_an_unknown_board_degrades_instead_of_failing_the_job() -> None:
    """A state board nobody configured must still produce a package."""
    assert get_board("Karnataka State Board").is_generic
    assert get_board(None).is_generic
    assert get_board("").is_generic


# ─────────────────────────────────────────────── the board changes the output


def test_cbse_and_icse_produce_measurably_different_banks() -> None:
    """The whole point. If these match, "configurable output" is a claim, not a feature."""
    cbse = _kinds(QUANT, get_board("CBSE"))
    icse = _kinds(QUANT, get_board("ICSE"))
    assert cbse != icse

    # CBSE has moved toward competency-based MCQ; ICSE stays long-form.
    assert cbse.get("mcq", 0) > icse.get("mcq", 0)
    assert icse.get("long_answer", 0) > cbse.get("long_answer", 0)


def test_a_board_scales_marks() -> None:
    base = build_blueprint(_knowledge(), QUANT, get_board("generic")).total_marks
    icse = build_blueprint(_knowledge(), QUANT, get_board("ICSE")).total_marks
    assert icse > base, "ICSE weights longer answers and should carry more marks"


def test_marks_never_round_to_zero() -> None:
    """`AssessmentItem` requires marks >= 1; a scale must not be able to break it."""
    for name in known_boards():
        blueprint = build_blueprint(_knowledge(), QUANT, get_board(name))
        assert all(spec.marks >= 1 for spec in blueprint.specs), name


def test_a_board_supplies_the_period_length_the_teacher_did_not_choose() -> None:
    assert get_board("IB").period_length(None) == 60
    assert get_board("generic").period_length(None) == 40


def test_an_explicit_period_length_beats_the_board() -> None:
    """The teacher is in the room; the board is a default."""
    assert get_board("IB").period_length(35) == 35


# ──────────────────────────────────────── the line a board may not cross


def test_a_board_cannot_conjure_numerical_items_for_narrative_content() -> None:
    """The most important test here.

    The board blend multiplies the profile's mix. A narrative profile weights
    `numerical` at zero, and zero times any bias is zero — so no board, however
    it weights numerical questions, can put one in a poetry chapter. If this ever
    fails, curriculum support has silently defeated the profile mechanism that
    makes the system work across subjects at all.
    """
    for name in known_boards():
        kinds = _kinds(NARRATIVE, get_board(name))
        assert "numerical" not in kinds, f"{name} introduced numerical items"
        assert kinds, f"{name} produced an empty bank"


def test_the_blend_stays_normalised() -> None:
    """A board must shift emphasis, not inflate the bank; the budget is decided elsewhere."""
    for name in known_boards():
        blended = get_board(name).blend(QUANT.assessment_mix)
        assert blended
        assert sum(blended.values()) == pytest.approx(1.0)


def test_a_board_that_zeroes_everything_falls_back_to_the_profile() -> None:
    """Degenerate config must not produce an empty bank."""
    board = get_board("generic")
    hostile = type(board)(
        name="hostile",
        label="Hostile",
        description="",
        period_minutes=40,
        unit_word="chapter",
        assessment_bias=dict.fromkeys(QUANT.assessment_mix, 0.0),
        marks_scale=1.0,
        emphasis=(),
    )
    assert hostile.blend(QUANT.assessment_mix) == QUANT.assessment_mix


def test_generic_adds_no_prompt_noise() -> None:
    """Telling a model to ignore a board it was never told about wastes tokens."""
    assert get_board("generic").prompt_guidance() == ""
    assert get_board("CBSE").prompt_guidance()
