"""Stage 6 — Activity Generation.

Produces the classroom activities referenced by the lesson content (FR-07). The
quality bar is whether a teacher could run the activity from the page without
interpreting it: real materials a real classroom has, instructions specific enough
to follow, success criteria observable while it is happening rather than after
marking, and differentiation in both directions.

The structural half — how many activities, of what type, for how long, attached to
which concepts — is decided in ``selection.py`` from the plan and the profile's
activity weights. The model writes only prose. That is what makes variety and
profile-conditioning testable properties rather than prompt aspirations, and it is
why a narrative package opens with debate and a quantitative one with a problem
set without any stage ever seeing a subject name.

Activity ids are deterministic (``act_p3_1``), which is what lets stage 5 write
``activity_refs`` before this stage has run. The two stages cannot import each
other, so the id scheme is mirrored in both and pinned by a test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from contracts.content import Activity
from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block
from pedagogy.curriculum import get_board
from pedagogy.registry import get_strategy
from stages.base import StageContext, stage_span
from stages.s6_activities.schemas import ActivityDraft
from stages.s6_activities.selection import ActivitySlot, plan_slots

__all__ = ["ActivityGenerationStage"]

SYSTEM = """You write one classroom activity. Its type, its length, and the \
concepts it covers have already been decided; you write what the teacher and the \
students actually do.

The test of this output is whether a teacher can run it from the page in a real \
room without interpreting anything.

`title` — short and concrete. Name the thing students do, not the topic.

`materials` — only things an ordinary classroom already has or a teacher can \
prepare in ten minutes. Chart paper, a stopwatch, a printed slip per pair, the \
textbook. If the activity needs nothing, return an empty list; inventing a lab \
kit makes the activity undeliverable.

`teacher_instructions` — 3 to 5 numbered steps in the order they happen, \
including how students are grouped, what is said to start, and what the teacher \
does while the activity runs. "Facilitate discussion" is not an instruction.

`student_instructions` — what students are told, in words they can read.

`success_criteria` — 2 or 3 things a teacher can OBSERVE while circulating, in \
this period. "Students understand the concept" is not observable. "Each pair can \
point to the step where the two forces cancel" is.

`support` — a concrete scaffold for students who cannot start: a sentence frame, \
a worked first item, a reduced set, a partner pairing. Not "give extra help".

`extension` — a genuinely harder question for students who finish early, not more \
of the same task.

Stay inside the concepts you were given, and pitch every instruction at the grade \
band stated."""


def audience_brief(classification: Mapping[str, Any]) -> str:
    grade = classification.get("grade_band") or "unspecified"
    difficulty = classification.get("difficulty") or "intermediate"
    subject = classification.get("subject") or "this material"
    return (
        f"AUDIENCE: grade band {grade}, {difficulty} level, {subject}.\n"
        f"Group sizes, reading level, and task complexity must suit grade {grade}."
    )


def language_directive(language: str | None) -> str:
    """Translate values, never keys (BR-06)."""
    if not language or language.lower().startswith("en"):
        return ""
    return (
        f"\n\nOUTPUT LANGUAGE: write every natural-language value in {language}. "
        "JSON keys stay in English exactly as the schema names them."
    )


def slot_brief(
    slot: ActivitySlot,
    concepts_by_id: Mapping[str, Mapping[str, Any]],
    objectives_by_id: Mapping[str, Mapping[str, Any]],
    misconceptions: list[Mapping[str, Any]],
) -> str:
    """The narrowed context for one activity: its period's material and nothing else."""
    lines = [
        f"ACTIVITY TYPE: {slot.activity_type.replace('_', ' ')}",
        f"LENGTH: {slot.duration_minutes} minutes",
        f"PERIOD {slot.period_no}: {slot.period_title}",
        "",
        "CONCEPTS THIS ACTIVITY MUST PRACTISE:",
        *(
            f"  - {concepts_by_id.get(cid, {}).get('name', cid)}: "
            f"{concepts_by_id.get(cid, {}).get('summary', '')}"
            for cid in slot.concept_ids
        ),
        "",
        "OBJECTIVES IT SERVES:",
        *(
            f"  - {objectives_by_id.get(oid, {}).get('statement', oid)}"
            for oid in slot.objective_ids
        ),
    ]
    if misconceptions:
        lines += [
            "",
            "MISCONCEPTIONS WORTH SURFACING DURING THIS ACTIVITY:",
            *(f"  - {m.get('statement')}" for m in misconceptions[:3]),
        ]
    return "\n".join(lines)


