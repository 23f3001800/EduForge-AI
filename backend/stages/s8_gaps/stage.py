"""Stage 8 — Learning Gap Analysis.

Produces the gaps a teacher should expect and plan for (FR-09): what students
will get wrong, a question that reveals it, and steps that fix the cause rather
than the symptom.

``severity.py`` decides which gaps exist and how urgent each is, from the concept
dependency graph. This module writes them. The split matters here more than
elsewhere: severity asked of a model comes back ``medium`` almost uniformly,
while "three later concepts are built on this one" is a fact already sitting in
the graph stage 3 produced.

Observed gaps — those stage 3 extracted from the document — carry their source
evidence forward and use the document's own correction as the first remediation
step, so a teacher can see that the fix came from the chapter rather than from a
model. Predicted gaps carry no evidence, which ``LearningGap`` permits precisely
because a genuine misconception is usually anticipated rather than stated.

A gap that comes back with no diagnostic and no remediation is dropped, not
padded. The whole value of this stage is the detect-and-fix pair; a gap without
one is a worry, and a teacher already has those.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from contracts.gaps import LearningGap
from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block
from pedagogy.registry import get_strategy
from stages.base import StageContext, stage_span
from stages.s8_gaps.schemas import GapDraft
from stages.s8_gaps.severity import GapSeed, plan_seeds

__all__ = ["GapAnalysisStage"]

SYSTEM = """You analyse ONE way students predictably go wrong on a specific \
concept, for the teacher who is about to teach it.

`misconception` — state the incorrect belief in the words a student would \
actually use, as a claim they think is true. Not "students struggle with X" — \
that names a topic, not an error. "Heavier objects fall faster" is a \
misconception; "difficulty with gravity" is not.

`why_it_happens` — the reasoning behind it. Usually the student is generalising \
from something that IS true in a narrower case, or from everyday experience. \
Name that source. A teacher who knows where the error comes from can address it; \
one who only knows it exists can only repeat themselves louder.

`diagnostic_questions` — 1 or 2 questions where a student holding this \
misconception gives a WRONG answer while a student who understands gives a right \
one. That is the whole test of a diagnostic: a question both answer correctly \
reveals nothing. For each, `reveals` says what a wrong answer tells the teacher, \
and `expected_wrong_answer` is what the student holding the misconception says.

