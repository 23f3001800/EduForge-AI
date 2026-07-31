"""Concept dependency graph construction.

The ``prerequisite_of`` subgraph must be acyclic. Stage 4 topologically sorts it
to order periods, and stage 9 checks period ordering against it — neither is
meaningful if a cycle can survive, and the contract rejects one outright.

Models produce cycles regularly: "force requires mass" and "mass is understood
through force" are both defensible sentences, and an extraction pass will emit
both. So cycles are expected input, not an error condition. The graph is repaired
by dropping the lowest-confidence edge in each cycle and recording what was
dropped, which is more useful than failing a job nine stages from the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

__all__ = ["GraphRepair", "build_concept_graph"]


@dataclass(slots=True)
class GraphRepair:
    dropped_edges: list[tuple[str, str]] = field(default_factory=list)
    dropped_unknown: int = 0
    dropped_self: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.dropped_edges or self.dropped_unknown or self.dropped_self)

    def summary(self) -> str:
        parts = []
        if self.dropped_edges:
            shown = ", ".join(f"{a}->{b}" for a, b in self.dropped_edges[:3])
            parts.append(f"broke {len(self.dropped_edges)} cycle edge(s): {shown}")
        if self.dropped_unknown:
            parts.append(f"dropped {self.dropped_unknown} edge(s) to unknown concepts")
        if self.dropped_self:
            parts.append(f"dropped {self.dropped_self} self-edge(s)")
        return "; ".join(parts)


def _find_cycle(adjacency: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as a node path, or None. Iterative — graphs can be large."""
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(adjacency, white)
    parent: dict[str, str | None] = {}

    for root in adjacency:
        if colour[root] != white:
            continue
        stack: list[tuple[str, bool]] = [(root, False)]
        parent[root] = None
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colour[node] = black
                continue
            if colour[node] != white:
                continue
            colour[node] = grey
            stack.append((node, True))
            for nxt in adjacency.get(node, []):
                if colour.get(nxt, white) == grey:
                    # Walk back up the parent chain from `node` to the grey
                    # ancestor `nxt`, then close the loop with the edge
                    # node -> nxt. Closing it matters: that edge is often the
                    # weakest one, and omitting it from the returned path means
                    # the repair drops a stronger edge instead.
                    path = [node]
                    cursor: str | None = parent.get(node)
                    while cursor is not None and cursor != nxt:
                        path.append(cursor)
                        cursor = parent.get(cursor)
                    path.append(nxt)
                    path.reverse()
                    path.append(nxt)
                    return path
                if colour.get(nxt, white) == white:
                    parent[nxt] = node
                    stack.append((nxt, False))
    return None


def build_concept_graph(
    concept_ids: list[str], raw_edges: list[dict[str, Any]]
) -> tuple[dict[str, Any], GraphRepair]:
    """Produce a contract-valid concept graph from raw model output."""
    repair = GraphRepair()
    known = set(concept_ids)

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in raw_edges:
        source, target = edge.get("from_id"), edge.get("to_id")
        relation = edge.get("relation", "prerequisite_of")

        if source == target:
            repair.dropped_self += 1
            continue
        if source not in known or target not in known:
            repair.dropped_unknown += 1
            continue

        key = (source, target, relation)
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            {
                "from_id": source,
                "to_id": target,
                "relation": relation,
                "confidence": float(edge.get("confidence", 1.0)),
            }
        )

    # Break cycles in the ordering subgraph only. `contrasts_with` is legitimately
    # symmetric and must not be touched.
    while True:
        adjacency: dict[str, list[str]] = {cid: [] for cid in concept_ids}
        ordering = [e for e in edges if e["relation"] == "prerequisite_of"]
        for edge in ordering:
            adjacency[edge["from_id"]].append(edge["to_id"])

        cycle = _find_cycle(adjacency)
        if cycle is None:
            break

        pairs = set(pairwise(cycle))
        candidates = [e for e in ordering if (e["from_id"], e["to_id"]) in pairs]
        if not candidates:
            # Defensive: cycle detected but no matching edge. Drop the whole
            # ordering subgraph rather than loop forever.
            edges = [e for e in edges if e["relation"] != "prerequisite_of"]
            repair.dropped_edges.append(("*", "*"))
            break

        weakest = min(candidates, key=lambda e: e["confidence"])
        edges.remove(weakest)
        repair.dropped_edges.append((weakest["from_id"], weakest["to_id"]))

    return {"node_ids": list(concept_ids), "edges": edges}, repair
