"""Font registration for stage-10 PDF rendering.

BR-06 requires non-Latin scripts to render — a Devanagari lesson plan that comes
out as tofu boxes is a failed deliverable — and neither of fpdf2's built-in core
fonts (Helvetica/Times/Courier, Latin-1 only) nor a generic Latin TTF can do
that. `NotoSans` covers the Latin/Cyrillic/Greek range the pipeline's English
output uses; `NotoSansDevanagari` covers the Devanagari block an
``output_language="hi"`` run produces. Both ship under the OFL inside this
package (see the accompanying ``OFL-*.txt`` files) so the licence travels with
the font instead of depending on the deploy environment happening to have one
installed — which is also why these are embedded TTFs rather than a system font
lookup: a container that never had Devanagari fonts installed must still render
Devanagari correctly.

Both files are variable fonts. Registering them *without* the ``variations``
argument takes fontTools' fast path (no instancer run) and lands on the font's
default named instance — Regular weight, per each file's ``fvar`` table — which
is what every rendered document uses here. Instancing an explicit Bold cut
through ``variations`` costs several seconds per family (fontTools re-flattens
every glyph outline), which would make every render — and this whole test
suite — slow for a cosmetic win, so headings in this package are set apart by
size and rules rather than by weight.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

__all__ = ["DEVANAGARI_FONT", "LATIN_FONT", "has_devanagari", "register_fonts"]

FONT_DIR = Path(__file__).parent / "fonts"

LATIN_FONT = "NotoSans"
DEVANAGARI_FONT = "NotoSansDevanagari"

_LATIN_FONT_FILE = FONT_DIR / "NotoSans[wdth,wght].ttf"
_DEVANAGARI_FONT_FILE = FONT_DIR / "NotoSansDevanagari[wdth,wght].ttf"
_LATIN_BOLD_FILE = FONT_DIR / "NotoSans-Bold.ttf"
_DEVANAGARI_BOLD_FILE = FONT_DIR / "NotoSansDevanagari-Bold.ttf"

#: Unicode block U+0900-U+097F (Devanagari). This is the one non-Latin script
#: the pipeline ships a dedicated font for; text in a third script still
#: renders — fpdf2 embeds NotoSans' own cmap for whatever it covers — just
#: without the fallback guarantee this module gives Devanagari specifically.
_DEVANAGARI_START, _DEVANAGARI_END = 0x0900, 0x097F


def has_devanagari(text: str) -> bool:
    """True if ``text`` contains at least one Devanagari codepoint."""
    return any(_DEVANAGARI_START <= ord(ch) <= _DEVANAGARI_END for ch in text)


#: Readable stand-ins for mathematical symbols, applied only where the font
#: genuinely lacks the glyph.
#:
#: This is a correctness fix wearing a typography hat. NotoSans covers Latin,
#: Greek and the common typographic marks, but not the mathematical operators
#: block — 24 of the symbols a physics or calculus chapter uses, including the
#: most frequent ones. fpdf2's behaviour for an uncoverable glyph is to *drop*
#: it and log, so "E ∝ 1/r²" was rendering as "E  1/r²": not mangled, not
#: obviously broken, just quietly saying something different from the source.
#: Silent deletion is the worst available outcome, and any legible substitute
#: beats it.
#:
#: Several entries map to a glyph the font does have (∑→Σ, ∏→Π, ∆→Δ, ⊥→⟂'s
#: word form) because the n-ary operators are near-identical in shape to their
#: Greek counterparts, which is a better answer than a word.
_MATH_FALLBACKS = {
    "→": "->",
    "⇒": "=>",
    "≈": "~",
    "≠": "!=",
    "≤": "<=",
    "≥": ">=",
    "≪": "<<",
    "≫": ">>",
    "∓": "-/+",
    "√": "sqrt",
    "∫": "integral",
    "∮": "closed integral",
    "∞": "infinity",
    "∝": "proportional to",
    "∂": "d",
    "∇": "grad",
    "∆": "Δ",
    "∑": "Σ",
    "∏": "Π",
    "⟂": "perpendicular to",
    "⊥": "perpendicular to",
    "∠": "angle ",
    "∴": "therefore",
    "∵": "because",
}


def _uncovered() -> frozenset[str]:
    """Which fallback keys this build's font actually cannot draw.

    Read from the font's own cmap rather than hardcoded, so that dropping in a
    wider font (NotoSansMath, say) silently retires the substitutions it makes
    unnecessary instead of leaving them to disfigure text the font can now set
    properly.
    """
    try:
        from fontTools import ttLib
    except ImportError:  # pragma: no cover - fontTools ships with fpdf2
        return frozenset(_MATH_FALLBACKS)

    try:
        with ttLib.TTFont(_LATIN_FONT_FILE, lazy=True) as font:
            covered: set[int] = set()
            for table in font["cmap"].tables:
                covered |= set(table.cmap)
    except Exception:  # pragma: no cover - a broken font is the renderer's problem
        return frozenset(_MATH_FALLBACKS)

    return frozenset(ch for ch in _MATH_FALLBACKS if ord(ch) not in covered)


#: Computed once per process: reading the cmap costs milliseconds, and every
#: string written to every artifact passes through ``typeset``.
_SUBSTITUTIONS = {ch: _MATH_FALLBACKS[ch] for ch in _uncovered()}


#: Vector notation. U+20D7 is a *combining* arrow that sits over the preceding
#: letter, and no font here draws it, so "E⃗" rendered as a bare "E" — losing the
#: distinction between a field vector and its magnitude, which in an
#: electrostatics chapter is the whole point of the notation.
_COMBINING_VECTOR = "⃗"


def typeset(text: str) -> str:
    """Make ``text`` safe to draw: substitute what the font cannot cover, and
    drop what should never have reached a page.

    Control characters are stripped rather than substituted. They arrive from
    PDF extraction — a source chapter carried U+0002 and U+0012 through parsing,
    chunking and generation into the rendered artifact — and they are not
    content in any encoding.

    Newlines are kept, because the renderer's wrapping honours them. Tabs are
    not: no font here has a tab glyph, so fpdf2 dropped them and warned, and a
    tab that survives as nothing silently closes up the gap it was there to
    make. Two spaces keep the separation visible.
    """
    if not text:
        return text

    if "\t" in text:
        text = text.replace("\t", "  ")

    for symbol, replacement in _SUBSTITUTIONS.items():
        if symbol in text:
            text = text.replace(symbol, replacement)

    # Written as "vec(E)" rather than dropped, so the notation survives.
    if _COMBINING_VECTOR in text:
        text = re.sub(rf"(\w){_COMBINING_VECTOR}", r"vec(\1)", text)
        text = text.replace(_COMBINING_VECTOR, "")

    if any(ch < " " and ch not in "\n\t" for ch in text):
        text = "".join(ch for ch in text if ch >= " " or ch in "\n\t")

    return text


def register_fonts(pdf: FPDF) -> None:
    """Register both families on one document and wire the fallback chain.

    ``set_fallback_fonts`` is what makes mixed-script text (an English heading
    over a Hindi body paragraph, a transliterated term inline) work without
    every call site tracking which font a given string needs — fpdf2
    substitutes the fallback font per glyph the primary font cannot cover.
    """
    pdf.add_font(LATIN_FONT, "", str(_LATIN_FONT_FILE))
    pdf.add_font(DEVANAGARI_FONT, "", str(_DEVANAGARI_FONT_FILE))
    # The bold cuts are pre-instanced static files (scripts/build_bold_fonts.py),
    # so registering them costs an ordinary font load rather than the ~2.5 s per
    # family that instancing `variations={"wght": 700}` here would cost on every
    # render. Registered under the same family name, which is what lets a call
    # site ask for style "B" and get it in either script.
    pdf.add_font(LATIN_FONT, "B", str(_LATIN_BOLD_FILE))
    pdf.add_font(DEVANAGARI_FONT, "B", str(_DEVANAGARI_BOLD_FILE))
    pdf.set_fallback_fonts([DEVANAGARI_FONT])
