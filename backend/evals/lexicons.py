"""Word lists the deterministic metrics compare against.

Every list here is *pedagogical*, never topical. There is no subject name in this
module and there cannot be one: the verbs that make an objective measurable are
the same verbs in a mechanics chapter and a poetry chapter, and the phrases that
make differentiation generic are generic everywhere. Where a check genuinely needs
domain knowledge, it uses the package's own vocabulary instead
(:func:`evals.text.build_vocabulary`), which adapts per document for free.

The Bloom map is deliberately even-handed across content shapes. ``calculate``,
``derive`` and ``plot`` sit alongside ``interpret``, ``argue`` and ``contextualise``
at comparable levels, so an objective written for narrative material is not marked
down for failing to sound quantitative. A verb list that only recognised STEM verbs
would silently make every humanities objective look unmeasurable — the same defect
as a validator that requires formulae, one layer up.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "BLOOM_ORDER",
    "BLOOM_VERBS",
    "EXOTIC_MATERIAL_MARKERS",
    "GENERIC_DIFFERENTIATION_MARKERS",
    "HEDGE_MARKERS",
    "OBSERVABLE_VERBS",
    "UNOBSERVABLE_MARKERS",
    "VAGUE_OBJECTIVE_VERBS",
    "WEAK_OBJECTIVE_VERBS",
    "bloom_distance",
    "bloom_index",
]

Bloom = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]

BLOOM_ORDER: tuple[Bloom, ...] = (
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
)

#: Verb -> the Bloom level that verb honestly denotes. Used to check that a
#: declared ``bloom_level`` matches the behaviour the statement actually asks for;
#: "list the causes" tagged ``analyze`` inflates the whole bank's profile.
BLOOM_VERBS: dict[str, Bloom] = {
    # remember
    "state": "remember",
    "list": "remember",
    "name": "remember",
    "define": "remember",
    "recall": "remember",
    "identify": "remember",
    "label": "remember",
    "recognise": "remember",
    "recognize": "remember",
    "match": "remember",
    "locate": "remember",
    "quote": "remember",
    "reproduce": "remember",
    # understand
    "explain": "understand",
    "describe": "understand",
    "summarise": "understand",
    "summarize": "understand",
    "paraphrase": "understand",
    "illustrate": "understand",
    "classify": "understand",
    "outline": "understand",
    "restate": "understand",
    "convert": "understand",
    "estimate": "understand",
    "predict": "understand",
    "interpret": "understand",
    # apply
    "calculate": "apply",
    "compute": "apply",
    "solve": "apply",
    "apply": "apply",
    "use": "apply",
    "demonstrate": "apply",
    "construct": "apply",
    "measure": "apply",
    "determine": "apply",
    "derive": "apply",
    "plot": "apply",
    "draw": "apply",
    "carry": "apply",
    "perform": "apply",
    "execute": "apply",
    "implement": "apply",
    "adapt": "apply",
    # analyze
    "analyse": "analyze",
    "analyze": "analyze",
    "compare": "analyze",
    "contrast": "analyze",
    "differentiate": "analyze",
    "distinguish": "analyze",
    "examine": "analyze",
    "infer": "analyze",
    "trace": "analyze",
    "attribute": "analyze",
    "deconstruct": "analyze",
    "investigate": "analyze",
    "relate": "analyze",
    "contextualise": "analyze",
    "contextualize": "analyze",
    # evaluate
    "evaluate": "evaluate",
    "justify": "evaluate",
    "critique": "evaluate",
    "judge": "evaluate",
    "assess": "evaluate",
    "argue": "evaluate",
    "defend": "evaluate",
    "recommend": "evaluate",
    "appraise": "evaluate",
    "weigh": "evaluate",
    "rank": "evaluate",
    "prioritise": "evaluate",
    "prioritize": "evaluate",
    # create
    "create": "create",
    "design": "create",
    "compose": "create",
    "devise": "create",
    "formulate": "create",
    "produce": "create",
    "plan": "create",
    "propose": "create",
    "generate": "create",
    "reconstruct": "create",
}

#: Verbs that describe an internal state nobody can observe. An objective opening
#: with one of these is a topic label wearing a verb.
VAGUE_OBJECTIVE_VERBS: frozenset[str] = frozenset(
    {
        "understand",
        "know",
        "learn",
        "appreciate",
        "grasp",
        "comprehend",
        "realise",
        "realize",
        "internalise",
        "internalize",
        "be",
        "become",
        "gain",
        "acquire",
        "familiarise",
        "familiarize",
        "study",
        "cover",
        "master",
        "value",
        "believe",
    }
)

#: Verbs that describe an activity rather than an outcome. Better than vague, still
#: not assessable on its own — you cannot mark "explore".
WEAK_OBJECTIVE_VERBS: frozenset[str] = frozenset(
    {"explore", "discuss", "consider", "review", "revise", "look", "think", "engage", "work"}
)

#: Verbs a teacher can watch happen inside the lesson. Success criteria are graded
#: against this: "students understand inertia" is not observable in the moment,
#: "student predicts the coin falls into the glass" is.
OBSERVABLE_VERBS: frozenset[str] = frozenset(
    {
        "state",
        "states",
        "write",
        "writes",
        "say",
        "says",
        "list",
        "lists",
        "name",
        "names",
        "identify",
        "identifies",
        "label",
        "labels",
        "draw",
        "draws",
        "sort",
        "sorts",
        "match",
        "matches",
        "order",
        "orders",
        "calculate",
        "calculates",
        "solve",
        "solves",
        "explain",
        "explains",
        "describe",
        "describes",
        "predict",
        "predicts",
        "cite",
        "cites",
        "quote",
        "quotes",
        "argue",
        "argues",
        "justify",
        "justifies",
        "compare",
        "compares",
        "contrast",
        "contrasts",
        "present",
        "presents",
        "produce",
        "produces",
        "record",
        "records",
        "measure",
        "measures",
        "demonstrate",
        "demonstrates",
        "correct",
        "corrects",
        "complete",
        "completes",
        "annotate",
        "annotates",
        "rank",
        "ranks",
        "select",
        "selects",
        "point",
        "points",
        "read",
        "reads",
        "perform",
        "performs",
        "build",
        "builds",
        "hand",
        "hands",
        "answer",
        "answers",
        "use",
        "uses",
        "show",
        "shows",
        "give",
        "gives",
        "refer",
        "refers",
    }
)

#: Phrases that mark an unobservable claim wherever they appear — success criteria,
#: exit-ticket indicators, rubric descriptors.
UNOBSERVABLE_MARKERS: frozenset[str] = frozenset(
    {
        "understand",
        "understands",
        "understanding",
        "know",
        "knows",
        "knowledge of",
        "appreciate",
        "appreciates",
        "aware",
        "awareness",
        "grasp",
        "grasps",
        "realise",
        "realize",
        "enjoy",
        "enjoys",
        "feel",
        "feels",
        "believe",
        "believes",
        "internalise",
        "internalize",
        "familiar",
        "learn",
        "learns",
        "learnt",
        "learned",
    }
)

#: Differentiation that could be pasted into any lesson on any topic. Each of these
#: is a real phrase generated content produces; none of them tells a teacher what
#: to actually do at 10:15 on Tuesday.
GENERIC_DIFFERENTIATION_MARKERS: tuple[str, ...] = (
    "extra help",
    "more help",
    "additional help",
    "additional support",
    "extra support",
    "more support",
    "weaker students",
    "weak students",
    "struggling students",
    "slower learners",
    "slow learners",
    "less able",
    "fast finishers",
    "early finishers",
    "advanced students",
    "able students",
    "gifted students",
    "bright students",
    "more challenging",
    "harder questions",
    "harder problems",
    "extra questions",
    "extra problems",
    "more questions",
    "more problems",
    "more practice",
    "further practice",
    "additional practice",
    "extra work",
    "more work",
    "as needed",
    "if necessary",
    "if required",
    "where appropriate",
    "as required",
    "give more time",
    "allow more time",
    "provide guidance",
    "offer guidance",
    "simplify the task",
    "make it easier",
    "make it harder",
    "help them",
    "support them",
    "challenge them",
)

#: Rubric descriptors and instructions that grade tone instead of substance.
HEDGE_MARKERS: tuple[str, ...] = (
    "good answer",
    "excellent answer",
    "adequate answer",
    "poor answer",
    "very good",
    "fairly good",
    "some understanding",
    "little understanding",
    "no understanding",
    "partially correct",
    "mostly correct",
    "as expected",
    "satisfactory",
    "unsatisfactory",
    "appropriate response",
)

#: Materials an ordinary classroom does not have. The test is availability, not
#: technology-aversion: a projector is fine, a spectrophotometer is not, and a
#: package that needs one per pair is not runnable in the room it was written for.
EXOTIC_MATERIAL_MARKERS: tuple[str, ...] = (
    "oscilloscope",
    "spectrophotometer",
    "centrifuge",
    "3d printer",
    "vr headset",
    "virtual reality",
    "arduino",
    "raspberry pi",
    "microcontroller",
    "laser cutter",
    "smart board",
    "smartboard",
    "interactive whiteboard",
    "one laptop per student",
    "laptop per student",
    "tablet per student",
    "one tablet per",
    "class set of laptops",
    "class set of tablets",
    "drone",
    "photogate",
    "data logger",
    "motion sensor",
    "force sensor",
    "wind tunnel",
    "kiln",
    "telescope",
    "microscope slide kit",
    "liquid nitrogen",
    "bunsen burner per student",
)


def bloom_index(level: str) -> int:
    """Position on the ladder, or ``-1`` for anything unrecognised."""
    try:
        return BLOOM_ORDER.index(level)  # type: ignore[arg-type]
    except ValueError:
        return -1


def bloom_distance(declared: str, implied: str) -> int:
    """Rungs between a declared level and the one the verb implies."""
    left, right = bloom_index(declared), bloom_index(implied)
    if left < 0 or right < 0:
        return 0
    return abs(left - right)
