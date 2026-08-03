"""Stage 1 contracts — document intelligence.

Everything here is produced deterministically by parsing. No model calls are
involved, so the same bytes in must yield the same structure out (docs/10 § M2).

The types are shaped around FR-02 ("preserve structure"), which is 15% of the
grade and is *not* satisfied by returning a flat string of text. A table must
survive as rows and cells; an equation must survive as something renderable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.primitives import Identifier, StrictModel

__all__ = [
    "Block",
    "BlockType",
    "Chunk",
    "DocumentMetadata",
    "DocumentStats",
    "OcrProvenance",
    "OutlineNode",
    "StructuredDocument",
    "TableData",
]

BlockType = Literal[
    "heading",
    "paragraph",
    "list",
    "table",
    "figure_caption",
    "equation",
    "code",
]


class TableData(StrictModel):
    """A table preserved as structure, never flattened to a string.

    Flattening is the single most common way "structure preservation" is silently
    failed: the text is all present, so a substring assertion passes, but the
    relationship between a cell and its column header is gone.
    """

    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    caption: str | None = None

    @model_validator(mode="after")
    def _rows_match_headers(self) -> TableData:
        if self.headers:
            width = len(self.headers)
            ragged = [i for i, r in enumerate(self.rows) if len(r) != width]
            if ragged:
                raise ValueError(
                    f"rows {ragged[:5]} do not match header width {width}; "
                    "pad short rows rather than dropping cells"
                )
        return self


class Block(StrictModel):
    """One structural unit of the source document, in reading order."""

    block_id: Identifier
    type: BlockType
    text: str = Field(description="Plain-text rendering; always populated, even for tables.")
    page: int | None = Field(default=None, ge=1)
    section_path: list[str] = Field(
        default_factory=list,
        description="Enclosing heading stack, outermost first, e.g. "
        '["Chapter 3", "3.2 Newton\'s Laws"].',
    )
    level: int | None = Field(default=None, ge=1, le=6, description="Heading depth.")
    latex: str | None = Field(
        default=None,
        description="Normalised LaTeX for equation blocks. `text` keeps the raw "
        "extraction as a fallback when normalisation is not recoverable.",
    )
    table: TableData | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Block:
        if self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start")
        if self.type == "table" and self.table is None:
            raise ValueError("block of type 'table' must carry `table`")
        if self.type != "table" and self.table is not None:
            raise ValueError("`table` is only valid on a block of type 'table'")
        if self.type == "heading" and self.level is None:
            raise ValueError("block of type 'heading' must carry `level`")
        return self


class OutlineNode(StrictModel):
    """A node in the document's heading tree."""

    block_id: Identifier
    title: str
    level: int = Field(ge=1, le=6)
    page: int | None = Field(default=None, ge=1)
    children: list[OutlineNode] = Field(default_factory=list)


class DocumentStats(StrictModel):
    """Counts used by later stages to decide strategy, and by the UI to show what
    was actually recovered from the file."""

    headings: int = Field(default=0, ge=0)
    paragraphs: int = Field(default=0, ge=0)
    tables: int = Field(default=0, ge=0)
    equations: int = Field(default=0, ge=0)
    figures: int = Field(default=0, ge=0)
    code_blocks: int = Field(default=0, ge=0)


class DocumentMetadata(StrictModel):
    filename: str = Field(min_length=1)
    mime: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=0)
    word_count: int | None = Field(default=None, ge=0)
    title: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    detected_language: str | None = Field(
        default=None, description="BCP-47 tag detected from content, e.g. 'en', 'hi'."
    )
    ocr: OcrProvenance | None = Field(
        default=None,
        description="Present only when some page had no text layer and was read by OCR.",
    )


class OcrProvenance(StrictModel):
    """Which pages a machine read, with what, and how sure it was.

    Recorded because OCR is the one step whose output can be *confidently*
    wrong. Every later stage grounds its claims in evidence spans checked
    against the source text — but if OCR misread the source, those checks
    validate the error rather than catching it. Grounding cannot see below
    itself, so the uncertainty has to be carried forward explicitly and shown
    to the teacher.

    ``confidence`` is ``None`` when the engine does not report one, which is
    not the same as zero and must not be rendered as a score. See
    ``evals.framework`` for the same distinction applied to metrics.
    """

    engine: str = Field(min_length=1, description="Engine identifier, e.g. 'tesseract'.")
    pages: list[int] = Field(default_factory=list, description="1-based pages read by OCR.")
    failed_pages: list[int] = Field(
        default_factory=list,
        description="Pages that had no text layer and could not be recognised either.",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    #: The threshold in force for this run, so a reader can tell whether the
    #: confidence above was considered acceptable without knowing the config.
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def below_threshold(self) -> bool:
        if self.confidence is None or self.min_confidence is None:
            return False
        return self.confidence < self.min_confidence


class StructuredDocument(StrictModel):
    """The complete deterministic parse of one uploaded file."""

    document_id: UUID
    metadata: DocumentMetadata
    blocks: list[Block] = Field(min_length=1)
    outline: list[OutlineNode] = Field(default_factory=list)
    stats: DocumentStats = Field(default_factory=DocumentStats)


class Chunk(StrictModel):
    """A retrieval unit.

    Chunking is section-aware (docs/03 § 4.1): a chunk never splits a table or an
    equation, and it carries the heading stack it came from so retrieval can filter
    by section and so evidence spans can cite a page and a location a teacher can
    actually find.
    """

    chunk_id: Identifier
    document_id: UUID
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    section_path: list[str] = Field(default_factory=list)
    token_count: int = Field(ge=1)
    block_ids: list[Identifier] = Field(default_factory=list)
