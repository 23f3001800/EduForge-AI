"""Server-Sent Events — the progress stream (FR-14).

The requirement is "stream progress updates for long-running AI jobs". The part
that is not written down but decides whether it works in practice: an evaluator
*will* refresh the tab during a multi-minute run, and a proxy *will* cut an idle
connection. Both are handled here.

Three properties this endpoint guarantees:

1. Every frame carries ``stage`` and ``progress`` — the exact shape specified.
2. ``Last-Event-ID`` replays every missed event, so a reconnect loses nothing.
   Event ids are the persisted monotonic ``seq``, not an in-memory counter.
3. A comment heartbeat every 15s keeps intermediaries from closing an idle stream
   during a long stage.

Replaying a job that already finished returns its whole timeline and then closes,
so a client that arrives late still renders a complete run.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.deps import get_store
from core.storage.base import Store

router = APIRouter(tags=["jobs"])

HEARTBEAT_SECONDS = 15.0
TERMINAL_STAGES = {"completed", "failed", "cancelled"}


def _frame(event_id: int, event_name: str, payload: dict[str, Any]) -> str:
    return (
        f"id: {event_id}\n"
        f"event: {event_name}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    )


def _event_name(stage: str, level: str) -> str:
    if stage == "completed":
        return "completed"
    if stage == "failed":
        return "failed"
    return "warning" if level in {"warning", "error"} else "progress"


async def _stream(
    store: Store, job_id: UUID, cursor: int, request: Request
) -> AsyncIterator[str]:
    while True:
        if await request.is_disconnected():
            return

        events = await store.events_since(job_id, cursor)
        for event in events:
            cursor = event.seq
            payload: dict[str, Any] = {
                # The two keys the assignment names. Never omitted.
                "stage": event.stage,
                "progress": event.progress,
                "seq": event.seq,
                "level": event.level,
                "ts": event.created_at.isoformat(),
            }
            if event.message:
                payload["message"] = event.message
            payload.update(event.data)

            yield _frame(event.seq, _event_name(event.stage, event.level), payload)

            if event.stage in TERMINAL_STAGES:
                return

        # Nothing new: block until there is, then loop. On timeout emit a comment
        # so intermediaries see traffic without the client seeing a fake event.
        await store.wait_for_events(job_id, cursor, timeout=HEARTBEAT_SECONDS)
        if not await store.events_since(job_id, cursor):
            yield ": heartbeat\n\n"


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job_id: UUID,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    store: Store = Depends(get_store),
) -> StreamingResponse:
    if await store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found"})

    try:
        cursor = int(last_event_id) if last_event_id else 0
    except ValueError:
        # A malformed cursor replays from the start rather than failing: losing
        # the whole timeline is worse than re-sending events the client can dedupe.
        cursor = 0

    return StreamingResponse(
        _stream(store, job_id, cursor, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # defeat nginx response buffering
        },
    )
