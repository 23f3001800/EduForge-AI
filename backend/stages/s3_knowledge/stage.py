"""Stage 3 — Knowledge Extraction.

Builds the structured educational representation (FR-04): objectives,
prerequisites, concepts, definitions, formulae, keywords, examples, applications,
misconceptions, and the concept dependency graph.

This is the highest-leverage stage in the pipeline. Everything downstream teaches,
sequences, and assesses what comes out of here, so a hallucinated concept is not a
local error — it propagates into the plan, the lesson content, and the assessment
bank before anyone sees it.

Hence the ordering: extract, then **verify citations deterministically**, then
build the graph. Items whose quotes do not appear in the chunk they cite are
dropped here, for free, rather than being caught by an LLM judge nine stages
later. Stage 9 still runs the semantic check; this is the cheap filter in front.
"""

from __future__ import annotations

from typing import Any

from contracts.knowledge import KnowledgeBase
from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block, evidence_rules
from pedagogy.registry import get_strategy
from stages.base import StageContext, stage_span
from stages.s3_knowledge.concept_graph import build_concept_graph
from stages.s3_knowledge.grounding import EvidenceAudit, verify_items
from stages.s3_knowledge.schemas import CoreKnowledge, PedagogicalKnowledge, merge_pair

__all__ = ["KnowledgeExtractionStage"]

#: Above this, extraction runs section-by-section and merges. A single call over a
#: long chapter degrades badly: recall drops and citations get vaguer.
SINGLE_CALL_TOKEN_BUDGET = 12_000

GROUNDED_FIELDS = (
    "concepts",
    "definitions",
    "formulae",
    "examples",
    "applications",
    "misconceptions",
)

SYSTEM = """You build a structured educational representation of a document, for \
a system that turns it into classroom teaching material.

Extract only what the document supports. You are not writing a textbook — you \
are recording what THIS document teaches, so that a teacher can plan lessons \
from it and trace every claim back to its source.

Learning objectives must be observable and assessable. "Understand \
photosynthesis" is not an objective; "Explain how light intensity affects the \
rate of photosynthesis" is. Match the Bloom's level to the verb you actually use.

Do not cluster objectives at `remember`. Recall-level objectives are the easiest \
to write and the least useful to teach from — a set of them produces a lesson \
that only asks students to repeat the text back. Most objectives should sit at \
`understand`, `apply`, or `analyze`, with recall used only where a fact genuinely \
must be memorised before anything else is possible.

Misconceptions are load-bearing: a later stage builds diagnostic questions and \
remediation from them, so an empty list disables that entirely. Even a short \
passage supports one or two — think about what a student would plausibly \
conclude from this text that is subtly wrong, or which everyday intuition it \
contradicts. Only omit them if the material genuinely affords none.

Concept importance: `core` means the document cannot be taught without it, \
`supporting` develops a core concept, `enrichment` is optional extension. Be \
sparing with `core` — it drives how many periods the lesson plan needs.

The concept graph records dependencies. A `prerequisite_of` edge means the first \
concept must be taught before the second. Only add an edge when the dependency is \
real; a graph asserting everything depends on everything is worth nothing.

Misconceptions should be ones students actually hold about this specific topic, \
with the reason they arise. Generic study advice is not a misconception.

Fields that do not apply to this material must be empty. A history chapter has no \
formulae, and returning an empty list is the correct answer — inventing entries \
to fill a field is worse than leaving it empty."""


def _chunk_text(chunks: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{chunk['chunk_id']}]"
        + (f" ({' > '.join(chunk['section_path'])})" if chunk.get("section_path") else "")
        + f"\n{chunk['text']}"
        for chunk in chunks
    )


