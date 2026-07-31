"""Stage 8 — gap selection, severity, and reconstruction.

Severity is the interesting part. It is computed from the concept graph rather
than asked for, so these tests assert a structural property: a misconception
about a concept the rest of the chapter is built on outranks one about a leaf,
regardless of how either is worded.
"""

from __future__ import annotations

from stages.s8_gaps.schemas import DiagnosticDraft, GapDraft, RemediationDraft
from stages.s8_gaps.severity import GapSeed, downstream_load, plan_seeds
from stages.s8_gaps.stage import build_gap

# a -> b -> c, and a -> d.  `a` gates three concepts; `c` and `d` gate nothing.
GRAPH = {
    "edges": [
        {"from_id": "a", "to_id": "b", "relation": "prerequisite_of"},
        {"from_id": "b", "to_id": "c", "relation": "prerequisite_of"},
        {"from_id": "a", "to_id": "d", "relation": "prerequisite_of"},
        {"from_id": "a", "to_id": "c", "relation": "related_to"},
    ]
}


def _knowledge(misconceptions: list[dict] | None = None) -> dict:
    return {
        "concepts": [
            {"concept_id": cid, "name": cid.upper(), "summary": "s", "importance": "core"}
            for cid in ("a", "b", "c", "d")
        ],
        "misconceptions": misconceptions or [],
        "concept_graph": GRAPH,
    }


# ──────────────────────────────────────────────────────────── downstream load


def test_load_is_transitive_not_just_direct() -> None:
    """`a` directly gates b and d, but b gates c — so a is load-bearing for three."""
    load = downstream_load(GRAPH)
    assert load["a"] == 3
    assert load["b"] == 1
    assert load.get("c", 0) == 0


def test_only_prerequisite_edges_count() -> None:
    """`related_to` is not a dependency; counting it would inflate every severity."""
    load = downstream_load({"edges": [{"from_id": "a", "to_id": "b", "relation": "related_to"}]})
    assert load.get("a", 0) == 0


def test_a_cyclic_graph_from_an_old_checkpoint_does_not_hang() -> None:
    cyclic = {
        "edges": [
            {"from_id": "x", "to_id": "y", "relation": "prerequisite_of"},
            {"from_id": "y", "to_id": "x", "relation": "prerequisite_of"},
        ]
    }
    assert downstream_load(cyclic)["x"] == 1


# ────────────────────────────────────────────────────────────────── severity


def test_a_load_bearing_concept_outranks_a_leaf() -> None:
    seeds = plan_seeds(
        _knowledge(
            [
                {"misconception_id": "m1", "statement": "wrong about a", "concept_ids": ["a"]},
                {"misconception_id": "m2", "statement": "wrong about c", "concept_ids": ["c"]},
            ]
        )
    )
    by_concept = {seed.concept_ids[0]: seed.severity for seed in seeds if seed.concept_ids}
    assert by_concept["a"] == "high"
    assert by_concept["c"] != "high"


def test_high_severity_gaps_are_reported_first() -> None:
    seeds = plan_seeds(
        _knowledge(
            [
                {"misconception_id": "m1", "statement": "leaf error", "concept_ids": ["c"]},
                {"misconception_id": "m2", "statement": "root error", "concept_ids": ["a"]},
            ]
        )
    )
    assert seeds[0].concept_ids == ["a"]


# ───────────────────────────────────────────────────────────── seed planning


def test_observed_gaps_carry_the_source_evidence_forward() -> None:
    seeds = plan_seeds(
        _knowledge(
            [
                {
                    "misconception_id": "m1",
                    "statement": "heavier falls faster",
                    "why_it_happens": "everyday experience",
                    "correction": "air resistance differs, not gravity",
                    "concept_ids": ["a"],
                    "evidence": [{"chunk_id": "c_0001", "quote": "objects fall"}],
                }
            ]
        )
    )
    observed = [s for s in seeds if s.observed]
    assert observed and observed[0].evidence
    assert observed[0].correction


