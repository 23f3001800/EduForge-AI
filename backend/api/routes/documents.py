"""Document upload (FR-01, NFR-09, H-15).

Uploads come from the public internet, so this route is a trust boundary. It
enforces size and type before anything touches a parser, and it deduplicates on
content hash so the same file uploaded twice yields one document.

MIME is taken from the sniffed magic bytes, not the client-supplied
``content_type`` and not the file extension — both are attacker-controlled.
Deep parsing and page-count limits belong to stage 1 (M2); this route stops the
obviously-wrong before it costs anything.
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.deps import get_app_settings, get_store
from core.config import Settings
from core.storage.base import DocumentRecord, Store

router = APIRouter(tags=["documents"])

#: Magic-byte prefixes for the formats the assignment names. DOCX and PPTX are
#: both ZIP containers, so they share a signature and are disambiguated later.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
]

_ZIP_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def sniff_mime(head: bytes, declared: str | None, filename: str) -> str | None:
    """Resolve the real media type, or None when unsupported."""
    for signature, mime in _SIGNATURES:
        if head.startswith(signature):
            if mime != "application/zip":
                return mime
            # A ZIP is only acceptable if it claims to be one of the OOXML types.
            if declared in _ZIP_MIMES:
                return declared
            lowered = filename.lower()
            if lowered.endswith(".docx"):
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if lowered.endswith(".pptx"):
                return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            return None

    # Plain text has no signature; accept it only if it decodes as UTF-8.
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text/plain"


@router.post("/documents", status_code=201)
async def upload_document(
    file: Annotated[UploadFile, File()],
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    payload = await file.read()

    if not payload:
        raise HTTPException(422, detail={"code": "empty_document", "message": "File is empty."})

    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            detail={
                "code": "document_too_large",
                "message": f"File exceeds {settings.max_upload_mb} MB limit.",
                "details": {
                    "size_bytes": len(payload),
                    "limit_bytes": settings.max_upload_bytes,
                },
            },
        )

    mime = sniff_mime(payload[:512], file.content_type, file.filename or "")
    if mime is None:
        raise HTTPException(
            415,
            detail={
                "code": "unsupported_media_type",
                "message": "Supported types are PDF, DOCX, PPTX, and plain text.",
            },
        )

    digest = hashlib.sha256(payload).hexdigest()
    candidate = DocumentRecord(
        id=uuid4(),
        sha256=digest,
        filename=file.filename or "upload",
        mime=mime,
        size_bytes=len(payload),
        blob_uri=f"mem://{digest}",
    )
    stored = await store.add_document(candidate)

    return {
        "document_id": str(stored.id),
        "sha256": stored.sha256,
        "filename": stored.filename,
        "mime": stored.mime,
        "size_bytes": stored.size_bytes,
        # A repeat upload satisfies the caller's intent, so this is 201 with a
        # flag rather than a 409 they would have to special-case.
        "deduplicated": stored.id != candidate.id,
    }
