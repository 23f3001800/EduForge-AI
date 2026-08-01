"""Activities — variety, runnability, and success criteria you can actually see.

Five variations of "discuss in pairs" is one activity type, not five, and every
one of them validates. So variety is measured as *distinct types against the
number of slots*, not as a count of activities.

Runnability is the other half, and it is where generated activities usually fail
quietly:

* **Materials** a real classroom has. Empty materials is a pass — a debate needs
  nothing — so this metric only ever penalises the presence of equipment the room
  does not have, never the absence of equipment it does.
* **Instructions** specific enough to run without interpretation: more than one
  step, steps long enough to be a step, and anchored to something in this package
  rather than to teaching in general.
* **Success criteria observable in the moment.** "Students understand inertia" is
  not observable; the teacher finds out next week when the marking comes back.
  "Student predicts the coin falls into the glass" is observable from the front of
  the room, which is what a success criterion is for.

Profile fit is scored gently and deliberately so. The pedagogy registry says which
types suit the material, but a demonstration in a narrative package is a choice, not
an error — the strong signal is a package where *nothing* matches the profile.
"""

from __future__ import annotations

from evals.context import EvalContext
from evals.lexicons import EXOTIC_MATERIAL_MARKERS, OBSERVABLE_VERBS, UNOBSERVABLE_MARKERS
from evals.text import distinct_ratio, has_concrete_anchor, normalise, tokens, word_count
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "criterion_is_observable", "score"]

KEY = "activities"
LABEL = "Activity variety and runnability"
WEIGHT = 0.14
METHOD = "hybrid"

#: A step shorter than this is a label, not an instruction.
MIN_STEP_WORDS = 5


def criterion_is_observable(text: str) -> float | None:
    """1.0 observable, 0.0 not, ``None`` when the lexicon cannot tell.

    ``None`` is the honest answer often enough that it gets its own return value:
    it is what the optional judge exists to resolve, and guessing would put a
    number on the harness that the harness did not earn.
    """
    words = set(tokens(text))
    folded = normalise(text)
    observable = bool(words & OBSERVABLE_VERBS)
    unobservable = any(
        marker in folded if " " in marker else marker in words for marker in UNOBSERVABLE_MARKERS
    )
    if unobservable and not observable:
        return 0.0
    if observable:
        return 1.0
    return None


