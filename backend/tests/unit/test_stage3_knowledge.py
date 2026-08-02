"""Stage 3 — citation verification and concept-graph repair.

Both are deterministic, which is the point: the cheapest hallucination defence in
the system runs before any judge model and costs nothing.

A fabricated citation is the most dangerous single failure in this pipeline. It
does not look like an error — it looks like a well-sourced fact — and it
propagates into the teaching plan, the lesson content, and the assessment bank
before anyone reads it.
"""

from __future__ import annotations

import pytest

from stages.s3_knowledge.concept_graph import build_concept_graph
from stages.s3_knowledge.grounding import normalise, verify_items

CHUNKS = {
    "c_0001": (
        "A body continues in its state of rest or uniform motion in a straight "
        "line unless acted upon by an external unbalanced force."
    ),
    "c_0002": "The acceleration of a body is proportional to the net force: F = m a.",
}


def _item(chunk_id: str, quote: str, name: str = "x") -> dict:
    return {"name": name, "evidence": [{"chunk_id": chunk_id, "quote": quote}]}


# ────────────────────────────────────────────────── citation verification


def test_a_verbatim_quote_is_kept() -> None:
    items = [_item("c_0001", "unless acted upon by an external unbalanced force")]
    kept, audit = verify_items(items, CHUNKS, label="concepts")
    assert len(kept) == 1
    assert audit.dropped == 0


def test_an_invented_quote_is_dropped() -> None:
    """The failure this whole mechanism exists for: a plausible fabrication."""
    items = [_item("c_0001", "Newton discovered this while watching an apple fall.")]
    kept, audit = verify_items(items, CHUNKS, label="concepts")
    assert kept == []
    assert audit.dropped_quote_absent == 1


def test_a_citation_to_a_nonexistent_chunk_is_dropped() -> None:
    """Models invent chunk ids as readily as they invent quotes."""
    items = [_item("c_9999", "unless acted upon by an external unbalanced force")]
    kept, audit = verify_items(items, CHUNKS, label="concepts")
    assert kept == []
    assert audit.dropped_unknown_chunk == 1


def test_an_item_with_no_evidence_is_dropped() -> None:
    kept, audit = verify_items([{"name": "x", "evidence": []}], CHUNKS, label="concepts")
    assert kept == []
    assert audit.dropped_no_evidence == 1


def test_extraction_artefacts_do_not_count_as_paraphrase() -> None:
    """PDFs mangle whitespace and quotation marks; that is not the model's fault."""
    items = [_item("c_0001", "unless   acted  upon\nby an external unbalanced force")]
    kept, _ = verify_items(items, CHUNKS, label="concepts")
    assert len(kept) == 1


def test_a_near_verbatim_quote_is_kept_but_confidence_is_lowered() -> None:
    """Reformatting survives with a marked-down score; invention does not survive."""
    items = [_item("c_0002", "acceleration of a body is proportional to net force")]
    kept, audit = verify_items(items, CHUNKS, label="concepts")
    assert len(kept) == 1
    assert audit.repaired_quote == 1
    assert kept[0]["evidence"][0]["confidence"] < 1.0


def test_only_the_unverifiable_evidence_entries_are_stripped() -> None:
    """An item with one good and one bad citation keeps the good one."""
    item = {
        "name": "inertia",
        "evidence": [
            {"chunk_id": "c_0001", "quote": "unless acted upon by an external unbalanced force"},
            {"chunk_id": "c_0001", "quote": "Entirely fabricated supporting sentence here."},
        ],
    }
    kept, _ = verify_items([item], CHUNKS, label="concepts")
    assert len(kept) == 1
    assert len(kept[0]["evidence"]) == 1


def test_audit_reports_what_it_removed() -> None:
    """Silent dropping would hide a systematic extraction failure."""
    items = [
        _item("c_0001", "unless acted upon by an external unbalanced force"),
        _item("c_9999", "unless acted upon by an external unbalanced force"),
        _item("c_0001", "A completely invented sentence with no basis at all."),
    ]
    _, audit = verify_items(items, CHUNKS, label="concepts")
    assert audit.kept == 1
    assert audit.dropped == 2
    assert audit.notes


