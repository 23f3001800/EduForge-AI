"""Two properties that are easy to claim and easy to get wrong.

Concurrency: stage 5 is the longest stage in the pipeline and its periods are
independent, so they must overlap. A test that only checked the output would pass
just as happily against the sequential version — so this one measures the overlap
directly.

Language: BR-06 says natural-language *values* are translated while JSON *keys*
stay English. The keys half is what keeps every downstream consumer working, and
it is the half a prompt can silently break.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from stages.base import StageContext
from stages.s4_planner.stage import language_directive as planner_directive
from stages.s5_classroom_content.stage import ClassroomContentStage
from stages.s5_classroom_content.stage import language_directive as content_directive
from stages.s6_activities.stage import language_directive as activity_directive
from stages.s7_assessments.stage import language_directive as assessment_directive
from stages.s8_gaps.stage import language_directive as gap_directive
from tests.fixtures import factories as fx

DIRECTIVES = {
    "planner": planner_directive,
    "classroom-content": content_directive,
    "activities": activity_directive,
    "assessments": assessment_directive,
    "gaps": gap_directive,
}


# ─────────────────────────────────────────────── stage 5 concurrency


class _SlowLLM:
    """Records when each call starts and ends, so overlap is measurable."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.spans: list[tuple[float, float]] = []
        self.peak = 0
        self._live = 0

    async def parse(self, *, output_model: Any, **_: Any) -> Any:
        self._live += 1
        self.peak = max(self.peak, self._live)
        started = asyncio.get_event_loop().time()
        await asyncio.sleep(self.delay)
        ended = asyncio.get_event_loop().time()
        self.spans.append((started, ended))
        self._live -= 1

        class Result:
            degraded = False
            value = output_model.model_construct()

        return Result()


def _state(periods: int = 4) -> dict[str, Any]:
    plan = fx.teaching_plan().model_dump(mode="json")
    template = plan["periods"][0]
    plan["periods"] = [
        {**template, "period_no": index + 1, "title": f"Period {index + 1}"}
        for index in range(periods)
    ]
    plan["total_periods"] = periods
    return {
        "knowledge": fx.knowledge_base().model_dump(mode="json"),
        "teaching_plan": plan,
        "classification": fx.classification().model_dump(mode="json"),
    }


async def test_periods_are_generated_concurrently() -> None:
    """The output alone cannot tell you this — only the timing can.

    Stage 5 carries 25% of a run's weight and its periods share no state, so
    generating them one after another wasted most of the wall clock on waiting.
    """
    llm = _SlowLLM(delay=0.05)
    stage = ClassroomContentStage(llm)  # type: ignore[arg-type]
    ctx = StageContext(job_id=uuid4(), options={})

    started = asyncio.get_event_loop().time()
    await stage.run(ctx, _state(periods=4))
    elapsed = asyncio.get_event_loop().time() - started

    # 4 periods x 2 calls x 50ms = 400ms strictly sequential. Concurrency must
    # beat that decisively; the threshold is loose so this does not turn into a
    # flaky benchmark on a loaded machine.
    assert elapsed < 0.30, f"took {elapsed:.3f}s — periods look sequential"
    assert llm.peak > 1, "no two calls were ever in flight together"


async def test_periods_come_back_in_order() -> None:
    """Concurrency must not reorder the lesson.

    Period 3 arriving before period 2 is normal in flight and unacceptable in
    output — a plan whose periods are shuffled is worse than a slow one.
    """
    stage = ClassroomContentStage(_SlowLLM(delay=0.01))  # type: ignore[arg-type]
    ctx = StageContext(job_id=uuid4(), options={})

    result = await stage.run(ctx, _state(periods=5))
    numbers = [period["period_no"] for period in result["period_contents"]]
    assert numbers == [1, 2, 3, 4, 5]


async def test_progress_never_moves_backwards_under_concurrency() -> None:
    """Out-of-order completions must not make the bar jump back."""
    seen: list[int] = []

    async def emit(*, stage: str, progress: int, message: str | None = None, **_: Any) -> None:
        seen.append(progress)

    stage = ClassroomContentStage(_SlowLLM(delay=0.01))  # type: ignore[arg-type]
    ctx = StageContext(job_id=uuid4(), options={}, emit=emit)
    await stage.run(ctx, _state(periods=4))

    assert seen == sorted(seen), f"progress went backwards: {seen}"


# ─────────────────────────────────────────────────────── BR-06 language


@pytest.mark.parametrize("stage_name", sorted(DIRECTIVES))
def test_english_adds_no_directive(stage_name: str) -> None:
    """Telling a model to write English when it already would is wasted tokens."""
    directive = DIRECTIVES[stage_name]
    assert directive("en") == ""
    assert directive("en-GB") == ""
    assert directive(None) == ""
    assert directive("") == ""


@pytest.mark.parametrize("stage_name", sorted(DIRECTIVES))
def test_a_non_english_language_instructs_values_only(stage_name: str) -> None:
    """The keys half is what keeps every downstream consumer working.

    A package whose keys were translated would fail schema validation, break the
    viewer, and break the PDF renderers — all at once, and all silently until
    something tried to read it.
    """
    directive = DIRECTIVES[stage_name]("hi")
    assert "hi" in directive
    lowered = directive.lower()
    assert "keys stay in english" in lowered
    assert "natural-language value" in lowered


def test_every_generation_stage_carries_the_directive() -> None:
    """A stage that forgets it produces one English section in a Hindi package."""
    assert set(DIRECTIVES) == {
        "planner",
        "classroom-content",
        "activities",
        "assessments",
        "gaps",
    }
    for name, directive in DIRECTIVES.items():
        assert directive("fr"), f"{name} produced no directive for a non-English language"
