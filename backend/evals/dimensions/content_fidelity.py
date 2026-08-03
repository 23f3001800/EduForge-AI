"""Content fidelity — is this package about the document it claims to be about?

Nine dimensions measured how well this package was *made* and not one of them read
``classification.subject`` or ``classification.topic``. The consequence was
demonstrated rather than theorised: a package labelled History, topic "The
Partition of Bengal", whose every concept, activity and assessment item taught
Newton's Laws of Motion, scored 0.874 and was banded **exemplary**. Every
structural check passed, because structurally it was a good package. It was about
the wrong thing, and nothing in the harness could see that.

Two questions, and neither needs a model:

* **Does the content match the label?** The topic stage 2 assigned is a claim
  about the document. The concepts, keywords, definitions and objectives stage 3
  extracted are a second, independent account of the same document. When the two
  share no vocabulary, one of them is wrong, and a teacher who searched for
  "Partition of Bengal" and received Newton's Laws has been failed before any
  question of teaching quality arises.

* **Does every concept reference resolve?** ``concept_ids`` thread through
  periods, checkpoints, activities, items, objectives, gaps and the blueprint. An
  id that names no extracted concept is a reference to teaching material that does
  not exist in this package — the pointer form of the same failure. This is pure
  set membership and cannot be argued with.

**Why absence is not scored here.** A topic string with no content words ("Chapter
5", "Unit II") is a stage-2 output this dimension cannot grade, so the alignment
metric drops to weight zero and says so, rather than scoring a package down for
its chapter being numbered. Reference integrity is always checkable and is always
scored.

**Subject is reported, not scored.** "Physics" appears nowhere in a chapter about
Newton's Laws, and "History" appears nowhere in a chapter about the Partition —
subject names are catalogue labels, not content words, and scoring their presence
would reward packages that name their own discipline in the prose. The topic is
the field that is supposed to describe the material, so the topic is what is
checked. Nothing here branches on which subject was named; the comparison is
between two fields of the same package and is identical code for every document.
"""

from __future__ import annotations

from collections.abc import Iterable

from evals.context import EvalContext
from evals.discrimination import content_words
from evals.text import fold
from evals.types import DimensionScore, Finding, Metric

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "content_fidelity"
LABEL = "Content fidelity"
WEIGHT = 0.11
METHOD = "deterministic"

#: Below this share of the topic's content words appearing anywhere in what the
#: package teaches, the label and the content are describing different documents.
TOPIC_ALIGNMENT_FLOOR = 0.5

#: Words that name a *place in a book* rather than a subject. A topic of "Chapter
#: 5" or "Unit II — Introduction" describes where the material sits, not what it
#: is about, and there is nothing here for content to align with. Removed before
#: alignment is computed so that a numbered chapter is reported as unscoreable
#: rather than scored as a mismatch. Structural vocabulary, not topical: the same
#: words label a mechanics chapter and a poetry chapter.
_STRUCTURAL_LABELS: frozenset[str] = frozenset(
    {
        "chapter",
        "unit",
        "lesson",
        "section",
        "module",
        "part",
        "book",
        "volume",
        "page",
        "topic",
        "exercise",
        "introduction",
        "revision",
        "appendix",
        "syllabus",
        "curriculum",
        "textbook",
        "chapters",
        "units",
        "lessons",
    }
)


def _teaching_corpus(ctx: EvalContext) -> str:
    """Everything this package claims to teach, as one comparable string.

    Names and summaries rather than scripts: a script may legitimately spend a
    segment on classroom management, but a concept name is a direct assertion
    about what the document is about.
    """
    parts: list[str] = []
    knowledge = ctx.knowledge
    for concept in ctx.concepts:
        parts += [str(concept.get("name") or ""), str(concept.get("summary") or "")]
    parts += [str(k) for k in (knowledge.get("keywords") or [])]
    parts += [str(d.get("term") or "") for d in (knowledge.get("definitions") or [])]
    parts += [str(o.get("statement") or "") for o in ctx.objectives]
    parts += [str(p.get("title") or "") for p in ctx.periods]
    parts += [str(a.get("title") or "") for a in ctx.activities]
    parts += [str(e.get("title") or "") for e in (knowledge.get("examples") or [])]
    return " ".join(parts)


