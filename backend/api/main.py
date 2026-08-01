"""FastAPI application.

Single origin by design: the built frontend is served as static assets from this
same app, so there is no CORS configuration, no second deploy, and no environment
variable pointing one at the other. That removes an entire class of failures that
only ever appear in the deployed environment (docs/02 ADR #8).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes import documents, events, jobs, options
from contracts.primitives import SCHEMA_VERSION
from core.config import REPO_ROOT, get_settings

API_PREFIX = "/api/v1"

#: Fallback wording when a route raises with a code but no human-readable text.
_DEFAULT_MESSAGES = {
    404: "The requested resource was not found.",
    409: "That conflicts with the current state.",
    413: "The upload is too large.",
    415: "That file type is not supported.",
    422: "The request could not be processed.",
}

#: Where `npm run build` puts the bundle, and where the Dockerfile copies it.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="EduForge AI",
        version="0.1.0",
        description=(
            "Converts raw educational documents into a structured, classroom-ready "
            "Teacher Knowledge Package."
        ),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
    )

    app.include_router(documents.router, prefix=API_PREFIX)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(options.router, prefix=API_PREFIX)

    # Every failure leaves through one of these three, so a client parses one
    # shape. This used to be true only of unhandled exceptions: a deliberate
    # HTTPException returned FastAPI's `{"detail": ...}` and a validation error
    # returned `{"detail": [ ... ]}`, so the UI's `body.error.message` read
    # `undefined.message` and the real error was replaced by a TypeError.
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Normalise a raised HTTPException into the envelope.

        Routes raise with ``detail={"code": ..., "message": ...}``, so that dict
        is the envelope's body when present; a bare string detail becomes the
        message.
        """
        detail: Any = exc.detail
        if isinstance(detail, dict):
            error = {
                "code": detail.get("code", "http_error"),
                "message": detail.get("message")
                or _DEFAULT_MESSAGES.get(exc.status_code, "Request failed."),
                **({"details": detail["details"]} if "details" in detail else {}),
            }
        else:
            error = {"code": "http_error", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": error})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        """422s, flattened to something a person can act on.

        Pydantic's raw error list names the failing field in ``loc`` and buries
        the reason in ``msg``; a UI showing the list verbatim shows JSON. The
        first error becomes the message and the whole list stays in ``details``.
        """
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        reason = first.get("msg", "Request body is not valid.")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": f"{field}: {reason}" if field else reason,
                    "details": {"errors": jsonable_encoder(errors)},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        """Never leak an internal traceback to a caller."""
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {"type": type(exc).__name__},
                }
            },
        )

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness only — deliberately checks no dependency, so it stays fast."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, Any]:
        settings = get_settings()
        return {
            "status": "ok",
            "llm_profile": settings.llm_profile,
            "schema_version": SCHEMA_VERSION,
        }

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA from this same app, if it has been built.

    Mounted last so it can never shadow ``/api/v1``, ``/healthz`` or ``/readyz``
    — Starlette matches routes in registration order, and this one matches
    everything.

    Absent ``dist/`` is not an error: the backend suite and ``make dev`` run
    against an unbuilt frontend constantly, and failing to boot over a missing
    static bundle would make the API undevelopable. The deployed image always has
    it, because the Dockerfile builds it in an earlier stage.
    """
    if not (FRONTEND_DIST / "index.html").is_file():
        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Any non-API path resolves to the SPA shell.

        The frontend routes client-side, so a hard refresh on ``/run/<job-id>``
        arrives here as a real GET the server has no route for. Returning
        ``index.html`` is what lets the router take over — without it a refresh
        mid-run 404s, which is precisely the moment the progress stream is
        supposed to prove it survives one.

        A real file wins over the shell so ``favicon.ico`` and friends resolve;
        anything under ``api/`` 404s honestly instead of returning HTML to a
        caller that asked for JSON.
        """
        if path.startswith("api/"):
            raise HTTPException(404, detail={"code": "not_found"})

        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


app = create_app()
