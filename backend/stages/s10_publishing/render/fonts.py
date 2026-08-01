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

from pathlib import Path

from fpdf import FPDF

__all__ = ["DEVANAGARI_FONT", "LATIN_FONT", "has_devanagari", "register_fonts"]

FONT_DIR = Path(__file__).parent / "fonts"

LATIN_FONT = "NotoSans"
DEVANAGARI_FONT = "NotoSansDevanagari"

_LATIN_FONT_FILE = FONT_DIR / "NotoSans[wdth,wght].ttf"
_DEVANAGARI_FONT_FILE = FONT_DIR / "NotoSansDevanagari[wdth,wght].ttf"

#: Unicode block U+0900-U+097F (Devanagari). This is the one non-Latin script
#: the pipeline ships a dedicated font for; text in a third script still
#: renders — fpdf2 embeds NotoSans' own cmap for whatever it covers — just
#: without the fallback guarantee this module gives Devanagari specifically.
_DEVANAGARI_START, _DEVANAGARI_END = 0x0900, 0x097F


def has_devanagari(text: str) -> bool:
    """True if ``text`` contains at least one Devanagari codepoint."""
    return any(_DEVANAGARI_START <= ord(ch) <= _DEVANAGARI_END for ch in text)


def register_fonts(pdf: FPDF) -> None:
    """Register both families on one document and wire the fallback chain.

    ``set_fallback_fonts`` is what makes mixed-script text (an English heading
    over a Hindi body paragraph, a transliterated term inline) work without
    every call site tracking which font a given string needs — fpdf2
    substitutes the fallback font per glyph the primary font cannot cover.
    """
    pdf.add_font(LATIN_FONT, "", str(_LATIN_FONT_FILE))
    pdf.add_font(DEVANAGARI_FONT, "", str(_DEVANAGARI_FONT_FILE))
    pdf.set_fallback_fonts([DEVANAGARI_FONT])