def test_load_bearing_concepts_get_predicted_gaps_the_document_never_named() -> None:
    """A chapter rarely lists the errors students make on its own hardest ideas."""
    seeds = plan_seeds(_knowledge([]))
    predicted = [s for s in seeds if not s.observed]
    assert predicted
    assert "a" in {cid for seed in predicted for cid in seed.concept_ids}
    assert all(seed.evidence == [] for seed in predicted)


def test_a_concept_already_covered_is_not_also_predicted() -> None:
    seeds = plan_seeds(
        _knowledge([{"misconception_id": "m1", "statement": "x", "concept_ids": ["a"]}])
    )
    for_a = [seed for seed in seeds if seed.concept_ids == ["a"]]
    assert len(for_a) == 1
    assert for_a[0].observed


def test_gap_ids_are_unique() -> None:
    seeds = plan_seeds(
        _knowledge(
            [
                {"misconception_id": "m1", "statement": "x", "concept_ids": ["a"]},
                {"misconception_id": "m2", "statement": "y", "concept_ids": ["b"]},
            ]
        )
    )
    ids = [seed.gap_id for seed in seeds]
    assert len(ids) == len(set(ids))


def test_a_document_with_no_structure_and_no_misconceptions_yields_no_gaps() -> None:
    assert plan_seeds({"concepts": [], "misconceptions": [], "concept_graph": {}}) == []


# ───────────────────────────────────────────────────────────────── gap build


def _seed(**kwargs) -> GapSeed:
    base = {"gap_id": "gap_01", "concept_ids": ["a"], "severity": "high"}
    return GapSeed(**{**base, **kwargs})


def test_a_gap_without_a_diagnostic_is_dropped() -> None:
    """Detect-and-fix is the whole value; a gap missing detection is just a worry."""
    gap, notes = build_gap(
        _seed(misconception="heavier falls faster"),
        GapDraft(
            misconception="heavier falls faster",
            remediation=[RemediationDraft(action="drop two objects", rationale="shows it")],
        ),
    )
    assert gap is None
    assert any("diagnostic" in n for n in notes)


def test_the_documents_own_correction_is_used_when_remediation_is_missing() -> None:
    gap, notes = build_gap(
        _seed(misconception="heavier falls faster", correction="air resistance differs"),
        GapDraft(
            misconception="heavier falls faster",
            diagnostic_questions=[
                DiagnosticDraft(question="Which lands first?", reveals="the belief")
            ],
        ),
    )
    assert gap is not None
    assert gap.remediation[0].action == "air resistance differs"
    assert any("document's own correction" in n for n in notes)


def test_a_predicted_gap_with_no_remediation_is_dropped() -> None:
    """Nothing to fall back on — a predicted seed carries no correction."""
    gap, _ = build_gap(
        _seed(),
        GapDraft(
            misconception="students think X",
            diagnostic_questions=[DiagnosticDraft(question="Q?", reveals="R")],
        ),
    )
    assert gap is None


def test_a_complete_gap_survives_with_its_computed_severity() -> None:
    gap, notes = build_gap(
        _seed(severity="high", concept_ids=["a", "b"]),
        GapDraft(
            misconception="heavier objects fall faster",
            why_it_happens="everyday experience with air resistance",
            diagnostic_questions=[
                DiagnosticDraft(
                    question="A feather and a hammer on the Moon — which lands first?",
                    reveals="whether the student separates gravity from air resistance",
                    expected_wrong_answer="the hammer",
                )
            ],
            remediation=[
                RemediationDraft(
                    action="Show the Apollo 15 hammer-and-feather drop.",
                    rationale="Removes air resistance, isolating the variable.",
                    estimated_minutes=6,
                )
            ],
        ),
    )
    assert gap is not None
    assert notes == []
    assert gap.severity == "high"
    assert gap.concept_ids == ["a", "b"]
    assert gap.diagnostic_questions[0].expected_wrong_answer == "the hammer"
    assert gap.remediation[0].estimated_minutes == 6
