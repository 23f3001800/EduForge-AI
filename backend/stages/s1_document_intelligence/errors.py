"""Ingestion failures.

Every one of these is a *rejection*, not a crash. Uploads arrive from the public
internet, so malformed, oversized, and hostile input is the expected case and has
to produce a clean, specific answer rather than a 500 or a hang (NFR-09).
"""

from __future__ import annotations

__all__ = [
    "DocumentTooLarge",
    "EmptyDocument",
    "IngestionError",
    "ParseFailure",
    "ParseTimeout",
    "TooManyPages",
    "UnsupportedMediaType",
]


class IngestionError(Exception):
    """Base for anything that makes a document unusable."""

    code = "ingestion_error"
    http_status = 422

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "details": self.details}


class UnsupportedMediaType(IngestionError):
    code = "unsupported_media_type"
    http_status = 415


class DocumentTooLarge(IngestionError):
    code = "document_too_large"
    http_status = 413


class TooManyPages(IngestionError):
    code = "too_many_pages"


class EmptyDocument(IngestionError):
    """Parsed successfully but yielded no usable text.

    A scanned PDF with no text layer lands here. That is a real and common case,
    and the honest answer is "this file has no extractable text" rather than a
    package generated from nothing.
    """

    code = "empty_document"


class ParseFailure(IngestionError):
    code = "parse_failed"


class ParseTimeout(IngestionError):
    """A parser exceeded its wall-clock budget.

    Malformed and adversarial files can drive a parser into pathological work.
    A timeout converts an indefinite hang into a bounded rejection.
    """

    code = "parse_timeout"
