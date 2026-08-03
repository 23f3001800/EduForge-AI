"""Stage 4's deterministic half — the part the model is not allowed to touch.

Everything here is pure Python over the concept graph: how many periods the
material needs, what order the concepts must be taught in, which concepts sit in
which period, which objectives each period serves, and how the minutes add up.

The split matters. If the model chose the ordering, "no period teaches a concept
before its prerequisite" would be a hope. Because the ordering is a topological
sort computed here, it is a property of the algorithm — stage 9 can verify it,
and a regression shows up as a failing unit test rather than as a teacher
discovering on Tuesday that Thursday's lesson was needed first.

What the model *does* get is everything a topological sort cannot produce: a
title a teacher recognises, a rationale that reads like a human wrote it, and a
sensible distribution of minutes inside a period.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "MAX_PERIODS",
    "Band",
    "PlanSkeleton",
    "build_skeleton",
    "default_time_allocation",
    "derive_period_count",
    "normalise_time_allocation",
    "partition_into_bands",
    "topological_order",
]

#: Instructional minutes one `core` concept is assumed to need (docs/03 § 4.3).
#: Not a universal truth — a tuned constant that produces plans teachers accept.
MINUTES_PER_CORE_CONCEPT = 12.0

#: Teaching load per concept by importance. `core` and `supporting` are the LLD's
#: 1.0 / 0.5; `enrichment` is weighted here rather than ignored because a document
#: whose extraction skewed to enrichment would otherwise derive one period and
#: then be forced to cram every concept into it.
IMPORTANCE_LOAD: Mapping[str, float] = {"core": 1.0, "supporting": 0.5, "enrichment": 0.25}
DEFAULT_LOAD = 0.5

#: Contract bound (`TeachingPlan.total_periods`). A 40-period plan from one
#: chapter is a derivation bug, not a long chapter.
MAX_PERIODS = 20

#: The period arc, as fractions of the period. Activate prior knowledge →
#: introduce → practise → check → consolidate. Used when the model declines to
#: allocate time, and as the shape its allocation is judged against.
DEFAULT_ARC: tuple[tuple[str, float], ...] = (
    ("Entry ticket — activate prior knowledge", 0.12),
    ("Direct instruction — introduce new material", 0.28),
    ("Guided practice", 0.30),
    ("Checkpoint — check for understanding", 0.15),
    ("Consolidation and exit ticket", 0.15),
)

_WORD = re.compile(r"[a-z0-9]+")
#: Words too common to make a lexical objective↔concept match meaningful.
_STOPWORDS = frozenset(
    [
        "a",
        "able",
        "an",
        "analyse",
        "analyze",
        "and",
        "apply",
        "are",
        "as",
        "at",
        "be",
        "by",
        "calculate",
        "compare",
        "describe",
        "evaluate",
        "explain",
        "for",
        "from",
        "how",
        "identify",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "state",
        "student",
        "students",
        "that",
        "the",
        "their",
        "them",
        "these",
        "this",
        "to",
        "understand",
        "use",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
    ]
)


# --------------------------------------------------------------- period count


def derive_period_count(
    concepts: Sequence[Mapping[str, Any]],
    period_duration_minutes: int,
    target: int | None = None,
) -> int:
    """How many periods this material needs (docs/03 § 4.3, SRS-4.2).

    Derived from teaching load and the length of a period, never fixed. A caller
    may override with ``target``, but the default is None precisely because a
    caller guessing is usually worse than the derivation.

    The count can never exceed the concept count: every period must teach at
    least one concept, so nine periods for four concepts is not a plan.
    """
    if target is not None:
        return max(1, min(int(target), MAX_PERIODS, max(len(concepts), 1)))

    load = sum(IMPORTANCE_LOAD.get(str(c.get("importance")), DEFAULT_LOAD) for c in concepts)
    capacity = max(period_duration_minutes, 1) / MINUTES_PER_CORE_CONCEPT
    derived = math.ceil(load / capacity) if capacity > 0 else 1
    return max(1, min(derived, MAX_PERIODS, max(len(concepts), 1)))


# ------------------------------------------------------------ topological sort


def topological_order(concept_ids: Sequence[str], edges: Iterable[Mapping[str, Any]]) -> list[str]:
    """Kahn's algorithm over the ``prerequisite_of`` subgraph.

    Ties are broken by the concept's position in the source document, which is
    what makes the output stable: the same knowledge base always produces the
    same plan, so a re-run does not silently reshuffle a teacher's week.

    Any cycle surviving stage 3's repair would strand nodes here. They are
    appended in document order rather than dropped — losing a concept is a worse
    failure than teaching one slightly out of sequence.
    """
    rank = {cid: i for i, cid in enumerate(concept_ids)}
    successors: dict[str, list[str]] = {cid: [] for cid in concept_ids}
    indegree: dict[str, int] = dict.fromkeys(concept_ids, 0)

    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.get("relation") != "prerequisite_of":
            continue
        source, target = edge.get("from_id"), edge.get("to_id")
        if source not in rank or target not in rank or source == target:
            continue
        if (source, target) in seen:
            continue
        seen.add((source, target))
        successors[source].append(target)
        indegree[target] += 1

    ready = sorted((cid for cid in concept_ids if indegree[cid] == 0), key=lambda c: rank[c])
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        newly: list[str] = []
        for nxt in successors[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                newly.append(nxt)
        if newly:
            ready = sorted([*ready, *newly], key=lambda c: rank[c])

    if len(ordered) != len(concept_ids):
        stranded = [cid for cid in concept_ids if cid not in set(ordered)]
        ordered.extend(stranded)
    return ordered


# ------------------------------------------------------------- band partition


def partition_into_bands(
    ordered_ids: Sequence[str], weights: Mapping[str, float], count: int
) -> list[list[str]]:
    """Split a topological order into ``count`` contiguous, load-balanced bands.

    Contiguity is the load-bearing property: because the input is a topological
    order and every band is a contiguous slice of it, a prerequisite can only
    ever land in the same band or an earlier one. Prerequisite correctness is
    therefore structural — there is no check to forget.

    Balance is exact rather than greedy: a dynamic program minimises the heaviest
    band. Greedy left-to-right filling routinely leaves the last period with one
    concept and 40 minutes, which is the front-loading that makes generated plans
    obviously machine-made.
    """
    items = list(ordered_ids)
    if not items:
        return []
    count = max(1, min(count, len(items)))
    if count == 1:
        return [items]

    n = len(items)
    load = [max(weights.get(cid, DEFAULT_LOAD), 0.0) for cid in items]
    prefix = [0.0] * (n + 1)
    for i, value in enumerate(load):
        prefix[i + 1] = prefix[i] + value

    def span(lo: int, hi: int) -> float:  # sum of load[lo:hi]
        return prefix[hi] - prefix[lo]

    # best[k][i] = minimal achievable heaviest band when the first i items are
    # split into k non-empty bands. Sizes here are chapter-sized (≤ 20 bands,
    # tens of concepts), so the cubic-ish DP is free.
    infinity = float("inf")
    best = [[infinity] * (n + 1) for _ in range(count + 1)]
    cut = [[0] * (n + 1) for _ in range(count + 1)]
    for i in range(1, n + 1):
        best[1][i] = span(0, i)

    for k in range(2, count + 1):
        for i in range(k, n + 1):
            for j in range(k - 1, i):
                candidate = max(best[k - 1][j], span(j, i))
                if candidate < best[k][i]:
                    best[k][i] = candidate
                    cut[k][i] = j

    bands: list[list[str]] = []
    end = n
    for k in range(count, 0, -1):
        start = cut[k][end] if k > 1 else 0
        bands.append(items[start:end])
        end = start
    bands.reverse()
    return bands


# ------------------------------------------------------------ time allocation


def default_time_allocation(duration_minutes: int) -> list[dict[str, Any]]:
    """The fallback period arc, scaled to the bell.

    Used when the model returns nothing usable. It is a defensible lesson shape
    rather than filler: a teacher handed only this still has a runnable period.
    """
    raw = [(label, duration_minutes * share) for label, share in DEFAULT_ARC]
    return _apportion(raw, duration_minutes)


#: A timetable label has to fit beside a clock reading, in a PDF cell and on a
#: phone. Beyond this it is instruction, not a label.
_MAX_LABEL_WORDS = 6


def _as_label(raw: str) -> str:
    """Reduce a model's slot description to something usable as a label.

    ``TimeSlot.label`` documents itself as "Entry ticket", "Guided practice" —
    a name. Models reliably answer with the *instruction* instead: a real run
    produced "Activate prior knowledge with demonstrations of everyday static
    electricity (sparks, charged plastic, hair standing); ask students to
    describe observations". Correct content, wrong field: rendered in a
    timetable cell it is a paragraph beside a number.

    So the deterministic half takes the first clause and caps its length, which
    is the same division of labour every generation stage uses — the model
    decides the emphasis and the wording, structure is not its call. The full
    sentence is not lost; the teacher script carries the instruction, at far
    more length than a label could.
    """
    text = " ".join(raw.split())
    if not text:
        return ""

    # The first clause is almost always the name: models write "Guided practice:
    # students calculate..." or "Hook - quick demonstration; then ask...".
    for separator in (":", ";", " - ", " — "):
        head, found, _ = text.partition(separator)
        if found and head.strip():
            text = head.strip()
            break

    words = text.split()
    if len(words) > _MAX_LABEL_WORDS:
        text = " ".join(words[:_MAX_LABEL_WORDS])
    return text.rstrip(" ,.;:-—").strip()


def normalise_time_allocation(
    slots: Sequence[Mapping[str, Any]], duration_minutes: int
) -> list[dict[str, Any]]:
    """Force a model's minutes onto the period budget.

    ``TeachingPlan`` requires each period to sum to its duration ± 5 %. Models
    produce 45 minutes of content for a 40-minute period roughly every time, so
    this rescales proportionally instead of asking more politely in the prompt —
    the labels and their relative emphasis are the model's judgement, the
    arithmetic is not.
    """
    cleaned: list[tuple[str, float]] = []
    for slot in slots:
        label = _as_label(str(slot.get("label") or ""))
        try:
            minutes = float(slot.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0.0
        if label and minutes > 0:
            cleaned.append((label, minutes))

    if not cleaned:
        return default_time_allocation(duration_minutes)

    # Every slot needs at least a minute, so a period cannot carry more slots
    # than it has minutes. Keep the ones the model weighted most heavily.
    if len(cleaned) > duration_minutes:
        cleaned = sorted(cleaned, key=lambda item: -item[1])[:duration_minutes]

    total = sum(minutes for _, minutes in cleaned)
    scale = duration_minutes / total if total else 1.0
    return _apportion([(label, minutes * scale) for label, minutes in cleaned], duration_minutes)


def _apportion(raw: Sequence[tuple[str, float]], duration_minutes: int) -> list[dict[str, Any]]:
    """Largest-remainder rounding to a whole-minute total, every slot ≥ 1."""
    target = max(duration_minutes, len(raw))
    floors = [max(1, int(minutes)) for _, minutes in raw]
    remainders = sorted(range(len(raw)), key=lambda i: (-(raw[i][1] - int(raw[i][1])), i))

    deficit = target - sum(floors)
    index = 0
    while deficit > 0 and remainders:
        floors[remainders[index % len(remainders)]] += 1
        deficit -= 1
        index += 1
    while deficit < 0:
        # Shave from the largest slot that can spare a minute.
        candidates = [i for i, value in enumerate(floors) if value > 1]
        if not candidates:
            break
        floors[max(candidates, key=lambda i: floors[i])] -= 1
        deficit += 1

    return [{"label": label, "minutes": floors[i]} for i, (label, _) in enumerate(raw)]


# ----------------------------------------------------------------- objectives


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


def map_objectives(
    objectives: Sequence[Mapping[str, Any]],
    bands: Sequence[Sequence[str]],
    concepts: Sequence[Mapping[str, Any]],
) -> tuple[list[list[str]], list[str]]:
    """Attach each objective to the period that completes it.

    An objective lands in the period where the *last* of its concepts is taught —
    that is the first point at which a student could actually demonstrate it, and
    therefore the only period whose exit ticket can honestly check it.

    Objectives whose ``concept_ids`` are empty or unresolvable get one lexical
    rescue attempt against concept names before being reported as unmapped.
    Silently dropping them would hide a real coverage hole; reporting them puts
    it in the validation report where a teacher sees it (SRS-4.5).
    """
    band_of: dict[str, int] = {cid: index for index, band in enumerate(bands) for cid in band}
    names = {str(c.get("concept_id")): _tokens(str(c.get("name") or "")) for c in concepts}

    per_band: list[list[str]] = [[] for _ in bands]
    unmapped: list[str] = []

    for objective in objectives:
        objective_id = str(objective.get("objective_id") or "").strip()
        if not objective_id:
            continue
        indices = [band_of[cid] for cid in objective.get("concept_ids") or [] if cid in band_of]
        if not indices:
            statement = _tokens(str(objective.get("statement") or ""))
            scored = [
                (len(statement & tokens), band_of[cid])
                for cid, tokens in names.items()
                if cid in band_of and statement & tokens
            ]
            if scored:
                indices = [max(scored)[1]]

        if not indices:
            unmapped.append(objective_id)
            continue
        per_band[max(indices)].append(objective_id)

    # A period with no objective is not teachable, and the contract rejects it.
    # Borrow from the nearest period that has one: objectives may legitimately
    # span periods, concepts may not.
    if any(per_band):
        for index, assigned in enumerate(per_band):
            if assigned:
                continue
            donor = min(
                (i for i, other in enumerate(per_band) if other),
                key=lambda i: (abs(i - index), i),
            )
            per_band[index] = [per_band[donor][0]]

    return per_band, unmapped


# ------------------------------------------------------------------ skeleton


@dataclass(slots=True)
class Band:
    """One period's deterministic content, before the model names it."""

    period_no: int
    concept_ids: list[str]
    objective_ids: list[str]
    load: float

    def concept_names(self, by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
        return [str(by_id[cid].get("name") or cid) for cid in self.concept_ids if cid in by_id]


@dataclass(slots=True)
class PlanSkeleton:
    """The full deterministic plan. The model may only decorate this."""

    bands: list[Band]
    period_duration_minutes: int
    unmapped_objective_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_periods(self) -> int:
        return len(self.bands)


def build_skeleton(
    knowledge: Mapping[str, Any],
    *,
    period_duration_minutes: int,
    target_period_count: int | None = None,
) -> PlanSkeleton:
    """Derive count, order, bands, and objective mapping in one deterministic pass.

    Raises ``ValueError`` when the knowledge base cannot support a plan at all —
    no concepts, or no objectives. Both are unrepresentable in ``TeachingPlan``
    (a period requires at least one of each), and inventing ids to fill them
    would produce a package whose cross-references point at nothing.
    """
    concepts = list(knowledge.get("concepts") or [])
    objectives = list(knowledge.get("learning_objectives") or [])
    if not concepts:
        raise ValueError("cannot build a teaching plan: the knowledge base contains no concepts")
    if not objectives:
        raise ValueError(
            "cannot build a teaching plan: the knowledge base contains no learning "
            "objectives, and every period must serve at least one"
        )

    concept_ids = [str(c["concept_id"]) for c in concepts]
    weights = {
        str(c["concept_id"]): IMPORTANCE_LOAD.get(str(c.get("importance")), DEFAULT_LOAD)
        for c in concepts
    }

    count = derive_period_count(concepts, period_duration_minutes, target_period_count)
    edges = (knowledge.get("concept_graph") or {}).get("edges") or []
    ordered = topological_order(concept_ids, edges)
    partitions = partition_into_bands(ordered, weights, count)
    objective_ids, unmapped = map_objectives(objectives, partitions, concepts)

    bands = [
        Band(
            period_no=index + 1,
            concept_ids=list(group),
            objective_ids=objective_ids[index],
            load=sum(weights.get(cid, DEFAULT_LOAD) for cid in group),
        )
        for index, group in enumerate(partitions)
    ]

    notes: list[str] = []
    if unmapped:
        notes.append(
            f"{len(unmapped)} objective(s) matched no concept in the plan and are reported unmapped"
        )
    if count != len(bands):
        notes.append(f"period count reduced from {count} to {len(bands)} by concept supply")

    return PlanSkeleton(
        bands=bands,
        period_duration_minutes=period_duration_minutes,
        unmapped_objective_ids=unmapped,
        notes=notes,
    )
