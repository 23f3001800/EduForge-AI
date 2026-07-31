"""Stage 8's deterministic half — which gaps exist, and which ones matter most.

Severity is computed from the concept dependency graph rather than asked for.
The contract defines ``high`` as "downstream concepts will fail if this is not
addressed first", which is a structural property of the DAG stage 3 built: a
misconception about a concept that three later concepts are built on is more
urgent than one about a leaf, whatever the prose around it suggests. A model
asked to rate severity mostly returns ``medium``, and where it does discriminate
it is reading tone rather than structure.

Gaps come from two places:

* **Observed** — the misconceptions stage 3 extracted from the document. These
  carry the source evidence forward, since the document named them.
* **Predicted** — concepts that carry real downstream load but that no extracted
  misconception touches. A chapter rarely lists the errors students make on its
  own hardest ideas, and a gap analysis that only restates the document's own
  warnings adds nothing a teacher could not get by reading it.

Predicted gaps carry no evidence, which is correct and is why ``LearningGap``
makes ``evidence`` optional where the stage 3 knowledge types do not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from contracts.primitives import Severity

__all__ = ["GapSeed", "downstream_load", "plan_seeds"]

#: How many concepts must depend on something before a misconception about it is
#: `high`. Two is deliberate: one dependent is a chain, and in a chapter of eight
#: concepts nearly everything has one.
HIGH_DEPENDENCY_THRESHOLD = 2

#: Cap on predicted gaps. Every gap costs a model call and a teacher's attention;
#: a list of fifteen "watch out for this" items is not read.
MAX_PREDICTED = 4

#: Ceiling on the whole analysis, for the same reason.
MAX_GAPS = 10


@dataclass(frozen=True, slots=True)
class GapSeed:
    """One gap's structure, fixed before the model writes its diagnostic or fix."""

    gap_id: str
    concept_ids: list[str]
    severity: Severity
    #: Present for observed gaps; empty for predicted ones.
    misconception: str = ""
    why_it_happens: str = ""
    correction: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def observed(self) -> bool:
        return bool(self.misconception)


def downstream_load(graph: Mapping[str, Any]) -> dict[str, int]:
    """How many concepts each concept is a prerequisite for, transitively.

    Transitive rather than direct: a concept that gates one concept which in turn
    gates four is load-bearing for five, and treating it as load-bearing for one
    would rank it alongside a leaf.
    """
    edges = [
        e
        for e in (graph.get("edges") or [])
        if e.get("relation") == "prerequisite_of" and e.get("from_id") and e.get("to_id")
    ]
    successors: dict[str, list[str]] = {}
    for edge in edges:
        successors.setdefault(str(edge["from_id"]), []).append(str(edge["to_id"]))

    load: dict[str, int] = {}
    for start in successors:
        # The stage 3 contract rejects prerequisite cycles, so a visited set is
        # belt-and-braces rather than load-bearing — but this must not hang on a
        # graph that reached us from a checkpoint written by an older build.
        seen: set[str] = set()
        stack = list(successors[start])
        while stack:
            node = stack.pop()
            if node in seen or node == start:
                continue
            seen.add(node)
            stack.extend(successors.get(node, ()))
        load[start] = len(seen)
    return load


def _severity_for(concept_ids: Sequence[str], load: Mapping[str, int], importance: str) -> Severity:
    reach = max((load.get(cid, 0) for cid in concept_ids), default=0)
    if reach >= HIGH_DEPENDENCY_THRESHOLD:
        return "high"
    if reach >= 1 or importance == "core":
        return "medium"
    return "low"


def plan_seeds(knowledge: Mapping[str, Any]) -> list[GapSeed]:
    """Decide the gap set: observed first, then predicted, ranked by severity."""
    concepts = list(knowledge.get("concepts") or [])
    misconceptions = list(knowledge.get("misconceptions") or [])
    load = downstream_load(knowledge.get("concept_graph") or {})
    importance_by_id = {
        str(c.get("concept_id")): str(c.get("importance") or "supporting") for c in concepts
    }

    seeds: list[GapSeed] = []
    covered: set[str] = set()

    for index, item in enumerate(misconceptions):
        concept_ids = [str(c) for c in (item.get("concept_ids") or [])]
        covered.update(concept_ids)
        importance = max(
            (importance_by_id.get(cid, "supporting") for cid in concept_ids),
            key=lambda value: value == "core",
            default="supporting",
        )
        seeds.append(
            GapSeed(
                gap_id=f"gap_{index + 1:02d}",
                concept_ids=concept_ids,
                severity=_severity_for(concept_ids, load, importance),
                misconception=str(item.get("statement") or ""),
                why_it_happens=str(item.get("why_it_happens") or ""),
                correction=str(item.get("correction") or ""),
                evidence=list(item.get("evidence") or []),
            )
        )

    # Predicted: load-bearing concepts nothing has flagged yet, hardest first.
    candidates = [
        concept
        for concept in concepts
        if str(concept.get("concept_id")) not in covered
        and (
            load.get(str(concept.get("concept_id")), 0) >= 1 or concept.get("importance") == "core"
        )
    ]
    candidates.sort(
        key=lambda c: (-load.get(str(c.get("concept_id")), 0), str(c.get("concept_id")))
    )

    for offset, concept in enumerate(candidates[:MAX_PREDICTED]):
        cid = str(concept.get("concept_id"))
        seeds.append(
            GapSeed(
                gap_id=f"gap_{len(misconceptions) + offset + 1:02d}",
                concept_ids=[cid],
                severity=_severity_for([cid], load, str(concept.get("importance") or "")),
            )
        )

    rank = {"high": 0, "medium": 1, "low": 2}
    seeds.sort(key=lambda seed: (rank[seed.severity], not seed.observed, seed.gap_id))
    return seeds[:MAX_GAPS]
