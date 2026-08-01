"""Request correlation, access logging, and latency metrics.

One middleware rather than three: they all need the same start time and the same
request id, and splitting them would mean computing both twice and ordering them
carefully for no benefit.

The request id is accepted from the caller when supplied (``X-Request-ID``), so a
trace started at a proxy or in the browser survives into these logs instead of
being renamed at the door. It is always echoed back, which is what lets a user
quote the id from a failure and have it found in the log.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.obs import metrics
from core.obs.context import bind, new_request_id
from core.obs.logging import get_logger

__all__ = ["REQUEST_ID_HEADER", "ObservabilityMiddleware"]

REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger("api.access")


def _route_template(request: Request) -> str:
    """The route pattern, not the resolved path.

    ``/api/v1/jobs/{job_id}`` rather than the id itself. Labelling metrics by the
    resolved path would create one time series per job and make the registry
    unbounded — a classic way to take down a metrics backend with your own
    telemetry.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return str(path)
    # No matched route means a 404; bucketing those together keeps a scanner
    # probing random urls from minting a series per probe.
    return "unmatched"


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        started = time.perf_counter()

        with bind(request_id=request_id):
            try:
                response = await call_next(request)
            except Exception:
                # The exception handler will turn this into a 500 envelope; log
                # it here because that handler cannot see how long it took.
                elapsed = time.perf_counter() - started
                logger.exception(
                    "request failed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round(elapsed * 1000, 1),
                        "request_id": request_id,
                    },
                )
                metrics.record_request(request.method, _route_template(request), 500, elapsed)
                raise

            elapsed = time.perf_counter() - started
            route = _route_template(request)
            metrics.record_request(request.method, route, response.status_code, elapsed)

            # SSE streams stay open for the length of a job; logging one line per
            # stream at completion would report a twelve-minute "request" and
            # bury the ones that matter.
            if not route.endswith("/events"):
                logger.info(
                    "request",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "route": route,
                        "status": response.status_code,
                        "duration_ms": round(elapsed * 1000, 1),
                        "request_id": request_id,
                    },
                )

            response.headers[REQUEST_ID_HEADER] = request_id
            return response
