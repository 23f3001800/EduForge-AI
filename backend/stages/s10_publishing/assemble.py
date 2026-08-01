"""Assembling the Teacher Knowledge Package from graph state (FR-11).

Nine stages each write one narrowed key to graph state; this module is the only
place that reads them all at once, because it is the only place allowed to —
stages 1-9 stay independent of each other by never doing what this function
does. Everything here is re-validated through :class:`TeacherKnowledgePackage`
itself, so a state fragment that looks right but is not (a period referencing
a concept id no stage actually produced, say) fails here rather than shipping.

Nothing here calls a model. Publishing is pure assembly and rendering — the
package already contains every claim any stage is going to make.
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from contracts.primitives import SCHEMA_VERSION
from contracts.tkp import TeacherKnowledgePackage

__all__ = ["assemble_package"]

#: State keys without which no TKP can be built at all. `period_contents`,
#: `activities`, and `learning_gaps` are deliberately absent from this list —
#: `TeacherKnowledgePackage` allows all three to be empty lists, and a short
#: document legitimately produces no gaps (stage 8 already documents this).
_REQUIRED_STATE_KEYS = (
    "structured_document",
    "classification",
    "knowledge",
    "teaching_plan",
    "assessments",
    "validation",
)

#: Sections of the knowledge base that inherit `Grounded` and so carry at
#: least one `Evidence` span each. Keyed to the identifier field that makes a
#: useful citation pointer; `None` falls back to a positional index.
_GROUNDED_SECTIONS: tuple[tuple[str, str | None], ...] = (
    ("concepts", "concept_id"),
    ("definitions", None),
    ("formulae", None),
    ("examples", None),
    ("applications", None),
    ("misconceptions", "misconception_id"),
)


def _app_version() -> str:
    try:
        return importlib.metadata.version("eduforge")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _collect_citations(
    knowledge: dict[str, Any], gaps: list[dict[str, Any]], chunks_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten every grounded claim's evidence into the package's citation index.

    Deduped on ``(chunk_id, quote)`` — the same source span cited by five
    concepts becomes one citation with five `referenced_by` pointers rather
    than five near-identical entries a teacher would have to cross-reference
    by hand.
    """
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    def add(pointer: str, evidence: list[dict[str, Any]] | None) -> None:
        for entry in evidence or []:
            chunk_id = entry.get("chunk_id")
            quote = entry.get("quote")
            if not chunk_id or not quote:
                continue
            key = (chunk_id, quote)
            chunk = chunks_by_id.get(chunk_id) or {}
            citation = grouped.setdefault(
                key,
                {
                    "chunk_id": chunk_id,
                    "page": entry.get("page") or chunk.get("page"),
                    "section_path": chunk.get("section_path") or [],
                    "quote": quote,
                    "referenced_by": [],
                },
            )
            citation["referenced_by"].append(pointer)

    for section, id_field in _GROUNDED_SECTIONS:
        for index, item in enumerate(knowledge.get(section) or []):
            pointer_id = item.get(id_field) if id_field else index
            add(f"/knowledge/{section}/{pointer_id}", item.get("evidence"))

    for gap in gaps or []:
        add(f"/learning_gaps/{gap.get('gap_id')}", gap.get("evidence"))

    return list(grouped.values())


def assemble_package(state: dict[str, Any]) -> TeacherKnowledgePackage:
    """Build and validate the package this job produced.

    Raises ``ValueError`` naming the missing key(s) when a required stage
    output is absent — a package assembled from a still-running pipeline is a
    bug in the caller, not a case to paper over — and lets
    ``TeacherKnowledgePackage``'s own validators raise when the assembled
    state is internally inconsistent (docs/00 § H-06).
    """
    missing = [key for key in _REQUIRED_STATE_KEYS if not state.get(key)]
    if missing:
        raise ValueError(f"cannot assemble package: missing required state key(s): {missing}")

    knowledge: dict[str, Any] = state["knowledge"]
    learning_gaps: list[dict[str, Any]] = state.get("learning_gaps") or []
    chunks_by_id = {c["chunk_id"]: c for c in (state.get("chunks") or [])}

    payload = {
        "schema_version": SCHEMA_VERSION,
        "tkp_id": str(uuid4()),
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": {
            "app_version": _app_version(),
            # Per-stage model/provider and token/cost bookkeeping is not threaded
            # through `GraphState` today (no stage records it there), so this is
            # honestly empty rather than guessed from the routing config, which
            # would describe what a stage was *configured* to use, not what it
            # actually billed.
            "models_by_stage": {},
            "providers_by_stage": {},
        },
        "source": state["structured_document"]["metadata"],
        "classification": state["classification"],
        "knowledge": knowledge,
        "teaching_plan": state["teaching_plan"],
        "classroom_content": state.get("period_contents") or [],
        "activities": state.get("activities") or [],
        "assessments": state["assessments"],
        "learning_gaps": learning_gaps,
        "validation": state["validation"],
        "provenance": {
            "citations": _collect_citations(knowledge, learning_gaps, chunks_by_id),
            # Stage timings/tokens/cost have the same gap as models_by_stage
            # above: no stage writes them into state, so there is nothing
            # honest to put here beyond the zero defaults.
        },
    }
    return TeacherKnowledgePackage.model_validate(payload)
