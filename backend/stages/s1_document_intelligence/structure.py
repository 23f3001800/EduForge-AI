"""Heading detection, section paths, and the outline tree.

DOCX and PPTX carry explicit style information, so headings are read directly.
PDF carries none — a heading is just text that happens to be larger — so it is
inferred from font size relative to the document's body size, plus numbering and
shape cues.

The heuristics are deliberately conservative. A missed heading costs some section
context; a *false* heading fragments the document and misleads every downstream
stage about its structure. When the signals disagree, this stays quiet.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from contracts.document import Block, OutlineNode

__all__ = [
    "NUMBERED_HEADING",
    "assign_section_paths",
    "body_font_size",
    "build_outline",
    "infer_heading_level",
]

#: "1.", "1.2", "1.2.3", "Chapter 4", "Section 2" — depth comes from the dot count.
NUMBERED_HEADING = re.compile(
    r"^\s*(?:(?P<word>chapter|section|unit|lesson|part)\s+)?"
    r"(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.*)$",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"[.!?;:,]\s*$")
_MAX_HEADING_WORDS = 14


@dataclass(slots=True)
class TextSpan:
    """A line of text with whatever typography the source preserved."""

    text: str
    page: int | None = None
    font_size: float | None = None
    bold: bool = False


def body_font_size(spans: list[TextSpan]) -> float | None:
    """Modal font size, weighted by character count — the document's body text.

    Weighting by characters rather than by line matters: a document with many
    short headings and few long paragraphs would otherwise elect a heading size
    as "body" and then classify the actual prose as headings.
    """
    weights: Counter[float] = Counter()
    for span in spans:
        if span.font_size and span.text.strip():
            weights[round(span.font_size, 1)] += len(span.text.strip())
    if not weights:
        return None
    return weights.most_common(1)[0][0]


def infer_heading_level(
    span: TextSpan, body_size: float | None, *, min_ratio: float = 1.15
) -> int | None:
    """Return a heading depth, or None when the line is body text.

    Explicit numbering wins outright — "3.2 Newton's Laws" is a heading whatever
    its font size, and its depth is unambiguous. Otherwise a line must be larger
    than body text *and* look like a title: short, and not sentence-punctuated.
    """
    text = span.text.strip()
    if not text:
        return None

    match = NUMBERED_HEADING.match(text)
    if match:
        depth = match.group("number").count(".") + 1
        if match.group("word"):
            depth = 1
        return min(depth, 6)

    if len(text.split()) > _MAX_HEADING_WORDS or _SENTENCE_END.search(text):
        return None

    if body_size and span.font_size:
        ratio = span.font_size / body_size
        if ratio >= min_ratio * 1.6:
            return 1
        if ratio >= min_ratio * 1.3:
            return 2
        if ratio >= min_ratio:
            return 3

    # No size information (plain text, or a PDF that lost it): fall back to bold
    # plus title shape. Weak, but better than declaring a document flat.
    if span.bold and len(text.split()) <= _MAX_HEADING_WORDS:
        return 2
    return None


def assign_section_paths(blocks: list[Block]) -> list[Block]:
    """Populate each block's enclosing heading stack, in document order.

    Section paths are what let retrieval filter by section and what let an
    evidence span tell a teacher *where in the chapter* a claim came from.
    """
    stack: list[tuple[int, str]] = []
    for block in blocks:
        if block.type == "heading" and block.level:
            while stack and stack[-1][0] >= block.level:
                stack.pop()
            # A heading's own path is its ancestors, not itself.
            block.section_path = [title for _, title in stack]
            stack.append((block.level, block.text.strip()))
        else:
            block.section_path = [title for _, title in stack]
    return blocks


def build_outline(blocks: list[Block]) -> list[OutlineNode]:
    """Nest headings into a tree.

    Tolerates skipped levels (an h1 followed by an h3), which real documents do
    constantly; the h3 simply attaches to the nearest shallower ancestor.
    """
    roots: list[OutlineNode] = []
    stack: list[OutlineNode] = []

    for block in blocks:
        if block.type != "heading" or not block.level:
            continue
        node = OutlineNode(
            block_id=block.block_id,
            title=block.text.strip(),
            level=block.level,
            page=block.page,
            children=[],
        )
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    return roots
