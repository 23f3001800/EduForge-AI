"""Ambient correlation identifiers.

A twelve-minute job spans one HTTP request, a background task, ten stages, and
dozens of model calls. Passing a request id through every one of those call
signatures would be noise in ninety functions to serve two, so it rides in
context variables instead.

Context variables rather than globals or thread-locals specifically because the
pipeline is asyncio: several jobs run concurrently in one process and one thread,
so a global would interleave and a thread-local would not isolate at all.
``contextvars`` is the only construct that follows an await chain correctly.

Nothing here is required for the system to work. If a log line has no job id it
is still a log line; the ids exist so that filtering the log by one job returns
that job's story and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

__all__ = [
    "bind",
    "current_context",
    "job_id_var",
    "new_request_id",
    "request_id_var",
    "stage_var",
]

#: Per-request, echoed to the client so a user-reported failure can be found in
#: the log by the id printed on their screen.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

#: Per-job, which outlives the request that created it.
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

#: The pipeline stage currently executing.
stage_var: ContextVar[str | None] = ContextVar("stage", default=None)

_VARS = {"request_id": request_id_var, "job_id": job_id_var, "stage": stage_var}


def new_request_id() -> str:
    """Short and readable. This gets pasted into bug reports and read aloud."""
    return uuid.uuid4().hex[:12]


def current_context() -> dict[str, str]:
    """Whatever correlation is in scope, omitting what is not set."""
    return {name: value for name, var in _VARS.items() if (value := var.get()) is not None}


@contextmanager
def bind(**values: Any) -> Iterator[None]:
    """Bind correlation for the duration of a block, then restore it exactly.

    Restoring via the token rather than resetting to ``None`` is what makes this
    safe to nest: an inner ``bind(stage=...)`` inside an outer one leaves the
    outer value intact on exit instead of clearing it.
    """
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    for name, value in values.items():
        var = _VARS.get(name)
        if var is not None and value is not None:
            tokens.append((var, var.set(str(value))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
