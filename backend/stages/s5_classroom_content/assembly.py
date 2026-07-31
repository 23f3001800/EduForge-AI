"""Stage 5's deterministic half — the part the model is not allowed to get wrong.

Two classes of failure are repaired here rather than prompted against, because
prompting against arithmetic does not work:

**The lesson timeline.** ``PeriodContent`` rejects overlapping script segments,
and models produce overlapping ones constantly — a 40-minute period comes back as
five beats that add to 47 and whose windows are copied from an example. So the
model is never asked for a window. It says how long a beat takes; the timeline is
laid out here by cumulative sum, which cannot overlap and cannot overrun.

**Board formulae.** ``formulae_latex`` is rebuilt from the formulae the source
document actually stated for this period's concepts, and the model's suggestions
are discarded. That is what makes "no formulae in a poetry lesson" a structural
guarantee rather than a hope: if extraction found none, none can reach the board.
A plausible invented equation is worse than a blank board, because a teacher will
copy it out.

Everything else here is fallback construction. When a call degrades, the period
still has to be teachable, so the fallbacks are derived from real content — this
period's concept names, its objectives, its source definitions — rather than from
boilerplate. They are also reported, so a degraded period is visible in the
validation report instead of passing as if it were authored.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from contracts.content import PeriodContent
from stages.s5_classroom_content.briefs import PeriodBrief
from stages.s5_classroom_content.schemas import LessonClose, LessonCore, ScriptSegmentDraft

__all__ = [
    "PRIMARY_ACTIVITY_INDEX",
    "activity_id",
    "apportion",
    "build_period_content",
    "lay_out_script",
]

#: Hard ceiling on script beats. More than this in a single period is not a
#: lesson plan, it is a transcript, and a teacher cannot follow it in the room.
MAX_SEGMENTS = 10

#: The activity slot every period is guaranteed to have. Stage 5 references this
#: id from ``activity_refs`` before stage 6 has run, and stage 6 always mints it —
#: the two stages cannot import each other, so the id scheme is mirrored in both
#: and pinned by ``test_activity_refs_resolve_against_generated_activities``.
PRIMARY_ACTIVITY_INDEX = 1


def activity_id(period_no: int, index: int = PRIMARY_ACTIVITY_INDEX) -> str:
    """Deterministic activity id. Mirrored in ``stages/s6_activities/selection.py``."""
    return f"act_p{period_no}_{index}"


def apportion(raw: Sequence[tuple[str, float]], total: int) -> list[int]:
    """Largest-remainder rounding onto a whole-minute total, every slot >= 1."""
    if not raw:
        return []
    target = max(total, len(raw))
    floors = [max(1, int(value)) for _, value in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i][1] - int(raw[i][1])), i))

    deficit = target - sum(floors)
    cursor = 0
    while deficit > 0:
        floors[order[cursor % len(order)]] += 1
        deficit -= 1
        cursor += 1
    while deficit < 0:
        spare = [i for i, value in enumerate(floors) if value > 1]
        if not spare:
            break
        floors[max(spare, key=lambda i: floors[i])] -= 1
        deficit += 1
    return floors


# ----------------------------------------------------------------- fallbacks


def _objective_phrase(brief: PeriodBrief) -> str:
    if not brief.objectives:
        return f"explain {', '.join(brief.concept_names) or brief.title}"
    statement = str(brief.objectives[0].get("statement") or "").strip().rstrip(".")
    return statement[:1].lower() + statement[1:] if statement else brief.title


def _fallback_notes(heading: str, brief: PeriodBrief) -> str:
    names = ", ".join(brief.concept_names) or brief.title
    return (
        f"{heading}: work through {names} with the class, keeping to the board notes "
        f"below. Circulate and check that students can {_objective_phrase(brief)}."
    )


def _fallback_segments(brief: PeriodBrief) -> list[ScriptSegmentDraft]:
    """A runnable script built from the plan's own arc when the call produced none."""
    slots = brief.time_allocation or [{"label": "Lesson", "minutes": brief.duration_minutes}]
    return [
        ScriptSegmentDraft(
            heading=str(slot.get("label") or "Lesson"),
            speaker_notes=_fallback_notes(str(slot.get("label") or "Lesson"), brief),
            minutes=int(slot.get("minutes") or 0),
        )
        for slot in slots
    ]


