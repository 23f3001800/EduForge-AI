"""Deliberately broken packages, and the score drop each one must cause.

This is the instrument that keeps the rest of the harness honest, and it exists
because the rubric failed a test nobody had run. Measured on a shipped package:

    baseline                       0.9167
    vacuous rubric descriptors     0.9210   (+0.0043 — better)
    filler speaker notes           0.9217   (+0.0050 — better)
    concept graph deleted entirely 0.9167   (no change at all)

Total spread across every degradation: 0.011, with two sabotages *improving* the
score. A rubric that behaves like this is not a weak instrument, it is a harmful
one: any prompt tuned against it is tuned toward padding, and the tuning will look
like progress the whole way down.

The fix is not a better rubric alone — a rubric can only be trusted if something
adversarial checks it. So each entry here takes a good package, breaks one thing
in a way real generated content actually breaks, and declares the **minimum score
drop** that break must cause. If a future prompt change, threshold tweak or new
dimension makes a sabotage cheap again, the assertion fails and names it.

Three severities, and the distinction is deliberate rather than cosmetic:

* ``severe`` — the package becomes unusable or dishonest for its stated purpose:
  it is about the wrong content, its citations are fabricated or absent, its
  rubrics cannot be marked with, its periods are copies. Minimum drop 0.05.
* ``moderate`` — a real defect a teacher would have to work around. Minimum drop
  0.02.
* ``minor`` — a narrow defect a teacher fixes in a minute. Minimum drop 0.01.

The third tier exists because the alternative was worse. Prose blackboard notes
are a genuine defect and they are a *small* one: they touch one metric in one
dimension, and the only way to make them cost five points of the total would be
to weight blackboard formatting as heavily as whether the package is about the
right subject. Inflating a weight to make an assertion pass is how a rubric stops
describing anything. Declaring what the instrument can and cannot resolve is the
honest alternative, and a tier a reviewer can argue with beats a weight nobody
can see.

A severity is a claim about how much of a package's usefulness the defect
destroys, and it should be argued with. What must not happen is a degradation
scoring *higher* than the package it damaged, which is why
:data:`MIN_ANY_DEGRADATION` applies to every entry regardless of severity.

Nothing in here names a subject. Degradations operate on structure — rubric
levels, speaker notes, concept ids, the classification topic — so the same suite
runs against a mechanics package and a poetry package and asserts the same
properties.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from evals.harness import evaluate

__all__ = [
    "DEGRADATIONS",
    "MIN_ANY_DEGRADATION",
    "MIN_DELTA",
    "Degradation",
    "DegradationResult",
    "run_suite",
]

Severity = Literal["severe", "moderate", "minor"]

#: Minimum drop by severity. A severe defect that costs less than five points of
#: the total is a defect the harness is telling the generator not to bother
#: fixing.
MIN_DELTA: Mapping[Severity, float] = {"severe": 0.05, "moderate": 0.02, "minor": 0.01}

#: No degradation may ever improve a score, or leave it untouched. This is the
#: floor the original instrument failed twice over.
MIN_ANY_DEGRADATION = 0.005


@dataclass(frozen=True, slots=True)
class Degradation:
    """One sabotage, what it simulates, and what it must cost."""

    key: str
    severity: Severity
    #: The real-world failure this reproduces. Written for whoever has to argue
    #: with the threshold later.
    describes: str
    #: Dimensions expected to notice. Checked, so a degradation cannot pass by
    #: coincidentally depressing something unrelated.
    lands_on: tuple[str, ...]
    apply: Callable[[dict[str, Any]], dict[str, Any]]

    @property
    def min_delta(self) -> float:
        return MIN_DELTA[self.severity]


@dataclass(frozen=True, slots=True)
class DegradationResult:
    key: str
    severity: Severity
    baseline: float
    degraded: float
    lands_on: tuple[str, ...]
    noticed_by: tuple[str, ...]

    @property
    def delta(self) -> float:
        return self.baseline - self.degraded

    @property
    def meets_minimum(self) -> bool:
        return self.delta >= MIN_DELTA[self.severity]

    @property
    def reduced_the_score(self) -> bool:
        return self.delta >= MIN_ANY_DEGRADATION

    @property
    def landed_where_expected(self) -> bool:
        return bool(set(self.lands_on) & set(self.noticed_by)) if self.lands_on else True

    def as_row(self) -> str:
        verdict = "ok" if (self.meets_minimum and self.landed_where_expected) else "FAIL"
        return (
            f"{self.key:26s} {self.severity:8s} {self.baseline:.4f} -> {self.degraded:.4f}  "
            f"delta {self.delta:+.4f} (min {MIN_DELTA[self.severity]:.2f})  {verdict}"
        )


# ────────────────────────────────────────────────────────────── the sabotages
#
# Each takes the package by value and returns it modified. They are written to
# leave the package *schema-plausible*: the whole point is that these all pass
# every structural check the pipeline applies, which is why only a rubric like
# this one can catch them.


def _vacuous_rubrics(package: dict[str, Any]) -> dict[str, Any]:
    """Rubric levels that grade tone instead of naming what the work contains.

    The canonical padding failure. Longer than the descriptors they replace,
    grammatical, level-labelled, mark-differentiated — and two markers reading
    the same borderline script land on different levels, because nothing here
    says what the script must actually say.
    """
    for item in package["assessments"]["items"]:
        rubric = item.get("rubric")
        if not rubric:
            continue
        marks = int(item.get("marks") or 3)
        rubric["levels"] = [
            {
                "label": "Excellent",
                "descriptor": "The response demonstrates an excellent overall understanding.",
                "marks": marks,
            },
            {
                "label": "Good",
                "descriptor": "The response demonstrates a good overall understanding.",
                "marks": max(1, marks - 1),
            },
            {
                "label": "Poor",
                "descriptor": "The response demonstrates a poor overall understanding.",
                "marks": 0,
            },
        ]
    return package


def _filler_speaker_notes(package: dict[str, Any]) -> dict[str, Any]:
    """One sentence of teaching-flavoured prose, in every segment of every period.

    Twice the length of the notes it replaces and totally unusable: it names no
    concept, instructs no action, and is identical everywhere. Under a
    word-count rule this scores as a *fuller* script than the real one.
    """
    filler = (
        "Take a moment here to engage the students in a meaningful way and ensure that "
        "everyone in the classroom is following along with the material being covered."
    )
    for period in package["classroom_content"]:
        for segment in period.get("teacher_script") or []:
            segment["speaker_notes"] = filler
    return package


def _inverted_prerequisites(package: dict[str, Any]) -> dict[str, Any]:
    """Teach every dependent idea before the idea it rests on.

    Reverses the period order of the concepts while leaving the graph intact, so
    the plan still claims a sequence rationale it now contradicts.
    """
    periods = package["teaching_plan"]["periods"]
    assignments = [list(p.get("concept_ids") or []) for p in periods]
    for period, ids in zip(periods, reversed(assignments), strict=True):
        period["concept_ids"] = ids
    return package


def _deleted_concept_graph(package: dict[str, Any]) -> dict[str, Any]:
    """Remove every prerequisite edge and keep everything else.

    The cheapest possible attack on a sequencing metric that averages an empty
    list to 1.0: with no declared ordering there are no violated orderings, so
    the plan scores perfectly for having nothing to be wrong about.
    """
    package["knowledge"]["concept_graph"] = {"node_ids": [], "edges": []}
    return package


def _off_topic_content(package: dict[str, Any]) -> dict[str, Any]:
    """Relabel the package as a different topic entirely.

    Simulates the observed failure in both directions at once — a document
    classified as one thing whose content teaches another. Every structural check
    still passes, because structurally nothing changed.
    """
    package["classification"]["subject"] = "Civics"
    package["classification"]["topic"] = "The drafting of the constituent assembly"
    return package


def _dangling_concept_references(package: dict[str, Any]) -> dict[str, Any]:
    """Point activities and items at concepts this document never extracted."""
    for offset, activity in enumerate(package.get("activities") or []):
        activity["concept_ids"] = [f"concept_not_extracted_{offset}"]
    for offset, item in enumerate(package["assessments"]["items"]):
        item["concept_ids"] = [f"concept_not_extracted_{offset}"]
    return package


def _duplicated_periods(package: dict[str, Any]) -> dict[str, Any]:
    """Copy period 1's content into every later period.

    Observed in a shipped sample. Each period keeps its own number and its own
    planned objective, and checks the first period's concept instead.
    """
    content = package.get("classroom_content") or []
    if len(content) < 2:
        return package
    for index, block in enumerate(content[1:], start=1):
        clone = copy.deepcopy(content[0])
        clone["period_no"] = block.get("period_no")
        clone["activity_refs"] = block.get("activity_refs")
        content[index] = clone
    return package


def _all_recall(package: dict[str, Any]) -> dict[str, Any]:
    """Every mark and every mid-lesson check at the bottom of the ladder."""
    for item in package["assessments"]["items"]:
        item["bloom_level"] = "remember"
    counts: dict[str, int] = {"remember": len(package["assessments"]["items"])}
    package["assessments"]["blueprint"]["items_by_bloom"] = counts
    for period in package.get("classroom_content") or []:
        for question in period.get("checkpoint_questions") or []:
            question["bloom_level"] = "remember"
    return package


def _nonsense_distractors(package: dict[str, Any]) -> dict[str, Any]:
    """Wrong answers nobody would pick, with no misconception behind them."""
    for item in package["assessments"]["items"]:
        options = item.get("options") or []
        for offset, option in enumerate(o for o in options if not o.get("is_correct")):
            option["text"] = "None of the above" if offset else "All of the above"
            option["rationale"] = None
    return package


def _stripped_citations(package: dict[str, Any]) -> dict[str, Any]:
    """Delete every evidence span, leaving the claims in place.

    The other half of the empty-mean defect: with nothing to check verbatim,
    citation integrity was a perfect score for a package that cites nothing.
    """
    for field in (
        "concepts",
        "definitions",
        "formulae",
        "examples",
        "applications",
        "misconceptions",
    ):
        for entry in package["knowledge"].get(field) or []:
            entry["evidence"] = []
    for gap in package.get("learning_gaps") or []:
        gap["evidence"] = []
    return package


def _fabricated_citations(package: dict[str, Any]) -> dict[str, Any]:
    """Quotes that read as authority and appear nowhere in the source.

    Worse than no citation, which is why it is scored harder than one: an absent
    citation is visibly absent, and an invented one is indistinguishable from a
    real one until somebody opens the book.
    """
    for field in (
        "concepts",
        "definitions",
        "formulae",
        "examples",
        "applications",
        "misconceptions",
    ):
        for entry in package["knowledge"].get(field) or []:
            spans = entry.get("evidence") or []
            entry["evidence"] = [
                {
                    "chunk_id": (spans[0] if spans else {}).get("chunk_id") or "c_001",
                    "quote": "This sentence was never written in the source document at all.",
                    "page": 1,
                }
            ]
    for gap in package.get("learning_gaps") or []:
        spans = gap.get("evidence") or []
        if spans:
            gap["evidence"] = [
                {
                    "chunk_id": spans[0].get("chunk_id") or "c_001",
                    "quote": "This sentence was never written in the source document at all.",
                    "page": 1,
                }
            ]
    return package


def _topic_restating_objectives(package: dict[str, Any]) -> dict[str, Any]:
    """Objectives that are a concept name with an unobservable verb glued on."""
    for objective in package["knowledge"]["learning_objectives"]:
        objective["statement"] = "Understand the topic"
        objective["bloom_level"] = "remember"
    return package


def _generic_differentiation(package: dict[str, Any]) -> dict[str, Any]:
    """The same two sentences of boilerplate on every activity."""
    for activity in package.get("activities") or []:
        activity["differentiation"] = {
            "support": "Provide extra support to weaker students as needed.",
            "extension": "Give more questions to the fast finishers.",
        }
    return package


def _unobservable_success_criteria(package: dict[str, Any]) -> dict[str, Any]:
    """Criteria a teacher cannot apply from the front of the room."""
    for activity in package.get("activities") or []:
        activity["success_criteria"] = ["Students understand the concept being taught."]
    return package


def _prose_board_notes(package: dict[str, Any]) -> dict[str, Any]:
    """Blackboard notes written as a paragraph, with no headings to hang it on.

    What ends up on the board is what the class copies into their books. A
    paragraph does not get written on a blackboard, and without headings there is
    nothing for the copied notes to be filed under.
    """
    paragraph = (
        "In this lesson we will consider the way in which the ideas under discussion "
        "connect to one another and to the wider material of the chapter, and students "
        "should make sure they take down everything that is said here carefully."
    )
    for period in package.get("classroom_content") or []:
        notes = period.get("blackboard_notes") or {}
        notes["bullet_points"] = [paragraph, paragraph]
        notes["headings"] = []
        period["blackboard_notes"] = notes
    return package


DEGRADATIONS: tuple[Degradation, ...] = (
    Degradation(
        key="off_topic_content",
        severity="severe",
        describes="a package labelled one topic whose content teaches another",
        lands_on=("content_fidelity",),
        apply=_off_topic_content,
    ),
    Degradation(
        key="dangling_concept_references",
        severity="severe",
        describes="activities and items pointing at concepts this document never extracted",
        lands_on=("content_fidelity", "coverage"),
        apply=_dangling_concept_references,
    ),
    Degradation(
        key="vacuous_rubrics",
        severity="severe",
        describes="rubric levels that grade tone rather than naming what the work contains",
        lands_on=("assessment_integrity",),
        apply=_vacuous_rubrics,
    ),
    Degradation(
        key="filler_speaker_notes",
        severity="severe",
        describes="one sentence of teaching-flavoured prose standing in for every script segment",
        lands_on=("classroom",),
        apply=_filler_speaker_notes,
    ),
    Degradation(
        key="duplicated_periods",
        severity="severe",
        describes="later periods reusing period 1's tickets, board notes and checkpoints",
        lands_on=("period_integrity", "classroom"),
        apply=_duplicated_periods,
    ),
    Degradation(
        key="stripped_citations",
        severity="severe",
        describes="every claim left in place with its evidence deleted",
        lands_on=("grounding",),
        apply=_stripped_citations,
    ),
    Degradation(
        key="fabricated_citations",
        severity="severe",
        describes="quotes that read as authority and appear nowhere in the source",
        lands_on=("grounding",),
        apply=_fabricated_citations,
    ),
    Degradation(
        key="inverted_prerequisites",
        severity="severe",
        describes="every dependent idea taught before the idea it rests on",
        lands_on=("sequencing",),
        apply=_inverted_prerequisites,
    ),
    Degradation(
        key="topic_restating_objectives",
        severity="severe",
        describes="objectives that are a concept name with an unobservable verb attached",
        lands_on=("objectives",),
        apply=_topic_restating_objectives,
    ),
    Degradation(
        key="deleted_concept_graph",
        severity="moderate",
        describes="no declared prerequisite anywhere, so no ordering can be checked",
        lands_on=("sequencing",),
        apply=_deleted_concept_graph,
    ),
    Degradation(
        key="all_recall_bloom",
        severity="moderate",
        describes="every mark and every mid-lesson check at the bottom of the ladder",
        lands_on=("bloom", "classroom"),
        apply=_all_recall,
    ),
    Degradation(
        key="nonsense_distractors",
        severity="moderate",
        describes="wrong answers nobody would pick, with no misconception behind them",
        lands_on=("assessment_integrity",),
        apply=_nonsense_distractors,
    ),
    Degradation(
        key="generic_differentiation",
        severity="moderate",
        describes="the same two sentences of boilerplate on every activity",
        lands_on=("differentiation",),
        apply=_generic_differentiation,
    ),
    Degradation(
        key="unobservable_success_criteria",
        severity="moderate",
        describes="success criteria a teacher cannot apply from the front of the room",
        lands_on=("activities",),
        apply=_unobservable_success_criteria,
    ),
    Degradation(
        key="prose_board_notes",
        severity="minor",
        describes="blackboard notes written as a paragraph nobody would copy down",
        lands_on=("classroom",),
        apply=_prose_board_notes,
    ),
)


def run_suite(
    package: Mapping[str, Any],
    *,
    chunks: Sequence[Mapping[str, Any]] | None = None,
    only: Sequence[str] = (),
) -> list[DegradationResult]:
    """Score the package, then score each sabotaged variant of it.

    The baseline is recomputed from the same input every time rather than cached
    across calls, so a suite run is reproducible in isolation and cannot be
    poisoned by a mutation leaking out of an earlier degradation.
    """
    selected = [d for d in DEGRADATIONS if not only or d.key in set(only)]
    baseline_report = evaluate(copy.deepcopy(dict(package)), chunks=chunks)
    baseline = baseline_report.overall
    before = {d.key: d.score for d in baseline_report.dimensions}

    results: list[DegradationResult] = []
    for degradation in selected:
        broken = degradation.apply(copy.deepcopy(dict(package)))
        report = evaluate(broken, chunks=chunks)
        after = {d.key: d.score for d in report.dimensions}
        # A dimension "noticed" only if it was scoreable both before and after and
        # moved down. One that became inapplicable is excluded rather than counted
        # as a catch: dropping out of the weighted mean is not the same as
        # detecting anything, and letting it count would let a degradation pass by
        # making a dimension unmeasurable.
        noticed = tuple(
            key
            for key, value in after.items()
            for baseline_value in [before.get(key)]
            if value is not None and baseline_value is not None and value < baseline_value - 1e-9
        )
        results.append(
            DegradationResult(
                key=degradation.key,
                severity=degradation.severity,
                baseline=baseline,
                degraded=report.overall,
                lands_on=degradation.lands_on,
                noticed_by=noticed,
            )
        )
    return results


def render(results: Sequence[DegradationResult]) -> str:
    """A table a reviewer can read without running anything."""
    if not results:
        return "no degradations run"
    lines = [r.as_row() for r in results]
    deltas = [r.delta for r in results]
    lines.append("")
    lines.append(
        f"spread {max(deltas) - min(deltas):.4f}; smallest drop {min(deltas):+.4f}; "
        f"largest {max(deltas):+.4f}"
    )
    return "\n".join(lines)
