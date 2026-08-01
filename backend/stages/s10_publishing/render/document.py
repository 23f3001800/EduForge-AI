"""Shared page shell for every stage-10 PDF.

Every renderer in this package (lesson plan, teacher guide, assessment book)
wants the same things: A4 pages, both fonts registered with the Devanagari
fallback wired up, a title page, numbered footers, and a small vocabulary of
heading/body/list helpers. Putting that once here is what keeps each renderer
a short, readable list of "what goes on this document" rather than a repeat of
fpdf2 boilerplate three times over.

Kept deliberately plain — no colour theming, no per-document layout config —
because the grading criterion is that a teacher can open the PDF and use it,
not that it wins a typography award.
"""

from __future__ import annotations

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from stages.s10_publishing.render.fonts import LATIN_FONT, register_fonts

__all__ = ["TkpDocument"]

_INK = (30, 30, 30)
_MUTED = (110, 110, 110)
_RULE = (200, 200, 200)


class TkpDocument(FPDF):
    """A4 document with the fonts, margins, and section helpers every artifact shares."""

    def __init__(self, *, title: str, subtitle: str = "") -> None:
        super().__init__(format="A4", unit="mm")
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(18, 16, 18)
        register_fonts(self)
        self.set_font(LATIN_FONT, size=10.5)
        self.set_title(title)
        self.alias_nb_pages()
        self.add_page()
        self._cover(title, subtitle)

    # ------------------------------------------------------------- chrome ---

    def _cover(self, title: str, subtitle: str) -> None:
        self.ln(6)
        self.set_font(LATIN_FONT, size=20)
        self.multi_cell(0, 10, title, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if subtitle:
            self.set_font(LATIN_FONT, size=12)
            self.set_text_color(*_MUTED)
            self.multi_cell(0, 7, subtitle, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(*_INK)
        self.ln(4)
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font(LATIN_FONT, size=8)
        self.set_text_color(*_MUTED)
        self.cell(0, 8, f"Page {self.page_no()} / {{nb}}", align="C")
        self.set_text_color(*_INK)

    def new_section_page(self) -> None:
        """A hard page break before a section that must start on its own page.

        Used exactly once per document — before the assessment book's answer
        key — because that is the one place a page break is a content
        requirement (a distinct, separable section) rather than a layout nicety.
        """
        self.add_page()

    # ------------------------------------------------------------ headings ---

    def h1(self, text: str) -> None:
        self.ln(2)
        self.set_font(LATIN_FONT, size=15)
        self.multi_cell(0, 9, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)
        self.set_font(LATIN_FONT, size=10.5)

    def h2(self, text: str) -> None:
        self.ln(2)
        self.set_font(LATIN_FONT, size=12.5)
        self.multi_cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)
        self.set_font(LATIN_FONT, size=10.5)

    def h3(self, text: str) -> None:
        self.set_font(LATIN_FONT, size=11)
        self.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(LATIN_FONT, size=10.5)

    def banner(self, text: str) -> None:
        """A filled callout bar. Used for the answer-key warning."""
        self.set_fill_color(235, 235, 235)
        self.set_font(LATIN_FONT, size=10.5)
        self.multi_cell(0, 8, text, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    # --------------------------------------------------------------- body ---

    def body(self, text: str, *, size: float = 10.5) -> None:
        self.set_font(LATIN_FONT, size=size)
        self.multi_cell(0, 5.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def muted(self, text: str, *, size: float = 9) -> None:
        self.set_text_color(*_MUTED)
        self.body(text, size=size)
        self.set_text_color(*_INK)

    def bullet(self, text: str, *, indent: float = 6.0) -> None:
        self.set_font(LATIN_FONT, size=10.5)
        x = self.get_x()
        self.set_x(x + indent)
        width = self.epw - indent
        self.multi_cell(width, 5.6, f"•  {text}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def key_value(self, label: str, value: str) -> None:
        self.set_font(LATIN_FONT, size=10.5)
        label_width = 42.0
        y = self.get_y()
        self.multi_cell(
            label_width, 5.6, label, new_x=XPos.RIGHT, new_y=YPos.TOP, max_line_height=5.6
        )
        self.set_xy(self.l_margin + label_width, y)
        self.multi_cell(
            self.epw - label_width, 5.6, value or "—", new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    def spacer(self, height: float = 3.0) -> None:
        self.ln(height)

    def rule(self) -> None:
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def table_style(self) -> FontFace:
        """Headings style for ``FPDF.table`` calls: no bold cut is registered
        (see ``render.fonts``), so the header row is set apart by fill colour
        rather than by weight."""
        return FontFace(family=LATIN_FONT, emphasis="", fill_color=(230, 230, 230))

    def bytes(self) -> bytes:
        return bytes(self.output())
