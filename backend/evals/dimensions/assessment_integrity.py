"""Assessment integrity — is this bank markable, and does it diagnose anything?

The contract already refuses the structural catastrophes: an MCQ with two correct
answers, a constructed-response item with no rubric, a mark total that does not
add up. Those are re-checked here anyway, cheaply, because the harness has to be
able to score a package that arrived as JSON from somewhere else — but they are
not where the interesting failures live.

The interesting failures all pass schema validation:

* **Distractors that teach nothing.** A wrong answer that no student would pick is
  a wasted option; a wrong answer that traces to a real misconception both teaches
  and diagnoses. "All of the above" does neither and signals a model that ran out
  of ideas at option D.
* **The length tell.** When the correct option is reliably the longest, the item
  is testing test-taking, not the subject.
* **Rubrics that restate the question.** Levels labelled Good / Fair / Poor with
  descriptors to match cannot separate two scripts. A level descriptor has to say
  what the work *contains*, which is checkable — but not by counting its words.
  This module used to accept any descriptor of five words or more as substantive,
  which is why "The response demonstrates an excellent understanding overall"
  passed and scored *above* "Correct value with units." The check is now whether
  adjacent levels differ in the content they name, with grading adjectives
  stripped first; see :mod:`evals.discrimination`.
* **A blueprint that no longer describes the bank.** The blueprint is supposed to
  be the design the bank was built to. When the two disagree, the coverage story
  the package tells about itself is fiction.

Profile conditioning is confined to the item-kind mix, and reads the registry's
``assessment_mix`` directly. Kinds a profile weights at zero are never looked for,
so a narrative bank with no numerical items loses nothing — and a numerical item
appearing *in* a narrative bank is flagged, because that is STEM shape leaking
into content that did not ask for it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from evals.context import EvalContext, coerce_int
from evals.discrimination import descriptor_discrimination
from evals.lexicons import HEDGE_MARKERS, UNOBSERVABLE_MARKERS
from evals.text import fold, mentions_vocabulary, normalise, word_count
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "assessment_integrity"
LABEL = "Assessment integrity"
WEIGHT = 0.15
METHOD = "deterministic"

#: Options that exist because the model needed a fourth line.
_FILLER_OPTIONS = ("all of the above", "none of the above", "both a and b", "all of these")

#: How much longer the key may be than the mean distractor before the length of the
#: option is doing the testing.
LENGTH_TELL_RATIO = 1.8

#: Below this, adjacent levels do not name different work and a marker has nothing
#: to decide a borderline script on. Applied to
#: :func:`evals.discrimination.descriptor_discrimination`, which measures content,
#: not length — a long descriptor made entirely of grading adjectives scores 0.
MIN_DESCRIPTOR_DISCRIMINATION = 0.75


def _mcq_structure(item: Mapping[str, Any]) -> tuple[float, list[str]]:
    """Per-MCQ structural score and the reasons it lost anything."""
    options = list(item.get("options") or [])
    correct = [o for o in options if o.get("is_correct")]
    labels = [str(o.get("label") or "") for o in options]
    answer = str(item.get("answer") or "")

    key_matches = False
    if correct:
        key = correct[0]
        key_matches = (
            answer.strip() == str(key.get("label") or "").strip()
            or fold(answer) == fold(str(key.get("text") or ""))
            or answer.strip().startswith(str(key.get("label") or "").strip())
        )

    checks = {
        "four options": len(options) == 4,
        "exactly one correct option": len(correct) == 1,
        "distinct labels": len(set(labels)) == len(labels) and all(labels),
        "answer key matching the correct option": key_matches,
    }
    return sum(checks.values()) / len(checks), [name for name, ok in checks.items() if not ok]


def score(ctx: EvalContext) -> DimensionScore:
    items = ctx.items
    if not items:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            metrics=(Metric("bank_present", 0.0, 1.0, "no assessment items"),),
            findings=(
                Finding(
                    "ASM_NO_ITEMS",
                    "/assessments/items",
                    "the bank is empty, so nothing in the package is measured",
                ),
            ),
        )

    findings: list[Finding] = []
    structure: list[float] = []
    distractors: list[float] = []
    rubrics: list[float] = []
    rubric_structures: list[float] = []

    mcqs = [(i, item) for i, item in enumerate(items) if str(item.get("kind")) == "mcq"]
    linked = 0

    for index, item in mcqs:
        path = f"/assessments/items/{index}"
        value, broken = _mcq_structure(item)
        structure.append(value)
        if broken:
            findings.append(
                Finding(
                    "ASM_MCQ_MALFORMED",
                    path,
                    f"missing {', '.join(broken)}; this item cannot be marked as written",
                )
            )

        options = list(item.get("options") or [])
        wrong = [o for o in options if not o.get("is_correct")]
        right = [o for o in options if o.get("is_correct")]

        rationale_share = (
            sum(1 for o in wrong if str(o.get("rationale") or "").strip()) / len(wrong)
            if wrong
            else 1.0
        )
        target = ctx.expectations.min_distractor_rationale_share
        rationale_score = min(1.0, rationale_share / target) if target > 0 else 1.0
        if rationale_share < target:
            findings.append(
                Finding(
                    "ASM_DISTRACTOR_UNEXPLAINED",
                    f"{path}/options",
                    f"{rationale_share:.0%} of distractors say why they are tempting; a "
                    "wrong answer with no misconception behind it neither teaches nor "
                    "diagnoses",
                )
            )

        filler = [
            o
            for o in options
            if any(f in normalise(str(o.get("text") or "")) for f in _FILLER_OPTIONS)
        ]
        if filler:
            findings.append(
                Finding(
                    "ASM_FILLER_OPTION",
                    f"{path}/options",
                    "uses an 'all/none of the above' option, which tests option-reading "
                    "rather than the concept",
                )
            )

        texts = [fold(str(o.get("text") or "")) for o in options]
        duplicates = len(texts) - len(set(texts))
        if duplicates:
            findings.append(
                Finding(
                    "ASM_DUPLICATE_OPTIONS",
                    f"{path}/options",
                    "two options say the same thing, so the item really has three",
                )
            )

        tell = False
        if right and wrong:
            key_len = word_count(str(right[0].get("text") or ""))
            mean_wrong = mean([float(word_count(str(o.get("text") or ""))) for o in wrong])
            tell = mean_wrong > 0 and key_len > mean_wrong * LENGTH_TELL_RATIO
            if tell:
                findings.append(
                    Finding(
                        "ASM_LENGTH_TELL",
                        f"{path}/options",
                        "the correct option is markedly longer than the distractors; "
                        "test-wise students will pick it without reading the stem",
                    )
                )

        distractors.append(
            mean(
                [
                    rationale_score,
                    0.0 if filler else 1.0,
                    0.0 if duplicates else 1.0,
                    0.0 if tell else 1.0,
                ]
            )
        )

        if str(item.get("linked_misconception_id") or ""):
            linked += 1

    # --- rubrics --------------------------------------------------------------
    constructed = [(i, item) for i, item in enumerate(items) if str(item.get("kind")) != "mcq"]
    for index, item in constructed:
        path = f"/assessments/items/{index}"
        rubric = item.get("rubric") or {}
        levels = list(rubric.get("levels") or [])
        marks = [coerce_int(level.get("marks")) for level in levels]
        descriptors = [str(level.get("descriptor") or "") for level in levels]
        extended = coerce_int(item.get("marks")) >= ctx.expectations.extended_response_marks

        hedged = [
            d
            for d in descriptors
            if any(h in normalise(d) for h in HEDGE_MARKERS)
            or any(u in normalise(d) for u in UNOBSERVABLE_MARKERS)
        ]
        # Descriptors are compared by what they say the work *contains*, in mark
        # order, so "excellent understanding" against "good understanding" reads
        # as the non-discrimination it is rather than as two distinct levels.
        ordered = [d for _, d in sorted(zip(marks, descriptors, strict=True), reverse=True)]
        discrimination = descriptor_discrimination(ordered)
        # Structure and discrimination are scored apart because they fail apart and
        # are worth different amounts. A rubric can have four levels, four distinct
        # mark values and a stated criterion — every structural box ticked — and
        # still be unmarkable, which is the state vacuous descriptors produce. The
        # structure is hygiene; whether a marker can separate two scripts with it is
        # the point of having a rubric at all.
        structure_checks = {
            "a rubric": bool(levels),
            "at least two levels": len(levels) >= 2,
            "levels that award different marks": len(set(marks)) == len(marks) and bool(marks),
            "enough levels for an extended response": (
                len(levels) >= ctx.expectations.min_rubric_levels_for_extended if extended else True
            ),
        }
        rubric_structures.append(sum(structure_checks.values()) / len(structure_checks))

        tied = any(mentions_vocabulary(d, ctx.vocabulary) for d in descriptors)
        # Hedged descriptors ("a good answer", "some understanding") are graded to
        # zero rather than deducted from: they are the exact failure the content
        # comparison exists to catch, and a rubric built from them discriminates
        # nothing however many levels it declares.
        rubrics.append(0.0 if hedged else (0.7 * discrimination + 0.3 * (1.0 if tied else 0.0)))

        broken = [name for name, ok in structure_checks.items() if not ok]
        if discrimination < MIN_DESCRIPTOR_DISCRIMINATION or hedged or not tied:
            findings.append(
                Finding(
                    "ASM_RUBRIC_INDISCRIMINATE",
                    f"{path}/rubric",
                    f"adjacent levels score {discrimination:.2f} on naming different work"
                    + (" and hedge rather than describe it" if hedged else "")
                    + ("; no level names anything this package teaches" if not tied else "")
                    + ". Two markers would land on different levels for the same "
                    "borderline script, which makes the marks it awards arbitrary",
                )
            )
        if broken:
            findings.append(
                Finding(
                    "ASM_RUBRIC_MALFORMED",
                    f"{path}/rubric",
                    f"lacks {', '.join(broken)}; the level ladder itself is broken before "
                    "any question of what the descriptors say",
                )
            )

    # --- arithmetic and blueprint honesty -------------------------------------
    actual_marks = sum(coerce_int(i.get("marks")) for i in items)
    declared_marks = coerce_int(ctx.assessments.get("total_marks"))
    blueprint = ctx.blueprint
    by_kind = Counter(str(i.get("kind")) for i in items)
    by_bloom = Counter(str(i.get("bloom_level")) for i in items)

    arithmetic_checks = {
        "total_marks agrees with the items": actual_marks == declared_marks,
        "blueprint item counts match the bank": (
            not blueprint.get("items_by_kind")
            or {str(k): coerce_int(v) for k, v in blueprint["items_by_kind"].items()}
            == dict(by_kind)
        ),
        "blueprint Bloom counts match the bank": (
            not blueprint.get("items_by_bloom")
            or {str(k): coerce_int(v) for k, v in blueprint["items_by_bloom"].items()}
            == dict(by_bloom)
        ),
    }
    arithmetic = sum(arithmetic_checks.values()) / len(arithmetic_checks)
    for name, ok in arithmetic_checks.items():
        if not ok:
            findings.append(
                Finding(
                    "ASM_BLUEPRINT_DRIFT",
                    "/assessments/blueprint",
                    f"{name} is false; the coverage story the package tells about itself "
                    "no longer describes the bank it contains",
                )
            )

    # --- kind mix against the profile ----------------------------------------
    expected = ctx.expectations.expected_item_kinds
    observed = {kind: count / len(items) for kind, count in by_kind.items()}
    if expected:
        drift = sum(abs(observed.get(kind, 0.0) - share) for kind, share in expected.items())
        unexpected = sorted(set(observed) & ctx.expectations.unexpected_item_kinds)
        drift += sum(observed[kind] for kind in unexpected)
        mix = max(0.0, 1.0 - drift / 2)
        for kind in unexpected:
            findings.append(
                Finding(
                    "ASM_OFF_PROFILE_ITEM",
                    "/assessments/items",
                    f"{observed[kind]:.0%} of items are {kind!r}, which the {ctx.profile} "
                    "profile weights at zero; this is STEM shape arriving where the "
                    "content did not ask for it",
                )
            )
    else:
        mix = 1.0

    # --- diagnosis ------------------------------------------------------------
    if ctx.misconceptions and mcqs:
        share = linked / len(mcqs)
        linkage = min(1.0, share / 0.5)
        if share < 0.5:
            findings.append(
                Finding(
                    "ASM_UNLINKED_DISTRACTORS",
                    "/assessments/items",
                    f"{share:.0%} of MCQs cite the misconception they probe, though the "
                    f"package extracted {len(ctx.misconceptions)}; the bank scores "
                    "students without telling the teacher what to reteach",
                )
            )
    else:
        linkage = 1.0

    # A bank with no MCQs has no MCQ defects, and a bank with no constructed
    # responses has no rubrics to disagree about. Both are legitimate shapes, so
    # the metric is reported at weight zero rather than scored 1.0 — a free 1.0
    # for an absent section is the same arithmetic that made "no citations" score
    # perfect citation integrity.
    absent = "not scored: a bank of a different shape owes nothing here"

    metrics = (
        Metric(
            "mcq_structure",
            mean(structure),
            0.15 if mcqs else 0.0,
            f"{len(mcqs)} MCQ(s) checked" if mcqs else f"no MCQs in this bank; {absent}",
        ),
        Metric(
            "distractor_quality",
            mean(distractors),
            0.20 if mcqs else 0.0,
            "plausible, explained, not filler" if mcqs else f"no MCQs in this bank; {absent}",
        ),
        Metric(
            "rubric_structure",
            mean(rubric_structures),
            0.08 if rubric_structures else 0.0,
            f"{len(constructed)} rubric(s): levels, distinct marks, enough of them"
            if rubric_structures
            else f"no constructed-response items; {absent}",
        ),
        Metric(
            "rubric_discrimination",
            mean(rubrics),
            0.35 if rubrics else 0.0,
            f"{len(constructed)} rubric(s): do adjacent levels name different work, and "
            "does any level name this package's content?"
            if rubrics
            else f"no constructed-response items; {absent}",
        ),
        Metric("marks_and_blueprint", arithmetic, 0.12, f"{actual_marks} marks in the bank"),
        Metric("kind_mix", mix, 0.05, f"against the {ctx.profile} assessment mix"),
        Metric("misconception_linkage", linkage, 0.05, "items trace to a diagnosed error"),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
