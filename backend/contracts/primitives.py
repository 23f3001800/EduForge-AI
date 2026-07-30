"""Shared primitives for every EduForge contract.

This is the root of the contract package. It imports nothing else in the project,
and everything else in `contracts/` builds on it.

The two ideas that matter here:

* :class:`StrictModel` forbids unknown fields. A stage that invents a field gets a
  loud failure instead of silently dropping data that a later stage expected.
* :class:`Grounded` makes source traceability a *type-level* requirement rather than
  a convention. An extracted claim without evidence cannot be constructed at all,
  which is what makes hallucination detection (FR-10) and RAG traceability (BR-02)
  the same subsystem instead of two half-built ones. See docs/00 § H-06.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SCHEMA_VERSION",
    "STAGE_NAMES",
    "BloomLevel",
    "Confidence",
    "Difficulty",
    "Evidence",
    "Grounded",
    "Identifier",
    "PedagogyProfile",
    "Severity",
    "StageName",
    "StrictModel",
]

#: Semver for the published TKP JSON Schema. Patch = docs only, minor = additive
#: optional fields, major = breaking. Packages record what they were built against.
SCHEMA_VERSION = "1.0.0"


class StrictModel(BaseModel):
    """Base for every contract model.

    ``extra="forbid"`` is deliberate: when a model returns a field we did not ask
    for, we want to know at the boundary rather than discover it missing three
    stages later.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


# --------------------------------------------------------------------- scalars

#: A probability-like score. Used for classification confidence, edge confidence,
#: and grounding strength.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

#: Stable within-package identifier, e.g. ``concept_photosynthesis``, ``period_1``.
#: Deliberately permissive on shape but not on emptiness — an empty id silently
#: breaks every cross-reference check in stage 9.
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][\w.-]*$")]

BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]

Difficulty = Literal["foundational", "intermediate", "advanced"]

Severity = Literal["low", "medium", "high"]

#: Selects prompt strategy, activity weighting, assessment mix, *and* the active
#: validation ruleset. This single value is the mechanism behind NFR-01 (subject
#: versatility) — see docs/02 § 6. No stage may branch on a subject name; it
#: branches on this instead.
PedagogyProfile = Literal["quantitative", "conceptual", "narrative", "procedural", "mixed"]

#: Canonical stage identifiers. These strings are the contract for three separate
#: things and must not drift between them: the ``stage`` field of every progress
#: event (FR-14), the ``stage`` key of a checkpoint row, and the ``stage`` owner
#: recorded on a validation issue so the repair router knows who to re-run.
StageName = Literal[
    "document-intelligence",
    "educational-classification",
    "knowledge-extraction",
    "teaching-planner",
    "lesson-generation",
    "activity-generation",
    "assessment-generation",
    "gap-analysis",
    "validation",
    "publishing",
]

STAGE_NAMES: tuple[StageName, ...] = (
    "document-intelligence",
    "educational-classification",
    "knowledge-extraction",
    "teaching-planner",
    "lesson-generation",
    "activity-generation",
    "assessment-generation",
    "gap-analysis",
    "validation",
    "publishing",
)


# -------------------------------------------------------------------- evidence


class Evidence(StrictModel):
    """A pointer back into the source document supporting one generated claim.

    ``quote`` is verbatim source text, not a paraphrase — stage 9 verifies the
    claim against exactly these characters, so a paraphrase defeats the check.
    """

    chunk_id: Identifier = Field(
        description="Chunk this claim was drawn from. Must resolve to a real chunk."
    )
    page: int | None = Field(default=None, ge=1, description="1-indexed source page, when known.")
    quote: str = Field(
        min_length=8,
        max_length=600,
        description="Verbatim span from the source that supports the claim.",
    )
    confidence: Confidence = 1.0


class Grounded(StrictModel):
    """Mixin for anything that must be traceable to the source document.

    ``min_length=1`` is the load-bearing constraint of the whole design: an
    ungrounded claim is not merely discouraged, it is unconstructable. Stage 3
    drops items that arrive without evidence rather than passing them downstream.

    Deliberately *not* grounded: ``MentorMoment``, which is a motivational anecdote
    permitted to draw on general knowledge and is flagged so validation does not
    penalise it (docs/01 § SRS-5.2).
    """

    evidence: list[Evidence] = Field(
        min_length=1,
        description="At least one supporting span from the source document.",
    )
