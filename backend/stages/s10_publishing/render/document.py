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

from stages.s10_publishing.render.fonts import LATIN_FONT, register_fonts, typeset

__all__ = ["TkpDocument"]

_INK = (28, 30, 34)
_MUTED = (110, 114, 120)
_RULE = (206, 210, 216)

#: One accent, used only on structural furniture — section rules, the eyebrow
#: label above an h1, the cover band. Never on body text: a teacher photocopies
#: these, and colour that carries meaning is lost the moment the page is
#: greyscale. It is decoration that survives being thrown away.
_ACCENT = (23, 78, 140)

#: Tint behind callouts and table headers. Light enough to photocopy cleanly.
_TINT = (238, 242, 247)


class TkpDocument(FPDF):
    """A4 document with the fonts, margins, and section helpers every artifact shares."""

    def __init__(self, *, title: str, subtitle: str = "") -> None:
        super().__init__(format="A4", unit="mm")
        # Set before the first add_page: footer() runs on every page and reads it.
        self._running_title = title
        # True until the first section claims the masthead page. See new_section_page.
        self._section_pending = True
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(20, 16, 20)
        register_fonts(self)
        self.set_font(LATIN_FONT, size=10.5)
        self.set_title(title)
        self.alias_nb_pages()
        self.add_page()
        self._cover(title, subtitle)

    # ------------------------------------------------------- text plumbing ---

    # Both text primitives are wrapped rather than each helper below calling
    # `typeset` itself, because `FPDF.table` writes its cells through these too.
    # Substituting in the helpers would leave every table — the lesson plan's
    # timing grid, the assessment blueprint — still dropping its maths symbols.

    def cell(self, *args, **kwargs):  # type: ignore[override]
        if len(args) >= 3 and isinstance(args[2], str):
            args = (*args[:2], typeset(args[2]), *args[3:])
        elif isinstance(kwargs.get("text"), str):
            kwargs["text"] = typeset(kwargs["text"])
        return super().cell(*args, **kwargs)

    def multi_cell(self, *args, **kwargs):  # type: ignore[override]
        if len(args) >= 3 and isinstance(args[2], str):
            args = (*args[:2], typeset(args[2]), *args[3:])
        elif isinstance(kwargs.get("text"), str):
            kwargs["text"] = typeset(kwargs["text"])
        # fpdf2 justifies by default. On a single-column A4 measure at 10.5pt
        # that stretches word spacing into visible rivers running down the page
        # — the strongest reason the rendered guide read as text poured into a
        # file rather than a typeset document. Ragged right is the correct
        # default for this measure; a caller that wants centring still asks.
        kwargs.setdefault("align", "L")
        return super().multi_cell(*args, **kwargs)

    # ------------------------------------------------------------- chrome ---

    def _cover(self, title: str, subtitle: str) -> None:
        """A masthead, not a title page.

        A full cover page would cost a sheet of paper per artifact for one line
        of text, and these get printed per class. So the document identifies
        itself in a band at the top of page 1 and then gets on with it.
        """
        self.set_fill_color(*_ACCENT)
        self.rect(0, 0, self.w, 3.5, style="F")
        self.ln(4)

        self.set_font(LATIN_FONT, "B", size=21)
        self.multi_cell(0, 10, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if subtitle:
            self.set_font(LATIN_FONT, size=11)
            self.set_text_color(*_MUTED)
            self.multi_cell(0, 6, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(*_INK)
        self.ln(3)
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(6)

    def footer(self) -> None:
        """A hairline, the document's name, and the page number.

        The document name repeats on every page because these get printed,
        stapled per class and then separated — a loose sheet that does not say
        which of the three artifacts it came from is a sheet a teacher has to
        read to identify.
        """
        self.set_y(-15)
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-12)
        self.set_font(LATIN_FONT, size=7.5)
        self.set_text_color(*_MUTED)
        self.cell(self.epw / 2, 8, self._running_title[:70])
        self.cell(self.epw / 2, 8, f"Page {self.page_no()} / {{nb}}", align="R")
        self.set_text_color(*_INK)

    def new_section_page(self) -> None:
        """Start a section on a fresh page — except when this page is still fresh.

        The teacher guide calls this before every period, so the first call
        landed immediately after the masthead and pushed Period 1 to page 2,
        leaving page 1 as a title and two-thirds of a blank sheet. A teacher
        printing six periods per class was printing that sheet every time.

        The masthead page is a fine home for the first section, so the first
        call is absorbed and every later one breaks as asked.
        """
        if self._section_pending:
            self._section_pending = False
            return
        self.add_page()

    # ------------------------------------------------------------ headings ---

    def h1(self, text: str, *, eyebrow: str = "") -> None:
        """A major section. Starts clear of what came before and is set in bold.

        Weight is the point. Every heading here used to differ from body copy by
        size alone — 15pt against 10.5pt — and a reader skimming for structure
        sees a slightly larger line of the same grey, not a heading. Bold plus a
        rule in the accent colour is what makes the section boundary legible at
        arm's length, which is how a teacher actually uses this mid-lesson.
        """
        # Never strand a heading at the foot of a page: if there is not room for
        # the heading and a couple of lines under it, start the next page.
        if self.get_y() > self.h - self.b_margin - 32:
            self.add_page()
        self.ln(3)
        if eyebrow:
            self.set_font(LATIN_FONT, "B", size=7.5)
            self.set_text_color(*_ACCENT)
            self.multi_cell(0, 4, eyebrow.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(*_INK)
            self.ln(0.5)
        self.set_font(LATIN_FONT, "B", size=15)
        self.multi_cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)
        self.set_draw_color(*_ACCENT)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(4)
        self.set_font(LATIN_FONT, size=10.5)

    def h2(self, text: str) -> None:
        if self.get_y() > self.h - self.b_margin - 26:
            self.add_page()
        self.ln(3)
        self.set_font(LATIN_FONT, "B", size=12)
        self.multi_cell(0, 6.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y() + 0.5, self.w - self.r_margin, self.get_y() + 0.5)
        self.ln(3)
        self.set_font(LATIN_FONT, size=10.5)

    def h3(self, text: str) -> None:
        """The smallest heading — bold at body size, so it leads a paragraph
        without competing with the h2 above it."""
        self.ln(1.5)
        self.set_font(LATIN_FONT, "B", size=10.5)
        self.multi_cell(0, 5.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(LATIN_FONT, size=10.5)

    def banner(self, text: str) -> None:
        """A filled callout bar. Used for the answer-key warning."""
        self.set_fill_color(*_TINT)
        self.set_font(LATIN_FONT, "B", size=10.5)
        self.multi_cell(0, 8, text, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(LATIN_FONT, size=10.5)
        self.ln(2)

    def callout(self, label: str, text: str) -> None:
        """A tinted block with an accent edge, for something set apart from the
        run of the page — a misconception to watch for, a safety note.

        Drawn as a rule plus a fill rather than a bordered box because fpdf2
        cannot know the wrapped height until after it writes, and a box drawn
        first at a guessed height is the classic way these documents end up with
        text spilling out of their own frames.
        """
        top = self.get_y()
        self.set_fill_color(*_TINT)
        self.set_x(self.l_margin + 3)
        self.set_font(LATIN_FONT, "B", size=8)
        self.set_text_color(*_ACCENT)
        self.multi_cell(
            self.epw - 3, 5, label.upper(), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        self.set_text_color(*_INK)
        self.set_font(LATIN_FONT, size=10)
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.epw - 3, 5.4, text, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_draw_color(*_ACCENT)
        self.set_line_width(1.0)
        self.line(self.l_margin, top, self.l_margin, self.get_y())
        self.set_line_width(0.2)
        self.set_font(LATIN_FONT, size=10.5)
        self.ln(3)

    # --------------------------------------------------------------- body ---

    def body(self, text: str, *, size: float = 10.5) -> None:
        self.set_font(LATIN_FONT, size=size)
        self.multi_cell(0, 5.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def muted(self, text: str, *, size: float = 9) -> None:
        self.set_text_color(*_MUTED)
        self.body(text, size=size)
        self.set_text_color(*_INK)

    def bullet(self, text: str, *, indent: float = 5.0) -> None:
        """A bullet whose continuation lines align under the text, not the dot.

        The old version put the marker inside the wrapped string, so a two-line
        bullet ran its second line back under the bullet character and the list
        lost its left edge — the single biggest reason these pages read as a
        wall of text rather than a list.
        """
        self.set_font(LATIN_FONT, size=10.5)
        top = self.get_y()
        self.set_x(self.l_margin + indent)
        self.cell(3.5, 5.6, "•")
        self.set_xy(self.l_margin + indent + 3.5, top)
        self.multi_cell(
            self.epw - indent - 3.5, 5.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    def key_value(self, label: str, value: str) -> None:
        """Label in bold on the left, value on the right, wrapping under itself."""
        label_width = 42.0
        y = self.get_y()
        self.set_font(LATIN_FONT, "B", size=9.5)
        self.set_text_color(*_MUTED)
        self.multi_cell(
            label_width, 5.6, label, new_x=XPos.RIGHT, new_y=YPos.TOP, max_line_height=5.6
        )
        self.set_text_color(*_INK)
        self.set_font(LATIN_FONT, size=10.5)
        self.set_xy(self.l_margin + label_width, y)
        self.multi_cell(
            self.epw - label_width, 5.6, value or "—", new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    def write(self, *args, **kwargs):  # type: ignore[override]
        if len(args) >= 2 and isinstance(args[1], str):
            args = (args[0], typeset(args[1]), *args[2:])
        elif isinstance(kwargs.get("text"), str):
            kwargs["text"] = typeset(kwargs["text"])
        return super().write(*args, **kwargs)

    def labelled(self, label: str, text: str) -> None:
        """A bold label running inline into regular body text.

        For numbered items — "Q3. (4 marks)" followed by the question. Sending
        the whole thing through a heading helper sets the entire stem bold, and
        a page of bold body text is harder to read than no bold at all: emphasis
        that covers everything emphasises nothing.

        ``write`` rather than ``cell`` + ``multi_cell`` because it flows: the
        stem wraps to the next line normally instead of being boxed beside a
        label of guessed width.
        """
        self.set_font(LATIN_FONT, "B", size=10.5)
        self.write(5.6, label)
        self.set_font(LATIN_FONT, size=10.5)
        if text:
            self.write(5.6, f" {text}")
        self.ln(5.6)

    def spacer(self, height: float = 3.0) -> None:
        self.ln(height)

    def rule(self) -> None:
        self.set_draw_color(*_RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def table_style(self) -> FontFace:
        """Header-row style for ``FPDF.table`` calls: bold on a tint.

        Both signals, not one. A tint alone survives greyscale printing but
        disappears if the page is photocopied light; weight survives either.
        """
        return FontFace(family=LATIN_FONT, emphasis="BOLD", fill_color=_TINT)

    def bytes(self) -> bytes:
        return bytes(self.output())
