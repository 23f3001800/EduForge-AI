"""Per-stage evaluation: ten evaluators, one per pipeline stage.

The rubric in :mod:`evals.dimensions` asks "is this package good teaching?". This
module asks a different question — "did stage *n* do its job?" — and the two are
not interchangeable. A package can score well on coverage while stage 4 quietly
scheduled a concept before its own prerequisite, because the rubric looks at the
finished artifact and this looks at each stage's contract with the next one.

Almost everything here is arithmetic over the published package, which is the
point. Three kinds of check recur, and they are worth naming:

* **Completeness** — did the stage fill in what it owes? Fraction of concepts
  with evidence, fraction of items with an answer key.
* **Referential integrity** — do the identifiers it emitted resolve? An
  ``activity_ref`` pointing at no activity is a defect no amount of good prose
  compensates for.
* **Self-consistency** — does the stage's own report of its work survive being
  recomputed? Stage 9 publishes a coverage summary; this recomputes it from the
  package and compares. A validator that reports numbers nobody re-derives is a
  validator nobody has checked.

The third is the one that catches real bugs, because it is the only class of
check the generating stage cannot satisfy by construction.

Where a metric genuinely cannot be computed, it is reported as
``NOT_MEASURABLE`` with what it would take — see :mod:`evals.framework` for why
that is preferable to a plausible number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evals.context import EvalContext
from evals.context import coerce_int as _int
from evals.framework import (
    Evidence,
    MetricResult,
    Recommendation,
    StageEvaluation,
    judged,
    measured,
    not_measurable,
)
from evals.text import contains_verbatim, word_count

__all__ = ["STAGE_EVALUATORS", "evaluate_stage", "evaluate_stages"]


#: Stages that make no model call, and so can never appear in
#: ``generator.models_by_stage``. Read against the two places that decide it:
#: ``orchestration.pipeline.build_stages`` constructs ``DocumentIntelligenceStage``
#: with no ``llm`` argument, and ``PublishingStage()`` with none either;
#: ``stages.s10_publishing.assemble._generator_fields`` omits both deliberately,
#: on the grounds that an absent entry means "no model was involved" and is more
#: informative than an empty string.
#:
#: The previous set here excluded ``validation`` and included
#: ``document-intelligence``, which was wrong on both counts: stage 1 never calls
#: a model, so demanding an attribution for it capped a flawless live run at
#: 87.5%, while stage 9 *does* call one — ``judge_claims`` — whenever a claim
#: lands in the ambiguous band, and its attribution went unchecked.
_NON_GENERATIVE_STAGES: frozenset[str] = frozenset({"document-intelligence", "publishing"})


# ─────────────────────────────────────────────────────────────── small helpers


def _pct(numerator: float, denominator: float) -> float:
    """A share as 0-100. An empty denominator is 100: nothing owed, nothing owing.

    Callers must not pass ``max(n, 1)`` as the denominator to dodge the zero case.
    That converts "there was nothing to check" into "nothing passed", which is the
    opposite answer — see ``concept_scheduling``, where it charged stage 3's empty
    output to stage 4 as a hard zero at weight 2.0.
    """
    if denominator <= 0:
        return 100.0
    return 100.0 * numerator / denominator


def _ev(path: str, observation: str) -> Evidence:
    return Evidence(path=path, observation=observation)


def _fix(action: str, impact: str, severity: str = "medium") -> Recommendation:
    return Recommendation(action=action, impact=impact, severity=severity)  # type: ignore[arg-type]


def _as_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _present(mapping: Mapping[str, Any], fields: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split ``fields`` into those populated on ``mapping`` and those not."""
    have = [f for f in fields if mapping.get(f) not in (None, "", [], {})]
    missing = [f for f in fields if f not in have]
    return have, missing


def _completeness(
    key: str,
    label: str,
    items: Sequence[Mapping[str, Any]],
    field: str,
    *,
    id_field: str,
    base: str,
    what: str,
    weight: float = 1.0,
) -> MetricResult:
    """The recurring shape: what share of ``items`` populated ``field``.

    Written once because it appears fourteen times across the ten stages, and
    fourteen hand-rolled versions would drift in how they treat an empty list.
    """
    if not items:
        return not_measurable(
            key,
            label,
            f"No {what} were produced, so there is nothing to check for {field}.",
            needed=f"a run that produces at least one {what[:-1] if what.endswith('s') else what}",
        )

    missing = [
        str(item.get(id_field) or f"#{i}") for i, item in enumerate(items) if not item.get(field)
    ]
    score = _pct(len(items) - len(missing), len(items))
    evidence = [
        _ev(f"{base}/{i}", f"{item.get(id_field) or f'#{i}'} has no {field}")
        for i, item in enumerate(items)
        if not item.get(field)
    ][:5]

    return measured(
        key,
        label,
        score,
        f"{len(items) - len(missing)} of {len(items)} {what} carry {field}."
        + (f" Missing on: {', '.join(missing[:5])}." if missing else ""),
        weight=weight,
        evidence=evidence,
        recommendations=(
            [
                _fix(
                    f"Populate {field} for the {len(missing)} {what} that lack it.",
                    f"A teacher reading those {what} has no {field} to work from.",
                    "high" if score < 70 else "medium",
                )
            ]
            if missing
            else []
        ),
    )


# ───────────────────────────────────────────────── 1 · document intelligence


