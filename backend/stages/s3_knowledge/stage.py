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

from collections.abc import Callable
from typing import Any

from contracts.knowledge import KnowledgeBase
from core.llm.base import estimate_tokens, schema_tokens
from core.llm.client import LLMClient
from core.llm.prompts import OUTPUT_DISCIPLINE, document_block, evidence_rules
from pedagogy.registry import get_strategy
from stages.base import StageContext, stage_span
from stages.s3_knowledge.concept_graph import build_concept_graph
from stages.s3_knowledge.grounding import EvidenceAudit, verify_items
from stages.s3_knowledge.schemas import CoreKnowledge, PedagogicalKnowledge, merge_pair

__all__ = ["KnowledgeExtractionStage", "derive_objectives"]

#: Fallback document window, used only when the route declares no ``tpm_ceiling``.
#: Above this, extraction runs section-by-section and merges: a single call over a
#: long chapter degrades badly — recall drops and citations get vaguer.
#:
#: It is a *fallback* now rather than the rule. As a constant it was a guess about
#: a provider it never named, and on the groq profile it was wrong by a factor of
#: eight: the real window there is `8000 - max_tokens - schema - system - margin`.
#: A run packed to 12,000 and was rejected before the model ran. Where a ceiling
#: is declared the number is computed from it; see :func:`_document_budget`.
SINGLE_CALL_TOKEN_BUDGET = 12_000

#: Never plan a document window smaller than this. Below it the per-call overhead
#: dominates so completely that the pass cannot say anything about the material,
#: and the honest answer is that this route cannot run this stage — which the
#: adapter's pre-flight check reports precisely, rather than this stage papering
#: over it with hundreds of useless calls.
MIN_DOCUMENT_WINDOW = 400

#: The catch-all key for chunks that carry no section path. Not a section: it is
#: what structure detection produces when it finds nothing, so it can hold most of
#: a document, and the "never split a section" rule must not apply to it.
ROOT_BUCKET = "__root__"

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


