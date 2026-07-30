# EduForge AI — Module Briefs (ready-to-issue agent prompts)

One brief per module. Each is self-contained: an agent receiving it needs only this brief plus
`docs/` and `contracts/`. Issue **M0 alone first** — it blocks everything.

**Shared preamble to prepend to every brief:**

> You are implementing one module of EduForge AI. The authoritative specs are in `docs/`:
> `00-requirements-trace.md` (requirement IDs), `01-srs.md`, `02-hld.md`, `03-lld.md`,
> `04-data-model.md`, `05-agent-graph.md`, `06-api-spec.md`, `07-folder-structure.md`,
> `10-definition-of-done.md`.
>
> Rules that are not negotiable:
> 1. **Own only your directories.** Do not modify files outside them. If you need a change in
>    `contracts/`, stop and raise it — do not edit it yourself.
> 2. **Never import another stage.** Depend on `contracts/`, `core/`, `pedagogy/` only. CI
>    enforces this.
> 3. **Code against fixtures, not against other modules.** Stub every dependency you do not own.
> 4. Model calls go through `core/llm/client.py` only. Never call the Anthropic SDK directly
>    from a stage.
> 5. Your PR description must list the requirement IDs from `docs/10-definition-of-done.md` that it
>    closes, and every checkbox in your module's DoD must pass.
> 6. Work on your own branch; open a draft PR. Do not merge to `main`.

---

## M0 · Contracts & Schema — **issue first, alone**

**Owns:** `backend/contracts/**`, `backend/tests/contract/**`, `scripts/generate_schema.py`,
`backend/tests/fixtures/**`

Implement every Pydantic v2 model in LLD §1 and the full `TeacherKnowledgePackage`. Then:
generate and commit `contracts/schema/tkp-1.0.0.json`; write one complete hand-authored fixture TKP
that validates; write input **and** output fixtures for all ten stages; add a CI check that fails on
schema drift.

Get the constraints right — they are load-bearing:
- `Grounded.evidence` has `min_length=1`. Traceability must be enforced by the type system, not by
  reviewer diligence.
- MCQ options: exactly 4, exactly one `is_correct: true`.
- `TeachingPlan.total_periods` bounded `[1, 20]`.
- `progress` bounded `[0, 100]`.
- Non-MCQ assessment items require a `rubric`.

`contracts/` must import nothing else in the project. Do not add behaviour — no I/O, no prompts, no
business logic. This package is vocabulary only.

**Definition of Done:** `docs/10-definition-of-done.md` § M0.

---

## M1 · Platform Foundation

**Owns:** `backend/core/{storage,progress,observability,config}/**`, `backend/alembic/**`
**Depends on:** M0

Build the migration for every table in `04-data-model.md`; repositories for documents, jobs, events,
checkpoints, packages, artifacts; a blob abstraction with local-fs and S3-compatible backends; the
settings loader (fail fast at boot with a message naming the missing key); `structlog` JSON logging
with a secret-redaction filter; a Prometheus registry; and the `ProgressEmitter`.

Two details that matter more than they look:
- `ProgressEmitter` **persists first, then notifies.** A dropped `pg_notify` must cost latency, never
  correctness. Write a test that proves the row exists when notify fails.
- The `jobs_claimable_idx` partial index and the `stage_outputs` uniqueness constraint are what make
  the queue safe. Do not "simplify" them.

Test repositories against a real Postgres (testcontainers or a CI service), not a mock.

---

## M2 · Document Intelligence (Stage 1)

**Owns:** `backend/stages/s1_document_intelligence/**`
**Depends on:** M0 (contracts), M1 (blob read — stub it if M1 is not ready)

Parse PDF/DOCX/PPTX/TXT into `StructuredDocument`, preserving structure: heading hierarchy and
outline, tables as `{headers, rows}`, equations normalised to LaTeX with raw text retained, figure
captions, document metadata. Then chunk section-aware per LLD §4.1.

This stage makes **zero model calls.** It is deterministic parsing. Same file in, byte-identical
structure out — assert that in a test.

The bar for "structure preservation" (FR-02, 15 % of the grade) is cell-level table fidelity and
recoverable equations, not "the text came out." Build fixtures that assert that, not substring
matches.

Safety is yours (NFR-09): MIME sniffing not extension trust, size and page caps, a hard parse
timeout, macros disabled, no shell-out to external converters. Include zip-bomb, truncated-PDF, and
adversarial-instruction fixtures; each must produce a clean `422`, never a 500 and never a hang.

---

## M3 · Knowledge Core (Stages 2–3 + Retrieval + Pedagogy Registry)

**Owns:** `backend/stages/s2_classification/**`, `backend/stages/s3_knowledge/**`,
`backend/core/retrieval/**`, `backend/pedagogy/**`
**Depends on:** M0; M1 for the chunk store (stub if needed)

This module carries the single largest share of the grade (educational understanding 20 % +
document intelligence support + both hallucination and versatility risks). Three things define it:

