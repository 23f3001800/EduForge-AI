"""Concrete OCR engines, one class each, all behind :class:`OcrEngine`.

Three are implemented because the port is only worth having if more than one
thing plugs into it — an abstraction with a single implementation is a guess
about the future, not a boundary. Each is constructed lazily and raises
:class:`OcrUnavailableError` naming exactly what is missing, so a misconfigured
engine is a clear message at startup rather than a stack trace mid-document.

Notes on the trade-offs, because the choice is an operator's to make:

* **Azure Document Intelligence** reads the PDF directly and does its own layout
  analysis, so tables and multi-column pages survive — which matters here, since
  FAQ Q7 says the benchmark inputs carry tables, maps and equations. It reports
  per-word confidence. It costs a network round trip and an API key.
* **Tesseract** is free and offline and needs a system binary. It is weakest on
  exactly the material this product sees most: two-column layouts and anything
  mathematical.
* **EasyOCR** is pip-only, so it respects a venv-only constraint, but drags in
  PyTorch and is slow without a GPU.
"""

from __future__ import annotations

import logging

from stages.s1_document_intelligence.ocr.base import (
    OcrEngine,
    OcrPage,
    OcrResult,
    OcrUnavailableError,
    PageImage,
)

logger = logging.getLogger(__name__)

__all__ = ["AzureDocumentIntelligenceEngine", "EasyOcrEngine", "TesseractEngine"]


class AzureDocumentIntelligenceEngine(OcrEngine):
    """Azure Document Intelligence — reads the PDF, returns text and confidence."""

    name = "azure-document-intelligence"

    def __init__(self, endpoint: str | None, key: str | None, *, model: str = "prebuilt-read"):
        if not endpoint or not key:
            raise OcrUnavailableError(
                "Azure Document Intelligence needs AZURE_DOC_INTEL_ENDPOINT and "
                "AZURE_DOC_INTEL_KEY. Create the resource with: az cognitiveservices "
                "account create --kind FormRecognizer --sku F0 ..."
            )
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise OcrUnavailableError(
                "azure-ai-documentintelligence is not installed: pip install "
                "azure-ai-documentintelligence"
            ) from exc

        self._model = model
        self._client = DocumentIntelligenceClient(
            endpoint=endpoint, credential=AzureKeyCredential(key)
        )

    def recognise(self, images: list[PageImage]) -> OcrResult:
        """One call for the whole document — the service paginates internally.

        Sending the PDF rather than the rasterised pages is deliberate: this
        service is a layout model, and handing it images of pages discards the
        vector text and structure it uses to get tables right.
        """
        pdf = next((image.pdf for image in images if image.pdf), b"")
        wanted = [image.page for image in images]
        if not pdf:
            return OcrResult(engine=self.name, failed_pages=tuple(wanted))

        try:
            poller = self._client.begin_analyze_document(
                self._model, body=pdf, content_type="application/pdf"
            )
            analysis = poller.result()
        except Exception as exc:
            logger.warning("azure document intelligence failed: %s", exc, exc_info=True)
            return OcrResult(engine=self.name, failed_pages=tuple(wanted))

        keep = set(wanted)
        pages: list[OcrPage] = []
        for page in analysis.pages or []:
            number = int(getattr(page, "page_number", 0) or 0)
            if number not in keep:
                continue

            words = list(getattr(page, "words", None) or [])
            text = " ".join(str(getattr(w, "content", "")) for w in words).strip()
            scores = [
                float(w.confidence) for w in words if getattr(w, "confidence", None) is not None
            ]
            pages.append(
                OcrPage(
                    page=number,
                    text=text,
                    confidence=(sum(scores) / len(scores)) if scores else None,
                )
            )

        recovered = {page.page for page in pages}
        return OcrResult(
            engine=self.name,
            pages=tuple(sorted(pages, key=lambda p: p.page)),
            failed_pages=tuple(sorted(keep - recovered)),
        )

    def close(self) -> None:
        self._client.close()


class TesseractEngine(OcrEngine):
    """Local Tesseract. Free and offline; needs the system binary."""

    name = "tesseract"

    def __init__(self, *, language: str = "eng"):
        try:
            import pytesseract
        except ImportError as exc:
            raise OcrUnavailableError(
                "pytesseract is not installed: pip install pytesseract"
            ) from exc
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise OcrUnavailableError(
                "the tesseract binary is not on PATH: apt install tesseract-ocr"
            ) from exc
        self._language = language

    def recognise(self, images: list[PageImage]) -> OcrResult:
        import io

        import pytesseract
        from PIL import Image

        pages: list[OcrPage] = []
        failed: list[int] = []

        for image in images:
            if not image.png:
                failed.append(image.page)
                continue
            try:
                with Image.open(io.BytesIO(image.png)) as handle:
                    data = pytesseract.image_to_data(
                        handle,
                        lang=self._language,
                        output_type=pytesseract.Output.DICT,
                    )
            except Exception as exc:
                logger.warning("tesseract failed on page %d: %s", image.page, exc)
                failed.append(image.page)
                continue

            words, scores = [], []
            for text, raw in zip(data.get("text", []), data.get("conf", []), strict=False):
                if not str(text).strip():
                    continue
                words.append(str(text))
                # Tesseract reports -1 where it declines to score a token.
                score = float(raw)
                if score >= 0:
                    scores.append(score / 100.0)

            pages.append(
                OcrPage(
                    page=image.page,
                    text=" ".join(words).strip(),
                    confidence=(sum(scores) / len(scores)) if scores else None,
                )
            )

        return OcrResult(engine=self.name, pages=tuple(pages), failed_pages=tuple(failed))


class EasyOcrEngine(OcrEngine):
    """EasyOCR. Pip-only, but pulls PyTorch and is slow without a GPU."""

    name = "easyocr"

    def __init__(self, *, languages: tuple[str, ...] = ("en",)):
        try:
            import easyocr
        except ImportError as exc:
            raise OcrUnavailableError(
                "easyocr is not installed: pip install easyocr (pulls PyTorch, ~2GB)"
            ) from exc
        self._reader = easyocr.Reader(list(languages), verbose=False)

    def recognise(self, images: list[PageImage]) -> OcrResult:
        pages: list[OcrPage] = []
        failed: list[int] = []

        for image in images:
            if not image.png:
                failed.append(image.page)
                continue
            try:
                found = self._reader.readtext(image.png)
            except Exception as exc:
                logger.warning("easyocr failed on page %d: %s", image.page, exc)
                failed.append(image.page)
                continue

            words = [str(text) for _, text, _ in found]
            scores = [float(score) for _, _, score in found]
            pages.append(
                OcrPage(
                    page=image.page,
                    text=" ".join(words).strip(),
                    confidence=(sum(scores) / len(scores)) if scores else None,
                )
            )

        return OcrResult(engine=self.name, pages=tuple(pages), failed_pages=tuple(failed))