def derive_objectives(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One objective per concept, when extraction returned none of its own.

    Stage 4 cannot build a plan without objectives — every period must serve at
    least one — so an empty list ends the run at stage 4 and throws away three
    stages of work and real model spend. That happened on a live narrative
    document: concepts came back, objectives did not, and the whole job failed.

    Deriving them is honest rather than inventive. ``LearningObjective`` is not a
    grounded type: it carries no evidence, so nothing here fabricates a citation.
    Each derived objective points at a ``concept_id`` that genuinely exists, and
    "explain this concept and why it matters" is what the concept already
    asserts is teachable. ``understand`` is the floor Bloom level a concept
    implies, deliberately not guessed higher.

    The caller warns, and the eval harness scores these lower than authored
    objectives — a derived objective is a degraded package, not a silent one.
    """
    derived: list[dict[str, Any]] = []
    for index, concept in enumerate(concepts):
        name = str(concept.get("name") or "").strip()
        if not name:
            continue
        derived.append(
            {
                "objective_id": f"obj_derived_{index + 1:02d}",
                "statement": f"Explain {name}, and why it matters in this material.",
                "bloom_level": "understand",
                "concept_ids": [str(concept["concept_id"])],
            }
        )
    return derived


def _chunk_text(chunks: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{chunk['chunk_id']}]"
        + (f" ({' > '.join(chunk['section_path'])})" if chunk.get("section_path") else "")
        + f"\n{chunk['text']}"
        for chunk in chunks
    )


def _tokens_of(chunks: list[dict[str, Any]]) -> int:
    return sum(int(chunk.get("token_count") or 0) for chunk in chunks)


def _group_by_section(chunks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group chunks under their top-level section, preserving order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        path = chunk.get("section_path") or []
        key = path[0] if path else ROOT_BUCKET
        groups.setdefault(key, []).append(chunk)
    return list(groups.values())


def _is_root_bucket(group: list[dict[str, Any]]) -> bool:
    """Whether this group is the no-section-path catch-all rather than a section."""
    return not (group and (group[0].get("section_path") or []))


def _split_to_budget(chunks: list[dict[str, Any]], budget: int) -> list[list[dict[str, Any]]]:
    """Cut a run of chunks into budget-sized pieces, in document order.

    A single chunk larger than the budget is emitted alone and still over it: the
    chunk is the smallest unit this stage has, and slicing text inside one would
    cut a quote in half and make it unciteable. That is a chunker problem, and the
    adapter's pre-flight check names it as one rather than letting it look like a
    packing failure here.
    """
    pieces: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    tokens = 0
    for chunk in chunks:
        size = int(chunk.get("token_count") or 0)
        if current and tokens + size > budget:
            pieces.append(current)
            current, tokens = [], 0
        current.append(chunk)
        tokens += size
    if current:
        pieces.append(current)
    return pieces


def _pack_sections(
    chunks: list[dict[str, Any]],
    budget: int = SINGLE_CALL_TOKEN_BUDGET,
    *,
    warn: Callable[[str], None] | None = None,
    hard_ceiling: bool = False,
) -> list[list[dict[str, Any]]]:
    """Pack sections into as few calls as the token budget allows.

    One call per section made extraction cost scale with how finely a document
    happens to be *sectioned*, which is a formatting accident, not a measure of
    content. A real NCERT chapter — 44 pages, 56k tokens — has 22 top-level
    sections and so cost 44 calls before this, against a free tier that allows
    50 per day. The same chapter packs into 5 groups.

    Sections are packed in document order and never split, so a section's chunks
    always reach the model together and the narrowed-context property that makes
    these prompts answerable is preserved. A single section larger than the budget
    still gets its own call, and is reported through ``warn``: splitting it would
    break that property, and an oversized prompt is the lesser problem.

    ``hard_ceiling`` is when that last sentence stops being true. It says the
    budget is a provider limit rather than a preference, and against a limit an
    oversized prompt is not a lesser problem — it is a request that cannot be
    sent at all, so keeping the section whole buys context for a call that never
    happens. Then, and only then, an oversized section is split too, loudly.

    **``__root__`` is exempt from that exemption.** It is not a section — it is
    where chunks land when structure detection found no heading above them — so
    "keep it together" protects nothing: there is no narrowed context to preserve,
    only an accident of parsing. Treating it as a section meant the never-split
    rule applied to a bucket that can hold most of the document. Measured on a
    real NCERT chapter, 198 of 262 chunks landed there and produced a single pass
    at 336% of budget, which is precisely the shape of request the provider
    rejects. It is packed to budget like ordinary content instead.

    That correctness does not depend on how large the root bucket happens to be.
    Structure detection improving shrinks it, and this loop then simply never
    splits anything; regressing grows it, and the splitting keeps every pass
    inside budget. Either way no pass exceeds the budget for a reason that was
    never about content.

    Calls scale with content volume, which is the variable that should decide them.
    """
    units: list[list[dict[str, Any]]] = []
    for group in _group_by_section(chunks):
        tokens = _tokens_of(group)
        if _is_root_bucket(group):
            if tokens > budget and warn is not None:
                warn(
                    f"{len(group)} chunks ({tokens:,} tokens) carry no section path and "
                    f"were split across {-(-tokens // budget)} passes to fit the "
                    f"{budget:,}-token window; a large unsectioned bucket usually means "
                    "structure detection found no headings, not that the document has none"
                )
            units.extend(_split_to_budget(group, budget))
            continue
        if tokens <= budget:
            units.append(group)
            continue

        name = group[0]["section_path"][0]
        if not hard_ceiling:
            if warn is not None:
                warn(
                    f"section {name!r} is {tokens:,} tokens, over the {budget:,}-token "
                    "window; kept whole because splitting a section splits the context "
                    "that makes its prompt answerable, and the window is a preference"
                )
            units.append(group)
            continue

        pieces = _split_to_budget(group, budget)
        if warn is not None:
            warn(
                f"section {name!r} is {tokens:,} tokens against a hard {budget:,}-token "
                f"ceiling, so it was split across {len(pieces)} passes; each pass sees "
                "less context than the section provides, which costs recall — but a "
                "section kept whole is a request the provider rejects outright"
            )
        units.extend(pieces)

    packed: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for unit in units:
        tokens = _tokens_of(unit)
        if current and current_tokens + tokens > budget:
            packed.append(current)
            current, current_tokens = [], 0
        current.extend(unit)
        current_tokens += tokens

    if current:
        packed.append(current)
    return packed


CORE_TASK = (
    "Extract the factual backbone of {scope}: the concepts it teaches, "
    "the terms it defines, any formulae it states, and its keywords. "
    "Do not produce learning objectives or misconceptions here — those "
    "are requested separately."
)

PEDAGOGY_TASK = (
    "Now produce the teaching layer: learning objectives, assumed "
    "prerequisites, worked examples, real-world applications, likely "
    "student misconceptions, and the dependency edges between the "
    "concepts listed above.\n\n"
    "A `prerequisite_of` edge means the first concept must be taught "
    "before the second. Add an edge only where the dependency is real."
)

#: Told to the model when its document view is a selection rather than the whole
#: chapter. Without it the model reads gaps as the document ending and writes
#: objectives for a fragment; with it, it treats the concept inventory as the
#: statement of scope and the excerpts as the evidence it must quote from.
PEDAGOGY_SCOPE_NOTE = (
    "The excerpts below are the passages that support the concepts listed above, "
    "plus a sample spanning the rest of the document. They are a selection, not "
    "the whole chapter. Judge objectives, prerequisites, and dependency edges "
    "against the FULL concept inventory — that inventory is the chapter's scope. "
    "Quote only from the excerpts, because a quote from text you were not shown "
    "cannot be verified and the claim carrying it is discarded."
)


#: Cost of one `[c_0001] (Section > Subsection)` header that :func:`_chunk_text`
#: interleaves. Not counted in any chunk's own ``token_count``, and at a hundred
#: chunks it is a thousand tokens of a window that is only a few thousand wide.
_CHUNK_HEADER_TOKENS = 12


def _document_budget(
    llm: LLMClient,
    stage: str,
    *,
    output_model: type[Any],
    fixed: str,
    chunks: list[dict[str, Any]],
) -> tuple[int, bool]:
    """Room left for document text on this route, and whether that room is hard.

    Everything that is not document text is not small. The strict JSON schema for
    ``CoreKnowledge`` is ~1.2k tokens and ``PedagogicalKnowledge`` ~1.8k, the
    system prompt with its pedagogy guidance is ~600, and the evidence rules list
    up to 60 chunk ids. On the groq profile the whole ceiling is 8000 and the
    answer reserves 3000 of it, so the fixed cost is most of what remains. A
    window chosen without subtracting it is not a window, which is how a pass
    packed to "12,000 tokens" became a 38,566-token request.

    The second return value is the one that changes behaviour elsewhere. ``True``
    means the route declared a ceiling and this number is a wall: a prompt over it
    is not merely large, it is unsendable. ``False`` means the window is the
    recall-driven preference it always was, and exceeding it costs quality rather
    than the request. :func:`_pack_sections` treats a section it cannot split very
    differently in those two worlds, and it is only allowed to because it is told
    which one it is in.

    Falls back to :data:`SINGLE_CALL_TOKEN_BUDGET` when no ceiling is declared —
    large-context production models genuinely have none worth planning around.
    """
    base = schema_tokens(output_model) + estimate_tokens(
        fixed, evidence_rules([c["chunk_id"] for c in chunks]), document_block("")
    )
    room = llm.prompt_budget(stage, overhead_tokens=base)
    if room is None:
        return SINGLE_CALL_TOKEN_BUDGET, False

    # Charge for the chunk headers a pass this size will actually carry, rather
    # than for every chunk in the document: a 3k-token window holds a handful of
    # chunks whether the document has 80 or 800, and charging for all of them
    # shrinks the window by more than the headers ever cost.
    average = max(1, _tokens_of(chunks) // max(len(chunks), 1))
    likely = min(len(chunks), max(1, room // average))
    room = llm.prompt_budget(stage, overhead_tokens=base + likely * _CHUNK_HEADER_TOKENS)
    return max(room or 0, MIN_DOCUMENT_WINDOW), True


def _citation_weights(core: CoreKnowledge) -> dict[str, int]:
    """How many extracted items cite each chunk, highest-value chunks first."""
    weights: dict[str, int] = {}
    for field in ("concepts", "definitions", "formulae"):
        for item in getattr(core, field, []) or []:
            for span in getattr(item, "evidence", []) or []:
                chunk_id = getattr(span, "chunk_id", None)
                if chunk_id:
                    weights[str(chunk_id)] = weights.get(str(chunk_id), 0) + 1
    return weights


def _pedagogy_context(
    chunks: list[dict[str, Any]], core: CoreKnowledge, budget: int
) -> list[dict[str, Any]]:
    """The slice of the document the pedagogy call actually needs, within budget.

    This call sent the *entire* document unconditionally, which threw away the
    only bound the stage had: the core pass is carefully map-reduced into
    budget-sized passes and then this one pass re-sent all of it. That single
    request was 38,566 tokens against an 8000-token ceiling — it is the request
    that killed a live run, and no amount of retrying could have made it fit.

    It does genuinely need document-level scope, which is why it is not simply
    packed like the core passes: objectives and dependency edges are judgements
    about the whole chapter, and fragmenting them produces objectives that
    describe a paragraph. But scope is not the same as every character. The
    concept inventory — passed in full, and cheap, at roughly one line each —
    already carries the document's structure. What the *document text* has to
    supply is quotable evidence, and the passages worth quoting are the ones the
    extracted concepts already cited.

    So: cited chunks first, most-cited first when they will not all fit, then the
    remaining budget spent on an even stride across everything uncited so the
    parts of the chapter that yielded no concepts are still represented. Whatever
    survives is emitted in document order, because reading order is information.
    """
    weights = _citation_weights(core)
    positions = {chunk["chunk_id"]: index for index, chunk in enumerate(chunks)}

    cited = [c for c in chunks if weights.get(c["chunk_id"])]
    cited.sort(key=lambda c: (-weights[c["chunk_id"]], positions[c["chunk_id"]]))

    selected: list[dict[str, Any]] = []
    spent = 0
    for chunk in cited:
        size = int(chunk.get("token_count") or 0)
        if spent + size > budget:
            continue
        selected.append(chunk)
        spent += size

    # Even stride over the uncited remainder: coverage of the whole document
    # beats a contiguous run of it, because what is missing from the concept
    # inventory is exactly what the head of the document does not explain.
    uncited = [c for c in chunks if not weights.get(c["chunk_id"])]
    if uncited and spent < budget:
        average = max(1, _tokens_of(uncited) // len(uncited))
        affordable = max(1, (budget - spent) // average)
        stride = max(1, len(uncited) // affordable)
        for chunk in uncited[::stride]:
            size = int(chunk.get("token_count") or 0)
            if spent + size > budget:
                break
            selected.append(chunk)
            spent += size

    selected.sort(key=lambda c: positions[c["chunk_id"]])
    return selected


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
                f"{CORE_TASK.format(scope=scope)}"
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
        core: CoreKnowledge,
    ) -> PedagogicalKnowledge:
        """Call 2 — what a teacher does with it. Needs call 1's concept ids."""
        await span.progress(0.45, message="extracting objectives and misconceptions")

        inventory = (
            "\n".join(f"- {c.concept_id}: {c.name} — {c.summary[:110]}" for c in core.concepts)
            or "- (no concepts were extracted; infer them from the document)"
        )
        preamble = (
            f"CONCEPTS ALREADY EXTRACTED (use these ids verbatim in concept_ids "
            f"and in concept_edges; do not invent new ids):\n{inventory}"
        )

        # The inventory is part of the fixed cost of this call, and on a long
        # chapter it is not small — a hundred concepts is a few thousand tokens.
        # Charging it to the overhead is what keeps the document selection below
        # from being sized against a window that is already spent.
        budget, _ = _document_budget(
            self._llm,
            self.name,
            output_model=PedagogicalKnowledge,
            fixed=f"{preamble}\n\n{PEDAGOGY_SCOPE_NOTE}\n\n{PEDAGOGY_TASK}\n\n{system}",
            chunks=chunks,
        )

        context = _pedagogy_context(chunks, core, budget)
        narrowed = len(context) < len(chunks)
        if narrowed:
            span.decide(
                f"pedagogy pass reads {len(context)} of {len(chunks)} chunks",
                f"objectives and edges are document-level judgements, but the document is "
                f"{_tokens_of(chunks):,} tokens against a {budget:,}-token window; scope comes "
                f"from the full {len(core.concepts)}-concept inventory, which is sent whole, "
                "and the text is narrowed to the passages those concepts cite plus a stride "
                "across the rest, so every claim still has a quotable source",
            )

        context_ids = [c["chunk_id"] for c in context]
        result = await self._llm.parse(
            stage=self.name,
            output_model=PedagogicalKnowledge,
            system=system,
            user_content=(
                f"{document_block(_chunk_text(context))}\n\n"
                f"{preamble}\n\n"
                + (f"{PEDAGOGY_SCOPE_NOTE}\n\n" if narrowed else "")
                + f"{evidence_rules(context_ids)}\n\n"
                f"{PEDAGOGY_TASK}"
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

            # What this route can actually spend on document text, rather than a
            # constant. On a large-context production model this is the old
            # recall-driven 12k; on the groq profile, whose real ceiling is 8000
            # tokens including the reservation for the answer, it is a fraction of
            # that — and packing to 12k there produced requests the provider
            # rejected outright. The budget is asked for, not assumed.
            core_budget, hard = _document_budget(
                self._llm,
                self.name,
                output_model=CoreKnowledge,
                fixed=f"{system}\n\n{CORE_TASK.format(scope='THIS SECTION only')}",
                chunks=chunks,
            )

            # Extraction runs as two narrower calls rather than one wide one.
            # Measured cause: the full KnowledgeBase schema is ~2.7k tokens of
            # prompt before the document even appears, and the object it demands
            # does not fit a 4k output budget — smaller models returned
            # json_validate_failed with an EMPTY generation, meaning nothing was
            # produced at all. Two calls each fit comfortably, and a weak call now
            # costs one half instead of everything.
            # A `len(chunks) <= 4` escape hatch used to share this condition. It
            # is gone: it assumed few chunks meant a small document, and a chunker
            # that emits four 10k-token chunks would have sent all of it in one
            # call regardless of the budget just computed. Chunk count says nothing
            # about size; the budget check already covers the case it meant to.
            if total_tokens <= core_budget:
                core = await self._extract_core(span, system, chunks, chunk_ids, 0.15, 0.40)
            else:
                groups = _pack_sections(chunks, core_budget, warn=span.warn, hard_ceiling=hard)
                span.decide(
                    f"extraction split into {len(groups)} passes",
                    f"{total_tokens:,} tokens exceeds the {core_budget:,}-token window this "
                    "route leaves for document text after the schema, system prompt, and the "
                    "reservation for the answer; sections are packed to that window rather "
                    "than one call each, so cost follows content volume",
                )
                await span.progress(0.12, message=f"map-reduce over {len(groups)} passes")
                cores: list[CoreKnowledge] = []
                for index, group in enumerate(groups, start=1):
                    part = await self._extract_core(
                        span,
                        system,
                        group,
                        [c["chunk_id"] for c in group],
                        0.12 + 0.28 * (index - 1) / len(groups),
                        0.12 + 0.28 * index / len(groups),
                        scope="THIS SECTION only" if len(groups) > 1 else "this document",
                    )
                    cores.append(part)
                core = _merge_cores(cores)

            # Objectives, misconceptions, and the dependency graph are
            # document-level judgements, so they are always produced globally —
            # fragmenting them across sections yields objectives that describe a
            # paragraph rather than the chapter.
            pedagogy = await self._extract_pedagogy(span, system, chunks, core)
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
                span.decide(
                    f"{audit.dropped} claims dropped",
                    "their quotes did not appear in the chunk they cited; an unverifiable "
                    "citation is removed here rather than propagating into six later stages",
                )

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

            if not payload.get("learning_objectives") and payload["concepts"]:
                payload["learning_objectives"] = derive_objectives(payload["concepts"])
                span.warn(
                    f"no learning objectives survived extraction; derived "
                    f"{len(payload['learning_objectives'])} from the concepts instead"
                )

            knowledge = KnowledgeBase.model_validate(payload)
            await span.progress(
                0.95,
                message=(
                    f"{len(knowledge.concepts)} concepts, "
                    f"{len(knowledge.learning_objectives)} objectives"
                ),
            )
            return {"knowledge": knowledge.model_dump(mode="json")}