def test_normalisation_folds_smart_punctuation() -> None:
    assert normalise("The teacher's “note” — here") == normalise('The teacher\'s "note" - here')


# ───────────────────────────────────────────────────── concept graph repair


def _edge(a: str, b: str, confidence: float = 1.0, relation: str = "prerequisite_of") -> dict:
    return {"from_id": a, "to_id": b, "relation": relation, "confidence": confidence}


def test_an_acyclic_graph_passes_through_unchanged() -> None:
    graph, repair = build_concept_graph(["a", "b", "c"], [_edge("a", "b"), _edge("b", "c")])
    assert len(graph["edges"]) == 2
    assert repair.changed is False


def test_a_two_node_cycle_is_broken_at_the_weakest_edge() -> None:
    """Models emit these constantly — both directions are defensible sentences."""
    graph, repair = build_concept_graph(["a", "b"], [_edge("a", "b", 0.9), _edge("b", "a", 0.4)])
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["from_id"] == "a"
    assert repair.dropped_edges == [("b", "a")]


def test_a_three_node_cycle_is_broken() -> None:
    """A pairwise check misses this; the DFS must find the whole loop."""
    graph, repair = build_concept_graph(
        ["a", "b", "c"],
        [_edge("a", "b", 0.9), _edge("b", "c", 0.8), _edge("c", "a", 0.2)],
    )
    assert len(graph["edges"]) == 2
    assert ("c", "a") in repair.dropped_edges


def test_the_repaired_graph_satisfies_the_contract() -> None:
    """End-to-end guarantee: whatever arrives, what leaves is constructible."""
    from contracts.knowledge import ConceptGraph

    graph, _ = build_concept_graph(
        ["a", "b", "c"],
        [_edge("a", "b"), _edge("b", "c"), _edge("c", "a"), _edge("a", "a")],
    )
    ConceptGraph.model_validate(graph)


def test_symmetric_contrast_edges_are_preserved() -> None:
    """`contrasts_with` is legitimately bidirectional; only ordering must be acyclic."""
    graph, repair = build_concept_graph(
        ["a", "b"],
        [_edge("a", "b", relation="contrasts_with"), _edge("b", "a", relation="contrasts_with")],
    )
    assert len(graph["edges"]) == 2
    assert repair.changed is False


def test_self_edges_and_dangling_references_are_removed() -> None:
    graph, repair = build_concept_graph(["a", "b"], [_edge("a", "a"), _edge("a", "ghost")])
    assert graph["edges"] == []
    assert repair.dropped_self == 1
    assert repair.dropped_unknown == 1


def test_duplicate_edges_are_collapsed() -> None:
    graph, _ = build_concept_graph(["a", "b"], [_edge("a", "b"), _edge("a", "b")])
    assert len(graph["edges"]) == 1


def test_repair_summary_is_human_readable() -> None:
    _, repair = build_concept_graph(["a", "b"], [_edge("a", "b"), _edge("b", "a")])
    assert "cycle" in repair.summary()


# ───────────────────────────────────────────────────────── merge behaviour


def _core(chunk: str) -> object:
    from stages.s3_knowledge.schemas import CoreKnowledge

    return CoreKnowledge.model_validate(
        {
            "concepts": [
                {
                    "concept_id": "c1",
                    "name": "Inertia",
                    "summary": "Resistance to change in motion.",
                    "importance": "core",
                    "evidence": [{"chunk_id": chunk, "quote": "a quote long enough"}],
                }
            ]
        }
    )


def test_merging_sections_unions_evidence_rather_than_replacing_it() -> None:
    """A concept found in two sections is better supported, not duplicated."""
    from stages.s3_knowledge.stage import _merge_cores

    merged = _merge_cores([_core("c_0001"), _core("c_0002")])  # type: ignore[arg-type]
    assert len(merged.concepts) == 1
    assert len(merged.concepts[0].evidence) == 2


