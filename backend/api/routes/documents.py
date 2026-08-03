"""Document upload (FR-01, NFR-09, H-15).

Uploads come from the public internet, so this route is a trust boundary. It
enforces size and type before anything touches a parser, and it deduplicates on
content hash so the same file uploaded twice yields one document.

MIME is taken from the sniffed magic bytes, not the client-supplied
``content_type`` and not the file extension — both are attacker-controlled.
Deep parsing, archive inspection and page-count limits belong to stage 1 (M2);
this route stops the obviously-wrong before it costs anything.

Size is checked twice, in increasing cost order: the declared ``Content-Length``
first, then the body itself as it is read, in bounded chunks. Reading the whole
upload and *then* measuring it — which is what this route used to do — means a
client that says it is sending 25 MB and sends 4 GB gets 4 GB of process memory
before the limit is consulted.
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from api.access import require_access
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

#: Read granularity. Small enough that the overshoot past the limit is bounded
#: by one chunk, large enough not to turn a 25 MB upload into 100k awaits.
_CHUNK_BYTES = 256 * 1024

#: A multipart body is the file plus a boundary, a part header and a trailer.
#: Allowed for so that a file exactly at the limit is not rejected on the
#: strength of the envelope around it.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024


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


def _too_large(size_bytes: int, settings: Settings) -> HTTPException:
    return HTTPException(
        413,
        detail={
            "code": "document_too_large",
            "message": f"File exceeds {settings.max_upload_mb} MB limit.",
            "details": {
                "size_bytes": size_bytes,
                "limit_bytes": settings.max_upload_bytes,
            },
        },
    )


def _declared_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        # A malformed header is not trusted either way; the streaming read below
        # is the check that actually holds.
        return None


class _OverLimitError(Exception):
    def __init__(self, size_bytes: int) -> None:
        super().__init__(size_bytes)
        self.size_bytes = size_bytes


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read the upload, stopping the moment it goes past ``limit``.

    Returns at most ``limit`` bytes' worth of accepted content; the caller raises
    on overflow. The point is that nothing beyond one chunk past the limit is
    ever held.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise _OverLimitError(total)
        chunks.append(chunk)
    return b"".join(chunks)



@router.post("/documents", status_code=201, dependencies=[Depends(require_access)])
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_app_settings),
) -> dict[str, object]:
    limit = settings.max_upload_bytes

    # Cheapest rejection first: the client's own declaration. A liar is caught by
    # the bounded read below, so this costs nothing and saves everything when the
    # client is honest.
    declared = _declared_length(request)
    if declared is not None and declared > limit + _MULTIPART_OVERHEAD_BYTES:
        raise _too_large(declared, settings)

    try:
        payload = await _read_bounded(file, limit)
    except _OverLimitError as over:
        await file.close()
        raise _too_large(over.size_bytes, settings) from None

    if not payload:
        raise HTTPException(422, detail={"code": "empty_document", "message": "File is empty."})

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
    # Keyed on the stored record's uri, not the candidate's: on a deduplicated
    # upload those are the same content anyway, and writing the candidate's uri
    # would orphan bytes nothing ever reads.
    await store.put_blob(stored.blob_uri, payload)

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
