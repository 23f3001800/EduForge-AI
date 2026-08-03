# EduForge AI — Deployment (DR-01)

> **Superseded.** This Render.com path was written before deployment and never actually used —
> the live app runs on **Azure App Service**, deployed from source. See
> [`13-azure-deployment.md`](13-azure-deployment.md) for what is actually running.
> `render.yaml` has been removed accordingly; the rest of this document is kept as a record of
> the alternative that was evaluated, not as current instructions.

---

## What ships

One Docker image (`Dockerfile`, repo root): the built `frontend/` copied into a slim, non-root
Python 3.12 runtime running `uvicorn api.main:app`. Single process — the API also drives the
worker in-process, because the job store is in-memory and cannot be shared across processes yet
(see README "Known limitations"). One container, no replicas, no external database.

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build: Node builds the frontend, Python 3.12-slim runs the API |
| `.dockerignore` | Keeps `.venv`, `node_modules`, `.git`, `.env`, caches out of the build context |
| `docker-compose.yml` | Local smoke test of the built image — not how this deploys |
| `.github/workflows/ci.yml` | Lint/test/boundaries/schema on every push and PR, then builds the image |
| `Makefile` | `make docker-build`, `make docker-run` |

---

## Platform: Render

**Chosen over Railway and Fly.io.** Both of those now require a card on file before a service gets
a public URL; Render still runs one free Docker-based web service without one. Render also reads a
`Dockerfile` natively (no buildpack translation to fight), gives the service a real HTTPS URL on
first deploy, and its dashboard is where the required secret is set — never in this repo.

Trade-off accepted: Render's free tier spins the instance down after ~15 minutes idle and takes
roughly 30–60s to cold-start on the next request. For a single-container, in-memory-store demo
service that is the right trade, not a defect to engineer around.

---

## Deploy steps (human-run)

1. **Push this branch to GitHub** (or your fork) — Render deploys from a connected repo.
2. **Create a free OpenRouter key** at <https://openrouter.ai/keys> if you don't already have one.
   The default profile only calls `:free` models, so this costs $0.
3. **Render dashboard → New → Blueprint.** Point it at this repo/branch. Render reads
   `render.yaml` and proposes one service, `eduforge-ai`, `plan: free`, built from `./Dockerfile`.
4. **Set the secret.** `render.yaml` declares `Open_Router_API_KEY` with `sync: false`, which
   means Render leaves it blank on purpose — it does not belong in a file committed to the repo.
   In the service's **Environment** tab, add:
   - `Open_Router_API_KEY` = your OpenRouter key
   (`LLM_PROFILE=production` is already set by the blueprint — see `render.yaml`.)
5. **Apply / deploy.** Render builds `Dockerfile` and starts the container.
6. **Port binding** — nothing to configure. Render injects `PORT`; the image's `CMD` binds
   uvicorn to `0.0.0.0:${PORT:-8000}` (see `Dockerfile`), which is exactly what Render's Docker
   runtime expects.
7. **Verify.** Render assigns a URL like `https://eduforge-ai-XXXX.onrender.com`.
   ```bash
   curl https://<your-service>.onrender.com/healthz     # {"status":"ok"}
   curl https://<your-service>.onrender.com/readyz       # {"status":"ok","llm_profile":"production",...}
   ```
   `render.yaml` also sets `healthCheckPath: /healthz`, so Render itself polls this before routing
   traffic to a new deploy and during rollouts.
8. **Smoke-test one real request** (this does make a live LLM call and is the one moment in this
   whole flow that costs anything against your key — it should still be $0 on `:free` models):
   ```bash
   curl -F "file=@physics.pdf" https://<your-service>.onrender.com/api/v1/documents
   ```

### Rollback

Render keeps every previous successful deploy. **Dashboard → the service → Deploys → pick the
previous one → Rollback.** This is a few seconds, not a redeploy, and it's why "every deploy must
be reversible" is satisfied without anything bespoke here — Render's own deploy history is the
mechanism, no extra tooling to build or trust.

---

## Environment variables

Every variable below is read by `backend/core/config.py` (`Settings`) and documented in
`.env.example`; nothing here is invented for this deploy.