**1. `pedagogy_profile` is the versatility mechanism (H-07, Q1).** Stage 2 emits it, and it routes
prompt fragments, activity weights, assessment mix, and the validation ruleset via the registry you
build in `pedagogy/`. **No subject name may appear anywhere in code or in a branch condition.** A
poetry document and a physics document must take structurally identical paths through different
data. Test that they get different profiles and that neither errors.

**2. Evidence is mandatory, not aspirational (H-06, Q2).** Every concept, definition, formula,
example, application, and misconception carries ≥ 1 `Evidence` span with a resolvable `chunk_id` and
a verbatim quote. Items that arrive without evidence are dropped at stage validation — they do not
get passed downstream with a shrug. This is what makes both FR-10 and BR-02 work; it is the highest-
leverage thing in the build.

**3. The concept DAG makes sequencing verifiable (H-09).** Emit `concept_graph` with
`prerequisite_of` edges. Detect cycles, break the lowest-confidence edge, record a warning. Do not
crash and do not silently ship a cyclic graph.

Also: map-reduce extraction above the single-call budget with dedup merge and evidence union
(LLD §4.2); hybrid BM25 + optional dense retrieval with RRF; curriculum alignment that returns
`null` rather than inventing a standard code.

---

## M4 · Orchestration (LangGraph + Worker + LLMClient)

**Owns:** `backend/orchestration/**`, `backend/worker/**`, `backend/core/llm/**`,
`backend/stages/base.py`
**Depends on:** M0, M1

Build the graph in `05-agent-graph.md`, the `SKIP LOCKED` worker, and — most importantly — the
`LLMClient`, which is the single choke point for every model call in the system.

`LLMClient` owns: structured output via `messages.parse()` with Pydantic models, one
schema-error-feedback repair attempt then a deterministic degraded object, adaptive thinking with
per-stage effort from `config/models.yaml`, prompt caching on the shared document prefix, retry with
backoff+jitter on 429/5xx, a concurrency semaphore, a per-job token budget, refusal handling, and
per-call accounting into `llm_calls`.

**Default every stage to `claude-opus-5`.** Model choice is an operator decision made in
`config/models.yaml`, never a hardcoded value in a stage.

Three tests are the real proof this module works:
- Kill the worker mid-run → restart → the job resumes at the first incomplete stage and completed
  stages are **not re-billed**.
- A stubbed transport that returns malformed JSON once proves the repair path; twice proves the
  degraded fallback.
- A two-stage run asserts `cache_read_input_tokens > 0` on the second stage — if the cache is not
  hitting, the prefix has a volatile byte in it and you need to find it.

Also yours: the injection-guard helper (`document_block()`) that every stage must route document
text through, and `orchestration/diagram.py` which generates the README architecture diagram from
the graph so it cannot go stale.

---

## M5 · Pedagogy Generation (Stages 4–8)

**Owns:** `backend/stages/s4_planner/**` … `backend/stages/s8_gaps/**`
**Depends on:** M0; consumes M3's contracts (use fixtures — do not wait for M3)

This module produces what the evaluator actually reads. Content generation is 25 % of the grade and
teaching planning another 20 %.

**Stage 4 is part algorithm, part model.** Derive period count from concept load (LLD §4.3) — never
hardcode 5. Topologically sort the prerequisite DAG and partition into balanced bands
**deterministically in code**; the model titles the bands, writes the rationale, and allocates time
within them. The model does not get to reorder prerequisites. That split is what makes cross-period
consistency verifiable instead of hopeful.

**Stages 5–8 are profile-conditioned throughout.** Pull prompt fragments, activity weights, and
assessment mix from the pedagogy registry. A narrative document producing zero numerical items is
**correct output**, not a bug — write the test that asserts it.

Per-period generation receives a narrowed context: only that period's concepts, objectives, and
evidence. Not the whole knowledge base. This keeps prompts small, cache hits high, and — critically
— stops a period from teaching another period's material.

Quality bar, not just schema validity: teacher scripts should be usable aloud; activities need real
materials and real success criteria; MCQ distractors should trace to actual misconceptions; rubrics
should discriminate. M11's rubric scores are how you will know whether you hit it.

---

## M6 · Validation Engine (Stage 9)

**Owns:** `backend/stages/s9_validation/**`
**Depends on:** M0

Four rule classes: schema conformance, coverage, consistency, grounding (LLD §4.4). Every issue
carries the `stage` that owns it so the repair router can act.

Two things distinguish a real validator from a decorative one:

**Profile-conditioning.** Required-field rules are selected by `pedagogy_profile`. No rule may
require formulae or numerical items unconditionally. A validator that fails every humanities
document destroys the versatility score that is explicitly graded.

**The negative-path suite.** Write deliberately corrupted TKPs — a concept never taught, a concept
taught twice, a prerequisite inverted, timing that does not sum, a claim its cited span does not
support, a schema violation — and assert each one is caught. A validator that has only ever been
tested on good input is indistinguishable from `return "pass"`.

Grounding must be cheap: lexical pre-filter with two thresholds, LLM judge only on the ambiguous
middle, batched. Assert in a test that the pre-filter keeps the judge off the majority of claims.

