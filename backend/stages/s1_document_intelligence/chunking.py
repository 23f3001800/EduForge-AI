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

Overlap has three invariants, all of which were violated at once by the original
implementation and all of which are pinned by tests:

* **It never compounds.** The tail carried into chunk *n+1* is taken from chunk
  *n*'s own blocks, not from the carry-prefixed body that was emitted. Deriving
  it from the body makes chunk *n*'s carry part of chunk *n+1*'s carry, so a
  short run of small chunks converges on every chunk being a copy of the one
  before it. On the reference physics chapter that put 55% of all chunk text in
  duplicate and left 261 of 262 chunks opening with carried text.
* **It never exceeds half the chunk it came from.** A carry that is the whole
  previous chunk is not context, it is a second copy — and :func:`_overlap_tail`
  returned exactly that for any chunk under the character budget.
* **It never crosses a section boundary.** A chunk is flushed at a major heading
  precisely so the new section starts clean; prefixing it with the tail of the
  previous section undoes that and hands retrieval a chunk that belongs to two
  sections, which is what section-aware chunking exists to prevent.

The carried prefix stays inside ``Chunk.text``, so a quote verified against a
chunk is verified against the chunk's own retrievable text and nothing has to
know about the seam. :func:`carried_prefix_len` recovers the seam position for
any consumer that needs to attribute a match to the chunk's own body — that is
derivable rather than stored because ``contracts.document.Chunk`` forbids extra
fields, and an ``overlap_char_len`` field there would be the better home for it.
"""

from __future__ import annotations

from contracts.document import Block, Chunk
from contracts.primitives import Identifier  # noqa: F401 - documents the id shape
from stages.s1_document_intelligence.structure import section_path_of

__all__ = [
    "MAX_OVERLAP_SHARE",
    "OVERLAP_TOKENS",
    "TARGET_TOKENS",
    "carried_prefix_len",
    "chunk_blocks",
    "estimate_tokens",
]

TARGET_TOKENS = 800
OVERLAP_TOKENS = 120
#: Empirical average across English prose and technical text. Good enough to
#: bound a chunk; never used for billing.
CHARS_PER_TOKEN = 4
#: A carry may be at most this share of the chunk it is taken from. Without it a
#: chunk shorter than the overlap budget is carried whole, and every short chunk
#: — which is most of them in a heavily subheaded document — appears twice.
MAX_OVERLAP_SHARE = 0.5

_ATOMIC = {"table", "equation"}
_BREAK_AT_LEVEL = 2


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _overlap_tail(text: str) -> str:
    """Trailing context carried into the next chunk, cut on a word boundary.

    Bounded twice over: by ``OVERLAP_TOKENS`` and by ``MAX_OVERLAP_SHARE`` of the
    source text. Returns "" when the source is too short for either bound to
    leave a usable word.
    """
    budget = min(OVERLAP_TOKENS * CHARS_PER_TOKEN, int(len(text) * MAX_OVERLAP_SHARE))
    if budget <= 0:
        return ""
    tail = text[-budget:]
    space = tail.find(" ")
    if space == -1:
        # No word boundary inside the budget: carrying a fragment of a word is
        # worse than carrying nothing, because it retrieves as a nonsense token.
        return ""
    return tail[space + 1 :].lstrip()


def carried_prefix_len(previous_text: str, text: str) -> int:
    """Characters at the head of ``text`` that repeat the tail of ``previous_text``.

    The seam between a chunk's carried context and its own body. Zero for the
    first chunk of a document and for any chunk that opens a section.
    """
    limit = min(len(previous_text), len(text), OVERLAP_TOKENS * CHARS_PER_TOKEN)
    for size in range(limit, 0, -1):
        if previous_text.endswith(text[:size]):
            return size
    return 0


def chunk_blocks(document_id: object, blocks: list[Block]) -> list[Chunk]:
    """Group blocks into retrieval chunks, preserving structure."""
    chunks: list[Chunk] = []
    buffer: list[Block] = []
    buffer_text = ""
    carry = ""

    def flush(*, boundary: bool = False) -> None:
        """Emit the buffered blocks as a chunk.

        ``boundary`` marks a flush forced by a section heading rather than by
        size: the next chunk starts a new section and must not inherit the
        previous one's tail.
        """
        nonlocal buffer, buffer_text, carry
        if not buffer:
            if boundary:
                carry = ""
            return
        body = f"{carry}\n{buffer_text}" if carry else buffer_text
        ordinal = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=f"c_{ordinal:04d}",
                document_id=document_id,  # type: ignore[arg-type]
                ordinal=ordinal,
                text=body.strip(),
                page=buffer[0].page,
                # The chunk's own section, including the heading it opens with —
                # `Block.section_path` alone names only that heading's ancestors.
                section_path=section_path_of(buffer[0]),
                token_count=estimate_tokens(body),
                block_ids=[b.block_id for b in buffer],
            )
        )
        # Derived from this chunk's own blocks, never from `body`: `body` already
        # contains the previous carry, and feeding it back in makes the overlap
        # compound until every chunk is a copy of its predecessor.
        carry = "" if boundary else _overlap_tail(buffer_text).strip()
        buffer = []
        buffer_text = ""

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        # A major heading starts a new chunk: a chunk spanning two sections gets
        # cited as belonging to both.
        if block.type == "heading" and block.level and block.level <= _BREAK_AT_LEVEL:
            flush(boundary=True)

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