def _stage_document_intelligence(ctx: EvalContext) -> StageEvaluation:
    source = ctx.package.get("source")
    source = source if isinstance(source, Mapping) else {}
    metrics: list[MetricResult] = []

    fields = (
        "filename",
        "mime",
        "sha256",
        "size_bytes",
        "page_count",
        "word_count",
        "detected_language",
    )
    have, missing = _present(source, fields)
    metrics.append(
        measured(
            "source_metadata",
            "Source metadata captured",
            _pct(len(have), len(fields)),
            f"{len(have)} of {len(fields)} source fields recorded"
            + (f"; missing {', '.join(missing)}." if missing else "."),
            evidence=[_ev("/source", f"recorded: {', '.join(have)}")],
            recommendations=(
                [
                    _fix(
                        f"Record {', '.join(missing)} at parse time.",
                        "Provenance cannot be audited without it.",
                        "low",
                    )
                ]
                if missing
                else []
            ),
        )
    )

    pages = _int(source.get("page_count"))
    words = _int(source.get("word_count"))
    if pages and words:
        # A born-digital page of prose runs 200-600 words. Far below that means
        # the extractor returned page furniture and little else — the signature
        # of a scanned page slipping through, which this pipeline is meant to
        # reject rather than silently under-extract.
        per_page = words / pages
        score = 100.0 if per_page >= 120 else _pct(per_page, 120)
        metrics.append(
            measured(
                "text_yield",
                "Text extracted per page",
                score,
                f"{per_page:.0f} words per page across {pages} pages. "
                + (
                    "Consistent with a born-digital document."
                    if per_page >= 120
                    else "Low enough to suggest the source was image-heavy or scanned."
                ),
                evidence=[_ev("/source/word_count", f"{words:,} words over {pages} pages")],
                recommendations=(
                    []
                    if per_page >= 120
                    else [
                        _fix(
                            "Check whether the source is scanned; the parser rejects "
                            "image-only pages by design.",
                            "Downstream stages are working from very little text.",
                            "high",
                        )
                    ]
                ),
            )
        )
    else:
        metrics.append(
            not_measurable(
                "text_yield",
                "Text extracted per page",
                "Page or word count was not recorded.",
                needed="page_count and word_count on /source",
            )
        )

    if ctx.chunks:
        empty = [cid for cid, text in ctx.chunks.items() if not text.strip()]
        metrics.append(
            measured(
                "chunk_integrity",
                "Chunks carry text",
                _pct(len(ctx.chunks) - len(empty), len(ctx.chunks)),
                f"{len(ctx.chunks) - len(empty)} of {len(ctx.chunks)} chunks hold text. "
                "Empty chunks break every citation that lands on them.",
                evidence=[_ev("/chunks", f"{len(ctx.chunks)} chunks retained")],
            )
        )
    else:
        metrics.append(
            not_measurable(
                "chunk_integrity",
                "Chunks carry text",
                "Source chunks were not supplied to the evaluator.",
                needed="the run's chunk set, which the API supplies from blob storage",
            )
        )

    # OCR now runs, so this stopped being one metric and became two questions.
    # How *sure* the recogniser was is reported by the engine and can be scored.
    # Whether it was *right* still cannot: that needs a reference transcript of
    # the scanned pages, which no uploader supplies.
    ocr = source.get("ocr")
    ocr = ocr if isinstance(ocr, Mapping) else None
    if ocr is None:
        metrics.append(
            not_measurable(
                "ocr_confidence",
                "OCR confidence",
                "No page needed OCR: every page carried a text layer, so nothing "
                "was read from an image and there is no confidence to report.",
                needed="a document with at least one scanned page",
            )
        )
    else:
        confidence = ocr.get("confidence")
        engine = str(ocr.get("engine") or "unknown")
        read = list(ocr.get("pages") or [])
        unread = list(ocr.get("failed_pages") or [])

        if isinstance(confidence, int | float):
            threshold = ocr.get("min_confidence")
            floor = float(threshold) if isinstance(threshold, int | float) else 0.8
            metrics.append(
                measured(
                    "ocr_confidence",
                    "OCR confidence",
                    100.0 * float(confidence),
                    f"{engine} read {len(read)} page(s) at a mean confidence of "
                    f"{float(confidence):.0%} against a {floor:.0%} floor. This is the "
                    "recogniser's own certainty, not a check that it was correct.",
                    weight=2.0,
                    confidence=0.9,
                    evidence=[_ev("/source/ocr", f"pages {read} read by {engine}")],
                    recommendations=(
                        [
                            _fix(
                                "Have a teacher check the OCR'd pages against the "
                                "original before teaching from them.",
                                "Every citation downstream is verified against this "
                                "text, so a misread is confirmed by those checks "
                                "rather than caught by them.",
                                "high",
                            )
                        ]
                        if float(confidence) < floor
                        else []
                    ),
                )
            )
        else:
            metrics.append(
                not_measurable(
                    "ocr_confidence",
                    "OCR confidence",
                    f"{engine} read {len(read)} page(s) but reports no confidence, "
                    "so how far to trust that text is genuinely unknown.",
                    needed="an engine that scores its own output, such as Azure "
                    "Document Intelligence or Tesseract",
                )
            )

        if unread:
            metrics.append(
                measured(
                    "ocr_page_recovery",
                    "Scanned pages recovered",
                    _pct(len(read), len(read) + len(unread)),
                    f"{len(read)} of {len(read) + len(unread)} page(s) without a text "
                    f"layer were recovered; page(s) {unread} were not, so their content "
                    "is absent from this package.",
                    weight=2.0,
                    evidence=[_ev("/source/ocr/failed_pages", f"unrecovered: {unread}")],
                    recommendations=[
                        _fix(
                            "Re-run with an OCR tier that has no per-request page cap.",
                            "Content on those pages is missing entirely, and nothing "
                            "downstream can tell it was ever there.",
                            "high",
                        )
                    ],
                )
            )

    metrics.append(
        not_measurable(
            "ocr_accuracy",
            "OCR accuracy",
            "Accuracy is a comparison against what the page actually said, and no "
            "uploader supplies a transcript of their own scan. Confidence is "
            "reported instead, which is the recogniser's certainty, not its "
            "correctness — the two come apart exactly when it matters.",
            needed="reference transcriptions of the scanned pages to diff against",
        )
    )
    metrics.append(
        not_measurable(
            "extraction_fidelity",
            "Extraction fidelity vs. original",
            "Fidelity is a comparison, and the original document's ground-truth text "
            "is not part of the package.",
            needed="a hand-checked transcript of the source PDF to diff the extraction against",
        )
    )

    return StageEvaluation(
        stage="document-intelligence",
        label="Document intelligence",
        metrics=metrics,
        missing=[] if source else ["/source is absent; nothing about the input can be checked"],
    )


# ────────────────────────────────────────────── 2 · educational classification


def _stage_classification(ctx: EvalContext) -> StageEvaluation:
    cls = ctx.classification
    metrics: list[MetricResult] = []

    fields = (
        "subject",
        "topic",
        "grade_band",
        "difficulty",
        "language",
        "pedagogy_profile",
        "category",
    )
    have, missing = _present(cls, fields)
    metrics.append(
        measured(
            "classification_completeness",
            "Classification fields populated",
            _pct(len(have), len(fields)),
            f"{len(have)} of {len(fields)} fields classified"
            + (f"; missing {', '.join(missing)}." if missing else "."),
            weight=1.5,
            evidence=[
                _ev(
                    "/classification",
                    f"subject={cls.get('subject')!r}, profile={cls.get('pedagogy_profile')!r}",
                )
            ],
        )
    )

    valid_profiles = {"quantitative", "conceptual", "narrative", "procedural", "mixed"}
    profile = str(cls.get("pedagogy_profile") or "")
    metrics.append(
        measured(
            "profile_validity",
            "Pedagogy profile is one the pipeline routes on",
            100.0 if profile in valid_profiles else 0.0,
            f"Profile {profile!r} "
            + (
                "is a routable profile; every downstream stage branches on it."
                if profile in valid_profiles
                else f"is not in {sorted(valid_profiles)} — downstream routing falls back to mixed."
            ),
            weight=2.0,
            evidence=[_ev("/classification/pedagogy_profile", profile or "(absent)")],
            recommendations=(
                []
                if profile in valid_profiles
                else [
                    _fix(
                        "Constrain the classifier's output to the profile enum.",
                        "Routing silently degrades to the generic path.",
                        "high",
                    )
                ]
            ),
        )
    )

    confidences = cls.get("confidences")
    confidences = confidences if isinstance(confidences, Mapping) else {}
    if confidences:
        values = [float(v) for v in confidences.values() if isinstance(v, int | float)]
        mean_conf = sum(values) / len(values) if values else 0.0
        # A self-report, and labelled as one. It measures how sure the classifier
        # said it was, which is not the same as how right it was — that second
        # question is the not-measurable one below.
        metrics.append(
            measured(
                "self_reported_confidence",
                "Classifier's own confidence",
                100.0 * mean_conf,
                f"Mean self-reported confidence {mean_conf:.2f} across "
                f"{', '.join(sorted(confidences))}. This is the classifier's own estimate, "
                "not an accuracy measurement.",
                weight=0.5,
                confidence=1.0,
                evidence=[_ev("/classification/confidences", str(dict(confidences)))],
            )
        )

        # The consistency check that has teeth: a field the classifier scored low
        # must appear in the list it publishes as low-confidence, or the review
        # flag it drives never fires.
        threshold = 0.7
        should_flag = {
            k for k, v in confidences.items() if isinstance(v, int | float) and float(v) < threshold
        }
        flagged = {str(f) for f in (cls.get("low_confidence_fields") or [])}
        undeclared = should_flag - flagged
        metrics.append(
            measured(
                "low_confidence_declared",
                "Low-confidence fields flagged for review",
                _pct(len(should_flag) - len(undeclared), max(len(should_flag), 1))
                if should_flag
                else 100.0,
                (
                    f"{len(undeclared)} field(s) scored below {threshold} without being flagged: "
                    f"{', '.join(sorted(undeclared))}."
                    if undeclared
                    else f"Every field scored below {threshold} is flagged for review."
                ),
                weight=1.5,
                evidence=[_ev("/classification/low_confidence_fields", str(sorted(flagged)))],
                recommendations=(
                    [
                        _fix(
                            "Derive low_confidence_fields from the confidences map rather than "
                            "letting the model populate both independently.",
                            "A field the classifier doubted reaches teachers unflagged.",
                            "high",
                        )
                    ]
                    if undeclared
                    else []
                ),
            )
        )
    else:
        metrics.append(
            not_measurable(
                "self_reported_confidence",
                "Classifier's own confidence",
                "No per-field confidences were recorded.",
                needed="/classification/confidences populated by stage 2",
            )
        )

    metrics.append(
        not_measurable(
            "subject_accuracy",
            "Subject / grade classification accuracy",
            "Accuracy needs labels. There is no corpus of documents with agreed subject and "
            "grade-band annotations to score this run against.",
            needed="a held-out set of documents labelled by teachers, ideally 100+ across subjects",
        )
    )

    return StageEvaluation(
        stage="educational-classification", label="Educational classification", metrics=metrics
    )


