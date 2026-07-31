"""Stage 2 — Educational Classification.

Decides what kind of teaching material this document is (FR-03). Its most
consequential output is not ``subject`` but ``pedagogy_profile``, which routes
prompt strategy, activity weighting, assessment mix, and the validation ruleset
for every stage after this one.

Two behaviours worth stating:

* **Confidence is reported, not hidden.** Fields below 0.5 are listed so the UI
  can surface them, rather than a shaky guess propagating silently through six
  downstream stages.
* **Curriculum alignment returns nothing rather than something plausible.** A
  fabricated standard code looks authoritative and is worse than an honest
  absence, so the prompt says so explicitly and the contract permits ``None``.

Only a sample of the document is sent: the outline plus head and tail chunks.
Classification is a judgement about shape, and shape is visible early — sending
the whole document would cost tokens for no accuracy.
"""

from __future__ import annotations

import json
from typing import Any

from contracts.classification import Classification
from core.llm.client import LLMClient
from core.llm.prompts import document_block
from stages.base import StageContext, stage_span

__all__ = ["ClassificationStage", "build_sample"]

MAX_SAMPLE_CHARS = 6000

SYSTEM = """You classify educational documents for a teaching-material pipeline.

Return JSON only, matching the provided schema exactly.

The most important field is `pedagogy_profile`. It determines how every later \
stage treats this material, so choose it from the content's actual shape rather \
than from its subject label:

- `quantitative`  formulae, derivations, calculation, measurement
- `conceptual`    systems and mechanisms; understanding over calculation
- `narrative`     interpretation of texts, events, motives, argument
- `procedural`    ordered technique or process learned by doing
- `mixed`         genuinely spans modes, or the shape is unclear

A history chapter is `narrative` even when it contains dates and numbers. A \
biology chapter is `conceptual` even though biology is a science. Judge the \
reasoning the material demands, not the department it belongs to.

Commit to a specific profile. `mixed` is not a safe middle option — it is the \
weakest setting and produces the blandest teaching material, because it tells \
every later stage to assume nothing. Choose it ONLY when no single mode accounts \
for most of the content. If the material contains formulae, derivations, units, \
or worked calculations as a central activity, it is `quantitative`, even if it \
also explains concepts in prose — nearly all quantitative material does both.

`subject` is the academic discipline — "Physics", "History", "Biology". It is \
NOT the filename, the chapter title, or the topic. Judge it from the content; a \
filename is a naming accident and is frequently misleading.

For `confidences`, give an honest per-field score in [0,1]. Do not inflate them; \
a low score is useful information and is surfaced to the teacher. Leave \
`low_confidence_fields` empty — it is derived automatically from `confidences`.

For `curriculum_alignment`: include it ONLY if you can name real, verifiable \
standard codes from the stated board. If you cannot, omit the field entirely. \
Never invent a code — a fabricated standard is worse than no alignment at all."""


def build_sample(structured_document: dict[str, Any], limit: int = MAX_SAMPLE_CHARS) -> str:
    """Outline plus head and tail of the body.

    The opening establishes subject and level; the closing often carries
    exercises and summaries that reveal the pedagogical mode. The middle is
    largely redundant for this judgement.
    """
    blocks = structured_document.get("blocks", [])
    metadata = structured_document.get("metadata", {})

    headings = [b["text"] for b in blocks if b.get("type") == "heading"]
    body = [b["text"] for b in blocks if b.get("type") not in {"heading", "table"}]
    stats = structured_document.get("stats", {})

    parts: list[str] = [
        # Filename deliberately omitted. It is weak evidence and models latch onto
        # it — a live run classified `subject` as "history.docx". The outline and
        # content below carry every signal that actually matters.
        f"PAGES: {metadata.get('page_count')}  WORDS: {metadata.get('word_count')}",
        f"STRUCTURE: {json.dumps(stats)}",
        "",
        "OUTLINE:",
        *(f"  {h}" for h in headings[:40]),
        "",
        "CONTENT SAMPLE:",
    ]

    budget = limit - len("\n".join(parts))
    joined = "\n".join(body)
    if len(joined) <= budget:
        parts.append(joined)
    else:
        half = budget // 2
        parts.append(joined[:half])
        parts.append("\n[... middle omitted ...]\n")
        parts.append(joined[-half:])

    return "\n".join(parts)


class ClassificationStage:
    """Replaces the stage-2 stub."""

    name = "educational-classification"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            sample = build_sample(state["structured_document"])
            board = (ctx.options or {}).get("curriculum_board")

            instructions = "Classify this document."
            if board:
                instructions += (
                    f" If, and only if, it genuinely maps to real {board} standards, "
                    f"include curriculum_alignment with verifiable codes."
                )

            await span.progress(0.3, message="classifying")
            result = await self._llm.parse(
                stage=self.name,
                output_model=Classification,
                system=SYSTEM,
                user_content=f"{document_block(sample)}\n\n{instructions}",
            )

            classification = result.value
            if result.degraded:
                span.warn("classification degraded; downstream strategy defaults to 'mixed'")
            if classification.low_confidence_fields:
                span.warn("low confidence: " + ", ".join(classification.low_confidence_fields))

            await span.progress(
                0.9,
                message=f"{classification.subject} · {classification.pedagogy_profile}",
            )
            return {"classification": classification.model_dump(mode="json")}
