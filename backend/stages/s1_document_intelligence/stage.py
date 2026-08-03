"""Stage 1 — Document Intelligence.

Parses an uploaded file into a :class:`StructuredDocument` plus retrieval chunks.
Makes **zero model calls**: the same bytes in must always produce the same
structure out, which is asserted in the test suite.

This stage is a trust boundary. Input arrives from the public internet, so limits
are enforced here rather than assumed upstream (NFR-09), in this order:

1. **byte size** — cheapest possible rejection;
2. **archive shape** — for the two OOXML container types, before a parser is
   handed the bytes, because a small upload can declare gigabytes of members;
3. **wall clock, address space and CPU** — the parser runs in a child process, so
   exceeding the budget ends the work rather than merely abandoning the wait.

That third point is the one worth being precise about. ``asyncio.wait_for``
around ``asyncio.to_thread`` cancels the *awaiter*, not the thread: the parse
keeps running, keeps allocating, and keeps burning CPU with nothing left waiting
for it — measured at 67 seconds past a 3 second budget. A child process can be
killed, so that is what happens here. Where a deployment cannot create one, the
in-thread path is used instead and the guarantee degrades to "the request is
bounded" rather than "the work is bounded"; that is a deliberate, documented
fallback, not an accident.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import math
import multiprocessing
import threading
import weakref
from collections.abc import Callable, MutableMapping
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from contracts.document import (
    Block,
    DocumentMetadata,
    DocumentStats,
    OcrProvenance,
    StructuredDocument,
)
from core.obs.logging import get_logger
from stages.base import StageContext, stage_span
from stages.s1_document_intelligence import parsers
from stages.s1_document_intelligence.chunking import chunk_blocks
from stages.s1_document_intelligence.errors import (
    DocumentTooLarge,
    EmptyDocument,
    ParseFailure,
    ParseTimeout,
    UnsupportedMediaType,
)
from stages.s1_document_intelligence.structure import assign_section_paths, build_outline

__all__ = ["DocumentIntelligenceStage", "ParseLimits", "parse_document"]

PARSER_BY_MIME = {
    "application/pdf": parsers.parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parsers.parse_docx,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": parsers.parse_pptx,
    "text/plain": parsers.parse_text,
    "text/markdown": parsers.parse_text,
}

#: How long a parse child gets to come up before the subprocess path is judged
#: unavailable and the thread path is used instead. A warm forkserver answers in
#: ~25 ms; this is generous enough that a loaded machine is not misdiagnosed.
_CHILD_STARTUP_TIMEOUT_S = 15.0

#: CPU seconds a child may burn beyond its wall-clock budget before the kernel
#: kills it. RLIMIT_CPU is the backstop for the case where the explicit kill
#: below cannot run; it must exceed the wall clock or it would fire first on a
#: perfectly healthy parse.
_CPU_GRACE_S = 30

_log = get_logger(__name__)


@dataclass(frozen=True)
class ParseLimits:
    """The resource envelope one parse is allowed, resolved once per call."""

    archive_uncompressed_bytes: int = parsers.DEFAULT_MAX_ARCHIVE_BYTES
    archive_ratio: int = parsers.DEFAULT_MAX_ARCHIVE_RATIO
    archive_members: int = parsers.DEFAULT_MAX_ARCHIVE_MEMBERS
    max_blocks: int = parsers.DEFAULT_MAX_BLOCKS
    max_chars: int = parsers.DEFAULT_MAX_TEXT_CHARS
    in_subprocess: bool = True
    workers: int = 2
    memory_bytes: int = 2048 * 1024 * 1024


def _settings_or_none() -> Any | None:
    """Settings, or None when they cannot be constructed.

    OCR is optional, so a configuration problem must degrade it rather than
    fail the parse — the same rule _limits_from_settings follows.
    """
    try:
        from core.config import get_settings

        return get_settings()
    except Exception:  # pragma: no cover - a missing key is not a parse failure
        return None


def _limits_from_settings() -> ParseLimits:
    """Read the envelope from settings, falling back to the module defaults.

    Deliberately total: a settings object that cannot be constructed must not be
    the reason a parse fails open *or* fails closed. The defaults here are the
    same values the settings declare.
    """
    try:
        from core.config import get_settings

        settings = get_settings()
        return ParseLimits(
            archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            archive_ratio=settings.max_archive_ratio,
            archive_members=settings.max_archive_members,
            max_blocks=settings.max_blocks_per_document,
            max_chars=settings.max_text_chars,
            in_subprocess=settings.parse_in_subprocess,
            workers=settings.parse_workers,
            memory_bytes=settings.parse_memory_bytes,
        )
    except Exception:
        return ParseLimits()


# ─────────────────────────────────────────────────────── bounded child process ───


def _apply_child_limits(address_space_bytes: int, cpu_seconds: int) -> None:
    """Child-process initializer: cap address space and CPU before any work.

    Runs in the child, so a parser that allocates without bound gets
    ``MemoryError`` and a parser that spins gets ``SIGXCPU`` — either way the
    child dies and the parent sees a broken pool instead of a dying host.
    ``resource`` is POSIX-only and some sandboxes refuse the call; neither is a
    reason to fail the parse, so both are tolerated.
    """
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return

    for which, wanted in (
        (resource.RLIMIT_AS, address_space_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
    ):
        try:
            _soft, hard = resource.getrlimit(which)
            limit = wanted if hard == resource.RLIM_INFINITY else min(wanted, hard)
            resource.setrlimit(which, (limit, limit))
        except (ValueError, OSError):  # pragma: no cover - platform dependent
            continue


def _child_is_alive() -> bool:
    """Trivial round trip that proves a child can start and answer."""
    return True


_CONTEXT_LOCK = threading.Lock()
_mp_context: Any | None = None
_subprocess_unavailable = False
_fallback_warned = False


def _get_mp_context() -> Any | None:
    """A start method whose children are forked from a clean template.

    ``fork`` is refused on purpose: this process runs an event loop and a thread
    pool, and forking it copies locks held by threads that do not exist in the
    child. ``forkserver`` forks from a single-threaded template instead, and
    ``spawn`` starts fresh; either is safe, both are cheap enough (~25 ms warm).
    """
    global _mp_context, _subprocess_unavailable
    if _subprocess_unavailable:
        return None
    if _mp_context is not None:
        return _mp_context
    with _CONTEXT_LOCK:
        if _mp_context is not None:
            return _mp_context
        try:
            available = multiprocessing.get_all_start_methods()
            method = next((m for m in ("forkserver", "spawn") if m in available), None)
            if method is None:
                raise RuntimeError("no safe multiprocessing start method available")
            context = multiprocessing.get_context(method)
            if method == "forkserver":
                # Pre-importing the parsers keeps the per-parse cost at a fork
                # rather than a full interpreter warm-up.
                context.set_forkserver_preload(["stages.s1_document_intelligence.parsers"])
            _mp_context = context
        except Exception:
            _subprocess_unavailable = True
            return None
    return _mp_context


_SLOTS: MutableMapping[Any, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _parse_slot(workers: int) -> asyncio.Semaphore:
    """Bound how many parse children exist at once, per event loop.

    Keyed on the loop rather than module-global because a semaphore belongs to
    the loop that first awaits it, and the test suite runs a loop per test.
    """
    loop = asyncio.get_running_loop()
    slot = _SLOTS.get(loop)
    if slot is None:
        slot = asyncio.Semaphore(workers)
        _SLOTS[loop] = slot
    return slot


class _SubprocessUnavailableError(Exception):
    """The child-process path could not be used; the caller should use threads."""


def _terminate(executor: ProcessPoolExecutor) -> None:
    """Kill the child outright. This is the whole point of the process path."""
    for process in list((getattr(executor, "_processes", None) or {}).values()):
        try:
            process.kill()
        except Exception:  # pragma: no cover - already dead
            continue


def _timed_out(timeout_s: float, *, killed: bool) -> ParseTimeout:
    detail = "and the parser was killed" if killed else "and was abandoned"
    return ParseTimeout(
        f"Parsing exceeded {timeout_s:.0f}s {detail}.",
        timeout_s=timeout_s,
        work_terminated=killed,
    )


async def _run_in_subprocess(
    call: Callable[[], list[Block]], *, timeout_s: float, limits: ParseLimits
) -> list[Block]:
    """Parse in a child process whose memory, CPU and lifetime are all capped."""
    context = _get_mp_context()
    if context is None:
        raise _SubprocessUnavailableError("no usable multiprocessing context")

    cpu_seconds = max(1, math.ceil(timeout_s) + _CPU_GRACE_S)
    loop = asyncio.get_running_loop()

    async with _parse_slot(limits.workers):
        try:
            executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=context,
                initializer=_apply_child_limits,
                initargs=(limits.memory_bytes, cpu_seconds),
            )
        except Exception as exc:
            raise _SubprocessUnavailableError("could not create a process pool") from exc

        try:
            # Prove a child can start *before* the parse is committed to it. A
            # pool that fails here is an environment that forbids subprocesses,
            # and the caller falls back to threads. A pool that breaks after
            # this point had its child killed by its own limits — that is a
            # rejection, and retrying it in-thread would be re-running the
            # attack with the limits removed.
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(executor, _child_is_alive),
                    timeout=_CHILD_STARTUP_TIMEOUT_S,
                )
            except Exception as exc:
                _terminate(executor)
                raise _SubprocessUnavailableError("no parse child could be started") from exc

            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, call), timeout=timeout_s
                )
            except TimeoutError as exc:
                _terminate(executor)
                raise _timed_out(timeout_s, killed=True) from exc
            except BrokenExecutor as exc:
                _terminate(executor)
                raise ParseFailure(
                    "Parsing exhausted the memory or CPU allowed for one document and was stopped.",
                    reason="child_resource_limit",
                ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


async def _run_in_thread(call: Callable[[], list[Block]], *, timeout_s: float) -> list[Block]:
    """Fallback path. Bounds the wait; cannot bound the work — see module docs."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(call), timeout=timeout_s)
    except TimeoutError as exc:
        raise _timed_out(timeout_s, killed=False) from exc