---

## M7 · Publishing (Stage 10)

**Owns:** `backend/stages/s10_publishing/**`, `deploy/fonts/**`
**Depends on:** M0 (build entirely against the fixture TKP)

Assemble the TKP, then render Lesson Plan, Teacher Guide, and Assessment Book PDFs plus a Markdown
bundle. One path: Jinja2 → HTML → WeasyPrint → PDF.

Two failure modes to design against from the start:
- **Fonts (H-11).** Embed the Noto family in the image and reference it explicitly in CSS. Write a
  Devanagari render test. A multilingual lesson plan full of tofu boxes is worse than no
  multilingual support.
- **Never let rendering lose the package.** If a PDF fails, mark that artifact `failed` and publish
  the JSON anyway. Ten minutes of successful pipeline work must not be thrown away by a layout bug.
  Test it with a forced failure.

Also yours: `provenance` population (per-stage models, tokens, cost, timings, citations) and the
sample-seeding script whose output becomes `/samples` (DR-06).

---

## M8 · API Layer

**Owns:** `backend/api/**`
**Depends on:** M0, M1

Implement `06-api-spec.md` exactly — status codes, error envelope, rate limits, idempotency.

**The SSE endpoint is the highest-risk surface in this module** (FR-14, H-02). Requirements:
- Every payload contains `stage` and `progress`. Contract-test both keys on every event.
- `Last-Event-ID` replays from the cursor, so a reconnecting client loses nothing. Write an
  integration test that disconnects mid-run, reconnects, and asserts every missed event arrives
  exactly once.
- Heartbeat every 15 s.
- Replaying a finished job returns the full timeline then closes.

The API must not import any stage — it reads the database and enqueues. Also mount the built
frontend as static assets so the whole product is one origin.

---

## M9 · Frontend

**Owns:** `frontend/**`
**Depends on:** M0 (fixture TKP), M8 (OpenAPI spec — build against the spec, not the running server)

Four screens: Upload, Run (live stage timeline), Package (TKP viewer), Samples.

Three things earn disproportionate credit:
- **The evidence popover.** Click a concept, definition, or claim and see its source quote and page.
  This is what makes RAG traceability (BR-02) visible to an evaluator in five seconds instead of
  buried in a JSON field nobody opens.
- **Resumable progress.** Refresh mid-run and the timeline picks up with no gap and no duplicates.
  Use `EventSource` with `Last-Event-ID`. This is the H-02 acceptance test.
- **The validation panel.** Show status, grounding score, and issues honestly. Surfacing warnings
  reads as rigour; hiding them reads as a validator that does nothing.

Design the partial-success state properly: `succeeded_partial` is a success with a caveat, not a
failure. Handle loading, empty, and error states. Responsive at 1280 and 375 px, keyboard-navigable,
visible focus.

---

## M10 · DevOps & Delivery

**Owns:** `deploy/**`, `.github/workflows/**`, `README.md`, `Makefile`, `scripts/**`
**Depends on:** M1

DR-01 — a deployed working prototype — is mandatory and binary. It is also the most common way a
submission like this fails. **Stand the deployment up at MS-1, while the pipeline is still stubs**,
so the deploy path is proven long before it carries anything valuable.

Deliver: a multi-stage Dockerfile (build UI → slim Python runtime with Noto fonts), a
`docker compose up` that works from a clean clone, an entrypoint that migrates then seeds samples
then serves, the live URL, health/readiness/metrics, log aggregation, a retention purge job, and CI
running lint, types, unit, integration, contract, schema-drift, boundary check, and image build.

The README carries DR-03/04/05: setup instructions **verified from a clean clone by someone who did
not write them**, the generated architecture diagram, and the orchestration explanation. Also
document cost and latency per document, and the limitations — an honest limitations section reads as
engineering maturity, not weakness.

Cold start matters (NFR-07): an evaluator opening a sleeping service and getting a timeout is
indistinguishable from a broken submission.

---

## M11 · Eval Harness & Samples

**Owns:** `evals/**`, `samples/**`
**Depends on:** a working pipeline (runs last, but **build the golden set early**)

65 % of the grade is output quality, and quality that is not measured does not improve. This module
is where that gets engineered rather than hoped for.

Assemble ≥ 8 golden documents across ≥ 6 subjects — physics, mathematics, biology, history,
literature, economics — deliberately including one equation-heavy, one purely narrative, one very
short (3 pages), and one very long (40+ pages). Build rubric scoring per dimension: document
intelligence, educational understanding, teaching planning, content quality, assessment alignment.

`run_eval.py` produces a comparable report across runs recording schema version, model config,
scores, cost, and latency — so a prompt change can be judged instead of guessed at.

**Gates you own:** every golden document reaches `pass` or `pass_with_warnings` (NFR-01);
structured-output reliability ≥ 99 % (NFR-04); reproducibility across two runs (NFR-12).

Finally, generate `/samples` from the shipping build with a README recording each source document
and the options used (DR-06), and document at least one prompt-iteration cycle with a measured
before/after score change — that is the evidence that output quality was engineered.