# ─────────────────────────────────────────────── 3 · knowledge extraction


def _stage_knowledge(ctx: EvalContext) -> StageEvaluation:
    metrics: list[MetricResult] = []
    concepts = ctx.concepts
    objectives = ctx.objectives

    metrics.append(
        _completeness(
            "concept_evidence",
            "Concepts carry evidence",
            concepts,
            "evidence",
            id_field="concept_id",
            base="/knowledge/concepts",
            what="concepts",
            weight=2.0,
        )
    )
    metrics.append(
        _completeness(
            "concept_summary",
            "Concepts carry a summary",
            concepts,
            "summary",
            id_field="concept_id",
            base="/knowledge/concepts",
            what="concepts",
        )
    )

    # Citation integrity: does the quote actually appear in the chunk it cites?
    # This is the single most valuable measurement in the framework — it is the
    # only one that can catch a fabricated citation, and it needs no model.
    spans = [
        (i, span)
        for i, concept in enumerate(concepts)
        for span in _as_list(concept.get("evidence"))
    ]
    if not ctx.chunks:
        metrics.append(
            not_measurable(
                "citation_integrity",
                "Quotes appear in the chunks they cite",
                "Verifying a quote needs the chunk it points at, and no chunks were supplied.",
                needed="the run's source chunks",
            )
        )
    elif not spans:
        metrics.append(
            not_measurable(
                "citation_integrity",
                "Quotes appear in the chunks they cite",
                "No evidence spans were emitted, so there are no citations to verify.",
                needed="concepts with at least one evidence span",
            )
        )
    else:
        bad: list[tuple[int, str]] = []
        for i, span in spans:
            chunk = ctx.chunks.get(str(span.get("chunk_id") or ""))
            quote = str(span.get("quote") or "")
            if chunk is None:
                bad.append((i, f"cites unknown chunk {span.get('chunk_id')!r}"))
            elif not contains_verbatim(quote, chunk):
                bad.append((i, f"quote not found in {span.get('chunk_id')}: {quote[:60]!r}"))

        metrics.append(
            measured(
                "citation_integrity",
                "Quotes appear in the chunks they cite",
                _pct(len(spans) - len(bad), len(spans)),
                f"{len(spans) - len(bad)} of {len(spans)} evidence spans quote text that is "
                "present verbatim in the chunk they cite."
                + (f" {len(bad)} do not." if bad else ""),
                weight=3.0,
                evidence=[
                    _ev(f"/knowledge/concepts/{i}/evidence", detail) for i, detail in bad[:5]
                ],
                recommendations=(
                    [
                        _fix(
                            "Re-run extraction with the citation verifier rejecting spans whose "
                            "quote is not substring-present in the cited chunk.",
                            "A citation that does not check out is worse than no citation — a "
                            "teacher trusts it.",
                            "high",
                        )
                    ]
                    if bad
                    else []
                ),
            )
        )

    blooms = [str(o.get("bloom_level") or "") for o in objectives]
    with_bloom = [b for b in blooms if b]
    if objectives:
        metrics.append(
            measured(
                "objective_bloom",
                "Objectives carry a Bloom level",
                _pct(len(with_bloom), len(objectives)),
                f"{len(with_bloom)} of {len(objectives)} objectives are tagged with a Bloom "
                f"level; {len(set(with_bloom))} distinct level(s) used.",
                weight=1.5,
                evidence=[
                    _ev(
                        "/knowledge/learning_objectives",
                        f"levels: {sorted(set(with_bloom)) or 'none'}",
                    )
                ],
            )
        )
    else:
        metrics.append(
            not_measurable(
                "objective_bloom",
                "Objectives carry a Bloom level",
                "No learning objectives were extracted.",
                needed="a run where stage 3 emits objectives",
            )
        )

    graph = ctx.concept_graph
    node_ids = {str(n) for n in (graph.get("node_ids") or [])}
    edges = _as_list(graph.get("edges"))
    concept_ids = ctx.concept_ids
    if node_ids or edges:
        dangling = [
            e
            for e in edges
            if str(e.get("from_id")) not in concept_ids or str(e.get("to_id")) not in concept_ids
        ]
        orphan_nodes = node_ids - concept_ids
        problems = len(dangling) + len(orphan_nodes)
        total = max(len(edges) + len(node_ids), 1)
        metrics.append(
            measured(
                "graph_integrity",
                "Concept graph resolves to real concepts",
                _pct(total - problems, total),
                f"{len(edges)} edges over {len(node_ids)} nodes. "
                + (
                    f"{len(dangling)} edge(s) and {len(orphan_nodes)} node(s) reference "
                    "concept ids that do not exist."
                    if problems
                    else "Every endpoint resolves to an extracted concept."
                ),
                weight=1.5,
                evidence=[
                    _ev("/knowledge/concept_graph/edges", f"{e.get('from_id')} -> {e.get('to_id')}")
                    for e in dangling[:5]
                ],
                recommendations=(
                    [
                        _fix(
                            "Filter graph edges against the concept id set before publishing.",
                            "Stage 4 sequences on this graph; a dangling edge is silently dropped.",
                            "high",
                        )
                    ]
                    if problems
                    else []
                ),
            )
        )
    else:
        metrics.append(
            not_measurable(
                "graph_integrity",
                "Concept graph resolves to real concepts",
                "No concept graph was produced.",
                needed="stage 3 emitting concept_graph.edges",
            )
        )

    return StageEvaluation(
        stage="knowledge-extraction",
        label="Knowledge extraction",
        metrics=metrics,
        missing=(["no concepts extracted"] if not concepts else [])
        + (["no learning objectives extracted"] if not objectives else []),
    )