# ──────────────────────────────────────────────────── split extraction


def test_the_two_halves_recombine_into_one_knowledge_base() -> None:
    """The split must be invisible downstream — stage output shape is unchanged."""
    from stages.s3_knowledge.schemas import PedagogicalKnowledge, merge_pair

    pedagogy = PedagogicalKnowledge.model_validate(
        {
            "learning_objectives": [
                {
                    "objective_id": "o1",
                    "statement": "Explain why a moving body keeps moving.",
                    "bloom_level": "understand",
                    "concept_ids": ["c1"],
                }
            ],
            "concept_edges": [
                {"from_id": "c1", "to_id": "c1", "relation": "requires", "confidence": 1.7}
            ],
        }
    )
    merged = merge_pair(_core("c_0001"), pedagogy)  # type: ignore[arg-type]

    assert [c["concept_id"] for c in merged["concepts"]] == ["c1"]
    assert len(merged["learning_objectives"]) == 1
    assert merged["concept_graph"]["node_ids"] == ["c1"]


def test_an_invented_relation_name_does_not_discard_the_edge() -> None:
    """Models reach for `requires`/`depends_on`. Losing a real dependency over a
    vocabulary slip is worse than coercing it to the ordering relation."""
    from stages.s3_knowledge.schemas import ConceptEdgeDraft

    edge = ConceptEdgeDraft.model_validate(
        {"from_id": "a", "to_id": "b", "relation": "depends_on", "confidence": 1.4}
    )
    assert edge.relation == "prerequisite_of"
    assert edge.confidence == 1.0  # clamped, not rejected


def test_a_degraded_half_does_not_discard_the_other() -> None:
    """The whole reason for splitting: one weak call costs half, not everything."""
    from stages.s3_knowledge.schemas import CoreKnowledge, PedagogicalKnowledge, merge_pair

    merged = merge_pair(_core("c_0001"), PedagogicalKnowledge())  # type: ignore[arg-type]
    assert len(merged["concepts"]) == 1
    assert merged["learning_objectives"] == []

    merged = merge_pair(
        CoreKnowledge(),
        PedagogicalKnowledge.model_validate(
            {
                "misconceptions": [
                    {
                        "misconception_id": "m1",
                        "statement": "Motion needs a force.",
                        "why_it_happens": "Friction hides the ideal case.",
                        "correction": "Uniform motion needs no net force.",
                        "evidence": [{"chunk_id": "c_0001", "quote": "a quote long enough"}],
                    }
                ]
            }
        ),
    )
    assert merged["concepts"] == []
    assert len(merged["misconceptions"]) == 1


# ─────────────────────────────────────────── objective fallback (live failure)


def test_objectives_are_derived_when_extraction_returns_none() -> None:
    """A live narrative run died at stage 4 with concepts but zero objectives.

    Stage 4 requires an objective per period, so an empty list ends the job and
    discards three stages of completed work and real model spend. Deriving from
    the concepts that DID survive turns a total loss into a degraded package.
    """
    from stages.s3_knowledge.stage import derive_objectives

    concepts = [
        {"concept_id": "c1", "name": "Partition of Bengal", "summary": "s", "importance": "core"},
        {"concept_id": "c2", "name": "Swadeshi Movement", "summary": "s", "importance": "core"},
    ]
    derived = derive_objectives(concepts)

    assert len(derived) == 2
    assert {o["concept_ids"][0] for o in derived} == {"c1", "c2"}
    # Every reference must resolve; an objective pointing at nothing is worse
    # than no objective, because stage 9 reports it as a broken package.
    assert all(o["concept_ids"][0] in {"c1", "c2"} for o in derived)
    assert len({o["objective_id"] for o in derived}) == 2
    # Not credited above the floor a bare concept actually implies.
    assert all(o["bloom_level"] == "understand" for o in derived)
    assert all(
        o["statement"] and not o["statement"].lower().startswith("understand ") for o in derived
    )


