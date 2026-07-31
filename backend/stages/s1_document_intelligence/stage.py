"""Stage 1 — Document Intelligence.

Parses an uploaded file into a :class:`StructuredDocument` plus retrieval chunks.
Makes **zero model calls**: the same bytes in must always produce the same
structure out, which is asserted in the test suite.

This stage is a trust boundary. Input arrives from the public internet, so limits
are enforced here rather than assumed upstream, and a parser is given a hard
wall-clock budget so a malformed file becomes a bounded rejection instead of a
hung worker (NFR-09).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any
from uuid import UUID

from contracts.document import (
    Block,
    DocumentMetadata,
    DocumentStats,
    StructuredDocument,
)
from stages.base import StageContext, stage_span
from stages.s1_document_intelligence import parsers
from stages.s1_document_intelligence.chunking import chunk_blocks
from stages.s1_document_intelligence.errors import (
    DocumentTooLarge,
    EmptyDocument,
    ParseTimeout,
    UnsupportedMediaType,
)
from stages.s1_document_intelligence.structure import assign_section_paths, build_outline

__all__ = ["DocumentIntelligenceStage", "parse_document"]

PARSER_BY_MIME = {
    "application/pdf": parsers.parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parsers.parse_docx,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": parsers.parse_pptx,
    "text/plain": parsers.parse_text,
    "text/markdown": parsers.parse_text,
}


def _stats(blocks: list[Block]) -> DocumentStats:
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.type] = counts.get(block.type, 0) + 1
    return DocumentStats(
        headings=counts.get("heading", 0),
        paragraphs=counts.get("paragraph", 0),
        tables=counts.get("table", 0),
        equations=counts.get("equation", 0),
        figures=counts.get("figure_caption", 0),
        code_blocks=counts.get("code", 0),
    )


async def parse_document(
    *,
    document_id: UUID,
    payload: bytes,
    filename: str,
    mime: str,
    max_bytes: int,
    max_pages: int,
    timeout_s: float,
) -> tuple[StructuredDocument, list[Any]]:
    """Parse bytes into a structured document and its chunks."""
    if len(payload) > max_bytes:
        raise DocumentTooLarge(
            f"File is {len(payload)} bytes; limit is {max_bytes}.",
            size_bytes=len(payload),
            limit_bytes=max_bytes,
        )

    parser = PARSER_BY_MIME.get(mime)
    if parser is None:
        raise UnsupportedMediaType(
            f"No parser for media type {mime!r}.",
            mime=mime,
            supported=sorted(PARSER_BY_MIME),
        )

    # Parsers are synchronous and CPU-bound; run off the event loop so one hostile
    # file cannot stall every other request in the process.
    try:
        blocks: list[Block] = await asyncio.wait_for(
            asyncio.to_thread(parser, payload, max_pages=max_pages),
            timeout=timeout_s,
        )
    except TimeoutError as exc:
        raise ParseTimeout(
            f"Parsing exceeded {timeout_s:.0f}s and was abandoned.", timeout_s=timeout_s
        ) from exc

    if not blocks:
        raise EmptyDocument(
            "No extractable text was found. A scanned document without a text "
            "layer needs OCR, which this pipeline does not perform."
        )

    blocks = assign_section_paths(blocks)
    word_count = sum(len(b.text.split()) for b in blocks)
    pages = [b.page for b in blocks if b.page]

    document = StructuredDocument(
        document_id=document_id,
        metadata=DocumentMetadata(
            filename=filename,
            mime=mime,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            page_count=max(pages) if pages else None,
            word_count=word_count,
            title=next((b.text for b in blocks if b.type == "heading"), None),
        ),
        blocks=blocks,
        outline=build_outline(blocks),
        stats=_stats(blocks),
    )
    return document, chunk_blocks(document_id, blocks)


class DocumentIntelligenceStage:
    """Pipeline node wrapper. Replaces the stage-1 stub."""

    name = "document-intelligence"

    def __init__(
        self,
        *,
        payload: bytes,
        filename: str,
        mime: str,
        max_bytes: int,
        max_pages: int,
        timeout_s: float,
    ) -> None:
        self._payload = payload
        self._filename = filename
        self._mime = mime
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._timeout_s = timeout_s

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            document, chunks = await parse_document(
                document_id=UUID(state["document_id"]),
                payload=self._payload,
                filename=self._filename,
                mime=self._mime,
                max_bytes=self._max_bytes,
                max_pages=self._max_pages,
                timeout_s=self._timeout_s,
            )
            await span.progress(0.8, message=f"{len(document.blocks)} blocks, {len(chunks)} chunks")
            if document.stats.equations:
                span.warn(f"{document.stats.equations} equations detected")
            return {
                "structured_document": document.model_dump(mode="json"),
                "chunks": [c.model_dump(mode="json") for c in chunks],
            }
