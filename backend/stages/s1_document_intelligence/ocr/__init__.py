"""OCR for pages whose words are locked inside pixels.

Swapping engines is a configuration change — ``OCR_ENGINE=tesseract`` — and
nothing downstream of :func:`recognise_scanned_pages` can tell which engine ran.
That is the whole point of the port: the recogniser is the least settled part of
this design (services improve, prices move, a self-hosted model may win later),
so it is the part held at arm's length.

The default is ``auto``: use the configured engine when it can start, and
otherwise degrade to no OCR with a message naming what is missing. Degrading is
right because OCR is a *recovery* path — a born-digital chapter never reaches it,
so an unavailable engine must not stop the ordinary case from working.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from stages.s1_document_intelligence.ocr.base import (
    OcrEngine,
    OcrPage,
    OcrResult,
    OcrUnavailableError,
    PageImage,
)
from stages.s1_document_intelligence.ocr.detect import (
    PageTextProfile,
    extract_pages,
    profile_pdf,
    rasterise,
)

if TYPE_CHECKING:
    from core.config import Settings

logger = logging.getLogger(__name__)

__all__ = [
    "OcrEngine",
    "OcrPage",
    "OcrResult",
    "OcrUnavailableError",
    "PageImage",
    "PageTextProfile",
    "build_engine",
    "extract_pages",
    "profile_pdf",
    "rasterise",
    "recognise_scanned_pages",
    "scanned_pages",
]

#: Engines that read a PDF directly rather than rasterised pages. Handing a
#: layout model images throws away the structure it is best at recovering.
_PDF_NATIVE = {"azure-document-intelligence"}


def build_engine(settings: Settings) -> OcrEngine | None:
    """Construct the configured engine, or ``None`` when OCR is off/unavailable.

    Never raises. An engine that cannot start is logged with its own message —
    which names the missing binary, package or key — and OCR is skipped.
    """
    choice = (getattr(settings, "ocr_engine", "auto") or "auto").strip().lower()
    if choice in {"none", "off", "disabled"}:
        return None

    from stages.s1_document_intelligence.ocr.engines import (
        AzureDocumentIntelligenceEngine,
        EasyOcrEngine,
        TesseractEngine,
    )

    def azure() -> OcrEngine:
        return AzureDocumentIntelligenceEngine(
            endpoint=getattr(settings, "azure_doc_intel_endpoint", None),
            key=getattr(settings, "azure_doc_intel_key", None),
        )

    builders = {
        "azure": azure,
        "azure-document-intelligence": azure,
        "tesseract": TesseractEngine,
        "easyocr": EasyOcrEngine,
    }

    # `auto` prefers the hosted reader — it is the only one that needs no local
    # install — then falls back through the local engines.
    order = ["azure", "tesseract", "easyocr"] if choice == "auto" else [choice]

    for name in order:
        builder = builders.get(name)
        if builder is None:
            logger.warning("unknown OCR engine %r; OCR disabled", name)
            return None
        try:
            engine = builder()
        except OcrUnavailableError as exc:
            # Explicitly chosen and unavailable is worth a louder line than one
            # candidate in the auto chain failing.
            log = logger.warning if choice != "auto" else logger.info
            log("OCR engine %r unavailable: %s", name, exc)
            continue
        logger.info("OCR engine ready: %s", engine.name)
        return engine

    return None


def scanned_pages(profiles: list[PageTextProfile], *, char_floor: int | None = None) -> list[int]:
    """Pages with no usable text layer.

    ``char_floor`` overrides the default per-page character floor, which is how
    the uploader's declared document kind (FAQ Q7) reaches this decision without
    being allowed to make it outright. See :meth:`PageTextProfile.is_scanned_at`
    for why the floor rather than the density line is the control worth exposing.
    """
    return [p.page for p in profiles if p.is_scanned_at(char_floor)]


def recognise_scanned_pages(
    payload: bytes,
    pages: list[int],
    engine: OcrEngine,
) -> OcrResult:
    """Run ``engine`` over the named pages. Synchronous; call it off the loop."""
    if not pages:
        return OcrResult(engine=engine.name)

    if engine.name in _PDF_NATIVE:
        # Only the pages that need reading. See extract_pages: hosted readers
        # bill per page and cap request size, and re-sending pages that already
        # parsed cleanly would let a guess overwrite exact text.
        trimmed = extract_pages(payload, pages)
        if not trimmed:
            return OcrResult(engine=engine.name, failed_pages=tuple(pages))
        images = [PageImage(page=number, pdf=trimmed) for number in pages]
    else:
        images = rasterise(payload, pages)
        if not images:
            return OcrResult(engine=engine.name, failed_pages=tuple(pages))

    return engine.recognise(images)
