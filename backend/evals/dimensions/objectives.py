"""Objective quality — is this an assessable behaviour, or a topic label?

The failure this dimension exists to catch is the one that looks fine in a demo:
"Understand photosynthesis" parses, validates, renders in the UI, and cannot be
marked. Five checks, all deterministic, all subject-neutral:

* **Measurable verb.** The leading verb must denote something a teacher can
  observe. ``explain``, ``calculate``, ``argue``, ``contrast`` do; ``understand``,
  ``appreciate``, ``know`` do not; ``explore`` and ``discuss`` describe what
  happens in the room rather than what the student can then do.
* **Bloom honesty.** The declared level must match the level the verb actually
  denotes. ``list`` tagged ``analyze`` inflates the Bloom profile of the whole
  package, and it is the single easiest thing for a model to get away with
  because nothing downstream checks it.
* **Concept linkage.** An objective attached to no concept cannot be traced to
  anything taught, planned, or assessed — every coverage check downstream depends
  on this edge existing.
* **Not a restatement.** Verb plus concept name and nothing else ("Explain
  inertia") is a topic with a verb glued on. A real objective names the condition
  or the context the behaviour happens in.
* **Specificity.** Long enough, and anchored to something in this package.

The optional judge only ever resolves the case the lexicon cannot: a verb it has
never seen. Everything else is decided in Python, so the score does not move when
the model does.
"""

from __future__ import annotations

import re

from evals.context import EvalContext
from evals.lexicons import (
    BLOOM_VERBS,
    VAGUE_OBJECTIVE_VERBS,
    WEAK_OBJECTIVE_VERBS,
    bloom_distance,
)
from evals.text import fold, has_concrete_anchor, jaccard, tokens, word_count
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "objectives"
LABEL = "Objective quality"
WEIGHT = 0.12
METHOD = "hybrid"

#: Below this an objective is a label, not a behaviour: there is no room for a
#: condition, an object, and a context in four words.
MIN_OBJECTIVE_WORDS = 6
#: Above this it names a circumstance, not just an action on a noun.
SPECIFIC_OBJECTIVE_WORDS = 9

#: Stems that carry no meaning and hide the real verb. Stripped before the verb is
#: read, so "Students will be able to explain..." is judged on `explain`.
_PADDING = re.compile(
    r"^\s*(?:(?:the\s+)?(?:students?|learners?|pupils?|candidates?)\s+"
    r"(?:will|should|can|must)\s+)?(?:be\s+able\s+to\s+)?",
    re.IGNORECASE,
)


def _effective_verb(statement: str) -> tuple[str, bool]:
    """The verb that actually governs the statement, and whether padding hid it."""
    stripped = _PADDING.sub("", statement, count=1)
    padded = fold(stripped) != fold(statement)
    words = tokens(stripped)
    if not words:
        return "", padded
    verb = words[0]
    # "Carry out an investigation", "Work out the acceleration": the second token
    # completes the verb, so try the pair before giving up on the first.
    if verb not in BLOOM_VERBS and len(words) > 1 and words[1] in {"out", "up", "down"}:
        return verb, padded
    return verb, padded


def _restates_a_concept(statement: str, concept_names: list[str]) -> bool:
    """Is this verb + concept name and nothing more?"""
    remainder = fold(_PADDING.sub("", statement, count=1))
    parts = remainder.split(" ", 1)
    if len(parts) < 2:
        return True
    tail = parts[1]
    # Drop a leading article so "explain the partition" matches "partition".
    tail = re.sub(r"^(?:the|a|an|its|his|her|their)\s+", "", tail)
    return any(jaccard(tail, fold(name)) >= 0.85 for name in concept_names if name)


