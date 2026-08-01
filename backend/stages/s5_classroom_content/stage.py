"""Stage 5 — Classroom Content Generation.

Produces the eight per-period artifacts a teacher actually reads in the room
(FR-06): entry ticket, timed teacher script, blackboard notes, activity
references, checkpoint questions, exit ticket, homework, and a mentor moment.

This is the largest single share of the grade, and the bar is not schema validity.
A script is only useful if a teacher who has not pre-read it can run the period
from it aloud, which means timed beats, explicit board actions, and the questions
students will actually ask. Entry and exit tickets are only useful if they
*diagnose*; a prompt that every student can answer correctly regardless of whether
they learned anything has occupied five minutes and told the teacher nothing.

Two structural decisions carry most of the quality:

**Two narrow calls per period, not one wide one.** The taught half and the
checking half are requested separately, so a weak call costs one half of one
period rather than the period, and neither schema is wide enough to trigger the
empty-generation failure stage 3 measured.

**A narrowed context per period.** Each call sees only its own concepts,
objectives, definitions, examples, and misconceptions, plus one line about its
neighbours. A period cannot teach another period's material because it is never
shown it, and the prompt stays small enough for a small model to write well in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block
from pedagogy.registry import ProfileStrategy, get_strategy
from stages.base import StageContext, stage_span
from stages.s5_classroom_content.assembly import build_period_content
from stages.s5_classroom_content.briefs import PeriodBrief, build_briefs
from stages.s5_classroom_content.schemas import LessonClose, LessonCore

__all__ = ["ClassroomContentStage"]

SYSTEM_CORE = """You write the taught half of one school period: how it opens, \
what the teacher says and does minute by minute, and what ends up on the board.

Write for a teacher who has NOT pre-read this and is holding it in front of the \
class. That single constraint decides everything else.

`entry_ticket` — a short opening task that surfaces what students already believe. \
It must be answerable in a few minutes with no preparation, and a wrong answer \
must be informative: prefer a prompt where a common misconception produces a \
visibly different answer from understanding. "What is today's topic?" diagnoses \
nothing.

`teacher_script` — 4 to 6 beats covering the whole period in order. For each beat:
- `heading`: what this beat is, in a few words.
- `minutes`: how long it takes. Proportions matter; the timeline is laid out \
afterwards, so do not write clock times or ranges.
- `speaker_notes`: what the teacher actually says or does. Write it so it can be \
read aloud or followed directly — name the example to use, the question to ask, \
the thing to point at. "Explain the concept" is not usable in a classroom; \
"Draw the two arrows first, then ask why they cancel" is.
- `board_action`: what goes on the board during this beat, if anything.
- `anticipated_questions`: what students in this grade band actually ask here, \
including the questions that come from the misconceptions you were given.

`blackboard_notes` — what is physically written on the board, not a summary of \
the lesson. Headings, short bullet points a student can copy, and any diagrams \
worth drawing. Only include a formula if the source material states one; if you \
were told the source states none, write none.

Use the source definitions and examples you were given rather than inventing \
parallel ones. Teach every concept listed and nothing beyond them."""

SYSTEM_CLOSE = """You write the checking half of one school period: whether it \
landed, how it closes, and what carries over.

`checkpoint_questions` — 2 or 3 mid-lesson checks. Each must be answerable in \
under a minute and must distinguish a student who understands from one who is \
following along. Pitch them at the Bloom level of the objective they check, and \
give the expected answer in enough detail to mark it on the spot.

`exit_ticket` — one prompt that tests the period's objective, not the period's \
topic. `success_indicator` is what a correct response contains, written so a \
teacher can sort a pile of tickets in under a minute.

`homework` — 1 to 3 tasks that consolidate what was taught, sized honestly in \
`estimated_minutes` for this grade band. Do not set work that requires material \
the period did not cover.

`mentor_moment` — a short, true-to-life anecdote connected to this period's \
content, with a takeaway a student can use. This is the one place you may draw on \
general knowledge rather than the source document; it is flagged as ungrounded so \
it is not judged as an unsupported claim. Keep it under 80 words and keep it \
specific — a generic encouragement to work hard is worth nothing."""


def audience_brief(classification: Mapping[str, Any]) -> str:
    """Grade band and difficulty as a hard constraint on vocabulary and demand."""
    grade = classification.get("grade_band") or "unspecified"
    difficulty = classification.get("difficulty") or "intermediate"
    subject = classification.get("subject") or "this material"
    return (
        f"AUDIENCE: grade band {grade}, {difficulty} level, {subject}.\n"
        f"Every sentence a student reads or hears must be readable at grade {grade}. "
        "Task complexity and cognitive demand must match that band too — correct "
        "content pitched two years high is unusable in the room."
    )


