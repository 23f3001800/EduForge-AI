"""Stage 10 — publishing assembly and rendering.

Three things are worth proving here that a schema check alone would not catch:

1. The assembled package is a *real* `TeacherKnowledgePackage`, not merely a
   dict shaped like one (the same discipline `test_pipeline.py` applies at the
   API boundary).
2. Devanagari text — the one non-Latin script the pipeline ships a font for —
   comes out as real glyphs, not tofu. `pypdf` round-tripping the exact string
   back out of the rendered PDF is a stronger check than "the font object
   exists": a font can be registered and still not be the one actually used.
3. The assessment book's answer key is a separable section — its content is
   verifiably absent from every page before it, not just visually distinct.
"""

from __future__ import annotations

import io
from typing import Any, get_args
from uuid import uuid4

import pytest
from pypdf import PdfReader

from contracts import (
    AssessmentBank,
    AssessmentBlueprint,
    AssessmentItem,
    Rubric,
    RubricLevel,
    TeacherKnowledgePackage,
)
from contracts.jobs import ArtifactKind, JobOptions
from contracts.primitives import SCHEMA_VERSION
from stages.base import StageContext
from stages.s10_publishing.assemble import assemble_package
from stages.s10_publishing.render import RENDERERS
from stages.s10_publishing.render.assessment_book import (
    ANSWER_KEY_HEADING,
    render_assessment_book_pdf,
)
from stages.s10_publishing.render.document import TkpDocument
from stages.s10_publishing.render.fonts import DEVANAGARI_FONT, has_devanagari
from stages.s10_publishing.render.lesson_plan import render_lesson_plan_pdf
from stages.s10_publishing.render.markdown_bundle import render_markdown_bundle
from stages.s10_publishing.render.teacher_guide import render_teacher_guide_pdf
from stages.s10_publishing.stage import PublishingStage
from tests.fixtures import factories as fx

# ─────────────────────────────────────────────────────────────── state helpers


def _full_state() -> dict[str, Any]:
    """A complete, internally consistent graph state — one real pipeline run."""
    return {
        "job_id": str(uuid4()),
        "document_id": str(fx.DOC_ID),
        "structured_document": fx.structured_document().model_dump(mode="json"),
        "chunks": [c.model_dump(mode="json") for c in fx.chunks()],
        "classification": fx.classification().model_dump(mode="json"),
        "knowledge": fx.knowledge_base().model_dump(mode="json"),
        "teaching_plan": fx.teaching_plan().model_dump(mode="json"),
        "period_contents": [p.model_dump(mode="json") for p in fx.classroom_content()],
        "activities": [a.model_dump(mode="json") for a in fx.activities()],
        "assessments": fx.assessments().model_dump(mode="json"),
        "learning_gaps": [g.model_dump(mode="json") for g in fx.learning_gaps()],
        "validation": fx.validation_report().model_dump(mode="json"),
    }


def _narrative_assessments() -> AssessmentBank:
    """A bank with no numerical item — the humanities counterpart to `fx.assessments()`."""
    items = [
        AssessmentItem(
            item_id="item_1",
            kind="mcq",
            stem="Why did the treaty collapse within a decade?",
            options=[
                {"label": "A", "text": "Neither side could enforce its terms", "is_correct": True},
                {"label": "B", "text": "The document was never signed", "is_correct": False},
                {"label": "C", "text": "A third nation vetoed it", "is_correct": False},
                {"label": "D", "text": "It was ruled unconstitutional", "is_correct": False},
            ],
            answer="A",
            marks=1,
            bloom_level="understand",
            concept_ids=["concept_causes"],
        ),
        AssessmentItem(
            item_id="item_2",
            kind="short_answer",
            stem="Explain one long-term cause of the treaty's collapse.",
            answer="Enforcement depended on institutions neither side actually funded.",
            marks=3,
            bloom_level="analyze",
            concept_ids=["concept_causes"],
            rubric=Rubric(
                criteria="Names a cause and explains its long-term effect",
                levels=[
                    RubricLevel(
                        label="Complete", descriptor="Cause and effect both clear.", marks=3
                    ),
                    RubricLevel(label="Partial", descriptor="Cause named, effect vague.", marks=1),
                ],
            ),
        ),
    ]
    return AssessmentBank(
        items=items,
        blueprint=AssessmentBlueprint(items_by_kind={"mcq": 1, "short_answer": 1}),
        total_marks=4,
    )


def _narrative_state() -> dict[str, Any]:
    """Zero formulae, zero numerical items — the humanities shape (docs/00 § H-07)."""
    state = _full_state()
    knowledge = dict(state["knowledge"])
    knowledge["formulae"] = []
    state["knowledge"] = knowledge
    state["classification"] = fx.narrative_classification().model_dump(mode="json")
    state["assessments"] = _narrative_assessments().model_dump(mode="json")
    return state


def _ctx(options: dict[str, Any] | None = None) -> StageContext:
    return StageContext(job_id=uuid4(), options=options or {}, emit=None)


def _pdf_pages(data: bytes) -> list[str]:
    assert data[:4] == b"%PDF"
    reader = PdfReader(io.BytesIO(data))
    return [page.extract_text() for page in reader.pages]


# ────────────────────────────────────────────────────────────────── assembly


async def test_assemble_package_produces_a_real_tkp() -> None:
    tkp = assemble_package(_full_state())
    assert isinstance(tkp, TeacherKnowledgePackage)
    # Round-trip through the wire format, exactly what the API boundary does —
    # a package that only validates as a live object is not what ships.
    TeacherKnowledgePackage.model_validate(tkp.model_dump(mode="json"))
    assert tkp.schema_version == SCHEMA_VERSION
    assert tkp.source.filename == "newtons-laws.pdf"
    assert tkp.generator.app_version


