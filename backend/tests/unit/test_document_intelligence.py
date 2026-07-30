"""Stage 1 — document intelligence (MS-2 gate).

Parsing accuracy and structure preservation are 15% of the assignment's grade,
and "the text all came out somewhere" does not satisfy it. These tests assert
structure at cell and hierarchy level, because a substring assertion passes on a
flattened table and that is exactly the failure worth catching.

Fixtures are real PDF/DOCX/PPTX files (``fixtures/documents/generate.py``), not
mocks — parser behaviour against synthetic input proves nothing.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from contracts.document import StructuredDocument
from stages.s1_document_intelligence.chunking import chunk_blocks, estimate_tokens
from stages.s1_document_intelligence.equations import is_probable_equation, to_latex
from stages.s1_document_intelligence.errors import (
    DocumentTooLarge,
    EmptyDocument,
    ParseFailure,
    ParseTimeout,
    TooManyPages,
    UnsupportedMediaType,
)
from stages.s1_document_intelligence.stage import parse_document
from stages.s1_document_intelligence.structure import TextSpan, infer_heading_level

DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "documents"

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TXT = "text/plain"

LIMITS = {"max_bytes": 26_214_400, "max_pages": 300, "timeout_s": 30.0}


async def _parse(name: str, mime: str, **overrides: object) -> tuple[StructuredDocument, list]:
    return await parse_document(
        document_id=uuid4(),
        payload=(DOCS / name).read_bytes(),
        filename=name,
        mime=mime,
        **{**LIMITS, **overrides},  # type: ignore[arg-type]
    )


# ─────────────────────────────────────────────────────────── format coverage


@pytest.mark.parametrize(
    ("name", "mime"),
    [("physics.pdf", PDF), ("history.docx", DOCX), ("lesson.pptx", PPTX), ("notes.md", TXT)],
)
async def test_every_required_format_parses(name: str, mime: str) -> None:
    """FR-01: PDF, DOCX, PPT, and text are all named in the assignment."""
    document, chunks = await _parse(name, mime)
    assert document.blocks
    assert chunks
    assert document.metadata.word_count and document.metadata.word_count > 10


# ────────────────────────────────────────────────────── structure preservation


async def test_pdf_heading_hierarchy_is_recovered() -> None:
    """PDF has no heading markup; the hierarchy is inferred and must be right."""
    document, _ = await _parse("physics.pdf", PDF)

    assert len(document.outline) == 1
    root = document.outline[0]
    assert "Newton" in root.title
    assert root.level == 1
    assert [c.level for c in root.children] == [2, 2]
    assert [c.title for c in root.children] == ["5.1 The First Law", "5.2 The Second Law"]


async def test_table_headers_do_not_leak_into_the_outline() -> None:
    """A bold table header row satisfies every heading cue.

    Left unhandled it is promoted into the hierarchy and corrupts the section
    path of every block after it.
    """
    document, _ = await _parse("physics.pdf", PDF)
    titles = [node.title for node in document.outline[0].children]
    assert not any("Quantity" in t for t in titles), f"table header leaked: {titles}"


@pytest.mark.parametrize(
    ("name", "mime", "headers", "first_row"),
    [
        ("physics.pdf", PDF, ["Quantity", "Symbol", "Unit"], ["Force", "F", "N"]),
        ("history.docx", DOCX, ["Year", "Event"], ["1905", "Partition announced"]),
        ("lesson.pptx", PPTX, ["Stage", "Location"], ["Light reactions", "Thylakoid"]),
    ],
)
async def test_tables_survive_as_cells_not_prose(
    name: str, mime: str, headers: list[str], first_row: list[str]
) -> None:
    """Flattening is the silent failure of 'structure preservation'.

    Asserted at cell level: a substring check would pass on a flattened table.
    """
    document, _ = await _parse(name, mime)
    tables = [b for b in document.blocks if b.type == "table" and b.table]
    assert tables, f"no table recovered from {name}"

    table = tables[0].table
    assert table is not None
    assert table.headers == headers
    assert table.rows[0] == first_row
    assert all(len(row) == len(table.headers) for row in table.rows)


async def test_equations_are_detected_and_kept_renderable() -> None:
    """A physics chapter that loses its equations cannot produce a lesson plan."""
    document, _ = await _parse("physics.pdf", PDF)
    equations = [b for b in document.blocks if b.type == "equation"]
    assert equations
    assert any("=" in b.text for b in equations)
    # Raw text is always retained, so a failed conversion degrades rather than loses.
    assert all(b.text for b in equations)


async def test_section_paths_locate_every_block_in_the_document() -> None:
    """Section paths are what let an evidence span tell a teacher where to look."""
    document, _ = await _parse("physics.pdf", PDF)
    equation = next(b for b in document.blocks if b.type == "equation")
    assert equation.section_path[-1] == "5.2 The Second Law"
    assert "Newton" in equation.section_path[0]


async def test_docx_styles_drive_headings() -> None:
    document, _ = await _parse("history.docx", DOCX)
    headings = [(b.level, b.text) for b in document.blocks if b.type == "heading"]
    assert (1, "The Partition of Bengal") in headings
    assert (2, "Background") in headings


async def test_pptx_slide_titles_become_headings_and_notes_are_kept() -> None:
    document, _ = await _parse("lesson.pptx", PPTX)
    headings = [b.text for b in document.blocks if b.type == "heading"]
    assert "Photosynthesis" in headings
    assert any(b.page == 2 for b in document.blocks)


async def test_markdown_hashes_are_honoured_as_explicit_levels() -> None:
    document, _ = await _parse("notes.md", TXT)
    headings = [(b.level, b.text) for b in document.blocks if b.type == "heading"]
    assert (1, "Cell Biology") in headings
    assert (2, "Transport") in headings


# ──────────────────────────────────────────────────────────────── versatility


async def test_a_humanities_document_yields_no_equations_and_that_is_fine() -> None:
    """NFR-01. Absent content is correct content, not a parsing failure."""
    document, _ = await _parse("history.docx", DOCX)
    assert document.stats.equations == 0
    assert document.stats.paragraphs > 0
    assert document.stats.tables == 1


# ────────────────────────────────────────────────────────────────── chunking


async def test_chunks_never_split_a_table() -> None:
    """A table row separated from its headers is no longer a table."""
    document, chunks = await _parse("physics.pdf", PDF)
    table_block = next(b for b in document.blocks if b.type == "table")
    owners = [c for c in chunks if table_block.block_id in c.block_ids]
    assert len(owners) == 1, "table block spans multiple chunks"


async def test_chunks_carry_the_metadata_a_citation_needs() -> None:
    _, chunks = await _parse("physics.pdf", PDF)
    assert all(c.chunk_id for c in chunks)
    assert all(c.token_count > 0 for c in chunks)
    assert any(c.section_path for c in chunks)


async def test_chunk_ordinals_are_dense_and_ordered() -> None:
    _, chunks = await _parse("history.docx", DOCX)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_oversized_atomic_block_becomes_its_own_chunk_rather_than_being_cut() -> None:
    from contracts.document import Block, TableData

    huge = Block(
        block_id="b_0000",
        type="table",
        text="x " * 4000,
        char_start=0,
        char_end=8000,
        table=TableData(headers=["a"], rows=[["b"]]),
    )
    chunks = chunk_blocks(uuid4(), [huge])
    assert len(chunks) == 1
    assert estimate_tokens(chunks[0].text) > 800


# ───────────────────────────────────────────────────────────── determinism


async def test_parsing_is_deterministic() -> None:
    """Same bytes in, same structure out. Stage 1 makes no model calls."""
    first, chunks_a = await _parse("physics.pdf", PDF)
    second, chunks_b = await _parse("physics.pdf", PDF)

    strip = {"document_id"}
    assert first.model_dump(exclude=strip) == second.model_dump(exclude=strip)
    assert [c.text for c in chunks_a] == [c.text for c in chunks_b]


# ────────────────────────────────────────────────────────── safety & limits


async def test_oversized_document_is_rejected_before_parsing() -> None:
    with pytest.raises(DocumentTooLarge):
        await _parse("physics.pdf", PDF, max_bytes=100)


async def test_page_cap_is_enforced() -> None:
    with pytest.raises(TooManyPages):
        await _parse("physics.pdf", PDF, max_pages=0)


async def test_unsupported_media_type_is_rejected() -> None:
    with pytest.raises(UnsupportedMediaType):
        await _parse("notes.md", "application/x-executable")


async def test_malformed_pdf_is_rejected_cleanly_not_hung() -> None:
    """Correct magic bytes, unusable body — must be a rejection, never a 500."""
    with pytest.raises(ParseFailure):
        await _parse("malformed.pdf", PDF)


async def test_document_with_no_extractable_text_is_rejected() -> None:
    """A scanned PDF lands here. Honest failure beats a package built on nothing."""
    with pytest.raises(EmptyDocument):
        await _parse("empty.txt", TXT)


async def test_parse_timeout_is_bounded() -> None:
    """Converts an indefinite hang on hostile input into a bounded rejection."""
    with pytest.raises(ParseTimeout):
        await _parse("physics.pdf", PDF, timeout_s=0.0001)


async def test_errors_carry_a_machine_readable_payload() -> None:
    with pytest.raises(DocumentTooLarge) as excinfo:
        await _parse("physics.pdf", PDF, max_bytes=100)
    payload = excinfo.value.to_payload()
    assert payload["code"] == "document_too_large"
    assert payload["details"]["limit_bytes"] == 100


# ───────────────────────────────────────────────────── prompt-injection input


async def test_instruction_shaped_text_is_extracted_as_ordinary_content() -> None:
    """H-13. Document text is data.

    Stage 1's obligation is to extract it faithfully and mark it as content; the
    delimiting that stops it acting as an instruction happens at the LLM boundary.
    Faithful extraction is what makes that possible.
    """
    document, _ = await _parse("adversarial.txt", TXT)
    text = " ".join(b.text for b in document.blocks)
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in text
    assert all(b.type in {"heading", "paragraph", "list", "equation"} for b in document.blocks)
    assert "Photosynthesis" in text


# ──────────────────────────────────────────────────────────── unit helpers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("F = m * a", True),
        ("E = mc²", True),
        ("6CO2 + 6H2O = C6H12O6 + 6O2", True),
        ("The force is equal to mass times acceleration.", False),
        ("This is the introduction to the chapter.", False),
        ("", False),
    ],
)
def test_equation_detection_separates_maths_from_prose(text: str, expected: bool) -> None:
    """Prose containing an equals sign is still prose."""
    assert is_probable_equation(text) is expected


def test_latex_normalisation_converts_symbols() -> None:
    assert to_latex("α = β × 2") == r"\alpha = \beta \times 2"
    assert to_latex("Just some ordinary sentence text here.") is None


def test_latex_normalisation_handles_sub_and_superscripts() -> None:
    assert to_latex("E = mc²") == "E = mc^{2}"
    assert to_latex("H₂O = x") == "H_{2}O = x"


def test_existing_latex_passes_through_untouched() -> None:
    """A wrong reconstruction is worse than none, so markup is never rewritten."""
    assert to_latex(r"\vec{F} = m\vec{a}") == r"\vec{F} = m\vec{a}"
    assert to_latex(r"$E = mc^2$") == "E = mc^2"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.2 Newton's Laws", 2),
        ("Chapter 5 Motion", 1),
        ("1.2.3 Deep Section", 3),
        ("This is an ordinary sentence that runs on and on and should not match.", None),
    ],
)
def test_numbered_headings_are_recognised_without_font_information(
    text: str, expected: int | None
) -> None:
    """Explicit numbering wins outright — plain text has no typography to read."""
    assert infer_heading_level(TextSpan(text=text), body_size=None) == expected


def test_sentence_punctuation_disqualifies_a_heading() -> None:
    span = TextSpan(text="A short bold line.", font_size=20.0, bold=True)
    assert infer_heading_level(span, body_size=11.0) is None
