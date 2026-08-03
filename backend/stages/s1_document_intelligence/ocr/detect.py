"""Which pages carry no text layer, and turning those into images.

The question "is this page scanned?" has a precise answer that does not need a
model: a page with a text layer yields characters when you ask for them, and a
page that is a photograph of paper yields none. The subtlety is that real
textbook pages sit between the two — a full-page diagram with a two-word caption
is *not* scanned, and a scanned page carrying a stray header from a digital
watermark is.

So the test is text *density* against page area, not presence, with a second
signal: a page whose entire area is covered by one image and which yields almost
no characters is scanned regardless of what those few characters say.

This runs on every PDF, cheaply, before any OCR decision — because the uploader's
``document_kind`` hint (FAQ Q7) is advisory and frequently wrong in both
directions. Someone uploading a born-digital chapter may pick "Scanned PDF" to be
safe, and someone uploading a photocopied chapter usually picks "Mostly Text".
Measuring costs milliseconds and is right; trusting the hint is free and is not.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PageTextProfile", "profile_pdf", "rasterise"]

#: Characters per square inch below which a page has no usable text layer.
#:
#: Calibrated against real documents rather than assumed. Measured on the NCERT
#: Class 11 Physics chapter (44pp): median 26.8, minimum 7.4 — and that minimum
#: page holds 675 perfectly extractable characters of worked exercises. The
#: French Revolution article (39pp) runs median 38.7, minimum 14.0.
#:
#: So real pages bottom out near 7, and an earlier threshold of 12 flagged two
#: readable pages as scanned. A genuinely image-only page yields 0-2: the gap
#: between "sparse" and "absent" is an order of magnitude, and the threshold
#: belongs in the gap, not at the bottom of the normal range. Sending a readable
#: page to OCR is not a harmless false positive — it spends a metered call and
#: replaces good text with a recogniser's guess.
MIN_CHARS_PER_SQIN = 3.0

#: Absolute floor, for pages too small for a density test to mean much.
MIN_CHARS_PER_PAGE = 60

#: A page whose images cover this much of its area is picture-first.
#:
#: Used only to tell a *scanned* page from a *blank* one, never as evidence of
#: scanning on its own. Measured reason: every page of the NCERT chapter reports
#: an image share of 1.00, because the book carries a full-page decorative
#: border. Treating high image coverage as a positive signal would flag the
#: entire book.
IMAGE_AREA_SHARE = 0.55

#: Rasterisation resolution. 300 DPI is the floor most OCR engines are tuned
#: for; below it, recognition of subscripts and small type degrades sharply,
#: and subscripts are exactly what a physics chapter is full of.
RENDER_DPI = 300


@dataclass(frozen=True, slots=True)
class PageTextProfile:
    """What one page looks like to the detector."""

    page: int
    chars: int
    area_sqin: float
    image_area_share: float

    @property
    def chars_per_sqin(self) -> float:
        return self.chars / self.area_sqin if self.area_sqin > 0 else 0.0

    @property
    def is_scanned(self) -> bool:
        """No usable text layer, so the words are locked inside pixels.

        Deliberately conservative. A false negative costs one page of a chapter;
        a false positive spends a metered OCR call and overwrites correct text
        with a recogniser's guess, which is the worse failure and the harder one
        to notice afterwards.
        """
        if self.chars >= MIN_CHARS_PER_PAGE:
            return False
        if self.chars_per_sqin >= MIN_CHARS_PER_SQIN:
            return False
        # Near-empty and covered in ink: the content is there and unreadable.
        # Near-empty with no ink is a genuinely blank or divider page, and
        # running OCR on it would return nothing at a real cost.
        return self.image_area_share >= IMAGE_AREA_SHARE


def profile_pdf(payload: bytes) -> list[PageTextProfile]:
    """Measure every page's text density and image coverage.

    Returns an empty list when the PDF cannot be opened — detection is a
    routing hint, and failing to open the file is the parser's error to raise
    with its own message, not this module's to pre-empt.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - dependency is declared
        return []

    profiles: list[PageTextProfile] = []
    try:
        with pymupdf.open(stream=payload, filetype="pdf") as document:
            for index, page in enumerate(document, start=1):
                rect = page.rect
                area_sqin = max((rect.width / 72.0) * (rect.height / 72.0), 0.01)
                text = page.get_text("text") or ""

                covered = 0.0
                for block in page.get_text("dict").get("blocks", []):
                    # type 1 is an image block in PyMuPDF's block taxonomy.
                    if block.get("type") == 1:
                        x0, y0, x1, y1 = block.get("bbox", (0, 0, 0, 0))
                        covered += abs((x1 - x0) * (y1 - y0))

                page_area_pt = max(rect.width * rect.height, 1.0)
                profiles.append(
                    PageTextProfile(
                        page=index,
                        chars=len(text.strip()),
                        area_sqin=area_sqin,
                        image_area_share=min(covered / page_area_pt, 1.0),
                    )
                )
    except Exception:  # pragma: no cover - see docstring
        return []
    return profiles


def rasterise(payload: bytes, pages: list[int], *, dpi: int = RENDER_DPI) -> list:
    """Render the named 1-based pages to PNG for an engine that needs images.

    Remote engines that read a PDF directly should not call this — see
    ``PageImage`` — but every local engine needs pixels.
    """
    from stages.s1_document_intelligence.ocr.base import PageImage

    try:
        import pymupdf
    except ImportError:  # pragma: no cover - dependency is declared
        return []

    images: list[PageImage] = []
    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)

    with pymupdf.open(stream=payload, filetype="pdf") as document:
        for number in pages:
            if not 1 <= number <= document.page_count:
                continue
            pixmap = document[number - 1].get_pixmap(matrix=matrix)
            images.append(PageImage(page=number, png=pixmap.tobytes("png"), metadata={"dpi": dpi}))
    return images