def score(ctx: EvalContext) -> DimensionScore:
    objectives = ctx.objectives
    findings: list[Finding] = []

    if not objectives:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            metrics=(Metric("objectives_present", 0.0, 1.0, "no learning objectives"),),
            findings=(
                Finding(
                    "OBJ_NONE",
                    "/knowledge/learning_objectives",
                    "the package states no learning objectives, so nothing in it is "
                    "aimed at anything a teacher could mark",
                ),
            ),
        )

    concept_names = [str(c.get("name") or "") for c in ctx.concepts]
    known_concepts = ctx.concept_ids
    judged = ctx.judgements.objective_measurable

    measurable: list[float] = []
    honest: list[float] = []
    linked: list[float] = []
    behavioural: list[float] = []
    specific: list[float] = []
    used_judge = False

    for index, objective in enumerate(objectives):
        path = f"/knowledge/learning_objectives/{index}"
        statement = str(objective.get("statement") or "")
        objective_id = str(objective.get("objective_id") or f"index_{index}")
        declared = str(objective.get("bloom_level") or "")
        verb, padded = _effective_verb(statement)

        # --- measurable verb -------------------------------------------------
        verdict = judged.get(objective_id)
        if verb in VAGUE_OBJECTIVE_VERBS:
            measurable.append(0.0)
            findings.append(
                Finding(
                    "OBJ_UNOBSERVABLE_VERB",
                    path,
                    f"{verb!r} names an internal state nobody can observe; rewrite as "
                    f"what the student will be seen to do ({statement[:70]!r})",
                )
            )
        elif verb in WEAK_OBJECTIVE_VERBS:
            measurable.append(0.35)
            findings.append(
                Finding(
                    "OBJ_ACTIVITY_NOT_OUTCOME",
                    path,
                    f"{verb!r} describes what happens in the lesson, not what the "
                    "student can afterwards do; nothing here is markable",
                )
            )
        elif verb in BLOOM_VERBS:
            measurable.append(1.0)
        elif verdict is not None:
            used_judge = True
            measurable.append(1.0 if verdict else 0.0)
        else:
            measurable.append(0.5)
            findings.append(
                Finding(
                    "OBJ_UNRECOGNISED_VERB",
                    path,
                    f"{verb!r} is not in the observable-verb lexicon; scored neutral "
                    "and queued for the judge rather than guessed at",
                )
            )

        if padded:
            findings.append(
                Finding(
                    "OBJ_PADDED_STEM",
                    path,
                    "opens with 'students will be able to'; the stem costs a line in "
                    "every rendering and adds nothing the field does not already say",
                )
            )

        # --- Bloom honesty ---------------------------------------------------
        implied = BLOOM_VERBS.get(verb)
        if implied is None:
            honest.append(0.5)
        else:
            distance = bloom_distance(declared, implied)
            honest.append({0: 1.0, 1: 0.6}.get(distance, 0.15))
            if distance >= 1:
                findings.append(
                    Finding(
                        "OBJ_BLOOM_MISMATCH",
                        path,
                        f"tagged {declared!r} but {verb!r} denotes {implied!r} "
                        f"({distance} level(s) apart); either the verb or the tag is wrong",
                    )
                )

        # --- concept linkage -------------------------------------------------
        ids = [str(c) for c in (objective.get("concept_ids") or [])]
        resolved = [c for c in ids if c in known_concepts]
        linked.append(1.0 if resolved else 0.0)
        if not resolved:
            findings.append(
                Finding(
                    "OBJ_UNLINKED",
                    path,
                    "links to no known concept, so no coverage check can tell whether "
                    "it is taught or assessed",
                )
            )

        # --- behaviour, not label --------------------------------------------
        words = word_count(statement)
        if words < MIN_OBJECTIVE_WORDS or _restates_a_concept(statement, concept_names):
            behavioural.append(0.0)
            findings.append(
                Finding(
                    "OBJ_TOPIC_RESTATEMENT",
                    path,
                    f"{statement[:70]!r} is a concept name with a verb in front; name "
                    "the condition or context the behaviour happens in",
                )
            )
        else:
            behavioural.append(1.0)

        # --- specificity ------------------------------------------------------
        anchored = has_concrete_anchor(statement, ctx.vocabulary)
        specific.append(1.0 if (anchored and words >= SPECIFIC_OBJECTIVE_WORDS) else 0.6)

    metrics = (
        Metric("measurable_verb", mean(measurable), 0.30, "leading verb denotes an observable act"),
        Metric("bloom_honesty", mean(honest), 0.25, "declared level matches the verb"),
        Metric("concept_linkage", mean(linked), 0.15, "resolves to a concept in this package"),
        Metric("behaviour_not_label", mean(behavioural), 0.20, "not a topic with a verb attached"),
        Metric("specificity", mean(specific), 0.10, "names a condition or context"),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method="hybrid" if used_judge else "deterministic",
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
