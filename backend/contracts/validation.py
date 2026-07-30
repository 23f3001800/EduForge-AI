"""Stage 9 contracts — the validation report.

Every issue carries the ``stage`` that owns it. That single field is what turns
validation from a report into a repair loop: the orchestrator collects the owning
stages of the errors, invalidates only those checkpoints, and re-enters the graph
at the earliest one (docs/03 § 4.5). Without it, a failure means re-running
everything or nothing.

The status ladder is deliberately three-valued. ``fail`` after two repair attempts
still publishes, as ``pass_with_warnings`` with the issue list attached — throwing
away ten minutes of successful pipeline work because one check tripped serves
nobody.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from contracts.primitives import Confidence, Identifier, StageName, StrictModel

__all__ = [
    "ConsistencyReport",
    "CoverageReport",
    "IssueSeverity",
    "UnsupportedClaim",
    "ValidationIssue",
    "ValidationReport",
    "ValidationStatus",
]

ValidationStatus = Literal["pass", "pass_with_warnings", "fail"]
IssueSeverity = Literal["error", "warning", "info"]


class ValidationIssue(StrictModel):
    code: str = Field(
        min_length=1,
        description='Stable machine code, e.g. "COVERAGE_CONCEPT_UNTAUGHT". Stable '
        "so the UI and the eval harness can group issues across runs.",
    )
    severity: IssueSeverity
    message: str = Field(min_length=1)
    path: str = Field(
        min_length=1, description="JSON pointer into the TKP, e.g. /knowledge/applications/2."
    )
    stage: StageName = Field(
        description="Which stage must regenerate to fix this. Drives the repair router."
    )


class CoverageReport(StrictModel):
    """Did the package actually teach and assess what it extracted?"""

    concepts_total: int = Field(default=0, ge=0)
    concepts_taught: int = Field(default=0, ge=0)
    objectives_total: int = Field(default=0, ge=0)
    objectives_planned: int = Field(default=0, ge=0)
    objectives_assessed: int = Field(default=0, ge=0)
    untaught_concept_ids: list[Identifier] = Field(default_factory=list)
    unassessed_objective_ids: list[Identifier] = Field(default_factory=list)


class ConsistencyReport(StrictModel):
    """Is the package internally coherent across periods?"""

    duplicate_concept_ids: list[Identifier] = Field(default_factory=list)
    prerequisite_violations: list[str] = Field(
        default_factory=list,
        description='Human-readable, e.g. "concept_force taught in period 3 but its '
        'prerequisite concept_mass is taught in period 4".',
    )
    dangling_activity_refs: list[Identifier] = Field(default_factory=list)
    timing_ok: bool = True


class UnsupportedClaim(StrictModel):
    """A generated claim its own cited span does not support."""

    path: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    cited_chunk_id: Identifier | None = None
    reason: str = Field(min_length=1)
    judge_confidence: Confidence = 1.0


class ValidationReport(StrictModel):
    status: ValidationStatus
    schema_ok: bool
    coverage: CoverageReport = Field(default_factory=CoverageReport)
    consistency: ConsistencyReport = Field(default_factory=ConsistencyReport)
    grounding_score: Confidence = Field(
        default=1.0,
        description="Share of groundable claims their cited spans support. Reported "
        "even on a pass — a silent 1.0 and a measured 1.0 are different facts.",
    )
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    profile_ruleset: str = Field(
        default="mixed",
        description="Which pedagogy-profile ruleset ran. Recorded so a reviewer can "
        "see that a narrative document was not judged against STEM expectations.",
    )
    attempts: int = Field(default=1, ge=1)
    checked_at: datetime

    @model_validator(mode="after")
    def _status_matches_issues(self) -> ValidationReport:
        has_error = any(i.severity == "error" for i in self.issues)
        has_warning = any(i.severity == "warning" for i in self.issues)

        if self.status == "pass" and (has_error or has_warning):
            raise ValueError("status 'pass' cannot carry error or warning issues")
        if self.status == "pass_with_warnings" and not (has_error or has_warning):
            raise ValueError("status 'pass_with_warnings' requires at least one issue")
        if self.status == "fail" and not has_error:
            raise ValueError("status 'fail' requires at least one error-severity issue")
        if not self.schema_ok and self.status == "pass":
            raise ValueError("schema_ok=False is incompatible with status 'pass'")
        return self
