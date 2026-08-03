"""OCR: does it fire only when it should, and does it tell the truth after?

FAQ Q7 names "Scanned PDF" as an input kind, so a page whose words are pixels
has to be readable. But OCR is the one step whose output can be *confidently
wrong* — every later stage checks its claims against the source text, and if OCR
misread the source those checks validate the error instead of catching it.

That makes a false positive worse than a false negative. Missing a scanned page
costs one page; running OCR on a page that parsed cleanly spends a metered call
and overwrites exact text with a recogniser's guess, which nothing downstream
can detect. So the detector is tested hardest in the direction of *not* firing.

No network: the engine is a stub. The live Azure path is exercised by the
capture script, not by the suite.
"""

from __future__ import annotations

import pytest

from stages.s1_document_intelligence.ocr import (
    OcrEngine,
    OcrPage,
    OcrResult,
    build_engine,
    scanned_pages,
)
from stages.s1_document_intelligence.ocr.detect import (
    MIN_CHARS_PER_PAGE,
    PageTextProfile,
)
from stages.s1_document_intelligence.stage import _char_floor_for

A4_SQIN = 8.27 * 11.69

#: The declared kinds that must route differently, weakest signal to strongest.
KINDS = ("mostly_text", "unknown", "scanned_pdf")


def _page(chars: int, *, image_share: float = 1.0, page: int = 1) -> PageTextProfile:
    return PageTextProfile(page=page, chars=chars, area_sqin=A4_SQIN, image_area_share=image_share)


# ────────────────────────────────────────── the detector must not over-fire


@pytest.mark.parametrize(
    ("chars", "why"),
    [
        (2804, "a dense prose page"),
        (1003, "a worked-example page with figures — measured on NCERT p10"),
        (675, "the sparsest real page in the NCERT chapter — p44, exercises"),
        (MIN_CHARS_PER_PAGE, "exactly at the floor"),
    ],
)
def test_a_page_with_real_text_is_never_sent_to_ocr(chars: int, why: str) -> None:
    """Every one of these has extractable text; OCR would overwrite it.

    The character counts are measured from the real NCERT Class 11 Physics
    chapter, not invented. An earlier threshold of 12 chars/sq-in flagged the
    675- and 1003-character pages as scanned — both are perfectly readable.
    """
    assert _page(chars).is_scanned is False, why


def test_the_declared_document_kind_changes_a_marginal_decision() -> None:
    """FAQ Q7's hint has to actually route something, or it is decoration.

    Guards a real defect. The hint was first wired to bias the chars-per-sq-in
    density line, which reads like a control and is not one: the character floor
    returns first, and a page under the floor is already far below every density
    threshold on any ordinary page size. Every declared kind produced identical
    routing. The assertion below — three kinds, three different answers for the
    *same* page — is what failed then and what would fail again.
    """
    stray_header_only = _page(45)
    answers = {kind: stray_header_only.is_scanned_at(_char_floor_for(kind)) for kind in KINDS}

    assert answers == {"mostly_text": False, "unknown": True, "scanned_pdf": True}
    assert len({_char_floor_for(k) for k in KINDS}) == len(KINDS), (
        "each declared kind must map to a distinct floor, or the hint is inert"
    )


@pytest.mark.parametrize(
    ("chars", "image_share", "why"),
    [
        (675, 1.0, "a sparse but genuinely readable page"),
        (2804, 1.0, "a dense prose page"),
        (0, 0.0, "a blank divider carrying no ink"),
    ],
)
def test_a_declared_kind_cannot_overturn_a_clear_reading(
    chars: int, image_share: float, why: str
) -> None:
    """The hint breaks ties. It does not get a vote on unambiguous pages.

    An uploader who picks "Scanned PDF" for a born-digital chapter — the common
    mistake, since it sounds like the safe answer — must not thereby send 44
    readable pages to a metered recogniser that would replace exact text with a
    guess.
    """
    page = _page(chars, image_share=image_share)
    verdicts = {page.is_scanned_at(_char_floor_for(kind)) for kind in KINDS}
    assert len(verdicts) == 1, f"declared kind changed the answer for {why}"
    assert verdicts == {page.is_scanned}, "the tie-breaker moved an undisputed page"