`remediation` — 2 or 3 steps that address the CAUSE you just named. Each needs \
an `action` a teacher can carry out in a lesson — a specific demonstration, \
comparison, or question sequence — and a `rationale` saying why it corrects the \
reasoning rather than just restating the right answer. Telling students the \
correct fact is not remediation; they were told once already."""


def audience_brief(classification: Mapping[str, Any]) -> str:
    grade = classification.get("grade_band") or "unspecified"
    return (
        f"AUDIENCE: grade band {grade}. The misconception must be one students at "
        "this level actually hold, and the remediation must fit a normal lesson."
    )


def language_directive(language: str | None) -> str:
    """Translate values, never keys (BR-06)."""
    if not language or language.lower().startswith("en"):
        return ""
    return (
        f"\n\nOUTPUT LANGUAGE: write every natural-language value in {language}. "
        "JSON keys stay in English exactly as the schema names them."
    )


def seed_brief(seed: GapSeed, concepts_by_id: Mapping[str, Mapping[str, Any]]) -> str:
    """The narrowed context for one gap."""
    lines = ["CONCEPTS THIS GAP CONCERNS:"]
    for cid in seed.concept_ids:
        concept = concepts_by_id.get(cid, {})
        lines.append(f"  - {concept.get('name', cid)}: {concept.get('summary', '')}")

    if seed.observed:
        lines += [
            "",
            "THE DOCUMENT ITSELF FLAGS THIS ERROR:",
            f"  belief: {seed.misconception}",
        ]
        if seed.why_it_happens:
            lines.append(f"  cause: {seed.why_it_happens}")
        if seed.correction:
            lines.append(f"  the document's correction: {seed.correction}")
        lines += [
            "",
            "Keep this misconception — do not substitute a different one. Write the "
            "diagnostic and the remediation for it.",
        ]
    else:
        lines += [
            "",
            f"SEVERITY: {seed.severity} — later concepts in this chapter build on this "
            "one, so an error here propagates.",
            "",
            "The document does not name a misconception for this concept. Identify the "
            "one students most predictably hold, from how this topic is normally "
            "misunderstood at this level.",
        ]
    return "\n".join(lines)


def build_gap(seed: GapSeed, draft: GapDraft) -> tuple[LearningGap | None, list[str]]:
    """Rebuild a validated ``LearningGap``, or ``None`` if it is not usable."""
    notes: list[str] = []

    misconception = draft.misconception.strip() or seed.misconception
    if not misconception:
        return None, ["no misconception statement"]

    diagnostics = [
        {
            "question": d.question.strip(),
            "reveals": d.reveals.strip()
            or f"A wrong answer indicates the student still believes: {misconception}",
            "expected_wrong_answer": d.expected_wrong_answer.strip() or None,
        }
        for d in draft.diagnostic_questions
        if d.question.strip()
    ]
    if not diagnostics:
        return None, ["no diagnostic question, which is the point of a gap entry"]

    steps = [
        {
            "action": r.action.strip(),
            "rationale": r.rationale.strip() or f"Addresses the reasoning behind: {misconception}",
            "estimated_minutes": r.estimated_minutes if r.estimated_minutes >= 1 else None,
        }
        for r in draft.remediation
        if r.action.strip()
    ]
    if not steps:
        # The document's own correction is a real remediation step and is better
        # sourced than anything a fallback could invent — but only observed gaps
        # have one.
        if seed.correction:
            notes.append("no remediation returned; the document's own correction was used")
            steps = [
                {
                    "action": seed.correction,
                    "rationale": "Stated in the source material as the correction for "
                    "this specific error.",
                    "estimated_minutes": None,
                }
            ]
        else:
            return None, ["no remediation steps"]

    gap = LearningGap.model_validate(
        {
            "gap_id": seed.gap_id,
            "misconception": misconception,
            "concept_ids": seed.concept_ids,
            "severity": seed.severity,
            "diagnostic_questions": diagnostics,
            "remediation": steps,
            "evidence": seed.evidence,
        }
    )
    return gap, notes


class GapAnalysisStage:
    """Replaces the stage-8 stub."""

    name = "gap-analysis"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            knowledge: dict[str, Any] = state.get("knowledge") or {}
            classification: dict[str, Any] = state.get("classification") or {}
            options = ctx.options or {}
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))

            seeds = plan_seeds(knowledge)
            if not seeds:
                # Legitimately empty: a short document with no misconceptions and no
                # dependency structure has no gaps to report. `learning_gaps` is not
                # min_length-constrained, so an empty list is a valid package.
                span.warn("no misconceptions and no load-bearing concepts; no gaps to analyse")
                return {"learning_gaps": []}

            concepts_by_id = {str(c["concept_id"]): c for c in (knowledge.get("concepts") or [])}

            system = (
                f"{SYSTEM}\n\n{strategy.prompt_guidance()}\n\n"
                f"{audience_brief(classification)}\n\n{OUTPUT_DISCIPLINE}"
                f"{language_directive(options.get('output_language'))}"
            )

            gaps: list[dict[str, Any]] = []
            for index, seed in enumerate(seeds):
                await span.progress(
                    index / len(seeds),
                    message=f"gap {index + 1} of {len(seeds)} ({seed.severity})",
                )
                result = await self._llm.parse(
                    stage=self.name,
                    output_model=GapDraft,
                    system=system,
                    user_content=(
                        f"{document_block(seed_brief(seed, concepts_by_id))}\n\n"
                        "Analyse this learning gap. Return only `misconception`, "
                        "`why_it_happens`, `diagnostic_questions`, and `remediation`."
                    ),
                )
                if result.degraded:
                    span.warn(f"{seed.gap_id}: gap analysis degraded")

                gap, notes = build_gap(seed, result.value)
                if gap is None:
                    span.warn(f"{seed.gap_id}: dropped — {'; '.join(notes)}")
                    continue
                for note in notes:
                    span.warn(f"{seed.gap_id}: {note}")
                gaps.append(gap.model_dump(mode="json"))

            high = sum(1 for g in gaps if g["severity"] == "high")
            await span.progress(0.98, message=f"{len(gaps)} gaps, {high} high severity")
            return {"learning_gaps": gaps}
