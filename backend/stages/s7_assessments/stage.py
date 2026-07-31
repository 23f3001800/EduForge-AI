"""Stage 7 — Assessment Generation.

Produces the assessment bank: items, answer key, and rubrics (FR-08). The
blueprint in ``blueprint.py`` has already decided how many items exist, of what
kind, at what Bloom level, worth how many marks, covering which objective. This
module writes them and rebuilds each one against ``contracts.assessment``.

Two policies are worth stating, because they are the ones that differ from the
other generation stages:

**A bad item is dropped, never repaired.** Everywhere else in this pipeline a
thin field gets a derived fallback. Not here. An assessment item's answer is the
answer key a teacher marks thirty scripts against, and a plausible-looking
invented answer is worse than no item — it is wrong in a way that costs students
marks and the teacher trust. So an item whose stem or answer came back empty is
discarded with a warning, and ``total_marks`` is recomputed from what survived
rather than asserted from the blueprint.

**An unusable MCQ degrades to a short answer rather than being discarded.** If
fewer than four distinct options came back, the question itself is usually fine —
it is the distractors that failed. Rewriting it as a constructed-response item
keeps the coverage the blueprint designed, and is honest about what it now is.

The bank still fails loudly if nothing survives: a package whose assessments key
holds an empty bank would pass schema validation and be useless in a classroom.
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from typing import Any

from contracts.assessment import AssessmentBank, AssessmentBlueprint, AssessmentItem
from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block
from pedagogy.registry import get_strategy
from stages.base import StageContext, stage_span
from stages.s7_assessments.blueprint import Blueprint, ItemSpec, build_blueprint, rubric_ladder
from stages.s7_assessments.schemas import ConstructedResponseDraft, MCQDraft

__all__ = ["AssessmentGenerationStage"]

#: Option labels, assigned positionally. The model never sees or chooses these —
#: it returns option *texts* and one index, so "which letter is correct" cannot
#: drift away from "which text is correct".
OPTION_LABELS = string.ascii_uppercase

MCQ_SYSTEM = """You write ONE multiple-choice question. Its topic, its Bloom \
level, and its mark value are already fixed; you write the question itself.

`stem` — a complete question, answerable from the material given. Not a \
fill-in-the-blank fragment, and never "Which of the following is true?" — that \
tests reading the options, not the concept.

`options` — exactly 4 answer texts, plain, with NO "A."/"B." labels and no \
"all of the above" or "none of the above". They must be roughly the same length: \
a conspicuously longer option is a giveaway independent of the content.

`correct_index` — the 0-based position in `options` of the one correct answer. \
Vary it across questions; do not always pick 0.

`rationales` — one per option, in the SAME order. For each wrong option, name \
the specific error or misconception a student who picks it is making. A \
distractor that traces to a real misconception both teaches and diagnoses; a \
random wrong answer does neither. For the correct option, say why it is right.

`answer` — restate the correct answer and give the reasoning a marker needs."""

CR_SYSTEM = """You write ONE written-response question and the rubric for \
marking it. Its topic, its Bloom level, and its mark value are already fixed.

`stem` — a complete question, answerable from the material given, and pitched at \
the mark value: a 6-mark question that a sentence answers is mis-marked.

`answer` — the model answer, at the length and depth worth full marks. This is \
the answer key; a marker will mark real scripts against it, so it must be \
correct and complete rather than indicative.

`working` — for a numerical question, the full worked solution: each step, with \
units carried through. Leave empty for non-numerical questions.

`rubric_criteria` — one line naming what the item is judged on.

