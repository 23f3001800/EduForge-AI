"""The OCR port: what an engine must do, and what it must report.

FAQ Q7 names "Scanned PDF" as a document kind an uploader can declare, and says
NCERT chapters routinely carry images, diagrams, figures, tables, maps and
equations. A pipeline that rejects image-only pages therefore fails a stated
requirement, not merely a nice-to-have.

Two decisions shape this module.

**The engine is a port, not a library call.** Tesseract, EasyOCR, Azure
Document Intelligence and Google Document AI differ in where they run (local
binary, local model, remote API), what they cost, and what they are good at —
but they answer the same question: *given this page image, what text is on it,
and how sure are you?* Everything downstream depends only on that answer, so an
engine can be swapped without touching chunking, extraction, or any stage.

**Confidence is part of the contract, not an afterthought.** OCR is the only
step in this pipeline whose output can be confidently wrong: it returns
plausible words for an unreadable page and nothing marks them as guesses.
Every other stage grounds its claims in evidence spans that can be checked
against the source; an OCR error corrupts the source itself, so every check
downstream inherits the error and none can detect it. An engine that cannot
report a confidence must say so (``confidence=None``) rather than return a
flattering default — the same rule the evaluation framework applies to metrics
it cannot measure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = ["OcrEngine", "OcrPage", "OcrResult", "OcrUnavailableError"]


class OcrUnavailableError(RuntimeError):
    """The engine cannot run here — missing binary, package, key, or quota.

    Raised at *construction* wherever possible, so an unusable engine is
    detected when the roster is built rather than half-way through a document.
    The message must name the specific thing to install or set: "OCR failed" is
    not an error a reader can act on.
    """


@dataclass(frozen=True, slots=True)
class OcrPage:
    """One recognised page."""

    page: int
    text: str
    #: Mean per-word confidence in ``[0, 1]``, or ``None`` when the engine does
    #: not report one. ``None`` is not zero: it means "unknown", and the
    #: aggregate below propagates that distinction rather than averaging a
    #: guess into a number that looks measured.
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Everything one OCR pass produced, plus how much to trust it."""

    engine: str
    pages: tuple[OcrPage, ...] = ()
    #: Pages the engine was asked for but could not read at all.
    failed_pages: tuple[int, ...] = ()

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def confidence(self) -> float | None:
        """Character-weighted mean confidence, or ``None`` if nothing reported one.

        Weighted by text length rather than a flat mean over pages: a page with
        four words and a page with four hundred are not equally strong evidence
        that the recognition went well, and a flat mean lets a near-empty page
        with an incidentally high score mask a long unreadable one.
        """
        scored = [(p, len(p.text)) for p in self.pages if p.confidence is not None]
        weight = sum(chars for _, chars in scored)
        if not scored or weight == 0:
            return None
        return sum((p.confidence or 0.0) * chars for p, chars in scored) / weight

    @property
    def pages_without_confidence(self) -> int:
        return sum(1 for page in self.pages if page.confidence is None)


@dataclass(frozen=True, slots=True)
class PageImage:
    """A rasterised page handed to an engine.

    Carries the raw PDF bytes alongside the image because remote engines
    (Azure Document Intelligence, Google Document AI) read a PDF directly and
    do their own layout analysis — rasterising first would throw away the very
    structure they are best at recovering.
    """

    page: int
    png: bytes = b""
    pdf: bytes = b""
    metadata: dict[str, object] = field(default_factory=dict)


class OcrEngine(ABC):
    """Recognise text on pages that carry no extractable text layer."""

    #: Stable identifier recorded in provenance, so a package says which engine
    #: produced its text and a later run can be compared like for like.
    name: str = "ocr"

    @abstractmethod
    def recognise(self, images: list[PageImage]) -> OcrResult:
        """Return the text on each page. Synchronous and CPU/network-bound.

        Callers run this off the event loop; an engine must not assume it owns
        the process, and must not raise for a single unreadable page — record
        it in ``failed_pages`` so one bad page does not lose the document.
        """

    def close(self) -> None:  # noqa: B027 - optional hook; most engines hold nothing
        """Release anything held open. Safe to call more than once."""
