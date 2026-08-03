"""Period integrity — does each period's content belong to that period?

The plan says period 2 teaches Newton's Second Law. The classroom content for
period 2 opens with period 1's entry ticket about inertia, checks period 1's
concept at the mid-lesson checkpoint, puts period 1's bullets on the board, and
sets period 1's homework. Every field is populated, every id resolves, the
schema is satisfied, and the period checks an objective it was not aimed at.

This was observed in a shipped sample, and under the rubric as it stood it cost
1.2% of the total score — entirely through a single ``distinct_periods`` ratio
that would have moved the same amount if the two periods had merely rhymed. The
failure is not "these periods look similar". It is "this period assesses
something it did not teach", which is a set-membership question with a definite
answer.

Four checks, all membership tests against the period's own ``concept_ids`` and
``objective_ids`` as declared in the teaching plan:

* **Checkpoints** must probe a concept this period teaches. A checkpoint on
  another period's concept tells the teacher nothing about the lesson just given.
* **The exit ticket and the board notes** must name this period's material. These
  are the artefacts the class leaves with; when they belong to a different period
  the class copies down the wrong lesson.
* **Activities** referenced by the period must carry at least one of its concepts.
* **Verbatim reuse** across periods, which is what makes all of the above happen
  at once — a period that is a copy of another period is not a period.

Absence is handled the way it should be: a period with no checkpoint questions
has no misaimed checkpoints, and that check drops to weight zero for that period
rather than scoring a free 1.0 or a punitive 0.0. What is *never* excused is a
populated field that points somewhere else.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from evals.context import EvalContext, coerce_int
from evals.discrimination import content_words
from evals.text import jaccard
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "period_integrity"
LABEL = "Period integrity"
WEIGHT = 0.05
METHOD = "deterministic"

#: Above this token overlap, two periods' student-facing artefacts are the same
#: artefacts. Set at the same level as ``evals.text.NEAR_DUPLICATE`` deliberately:
#: this measures duplication, and duplication has one threshold in this codebase.
DUPLICATE_PERIOD = 0.85


def _distinguishing_terms(ctx: EvalContext) -> dict[str, frozenset[str]]:
    """concept_id -> the terms that identify *this* concept and no other.

    Two design points, both load-bearing.

    Names alone are not enough. The natural referent for "Newton's Second Law" in
    an exit ticket is "acceleration" and "net force", not the eponym, so the
    summary is folded in — otherwise a perfectly aimed exit ticket reads as
    off-period because it declined to name a person.

    Shared terms are then subtracted. If "force" appears in three concepts'
    summaries, an artefact naming "force" says nothing about which period it
    belongs to, and counting it would let one vocabulary satisfy every period —
    which is precisely the duplication this dimension exists to detect.
    """
    per_concept: dict[str, set[str]] = {}
    for concept in ctx.concepts:
        cid = str(concept.get("concept_id") or "")
        if not cid:
            continue
        text = f"{concept.get('name') or ''} {concept.get('summary') or ''}"
        per_concept[cid] = content_words(text)

    counts: Counter[str] = Counter()
    for terms in per_concept.values():
        counts.update(terms)

    return {
        cid: frozenset(t for t in terms if counts[t] == 1) or frozenset(terms)
        for cid, terms in per_concept.items()
    }


def _vocabulary_of(distinguishing: Mapping[str, frozenset[str]], ids: set[str]) -> frozenset[str]:
    if not ids:
        return frozenset()
    return frozenset().union(*(distinguishing.get(cid, frozenset()) for cid in ids))


def _names_any(text: str, terms: frozenset[str]) -> bool:
    """Does this text name any of these terms?

    Both sides go through :func:`content_words`, so the comparison is stemmed on
    both sides and "momentum"/"momentums" and "unit"/"units" are the same term.
    An empty term set answers ``True``: a concept whose every word is shared with
    another concept gives this check nothing to work with, and inventing a
    failure from that would be the harness blaming the package for its own blind
    spot.
    """
    if not terms:
        return True
    return bool(content_words(text) & terms)


def _period_signature(content: Mapping[str, Any]) -> str:
    """What a class would actually experience of this period, as one string."""
    board = content.get("blackboard_notes") or {}
    return " ".join(
        [
            str((content.get("entry_ticket") or {}).get("prompt") or ""),
            str((content.get("exit_ticket") or {}).get("prompt") or ""),
            str((content.get("exit_ticket") or {}).get("success_indicator") or ""),
            " ".join(str(b) for b in (board.get("bullet_points") or [])),
            " ".join(str(h) for h in (board.get("headings") or [])),
            " ".join(str(t) for t in ((content.get("homework") or {}).get("tasks") or [])),
            " ".join(
                str(q.get("question") or "") for q in (content.get("checkpoint_questions") or [])
            ),
        ]
    )


def score(ctx: EvalContext) -> DimensionScore:
    periods = ctx.periods
    content = ctx.classroom_content

    if not periods or not content:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            applicable=False,
            reason=(
                "period integrity compares planned periods against the content written "
                "for them; this package has "
                + ("no plan" if not periods else "no classroom content")
            ),
        )

    findings: list[Finding] = []
    concepts_by_period = {
        coerce_int(p.get("period_no")): {str(c) for c in (p.get("concept_ids") or [])}
        for p in periods
    }
    distinguishing = _distinguishing_terms(ctx)

    checkpoint_scores: list[float] = []
    artefact_scores: list[float] = []
    activity_scores: list[float] = []

    for index, block in enumerate(content):
        number = coerce_int(block.get("period_no"))
        path = f"/classroom_content/{index}"
        own = concepts_by_period.get(number, set())
        if not own:
            findings.append(
                Finding(
                    "PER_UNPLANNED_CONTENT",
                    path,
                    f"content exists for period {number} but the plan assigns that period "
                    "no concepts; there is no objective this content can be checked against",
                )
            )
            checkpoint_scores.append(0.0)
            artefact_scores.append(0.0)
            continue

        own_vocabulary = _vocabulary_of(distinguishing, own)

        # --- checkpoints probe this period's concepts --------------------------
        questions = list(block.get("checkpoint_questions") or [])
        if questions:
            aimed = []
            for offset, question in enumerate(questions):
                ids = {str(c) for c in (question.get("concept_ids") or [])}
                on_target = (
                    bool(ids & own)
                    if ids
                    else _names_any(str(question.get("question") or ""), own_vocabulary)
                )
                aimed.append(1.0 if on_target else 0.0)
                if not on_target:
                    elsewhere = sorted(n for n, ids_ in concepts_by_period.items() if ids & ids_)
                    findings.append(
                        Finding(
                            "PER_CHECKPOINT_OFF_PERIOD",
                            f"{path}/checkpoint_questions/{offset}",
                            f"period {number} checks "
                            + (
                                f"a concept belonging to period {elsewhere[0]}"
                                if elsewhere
                                else "a concept this period does not teach"
                            )
                            + "; the check reports on a lesson the class has not just had",
                        )
                    )
            checkpoint_scores.append(mean(aimed))

        # --- exit ticket and board notes name this period's material -----------
        board = block.get("blackboard_notes") or {}
        exit_ticket = block.get("exit_ticket") or {}
        artefacts = {
            "exit ticket": " ".join(
                [
                    str(exit_ticket.get("prompt") or ""),
                    str(exit_ticket.get("success_indicator") or ""),
                ]
            ),
            "board notes": " ".join(
                [
                    *(str(h) for h in (board.get("headings") or [])),
                    *(str(b) for b in (board.get("bullet_points") or [])),
                ]
            ),
        }
        for name, text in artefacts.items():
            if not text.strip():
                continue  # absence is a classroom-readiness finding, not a fidelity one
            on_target = _names_any(text, own_vocabulary)
            artefact_scores.append(1.0 if on_target else 0.0)
            if not on_target:
                findings.append(
                    Finding(
                        "PER_ARTEFACT_OFF_PERIOD",
                        f"{path}/{'exit_ticket' if name == 'exit ticket' else 'blackboard_notes'}",
                        f"period {number}'s {name} names none of the concepts that period "
                        f"teaches ({', '.join(sorted(ctx.concept_name(c) for c in own))}); "
                        "what the class copies down is not what the period was for",
                    )
                )

        # --- referenced activities belong to this period -----------------------
        refs = {str(r) for r in (block.get("activity_refs") or [])}
        for ref in sorted(refs):
            activity = next(
                (a for a in ctx.activities if str(a.get("activity_id")) == ref),
                None,
            )
            if activity is None:
                continue  # a dangling ref is stage 5's defect and is scored there
            ids = {str(c) for c in (activity.get("concept_ids") or [])}
            on_target = bool(ids & own) if ids else True
            activity_scores.append(1.0 if on_target else 0.0)
            if not on_target:
                findings.append(
                    Finding(
                        "PER_ACTIVITY_OFF_PERIOD",
                        f"{path}/activity_refs",
                        f"period {number} runs activity {ref!r}, which practises a concept "
                        "this period does not teach",
                    )
                )

    # --- periods are not copies of each other ---------------------------------
    signatures = [_period_signature(block) for block in content]
    duplicated: list[tuple[int, int]] = []
    for i, left in enumerate(signatures):
        for j, right in enumerate(signatures[i + 1 :], start=i + 1):
            if left.strip() and jaccard(left, right) >= DUPLICATE_PERIOD:
                duplicated.append((i, j))
    pair_count = len(signatures) * (len(signatures) - 1) // 2
    uniqueness = 1.0 - (len(duplicated) / pair_count) if pair_count else 1.0
    for i, j in duplicated[:5]:
        findings.append(
            Finding(
                "PER_DUPLICATED",
                f"/classroom_content/{j}",
                f"period {content[j].get('period_no')} reuses period "
                f"{content[i].get('period_no')}'s tickets, board notes, homework and "
                "checkpoints verbatim; whichever objective the second period was aimed at, "
                "it is not the one this content checks",
            )
        )

    metrics = (
        Metric(
            "checkpoints_on_period",
            mean(checkpoint_scores),
            0.30 if checkpoint_scores else 0.0,
            f"{len(checkpoint_scores)} period(s) with checkpoints"
            if checkpoint_scores
            else "no checkpoint questions anywhere; not scored here",
        ),
        Metric(
            "artefacts_on_period",
            mean(artefact_scores),
            0.30 if artefact_scores else 0.0,
            f"{len(artefact_scores)} exit ticket(s) and board note block(s) checked "
            "against their own period's concepts"
            if artefact_scores
            else "no exit tickets or board notes; not scored here",
        ),
        Metric(
            "activities_on_period",
            mean(activity_scores),
            0.15 if activity_scores else 0.0,
            f"{len(activity_scores)} referenced activity(ies) practise their period's concepts"
            if activity_scores
            else "no activity references; not scored here",
        ),
        Metric(
            "periods_are_not_copies",
            uniqueness,
            0.25,
            f"{len(duplicated)} duplicated pair(s) across {len(signatures)} period(s)",
        ),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