def score(ctx: EvalContext) -> DimensionScore:
    activities = ctx.activities
    findings: list[Finding] = []

    if not activities:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            metrics=(Metric("activities_present", 0.0, 1.0, "no activities"),),
            findings=(
                Finding(
                    "ACT_NONE",
                    "/activities",
                    "the package contains no activities, so every period is teacher talk",
                ),
            ),
        )

    preferred = ctx.expectations.preferred_activity_types
    judged = ctx.judgements.criterion_observable
    used_judge = False

    # --- variety --------------------------------------------------------------
    types = [str(a.get("type") or "") for a in activities]
    distinct = len(set(types))
    ceiling = min(len(activities), max(len(preferred), 1))
    variety = min(1.0, distinct / ceiling) if ceiling else 1.0
    if distinct < min(len(activities), ctx.expectations.min_distinct_activity_types):
        findings.append(
            Finding(
                "ACT_MONOTONOUS",
                "/activities",
                f"{len(activities)} activities across {distinct} type(s) "
                f"({', '.join(sorted(set(types)))}); the same format every period is one "
                "activity repeated, not a programme",
            )
        )

    fit = [1.0 if kind in preferred else 0.0 for kind in types]
    if preferred and not any(fit):
        findings.append(
            Finding(
                "ACT_PROFILE_MISMATCH",
                "/activities",
                f"no activity uses a type the {ctx.profile} profile weights "
                f"({', '.join(sorted(preferred))})",
            )
        )

    # --- per-activity ---------------------------------------------------------
    criteria_scores: list[float] = []
    instruction_scores: list[float] = []
    materials_scores: list[float] = []

    for index, activity in enumerate(activities):
        path = f"/activities/{index}"
        activity_id = str(activity.get("activity_id") or f"index_{index}")

        for offset, criterion in enumerate(activity.get("success_criteria") or []):
            verdict = criterion_is_observable(str(criterion))
            if verdict is None:
                judged_verdict = judged.get(f"{activity_id}#{offset}")
                if judged_verdict is None:
                    criteria_scores.append(0.5)
                else:
                    used_judge = True
                    criteria_scores.append(1.0 if judged_verdict else 0.0)
                continue
            criteria_scores.append(verdict)
            if verdict == 0.0:
                findings.append(
                    Finding(
                        "ACT_CRITERION_UNOBSERVABLE",
                        f"{path}/success_criteria/{offset}",
                        f"{str(criterion)[:70]!r} describes a mental state; a teacher "
                        "cannot see it happen and so cannot use it during the lesson",
                    )
                )

        steps = [str(s) for s in (activity.get("teacher_instructions") or [])]
        student = [str(s) for s in (activity.get("student_instructions") or [])]
        parts = [
            1.0 if len(steps) >= ctx.expectations.min_teacher_steps else 0.0,
            1.0 if steps and all(word_count(s) >= MIN_STEP_WORDS for s in steps) else 0.0,
            1.0 if student else 0.0,
            1.0 if any(has_concrete_anchor(s, ctx.vocabulary) for s in steps + student) else 0.0,
        ]
        instruction_scores.append(sum(parts) / len(parts))
        if sum(parts) < len(parts):
            missing = [
                name
                for name, ok in zip(
                    ("enough steps", "steps with substance", "student-facing wording", "an anchor"),
                    parts,
                    strict=True,
                )
                if not ok
            ]
            findings.append(
                Finding(
                    "ACT_THIN_INSTRUCTIONS",
                    f"{path}/teacher_instructions",
                    f"{str(activity.get('title'))!r} lacks {', '.join(missing)}; a teacher "
                    "reading this cold would have to invent the middle of it",
                )
            )

        materials = [str(m) for m in (activity.get("materials") or [])]
        exotic = [m for m in materials if any(x in normalise(m) for x in EXOTIC_MATERIAL_MARKERS)]
        if materials:
            materials_scores.append(0.0 if exotic else 1.0)
        if exotic:
            findings.append(
                Finding(
                    "ACT_MATERIAL_UNAVAILABLE",
                    f"{path}/materials",
                    f"requires {', '.join(exotic)}; an ordinary classroom does not have "
                    "this, so the activity will be skipped rather than adapted",
                )
            )

    # --- padding --------------------------------------------------------------
    signatures = [
        " ".join(
            [str(a.get("title") or ""), *(str(s) for s in a.get("teacher_instructions") or [])]
        )
        for a in activities
    ]
    distinctness = distinct_ratio(signatures)
    if distinctness < 1.0:
        findings.append(
            Finding(
                "ACT_DUPLICATED",
                "/activities",
                f"{distinctness:.0%} of activities are distinct; the rest are the same "
                "activity with the nouns changed",
            )
        )

    metrics = (
        Metric("type_variety", variety, 0.25, f"{distinct} distinct type(s) across {len(types)}"),
        Metric("profile_fit", mean(fit), 0.10, f"types the {ctx.profile} profile weights"),
        Metric("observable_criteria", mean(criteria_scores), 0.25, "visible during the lesson"),
        Metric("instruction_specificity", mean(instruction_scores), 0.20, "runnable without edits"),
        Metric(
            "materials_realism",
            mean(materials_scores),
            0.10,
            f"{len(materials_scores)} activity(ies) list materials; listing none is a pass",
        ),
        Metric("distinct_activities", distinctness, 0.10, "not the same activity repeated"),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method="hybrid" if used_judge else "deterministic",
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