# ──────────────────────────────────────────────────── 4 · teaching planner


def _stage_planner(ctx: EvalContext) -> StageEvaluation:
    metrics: list[MetricResult] = []
    periods = ctx.periods
    concept_ids = ctx.concept_ids

    if not periods:
        return StageEvaluation(
            stage="teaching-planner",
            label="Teaching planner",
            metrics=[
                not_measurable(
                    "plan_present",
                    "A teaching plan exists",
                    "No periods were planned.",
                    needed="stage 4 emitting teaching_plan.periods",
                )
            ],
            missing=["teaching_plan.periods is empty"],
        )

    scheduled = set(ctx.period_of_concept())
    untaught = sorted(concept_ids - scheduled)
    if not concept_ids:
        # `max(len(concept_ids), 1)` used to sit in the denominator here, which
        # turned "stage 3 extracted nothing" into "stage 4 scheduled 0% of the
        # concepts" — a hard zero at weight 2.0, charged to the stage that had
        # nothing to schedule. Stage 4 cannot be graded on a plan for no concepts.
        metrics.append(
            not_measurable(
                "concept_scheduling",
                "Every concept is scheduled into a period",
                "No concepts were extracted, so there is nothing for the plan to schedule. "
                "This is stage 3's gap and cannot be charged to stage 4.",
                needed="at least one concept from knowledge extraction",
            )
        )
    else:
        metrics.append(
            measured(
                "concept_scheduling",
                "Every concept is scheduled into a period",
                _pct(len(concept_ids) - len(untaught), len(concept_ids)),
                f"{len(concept_ids) - len(untaught)} of {len(concept_ids)} concepts are taught in "
                f"some period." + (f" Untaught: {', '.join(untaught[:5])}." if untaught else ""),
                weight=2.0,
                evidence=[_ev("/teaching_plan/periods", f"{len(periods)} periods scheduled")],
                recommendations=(
                    [
                        _fix(
                            "Extend the plan or drop the concepts nothing teaches.",
                            "A concept extracted but never taught is work the teacher paid for "
                            "and cannot use.",
                            "high",
                        )
                    ]
                    if untaught
                    else []
                ),
            )
        )

    # Prerequisite order — the check the finished artifact cannot answer for
    # itself. An edge A -> B means A must be taught no later than B.
    edges = [
        e
        for e in _as_list(ctx.concept_graph.get("edges"))
        if str(e.get("relation")) == "prerequisite_of"
    ]
    order = ctx.period_of_concept()
    checkable = [
        e for e in edges if str(e.get("from_id")) in order and str(e.get("to_id")) in order
    ]
    if checkable:
        violations = [
            e for e in checkable if order[str(e.get("from_id"))] > order[str(e.get("to_id"))]
        ]
        metrics.append(
            measured(
                "prerequisite_order",
                "Prerequisites are taught before what needs them",
                _pct(len(checkable) - len(violations), len(checkable)),
                f"{len(checkable) - len(violations)} of {len(checkable)} prerequisite edges are "
                "respected by the period order."
                + (
                    f" {len(violations)} concept(s) are taught before their prerequisite."
                    if violations
                    else ""
                ),
                weight=2.5,
                evidence=[
                    _ev(
                        "/teaching_plan/periods",
                        f"{ctx.concept_name(str(e.get('from_id')))} (period "
                        f"{order[str(e.get('from_id'))]}) is a prerequisite of "
                        f"{ctx.concept_name(str(e.get('to_id')))} (period "
                        f"{order[str(e.get('to_id'))]})",
                    )
                    for e in violations[:5]
                ],
                recommendations=(
                    [
                        _fix(
                            "Topologically sort concepts on the prerequisite graph before "
                            "allocating periods.",
                            "Students meet a dependent idea before the one it rests on.",
                            "high",
                        )
                    ]
                    if violations
                    else []
                ),
            )
        )
    else:
        metrics.append(
            not_measurable(
                "prerequisite_order",
                "Prerequisites are taught before what needs them",
                "The concept graph declares no prerequisite edges between scheduled "
                "concepts, so there is no ordering constraint to check.",
                needed="prerequisite_of edges from stage 3",
            )
        )

    budget = ctx.period_minutes
    if budget:
        overruns: list[tuple[int, int]] = []
        for period in periods:
            allocation = period.get("time_allocation")
            spent = (
                sum(_int(seg.get("minutes")) for seg in _as_list(allocation))
                if isinstance(allocation, list)
                else 0
            )
            if spent > budget:
                overruns.append((_int(period.get("period_no")), spent))
        metrics.append(
            measured(
                "time_budget",
                "Period plans fit the period",
                _pct(len(periods) - len(overruns), len(periods)),
                f"{len(periods) - len(overruns)} of {len(periods)} periods allocate no more than "
                f"the {budget}-minute period."
                + (
                    f" Over budget: {', '.join(f'period {n} at {m} min' for n, m in overruns)}."
                    if overruns
                    else ""
                ),
                weight=1.5,
                evidence=[
                    _ev(
                        f"/teaching_plan/periods/{n - 1}/time_allocation",
                        f"{m} minutes allocated against a {budget}-minute period",
                    )
                    for n, m in overruns[:5]
                ],
                recommendations=(
                    [
                        _fix(
                            "Rescale segment minutes to the period length in the deterministic "
                            "half of stage 4.",
                            "A plan that does not fit the bell is a plan the teacher abandons "
                            "mid-lesson.",
                            "high",
                        )
                    ]
                    if overruns
                    else []
                ),
            )
        )
    else:
        metrics.append(
            not_measurable(
                "time_budget",
                "Period plans fit the period",
                "The plan does not state a period duration.",
                needed="teaching_plan.period_duration_minutes",
            )
        )

    return StageEvaluation(stage="teaching-planner", label="Teaching planner", metrics=metrics)


# ──────────────────────────────────────────────────── 5 · lesson generation