| Variable | Required for this deploy? | Notes |
|---|---|---|
| `LLM_PROFILE` | Yes — set by `render.yaml` to `production` | `ci` needs no key at all (replay adapter) but also does not call a real model — wrong choice for a live demo |
| `Open_Router_API_KEY` | **Yes — set by hand, this is the one secret** | Missing this under `production`/`dev` raises in `Settings._required_key_for_profile` — see the note right below, the failure is real but **not** at process boot despite the module docstring's claim |
| `PORT` | No — injected by Render | Consumed by the `CMD` in `Dockerfile`, not by `Settings` (the app has no `port` setting; uvicorn's `--port` is a process argument, same as `make dev`) |
| everything else (`MAX_UPLOAD_MB`, `DATABASE_URL`, `BLOB_BACKEND`, `RETENTION_DAYS`, `DEMO_ACCESS_CODE`, …) | No | `Settings` defaults are fine for the demo. `DATABASE_URL` is a real default value but nothing connects to it — see "Why no Postgres" |

`DEMO_ACCESS_CODE` is worth setting by hand once real traffic is a concern: it's an optional shared
access code already wired into `Settings`; unset, the demo is open and rate-limited only by
whatever the app already enforces.

**Verified, not assumed — a missing key does not fail the boot.** `backend/core/config.py`'s module
docstring says "Fails fast at boot with a message naming the missing key," but `get_settings()` is
never called during app startup (`create_app()` builds routers only; nothing in `main.py` touches
`Settings` before the first request). Built and ran this image locally with
`LLM_PROFILE=production` and no key set to confirm the actual behavior: `/healthz` returns `200`
(it deliberately checks no dependency), the container reports Docker-healthy, and the process stays
up — it's the *first request that constructs `Settings`* that fails, with a `500` and a generic
`{"error":{"code":"internal_error",...}}` body (the blanket exception handler in `main.py` strips
the real message from the client; it's still in the server logs). In this deploy that first request
is either `GET /readyz` or the very first document upload (`POST /api/v1/documents` also depends on
`get_app_settings`), so a bad deploy surfaces within one request — just not at the health check.
**Practical consequence: always curl `/readyz` after a deploy, not only `/healthz`** — see step 7.

---

## Why no Postgres in this deploy

`docker-compose.yml` defines a `postgres` service, but it is **not started by default**
(`profiles: ["with-db"]`). That's deliberate, not an oversight: `backend/core/storage/memory.py`
is the only `Store` implementation that exists today, and nothing in `backend/core/storage/`
opens a connection to `DATABASE_URL`. Wiring a database into this deploy that nothing talks to
would be a false signal of durability. The interface (`core/storage/base.py`) is written so that
when `core/storage/postgres.py` lands, this compose file and the Render service only need
`DATABASE_URL` pointed at a real instance — no route, stage, or contract changes.

**Consequence for the deployed demo, stated plainly:** a Render free-tier restart (deploy, crash,
or idle spin-down/wake) loses every uploaded document and every job, in-flight or completed. This
matches the README's "Known limitations" and is not something this deployment configuration can
paper over — it is a property of the current storage layer.

---

## Must-fix before production

These are real, verified gaps — not speculative. Each was reproduced directly, not inferred, by
installing `backend`'s declared extras into a clean virtualenv and running the app/tests against
it (exactly what `Dockerfile` and `ci.yml` now do). **None of these were fixed here**: they live
under `backend/`, which is out of scope for this change — other agents own it. Filing here so
whoever owns `backend/pyproject.toml` next has a reproducible bug report, not a vague warning.

1. **`backend/pyproject.toml`'s `llm` extra is missing `openai` and `google-genai`.**
   `core/llm/providers/openai_compat.py` (which backs the OpenRouter adapter) does
   `import openai` inside `OpenRouterAdapter.__init__`; `gemini_provider.py` does
   `from google import genai`. Neither package is declared anywhere in `pyproject.toml`.
   **This is not merely a deploy-time issue** — `core/llm/client.py:build_adapters` constructs
   `OpenRouterAdapter` *eagerly* whenever `open_router_api_key` is set, which is why
   `backend/tests/unit/test_knowledge_core.py::test_anthropic_is_not_callable_merely_because_a_key_exists`
   fails with `ModuleNotFoundError: No module named 'openai'` in a venv built strictly from the
   declared extras — confirmed by reproducing it directly. It only doesn't fail in the existing
   `./.venv` because that venv has drifted ahead of what `pyproject.toml` declares (`openai` and
   `google-genai` are already installed there, undeclared).
   **Workaround in this change:** `Dockerfile` and `ci.yml` both pin `openai==2.51.0` and
   `google-genai==2.16.0` explicitly, alongside the declared extras, with a comment pointing back
   here. **Real fix:** add both to the `llm` extra in `backend/pyproject.toml`.

2. **The built frontend is never served.** `backend/api/main.py`'s module docstring says "the
   built frontend is served as static assets from this same app" (single origin, no CORS), but
   there is no `StaticFiles` mount, no `FileResponse` fallback, nothing in `main.py` or anywhere
   else in `backend/` that reads `frontend/dist`. Verified by grepping the whole backend tree for
   `StaticFiles`/`mount`/`dist` — zero hits outside that one docstring sentence and the frontend's
   own `vite.config.ts`. The API works end-to-end today; the UI does not load at the deployed URL.
   `Dockerfile` still copies `frontend/dist` into the image (at `/app/frontend/dist`, the path a
   `REPO_ROOT`-relative mount would expect) so the asset is already positioned — wiring
   `app.mount("/", StaticFiles(directory=..., html=True))` in `main.py`, registered *after* the
   API routers so `/api/v1/*` keeps precedence, is a `backend/` change and out of scope here.

3. **`make install` (and the README's own quick-start) under-installs.** Both say
   `pip install -e "backend[dev]"`. The `dev` extra is test/lint tooling only — no `fastapi`, no
   `uvicorn`, no parsing libraries. A venv built by literally following the README cannot run
   `make dev` or `make check` (route/test imports fail). The actual `./.venv` in this repo was
   populated with a broader, undocumented set of extras. `ci.yml` and `Dockerfile` both install
   the extras verified necessary (`api,llm,parsing`, plus `dev` for CI) rather than repeat the
   under-scoped command — but the discrepancy between what's documented and what's required should
   be closed at the source.

4. **`get_settings()` is never called at startup, so a missing key doesn't fail the boot** despite
   `backend/core/config.py`'s docstring claiming "fails fast at boot." Verified locally (see
   "Verified, not assumed" above): the container starts, `/healthz` returns `200`, and Docker's own
   `HEALTHCHECK` reports healthy with `LLM_PROFILE=production` and no key at all — the process only
   fails on the first request that constructs `Settings` (`/readyz`, or any route depending on
   `get_app_settings`, e.g. document upload), and that failure reaches the client as a generic `500`
   with no explanation (`main.py`'s catch-all exception handler). Not a correctness bug — the
   validation itself is correct and does the right thing eventually — but it means a health check
   alone (Docker's, Render's, or a human's) cannot distinguish "up and configured" from "up and
   silently broken." **Worked around here** by making step 7 below check `/readyz`, not just
   `/healthz`. **Real fix** is a `backend/` change: call `get_settings()` once during the FastAPI
   `startup` event (or at module import) so a bad deploy fails the same way a missing dependency
   already does, instead of waiting for a real request to discover it.

None of these four block this deployment from working — items 1 and 3 are worked around in
`Dockerfile`/`ci.yml`, item 4 is worked around in the verification step, and item 2 means the demo
is API-only (fully usable via `curl`/`/api/v1/docs`, per the README's own examples) until it's fixed
upstream.

---

## Failure modes and how this deployment handles them

| Failure | Behaviour |
|---|---|
| Missing `Open_Router_API_KEY` under `LLM_PROFILE=production` | Verified locally (not assumed): the container **stays up** and `/healthz` returns `200` — it does not fail at boot despite `config.py`'s docstring. The first request that builds `Settings` (`/readyz`, or a document upload) gets a `500` with a generic body; the real message (`"requires Open_Router_API_KEY to be set"`) is in the container logs, not the response. This is why step 7 checks `/readyz` specifically — see "Must-fix before production" item 4. |
| Container crashes mid-job | The in-memory store's state is lost with the process (see "Why no Postgres" above) — the in-flight job disappears, not just stalls. A teacher re-uploads and re-runs. This is the honest current behavior, not something this deployment config can fix. |
| Render free-tier idle spin-down | Next request cold-starts the container (Dockerfile has no slow init — no DB migration, no model warm-up); expect the request that wakes it to take tens of seconds, not fail outright. `/healthz` deliberately checks no dependency (see `main.py`), so it returns fast once the process is up, which is what Render's own health polling relies on. |
| Bad deploy | Roll back from Render's deploy history (see "Rollback" above) — no bespoke rollback tooling to trust or maintain. |
| LLM provider rate-limited or down | `core/llm/client.py` already owns retry/backoff and a token budget per job (see README "Orchestration"); this deployment adds nothing and takes nothing away from that — it's unchanged by being containerized. |
| Two requests uploading the same file | Deduplicated on content hash in the store itself (`add_document`, `core/storage/memory.py`) — a deployment/infra concern this explicitly is not, since it's already handled one layer down. |

---

## What only the human can do

- Create the OpenRouter account and key (constraint: no accounts created on your behalf).
- Create/connect the Render account and apply the blueprint.
- Paste the key into Render's Environment tab — it must never be committed, and this change does
  not do so.
- Decide whether to set `DEMO_ACCESS_CODE` before sharing the URL publicly.
- Fix the four items above in `backend/`, if/when this deploy needs to run the model path, serve
  the UI, or fail loudly on a bad config, without an out-of-band workaround.

---

## Verified locally before trusting any of the above

Docker Desktop was available in this environment, so the image was actually **built and run
locally** while writing this document — not deployed anywhere, no account touched, no push. What
was checked, with `docker build -t eduforge-ai:verify .` then `docker run`:

- The image builds clean off this `Dockerfile` (Vite build stage, then the Python stage installing
  `backend[api,llm,parsing]` plus the two pinned compensating packages).
- `LLM_PROFILE=ci`, no key: container starts, runs as the non-root `eduforge` user
  (`docker exec ... whoami` → `eduforge`), `/healthz` → `200 {"status":"ok"}`, `/readyz` →
  `200 {"status":"ok","llm_profile":"ci","schema_version":"1.0.0"}`, Docker's own `HEALTHCHECK`
  reports `healthy`.
- `LLM_PROFILE=production`, no key: this is what surfaced "Must-fix before production" item 4 —
  `/healthz` still `200`, container still Docker-healthy, but `/readyz` and a real file upload both
  return `500` with the `ValidationError` visible only in `docker logs`.
- `GET /` → `404`, confirming "Must-fix" item 2 (no static frontend mount) against the running
  container, not just by reading the source.

Reproduce with:

```bash
make docker-build
make docker-run          # or: docker compose up --build
curl localhost:8000/healthz
curl localhost:8000/readyz
```