def test_image_coverage_alone_never_means_scanned() -> None:
    """Measured reason: *every* page of the NCERT chapter reports an image share
    of 1.00, because the book carries a full-page decorative border. Treating
    coverage as positive evidence would send the entire book to OCR."""
    assert _page(2804, image_share=1.0).is_scanned is False


def test_a_page_with_no_text_layer_is_caught() -> None:
    assert _page(0).is_scanned is True


def test_a_blank_page_is_not_sent_to_ocr() -> None:
    """No text and no ink is a divider or a blank, not a scan. Reading it costs
    a metered call and returns nothing."""
    assert _page(0, image_share=0.0).is_scanned is False


def test_stray_artefacts_do_not_rescue_a_scanned_page() -> None:
    """A scan often yields a few characters from a header or watermark. Those
    are not a text layer."""
    assert _page(9).is_scanned is True


def test_scanned_pages_reports_page_numbers_in_order() -> None:
    profiles = [_page(3000, page=1), _page(0, page=2), _page(0, page=3)]
    assert scanned_pages(profiles) == [2, 3]


# ─────────────────────────────────────────────── confidence must stay honest


def test_confidence_is_none_when_no_engine_reported_one() -> None:
    """``None`` is not zero. An engine that does not score its output must not
    be given a flattering default — the same rule the evaluation framework
    applies to metrics it cannot measure."""
    result = OcrResult(engine="stub", pages=(OcrPage(page=1, text="hello"),))
    assert result.confidence is None


def test_confidence_is_weighted_by_how_much_text_each_page_carried() -> None:
    """A four-word page and a four-hundred-word page are not equally strong
    evidence that recognition went well. A flat mean lets a near-empty page with
    an incidentally high score mask a long unreadable one."""
    result = OcrResult(
        engine="stub",
        pages=(
            OcrPage(page=1, text="x" * 900, confidence=0.60),
            OcrPage(page=2, text="y" * 100, confidence=1.00),
        ),
    )
    assert result.confidence == pytest.approx(0.64)  # not the flat mean of 0.80


def test_pages_the_engine_could_not_read_are_reported_not_hidden() -> None:
    """The Azure free tier silently returns only the first two pages. Recording
    the rest as failed is what stops a partial read looking like a whole one."""
    result = OcrResult(
        engine="stub",
        pages=(OcrPage(page=1, text="a", confidence=0.9),),
        failed_pages=(2, 3),
    )
    assert result.failed_pages == (2, 3)
    assert result.text == "a"


# ───────────────────────────────────────────────────── engine selection


def test_ocr_can_be_switched_off_by_configuration() -> None:
    class _Settings:
        ocr_engine = "none"

    assert build_engine(_Settings()) is None


def test_an_unavailable_engine_degrades_rather_than_raising() -> None:
    """OCR is a recovery path. A born-digital chapter never reaches it, so a
    missing key must not stop the ordinary case from working."""

    class _Settings:
        ocr_engine = "azure"
        azure_doc_intel_endpoint = None
        azure_doc_intel_key = None

    assert build_engine(_Settings()) is None


def test_an_unknown_engine_name_disables_ocr_rather_than_guessing() -> None:
    class _Settings:
        ocr_engine = "not-a-real-engine"

    assert build_engine(_Settings()) is None


def test_every_engine_answers_the_same_shape() -> None:
    """The port is only worth having if a caller cannot tell which engine ran."""

    class _Stub(OcrEngine):
        name = "stub"

        def recognise(self, images: list) -> OcrResult:
            return OcrResult(
                engine=self.name,
                pages=tuple(OcrPage(page=i.page, text="t", confidence=0.5) for i in images),
            )

    from stages.s1_document_intelligence.ocr.base import PageImage

    result = _Stub().recognise([PageImage(page=1), PageImage(page=2)])
    assert [p.page for p in result.pages] == [1, 2]
    assert result.confidence == pytest.approx(0.5)