def _stage_lessons(ctx: EvalContext) -> StageEvaluation:
    metrics: list[MetricResult] = []
    content = ctx.classroom_content
    periods = ctx.periods

    if periods:
        covered = {_int(c.get("period_no")) for c in content}
        planned = {_int(p.get("period_no")) for p in periods}
        gaps = sorted(planned - covered)
        metrics.append(
            measured(
                "period_coverage",
                "Every planned period has classroom content",
                _pct(len(planned) - len(gaps), max(len(planned), 1)),
                f"{len(planned) - len(gaps)} of {len(planned)} planned periods have generated "
                f"content." + (f" Missing: periods {gaps}." if gaps else ""),
                weight=2.0,
                evidence=[
                    _ev(
                        "/classroom_content",
                        f"{len(content)} content blocks for {len(planned)} periods",
                    )
                ],
                recommendations=(
                    [
                        _fix(
                            "Re-run stage 5 for the periods with no content.",
                            "The teacher has a plan for those periods and nothing to teach from.",
                            "high",
                        )
                    ]
                    if gaps
                    else []
                ),
            )
        )

    blocks = (
        "teacher_script",
        "blackboard_notes",
        "checkpoint_questions",
        "entry_ticket",
        "exit_ticket",
        "homework",
    )
    if content:
        filled = sum(len(_present(c, blocks)[0]) for c in content)
        total = len(content) * len(blocks)
        thin = [
            (_int(c.get("period_no")), _present(c, blocks)[1])
            for c in content
            if _present(c, blocks)[1]
        ]
        metrics.append(
            measured(
                "lesson_block_completeness",
                "Each period carries the full set of lesson blocks",
                _pct(filled, total),
                f"{filled} of {total} lesson blocks are populated across {len(content)} periods."
                + (
                    f" Thinnest: period {thin[0][0]} missing {', '.join(thin[0][1])}."
                    if thin
                    else ""
                ),
                weight=1.5,
                evidence=[
                    _ev(f"/classroom_content/{i}", f"period {n} missing: {', '.join(m)}")
                    for i, (n, m) in enumerate(thin[:5])
                ],
            )
        )

        # Volume, not quality — said plainly, and weighted like a proxy. 250 words
        # is roughly what a 40-minute period's spoken guidance runs to; below it,
        # the teacher is improvising.
        lengths = [word_count(str(c.get("teacher_script") or "")) for c in content]
        mean_fill = sum(min(1.0, n / 250) for n in lengths) / len(lengths)
        metrics.append(
            measured(
                "script_substance",
                "Teacher scripts have enough to work from",
                100.0 * mean_fill,
                f"Teacher scripts average {sum(lengths) // len(lengths)} words per period "
                "against a 250-word working floor. This measures volume, not teaching quality.",
                weight=0.5,
                evidence=[
                    _ev(
                        "/classroom_content/0/teacher_script",
                        f"{word_count(str(content[0].get('teacher_script') or ''))} words",
                    )
                ],
            )
        )

        refs = [str(r) for c in content for r in (c.get("activity_refs") or [])]
        activity_ids = {str(a.get("activity_id")) for a in ctx.activities}
        if refs:
            dangling = [r for r in refs if r not in activity_ids]
            metrics.append(
                measured(
                    "activity_ref_integrity",
                    "Activity references resolve",
                    _pct(len(refs) - len(dangling), len(refs)),
                    f"{len(refs) - len(dangling)} of {len(refs)} activity references point at an "
                    "activity that exists."
                    + (f" Dangling: {', '.join(sorted(set(dangling))[:5])}." if dangling else ""),
                    weight=2.0,
                    evidence=[
                        _ev("/classroom_content", f"unresolved ref {r}")
                        for r in sorted(set(dangling))[:5]
                    ],
                    recommendations=(
                        [
                            _fix(
                                "Resolve activity_refs against the activity bank in stage 10's "
                                "assembly, and fail the build on a dangling reference.",
                                "The lesson tells the teacher to run an activity that is not in "
                                "the package.",
                                "high",
                            )
                        ]
                        if dangling
                        else []
                    ),
                )
            )
    else:
        metrics.append(
            not_measurable(
                "lesson_block_completeness",
                "Each period carries the full set of lesson blocks",
                "No classroom content was generated.",
                needed="stage 5 output",
            )
        )

    return StageEvaluation(
        stage="lesson-generation",
        label="Lesson generation",
        metrics=metrics,
        missing=["classroom_content is empty"] if not content else [],
    )


# ────────────────────────────────────────────────── 6 · activity generation


def _stage_activities(ctx: EvalContext) -> StageEvaluation:
    activities = ctx.activities
    if not activities:
        return StageEvaluation(
            stage="activity-generation",
            label="Activity generation",
            metrics=[
                not_measurable(
                    "activities_present",
                    "Activities were generated",
                    "No activities are in the package.",
                    needed="stage 6 output",
                )
            ],
            missing=["activities is empty"],
        )

    metrics: list[MetricResult] = []
    kinds = [str(a.get("type") or "") for a in activities]
    distinct = len({k for k in kinds if k})
    # Four distinct types across a package is the point where a week of lessons
    # stops feeling like the same exercise repeated.
    target = min(4, len(activities))
    metrics.append(
        measured(
            "type_variety",
            "Activities vary in kind",
            _pct(distinct, target),
            f"{distinct} distinct activity type(s) across {len(activities)} activities "
            f"({', '.join(sorted({k for k in kinds if k}))}), against a target of {target}.",
            weight=1.5,
            evidence=[_ev("/activities", f"types: {sorted(set(kinds))}")],
            recommendations=(
                [
                    _fix(
                        "Widen the type weighting for this pedagogy profile in stage 6.",
                        "Repeating one activity format across a unit loses the class.",
                        "medium",
                    )
                ]
                if distinct < target
                else []
            ),
        )
    )

    concept_ids = ctx.concept_ids
    linked = [a for a in activities if {str(c) for c in (a.get("concept_ids") or [])} & concept_ids]
    metrics.append(
        measured(
            "concept_linkage",
            "Activities target extracted concepts",
            _pct(len(linked), len(activities)),
            f"{len(linked)} of {len(activities)} activities reference at least one concept that "
            "stage 3 actually extracted.",
            weight=2.0,
            evidence=[
                _ev(f"/activities/{i}", f"{a.get('activity_id')} references {a.get('concept_ids')}")
                for i, a in enumerate(activities)
                if a not in linked
            ][:5],
        )
    )

    metrics.append(
        _completeness(
            "teacher_instructions",
            "Activities carry teacher instructions",
            activities,
            "teacher_instructions",
            id_field="activity_id",
            base="/activities",
            what="activities",
            weight=1.5,
        )
    )
    metrics.append(
        _completeness(
            "success_criteria",
            "Activities state success criteria",
            activities,
            "success_criteria",
            id_field="activity_id",
            base="/activities",
            what="activities",
        )
    )
    metrics.append(
        _completeness(
            "differentiation",
            "Activities carry differentiation",
            activities,
            "differentiation",
            id_field="activity_id",
            base="/activities",
            what="activities",
        )
    )

    budget = ctx.period_minutes
    if budget:
        overruns = [a for a in activities if _int(a.get("duration_minutes")) > budget]
        metrics.append(
            measured(
                "timing_fit",
                "Activities fit inside a period",
                _pct(len(activities) - len(overruns), len(activities)),
                f"{len(activities) - len(overruns)} of {len(activities)} activities run within "
                f"the {budget}-minute period.",
                evidence=[
                    _ev(
                        f"/activities/{i}",
                        f"{a.get('activity_id')} runs {a.get('duration_minutes')} min",
                    )
                    for i, a in enumerate(activities)
                    if a in overruns
                ][:5],
            )
        )

    return StageEvaluation(
        stage="activity-generation", label="Activity generation", metrics=metrics
    )


# ──────────────────────────────────────────────── 7 · assessment generation


