"""Structured logging.

One JSON object per line, with the correlation ids from ``context`` merged in
automatically. JSON because these logs are read by ``az webapp log tail`` and by
whatever aggregator comes later, and a grep-able ``"job_id":"..."`` is worth more
than pretty alignment nobody sees.

Implemented on the standard library rather than structlog. The dependency is
declared in ``platform_deps`` but not installed in the running image, and the
part of structlog that matters here — merge a context dict, emit JSON — is about
forty lines. Adding a dependency to the deployed image to save forty lines of
well-understood code is a bad trade, and this way ``logging`` calls from inside
FastAPI, uvicorn and the SDKs land in the same format as ours.

Anything passed as an ``extra`` field appears as a top-level key, so
``logger.info("stage finished", extra={"duration_ms": 812})`` is queryable
without parsing the message.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from core.obs.context import current_context

__all__ = ["JsonFormatter", "configure_logging", "get_logger"]

#: Attributes `logging` puts on every record. Anything outside this set was
#: passed by a caller as `extra=` and belongs in the output.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, correlation merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **current_context(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            # The type and message, not the whole traceback: a traceback per line
            # makes JSON logs unreadable, and the traceback is already going to
            # stderr through the default handler chain when it matters.
            exc_type, exc_value, _ = record.exc_info
            payload["error_type"] = getattr(exc_type, "__name__", str(exc_type))
            payload["error"] = str(exc_value)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Install the formatter on the root logger.

    Idempotent — replaces handlers rather than appending, because uvicorn's
    reloader calls application setup more than once and each call would otherwise
    add another handler and duplicate every line.

    ``json_output=False`` gives plain text, which is what you want when reading a
    local run in a terminal.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; let its records propagate to ours so
    # access logs and application logs come out in one format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # The provider SDKs log every request at DEBUG, including payloads. That is
    # both noisy and a way to leak document text into logs.
    for name in ("httpx", "httpcore", "openai", "google_genai", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