def build_activity(
    slot: ActivitySlot, draft: ActivityDraft, concepts_by_id: Mapping[str, Mapping[str, Any]]
) -> tuple[Activity, list[str]]:
    """Assemble a validated ``Activity`` from the slot's structure and the draft's prose.

    Every fallback is derived from the slot's own concepts rather than from
    boilerplate, and every one of them is reported. A degraded activity that reads
    as though it were authored is worse than one flagged as thin.
    """
    notes: list[str] = []
    names = [str(concepts_by_id.get(cid, {}).get("name") or cid) for cid in slot.concept_ids]
    subject_of = ", ".join(names) or slot.period_title
    readable = slot.activity_type.replace("_", " ")

    teacher_steps = [step.strip() for step in draft.teacher_instructions if step and step.strip()]
    if not teacher_steps:
        notes.append("teacher instructions were empty; a minimal runnable sequence was derived")
        teacher_steps = [
            f"Set up the {readable} and state that the focus is {subject_of}.",
            f"Run the {readable} for {max(1, slot.duration_minutes - 4)} minutes, "
            "circulating and listening for the misconception named in the lesson notes.",
            "Close by taking two responses and correcting one common error aloud.",
        ]

    criteria = [item.strip() for item in draft.success_criteria if item and item.strip()]
    if not criteria:
        notes.append("success criteria were empty; derived from the activity's concepts")
        criteria = [
            f"Each group can state what {names[0] if names else subject_of} means in their "
            "own words when asked.",
            "Each group produces the required output before the time is up.",
        ]

    support = draft.support.strip() or (
        f"Give a sentence frame and one completed example for {subject_of} before the group starts."
    )
    extension = draft.extension.strip() or (
        f"Ask for a case where {subject_of} would give a different result, and why."
    )
    if not draft.support.strip() or not draft.extension.strip():
        notes.append("differentiation was incomplete; a derived scaffold was substituted")

    activity = Activity.model_validate(
        {
            "activity_id": slot.activity_id,
            "period_no": slot.period_no,
            "type": slot.activity_type,
            "title": draft.title.strip() or f"{readable.title()}: {subject_of}",
            "duration_minutes": slot.duration_minutes,
            "materials": [item.strip() for item in draft.materials if item and item.strip()],
            "teacher_instructions": teacher_steps,
            "student_instructions": [
                item.strip() for item in draft.student_instructions if item and item.strip()
            ],
            "success_criteria": criteria,
            "differentiation": {"support": support, "extension": extension},
            "concept_ids": slot.concept_ids,
        }
    )
    return activity, notes


class ActivityGenerationStage:
    """Replaces the stage-6 stub."""

    name = "activity-generation"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            knowledge: dict[str, Any] = state.get("knowledge") or {}
            plan: dict[str, Any] = state.get("teaching_plan") or {}
            classification: dict[str, Any] = state.get("classification") or {}
            options = ctx.options or {}
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))

            slots = plan_slots(plan, strategy)
            if not slots:
                raise ValueError(
                    "cannot generate activities: the teaching plan contains no periods"
                )

            concepts_by_id = {str(c["concept_id"]): c for c in (knowledge.get("concepts") or [])}
            objectives_by_id = {
                str(o["objective_id"]): o for o in (knowledge.get("learning_objectives") or [])
            }
            all_misconceptions = list(knowledge.get("misconceptions") or [])

            system = (
                f"{SYSTEM}\n\n{strategy.prompt_guidance()}\n\n"
                f"{get_board(options.get('curriculum_board')).prompt_guidance()}\n\n"
                f"{audience_brief(classification)}\n\n{OUTPUT_DISCIPLINE}"
                f"{language_directive(options.get('output_language'))}"
            )

            total = len(slots)
            done = 0

            async def generate(slot: ActivitySlot) -> tuple[dict[str, Any], list[str]]:
                """One activity, start to finish.

                Slots are independent — each carries its own period, concepts and
                objectives, drawn from the plan rather than from a sibling slot —
                so there is no ordering constraint between them, only within one.
                Generating them concurrently is the same move stage 5 made for
                periods, and for the same reason: this stage was the second-largest
                share of a run's wall time and was paying for it one round trip at
                a time.

                Concurrency is bounded by the LLM client's own semaphore rather
                than here, so the ceiling stays in one place and a provider's rate
                limit is respected across every stage at once, not per stage.
                """
                nonlocal done
                relevant = [
                    m
                    for m in all_misconceptions
                    if set(slot.concept_ids) & {str(c) for c in (m.get("concept_ids") or [])}
                ]
                brief = slot_brief(slot, concepts_by_id, objectives_by_id, relevant)
                result = await self._llm.parse(
                    stage=self.name,
                    output_model=ActivityDraft,
                    system=system,
                    user_content=(
                        f"{document_block(brief)}\n\n"
                        f"Write the {slot.activity_type.replace('_', ' ')} described above. "
                        "Return only the keys `title`, `materials`, "
                        "`teacher_instructions`, `student_instructions`, "
                        "`success_criteria`, `support`, and `extension`."
                    ),
                )
                if result.degraded:
                    span.warn(f"{slot.activity_id}: activity generation degraded")

                activity, notes = build_activity(slot, result.value, concepts_by_id)

                done += 1
                # Reported on completion rather than on start, and scaled below
                # 1.0 — see stage 5's `ClassroomContentStage.run` for why: with
                # slots finishing out of submission order, reporting on start can
                # run progress backwards, and reaching a full 1.0 here would race
                # the closing summary below it.
                await span.progress(
                    0.95 * done / total,
                    message=f"{slot.activity_type} for period {slot.period_no}",
                )
                return activity.model_dump(mode="json"), notes

            # TaskGroup rather than asyncio.gather: gather does not cancel its
            # siblings when one coroutine raises, so a mid-run failure would leave
            # the other slots' calls in flight, making billable LLM requests for a
            # job that had already failed. TaskGroup cancels every sibling the
            # instant one task raises.
            #
            # Tasks are appended in submission order and read back in that same
            # order below, so activities stay sequenced even though they complete
            # out of order — the same guarantee `gather` gave for free.
            tasks: list[asyncio.Task[tuple[dict[str, Any], list[str]]]] = []
            async with asyncio.TaskGroup() as tg:
                for slot in slots:
                    tasks.append(tg.create_task(generate(slot)))
            results = [task.result() for task in tasks]

            activities: list[dict[str, Any]] = []
            for slot, (activity, notes) in zip(slots, results, strict=True):
                for note in notes:
                    span.warn(f"{slot.activity_id}: {note}")
                activities.append(activity)

            distinct = {a["type"] for a in activities}
            await span.progress(
                0.98,
                message=f"{len(activities)} activities, {len(distinct)} distinct types",
            )
            return {"activities": activities}