def _fallback_checkpoints(brief: PeriodBrief) -> list[dict[str, Any]]:
    """Checks derived from the objectives this period claims to complete."""
    questions: list[dict[str, Any]] = []
    for objective in brief.objectives[:2]:
        statement = str(objective.get("statement") or "").strip().rstrip(".")
        if not statement:
            continue
        target = next(
            (
                c
                for c in brief.concepts
                if str(c.get("concept_id")) in {str(x) for x in objective.get("concept_ids") or []}
            ),
            brief.concepts[0] if brief.concepts else {},
        )
        questions.append(
            {
                "question": f"In your own words: {statement[:1].lower() + statement[1:]}?",
                "expected_answer": str(
                    target.get("summary") or f"A correct account of {statement}."
                ),
                "bloom_level": str(objective.get("bloom_level") or "understand"),
                "concept_ids": [
                    cid for cid in (objective.get("concept_ids") or []) if cid in brief.concept_ids
                ],
            }
        )
    if questions:
        return questions

    name = (brief.concept_names or [brief.title])[0]
    summary = str(brief.concepts[0].get("summary")) if brief.concepts else brief.title
    return [
        {
            "question": f"Explain {name} in one sentence, in your own words.",
            "expected_answer": summary,
            "bloom_level": "understand",
            "concept_ids": brief.concept_ids[:1],
        }
    ]


