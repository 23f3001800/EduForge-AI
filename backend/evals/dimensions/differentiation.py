"""Differentiation — present is not the same as useful.

``Activity.differentiation`` is a required field, so *presence* is guaranteed by
the contract and measuring it would score every package 1.0. What is not
guaranteed, and what decides whether a teacher uses it, is specificity:

    support: "Provide extra support to students who need it."
    support: "Give the rearranged form a = F/m at the top of the sheet."

Both satisfy the schema. One of them is a teacher's next move. The discriminator
used here is subject-agnostic and needs no model: does the text name something
*this package teaches*, or a number, or a literal the teacher can hand over? Advice
that could be pasted into any lesson on any topic never does.

Three further checks:

* **Support and extension must differ.** A pair where both sides say the same thing
  is one instruction split across two fields.
* **No copy-paste across activities.** Identical differentiation on every activity
  is padding, and it is the single most common way this field is filled.
* **Extension must extend.** "More of the same questions" is volume, not depth;
  a real extension changes what is being asked, not how much of it there is.
"""

from __future__ import annotations

from evals.context import EvalContext
from evals.lexicons import GENERIC_DIFFERENTIATION_MARKERS
from evals.text import distinct_ratio, has_concrete_anchor, jaccard, normalise, word_count
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score", "specificity"]

KEY = "differentiation"
LABEL = "Differentiation"
WEIGHT = 0.08
METHOD = "hybrid"

#: Under this, there is no room for an instruction — only for a sentiment.
MIN_WORDS = 6

#: Above this token overlap, support and extension are the same sentence.
SAME_INSTRUCTION = 0.7

#: Phrases that describe more work rather than different work.
_VOLUME_ONLY = (
    "more questions",
    "more problems",
    "extra questions",
    "extra problems",
    "more practice",
    "additional questions",
    "additional problems",
    "further examples",
    "more examples",
    "same task",
    "more of the same",
)


def specificity(text: str, vocabulary: frozenset[str]) -> float:
    """How usable this instruction is, in ``[0, 1]``.

    Deductions compose: generic phrasing with nothing concrete attached is the
    worst case, generic phrasing that still names the actual content is a partial
    credit, and length alone never rescues either.
    """
    folded = normalise(text)
    generic = any(marker in folded for marker in GENERIC_DIFFERENTIATION_MARKERS)
    anchored = has_concrete_anchor(text, vocabulary)

    value = 1.0
    if word_count(text) < MIN_WORDS:
        value -= 0.4
    if generic and not anchored:
        value -= 0.5
    elif generic:
        value -= 0.15
    if not anchored:
        value -= 0.25
    return max(0.0, value)


def score(ctx: EvalContext) -> DimensionScore:
    activities = ctx.activities
    if not activities:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            applicable=False,
            reason="no activities to differentiate",
        )

    findings: list[Finding] = []
    judged = ctx.judgements.differentiation_specific
    used_judge = False

    present: list[float] = []
    specific: list[float] = []
    distinct_pair: list[float] = []
    extends: list[float] = []
    supports: list[str] = []
    extensions: list[str] = []

    for index, activity in enumerate(activities):
        path = f"/activities/{index}/differentiation"
        activity_id = str(activity.get("activity_id") or f"index_{index}")
        block = activity.get("differentiation") or {}
        support = str(block.get("support") or "")
        extension = str(block.get("extension") or "")
        supports.append(support)
        extensions.append(extension)

        present.append(1.0 if support and extension else 0.0)
        if not (support and extension):
            findings.append(
                Finding(
                    "DIF_MISSING",
                    path,
                    f"{str(activity.get('title'))!r} has no "
                    f"{'support' if not support else 'extension'}",
                )
            )
            continue

        pair_scores = []
        for side, text in (("support", support), ("extension", extension)):
            verdict = judged.get(f"{activity_id}#{side}")
            value = specificity(text, ctx.vocabulary)
            if verdict is not None and 0.3 < value < 0.8:
                used_judge = True
                value = 1.0 if verdict else 0.0
            pair_scores.append(value)
            if value < 0.6:
                findings.append(
                    Finding(
                        "DIF_GENERIC",
                        f"{path}/{side}",
                        f"{text[:70]!r} could be pasted into any lesson on any topic; "
                        "name the scaffold, the prompt, or the artefact the student gets",
                    )
                )
        specific.append(sum(pair_scores) / 2)

        same = jaccard(support, extension) >= SAME_INSTRUCTION
        distinct_pair.append(0.0 if same else 1.0)
        if same:
            findings.append(
                Finding(
                    "DIF_PAIR_IDENTICAL",
                    path,
                    "support and extension say the same thing, so the activity offers "
                    "one route rather than three",
                )
            )

        volume_only = any(marker in normalise(extension) for marker in _VOLUME_ONLY)
        extends.append(0.0 if volume_only else 1.0)
        if volume_only:
            findings.append(
                Finding(
                    "DIF_EXTENSION_IS_VOLUME",
                    f"{path}/extension",
                    f"{extension[:70]!r} offers more of the same work; an extension "
                    "should change the demand, not the quantity",
                )
            )

    across = (distinct_ratio(supports) + distinct_ratio(extensions)) / 2
    if across < 1.0:
        findings.append(
            Finding(
                "DIF_COPY_PASTED",
                "/activities",
                f"only {across:.0%} of differentiation text across activities is "
                "distinct; the same two sentences are doing duty everywhere",
            )
        )

    metrics = (
        Metric("present", mean(present), 0.15, "both sides filled in"),
        Metric("specific", mean(specific), 0.40, "names something this package teaches"),
        Metric("support_differs_from_extension", mean(distinct_pair), 0.15, "two routes, not one"),
        Metric("extension_deepens", mean(extends), 0.15, "different demand, not more volume"),
        Metric("distinct_across_activities", across, 0.15, "not copy-pasted between activities"),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method="hybrid" if used_judge else "deterministic",
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
