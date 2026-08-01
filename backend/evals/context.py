"""The read-only view of one package that every metric shares.

Metrics operate on the serialised package (``model_dump(mode="json")``), not on
contract models. That is the same choice the deterministic halves of stages 7 and
8 make, and for the same reason: the harness must be able to score a published
``package.json`` off disk — including one written by an older schema version —
without first satisfying every validator in the contract. A package that no longer
constructs is exactly the package a reviewer most wants a score for.

The context also carries the two things every metric would otherwise recompute:
the profile's expectations, and the package's own teaching vocabulary, which is
what the specificity checks probe against.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from evals.expectations import Expectations, resolve
from evals.text import build_vocabulary
from evals.types import Judgements

__all__ = ["EvalContext", "build_context"]


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, Mapping)]


@dataclass(frozen=True, slots=True)
class EvalContext:
    """One package, plus everything needed to judge it fairly."""

    package: Mapping[str, Any]
    chunks: Mapping[str, str]
    expectations: Expectations
    vocabulary: frozenset[str]
    judgements: Judgements

    # ------------------------------------------------------------- accessors

    @property
    def classification(self) -> Mapping[str, Any]:
        return _as_mapping(self.package.get("classification"))

    @property
    def profile(self) -> str:
        return self.expectations.profile

    @property
    def grade_band(self) -> str:
        return str(self.classification.get("grade_band") or "")

    @property
    def knowledge(self) -> Mapping[str, Any]:
        return _as_mapping(self.package.get("knowledge"))

    @property
    def concepts(self) -> list[Mapping[str, Any]]:
        return _as_list(self.knowledge.get("concepts"))

    @property
    def objectives(self) -> list[Mapping[str, Any]]:
        return _as_list(self.knowledge.get("learning_objectives"))

    @property
    def misconceptions(self) -> list[Mapping[str, Any]]:
        return _as_list(self.knowledge.get("misconceptions"))

    @property
    def concept_graph(self) -> Mapping[str, Any]:
        return _as_mapping(self.knowledge.get("concept_graph"))

    @property
    def plan(self) -> Mapping[str, Any]:
        return _as_mapping(self.package.get("teaching_plan"))

    @property
    def periods(self) -> list[Mapping[str, Any]]:
        return _as_list(self.plan.get("periods"))

    @property
    def period_minutes(self) -> int:
        return int(self.plan.get("period_duration_minutes") or 0)

    @property
    def classroom_content(self) -> list[Mapping[str, Any]]:
        return _as_list(self.package.get("classroom_content"))

    @property
    def activities(self) -> list[Mapping[str, Any]]:
        return _as_list(self.package.get("activities"))

    @property
    def assessments(self) -> Mapping[str, Any]:
        return _as_mapping(self.package.get("assessments"))

    @property
    def items(self) -> list[Mapping[str, Any]]:
        return _as_list(self.assessments.get("items"))

    @property
    def blueprint(self) -> Mapping[str, Any]:
        return _as_mapping(self.assessments.get("blueprint"))

    @property
    def learning_gaps(self) -> list[Mapping[str, Any]]:
        return _as_list(self.package.get("learning_gaps"))

    @property
    def concept_ids(self) -> set[str]:
        return {str(c.get("concept_id")) for c in self.concepts if c.get("concept_id")}

    def concept_name(self, concept_id: str) -> str:
        for concept in self.concepts:
            if str(concept.get("concept_id")) == concept_id:
                return str(concept.get("name") or concept_id)
        return concept_id

    def period_of_concept(self) -> dict[str, int]:
        """concept_id -> the period that teaches it. Empty for untaught concepts."""
        mapping: dict[str, int] = {}
        for period in self.periods:
            number = int(period.get("period_no") or 0)
            for cid in period.get("concept_ids") or []:
                mapping.setdefault(str(cid), number)
        return mapping


def build_context(
    package: Mapping[str, Any],
    *,
    chunks: Sequence[Mapping[str, Any]] | None = None,
    judgements: Judgements | None = None,
) -> EvalContext:
    """Assemble the context, resolving the profile through the pedagogy registry."""
    classification = _as_mapping(package.get("classification"))
    profile = str(classification.get("pedagogy_profile") or "mixed")

    corpus = {
        str(chunk.get("chunk_id")): str(chunk.get("text") or "")
        for chunk in _as_list(chunks or [])
        if chunk.get("chunk_id")
    }

    return EvalContext(
        package=package,
        chunks=corpus,
        expectations=resolve(profile),
        vocabulary=build_vocabulary(package),
        judgements=judgements or Judgements(),
    )
