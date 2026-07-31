"""Stage 2 contracts — educational classification.

The important field here is not ``subject``. It is ``pedagogy_profile``.

``subject`` is descriptive metadata a human reads. ``pedagogy_profile`` is the
routing key that selects prompt strategy, activity weighting, assessment mix, and
the active validation ruleset for every stage after this one. It exists so that no
code anywhere branches on a subject name — which is the only way a single pipeline
handles a physics chapter and a poetry chapter without one of them being a
second-class citizen (docs/00 § H-07, docs/02 § 6).
"""

from __future__ import annotations

from pydantic import Field, model_validator

from contracts.primitives import Confidence, Difficulty, PedagogyProfile, StrictModel

__all__ = [
    "Classification",
    "CurriculumAlignment",
    "CurriculumBoard",
    "StandardRef",
]

CurriculumBoard = str  # "CBSE" | "ICSE" | "CommonCore" | "IB" | "Other" — open by design


class StandardRef(StrictModel):
    """A single curriculum standard this document maps to.

    ``code`` must be a real, verifiable identifier from the named board. A model
    that cannot find a genuine match must return no alignment at all rather than
    inventing a plausible-looking code — a fabricated standard is worse than an
    absent one, because it looks authoritative (docs/10 § M3).
    """

    code: str = Field(min_length=1, description="Official standard code, verbatim.")
    description: str = Field(min_length=1)
    confidence: Confidence


class CurriculumAlignment(StrictModel):
    """Optional mapping to a named curriculum board (BR-03)."""

    board: CurriculumBoard
    mapped_standards: list[StandardRef] = Field(default_factory=list)
    confidence: Confidence


class Classification(StrictModel):
    """What kind of teaching material this document is."""

    subject: str = Field(min_length=1, description='e.g. "Physics", "History".')
    grade_band: str = Field(min_length=1, description='e.g. "9-10", "UG-1".')
    difficulty: Difficulty
    topic: str = Field(min_length=1)
    chapter: str | None = None
    category: str = Field(
        min_length=1,
        description='Document shape, e.g. "textbook_chapter", "research_paper", '
        '"lecture_notes", "handout".',
    )
    language: str = Field(min_length=2, description="BCP-47 tag of the source content.")

    pedagogy_profile: PedagogyProfile = Field(
        description="Routing key for all downstream prompt, activity, assessment, "
        "and validation strategy. Never branch on `subject` instead."
    )

    curriculum_alignment: CurriculumAlignment | None = Field(
        default=None,
        description="Present only when a genuine standard match was found. "
        "Absent is a valid, honest answer.",
    )

    confidences: dict[str, Confidence] = Field(
        default_factory=dict,
        description="Per-field confidence, keyed by field name.",
    )
    low_confidence_fields: list[str] = Field(
        default_factory=list,
        description="Fields scoring below 0.5. Surfaced in the UI rather than "
        "silently propagated into six downstream stages.",
    )

    @model_validator(mode="after")
    def _derive_low_confidence_fields(self) -> Classification:
        """Recompute rather than reject.

        This field is fully derivable from ``confidences``, so demanding the model
        compute it correctly buys nothing and costs a repair attempt every time it
        slips — which was happening on real runs. Deriving it here guarantees the
        invariant the UI depends on (low-confidence fields are surfaced, never
        silently propagated) without spending a round trip to enforce it.
        """
        derived = sorted(k for k, v in self.confidences.items() if v < 0.5)
        if sorted(self.low_confidence_fields) != derived:
            object.__setattr__(self, "low_confidence_fields", derived)
        return self
