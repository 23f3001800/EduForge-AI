"""Stage 3 — citation verification and concept-graph repair.

Both are deterministic, which is the point: the cheapest hallucination defence in
the system runs before any judge model and costs nothing.

A fabricated citation is the most dangerous single failure in this pipeline. It
does not look like an error — it looks like a well-sourced fact — and it
propagates into the teaching plan, the lesson content, and the assessment bank
before anyone reads it.
"""

from __future__ import annotations

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
    assert normalise("The teacher's “note” — here") == normalise("The teacher's \"note\" - here")


# ───────────────────────────────────────────────────── concept graph repair


def _edge(a: str, b: str, confidence: float = 1.0, relation: str = "prerequisite_of") -> dict:
    return {"from_id": a, "to_id": b, "relation": relation, "confidence": confidence}


def test_an_acyclic_graph_passes_through_unchanged() -> None:
    graph, repair = build_concept_graph(["a", "b", "c"], [_edge("a", "b"), _edge("b", "c")])
    assert len(graph["edges"]) == 2
    assert repair.changed is False


def test_a_two_node_cycle_is_broken_at_the_weakest_edge() -> None:
    """Models emit these constantly — both directions are defensible sentences."""
    graph, repair = build_concept_graph(
        ["a", "b"], [_edge("a", "b", 0.9), _edge("b", "a", 0.4)]
    )
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


def test_merging_sections_unions_evidence_rather_than_replacing_it() -> None:
    """A concept found in two sections is better supported, not duplicated."""
    from contracts.knowledge import KnowledgeBase
    from stages.s3_knowledge.stage import _merge_bases

    def base(chunk: str) -> KnowledgeBase:
        return KnowledgeBase.model_validate(
            {
                "concepts": [
                    {
                        "concept_id": "c1",
                        "name": "Inertia",
                        "summary": "Resistance to change in motion.",
                        "importance": "core",
                        "evidence": [{"chunk_id": chunk, "quote": "a quote long enough"}],
                    }
                ],
                "concept_graph": {"node_ids": ["c1"], "edges": []},
            }
        )

    merged = _merge_bases([base("c_0001"), base("c_0002")])
    assert len(merged["concepts"]) == 1
    assert len(merged["concepts"][0]["evidence"]) == 2
