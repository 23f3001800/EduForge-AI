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
    reports: list[dict[str, Any]] = state.get("stage_reports") or []

    payload = {
        "schema_version": SCHEMA_VERSION,
        "tkp_id": str(uuid4()),
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": {
            "app_version": _app_version(),
            # Taken from what each stage actually called, not from the routing
            # config — config describes what a stage was *configured* to use,
            # which diverges the moment a fallback fires.
            **_generator_fields(reports),
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
            **_provenance_fields(reports),
        },
    }
    return TeacherKnowledgePackage.model_validate(payload)


def _generator_fields(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Which model and provider actually produced each stage.

    Stages that make no model call (document intelligence, publishing) are
    omitted rather than listed as empty — an absent entry says "no model was
    involved", which is true and useful; an empty string says nothing.
    """
    models = {r["stage"]: r["model"] for r in reports if r.get("model")}
    providers = {r["stage"]: r["provider"] for r in reports if r.get("provider")}
    return {"models_by_stage": models, "providers_by_stage": providers}


def _provenance_fields(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-stage timings and totals, summed from what each stage reported.

    These were zero until stages started reporting usage, which made the cost of
    a package invisible to the person who ran it. A teacher deciding whether to
    regenerate a section, and an operator deciding whether the pipeline is worth
    its bill, both need this and neither could see it.
    """
    timings = [
        {
            "stage": report["stage"],
            "duration_ms": int(report.get("duration_ms") or 0),
            "tokens_in": int(report.get("tokens_in") or 0),
            "tokens_out": int(report.get("tokens_out") or 0),
            "tokens_cached": int(report.get("tokens_cached") or 0),
            "attempts": max(1, int(report.get("attempts") or 1)),
            "degraded": bool(report.get("degraded")),
        }
        for report in reports
        if report.get("stage")
    ]
    decisions = [
        {"stage": report["stage"], **decision}
        for report in reports
        for decision in (report.get("decisions") or [])
        if decision.get("what") and decision.get("because")
    ]

    return {
        "stage_timings": timings,
        "decisions": decisions,
        "total_tokens_in": sum(t["tokens_in"] for t in timings),
        "total_tokens_out": sum(t["tokens_out"] for t in timings),
        "total_cost_usd": round(sum(float(r.get("cost_usd") or 0.0) for r in reports), 6),
        "total_duration_ms": sum(t["duration_ms"] for t in timings),
    }