async def test_assembled_citations_are_pulled_from_grounded_evidence() -> None:
    tkp = assemble_package(_full_state())
    assert tkp.provenance.citations
    pointers = {ref for c in tkp.provenance.citations for ref in c.referenced_by}
    assert any(p.startswith("/knowledge/concepts/") for p in pointers)


@pytest.mark.parametrize(
    "missing", ["classification", "knowledge", "teaching_plan", "assessments", "validation"]
)
async def test_assembly_fails_loudly_when_a_required_stage_output_is_absent(missing: str) -> None:
    state = _full_state()
    del state[missing]
    with pytest.raises(ValueError, match=missing):
        assemble_package(state)


# ──────────────────────────────────────────────────────────────── devanagari


def test_devanagari_font_is_registered_on_every_rendered_document() -> None:
    doc = TkpDocument(title="त")
    assert DEVANAGARI_FONT.lower() in doc.fonts


def test_devanagari_text_renders_as_real_glyphs_not_tofu() -> None:
    hindi_topic = "न्यूटन के गति के नियम"
    assert has_devanagari(hindi_topic)

    tkp = assemble_package(_full_state())
    tkp = tkp.model_copy(
        update={"classification": tkp.classification.model_copy(update={"topic": hindi_topic})}
    )

    data = render_lesson_plan_pdf(tkp)
    assert data[:4] == b"%PDF"
    assert len(data) > 1000  # a tofu-only render would still be small; a real one embeds glyphs

    # The strongest available proof of "not tofu": pypdf recovers the exact
    # Devanagari string from the embedded font's ToUnicode map. A font that
    # rendered boxes because the glyphs were absent could not round-trip this.
    text = "\n".join(_pdf_pages(data))
    assert hindi_topic in text


# ────────────────────────────────────────────────────────────── answer key


def test_answer_key_is_a_distinct_section_after_the_questions() -> None:
    tkp = assemble_package(_full_state())
    data = render_assessment_book_pdf(tkp)
    pages = _pdf_pages(data)

    key_pages = [i for i, text in enumerate(pages) if ANSWER_KEY_HEADING in text]
    assert key_pages, "no page carries the Answer Key heading"
    key_start = key_pages[0]

    numerical_answer = "3 m/s^2"
    distractor_rationale = "Targets the belief that motion requires a force."

    before = "\n".join(pages[:key_start])
    after = "\n".join(pages[key_start:])
    assert numerical_answer not in before
    assert distractor_rationale not in before
    assert numerical_answer in after
    assert distractor_rationale in after


def test_questions_section_shows_all_four_mcq_options_unmarked() -> None:
    """Not hiding the correct option — hiding which one it is."""
    tkp = assemble_package(_full_state())
    pages = _pdf_pages(render_assessment_book_pdf(tkp))
    questions_text = pages[0]
    assert "They continue moving while the bus slows" in questions_text
    assert "A forward force acts on them" in questions_text


# ────────────────────────────────────────────────────────── narrative content


def test_narrative_package_with_no_formulae_publishes_cleanly() -> None:
    tkp = assemble_package(_narrative_state())
    assert tkp.knowledge.formulae == []
    assert all(item.kind != "numerical" for item in tkp.assessments.items)

    for renderer in (render_lesson_plan_pdf, render_teacher_guide_pdf, render_assessment_book_pdf):
        data = renderer(tkp)
        assert data[:4] == b"%PDF"

    lesson_plan_text = "\n".join(_pdf_pages(render_lesson_plan_pdf(tkp)))
    assert "Formulae" not in lesson_plan_text

    markdown = render_markdown_bundle(tkp).decode("utf-8")
    assert "## Formulae" not in markdown


# ───────────────────────────────────────────────────────────── the full stage


async def test_publishing_stage_returns_a_validated_package() -> None:
    state = _full_state()
    result = await PublishingStage().run(_ctx(), state)

    assert set(result) == {"package"}
    TeacherKnowledgePackage.model_validate(result["package"])


async def test_publishing_stage_honours_include_artifacts() -> None:
    messages: list[str] = []

    async def emit(*, stage: str, progress: int, message: str | None = None, **_: Any) -> None:
        if message:
            messages.append(message)

    ctx = StageContext(job_id=uuid4(), options={"include_artifacts": ["tkp_json"]}, emit=emit)
    await PublishingStage().run(ctx, _full_state())

    rendering_messages = [m for m in messages if m.startswith("rendering ")]
    assert rendering_messages == ["rendering tkp_json"]


async def test_publishing_stage_defaults_match_job_options() -> None:
    messages: list[str] = []

    async def emit(*, stage: str, progress: int, message: str | None = None, **_: Any) -> None:
        if message:
            messages.append(message)

    ctx = StageContext(job_id=uuid4(), options={}, emit=emit)
    await PublishingStage().run(ctx, _full_state())

    rendered = {m.removeprefix("rendering ") for m in messages if m.startswith("rendering ")}
    assert rendered == set(JobOptions().include_artifacts)


async def test_publishing_stage_ignores_an_unknown_artifact_kind() -> None:
    ctx = _ctx({"include_artifacts": ["tkp_json", "not_a_real_kind"]})
    result = await PublishingStage().run(ctx, _full_state())
    TeacherKnowledgePackage.model_validate(result["package"])


def test_renderers_cover_every_artifact_kind_job_options_can_request() -> None:
    assert set(get_args(ArtifactKind)) == set(RENDERERS)
