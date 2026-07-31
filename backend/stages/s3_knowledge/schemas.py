"""Intermediate extraction schemas — two halves of one ``KnowledgeBase``.

Asking for the whole of ``KnowledgeBase`` in one call does not work on a small
model. Measured against ``openai/gpt-oss-20b`` at 4000 max_tokens the call fails
with ``json_validate_failed`` and an **empty** ``failed_generation``: the model
never produces the object at all. The strict schema alone is ~2.7k tokens of
prompt, and the object it demands — nine lists, each item carrying nested
evidence, plus the graph — does not fit in what is left for output. Meanwhile the
small-schema classification call on the same model succeeds every time.

So the size of the schema is the failure, and the fix is to ask for less per
call. Extraction runs as two sequential calls whose results merge back into one
``KnowledgeBase``:

* :class:`CoreKnowledge` — what the document *is about*: concepts, definitions,
  formulae, keywords.
* :class:`PedagogicalKnowledge` — what a teacher *does with it*: objectives,
  prerequisites, examples, applications, misconceptions, and the graph edges.

The second call depends on the first: edges and ``concept_ids`` are only
meaningful against real concept ids, so the roster from call one is passed into
call two's prompt.

These models are local on purpose. They are a transport detail of one stage — how
much we dare ask for at a time on a given model — not vocabulary the rest of the
system shares. ``contracts/`` stays the single description of what a knowledge
base *is*; nothing downstream learns that extraction takes two calls.

The item types themselves are the contract types, unchanged. That is what makes
merging a concatenation rather than a translation, and it keeps the evidence
requirement (``Grounded.evidence`` has ``min_length=1``) enforced at parse time
in exactly the place it was before.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from contracts.knowledge import (
    Application,
    Concept,
    Definition,
    Example,
    Formula,
    LearningObjective,
    Misconception,
    Prerequisite,
    RelationType,
)
from contracts.primitives import Confidence, StrictModel

__all__ = [
    "ConceptEdgeDraft",
    "CoreKnowledge",
    "PedagogicalKnowledge",
    "merge_pair",
]

_RELATIONS: frozenset[str] = frozenset(("prerequisite_of", "part_of", "contrasts_with"))


class ConceptEdgeDraft(StrictModel):
    """One proposed dependency, before the graph is repaired.

    Deliberately *not* ``contracts.knowledge.ConceptEdge``. That model rejects
    self-edges and unresolvable ids at construction, which is right for the
    published contract and wrong here: a single bad edge would fail the whole
    parse and cost the entire pedagogical half of the extraction. Cycles,
    self-edges, and references to concepts that citation verification dropped are
    all *expected* model output, and ``concept_graph.build_concept_graph`` already
    knows how to repair each of them. This type only has to survive the trip.
    """

    from_id: str = ""
    to_id: str = ""
    relation: RelationType = "prerequisite_of"
    confidence: Confidence = 1.0

    @field_validator("relation", mode="before")
    @classmethod
    def _known_relation(cls, value: Any) -> Any:
        """Coerce an invented relation to the one that carries ordering.

        Models reach for `requires`, `depends_on`, `leads_to`. Rejecting the edge
        would discard a real dependency over a vocabulary slip; the graph builder
        drops it later if it turns out to be spurious.
        """
        if isinstance(value, str) and value not in _RELATIONS:
            return "prerequisite_of"
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> Any:
        """A 1.5 or a -0.2 is a scale slip, not a reason to lose the edge."""
        if isinstance(value, int | float) and not isinstance(value, bool):
            return min(1.0, max(0.0, float(value)))
        return value


class CoreKnowledge(StrictModel):
    """Call 1 — the factual backbone. What this document is about."""

    concepts: list[Concept] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    formulae: list[Formula] = Field(
        default_factory=list,
        description="Legitimately empty for narrative content.",
    )
    keywords: list[str] = Field(default_factory=list)


class PedagogicalKnowledge(StrictModel):
    """Call 2 — what a teacher does with it. Needs call 1's concept ids."""

    learning_objectives: list[LearningObjective] = Field(default_factory=list)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    applications: list[Application] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    concept_edges: list[ConceptEdgeDraft] = Field(
        default_factory=list,
        description="Proposed dependencies between the concepts from call 1.",
    )


def merge_pair(core: CoreKnowledge, pedagogy: PedagogicalKnowledge) -> dict[str, Any]:
    """Recombine the two halves into one ``KnowledgeBase``-shaped payload.

    Neither half is required to have succeeded. A degraded call yields its model's
    empty instance, so a weak core call costs the concepts and keeps the
    objectives, and a weak pedagogical call costs the objectives and keeps the
    concepts. Losing both halves because one failed is the outcome this whole
    split exists to avoid.

    Edges are handed on as raw drafts under ``concept_graph``; validation and
    cycle repair stay where they were, in ``concept_graph.build_concept_graph``.
    """
    core_payload = core.model_dump(mode="json")
    pedagogy_payload = pedagogy.model_dump(mode="json")
    edges = pedagogy_payload.pop("concept_edges", []) or []

    payload: dict[str, Any] = {**core_payload, **pedagogy_payload}
    payload["concept_graph"] = {
        "node_ids": [c["concept_id"] for c in core_payload.get("concepts") or []],
        "edges": edges,
    }
    return payload