async def _run_parser(
    call: Callable[[], list[Block]], *, timeout_s: float, limits: ParseLimits
) -> list[Block]:
    if limits.in_subprocess:
        try:
            return await _run_in_subprocess(call, timeout_s=timeout_s, limits=limits)
        except _SubprocessUnavailableError as exc:
            # Logged once per process, at WARNING: a control that quietly stops
            # applying is worse than one that was never configured, because
            # nothing tells you the timeout no longer ends the work.
            global _fallback_warned
            if not _fallback_warned:
                _fallback_warned = True
                _log.warning(
                    "parse_subprocess_unavailable",
                    extra={
                        "reason": str(exc),
                        "consequence": "parse timeout bounds the wait, not the work",
                    },
                )
    return await _run_in_thread(call, timeout_s=timeout_s)


# ────────────────────────────────────────────────────────────────── the stage ───


def _stats(blocks: list[Block]) -> DocumentStats:
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.type] = counts.get(block.type, 0) + 1
    return DocumentStats(
        headings=counts.get("heading", 0),
        paragraphs=counts.get("paragraph", 0),
        tables=counts.get("table", 0),
        equations=counts.get("equation", 0),
        figures=counts.get("figure_caption", 0),
        code_blocks=counts.get("code", 0),
    )


#: How far the uploader's declared document kind may move the per-page character
#: floor that decides whether a page is scanned.
#:
#: The floor is what actually decides. A page holding at least this many
#: characters is never called scanned, and on any ordinary page size a page under
#: the floor is already far below the density line — so the density test settles
#: nothing and biasing it would be theatre. The default floor is 60.
#:
#: 30 characters is a deliberate half-step: it moves the boundary by half its own
#: width, which is enough to change the answer for a page carrying a stray header
#: and nothing else, and not enough to reach a page with real text on it.
_KIND_FLOOR_NUDGE = 30

