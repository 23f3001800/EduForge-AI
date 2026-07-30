"""FastAPI application.

Single origin by design: the built frontend is served as static assets from this
same app, so there is no CORS configuration, no second deploy, and no environment
variable pointing one at the other. That removes an entire class of failures that
only ever appear in the deployed environment (docs/02 ADR #8).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.routes import documents, events, jobs
from contracts.primitives import SCHEMA_VERSION
from core.config import get_settings

API_PREFIX = "/api/v1"


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

    return app


app = create_app()
