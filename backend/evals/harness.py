"""Run the rubric over one package.

``evaluate`` is pure and deterministic: same package in, same numbers out, no
network, no model, no clock. That is not a limitation, it is the design. Free and
reproducible metrics can be run on every commit, cannot flatter the system, and do
not quietly change their mind when a provider updates a checkpoint.

**On ``EVAL_PROFILE``.** ``core.llm.router`` declares that quality evaluation runs
under the ``production`` profile, because tuning against one model and shipping
another produces scores that do not transfer. This module honours that in the
place where it actually bites:

* Anything the *judge* touches is gated hard — :func:`require_eval_profile` raises
  under any other profile, and the judge is the only part of the harness whose
  numbers depend on which model answered.
* The deterministic pass is not gated, because refusing to count MCQ options
  unless an API key is present would be theatre. Instead every report records the
  profile it was produced under and exposes ``transferable``, so a judged score
  from the wrong profile can never be quietly compared against a real one.

``absent_by_design`` is the other thing this module owes a reviewer. A narrative
package has no formulae and no numerical items; that is the designed output of its
profile, and the report says so in words rather than leaving a reader to wonder
whether something failed silently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.llm.router import EVAL_PROFILE
from evals.context import EvalContext, build_context
from evals.dimensions import run_all
from evals.types import EvalReport, Judgements

__all__ = ["EvalProfileError", "current_profile", "evaluate", "require_eval_profile"]


class EvalProfileError(RuntimeError):
    """Raised when a judged evaluation is attempted outside ``EVAL_PROFILE``."""


def current_profile() -> str:
    """The LLM profile this process is running under, without importing settings
    eagerly at module scope — the harness must import cleanly with no credentials.
    """
    try:
        from core.config import get_settings

        return str(get_settings().llm_profile)
    except Exception:  # pragma: no cover - a missing credential is not an eval failure
        return "unknown"


def require_eval_profile() -> None:
    """Refuse to produce a judged score outside the profile it would transfer from."""
    profile = current_profile()
    if profile != EVAL_PROFILE:
        raise EvalProfileError(
            f"the LLM judge runs only under LLM_PROFILE={EVAL_PROFILE!r} (currently "
            f"{profile!r}). Scores tuned against one model and shipped on another do "
            "not transfer, so a judged run here would produce numbers that mislead. "
            "Run the deterministic pass instead — it is profile-independent by "
            "construction."
        )


def _absent_by_design(ctx: EvalContext) -> tuple[str, ...]:
    """State plainly what this profile does *not* owe, and does not have.

    Absent content is often correct content. Saying so is part of the review: a
    reader who sees "formulae: 0" with no comment reasonably assumes something
    broke.
    """
    expects = ctx.expectations
    notes: list[str] = []
    required = set(expects.required_knowledge_fields)

    for field in ("formulae", "examples", "applications", "definitions", "misconceptions"):
        if not ctx.knowledge.get(field) and field not in required:
            notes.append(
                f"knowledge.{field}: empty, and the {expects.profile} profile does not "
                f"require it — this is a pass, not a gap"
            )

    kinds = {str(item.get("kind")) for item in ctx.items}
    for kind in sorted(expects.unexpected_item_kinds):
        if kind not in kinds:
            notes.append(
                f"assessments: no {kind!r} items, which is what the {expects.profile} "
                f"profile designs for — their absence is scored as correct"
            )

    if not any(a.get("materials") for a in ctx.activities):
        notes.append(
            "activities: no materials listed; an activity that needs nothing is "
            "runnable everywhere and is not penalised"
        )

    if any(not gap.get("evidence") for gap in ctx.learning_gaps):
        notes.append(
            "learning_gaps: some gaps carry no evidence, which is correct for a "
            "predicted gap — the document rarely names the errors students make on "
            "its own hardest ideas"
        )

    return tuple(notes)


def evaluate(
    package: Mapping[str, Any] | Any,
    *,
    chunks: Sequence[Mapping[str, Any]] | None = None,
    judgements: Judgements | None = None,
) -> EvalReport:
    """Score one package against the rubric.

    ``package`` may be a :class:`contracts.TeacherKnowledgePackage` or the plain
    mapping it dumps to. Accepting the mapping is deliberate — a published
    ``package.json`` that no longer satisfies the current contract is exactly the
    package a reviewer most wants a score for.

    ``chunks`` are the source chunks the package was generated from. Without them
    the grounding dimension reports itself inapplicable rather than scoring zero.
    """
    payload = package.model_dump(mode="json") if hasattr(package, "model_dump") else package
    if not isinstance(payload, Mapping):
        raise TypeError(f"expected a package mapping or model, got {type(package).__name__}")

    if judgements is not None and judgements:
        require_eval_profile()

    ctx = build_context(payload, chunks=chunks, judgements=judgements)
    dimensions = run_all(ctx)

    classification = ctx.classification
    return EvalReport(
        package_id=str(payload.get("tkp_id") or "unknown"),
        profile=ctx.profile,
        subject=str(classification.get("subject") or "unknown"),
        grade_band=ctx.grade_band,
        dimensions=dimensions,
        absent_by_design=_absent_by_design(ctx),
        llm_profile=current_profile(),
        judged=bool(judgements),
    )