def test_derived_objectives_satisfy_the_planner_that_rejected_the_empty_list() -> None:
    """The fallback is only worth anything if stage 4 accepts it."""
    from stages.s3_knowledge.stage import derive_objectives
    from stages.s4_planner.banding import build_skeleton

    concepts = [
        {"concept_id": "c1", "name": "Partition of Bengal", "summary": "s", "importance": "core"},
    ]
    knowledge = {
        "concepts": concepts,
        "learning_objectives": derive_objectives(concepts),
        "concept_graph": {"edges": []},
    }
    skeleton = build_skeleton(knowledge, period_duration_minutes=40)
    assert skeleton is not None

    with pytest.raises(ValueError, match="no learning objectives"):
        build_skeleton({**knowledge, "learning_objectives": []}, period_duration_minutes=40)


def test_nothing_is_derived_when_there_are_no_concepts_either() -> None:
    """A document that yielded nothing must still fail loudly, not fabricate."""
    from stages.s3_knowledge.stage import derive_objectives

    assert derive_objectives([]) == []


# ───────────────────────────────────── extraction fan-out (real documents)


def _chunk(section: str, tokens: int, index: int) -> dict:
    return {
        "chunk_id": f"c_{index:04d}",
        "text": "x" * tokens,
        "token_count": tokens,
        "section_path": [section],
    }


def test_calls_scale_with_content_not_with_section_count() -> None:
    """A finely-sectioned document must not cost a call per heading.

    A real NCERT chapter — 44 pages, 56k tokens — has 22 top-level sections. One
    call per section meant 44 extraction calls against a free tier that allows
    50 per day, and a live run on it ran past thirty minutes. Section count is a
    formatting accident; token volume is the thing that should decide cost.
    """
    from stages.s3_knowledge.stage import _group_by_section, _pack_sections

    # 22 small sections, 56k tokens total — the shape of the real chapter.
    chunks = [_chunk(f"section {s}", 2_600, index) for s in range(22) for index in [s]]
    assert len(_group_by_section(chunks)) == 22

    packed = _pack_sections(chunks, budget=12_000)
    assert len(packed) < 8, f"packed into {len(packed)} passes, barely better than 22"
    # Nothing may be lost in the packing.
    assert sum(len(group) for group in packed) == len(chunks)


def test_a_section_is_never_split_across_calls() -> None:
    """A section's chunks must reach the model together.

    The narrowed-context property is what makes these prompts answerable at all;
    half a section in one call and half in another produces two partial readings
    of the same material.
    """
    from stages.s3_knowledge.stage import _pack_sections

    chunks = [_chunk("a", 5_000, 0), _chunk("a", 5_000, 1), _chunk("b", 5_000, 2)]
    packed = _pack_sections(chunks, budget=12_000)

    for group in packed:
        sections = {tuple(c["section_path"]) for c in group}
        # Either a group holds whole sections, or one oversized section alone.
        assert sections, "empty group"
    a_groups = [g for g in packed if any(c["section_path"] == ["a"] for c in g)]
    assert len(a_groups) == 1, "section 'a' was split across calls"


def test_a_section_larger_than_the_budget_still_gets_a_call() -> None:
    """Splitting it would break the narrowed context; an oversized prompt is the
    lesser problem, and the client already fits prompts to the token ceiling."""
    from stages.s3_knowledge.stage import _pack_sections

    chunks = [_chunk("huge", 40_000, 0)]
    packed = _pack_sections(chunks, budget=12_000)
    assert len(packed) == 1
    assert packed[0][0]["chunk_id"] == "c_0000"


def test_packing_preserves_document_order() -> None:
    """Extraction merges parts; out-of-order parts make the merge non-deterministic."""
    from stages.s3_knowledge.stage import _pack_sections

    chunks = [_chunk(f"s{i}", 4_000, i) for i in range(6)]
    packed = _pack_sections(chunks, budget=12_000)
    ids = [c["chunk_id"] for group in packed for c in group]
    assert ids == sorted(ids)