def _clamp_ticket(minutes: int, duration: int, default: int) -> int:
    """Tickets are bounded at 15 minutes by contract, and a third of the bell by sense."""
    ceiling = max(1, min(15, duration // 3))
    return max(1, min(minutes or default, ceiling))


# -------------------------------------------------------------------- script


def lay_out_script(
    drafts: Sequence[ScriptSegmentDraft], brief: PeriodBrief
) -> tuple[list[dict[str, Any]], list[str]]:
    """Place the model's beats on a real timeline.

    Returns the segments plus any notes worth surfacing. Durations are the model's
    judgement, rescaled; the windows are arithmetic and are computed here so they
    cannot overlap.
    """
    notes: list[str] = []
    usable = [
        draft
        for draft in drafts
        if (draft.heading or "").strip() or (draft.speaker_notes or "").strip()
    ]
    if not usable:
        notes.append("teacher script was empty; rebuilt from the plan's time allocation")
        usable = _fallback_segments(brief)

    if len(usable) > MAX_SEGMENTS:
        notes.append(f"teacher script truncated from {len(usable)} to {MAX_SEGMENTS} segments")
        usable = usable[:MAX_SEGMENTS]
    # Every segment needs a whole minute, so a period cannot carry more beats than
    # it has minutes.
    usable = usable[: max(1, brief.duration_minutes)]

    weights = [float(draft.minutes) for draft in usable]
    if sum(weights) <= 0:
        planned = [float(slot.get("minutes") or 0) for slot in brief.time_allocation]
        weights = (
            planned
            if len(planned) == len(usable) and sum(planned) > 0
            else [brief.duration_minutes / len(usable)] * len(usable)
        )

    scale = brief.duration_minutes / sum(weights)
    minutes = apportion(
        [
            (draft.heading or "Lesson", weight * scale)
            for draft, weight in zip(usable, weights, strict=True)
        ],
        brief.duration_minutes,
    )

    segments: list[dict[str, Any]] = []
    cursor = 0
    for draft, span in zip(usable, minutes, strict=True):
        heading = (draft.heading or "").strip() or f"Segment {len(segments) + 1}"
        segments.append(
            {
                "minute_start": cursor,
                "minute_end": cursor + span,
                "heading": heading,
                "speaker_notes": (draft.speaker_notes or "").strip()
                or _fallback_notes(heading, brief),
                "board_action": (draft.board_action or "").strip() or None,
                "anticipated_questions": [
                    q.strip() for q in draft.anticipated_questions if q and q.strip()
                ],
            }
        )
        cursor += span
    return segments, notes


# ------------------------------------------------------------------ assembly


def build_period_content(
    brief: PeriodBrief, core: LessonCore, close: LessonClose
) -> tuple[PeriodContent, list[str]]:
    """Assemble one validated ``PeriodContent`` from two drafts and the brief."""
    notes: list[str] = []
    segments, script_notes = lay_out_script(core.teacher_script, brief)
    notes.extend(script_notes)

    names = brief.concept_names or [brief.title]

    entry = core.entry_ticket
    entry_prompt = (entry.prompt or "").strip()
    if not entry_prompt:
        notes.append("entry ticket was empty; derived from the period's concepts")
        recall = ", ".join(brief.previous_concepts) if brief.previous_concepts else names[0]
        entry_prompt = f"On your own, in one sentence: what do you already know about {recall}?"
    entry_expected = (entry.expected_response or "").strip() or (
        f"Any reasonable prior idea about {names[0]}; misconceptions here are useful "
        "and should be left uncorrected until the lesson addresses them."
    )

    exit_ticket = close.exit_ticket
    exit_prompt = (exit_ticket.prompt or "").strip()
    if not exit_prompt:
        notes.append("exit ticket was empty; derived from the period's objectives")
        exit_prompt = f"In one or two sentences, {_objective_phrase(brief)}."
    exit_indicator = (exit_ticket.success_indicator or "").strip() or (
        f"The response addresses {names[0]} directly and is consistent with the "
        "definition used in the lesson."
    )

    checkpoints = [
        {
            "question": (draft.question or "").strip(),
            "expected_answer": (draft.expected_answer or "").strip(),
            "bloom_level": draft.bloom_level,
            "concept_ids": [cid for cid in draft.concept_ids if cid in brief.concept_ids],
        }
        for draft in close.checkpoint_questions
    ]
    checkpoints = [c for c in checkpoints if c["question"] and c["expected_answer"]]
    if not checkpoints:
        notes.append("no usable checkpoint question; derived from the period's objectives")
        checkpoints = _fallback_checkpoints(brief)

    tasks = [task.strip() for task in close.homework.tasks if task and task.strip()]
    if not tasks:
        notes.append("homework was empty; derived from the period's objectives")
        tasks = [f"Write a short paragraph in which you {_objective_phrase(brief)}."]

    mentor = close.mentor_moment
    mentor_story = (mentor.story or "").strip()
    if not mentor_story:
        notes.append("mentor moment was empty; a placeholder was derived from the topic")
        mentor_story = (
            f"{names[0]} was not obvious to the people who first worked it out — it took "
            "them repeated attempts, and several wrong turns, before it looked simple."
        )

    # Board formulae come from the source, never from the model. Extraction found
    # what this document states; anything else on the board is invention.
    source_formulae = [str(f.get("latex")) for f in brief.formulae if f.get("latex")]
    proposed = [f.strip() for f in core.blackboard_notes.formulae_latex if f and f.strip()]
    if proposed and not source_formulae:
        notes.append(
            f"dropped {len(proposed)} board formula(e) the source does not state — "
            "this material carries none"
        )

    headings = [h.strip() for h in core.blackboard_notes.headings if h and h.strip()]
    bullets = [b.strip() for b in core.blackboard_notes.bullet_points if b and b.strip()]
    if not headings and not bullets:
        notes.append("blackboard notes were empty; derived from the period's concepts")
        headings = [brief.title]
        bullets = [f"{c.get('name')}: {c.get('summary')}" for c in brief.concepts] or [brief.title]

    content = PeriodContent.model_validate(
        {
            "period_no": brief.period_no,
            "entry_ticket": {
                "prompt": entry_prompt,
                "expected_response": entry_expected,
                "duration_minutes": _clamp_ticket(
                    entry.duration_minutes, brief.duration_minutes, 5
                ),
            },
            "teacher_script": segments,
            "blackboard_notes": {
                "headings": headings or [brief.title],
                "bullet_points": bullets,
                "diagrams_to_draw": [
                    d.strip() for d in core.blackboard_notes.diagrams_to_draw if d and d.strip()
                ],
                "formulae_latex": source_formulae,
            },
            "activity_refs": [activity_id(brief.period_no)],
            "checkpoint_questions": checkpoints,
            "exit_ticket": {
                "prompt": exit_prompt,
                "success_indicator": exit_indicator,
                "duration_minutes": _clamp_ticket(
                    exit_ticket.duration_minutes, brief.duration_minutes, 5
                ),
            },
            "homework": {
                "tasks": tasks,
                "estimated_minutes": max(1, min(close.homework.estimated_minutes or 20, 180)),
                "submission_format": (close.homework.submission_format or "").strip() or None,
            },
            "mentor_moment": {
                "title": (mentor.title or "").strip() or f"Where {names[0]} came from",
                "story": mentor_story,
                "takeaway": (mentor.takeaway or "").strip()
                or "Understanding takes more than one attempt, and that is normal.",
            },
        }
    )
    return content, notes
