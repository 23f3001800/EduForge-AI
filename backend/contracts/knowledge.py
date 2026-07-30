"""Stage 3 contracts — the structured educational representation.

Two design decisions are enforced here rather than left to prompt discipline:

1. **Evidence is mandatory.** Concepts, definitions, formulae, examples,
   applications, and misconceptions all inherit :class:`Grounded`, so an
   ungrounded claim cannot be constructed. This is what makes hallucination
   detection (FR-10) and citation traceability (BR-02) one subsystem.

2. **The concept graph is acyclic.** ``prerequisite_of`` edges are validated for
   cycles at construction time. Stage 4 topologically sorts this graph to order
   periods, and stage 9 checks period ordering against it — neither is meaningful
   if the graph can contain a cycle (docs/00 § H-09).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from contracts.primitives import (
    BloomLevel,
    Confidence,
    Grounded,
    Identifier,
    StrictModel,
)

__all__ = [
    "Application",
    "Concept",
    "ConceptEdge",
    "ConceptGraph",
    "ConceptImportance",
    "Definition",
    "Example",
    "Formula",
    "KnowledgeBase",
    "LearningObjective",
    "Misconception",
    "Prerequisite",
    "RelationType",
    "VariableDef",
]

ConceptImportance = Literal["core", "supporting", "enrichment"]
RelationType = Literal["prerequisite_of", "part_of", "contrasts_with"]


class Concept(Grounded):
    """One teachable idea extracted from the document."""

    concept_id: Identifier
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    importance: ConceptImportance = Field(
        description="Drives period-count derivation and time allocation in stage 4."
    )


class Definition(Grounded):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    concept_ids: list[Identifier] = Field(default_factory=list)


class VariableDef(StrictModel):
    symbol: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    unit: str | None = None


class Formula(Grounded):
    """A formula carried in both renderable and speakable form.

    ``latex`` is what the PDF renderer typesets; ``plain`` is what a teacher reads
    aloud and what search indexes. Both are required — a formula that only exists
    as LaTeX is unusable in half the output artifacts.
    """

    name: str | None = None
    latex: str = Field(min_length=1)
    plain: str = Field(min_length=1)
    variables: list[VariableDef] = Field(default_factory=list)
    concept_ids: list[Identifier] = Field(default_factory=list)


class Example(Grounded):
    title: str | None = None
    body: str = Field(min_length=1)
    concept_ids: list[Identifier] = Field(default_factory=list)


class Application(Grounded):
    """A real-world use of a concept.

    High hallucination risk: models readily invent plausible applications that the
    source never mentions. Grounded by construction for exactly that reason.
    """

    context: str = Field(min_length=1)
    description: str = Field(min_length=1)
    concept_ids: list[Identifier] = Field(default_factory=list)


class Prerequisite(StrictModel):
    """Knowledge assumed by this document but not taught within it."""

    statement: str = Field(min_length=1)
    concept_ids: list[Identifier] = Field(default_factory=list)


class LearningObjective(StrictModel):
    """An observable, assessable behaviour — not a topic label.

    "Understand photosynthesis" is not an objective. "Explain how light intensity
    affects the rate of photosynthesis" is. The Bloom level must match the verb.
    """

    objective_id: Identifier
    statement: str = Field(min_length=1)
    bloom_level: BloomLevel
    concept_ids: list[Identifier] = Field(default_factory=list)


class Misconception(Grounded):
    """A predictable student error, with its cause and its correction."""

    misconception_id: Identifier
    statement: str = Field(min_length=1, description="The incorrect belief, stated plainly.")
    why_it_happens: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    concept_ids: list[Identifier] = Field(default_factory=list)


class ConceptEdge(StrictModel):
    from_id: Identifier
    to_id: Identifier
    relation: RelationType
    confidence: Confidence = 1.0

    @model_validator(mode="after")
    def _no_self_edge(self) -> ConceptEdge:
        if self.from_id == self.to_id:
            raise ValueError(f"self-referential edge on {self.from_id!r}")
        return self


class ConceptGraph(StrictModel):
    """Concept dependency structure. The ``prerequisite_of`` subgraph must be a DAG.

    Cycle-breaking is stage 3's job (drop the lowest-confidence edge, record a
    warning). By the time a graph reaches this contract it must already be acyclic
    — this validator is the backstop that stops a cyclic graph from silently
    reaching stage 4, where it would produce an arbitrary period ordering.
    """

    node_ids: list[Identifier] = Field(default_factory=list)
    edges: list[ConceptEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edges_resolve_and_prereqs_are_acyclic(self) -> ConceptGraph:
        nodes = set(self.node_ids)
        dangling = {
            e_id
            for edge in self.edges
            for e_id in (edge.from_id, edge.to_id)
            if e_id not in nodes
        }
        if dangling:
            raise ValueError(f"edges reference unknown concept ids: {sorted(dangling)[:5]}")

        adjacency: dict[str, list[str]] = {n: [] for n in self.node_ids}
        for edge in self.edges:
            if edge.relation == "prerequisite_of":
                adjacency[edge.from_id].append(edge.to_id)

        # Iterative three-colour DFS; recursion would blow the stack on a large graph.
        WHITE, GREY, BLACK = 0, 1, 2
        colour = dict.fromkeys(adjacency, WHITE)
        for root in adjacency:
            if colour[root] != WHITE:
                continue
            stack: list[tuple[str, bool]] = [(root, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    colour[node] = BLACK
                    continue
                if colour[node] == GREY:
                    continue
                colour[node] = GREY
                stack.append((node, True))
                for nxt in adjacency[node]:
                    if colour[nxt] == GREY:
                        raise ValueError(
                            "prerequisite_of subgraph contains a cycle involving "
                            f"{node!r} -> {nxt!r}; stage 3 must break the "
                            "lowest-confidence edge before emitting the graph"
                        )
                    if colour[nxt] == WHITE:
                        stack.append((nxt, False))
        return self


class KnowledgeBase(StrictModel):
    """The complete educational representation of one document (FR-04)."""

    learning_objectives: list[LearningObjective] = Field(default_factory=list)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    formulae: list[Formula] = Field(
        default_factory=list,
        description="Legitimately empty for narrative content. Validation is "
        "conditioned on pedagogy_profile and must never require this.",
    )
    keywords: list[str] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    applications: list[Application] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    concept_graph: ConceptGraph = Field(default_factory=ConceptGraph)

    @model_validator(mode="after")
    def _concept_ids_are_unique_and_graph_matches(self) -> KnowledgeBase:
        ids = [c.concept_id for c in self.concepts]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate concept_id(s): {dupes[:5]}")

        obj_ids = [o.objective_id for o in self.learning_objectives]
        if len(obj_ids) != len(set(obj_ids)):
            dupes = sorted({i for i in obj_ids if obj_ids.count(i) > 1})
            raise ValueError(f"duplicate objective_id(s): {dupes[:5]}")

        if self.concept_graph.node_ids:
            missing = set(self.concept_graph.node_ids) - set(ids)
            if missing:
                raise ValueError(
                    f"concept_graph references concepts not in `concepts`: {sorted(missing)[:5]}"
                )
        return self