`rubric_levels` — 2 or 3 levels, highest first, each awarding a DIFFERENT number \
of marks, with the top level worth the item's full marks. Each descriptor must \
say what that level's work actually contains, in terms of THIS question. \
"Good answer" and "shows understanding" are not descriptors — a second marker \
could not apply them to the same script and reach the same mark."""


def audience_brief(classification: Mapping[str, Any]) -> str:
    grade = classification.get("grade_band") or "unspecified"
    difficulty = classification.get("difficulty") or "intermediate"
    return (
        f"AUDIENCE: grade band {grade}, {difficulty} level. "
        "Vocabulary, reading load, and expected answer length must suit that grade."
    )


def language_directive(language: str | None) -> str:
    """Translate values, never keys (BR-06)."""
    if not language or language.lower().startswith("en"):
        return ""
    return (
        f"\n\nOUTPUT LANGUAGE: write every natural-language value in {language}. "
        "JSON keys stay in English exactly as the schema names them."
    )


def spec_brief(
    spec: ItemSpec,
    concepts_by_id: Mapping[str, Mapping[str, Any]],
    misconceptions: list[Mapping[str, Any]],
) -> str:
    """The narrowed context for one item: what it must assess, and nothing else."""
    lines = [
        f"ITEM TYPE: {spec.kind.replace('_', ' ')}",
        f"MARKS: {spec.marks}",
        f"BLOOM LEVEL: {spec.bloom_level} — the question must actually demand this.",
    ]
    if spec.objective_statement:
        lines += ["", f"OBJECTIVE THIS ITEM MEASURES: {spec.objective_statement}"]
    lines += ["", "CONCEPTS IT MUST ASSESS:"]
    for cid in spec.concept_ids:
        concept = concepts_by_id.get(cid, {})
        lines.append(f"  - {concept.get('name', cid)}: {concept.get('summary', '')}")
    if misconceptions:
        lines += [
            "",
            "KNOWN STUDENT MISCONCEPTIONS ON THIS MATERIAL — build distractors from "
            "these where they fit:",
            *(
                f"  - {m.get('statement')} (because: {m.get('why_it_happens')})"
                for m in misconceptions[:3]
            ),
        ]
    return "\n".join(lines)


def build_mcq(
    spec: ItemSpec, draft: MCQDraft, misconception_id: str | None
) -> tuple[AssessmentItem | None, list[str]]:
    """Rebuild a validated MCQ, or return ``None`` when it should degrade.

    Returning ``None`` rather than raising lets the caller re-issue the item as a
    constructed response, which keeps the blueprint's coverage intact.
    """
    notes: list[str] = []
    stem = draft.stem.strip()
    answer = draft.answer.strip()
    if not stem or not answer:
        return None, ["stem or answer came back empty"]

    # Dedupe preserving order: two identical options make a 3-option question
    # wearing a 4-option shape, and the duplicate is never the intended answer.
    seen: dict[str, int] = {}
    options: list[str] = []
    kept_indices: list[int] = []
    for index, text in enumerate(draft.options):
        cleaned = text.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen[key] = index
        options.append(cleaned)
        kept_indices.append(index)

    if len(options) != 4:
        return None, [f"expected 4 distinct options, got {len(options)}"]

    # correct_index refers to the pre-dedupe list; map it through, and fall back
    # to 0 rather than silently marking the wrong option correct.
    if draft.correct_index in kept_indices:
        correct = kept_indices.index(draft.correct_index)
    else:
        correct = 0
        notes.append(
            f"correct_index {draft.correct_index} was out of range; first option marked correct"
        )

    rationales = list(draft.rationales)
    built = []
    for position, text in enumerate(options):
        source_index = kept_indices[position]
        rationale = (
            rationales[source_index].strip()
            if source_index < len(rationales) and rationales[source_index]
            else None
        )
        built.append(
            {
                "label": OPTION_LABELS[position],
                "text": text,
                "is_correct": position == correct,
                "rationale": rationale,
            }
        )

    item = AssessmentItem.model_validate(
        {
            "item_id": spec.item_id,
            "kind": "mcq",
            "stem": stem,
            "options": built,
            "answer": answer,
            "marks": spec.marks,
            "bloom_level": spec.bloom_level,
            "concept_ids": spec.concept_ids,
            "linked_misconception_id": misconception_id,
        }
    )
    return item, notes


def build_constructed(
    spec: ItemSpec, draft: ConstructedResponseDraft, kind: str, marks: int
) -> tuple[AssessmentItem | None, list[str]]:
    """Rebuild a validated non-MCQ item, repairing only the rubric."""
    notes: list[str] = []
    stem = draft.stem.strip()
    answer = draft.answer.strip()
    if not stem or not answer:
        return None, ["stem or answer came back empty"]

    levels = [
        {"label": lvl.label.strip(), "descriptor": lvl.descriptor.strip(), "marks": lvl.marks}
        for lvl in draft.rubric_levels
        if lvl.label.strip() and lvl.descriptor.strip() and lvl.marks >= 0
    ]
    # `Rubric` rejects a ladder whose levels all award the same marks, and it is
    # right to: such a rubric restates the question instead of discriminating.
    if len(levels) < 2 or len({lvl["marks"] for lvl in levels}) == 1:
        if draft.rubric_levels:
            notes.append("rubric levels did not discriminate; a derived mark ladder was used")
        else:
            notes.append("no rubric was returned; a derived mark ladder was used")
        levels = rubric_ladder(marks, answer)
    elif max(int(lvl["marks"]) for lvl in levels) > marks:
        notes.append(f"rubric awarded more than the item's {marks} marks; ladder rederived")
        levels = rubric_ladder(marks, answer)

    working = draft.working.strip() or None
    if kind == "numerical" and working is None:
        notes.append("numerical item returned no worked solution")

    item = AssessmentItem.model_validate(
        {
            "item_id": spec.item_id,
            "kind": kind,
            "stem": stem,
            "answer": answer,
            "working": working,
            "marks": marks,
            "bloom_level": spec.bloom_level,
            "concept_ids": spec.concept_ids,
            "rubric": {
                "criteria": draft.rubric_criteria.strip()
                or f"Accuracy and completeness of the response to: {stem[:80]}",
                "levels": levels,
            },
        }
    )
    return item, notes


def summarise(items: list[AssessmentItem]) -> AssessmentBlueprint:
    """The realised blueprint — what the bank actually contains, not what was planned."""
    by_kind: dict[str, int] = {}
    by_bloom: dict[str, int] = {}
    marks_by_concept: dict[str, int] = {}
    for item in items:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
        by_bloom[item.bloom_level] = by_bloom.get(item.bloom_level, 0) + 1
        for cid in item.concept_ids:
            marks_by_concept[cid] = marks_by_concept.get(cid, 0) + item.marks
    return AssessmentBlueprint(
        items_by_kind=by_kind, items_by_bloom=by_bloom, marks_by_concept=marks_by_concept
    )


class AssessmentGenerationStage:
    """Replaces the stage-7 stub."""

    name = "assessment-generation"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            knowledge: dict[str, Any] = state.get("knowledge") or {}
            classification: dict[str, Any] = state.get("classification") or {}
            options = ctx.options or {}
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))

            blueprint: Blueprint = build_blueprint(knowledge, strategy)
            if not blueprint.specs:
                raise ValueError(
                    "cannot generate assessments: the knowledge base has no concepts "
                    "or objectives to assess"
                )

            concepts_by_id = {str(c["concept_id"]): c for c in (knowledge.get("concepts") or [])}
            all_misconceptions = list(knowledge.get("misconceptions") or [])

            common = (
                f"\n\n{strategy.prompt_guidance()}\n\n{audience_brief(classification)}\n\n"
                f"{OUTPUT_DISCIPLINE}{language_directive(options.get('output_language'))}"
            )
            mcq_system = MCQ_SYSTEM + common
            cr_system = CR_SYSTEM + common

            items: list[AssessmentItem] = []
            for index, spec in enumerate(blueprint.specs):
                await span.progress(
                    index / len(blueprint.specs),
                    message=f"item {index + 1} of {len(blueprint.specs)} ({spec.kind})",
                )
                relevant = [
                    m
                    for m in all_misconceptions
                    if set(spec.concept_ids) & {str(c) for c in (m.get("concept_ids") or [])}
                ]
                brief = spec_brief(spec, concepts_by_id, relevant)
                misconception_id = str(relevant[0].get("misconception_id")) if relevant else None

                item: AssessmentItem | None = None
                notes: list[str] = []

                if spec.kind == "mcq":
                    result = await self._llm.parse(
                        stage=self.name,
                        output_model=MCQDraft,
                        system=mcq_system,
                        user_content=(
                            f"{document_block(brief)}\n\n"
                            "Write the multiple-choice question described above. Return only "
                            "`stem`, `options`, `correct_index`, `rationales`, and `answer`."
                        ),
                    )
                    if result.degraded:
                        span.warn(f"{spec.item_id}: generation degraded")
                    item, notes = build_mcq(spec, result.value, misconception_id)
                    if item is None:
                        # The question is usually sound; the distractors failed.
                        # Re-ask as a short answer to keep the designed coverage.
                        span.warn(
                            f"{spec.item_id}: unusable as an MCQ "
                            f"({'; '.join(notes)}); reissued as a short answer"
                        )
                        spec = ItemSpec(
                            item_id=spec.item_id,
                            kind="short_answer",
                            marks=spec.marks,
                            bloom_level=spec.bloom_level,
                            concept_ids=spec.concept_ids,
                            objective_id=spec.objective_id,
                            objective_statement=spec.objective_statement,
                        )

                if item is None:
                    kind = spec.kind if spec.kind != "mcq" else "short_answer"
                    result_cr = await self._llm.parse(
                        stage=self.name,
                        output_model=ConstructedResponseDraft,
                        system=cr_system,
                        user_content=(
                            f"{document_block(spec_brief(spec, concepts_by_id, relevant))}\n\n"
                            f"Write the {kind.replace('_', ' ')} question described above, "
                            "worth exactly "
                            f"{spec.marks} marks. Return only `stem`, `answer`, `working`, "
                            "`rubric_criteria`, and `rubric_levels`."
                        ),
                    )
                    if result_cr.degraded:
                        span.warn(f"{spec.item_id}: generation degraded")
                    item, notes = build_constructed(spec, result_cr.value, kind, spec.marks)

                if item is None:
                    # Never fabricated. A wrong answer key is worse than a shorter bank.
                    span.warn(f"{spec.item_id}: dropped — {'; '.join(notes)}")
                    continue
                for note in notes:
                    span.warn(f"{spec.item_id}: {note}")
                items.append(item)

            if not items:
                raise ValueError(
                    f"assessment generation produced no usable items from "
                    f"{len(blueprint.specs)} planned"
                )

            bank = AssessmentBank(
                items=items,
                blueprint=summarise(items),
                total_marks=sum(item.marks for item in items),
            )
            await span.progress(0.98, message=f"{len(items)} items, {bank.total_marks} marks")
            return {"assessments": bank.model_dump(mode="json")}