#: FAQ Q7 lets an uploader declare what they are sending. The hint is advisory:
#: someone uploading a born-digital chapter picks "Scanned PDF" to be safe, and
#: someone uploading a photocopy picks "Mostly Text". So it adjusts where the
#: line sits rather than deciding which side of it a page falls on.
_KIND_BIAS: dict[str, int] = {
    # Declared scanned: lean toward reading a marginal page rather than losing it.
    "scanned_pdf": +_KIND_FLOOR_NUDGE,
    # Declared text: lean against spending a metered OCR call on a page that
    # probably parsed fine.
    "mostly_text": -_KIND_FLOOR_NUDGE,
    "text_with_tables": -_KIND_FLOOR_NUDGE,
    # Diagrams and equations say nothing about whether a text layer exists - a
    # figure-heavy born-digital page is still born-digital - so they do not move
    # the line at all.
    "text_with_diagrams": 0,
    "text_with_equations": 0,
    "unknown": 0,
}


def _char_floor_for(document_kind: str | None) -> int:
    """The scanned-page character floor, adjusted by the uploader's declared kind."""
    from stages.s1_document_intelligence.ocr.detect import MIN_CHARS_PER_PAGE

    bias = _KIND_BIAS.get((document_kind or "unknown").strip().lower(), 0)
    # Never let a hint drive the floor to zero: at zero no page clears it, every
    # inked page becomes "scanned", and a wrong hint would send a whole readable
    # document to a metered recogniser.
    return max(10, MIN_CHARS_PER_PAGE + bias)