def _referenced_concept_ids(ctx: EvalContext) -> dict[str, list[str]]:
    """Every concept id the package points at, and where from.

    Ordered so the report names the earliest structural user of a dangling id,
    which is usually the stage that invented it.
    """
    found: dict[str, list[str]] = {}

    def note(value: object, path: str) -> None:
        cid = str(value)
        if cid and cid != "None":
            found.setdefault(cid, []).append(path)

    def walk(items: Iterable[dict], base: str) -> None:
        for index, item in enumerate(items):
            for cid in item.get("concept_ids") or []:
                note(cid, f"{base}/{index}")

    walk(ctx.objectives, "/knowledge/learning_objectives")
    walk(ctx.periods, "/teaching_plan/periods")
    walk(ctx.activities, "/activities")
    walk(ctx.items, "/assessments/items")
    walk(ctx.learning_gaps, "/learning_gaps")
    walk(ctx.misconceptions, "/knowledge/misconceptions")

    for index, content in enumerate(ctx.classroom_content):
        for offset, question in enumerate(content.get("checkpoint_questions") or []):
            for cid in question.get("concept_ids") or []:
                note(cid, f"/classroom_content/{index}/checkpoint_questions/{offset}")

    for cid in ctx.blueprint.get("marks_by_concept") or {}:
        note(cid, "/assessments/blueprint/marks_by_concept")

    for edge in ctx.concept_graph.get("edges") or []:
        if isinstance(edge, dict):
            note(edge.get("from_id"), "/knowledge/concept_graph/edges")
            note(edge.get("to_id"), "/knowledge/concept_graph/edges")

    return found


def score(ctx: EvalContext) -> DimensionScore:
    findings: list[Finding] = []
    known = ctx.concept_ids

    # --- does the content match the label? -------------------------------------
    topic = str(ctx.classification.get("topic") or "")
    topic_terms = content_words(topic) - _STRUCTURAL_LABELS
    corpus = _teaching_corpus(ctx)
    corpus_terms = content_words(corpus)
    corpus_folded = fold(corpus)

    if not topic_terms:
        alignment = 1.0
        alignment_weight = 0.0
        alignment_note = (
            f"topic {topic!r} contains no content words, so there is nothing to align "
            "against; reported, not scored"
        )
    else:
        # A topic term counts as present if it is a content word of the teaching
        # corpus or appears in it at all — "Motion" inside "uniform motion" is a
        # match, and stemming already reconciles plurals.
        hit = {
            term
            for term in topic_terms
            if term in corpus_terms or any(term in t for t in corpus_terms) or term in corpus_folded
        }
        alignment = len(hit) / len(topic_terms)
        alignment_weight = 0.50
        alignment_note = (
            f"{len(hit)} of {len(topic_terms)} content word(s) in the declared topic "
            f"{topic!r} appear in what the package teaches"
        )
        if alignment < TOPIC_ALIGNMENT_FLOOR:
            missing = ", ".join(sorted(topic_terms - hit)[:6])
            findings.append(
                Finding(
                    "FID_TOPIC_MISMATCH",
                    "/classification/topic",
                    f"the package is labelled {topic!r} but teaches none of: {missing}. "
                    "Either stage 2 classified the wrong document or stage 3 extracted "
                    "from one — a teacher who searched for this topic has been handed "
                    "material about something else, and no amount of structural quality "
                    "repairs that",
                )
            )

    # --- do the references resolve? -------------------------------------------
    referenced = _referenced_concept_ids(ctx)
    dangling = {cid: paths for cid, paths in referenced.items() if cid not in known}
    resolved_share = (len(referenced) - len(dangling)) / len(referenced) if referenced else 0.0
    for cid, paths in sorted(dangling.items())[:8]:
        findings.append(
            Finding(
                "FID_CONCEPT_UNRESOLVED",
                paths[0],
                f"references concept {cid!r}, which this document never extracted "
                f"(referenced from {len(paths)} place(s)); the material it points at "
                "does not exist in this package",
            )
        )

    if not referenced:
        findings.append(
            Finding(
                "FID_NO_CONCEPT_REFERENCES",
                "/knowledge/concepts",
                "nothing in the plan, the activities or the bank names a concept id, so "
                "no part of this package is traceable to anything the document taught",
            )
        )

    # --- is the extracted content itself present? ------------------------------
    # A package whose teaching corpus is empty cannot be about anything. Scored
    # rather than skipped, because "no concepts" is exactly the state in which
    # every other fidelity check would trivially pass.
    substance = 1.0 if corpus_terms else 0.0
    if not corpus_terms:
        findings.append(
            Finding(
                "FID_NO_TEACHING_CONTENT",
                "/knowledge",
                "the package names no concepts, keywords, definitions or objectives; "
                "there is no content here to be faithful to",
            )
        )

    metrics = (
        Metric("topic_alignment", alignment, alignment_weight, alignment_note),
        Metric(
            "concept_reference_integrity",
            resolved_share,
            0.35,
            f"{len(referenced) - len(dangling)} of {len(referenced)} referenced concept "
            f"id(s) resolve to a concept extracted from this document"
            if referenced
            else "no concept id is referenced anywhere in the package",
        ),
        Metric(
            "teaching_content_present",
            substance,
            0.15,
            f"{len(corpus_terms)} distinct content term(s) across concepts, keywords, "
            "definitions and objectives",
        ),
        Metric(
            "declared_subject",
            0.0,
            0.0,
            f"subject {str(ctx.classification.get('subject') or 'unknown')!r}, grade band "
            f"{ctx.grade_band!r} (reported, never scored: a subject name is a catalogue "
            "label and rewarding its appearance in the prose would be a defect)",
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
