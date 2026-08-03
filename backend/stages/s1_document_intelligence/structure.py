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
    "section_path_of",
]

#: "1.", "1.2", "1.2.3", "Chapter 4", "Section 2" — depth comes from the dot count.
NUMBERED_HEADING = re.compile(
    r"^\s*(?:(?P<word>chapter|section|unit|lesson|part)\s+)?"
    r"(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.*)$",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"[.!?;:,]\s*$")
_MAX_HEADING_WORDS = 14
#: A section title contains at least one *word*, and two letters in a row is the
#: weakest available test for one. Neither numbering nor typography is sufficient
#: on its own: a PDF flattens ``q₁q₂ / 4πε₀r²`` to ``4 p e`` and ``2 3 n 1 2 3 n``,
#: which match :data:`NUMBERED_HEADING` exactly, and it sets a figure's variable
#: labels ("F r", "r r r") large and bold, which is all the unnumbered path has to
#: go on. On the reference physics chapter 102 of 270 detected headings were
#: formula debris of this shape. Each one opened a bogus section, so the body was
#: cut into ~100-character chunks filed under section names like "1 2" — a false
#: heading fragments the document and misleads every downstream stage about its
#: structure, which is why this module errs quiet.
_TITLE_WORD = re.compile(r"[^\W\d_]{2,}")
#: A numbered heading's title starts the way a title starts. PDF extraction emits
#: a wrapped body line as its own span, and any such line beginning with a year
#: matches :data:`NUMBERED_HEADING` with the year as the section number:
#: "1791 further discredited the monarchy, and military defeats after" parses as
#: section 1791, title "further discredited...". On the reference history article
#: 299 of 365 detected headings were mid-sentence prose of exactly this shape.
#: A continuation of a sentence begins in lower case; a section title does not.
#: Losing a genuinely lower-cased heading costs some section context, which is the
#: cheaper error — this module errs quiet by design.
_TITLE_START = re.compile(r"^[^\w]*[^\Wa-z]")


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


def _is_title_shaped(text: str) -> bool:
    """Is this line short, unpunctuated, and started like a title?

    Applied to the whole line on the typography path and to the text after the
    section number on the numbered path, because a wrapped body line beginning
    with a year counterfeits numbering perfectly and shape is the only thing left
    that tells the two apart.
    """
    return bool(
        _TITLE_WORD.search(text)
        and _TITLE_START.match(text)
        and len(text.split()) <= _MAX_HEADING_WORDS
        and not _SENTENCE_END.search(text)
    )


def infer_heading_level(
    span: TextSpan, body_size: float | None, *, min_ratio: float = 1.15
) -> int | None:
    """Return a heading depth, or None when the line is body text.

    Explicit numbering wins over *typography* — "3.2 Newton's Laws" is a heading
    whatever its font size, and its depth is unambiguous. It does not win over
    shape: numbering is the easiest signal to counterfeit, because a flattened
    formula and a wrapped line starting with a year both look exactly like it. So
    both paths require the line to look like a title; only the size requirement is
    waived. Otherwise a line must be larger than body text *and* look like a
    title: short, and not sentence-punctuated.
    """
    text = span.text.strip()
    if not text:
        return None

    match = NUMBERED_HEADING.match(text)
    if match and _is_title_shaped(match.group("title")):
        depth = match.group("number").count(".") + 1
        if match.group("word"):
            depth = 1
        return min(depth, 6)

    if not _is_title_shaped(text):
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
            # A heading's own path is its ancestors, not itself. That is the right
            # shape for a *block* — a heading is not nested inside itself — but it
            # is the wrong shape for anything asking "which section is this?", so
            # use :func:`section_path_of` for that question rather than reading
            # ``section_path`` directly.
            block.section_path = [title for _, title in stack]
            stack.append((block.level, block.text.strip()))
        else:
            block.section_path = [title for _, title in stack]
    return blocks


def section_path_of(block: Block) -> list[str]:
    """The section this block *is in*, including itself when it is a heading.

    ``Block.section_path`` holds a heading's ancestors, which is correct for the
    block but wrong for a chunk that opens with that heading: taking it verbatim
    files "1.4 Basic Properties of Electric Charge" and everything under it into
    the enclosing chapter, or — for a top-level heading — into no section at all.
    On the reference physics chapter that emptied the section path of 76% of all
    chunks and dropped them into a single unnamed bucket downstream.
    """
    title = block.text.strip()
    if block.type == "heading" and title:
        return [*block.section_path, title]
    return list(block.section_path)


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
