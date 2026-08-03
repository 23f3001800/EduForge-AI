"""Regressions for chunk overlap, section paths, and the grounding polarity gate.

Every test here pins a bug that was found by measuring the pipeline against a real
textbook (``Books/leph101.pdf``, NCERT Physics XI ch. 1) rather than a fixture. The
numbers in the docstrings are from that measurement, and they are what these tests
exist to keep from coming back:

================================  =======  ======
measure                            before   after
================================  =======  ======
chunk text that is duplicate        55.0%    9.7%
chunks opening with carried text  261/262   25/84
chunks with empty section_path      75.6%    3.6%
median chunk length (chars)           580     474
================================  =======  ======

The duplication that remains is the overlap actually doing its job: a bounded tail
carried across a *size-driven* split. The residual empty paths are the three chunks
of front matter that precede the chapter's first heading, which have no section to
name and correctly say so.
"""

from __future__ import annotations

from itertools import pairwise
from uuid import uuid4

import pytest

from contracts.document import Block
from evals.text import contains_verbatim
from stages.s1_document_intelligence.chunking import (
    CHARS_PER_TOKEN,
    OVERLAP_TOKENS,
    TARGET_TOKENS,
    carried_prefix_len,
    chunk_blocks,
)
from stages.s1_document_intelligence.structure import (
    assign_section_paths,
    infer_heading_level,
    section_path_of,
)
from stages.s9_validation.grounding import (
    TAU_HIGH,
    GroundableClaim,
    contradiction_risk,
    lexical_overlap,
    prefilter,
)

OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN


def _paragraph(index: int, text: str, *, section: list[str] | None = None) -> Block:
    return Block(
        block_id=f"b_{index:04d}",
        type="paragraph",
        text=text,
        page=1,
        section_path=section or [],
        char_start=0,
        char_end=len(text),
    )


def _heading(index: int, text: str, level: int = 2) -> Block:
    return Block(
        block_id=f"b_{index:04d}",
        type="heading",
        text=text,
        page=1,
        level=level,
        char_start=0,
        char_end=len(text),
    )


