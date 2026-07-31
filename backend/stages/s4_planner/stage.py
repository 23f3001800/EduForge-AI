"""Stage 4 — Teaching Planner.

Turns a knowledge base into a multi-period teaching plan (FR-05). The stage is
deliberately half algorithm and half model, and the seam between them is the
point of the design:

**Python decides the structure.** How many periods the material needs, what order
the concepts must be taught in, which concepts sit in which period, and which
objectives each period can honestly claim to complete — all of it is computed in
``banding.py`` before any model is called. Prerequisite correctness is therefore a
property of a topological sort plus a contiguous partition, not something a prompt
asked for politely. Stage 9 can verify it; a regression fails a unit test rather
than a teacher's Thursday.

**The model decides the language.** A title a teacher would write in a register, a
rationale that explains what this period builds on and what it enables, and a
split of the period's minutes across a defensible arc. None of that is derivable
from a graph, and all of it is what makes the plan readable.

One model call per period, not one for the plan. Each call sees only its own
period's concepts and objectives plus one line about its neighbours, so the prompt
stays small and no period can quietly borrow another period's material.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts.plan import TeachingPlan
from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block
from pedagogy.registry import ProfileStrategy, get_strategy
from stages.base import StageContext, stage_span
from stages.s4_planner.banding import (
    Band,
    PlanSkeleton,
    build_skeleton,
    default_time_allocation,
    normalise_time_allocation,
)
from stages.s4_planner.schemas import BandDraft

__all__ = ["TeachingPlannerStage"]

SYSTEM = """You write the human half of one period in a multi-period teaching plan.

The sequence is already decided. A topological sort of the concept dependency \
graph fixed which concepts this period teaches and where the period sits. You are \
not being asked to review that: do not propose a different order, do not add or \
drop concepts, and do not describe material that belongs to another period.

Produce exactly three things.

`title` — what a teacher would write in a register for THIS period. Name the \
actual content, in 3 to 8 words. "Lesson 3" and the chapter's own title are both \
failures; a teacher scanning a week of titles must be able to tell the periods \
apart.

`sequence_rationale` — one or two sentences saying what this period builds on and \
what it makes possible. Refer to the named prior and following material given to \
you. "This period builds on prior knowledge" says nothing and is worse than \
silence; name the actual idea.

`time_allocation` — how the period's minutes divide across a teachable arc: \
activate prior knowledge, introduce the new material, practise it, check whether \
it landed, consolidate. Use 4 to 6 slots. Each label must say what actually \
happens in that slot, so "Guided practice: pairs work through two worked \
examples" rather than "Activity". Proportions matter, exact minutes do not — the \
arithmetic is rebalanced to the period length afterwards."""


# ------------------------------------------------------------------ prompting


def audience_brief(classification: Mapping[str, Any]) -> str:
    """The grade band and difficulty, stated as a constraint rather than context.

    Cognitive demand and vocabulary are graded criteria, and a model given no
    audience writes for an undergraduate every time.
    """
    grade = classification.get("grade_band") or "unspecified"
    difficulty = classification.get("difficulty") or "intermediate"
    subject = classification.get("subject") or "this material"
    topic = classification.get("topic") or ""
    line = f"AUDIENCE: grade band {grade}, {difficulty} level, {subject}"
    if topic:
        line += f" — {topic}"
    return (
        f"{line}\n"
        f"Vocabulary, cognitive demand, and task complexity must suit grade {grade}. "
        "Content a grade band above or below the stated one is unusable even when "
        "it is correct."
    )


def language_directive(language: str | None) -> str:
    """Translate values, never keys (BR-06)."""
    if not language or language.lower().startswith("en"):
        return ""
    return (
        f"\n\nOUTPUT LANGUAGE: write every natural-language value in {language}. "
        "JSON keys stay in English exactly as the schema names them."
    )