def language_directive(language: str | None) -> str:
    """Translate values, never keys (BR-06)."""
    if not language or language.lower().startswith("en"):
        return ""
    return (
        f"\n\nOUTPUT LANGUAGE: write every natural-language value in {language}. "
        "JSON keys stay in English exactly as the schema names them."
    )


class ClassroomContentStage:
    """Replaces the stage-5 stub."""

    name = "lesson-generation"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _core(self, span: Any, system: str, brief: PeriodBrief) -> LessonCore:
        result = await self._llm.parse(
            stage=self.name,
            output_model=LessonCore,
            system=system,
            user_content=(
                f"{document_block(brief.as_prompt())}\n\n"
                "Write the entry ticket, the teacher script, and the blackboard "
                "notes for this period. Return only the keys `entry_ticket`, "
                "`teacher_script`, and `blackboard_notes`."
            ),
        )
        if result.degraded:
            span.warn(f"period {brief.period_no}: lesson core degraded; script rebuilt from plan")
        return result.value

    async def _close(self, span: Any, system: str, brief: PeriodBrief) -> LessonClose:
        result = await self._llm.parse(
            stage=self.name,
            output_model=LessonClose,
            system=system,
            user_content=(
                f"{document_block(brief.as_prompt())}\n\n"
                "Write the checkpoint questions, the exit ticket, the homework, and "
                "the mentor moment for this period. Return only the keys "
                "`checkpoint_questions`, `exit_ticket`, `homework`, and "
                "`mentor_moment`."
            ),
        )
        if result.degraded:
            span.warn(
                f"period {brief.period_no}: lesson close degraded; checks derived from objectives"
            )
        return result.value

    def _system(
        self,
        base: str,
        strategy: ProfileStrategy,
        classification: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> str:
        return (
            f"{base}\n\n{strategy.prompt_guidance()}\n\n"
            f"{audience_brief(classification)}\n\n{OUTPUT_DISCIPLINE}"
            f"{language_directive(options.get('output_language'))}"
        )

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            knowledge: dict[str, Any] = state.get("knowledge") or {}
            plan: dict[str, Any] = state.get("teaching_plan") or {}
            classification: dict[str, Any] = state.get("classification") or {}
            options = ctx.options or {}
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))

            briefs = build_briefs(knowledge, plan)
            if not briefs:
                raise ValueError(
                    "cannot generate classroom content: the teaching plan contains no periods"
                )

            system_core = self._system(SYSTEM_CORE, strategy, classification, options)
            system_close = self._system(SYSTEM_CLOSE, strategy, classification, options)

            total = len(briefs)
            done = 0

            async def generate(brief: PeriodBrief) -> tuple[dict[str, Any], list[str]]:
                """One period, start to finish.

                Periods are independent — each brief carries its own concepts,
                objectives and neighbours — so there is no ordering constraint
                between them, only within one. Generating them concurrently turns
                the longest stage in the pipeline from N sequential round trips
                into roughly one, and this stage is 25% of a run.

                Concurrency is bounded by the LLM client's own semaphore rather
                than here, so the ceiling stays in one place and a provider's
                rate limit is respected across every stage at once, not per
                stage.
                """
                nonlocal done
                core = await self._core(span, system_core, brief)
                close = await self._close(span, system_close, brief)
                content, notes = build_period_content(brief, core, close)

                done += 1
                # Reported on completion rather than on start: with work in
                # flight, "starting period 4" while 2 and 3 are unfinished
                # overstates progress.
                #
                # Scaled to 0.95 so the last period to finish lands below the
                # closing summary below it. Reaching a full 1.0 here made the
                # stage emit 65, 64, 65 — the ProgressEmitter would have clamped
                # that in production, which is exactly why the stage must not
                # rely on it: a bar that only looks monotonic because something
                # downstream hides the mistake is still wrong.
                await span.progress(
                    0.95 * done / total, message=f"period {brief.period_no} complete"
                )
                return content.model_dump(mode="json"), notes

            # gather preserves input order, so periods come back sequenced even
            # though they were produced out of order.
            results = await asyncio.gather(*(generate(brief) for brief in briefs))

            contents: list[dict[str, Any]] = []
            for brief, (content, notes) in zip(briefs, results, strict=True):
                for note in notes:
                    span.warn(f"period {brief.period_no}: {note}")
                contents.append(content)

            await span.progress(0.98, message=f"{total} periods of classroom content")
            return {"period_contents": contents}