async def _recover_scanned_pages(
    *,
    payload: bytes,
    mime: str,
    blocks: list[Block],
    limits: ParseLimits,
    document_kind: str | None = None,
) -> tuple[list[Block], OcrProvenance | None]:
    """Read pages that carry no text layer, and record how it went.

    Returns the blocks unchanged and ``None`` whenever OCR does not apply —
    a non-PDF, a fully born-digital document, or no engine configured. That is
    the overwhelmingly common path and it must cost nothing: detection is a
    local measurement, and no engine is constructed until a page actually needs
    one.

    Recognised pages are appended rather than interleaved. Their true position
    in reading order is unknowable without laying them back out against the
    text blocks, and guessing wrong would scramble a document that OCR had just
    successfully rescued. ``page`` is set on every block, so ordering is
    recoverable downstream; :func:`assign_section_paths` runs afterwards and
    gives them section paths like any other block.
    """
    if mime != "application/pdf":
        return blocks, None

    from stages.s1_document_intelligence import ocr as ocr_module

    profiles = ocr_module.profile_pdf(payload)
    pages = ocr_module.scanned_pages(profiles, char_floor=_char_floor_for(document_kind))
    if not pages:
        return blocks, None

    settings = _settings_or_none()
    max_pages = getattr(settings, "ocr_max_pages", 60) if settings else 60
    if len(pages) > max_pages:
        # A hosted engine is metered per page. Refusing loudly beats quietly
        # billing for a 400-page scan the uploader thought was a chapter.
        _log.warning("ocr_skipped_too_many_pages", extra={"pages": len(pages), "limit": max_pages})
        return blocks, None

    engine = ocr_module.build_engine(settings) if settings else None
    if engine is None:
        _log.warning("ocr_needed_but_unavailable", extra={"pages": len(pages)})
        return blocks, None

    try:
        result = await asyncio.to_thread(ocr_module.recognise_scanned_pages, payload, pages, engine)
    except Exception:
        # OCR is a recovery path. If it fails, the document is no worse off
        # than before it ran, so the parse continues with what the parser found.
        _log.warning("ocr_failed", exc_info=True)
        return blocks, None
    finally:
        engine.close()

    # Built through the same choke point as every parser, so OCR output is
    # bounded by the same block and character ceilings. A recogniser handed a
    # noisy scan can emit a great deal of text.
    builder = parsers._BlockBuilder(max_blocks=limits.max_blocks, max_chars=limits.max_chars)
    for page in result.pages:
        builder.add("paragraph", page.text, page=page.page)
    recovered = list(builder.blocks)

    threshold = getattr(settings, "ocr_min_confidence", None) if settings else None
    provenance = OcrProvenance(
        engine=result.engine,
        pages=[p.page for p in result.pages if p.text.strip()],
        failed_pages=list(result.failed_pages),
        confidence=result.confidence,
        min_confidence=threshold,
    )
    _log.info(
        "ocr_recovered_pages",
        extra={
            "engine": result.engine,
            "pages": len(recovered),
            "confidence": result.confidence,
        },
    )
    return blocks + recovered, provenance