def _stage_assessments(ctx: EvalContext) -> StageEvaluation:
    items = ctx.items
    if not items:
        return StageEvaluation(
            stage="assessment-generation",
            label="Assessment generation",
            metrics=[
                not_measurable(
                    "items_present",
                    "Assessment items were generated",
                    "The assessment bank is empty.",
                    needed="stage 7 output",
                )
            ],
            missing=["assessments.items is empty"],
        )

    metrics: list[MetricResult] = []

    # An item without an answer is not an assessment, it is a question. The
    # rubric field carries open-response items, where a single answer string is
    # the wrong shape.
    unanswerable = [
        i
        for i in items
        if not i.get("answer") and not i.get("rubric") and not i.get("expected_answer")
    ]
    metrics.append(
        measured(
            "answer_key",
            "Every item can be marked",
            _pct(len(items) - len(unanswerable), len(items)),
            f"{len(items) - len(unanswerable)} of {len(items)} items carry an answer or a rubric.",
            weight=3.0,
            evidence=[
                _ev(
                    f"/assessments/items/{items.index(i)}",
                    f"{i.get('item_id')} ({i.get('kind')}) has neither answer nor rubric",
                )
                for i in unanswerable[:5]
            ],
            recommendations=(
                [
                    _fix(
                        "Reject items with no answer key in stage 7's deterministic half.",
                        "An unmarkable item wastes class time and the teacher's evening.",
                        "high",
                    )
                ]
                if unanswerable
                else []
            ),
        )
    )

    mcqs = [i for i in items if str(i.get("kind")) == "mcq"]
    if mcqs:
        broken: list[tuple[str, str]] = []
        for item in mcqs:
            options = _as_list(item.get("options"))
            correct = [o for o in options if o.get("is_correct")]
            if len(options) < 3:
                broken.append((str(item.get("item_id")), f"only {len(options)} options"))
            elif len(correct) != 1:
                broken.append((str(item.get("item_id")), f"{len(correct)} correct options"))
        metrics.append(
            measured(
                "mcq_integrity",
                "MCQs have one right answer and real distractors",
                _pct(len(mcqs) - len(broken), len(mcqs)),
                f"{len(mcqs) - len(broken)} of {len(mcqs)} multiple-choice items have three or "
                "more options with exactly one marked correct.",
                weight=2.0,
                evidence=[_ev("/assessments/items", f"{iid}: {why}") for iid, why in broken[:5]],
                recommendations=(
                    [
                        _fix(
                            "Validate option cardinality and single-correctness before publishing.",
                            "An MCQ with two correct answers is marked wrong for students who "
                            "picked the other one.",
                            "high",
                        )
                    ]
                    if broken
                    else []
                ),
            )
        )

    objectives = ctx.objectives
    if objectives:
        assessed_concepts = {str(c) for i in items for c in (i.get("concept_ids") or [])}
        covered = [
            o
            for o in objectives
            if {str(c) for c in (o.get("concept_ids") or [])} & assessed_concepts
            or str(o.get("objective_id"))
            in {str(oid) for i in items for oid in (i.get("objective_ids") or [])}
        ]
        metrics.append(
            measured(
                "objective_coverage",
                "Objectives are assessed",
                _pct(len(covered), len(objectives)),
                f"{len(covered)} of {len(objectives)} learning objectives are reachable from at "
                "least one assessment item.",
                weight=2.5,
                evidence=[
                    _ev(
                        f"/knowledge/learning_objectives/{i}",
                        f"{o.get('objective_id')} is not assessed",
                    )
                    for i, o in enumerate(objectives)
                    if o not in covered
                ][:5],
                recommendations=(
                    [
                        _fix(
                            "Drive item generation from the objective list rather than the concept "
                            "list.",
                            "An objective nobody assesses is an objective nobody knows was met.",
                            "high",
                        )
                    ]
                    if len(covered) < len(objectives)
                    else []
                ),
            )
        )

    blooms = {str(i.get("bloom_level")) for i in items if i.get("bloom_level")}
    metrics.append(
        measured(
            "bloom_spread",
            "Items span more than recall",
            _pct(len(blooms), min(3, len(items))),
            f"{len(blooms)} distinct Bloom level(s) in the bank ({', '.join(sorted(blooms))}). "
            "Three or more is the point at which a paper distinguishes recall from reasoning.",
            weight=1.5,
            evidence=[_ev("/assessments/items", f"bloom levels: {sorted(blooms)}")],
        )
    )

    # The blueprint is stage 7's own account of what it built. Recomputing it is
    # how a report stops being taken on trust.
    blueprint = ctx.blueprint
    by_kind = blueprint.get("items_by_kind")
    if isinstance(by_kind, Mapping) and by_kind:
        actual: dict[str, int] = {}
        for item in items:
            actual[str(item.get("kind"))] = actual.get(str(item.get("kind")), 0) + 1
        claimed = {str(k): _int(v) for k, v in by_kind.items()}
        mismatches = {
            k: (claimed.get(k, 0), actual.get(k, 0))
            for k in set(claimed) | set(actual)
            if claimed.get(k, 0) != actual.get(k, 0)
        }
        metrics.append(
            measured(
                "blueprint_consistency",
                "Blueprint matches the items actually present",
                _pct(
                    len(set(claimed) | set(actual)) - len(mismatches),
                    max(len(set(claimed) | set(actual)), 1),
                ),
                "The published blueprint agrees with a recount of the bank."
                if not mismatches
                else "Blueprint disagrees with the bank on: "
                + ", ".join(f"{k} (claims {c}, has {a})" for k, (c, a) in mismatches.items()),
                weight=2.0,
                evidence=[_ev("/assessments/blueprint/items_by_kind", str(claimed))],
                recommendations=(
                    [
                        _fix(
                            "Compute the blueprint from the item list instead of alongside it.",
                            "The blueprint is what a teacher checks coverage against; a wrong one "
                            "misleads.",
                            "high",
                        )
                    ]
                    if mismatches
                    else []
                ),
            )
        )

    total_marks = ctx.assessments.get("total_marks")
    if isinstance(total_marks, int | float):
        summed = sum(_int(i.get("marks")) for i in items)
        metrics.append(
            measured(
                "marks_consistency",
                "Total marks equal the sum of the items",
                100.0 if _int(total_marks) == summed else 0.0,
                f"Published total is {_int(total_marks)}; the items sum to {summed}."
                + (" They agree." if _int(total_marks) == summed else " They do not."),
                weight=1.0,
                evidence=[_ev("/assessments/total_marks", f"{total_marks} vs {summed} summed")],
            )
        )

    metrics.append(
        not_measurable(
            "item_difficulty_calibration",
            "Item difficulty is calibrated",
            "Difficulty is a property of a population's responses. No student has answered "
            "these items, so there is no p-value or discrimination index to report.",
            needed="response data from a cohort — item-response theory needs roughly 100 "
            "students per item",
        )
    )

    return StageEvaluation(
        stage="assessment-generation", label="Assessment generation", metrics=metrics
    )


# ────────────────────────────────────────────────────── 8 · gap analysis