def band_brief(
    band: Band,
    skeleton: PlanSkeleton,
    concepts_by_id: Mapping[str, Mapping[str, Any]],
    objectives_by_id: Mapping[str, Mapping[str, Any]],
    previous_title: str | None,
) -> str:
    """The narrowed context for one period.

    Only this period's concepts and objectives, plus a single line naming what
    came before and what comes next. The whole knowledge base would make the
    prompt large and the rationale vague, and it is what lets a period drift into
    teaching its neighbour's material.
    """
    lines = [
        f"PERIOD {band.period_no} OF {skeleton.total_periods} "
        f"({skeleton.period_duration_minutes} minutes)",
        "",
        "CONCEPTS TAUGHT IN THIS PERIOD (all of them, and only these):",
    ]
    for cid in band.concept_ids:
        concept = concepts_by_id.get(cid, {})
        lines.append(
            f"  - {concept.get('name', cid)} [{concept.get('importance', 'supporting')}]: "
            f"{concept.get('summary', '')}"
        )

    lines += ["", "OBJECTIVES THIS PERIOD COMPLETES:"]
    for oid in band.objective_ids:
        objective = objectives_by_id.get(oid, {})
        lines.append(
            f"  - {objective.get('statement', oid)} "
            f"(Bloom: {objective.get('bloom_level', 'understand')})"
        )

    index = band.period_no - 1
    if index > 0:
        prior = skeleton.bands[index - 1]
        named = ", ".join(prior.concept_names(concepts_by_id)) or "earlier material"
        lines += ["", f"TAUGHT IMMEDIATELY BEFORE: {named}"]
        if previous_title:
            lines.append(f"  (that period is titled: {previous_title})")
    else:
        lines += ["", "TAUGHT IMMEDIATELY BEFORE: nothing — this is the opening period."]

    if index + 1 < skeleton.total_periods:
        following = skeleton.bands[index + 1]
        named = ", ".join(following.concept_names(concepts_by_id)) or "later material"
        lines.append(f"TAUGHT IMMEDIATELY AFTER: {named}")
    else:
        lines.append("TAUGHT IMMEDIATELY AFTER: nothing — this is the closing period.")

    return "\n".join(lines)


# ------------------------------------------------------------ deterministic UX


def fallback_title(names: Sequence[str], period_no: int) -> str:
    """A usable title when the model call produced nothing.

    Built from the concepts actually in the band, so it still tells a teacher what
    the period covers. ``Period 3`` is the last resort and only when the band's
    concepts have no names at all.
    """
    usable = [name.strip() for name in names if name and name.strip()]
    if not usable:
        return f"Period {period_no}"
    if len(usable) == 1:
        return usable[0]
    if len(usable) == 2:
        return f"{usable[0]} and {usable[1]}"
    return f"{usable[0]}, {usable[1]} and {usable[2]}"


