"""Structure-aware chunking.

Chunks are the unit of retrieval *and* the unit of citation. Every evidence span
in the finished package points at a chunk, so a chunk that splits a table down
the middle produces a citation a teacher cannot make sense of.

Two rules follow from that:

* Never split a table or an equation. A table row separated from its headers has
  lost the information that made it a table.
* Break on structural boundaries first, size second. A chunk that spans two
  sections gets cited as belonging to both, which is worse than a short chunk.

Token counts are estimated, not tokenised. Chunking runs before any provider is
chosen, and provider tokenisers disagree anyway; the estimate only has to be
consistent enough to bound chunk size.
"""

from __future__ import annotations

from contracts.document import Block, Chunk
from contracts.primitives import Identifier  # noqa: F401 - documents the id shape

__all__ = ["OVERLAP_TOKENS", "TARGET_TOKENS", "chunk_blocks", "estimate_tokens"]

TARGET_TOKENS = 800
OVERLAP_TOKENS = 120
#: Empirical average across English prose and technical text. Good enough to
#: bound a chunk; never used for billing.
CHARS_PER_TOKEN = 4

_ATOMIC = {"table", "equation"}
_BREAK_AT_LEVEL = 2


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _overlap_tail(text: str) -> str:
    """Trailing context carried into the next chunk, cut on a word boundary."""
    budget = OVERLAP_TOKENS * CHARS_PER_TOKEN
    if len(text) <= budget:
        return text
    tail = text[-budget:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else tail


def chunk_blocks(document_id: object, blocks: list[Block]) -> list[Chunk]:
    """Group blocks into retrieval chunks, preserving structure."""
    chunks: list[Chunk] = []
    buffer: list[Block] = []
    buffer_text = ""
    carry = ""

    def flush() -> None:
        nonlocal buffer, buffer_text, carry
        if not buffer:
            return
        body = carry + buffer_text if carry else buffer_text
        ordinal = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=f"c_{ordinal:04d}",
                document_id=document_id,  # type: ignore[arg-type]
                ordinal=ordinal,
                text=body.strip(),
                page=buffer[0].page,
                section_path=list(buffer[0].section_path),
                token_count=estimate_tokens(body),
                block_ids=[b.block_id for b in buffer],
            )
        )
        carry = _overlap_tail(body)
        buffer = []
        buffer_text = ""

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        # A major heading starts a new chunk: a chunk spanning two sections gets
        # cited as belonging to both.
        if block.type == "heading" and block.level and block.level <= _BREAK_AT_LEVEL:
            flush()

        block_tokens = estimate_tokens(text)

        if block.type in _ATOMIC:
            # Atomic blocks are never split. One that exceeds the target becomes
            # its own oversized chunk rather than being cut in half.
            if buffer and estimate_tokens(buffer_text) + block_tokens > TARGET_TOKENS:
                flush()
            buffer.append(block)
            buffer_text += text + "\n"
            if estimate_tokens(buffer_text) >= TARGET_TOKENS:
                flush()
            continue

        if buffer and estimate_tokens(buffer_text) + block_tokens > TARGET_TOKENS:
            flush()

        buffer.append(block)
        buffer_text += text + "\n"

    flush()
    return chunks
