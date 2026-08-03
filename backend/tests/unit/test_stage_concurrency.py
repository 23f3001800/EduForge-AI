"""Fan-out concurrency for stages 6, 7 and 8.

These three stages used to `await` one model call at a time in a `for` loop —
the exact shape stage 5 moved away from in `ClassroomContentStage.run`, for a
measured reason: on a real 44-page chapter, activity-generation alone cost
7.9 minutes sequentially while lesson-generation, doing more work, took 2.4
minutes concurrently. This file proves the fan-out stage 5 also introduced here
carries the two properties that make it safe rather than just fast:

1. **Output order survives out-of-order completion.** Tasks are submitted in
   list order and read back in that same order, regardless of which one the
   event loop happened to finish first — proved here by making the *first*
   submitted item the *slowest* to complete.
2. **A failure cancels its siblings.** `asyncio.TaskGroup`, not
   `asyncio.gather`, so one item raising does not leave every other item's
   model call running — and billing — for a job that has already failed. Mirrors
   `test_a_failing_period_cancels_its_siblings_instead_of_letting_them_keep_calling`
   in `tests/integration/test_async_correctness.py`, one level down the stage
   list.

Stage 4 (`s4_planner`) is deliberately not exercised here: its per-period loop
folds the *previous* period's model-written title into the *next* period's
prompt (see the comment above the loop in `stages/s4_planner/stage.py`), which
is a genuine cross-iteration data dependency rather than a leftover for-loop,
so it stays sequential.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from pedagogy.registry import get_strategy
from stages.base import StageContext
from stages.s6_activities.stage import ActivityGenerationStage
from stages.s7_assessments.blueprint import build_blueprint
from stages.s7_assessments.schemas import ConstructedResponseDraft, MCQDraft, RubricLevelDraft
from stages.s7_assessments.stage import AssessmentGenerationStage
from stages.s8_gaps.schemas import DiagnosticDraft, GapDraft, RemediationDraft
from stages.s8_gaps.stage import GapAnalysisStage


def _ctx() -> StageContext:
    return StageContext(job_id=uuid4(), options={})


# ══════════════════════════════════ shared fixtures/state builders ══════════


def _activity_state(periods: int) -> dict[str, Any]:
    """A teaching plan with `periods` independent, single-activity periods."""
    plan = {
        "total_periods": periods,
        "period_duration_minutes": 40,
        "periods": [
            {
                "period_no": index + 1,
                "title": f"Period {index + 1}",
                "objective_ids": [],
                "concept_ids": [],
                "time_allocation": [
                    {"label": "Entry", "minutes": 5},
                    {"label": "Practice", "minutes": 20},
                    {"label": "Exit", "minutes": 5},
                ],
                "sequence_rationale": "x",
            }
            for index in range(periods)
        ],
    }
    return {
        "knowledge": {"concepts": [], "learning_objectives": [], "misconceptions": []},
        "teaching_plan": plan,
        "classification": {
            "pedagogy_profile": "mixed",
            "grade_band": "9-10",
            "difficulty": "intermediate",
            "subject": "Physics",
        },
    }


def _assessment_knowledge(concepts: int = 4, objectives: int = 3) -> dict[str, Any]:
    return {
        "concepts": [
            {"concept_id": f"c{i}", "name": f"Concept {i}", "summary": "s", "importance": "core"}
            for i in range(concepts)
        ],
        "learning_objectives": [
            {
                "objective_id": f"o{i}",
                "statement": f"Objective {i}",
                "bloom_level": "understand",
                "concept_ids": [f"c{i % concepts}"],
            }
            for i in range(objectives)
        ],
        "misconceptions": [],
    }


def _assessment_state(concepts: int = 4, objectives: int = 3) -> dict[str, Any]:
    return {
        "knowledge": _assessment_knowledge(concepts, objectives),
        "classification": {
            "pedagogy_profile": "quantitative",
            "grade_band": "9-10",
            "difficulty": "intermediate",
        },
    }


def _gap_state(n: int) -> dict[str, Any]:
    return {
        "knowledge": {
            "concepts": [
                {
                    "concept_id": f"c{i}",
                    "name": f"Concept {i}",
                    "summary": "s",
                    "importance": "core",
                }
                for i in range(n)
            ],
            "misconceptions": [
                {
                    "misconception_id": f"m{i}",
                    "statement": f"wrong belief {i}",
                    "concept_ids": [f"c{i}"],
                }
                for i in range(n)
            ],
            "concept_graph": {"edges": []},
        },
        "classification": {"pedagogy_profile": "mixed", "grade_band": "9-10"},
    }


def _reversed_delays(n: int, step: float = 0.01) -> list[float]:
    """Item 0 waits longest, the last item waits least — genuine out-of-order
    completion rather than a coincidence of scheduling."""
    return [(n - i) * step for i in range(n)]


# ══════════════════════════════════ stage 6 — activity generation ═══════════


class _OrderedActivityLLM:
    def __init__(self, delays: list[float]) -> None:
        self._delays = delays
        self.call_order: list[int] = []

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        index = len(self.call_order)
        self.call_order.append(index)
        await asyncio.sleep(self._delays[index])
        value = output_model(
            title=f"activity-{index}",
            materials=["chart paper"],
            teacher_instructions=["Step one.", "Step two."],
            student_instructions=["Do the task."],
            success_criteria=["Criterion one."],
            support="Support text.",
            extension="Extension text.",
        )
        return SimpleNamespace(degraded=False, value=value)


async def test_activity_output_order_survives_out_of_order_completion() -> None:
    n = 5
    llm = _OrderedActivityLLM(_reversed_delays(n))
    stage = ActivityGenerationStage(llm)  # type: ignore[arg-type]

    result = await stage.run(_ctx(), _activity_state(periods=n))

    titles = [activity["title"] for activity in result["activities"]]
    assert titles == [f"activity-{i}" for i in range(n)], (
        "activities must come back in submission order even though the slowest "
        f"call was submitted first: {titles}"
    )


class _FailingActivityLLM:
    def __init__(self, delay: float = 0.03) -> None:
        self.delay = delay
        self.started = 0
        self.finished = 0
        self._raised = False

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        self.started += 1
        if not self._raised:
            self._raised = True
            await asyncio.sleep(self.delay)
            raise RuntimeError("boom")
        await asyncio.sleep(self.delay * 8)
        self.finished += 1
        return SimpleNamespace(degraded=False, value=output_model())


async def test_a_failing_activity_cancels_its_siblings() -> None:
    llm = _FailingActivityLLM(delay=0.03)
    stage = ActivityGenerationStage(llm)  # type: ignore[arg-type]

    with pytest.raises(Exception):  # noqa: B017 - TaskGroup raises an ExceptionGroup
        await stage.run(_ctx(), _activity_state(periods=6))

    assert llm.started >= 2, "not enough overlap in flight to prove anything"
    assert llm.finished == 0, (
        f"{llm.finished} sibling call(s) ran to completion after the first one failed — "
        "asyncio.gather does not cancel them, and each one is a billable model call for "
        "a job that had already failed"
    )


# ══════════════════════════════════ stage 7 — assessment generation ═════════


class _OrderedAssessmentLLM:
    def __init__(self, delays: list[float]) -> None:
        self._delays = delays
        self.call_order: list[int] = []

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        index = len(self.call_order)
        self.call_order.append(index)
        await asyncio.sleep(self._delays[index])
        if output_model is MCQDraft:
            value = MCQDraft(
                stem=f"item-{index}",
                options=["Option A", "Option B", "Option C", "Option D"],
                correct_index=0,
                rationales=["a", "b", "c", "d"],
                answer=f"answer-{index}",
            )
        else:
            value = ConstructedResponseDraft(
                stem=f"item-{index}",
                answer=f"answer-{index}",
                rubric_criteria="Accuracy",
                rubric_levels=[
                    RubricLevelDraft(label="Full", descriptor="Complete.", marks=3),
                    RubricLevelDraft(label="Partial", descriptor="Partial.", marks=1),
                ],
            )
        return SimpleNamespace(degraded=False, value=value)


async def test_assessment_output_order_survives_out_of_order_completion() -> None:
    state = _assessment_state()
    n = len(build_blueprint(state["knowledge"], get_strategy("quantitative")).specs)
    assert n >= 4, "the fixture must produce enough items for concurrency to matter"

    llm = _OrderedAssessmentLLM(_reversed_delays(n))
    stage = AssessmentGenerationStage(llm)  # type: ignore[arg-type]

    result = await stage.run(_ctx(), state)

    stems = [item["stem"] for item in result["assessments"]["items"]]
    assert stems == [f"item-{i}" for i in range(n)], (
        "items must come back in blueprint (submission) order even though the slowest "
        f"call was submitted first: {stems}"
    )


class _FailingAssessmentLLM:
    def __init__(self, delay: float = 0.03) -> None:
        self.delay = delay
        self.started = 0
        self.finished = 0
        self._raised = False

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        self.started += 1
        if not self._raised:
            self._raised = True
            await asyncio.sleep(self.delay)
            raise RuntimeError("boom")
        await asyncio.sleep(self.delay * 8)
        self.finished += 1
        return SimpleNamespace(degraded=False, value=output_model())


async def test_a_failing_assessment_item_cancels_its_siblings() -> None:
    llm = _FailingAssessmentLLM(delay=0.03)
    stage = AssessmentGenerationStage(llm)  # type: ignore[arg-type]

    with pytest.raises(Exception):  # noqa: B017 - TaskGroup raises an ExceptionGroup
        await stage.run(_ctx(), _assessment_state())

    assert llm.started >= 2, "not enough overlap in flight to prove anything"
    assert llm.finished == 0, (
        f"{llm.finished} sibling call(s) ran to completion after the first one failed — "
        "asyncio.gather does not cancel them, and each one is a billable model call for "
        "a job that had already failed"
    )


class _ReissueLLM:
    """Exactly two items: `item_01` is an MCQ whose distractors are unusable
    (four identical options), so it must be reissued as a constructed-response
    item using the same slot; `item_02` is a plain short-answer item with no
    reissue at all.

    With only one MCQ spec in play, every MCQ call and every CR call is
    unambiguous: the single MCQ call belongs to `item_01`, its reissue is the
    *second* CR call to arrive (after `item_02`'s own, independent CR call has
    already had the chance to start), and that reissue can only start once the
    MCQ call it depends on has returned.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        if output_model is MCQDraft:
            self.calls.append(("mcq", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.03)
            # Four identical options: build_mcq rejects this (fewer than 4
            # distinct) and the caller must reissue it as a constructed
            # response for the *same* item, sequentially after this call.
            value = MCQDraft(
                stem="Which force?",
                options=["Same", "Same", "Same", "Same"],
                correct_index=0,
                answer="Same",
            )
            return SimpleNamespace(degraded=False, value=value)

        self.calls.append(("cr", asyncio.get_event_loop().time()))
        await asyncio.sleep(0.01)
        value = ConstructedResponseDraft(
            stem="Explain the force.",
            answer="Because the net force is nonzero.",
            rubric_criteria="Accuracy",
            rubric_levels=[
                RubricLevelDraft(label="Full", descriptor="Complete.", marks=3),
                RubricLevelDraft(label="Partial", descriptor="Partial.", marks=1),
            ],
        )
        return SimpleNamespace(degraded=False, value=value)


async def test_mcq_reissue_stays_sequential_within_its_own_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stages.s7_assessments import stage as s7_stage
    from stages.s7_assessments.blueprint import Blueprint, ItemSpec

    fixed_specs = [
        ItemSpec(
            item_id="item_01",
            kind="mcq",
            marks=1,
            bloom_level="remember",
            concept_ids=["c0"],
        ),
        ItemSpec(
            item_id="item_02",
            kind="short_answer",
            marks=3,
            bloom_level="understand",
            concept_ids=["c1"],
        ),
    ]
    monkeypatch.setattr(s7_stage, "build_blueprint", lambda *a, **k: Blueprint(specs=fixed_specs))

    llm = _ReissueLLM()
    stage = AssessmentGenerationStage(llm)  # type: ignore[arg-type]

    result = await stage.run(_ctx(), _assessment_state())

    mcq_calls = [t for kind, t in llm.calls if kind == "mcq"]
    cr_calls = sorted(t for kind, t in llm.calls if kind == "cr")
    assert len(mcq_calls) == 1, "item_01's MCQ call must happen exactly once"
    assert len(cr_calls) == 2, (
        "item_02's own call plus item_01's reissue — two constructed-response calls total"
    )

    # item_02's independent call is free to start immediately, before item_01's
    # MCQ call has even returned — proof the two items ran concurrently rather
    # than the second waiting on the first.
    assert cr_calls[0] < mcq_calls[0] + 0.03, (
        "item_02's own call did not start until after item_01's MCQ call finished — "
        "items are not running concurrently"
    )
    # item_01's reissue is necessarily the later of the two CR calls, and it can
    # only have been issued after its own MCQ call returned.
    assert cr_calls[-1] > mcq_calls[0], (
        "the constructed-response reissue started before its own item's MCQ call finished"
    )

    kinds = [item["kind"] for item in result["assessments"]["items"]]
    assert kinds == ["short_answer", "short_answer"], (
        "item_01 must survive as a short-answer item after its MCQ reissue, and output "
        "order must still follow blueprint (submission) order"
    )


# ══════════════════════════════════ stage 8 — gap analysis ══════════════════


class _OrderedGapLLM:
    def __init__(self, delays: list[float]) -> None:
        self._delays = delays
        self.call_order: list[int] = []

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        index = len(self.call_order)
        self.call_order.append(index)
        await asyncio.sleep(self._delays[index])
        value = GapDraft(
            misconception=f"gap-{index}",
            why_it_happens="everyday experience",
            diagnostic_questions=[
                DiagnosticDraft(question="Q?", reveals="R", expected_wrong_answer="W")
            ],
            remediation=[RemediationDraft(action="Do X.", rationale="Because Y.")],
        )
        return SimpleNamespace(degraded=False, value=value)


async def test_gap_output_order_survives_out_of_order_completion() -> None:
    n = 5
    llm = _OrderedGapLLM(_reversed_delays(n))
    stage = GapAnalysisStage(llm)  # type: ignore[arg-type]

    result = await stage.run(_ctx(), _gap_state(n))

    misconceptions = [gap["misconception"] for gap in result["learning_gaps"]]
    assert misconceptions == [f"gap-{i}" for i in range(n)], (
        "gaps must come back in submission order even though the slowest call was "
        f"submitted first: {misconceptions}"
    )


class _FailingGapLLM:
    def __init__(self, delay: float = 0.03) -> None:
        self.delay = delay
        self.started = 0
        self.finished = 0
        self._raised = False

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        self.started += 1
        if not self._raised:
            self._raised = True
            await asyncio.sleep(self.delay)
            raise RuntimeError("boom")
        await asyncio.sleep(self.delay * 8)
        self.finished += 1
        return SimpleNamespace(degraded=False, value=output_model())


async def test_a_failing_gap_cancels_its_siblings() -> None:
    llm = _FailingGapLLM(delay=0.03)
    stage = GapAnalysisStage(llm)  # type: ignore[arg-type]

    with pytest.raises(Exception):  # noqa: B017 - TaskGroup raises an ExceptionGroup
        await stage.run(_ctx(), _gap_state(6))

    assert llm.started >= 2, "not enough overlap in flight to prove anything"
    assert llm.finished == 0, (
        f"{llm.finished} sibling call(s) ran to completion after the first one failed — "
        "asyncio.gather does not cancel them, and each one is a billable model call for "
        "a job that had already failed"
    )


# ══════════════════════ true concurrency, not just correct ordering ═════════


async def test_activity_generation_runs_concurrently_not_one_at_a_time() -> None:
    """The point of the change: wall time tracks the slowest item, not the sum."""
    n = 6
    delay = 0.05
    llm = _OrderedActivityLLM([delay] * n)
    stage = ActivityGenerationStage(llm)  # type: ignore[arg-type]

    started = asyncio.get_event_loop().time()
    await stage.run(_ctx(), _activity_state(periods=n))
    elapsed = asyncio.get_event_loop().time() - started

    sequential_floor = n * delay
    assert elapsed < sequential_floor * 0.6, (
        f"{elapsed:.3f}s elapsed for {n} activities at {delay}s each — that is close to the "
        f"{sequential_floor:.3f}s a sequential for-loop would have taken, not evidence of "
        "concurrent fan-out"
    )
