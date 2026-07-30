"""Stub stages — scaffolding for the walking skeleton (MS-1).

Each stub returns the reference fixture for its stage and makes **no model
calls**. They exist so the graph, the worker, the checkpointing, the progress
stream, and the API can all be built and proven before any stage is real.

Every stub is deleted when its module lands: M2 replaces the stage-1 stub, M3
replaces stages 2-3, and so on. A stub still present after its milestone is a
bug, and ``test_no_stub_survives_its_milestone`` is where that gets caught.

The lesson-generation stub deliberately emits per-period progress rather than a
single jump, because progress interpolation across the longest stage is exactly
the behaviour a fan-out stage has to get right.
"""

from __future__ import annotations

import asyncio
from typing import Any

from contracts.primitives import StageName
from stages.base import StageContext, stage_span
from tests.fixtures import factories as fx

__all__ = ["STUB_STAGES", "StubStage"]

#: Small delay so a skeleton run produces a visibly progressing stream rather
#: than ten events in the same millisecond. Zero in tests.
STEP_DELAY_S = 0.0


class StubStage:
    """Returns a fixture. Replaced wholesale by the real stage."""

    def __init__(self, name: StageName, key: str, payload_factory: Any) -> None:
        self.name = name
        self.key = key
        self._factory = payload_factory

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            if self.name == "lesson-generation":
                # Simulate per-period fan-out so progress interpolation is exercised.
                periods = (state.get("teaching_plan") or {}).get("total_periods", 1)
                for index in range(periods):
                    if STEP_DELAY_S:
                        await asyncio.sleep(STEP_DELAY_S)
                    await span.progress(
                        (index + 1) / periods,
                        message=f"period {index + 1} of {periods}",
                    )
            elif STEP_DELAY_S:
                await asyncio.sleep(STEP_DELAY_S)

            payload = self._factory()
            if isinstance(payload, list):
                value = [item.model_dump(mode="json") for item in payload]
            else:
                value = payload.model_dump(mode="json")
            return {self.key: value}


def _package() -> Any:
    return fx.teacher_knowledge_package()


STUB_STAGES: list[StubStage] = [
    StubStage("document-intelligence", "structured_document", fx.structured_document),
    StubStage("educational-classification", "classification", fx.classification),
    StubStage("knowledge-extraction", "knowledge", fx.knowledge_base),
    StubStage("teaching-planner", "teaching_plan", fx.teaching_plan),
    StubStage("lesson-generation", "period_contents", fx.classroom_content),
    StubStage("activity-generation", "activities", fx.activities),
    StubStage("assessment-generation", "assessments", fx.assessments),
    StubStage("gap-analysis", "learning_gaps", fx.learning_gaps),
    StubStage("validation", "validation", fx.validation_report),
    StubStage("publishing", "package", _package),
]