async def parse_document(
    *,
    document_id: UUID,
    payload: bytes,
    filename: str,
    mime: str,
    max_bytes: int,
    max_pages: int,
    timeout_s: float,
    limits: ParseLimits | None = None,
    document_kind: str | None = None,
) -> tuple[StructuredDocument, list[Any]]:
    """Parse bytes into a structured document and its chunks."""
    if len(payload) > max_bytes:
        raise DocumentTooLarge(
            f"File is {len(payload)} bytes; limit is {max_bytes}.",
            size_bytes=len(payload),
            limit_bytes=max_bytes,
        )

    parser = PARSER_BY_MIME.get(mime)
    if parser is None:
        raise UnsupportedMediaType(
            f"No parser for media type {mime!r}.",
            mime=mime,
            supported=sorted(PARSER_BY_MIME),
        )

    limits = limits or _limits_from_settings()

    # Before the parser, not inside it. DOCX and PPTX are ZIP archives, and the
    # byte-size check above says nothing about what they expand to: a 2.18 MB
    # DOCX declaring 2.9 GB of members passes every limit upstream of here.
    if mime in parsers.OOXML_MIMES:
        parsers.inspect_ooxml_archive(
            payload,
            max_total_bytes=limits.archive_uncompressed_bytes,
            max_ratio=limits.archive_ratio,
            max_members=limits.archive_members,
        )

    call = functools.partial(
        parser,
        payload,
        max_pages=max_pages,
        max_blocks=limits.max_blocks,
        max_chars=limits.max_chars,
    )
    blocks: list[Block] = await _run_parser(call, timeout_s=timeout_s, limits=limits)

    # Pages with no text layer are invisible to every parser above — the words
    # are pixels. Recover them before deciding the document is empty, because
    # "scanned" and "blank" produce identical output up to this point and only
    # one of them is a failure. FAQ Q7 names scanned PDFs as an expected input.
    blocks, ocr = await _recover_scanned_pages(
        payload=payload,
        mime=mime,
        blocks=blocks,
        limits=limits,
        document_kind=document_kind,
    )

    if not blocks:
        raise EmptyDocument(
            "No extractable text was found. If this is a scanned document, OCR "
            "either found nothing or is not configured — set OCR_ENGINE and the "
            "credentials for the engine you choose."
        )

    blocks = assign_section_paths(blocks)
    word_count = sum(len(b.text.split()) for b in blocks)
    pages = [b.page for b in blocks if b.page]

    document = StructuredDocument(
        document_id=document_id,
        metadata=DocumentMetadata(
            filename=filename,
            mime=mime,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            page_count=max(pages) if pages else None,
            word_count=word_count,
            title=next((b.text for b in blocks if b.type == "heading"), None),
            ocr=ocr,
        ),
        blocks=blocks,
        outline=build_outline(blocks),
        stats=_stats(blocks),
    )
    return document, chunk_blocks(document_id, blocks)


class DocumentIntelligenceStage:
    """Pipeline node wrapper. Replaces the stage-1 stub."""

    name = "document-intelligence"

    def __init__(
        self,
        *,
        payload: bytes,
        filename: str,
        mime: str,
        max_bytes: int,
        max_pages: int,
        timeout_s: float,
        limits: ParseLimits | None = None,
    ) -> None:
        self._payload = payload
        self._filename = filename
        self._mime = mime
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._timeout_s = timeout_s
        self._limits = limits

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            document, chunks = await parse_document(
                document_id=UUID(state["document_id"]),
                payload=self._payload,
                filename=self._filename,
                mime=self._mime,
                max_bytes=self._max_bytes,
                max_pages=self._max_pages,
                timeout_s=self._timeout_s,
                limits=self._limits,
                document_kind=ctx.options.get("document_kind"),
            )
            await span.progress(0.8, message=f"{len(document.blocks)} blocks, {len(chunks)} chunks")
            if document.stats.equations:
                span.warn(f"{document.stats.equations} equations detected")

            # A teacher has to be told which words came from a machine reading
            # pixels rather than from the document itself. Everything downstream
            # grounds its claims against this text, so if OCR misread it, every
            # later check confirms the error instead of catching it — this
            # warning is the only place that uncertainty is visible.
            ocr = document.metadata.ocr
            if ocr is not None:
                span.decide(
                    f"{len(ocr.pages)} page(s) read by OCR ({ocr.engine})",
                    "those pages carried no text layer, so the words were "
                    "recovered from the page image rather than extracted",
                )
                if ocr.below_threshold:
                    span.warn(
                        f"OCR confidence {ocr.confidence:.0%} is below the "
                        f"{ocr.min_confidence:.0%} threshold on page(s) "
                        f"{ocr.pages}; check this material against the source "
                        "before teaching from it"
                    )
                elif ocr.confidence is None:
                    span.warn(
                        f"{ocr.engine} reported no confidence for the "
                        f"{len(ocr.pages)} page(s) it read; their accuracy is unknown"
                    )
                if ocr.failed_pages:
                    span.warn(
                        f"page(s) {ocr.failed_pages} had no text layer and could "
                        "not be read; that content is missing from this package"
                    )
            return {
                "structured_document": document.model_dump(mode="json"),
                "chunks": [c.model_dump(mode="json") for c in chunks],
            }
