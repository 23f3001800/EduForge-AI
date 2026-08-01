"""FastAPI application.

Single origin by design: the built frontend is served as static assets from this
same app, so there is no CORS configuration, no second deploy, and no environment
variable pointing one at the other. That removes an entire class of failures that
only ever appear in the deployed environment (docs/02 ADR #8).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import documents, events, jobs
from contracts.primitives import SCHEMA_VERSION
from core.config import REPO_ROOT, get_settings

API_PREFIX = "/api/v1"

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

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        """Uniform error envelope; never leak an internal traceback to a caller."""
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