def _group_by_section(chunks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group chunks under their top-level section for map-reduce extraction."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        path = chunk.get("section_path") or []
        key = path[0] if path else "__root__"
        groups.setdefault(key, []).append(chunk)
    return list(groups.values())


def _merge_cores(parts: list[CoreKnowledge]) -> CoreKnowledge:
    """Union of section-level core extractions, deduped on normalised name.

    Evidence is unioned rather than replaced: the same concept found in two
    sections is better supported, not duplicated.
    """
    fields = ("concepts", "definitions", "formulae")
    by_key: dict[str, dict[str, dict[str, Any]]] = {field: {} for field in fields}
    keywords: list[str] = []

    def key_for(item: dict[str, Any]) -> str:
        for candidate in ("concept_id", "term", "name"):
            if item.get(candidate):
                return str(item[candidate]).strip().casefold()
        return repr(sorted(item.items()))[:120]

    for part in parts:
        payload = part.model_dump(mode="json")
        keywords.extend(payload.get("keywords") or [])
        for field in fields:
            for item in payload.get(field) or []:
                key = key_for(item)
                existing = by_key[field].get(key)
                if existing is None:
                    by_key[field][key] = dict(item)
                elif item.get("evidence"):
                    existing.setdefault("evidence", [])
                    existing["evidence"].extend(item["evidence"])

    return CoreKnowledge.model_validate(
        {
            **{field: list(by_key[field].values()) for field in fields},
            "keywords": sorted(dict.fromkeys(keywords)),
        }
    )


class KnowledgeExtractionStage:
    """Replaces the stage-3 stub."""

    name = "knowledge-extraction"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _extract_core(
        self,
        span: Any,
        system: str,
        chunks: list[dict[str, Any]],
        chunk_ids: list[str],
        progress_from: float,
        progress_to: float,
        *,
        scope: str = "this document",
    ) -> CoreKnowledge:
        """Call 1 — the factual backbone: concepts, definitions, formulae, keywords."""
        await span.progress(progress_from, message="extracting concepts")
        result = await self._llm.parse(
            stage=self.name,
            output_model=CoreKnowledge,
            system=system,
            user_content=(
                f"{document_block(_chunk_text(chunks))}\n\n"
                f"{evidence_rules(chunk_ids)}\n\n"
                f"Extract the factual backbone of {scope}: the concepts it teaches, "
                "the terms it defines, any formulae it states, and its keywords. "
                "Do not produce learning objectives or misconceptions here — those "
                "are requested separately."
            ),
        )
        if result.degraded:
            span.warn("core knowledge extraction degraded")
        await span.progress(progress_to)
        return result.value

    async def _extract_pedagogy(
        self,
        span: Any,
        system: str,
        chunks: list[dict[str, Any]],
        chunk_ids: list[str],
        core: CoreKnowledge,
    ) -> PedagogicalKnowledge:
        """Call 2 — what a teacher does with it. Needs call 1's concept ids."""
        await span.progress(0.45, message="extracting objectives and misconceptions")

        inventory = "\n".join(
            f"- {c.concept_id}: {c.name} — {c.summary[:110]}" for c in core.concepts
        ) or "- (no concepts were extracted; infer them from the document)"

        result = await self._llm.parse(
            stage=self.name,
            output_model=PedagogicalKnowledge,
            system=system,
            user_content=(
                f"{document_block(_chunk_text(chunks))}\n\n"
                f"CONCEPTS ALREADY EXTRACTED (use these ids verbatim in concept_ids "
                f"and in concept_edges; do not invent new ids):\n{inventory}\n\n"
                f"{evidence_rules(chunk_ids)}\n\n"
                "Now produce the teaching layer: learning objectives, assumed "
                "prerequisites, worked examples, real-world applications, likely "
                "student misconceptions, and the dependency edges between the "
                "concepts listed above.\n\n"
                "A `prerequisite_of` edge means the first concept must be taught "
                "before the second. Add an edge only where the dependency is real."
            ),
        )
        if result.degraded:
            span.warn("pedagogical knowledge extraction degraded")
        await span.progress(0.70)
        return result.value

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            chunks: list[dict[str, Any]] = state.get("chunks") or []
            classification = state.get("classification") or {}
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))
            chunk_ids = [c["chunk_id"] for c in chunks]
            total_tokens = sum(c.get("token_count", 0) for c in chunks)

            system = f"{SYSTEM}\n\n{strategy.prompt_guidance()}\n\n{OUTPUT_DISCIPLINE}"

            # Extraction runs as two narrower calls rather than one wide one.
            # Measured cause: the full KnowledgeBase schema is ~2.7k tokens of
            # prompt before the document even appears, and the object it demands
            # does not fit a 4k output budget — smaller models returned
            # json_validate_failed with an EMPTY generation, meaning nothing was
            # produced at all. Two calls each fit comfortably, and a weak call now
            # costs one half instead of everything.
            if total_tokens <= SINGLE_CALL_TOKEN_BUDGET or len(chunks) <= 4:
                core = await self._extract_core(span, system, chunks, chunk_ids, 0.15, 0.40)
            else:
                groups = _group_by_section(chunks)
                await span.progress(0.12, message=f"map-reduce over {len(groups)} sections")
                cores: list[CoreKnowledge] = []
                for index, group in enumerate(groups, start=1):
                    part = await self._extract_core(
                        span,
                        system,
                        group,
                        [c["chunk_id"] for c in group],
                        0.12 + 0.28 * (index - 1) / len(groups),
                        0.12 + 0.28 * index / len(groups),
                        scope="THIS SECTION only",
                    )
                    cores.append(part)
                core = _merge_cores(cores)

            # Objectives, misconceptions, and the dependency graph are
            # document-level judgements, so they are always produced globally —
            # fragmenting them across sections yields objectives that describe a
            # paragraph rather than the chapter.
            pedagogy = await self._extract_pedagogy(span, system, chunks, chunk_ids, core)
            payload = merge_pair(core, pedagogy)

            # ── deterministic citation verification ────────────────────────
            await span.progress(0.75, message="verifying citations")
            chunks_by_id = {c["chunk_id"]: c["text"] for c in chunks}
            audit = EvidenceAudit()
            for field in GROUNDED_FIELDS:
                payload[field], audit = verify_items(
                    payload.get(field) or [], chunks_by_id, label=field, audit=audit
                )
            if audit.dropped:
                span.warn(f"evidence verification — {audit.summary()}")

            # ── concept graph ──────────────────────────────────────────────
            concept_ids = [c["concept_id"] for c in payload["concepts"]]
            raw_graph = payload.get("concept_graph") or {}
            graph, repair = build_concept_graph(concept_ids, raw_graph.get("edges") or [])
            payload["concept_graph"] = graph
            if repair.changed:
                span.warn(f"concept graph repaired — {repair.summary()}")

            # Objectives and misconceptions may reference concepts that citation
            # verification removed; strip those references so the package stays
            # internally consistent.
            known = set(concept_ids)
            for field in ("learning_objectives", "prerequisites", *GROUNDED_FIELDS):
                for item in payload.get(field) or []:
                    if "concept_ids" in item:
                        item["concept_ids"] = [c for c in item["concept_ids"] if c in known]

            knowledge = KnowledgeBase.model_validate(payload)
            await span.progress(
                0.95,
                message=(
                    f"{len(knowledge.concepts)} concepts, "
                    f"{len(knowledge.learning_objectives)} objectives"
                ),
            )
            return {"knowledge": knowledge.model_dump(mode="json")}