def _prose(marker: str, chars: int) -> str:
    """Filler that is unique per marker, so a repeat is unambiguous."""
    unit = f"{marker}word "
    return (unit * (chars // len(unit) + 1))[:chars]


def _duplicate_share(chunks: list) -> float:
    total = sum(len(c.text) for c in chunks)
    carried = sum(carried_prefix_len(prev.text, cur.text) for prev, cur in pairwise(chunks))
    return carried / total if total else 0.0


# ──────────────────────────────────────────────────────────── overlap carry


def test_overlap_does_not_compound_across_a_long_run_of_chunks() -> None:
    """The bug: ``carry = _overlap_tail(carry + buffer_text)``.

    Feeding the emitted body back into the carry makes chunk *n*'s carry part of
    chunk *n+1*'s carry. Over a long document it converges on every chunk being a
    copy of the one before it — 55% of all chunk text on the reference chapter.
    A single flat section with no headings is the pure case: nothing but size
    forces the breaks, so every break carries.
    """
    blocks = [_paragraph(i, _prose(f"p{i}", 1200)) for i in range(40)]
    chunks = chunk_blocks(uuid4(), blocks)

    assert len(chunks) > 5, "test needs several size-driven flushes to be meaningful"
    assert _duplicate_share(chunks) < 0.20


def test_no_single_chunk_is_mostly_carried_text() -> None:
    """A carry that is most of a chunk is not context, it is a second copy."""
    blocks = [_paragraph(i, _prose(f"p{i}", 1200)) for i in range(40)]
    chunks = chunk_blocks(uuid4(), blocks)

    for prev, cur in pairwise(chunks):
        carried = carried_prefix_len(prev.text, cur.text)
        assert carried <= len(cur.text) / 2, (
            f"chunk {cur.chunk_id} is {carried}/{len(cur.text)} carried text"
        )


def test_carry_is_bounded_by_the_overlap_budget() -> None:
    blocks = [_paragraph(i, _prose(f"p{i}", 1200)) for i in range(20)]
    chunks = chunk_blocks(uuid4(), blocks)

    for prev, cur in pairwise(chunks):
        assert carried_prefix_len(prev.text, cur.text) <= OVERLAP_CHARS


def test_a_short_chunk_is_never_carried_whole() -> None:
    """``_overlap_tail`` returned its whole argument below the 480-char budget.

    Every chunk shorter than the budget was therefore reproduced in full at the
    head of the next one — and in a heavily subheaded document most chunks are
    shorter than the budget.
    """
    blocks = [
        _paragraph(0, _prose("alpha", 200)),
        _paragraph(1, _prose("beta", TARGET_TOKENS * CHARS_PER_TOKEN + 100)),
        _paragraph(2, _prose("gamma", 200)),
    ]
    chunks = chunk_blocks(uuid4(), blocks)

    assert len(chunks) >= 2
    assert chunks[0].text not in chunks[1].text


def test_overlap_still_exists_when_a_section_is_split_by_size() -> None:
    """Bounded context, not zero context. A size-driven break is mid-thought."""
    blocks = [_paragraph(i, _prose(f"p{i}", 1500)) for i in range(6)]
    chunks = chunk_blocks(uuid4(), blocks)

    assert len(chunks) > 1
    carried = [carried_prefix_len(p.text, c.text) for p, c in pairwise(chunks)]
    assert any(n > 0 for n in carried), "size-driven splits lost their overlap entirely"


def test_carry_is_dropped_at_a_section_boundary() -> None:
    """A chunk flushed by a heading starts a new section and must start clean.

    Prefixing it with the previous section's tail undoes the very break that was
    made to stop a chunk belonging to two sections at once.
    """
    blocks = assign_section_paths(
        [
            _heading(0, "1 Electric Charge", level=2),
            _paragraph(1, _prose("chargebody", 900)),
            _heading(2, "2 Coulomb's Law", level=2),
            _paragraph(3, _prose("coulombbody", 900)),
        ]
    )
    chunks = chunk_blocks(uuid4(), blocks)

    assert len(chunks) == 2
    assert carried_prefix_len(chunks[0].text, chunks[1].text) == 0
    assert "chargebody" not in chunks[1].text


def test_carry_is_dropped_even_when_the_boundary_flush_emits_nothing() -> None:
    """Two headings in a row: the second must not inherit a stale carry."""
    blocks = assign_section_paths(
        [
            _paragraph(0, _prose("intro", 900)),
            _heading(1, "1 First", level=2),
            _heading(2, "2 Second", level=2),
            _paragraph(3, _prose("body", 400)),
        ]
    )
    chunks = chunk_blocks(uuid4(), blocks)

    assert "intro" not in chunks[-1].text


def test_carried_prefix_len_locates_the_seam() -> None:
    """The carried region stays inside ``text`` so a quote verifies against the
    chunk's own retrievable text; this is how a consumer finds where it ends."""
    blocks = [_paragraph(i, _prose(f"p{i}", 1500)) for i in range(6)]
    chunks = chunk_blocks(uuid4(), blocks)

    for prev, cur in pairwise(chunks):
        seam = carried_prefix_len(prev.text, cur.text)
        assert prev.text.endswith(cur.text[:seam])

    assert carried_prefix_len("", chunks[0].text) == 0


def test_token_count_matches_the_text_that_was_emitted() -> None:
    chunks = chunk_blocks(uuid4(), [_paragraph(i, _prose(f"p{i}", 1500)) for i in range(6)])
    for chunk in chunks:
        assert chunk.token_count == pytest.approx(len(chunk.text) / CHARS_PER_TOKEN, abs=2)


# ─────────────────────────────────────────────────────────────── section path


def test_a_chunk_opening_with_a_heading_is_filed_under_that_heading() -> None:
    """``Block.section_path`` holds a heading's *ancestors*, so taking it verbatim
    filed 76% of the reference chapter's chunks under no section at all."""
    blocks = assign_section_paths(
        [
            _heading(0, "Chapter 1", level=1),
            _heading(1, "1.4 Basic Properties of Electric Charge", level=2),
            _paragraph(2, _prose("body", 300)),
        ]
    )
    chunks = chunk_blocks(uuid4(), blocks)

    assert chunks[-1].section_path == [
        "Chapter 1",
        "1.4 Basic Properties of Electric Charge",
    ]


def test_a_top_level_heading_still_names_its_own_section() -> None:
    """The empty-path case: an h1 has no ancestors, so the old code left it empty."""
    blocks = assign_section_paths([_heading(0, "Chapter 1", level=1), _paragraph(1, "body text")])
    chunks = chunk_blocks(uuid4(), blocks)

    assert chunks[0].section_path == ["Chapter 1"]


def test_a_chunk_opening_with_prose_keeps_its_enclosing_path() -> None:
    """Only headings name themselves; a paragraph is genuinely inside its section."""
    blocks = assign_section_paths(
        [
            _heading(0, "1 Electric Charge", level=2),
            _paragraph(1, _prose("first", TARGET_TOKENS * CHARS_PER_TOKEN // 2)),
            _paragraph(2, _prose("second", TARGET_TOKENS * CHARS_PER_TOKEN // 2)),
        ]
    )
    chunks = chunk_blocks(uuid4(), blocks)

    assert len(chunks) == 2
    assert chunks[0].section_path == ["1 Electric Charge"], "opens with the heading"
    assert chunks[1].section_path == ["1 Electric Charge"], "opens with prose inside it"


def test_section_path_of_agrees_with_the_block_for_non_headings() -> None:
    block = _paragraph(0, "text", section=["A", "B"])
    assert section_path_of(block) == ["A", "B"]
    assert section_path_of(block) is not block.section_path, "must not alias the block"


# ───────────────────────────────────────────────────── false heading detection


@pytest.mark.parametrize(
    "line",
    [
        "1 2",  # q1 q2 with the subscripts flattened
        "2 3 n 1 2 3 n",
        "9 2 -2",
        "2 2 3/2",
        "4 ( )",
    ],
)
def test_flattened_formulae_are_not_numbered_headings(line: str) -> None:
    """A PDF renders ``q1q2 / 4pe0r^2`` as digits and stray letters, and that
    matches the numbered-heading pattern perfectly. 102 of 270 headings detected
    in the reference chapter were debris of this shape; each one opened a bogus
    section and cut the body into ~100-character chunks."""
    from stages.s1_document_intelligence.structure import TextSpan

    assert infer_heading_level(TextSpan(text=line, font_size=10.0), 10.0) is None


@pytest.mark.parametrize(
    ("line", "level"),
    [
        ("1.4.1 Additivity of charges", 3),
        ("1.5 Coulomb's Law", 2),
        ("Chapter 4 Moving Charges", 1),
    ],
)
def test_real_numbered_headings_still_pass(line: str, level: int) -> None:
    from stages.s1_document_intelligence.structure import TextSpan

    assert infer_heading_level(TextSpan(text=line, font_size=10.0), 10.0) == level


@pytest.mark.parametrize("line", ["F r", "4 p e", "r r r"])
def test_large_single_letter_math_is_not_a_heading(line: str) -> None:
    """The unnumbered path has only typography to go on, and a figure's variable
    labels are set large and bold. Two letters in a row separates a word from a
    symbol."""
    from stages.s1_document_intelligence.structure import TextSpan

    assert infer_heading_level(TextSpan(text=line, font_size=20.0, bold=True), 10.0) is None


def test_an_unnumbered_word_heading_still_passes_on_typography() -> None:
    from stages.s1_document_intelligence.structure import TextSpan

    assert infer_heading_level(TextSpan(text="SUMMARY", font_size=20.0), 10.0) == 1


# ──────────────────────────────────────────────── grounding contradiction gate


_CHUNK = (
    "Like charges repel and unlike charges attract. The force between two point "
    "charges increases as the magnitude of either charge increases, and decreases "
    "as the square of the distance separating them."
)


def _claim(text: str) -> GroundableClaim:
    return GroundableClaim(
        path="/knowledge/concepts/0",
        text=text,
        chunk_id="c_0000",
        stage="knowledge-extraction",
    )


def test_a_negated_claim_no_longer_auto_passes() -> None:
    """The false negative this gate exists for.

    ``lexical_overlap`` is a bag of tokens, so inserting "not" costs one token out
    of twenty and the claim still scores above TAU_HIGH. This exact shape measured
    0.70 and was returned ``supported`` with no model call — the hallucination
    detector reporting no hallucination.
    """
    text = (
        "The force between two point charges does not increase "
        "as the magnitude of either charge increases."
    )
    assert lexical_overlap(text, _CHUNK) >= TAU_HIGH, "precondition: the old code auto-passed this"

    decided, ambiguous = prefilter([_claim(text)], {"c_0000": _CHUNK})
    assert decided == []
    assert len(ambiguous) == 1


def test_an_antonym_swap_no_longer_auto_passes() -> None:
    """No negation at all — every token is one the source uses, just reassigned."""
    text = "Like charges attract and unlike charges repel."
    assert contradiction_risk(text, "Like charges repel and unlike charges attract.") is None, (
        "both sides appear in the passage, so the pair alone cannot tell us which"
    )

    span = "Like charges repel one another with a force along the line joining them."
    assert contradiction_risk("Like charges attract one another with a force.", span) is not None


def test_a_dropped_negation_is_caught() -> None:
    span = "A charged body does not attract a neutral conductor in this arrangement."
    assert contradiction_risk("A charged body attracts a neutral conductor", span) is None
    assert contradiction_risk("A charged body does attract a neutral conductor", span) is not None


def test_a_faithful_restatement_still_auto_passes() -> None:
    """The gate must cost nothing on the common path, including the auto-pass."""
    text = "Like charges repel and unlike charges attract."
    decided, ambiguous = prefilter([_claim(text)], {"c_0000": _CHUNK})

    assert ambiguous == []
    assert [v.verdict for v in decided] == ["supported"]


def test_a_negation_the_source_shares_does_not_route_to_the_judge() -> None:
    """A negator in both texts is the claim repeating its source, not contradicting it."""
    span = "A neutral body is not charged, and it does not experience a net force."
    assert contradiction_risk("A neutral body is not charged.", span) is None


def test_a_paraphrase_still_goes_to_the_judge_rather_than_being_failed() -> None:
    """Unchanged behaviour, re-pinned: low overlap is a paraphrase signal."""
    text = "When a bus brakes suddenly, passengers continue moving forward."
    decided, ambiguous = prefilter([_claim(text)], {"c_0000": _CHUNK})

    assert decided == []
    assert len(ambiguous) == 1


def test_an_unresolvable_chunk_id_is_still_dispositive() -> None:
    decided, ambiguous = prefilter([_claim("anything")], {})
    assert ambiguous == []
    assert [v.verdict for v in decided] == ["unsupported"]


def test_the_gate_is_subject_agnostic() -> None:
    """NFR-01: the same code, no subject terms. A history claim flips the same way."""
    span = "The Non-Cooperation Movement was suspended after the violence at Chauri Chaura."
    text = "The Non-Cooperation Movement was not suspended after the violence at Chauri Chaura."
    assert lexical_overlap(text, span) >= TAU_HIGH
    assert contradiction_risk(text, span) is not None


# ──────────────────────────────────────────────────────── verbatim alignment


def test_contains_verbatim_is_token_aligned() -> None:
    """Raw substring containment credited a quote that straddles word boundaries."""
    assert not contains_verbatim("art of war", "a part of warfare")
    assert not contains_verbatim("harge", "the charge on an electron")


def test_contains_verbatim_still_ignores_punctuation_and_case() -> None:
    assert contains_verbatim("F = m a.", "the relation F = m a holds")
    assert contains_verbatim("Charge Is Quantised", "we say that charge is quantised, meaning")


def test_contains_verbatim_matches_at_the_edges_of_the_span() -> None:
    assert contains_verbatim("charge", "charge")
    assert contains_verbatim("like charges", "like charges repel")
    assert contains_verbatim("charges repel", "like charges repel")


def test_an_empty_quote_is_never_verbatim() -> None:
    assert not contains_verbatim("", "anything at all")
    assert not contains_verbatim("   ", "anything at all")
