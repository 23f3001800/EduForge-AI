# syntax=docker/dockerfile:1.7
#
# EduForge AI — single-process image (API drives the worker in-process; see
# docs/12-deployment.md "Known limitations"). Two stages: build the Vite
# frontend, then assemble a slim, non-root Python 3.12 runtime.
#
# Build:  docker build -t eduforge-ai .
# Run:    docker run --rm -p 8000:8000 --env-file .env eduforge-ai
#
# ── env this image consumes (all validated by backend/core/config.py) ───────
#   LLM_PROFILE            production | dev | ci   (default: production)
#   Open_Router_API_KEY    required when LLM_PROFILE=production|dev
#   PORT                   port to bind (platforms like Render/Railway inject
#                           this); defaults to 8000 for a plain `docker run`

# ─────────────────────────────── frontend build ──────────────────────────────
FROM node:22-slim AS frontend-build
WORKDIR /src/frontend

# Install deps first so this layer only reinvalidates when the lockfile changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build
# -> /src/frontend/dist

# ─────────────────────────────── python runtime ──────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# Non-root user. Home is /app so pip's editable install and any runtime temp
# files land somewhere the user actually owns.
RUN groupadd --system --gid 1000 eduforge \
    && useradd --system --uid 1000 --gid eduforge --home-dir /app --shell /usr/sbin/nologin eduforge

# The backend source tree (contracts/core/stages/orchestration/worker/api/
# pedagogy) is what gets pip-installed editable and what PYTHONPATH points at —
# same layout the Makefile uses locally (`export PYTHONPATH := backend`, run
# from the repo root).
COPY backend/ backend/
# config/models.yaml is read via a REPO_ROOT-relative path in core/config.py
# (REPO_ROOT = parents[2] of backend/core/config.py), so it must sit next to
# backend/, not inside it.
COPY config/ config/

# `api`     -> fastapi, uvicorn, python-multipart, sse-starlette (serve the app)
# `llm`     -> langgraph, plus the provider SDK (openai backs both OpenRouter,
#              the default production provider, and the Azure OpenAI adapter)
# `parsing` -> pypdf, pdfplumber, python-docx, python-pptx (stage 1 ingestion)
# `render`  -> fpdf2 (stage 10). Pure Python — no cairo, pango, gdk-pixbuf,
#              wkhtmltopdf or LaTeX, which is exactly why publishing fits in this
#              image with no apt layer at all. The Noto fonts ship in the tree.
#
# NOT installed, deliberately:
#   `platform_deps` (sqlalchemy/alembic/psycopg/pgvector) — nothing connects to
#       Postgres yet; the store is in-memory (see docs/12-deployment.md).
RUN pip install --no-cache-dir -e "backend[api,llm,parsing,render,ocr]"

# Built frontend assets. main.py does not currently mount them (see
# docs/12-deployment.md "Must-fix before production") — this makes the asset
# available in the image the moment that one line lands, without a rebuild of
# this Dockerfile.
COPY --from=frontend-build /src/frontend/dist frontend/dist

# blob/ exists for BLOB_BACKEND=local; unused by the in-memory store today but
# harmless to provision, and it must be writable by the non-root user if a
# future local blob implementation lands behind the same Store interface.
RUN mkdir -p /app/blob && chown -R eduforge:eduforge /app

USER eduforge

EXPOSE 8000

# No curl in the base image and none added on purpose (keeps the image
# smaller and avoids an apt-get layer); Python is already here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,sys,urllib.request; \
        urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz', timeout=3).read(); \
        sys.exit(0)" || exit 1

# Shell form so ${PORT:-8000} expands: platforms like Render/Railway inject
# PORT and expect the process to bind to it; `docker run -p` maps 8000 by
# default when PORT is unset. --app-dir backend mirrors `make dev` exactly.
CMD ["sh", "-c", "exec uvicorn api.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