def _stage_gaps(ctx: EvalContext) -> StageEvaluation:
    gaps = ctx.learning_gaps
    if not gaps:
        return StageEvaluation(
            stage="gap-analysis",
            label="Gap analysis",
            metrics=[
                not_measurable(
                    "gaps_present",
                    "Learning gaps were predicted",
                    "No gaps were predicted for this package.",
                    needed="stage 8 output",
                )
            ],
            missing=["learning_gaps is empty"],
        )

    metrics: list[MetricResult] = []
    concept_ids = ctx.concept_ids
    linked = [g for g in gaps if {str(c) for c in (g.get("concept_ids") or [])} & concept_ids]
    metrics.append(
        measured(
            "gap_concept_linkage",
            "Gaps attach to real concepts",
            _pct(len(linked), len(gaps)),
            f"{len(linked)} of {len(gaps)} predicted gaps name a concept that stage 3 extracted.",
            weight=2.0,
            evidence=[
                _ev(f"/learning_gaps/{i}", f"{g.get('gap_id')} references {g.get('concept_ids')}")
                for i, g in enumerate(gaps)
                if g not in linked
            ][:5],
        )
    )

    metrics.append(
        _completeness(
            "remediation",
            "Gaps carry a remediation",
            gaps,
            "remediation",
            id_field="gap_id",
            base="/learning_gaps",
            what="gaps",
            weight=2.5,
        )
    )
    metrics.append(
        _completeness(
            "diagnostics",
            "Gaps carry a diagnostic question",
            gaps,
            "diagnostic_questions",
            id_field="gap_id",
            base="/learning_gaps",
            what="gaps",
            weight=2.0,
        )
    )

    # A diagnostic that does not say what the wrong answer looks like cannot be
    # used to diagnose anything — the teacher sees a wrong answer and learns
    # nothing about which misconception produced it.
    questions = [q for g in gaps for q in _as_list(g.get("diagnostic_questions"))]
    if questions:
        with_distractor = [q for q in questions if q.get("expected_wrong_answer")]
        metrics.append(
            measured(
                "diagnostic_discrimination",
                "Diagnostics predict the wrong answer",
                _pct(len(with_distractor), len(questions)),
                f"{len(with_distractor)} of {len(questions)} diagnostic questions state the wrong "
                "answer the misconception produces, which is what makes them diagnostic rather "
                "than merely difficult.",
                weight=1.5,
                evidence=[_ev("/learning_gaps", f"{len(questions)} diagnostic questions")],
            )
        )

    misconception_texts = {
        str(m.get("statement") or m.get("misconception") or "").lower() for m in ctx.misconceptions
    }
    if misconception_texts:
        aligned = [
            g for g in gaps if str(g.get("misconception") or "").lower() in misconception_texts
        ]
        metrics.append(
            measured(
                "misconception_alignment",
                "Gaps trace to extracted misconceptions",
                _pct(len(aligned), len(gaps)),
                f"{len(aligned)} of {len(gaps)} gaps restate a misconception stage 3 found in "
                "the source. The remainder are predicted rather than sourced, which is a "
                "legitimate output of this stage.",
                weight=0.5,
                evidence=[
                    _ev(
                        "/knowledge/misconceptions",
                        f"{len(misconception_texts)} extracted misconceptions",
                    )
                ],
            )
        )

    return StageEvaluation(stage="gap-analysis", label="Gap analysis", metrics=metrics)


# ──────────────────────────────────────────────────────── 9 · validation


def _stage_validation(ctx: EvalContext) -> StageEvaluation:
    validation = ctx.package.get("validation")
    validation = validation if isinstance(validation, Mapping) else {}
    if not validation:
        return StageEvaluation(
            stage="validation",
            label="Validation",
            metrics=[
                not_measurable(
                    "validation_ran",
                    "Validation ran",
                    "The package carries no validation report.",
                    needed="stage 9 output",
                )
            ],
            missing=["validation is absent"],
        )

    metrics: list[MetricResult] = []
    status = str(validation.get("status") or "unknown")
    issues = _as_list(validation.get("issues"))
    blocking = [i for i in issues if str(i.get("severity")) in {"error", "blocker", "critical"}]
    metrics.append(
        measured(
            "issue_resolution",
            "No blocking issues remain",
            100.0 if not blocking else _pct(len(issues) - len(blocking), max(len(issues), 1)),
            f"Status {status!r} with {len(issues)} issue(s), {len(blocking)} of them blocking.",
            weight=2.5,
            evidence=[
                _ev("/validation/issues", f"{i.get('code')}: {i.get('message')}")
                for i in blocking[:5]
            ],
            recommendations=(
                [
                    _fix(
                        "Route the blocking issues back to their owning stage for repair.",
                        "The package ships with defects its own validator found.",
                        "high",
                    )
                ]
                if blocking
                else []
            ),
        )
    )

    # Recompute stage 9's coverage claims. This is the check with the most
    # leverage in the whole framework: it is the only place where a stage's own
    # report of its work is independently re-derived.
    coverage = validation.get("coverage")
    coverage = coverage if isinstance(coverage, Mapping) else {}
    if coverage:
        taught = len(set(ctx.period_of_concept()) & ctx.concept_ids)
        claimed_taught = _int(coverage.get("concepts_taught"))
        claimed_total = _int(coverage.get("concepts_total"))
        actual_total = len(ctx.concept_ids)

        disagreements: list[str] = []
        if claimed_total != actual_total:
            disagreements.append(
                f"concepts_total claims {claimed_total}, the package has {actual_total}"
            )
        if claimed_taught != taught:
            disagreements.append(f"concepts_taught claims {claimed_taught}, recount finds {taught}")

        metrics.append(
            measured(
                "coverage_report_accuracy",
                "Coverage report survives a recount",
                100.0 if not disagreements else 0.0,
                "The published coverage numbers match an independent recount of the package."
                if not disagreements
                else "Recount disagrees: " + "; ".join(disagreements),
                weight=3.0,
                evidence=[_ev("/validation/coverage", d) for d in disagreements]
                or [
                    _ev(
                        "/validation/coverage",
                        f"{claimed_taught}/{claimed_total} concepts taught, confirmed",
                    )
                ],
                recommendations=(
                    [
                        _fix(
                            "Derive the coverage block from the package inside stage 9 rather than "
                            "carrying numbers forward from earlier stages.",
                            "A validator whose own summary is wrong cannot be used to gate a "
                            "release.",
                            "high",
                        )
                    ]
                    if disagreements
                    else []
                ),
            )
        )

    consistency = validation.get("consistency")
    consistency = consistency if isinstance(consistency, Mapping) else {}
    if consistency:
        checks = ("dangling_activity_refs", "duplicate_concept_ids", "prerequisite_violations")
        clean = [c for c in checks if not consistency.get(c)]
        metrics.append(
            measured(
                "structural_consistency",
                "Structural checks pass",
                _pct(len(clean), len(checks)),
                f"{len(clean)} of {len(checks)} structural checks are clean"
                + (
                    f"; failing: {', '.join(c for c in checks if c not in clean)}."
                    if len(clean) < len(checks)
                    else "."
                ),
                weight=2.0,
                evidence=[
                    _ev(f"/validation/consistency/{c}", str(consistency.get(c)))
                    for c in checks
                    if c not in clean
                ],
            )
        )

    grounding = validation.get("grounding_score")
    if isinstance(grounding, int | float):
        metrics.append(
            measured(
                "grounding_score",
                "Claims are supported by the source",
                100.0 * float(grounding),
                f"Stage 9 scored grounding at {float(grounding):.2f}. "
                f"{len(_as_list(validation.get('unsupported_claims')))} claim(s) were recorded "
                "as unsupported.",
                weight=2.5,
                evidence=[
                    _ev("/validation/unsupported_claims", str(c.get("claim") or c)[:120])
                    for c in _as_list(validation.get("unsupported_claims"))[:5]
                ]
                or [_ev("/validation/grounding_score", f"{float(grounding):.2f}")],
            )
        )

    return StageEvaluation(stage="validation", label="Validation", metrics=metrics)


# ──────────────────────────────────────────────────────── 10 · publishing