def fallback_rationale(
    band: Band,
    skeleton: PlanSkeleton,
    concepts_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    """A rationale derived from the ordering that actually produced this band."""
    index = band.period_no - 1
    here = ", ".join(band.concept_names(concepts_by_id)) or "this period's concepts"
    parts: list[str] = []
    if index > 0:
        before = ", ".join(skeleton.bands[index - 1].concept_names(concepts_by_id))
        parts.append(f"{here} follows {before}, which it depends on")
    else:
        parts.append(f"{here} opens the sequence because nothing else is a prerequisite for it")
    if index + 1 < skeleton.total_periods:
        after = ", ".join(skeleton.bands[index + 1].concept_names(concepts_by_id))
        parts.append(f"and is needed before {after}")
    return "; ".join(parts) + "."


def _ensure_objectives(skeleton: PlanSkeleton, objective_ids: Sequence[str]) -> list[str]:
    """Round-robin objectives across bands when the mapping produced none anywhere.

    ``Period.objective_ids`` has ``min_length=1``: a period serving no objective is
    unrepresentable, and rightly so. This only fires when every objective failed to
    resolve to a concept, which is a stage 3 quality problem rather than a planning
    one — the caller warns, and the objectives stay visible in the plan instead of
    the whole stage failing.
    """
    if any(band.objective_ids for band in skeleton.bands) or not objective_ids:
        return []
    for offset, band in enumerate(skeleton.bands):
        band.objective_ids = [objective_ids[offset % len(objective_ids)]]
    return list(objective_ids)


class TeachingPlannerStage:
    """Replaces the stage-4 stub."""

    name = "teaching-planner"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _decorate(
        self,
        span: Any,
        system: str,
        brief: str,
        strategy: ProfileStrategy,
    ) -> BandDraft:
        result = await self._llm.parse(
            stage=self.name,
            output_model=BandDraft,
            system=system,
            user_content=(
                f"{document_block(brief)}\n\n"
                "Write the title, the sequence rationale, and the time allocation "
                "for the period described above. Return only the three keys "
                "`title`, `sequence_rationale`, and `time_allocation`.\n\n"
                f"Weight the arc towards what this kind of material needs: "
                f"{', '.join(strategy.preferred_activities(3))}."
            ),
        )
        if result.degraded:
            span.warn("period decoration degraded; falling back to derived title and arc")
        return result.value

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            knowledge: dict[str, Any] = state.get("knowledge") or {}
            classification: dict[str, Any] = state.get("classification") or {}
            options = ctx.options or {}
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))

            duration = int(options.get("period_duration_minutes") or 40)
            target = options.get("target_period_count")

            # ── deterministic: count, order, bands, objectives ──────────────
            skeleton = build_skeleton(
                knowledge,
                period_duration_minutes=duration,
                target_period_count=int(target) if target else None,
            )
            for note in skeleton.notes:
                span.warn(note)

            concepts_by_id = {str(c["concept_id"]): c for c in (knowledge.get("concepts") or [])}
            objectives_by_id = {
                str(o["objective_id"]): o for o in (knowledge.get("learning_objectives") or [])
            }
            rescued = _ensure_objectives(skeleton, list(objectives_by_id))
            if rescued:
                span.warn(
                    "no objective resolved to a concept; objectives were distributed "
                    "across periods so the plan remains representable"
                )

            system = (
                f"{SYSTEM}\n\n{strategy.prompt_guidance()}\n\n"
                f"{audience_brief(classification)}\n\n{OUTPUT_DISCIPLINE}"
                f"{language_directive(options.get('output_language'))}"
            )

            # ── model: titles, rationales, minutes ──────────────────────────
            periods: list[dict[str, Any]] = []
            previous_title: str | None = None
            for band in skeleton.bands:
                await span.progress(
                    0.05 + 0.9 * (band.period_no - 1) / skeleton.total_periods,
                    message=f"period {band.period_no} of {skeleton.total_periods}",
                )
                brief = band_brief(band, skeleton, concepts_by_id, objectives_by_id, previous_title)
                draft = await self._decorate(span, system, brief, strategy)

                names = band.concept_names(concepts_by_id)
                title = draft.title.strip() or fallback_title(names, band.period_no)
                rationale = draft.sequence_rationale.strip() or fallback_rationale(
                    band, skeleton, concepts_by_id
                )
                slots = (
                    normalise_time_allocation(
                        [slot.model_dump(mode="json") for slot in draft.time_allocation], duration
                    )
                    if draft.time_allocation
                    else default_time_allocation(duration)
                )

                periods.append(
                    {
                        "period_no": band.period_no,
                        "title": title,
                        "objective_ids": band.objective_ids,
                        "concept_ids": band.concept_ids,
                        "time_allocation": slots,
                        "sequence_rationale": rationale,
                    }
                )
                previous_title = title

            plan = TeachingPlan.model_validate(
                {
                    "total_periods": skeleton.total_periods,
                    "period_duration_minutes": duration,
                    "periods": periods,
                    "unmapped_objective_ids": skeleton.unmapped_objective_ids,
                }
            )
            await span.progress(
                0.97,
                message=(
                    f"{plan.total_periods} periods x {duration} min, "
                    f"{len(concepts_by_id)} concepts sequenced"
                ),
            )
            return {"teaching_plan": plan.model_dump(mode="json")}
