"""Stage 9 — Validation.

Four rule classes run against the in-progress package, in a fixed order chosen
for cost rather than importance: schema, coverage, and consistency are pure
computation over the state dicts already sitting in memory, so all three run
before a single token is spent. Grounding — the one rule class that needs a
model at all, and even then only for the claims a lexical pre-filter could not
already resolve (``stages/s9_validation/grounding.py``) — runs last. A document
whose knowledge base failed schema validation gets that news for free; it does
not wait on a batch of judge calls to learn something the first rule already
knew.

The rule modules already do the substantive work — this module is the part that
was deliberately left out of them: turning four independent findings into one
``ValidationReport`` with one status. That status is not asked of a model. It is
derived, by a fixed policy, from the issue severities the rules themselves
produced: any ``error`` makes the whole package ``fail``; only ``warning``s make
it ``pass_with_warnings``; no issues at all make it ``pass``. The
``ValidationReport`` validator (``contracts.validation``) enforces the converse —
``pass`` cannot carry an issue, ``fail`` cannot carry zero errors — so this
policy is the only way to build a report that survives construction.

**The versatility property this stage exists to protect (docs/00 § H-07):** a
narrative document with no formulae and no numerical items must validate as
``pass``, not ``fail``. Nothing here special-cases that outcome — there is no
``if profile == "narrative"`` anywhere below. The profile-conditioned rules in
``coverage_rules.check_profile_requirements`` simply never ask a narrative
document for fields its own profile never required, so the STEM-shaped checks
that would otherwise flag "no formulae" are never evaluated against it. A
validator that only ever sees good input is indistinguishable from
``return "pass"``; the tests for this stage exist to tell the two apart.

Every issue this stage emits carries the ``stage`` that must regenerate to fix
it (``SECTION_OWNER``, and the claim/stage pairing ``grounding.py`` already
attaches per claim). That is what makes ``stages_to_regenerate`` — returned
alongside the report so the orchestrator's repair router can invalidate exactly
those checkpoints — derivable rather than guessed: it is the deduplicated set of
owning stages behind every ``error``-severity issue. A ``warning`` never forces
a regeneration; that is precisely the distinction that keeps a document with
one partially-supported claim from being thrown back at a stage for a full
re-run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.validation import ValidationIssue, ValidationReport
from core.llm.client import LLMClient
from pedagogy.registry import get_strategy
from stages.base import StageContext, stage_span
from stages.s9_validation.consistency_rules import check_consistency
from stages.s9_validation.coverage_rules import check_coverage, check_profile_requirements
from stages.s9_validation.grounding import check_grounding
from stages.s9_validation.issues import IssueDict
from stages.s9_validation.schema_rules import check_schema

__all__ = ["ValidationStage"]


def resolve_status(issues: list[IssueDict]) -> str:
    """The whole status policy, in one place, and cheap to audit against the
    ``ValidationReport`` validator it must never contradict.
    """
    if any(issue["severity"] == "error" for issue in issues):
        return "fail"
    if issues:
        return "pass_with_warnings"
    return "pass"


def stages_to_regenerate(issues: list[IssueDict]) -> list[str]:
    """Which stages a repair cycle must re-run — the owners of every ``error``.

    A ``warning`` (a partially-supported claim, an unmet profile expectation)
    never lands here: the report still ships, and re-running a stage over a
    warning would spend a repair attempt on something that was never going to
    block publication.
    """
    seen: list[str] = []
    for issue in issues:
        if issue["severity"] == "error" and issue["stage"] not in seen:
            seen.append(issue["stage"])
    return seen


class ValidationStage:
    """Replaces the stage-9 stub."""

    name = "validation"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            classification: dict[str, Any] = state.get("classification") or {}
            knowledge: dict[str, Any] = state.get("knowledge") or {}
            teaching_plan: dict[str, Any] = state.get("teaching_plan") or {}
            period_contents: list[dict[str, Any]] = state.get("period_contents") or []
            activities: list[dict[str, Any]] = state.get("activities") or []
            assessments: dict[str, Any] = state.get("assessments") or {}
            learning_gaps: list[dict[str, Any]] = state.get("learning_gaps") or []
            chunks: list[dict[str, Any]] = state.get("chunks") or []
            strategy = get_strategy(classification.get("pedagogy_profile", "mixed"))

            # Free first: schema, coverage, and consistency are pure computation
            # over what is already in memory. Nothing here spends a token.
            await span.progress(0.05, message="checking schema conformance")
            schema_ok, schema_issues = check_schema(
                classification=classification,
                knowledge=knowledge,
                teaching_plan=teaching_plan,
                period_contents=period_contents,
                activities=activities,
                assessments=assessments,
                learning_gaps=learning_gaps,
            )

            await span.progress(0.25, message="checking coverage")
            coverage, coverage_issues = check_coverage(
                knowledge=knowledge, teaching_plan=teaching_plan, assessments=assessments
            )
            profile_issues = check_profile_requirements(
                knowledge=knowledge, assessments=assessments, strategy=strategy
            )

            await span.progress(0.45, message="checking consistency")
            consistency, consistency_issues = check_consistency(
                knowledge=knowledge,
                teaching_plan=teaching_plan,
                period_contents=period_contents,
                activities=activities,
            )

            # Last, and the only rule class that can spend a token — and even
            # then only on the claims the lexical pre-filter left ambiguous.
            await span.progress(0.6, message="checking grounding")
            grounding_score, unsupported_claims, grounding_issues = await check_grounding(
                self._llm,
                knowledge=knowledge,
                learning_gaps=learning_gaps,
                chunks=chunks,
                stage=self.name,
            )

            issues: list[IssueDict] = [
                *schema_issues,
                *coverage_issues,
                *profile_issues,
                *consistency_issues,
                *grounding_issues,
            ]
            status = resolve_status(issues)
            regenerate = stages_to_regenerate(issues)
            if regenerate:
                span.warn(
                    f"{len(regenerate)} stage(s) flagged for targeted regeneration: "
                    f"{', '.join(regenerate)}"
                )

            report = ValidationReport(
                status=status,  # type: ignore[arg-type]
                schema_ok=schema_ok,
                coverage=coverage,
                consistency=consistency,
                grounding_score=grounding_score,
                unsupported_claims=unsupported_claims,  # type: ignore[arg-type]
                issues=[ValidationIssue.model_validate(issue) for issue in issues],
                profile_ruleset=strategy.name,
                attempts=int(state.get("validation_attempts") or 1),
                checked_at=datetime.now(UTC),
            )

            await span.progress(
                0.98,
                message=f"{status} — {len(issues)} issue(s), grounding {grounding_score:.2f}",
            )
            return {
                "validation": report.model_dump(mode="json"),
                "stages_to_regenerate": regenerate,
            }