def _stage_publishing(ctx: EvalContext) -> StageEvaluation:
    metrics: list[MetricResult] = []
    provenance = ctx.package.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    generator = ctx.package.get("generator")
    generator = generator if isinstance(generator, Mapping) else {}

    timings = _as_list(provenance.get("stage_timings"))
    timed = {str(t.get("stage")) for t in timings}
    from contracts.primitives import STAGE_NAMES

    missing_timings = [s for s in STAGE_NAMES if s not in timed]
    metrics.append(
        measured(
            "stage_timings",
            "Every stage reported its cost",
            _pct(len(STAGE_NAMES) - len(missing_timings), len(STAGE_NAMES)),
            f"{len(timed)} of {len(STAGE_NAMES)} stages recorded a timing entry"
            + (f"; missing {', '.join(missing_timings)}." if missing_timings else "."),
            weight=1.5,
            evidence=[
                _ev(
                    "/provenance/stage_timings",
                    f"{len(timings)} entries totalling {provenance.get('total_duration_ms', 0)} ms",
                )
            ],
            recommendations=(
                [
                    _fix(
                        "Emit a timing entry from every stage span, including cheap ones.",
                        "Per-stage cost cannot be attributed without it.",
                        "medium",
                    )
                ]
                if missing_timings
                else []
            ),
        )
    )

    models = generator.get("models_by_stage")
    models = models if isinstance(models, Mapping) else {}
    generative = [s for s in STAGE_NAMES if s not in _NON_GENERATIVE_STAGES]
    attributed = [s for s in generative if models.get(s)]
    unattributed = [s for s in generative if not models.get(s)]
    metrics.append(
        measured(
            "model_attribution",
            "Each model-calling stage names the model that ran it",
            _pct(len(attributed), len(generative)),
            f"{len(attributed)} of {len(generative)} model-calling stages record which model "
            "produced their output"
            + (f"; missing {', '.join(unattributed)}." if unattributed else ".")
            + f" {', '.join(sorted(_NON_GENERATIVE_STAGES))} are excluded because they make "
            "no model call, so an absent entry for them is correct rather than missing.",
            weight=1.0,
            evidence=[_ev("/generator/models_by_stage", str(dict(models))[:200])],
            recommendations=(
                [
                    _fix(
                        f"Report the model used by {', '.join(unattributed)}.",
                        "Without it a regression cannot be attributed to a model change.",
                        "low",
                    )
                ]
                if unattributed
                else []
            ),
        )
    )

    decisions = _as_list(provenance.get("decisions"))
    metrics.append(
        measured(
            "decision_record",
            "Stages explain their choices",
            _pct(len(decisions), 4),
            f"{len(decisions)} stage decision(s) recorded with a reason. Four is the point at "
            "which the main routing choices — period count, item mix, gap severity, profile — "
            "are all accounted for.",
            weight=1.0,
            evidence=[
                _ev(
                    "/provenance/decisions",
                    f"{d.get('stage')}: {d.get('what')} — {d.get('because')}",
                )
                for d in decisions[:4]
            ],
            recommendations=(
                [
                    _fix(
                        "Record a decision from each stage that makes a routing choice.",
                        "A reviewer cannot tell whether a choice was reasoned or arbitrary.",
                        "low",
                    )
                ]
                if len(decisions) < 4
                else []
            ),
        )
    )

    fields = ("tkp_id", "schema_version", "generated_at")
    have, missing = _present(ctx.package, fields)
    metrics.append(
        measured(
            "package_identity",
            "Package is identified and versioned",
            _pct(len(have), len(fields)),
            f"{len(have)} of {len(fields)} identity fields present"
            + (
                f"; missing {', '.join(missing)}."
                if missing
                else f" (schema {ctx.package.get('schema_version')})."
            ),
            weight=1.5,
            evidence=[_ev("/schema_version", str(ctx.package.get("schema_version")))],
        )
    )

    cost = provenance.get("total_cost_usd")
    tokens_in = _int(provenance.get("total_tokens_in"))
    if isinstance(cost, int | float) and tokens_in:
        metrics.append(
            measured(
                "cost_accounting",
                "Cost and token usage are accounted for",
                100.0,
                f"${float(cost):.4f} across {tokens_in:,} input and "
                f"{_int(provenance.get('total_tokens_out')):,} output tokens.",
                weight=0.5,
                evidence=[_ev("/provenance/total_cost_usd", f"${float(cost):.4f}")],
            )
        )
    else:
        metrics.append(
            not_measurable(
                "cost_accounting",
                "Cost and token usage are accounted for",
                "The package records no token totals.",
                needed="usage attribution from the LLM call log",
            )
        )

    return StageEvaluation(stage="publishing", label="Publishing", metrics=metrics)


# ──────────────────────────────────────────────────────── cross-cutting


def _stage_outcomes(ctx: EvalContext) -> StageEvaluation:
    """The metrics the brief asks for that no artifact can answer.

    Kept as a named group rather than scattered, because the honest answer to
    "how satisfied are teachers" is a study, and grouping the four questions
    that need one makes the shape of the missing work legible: three of them are
    the same study.
    """
    _ = ctx
    return StageEvaluation(
        stage="outcomes",
        label="Learning outcomes",
        metrics=[
            not_measurable(
                "teacher_satisfaction",
                "Teacher satisfaction",
                "Satisfaction is a rating teachers give. None have used this package.",
                needed="a pilot with teachers rating packages after classroom use — 20+ "
                "responses before a mean means anything",
            ),
            not_measurable(
                "student_learning_effectiveness",
                "Student learning effectiveness",
                "Effectiveness is measured by what students learn, which requires students, a "
                "pre-test and a post-test.",
                needed="a controlled classroom trial with pre/post assessment against a "
                "conventionally-planned unit",
            ),
            not_measurable(
                "time_saved",
                "Teacher preparation time saved",
                "Time saved is a difference against how long the same teacher would take "
                "unaided. That baseline has not been collected.",
                needed="timed preparation of the same unit by teachers with and without the "
                "package",
            ),
            not_measurable(
                "curriculum_conformance",
                "Conformance to a published curriculum",
                "The package aligns to a board's structure, but no authority has certified the "
                "mapping. Reporting a conformance score would state agreement nobody granted.",
                needed="an official syllabus document parsed to statement level, and a "
                "reviewer's sign-off on the mapping",
            ),
        ],
    )


# ─────────────────────────────────────────────────────────────── registry


STAGE_EVALUATORS: tuple[tuple[str, Any], ...] = (
    ("document-intelligence", _stage_document_intelligence),
    ("educational-classification", _stage_classification),
    ("knowledge-extraction", _stage_knowledge),
    ("teaching-planner", _stage_planner),
    ("lesson-generation", _stage_lessons),
    ("activity-generation", _stage_activities),
    ("assessment-generation", _stage_assessments),
    ("gap-analysis", _stage_gaps),
    ("validation", _stage_validation),
    ("publishing", _stage_publishing),
    ("outcomes", _stage_outcomes),
)


def evaluate_stage(stage: str, ctx: EvalContext) -> StageEvaluation:
    for key, run in STAGE_EVALUATORS:
        if key == stage:
            return run(ctx)
    raise KeyError(f"no evaluator for stage {stage!r}; have {[k for k, _ in STAGE_EVALUATORS]}")


def evaluate_stages(ctx: EvalContext) -> list[StageEvaluation]:
    """Every stage, in pipeline order. Order is the reading order for a report."""
    return [run(ctx) for _, run in STAGE_EVALUATORS]


# Re-exported so callers can build a judged metric without importing two modules.
_ = judged
