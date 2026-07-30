# EduForge AI — Definition of Done, per Module

A module is **done** when every checkbox passes *and* every requirement ID assigned to it is closed
by a named test or artifact. "It works on my machine" closes nothing.

**Universal DoD** — applies to all twelve modules, in addition to the module-specific list:

- [ ] Public functions are type-annotated; `mypy --strict` clean on the module's packages
- [ ] `ruff` clean; import-boundary check passes (no cross-stage imports)
- [ ] Unit tests ≥ 80 % line coverage on the module's own packages
- [ ] No secret, key, or absolute local path committed
- [ ] All new config keys documented in `.env.example` with a sane default
- [ ] Every error path raises a typed exception from the shared taxonomy, never a bare `Exception`
- [ ] Structured logs carry `job_id` where a job exists
- [ ] Module README section explains the "why", not just the "what"
- [ ] Draft PR opened with the requirement IDs it closes listed in the description

---

## M0 · Contracts & Schema — *blocking*
**Closes:** the vocabulary for every other module.

- [ ] Every model in LLD §1 implemented as Pydantic v2 with field constraints (not bare `str`)
- [ ] `Grounded.evidence` has `min_length=1` — traceability is enforced by the type, not by prose
- [ ] `contracts/schema/tkp-1.0.0.json` generated and committed; `scripts/generate_schema.py` reproduces it byte-for-byte
- [ ] CI job fails on schema drift
- [ ] One complete hand-written fixture TKP validates against the schema
- [ ] Input **and** output fixtures exist for all ten stages
- [ ] `contracts/` imports nothing else in the project (verified by the boundary check)
- [ ] `schema_version` semantics documented

## M1 · Platform Foundation
**Closes:** NFR-11, NFR-12, part of NFR-02, S4, S5.

- [ ] Alembic migration `0001` creates every table in the data model; `upgrade`/`downgrade` both tested
- [ ] Repositories for documents, jobs, events, checkpoints, packages, artifacts — each unit-tested against a real Postgres (testcontainers or a CI service)
- [ ] Blob storage abstraction with local-fs and S3-compatible backends; same interface, both tested
- [ ] `Settings` fails fast at boot with a readable message naming the missing key
- [ ] `structlog` JSON output; secret-redaction filter proven by a test that logs a fake key and asserts it is masked
- [ ] Prometheus registry with the metric names the ops docs reference
- [ ] `ProgressEmitter` persists-then-notifies; a test asserts the event row exists even when `pg_notify` fails
- [ ] `pgvector` + FTS indexes created and exercised

## M2 · Document Intelligence
**Closes:** FR-01, FR-02, NFR-09, H-14, T9, S2.

- [ ] PDF, DOCX, PPTX, TXT/MD all parse to `StructuredDocument`
- [ ] Heading hierarchy and `outline` correct on a nested-heading fixture
- [ ] Tables emitted as `{headers, rows}` — a table fixture asserts cell-level fidelity, not a substring match
- [ ] Equations detected and LaTeX-normalised on a physics fixture; raw text retained as fallback
- [ ] Figure captions and document metadata extracted
- [ ] Chunker never splits a table or equation block; `section_path` correct on every chunk
- [ ] Size, page-count, and parse-timeout caps enforced — each with a fixture returning `422`, never a 500 or a hang
- [ ] Zip-bomb and truncated-PDF fixtures rejected cleanly
- [ ] Macros disabled; no shell-out to external converters
- [ ] Deterministic: same file in → identical `StructuredDocument` out

## M3 · Knowledge Core (S2 + S3 + Retrieval + Pedagogy Registry)
**Closes:** FR-03, FR-04, BR-02, BR-03, NFR-01, NFR-05, H-05, H-06, H-07, H-09, Q1, Q2, Q8.

- [ ] All seven classification fields plus per-field confidences; `low_confidence_fields` populated below 0.5
- [ ] `pedagogy_profile` emitted; **a physics fixture and a poetry fixture receive different profiles**
- [ ] Curriculum alignment returns mapped standards or `null` — never a fabricated standard code (asserted by test)
- [ ] All nine knowledge lists extracted with correct types
- [ ] **100 % of groundable items carry ≥ 1 evidence span**, and every `chunk_id` resolves to a real chunk (test asserts both)
- [ ] Learning objectives carry Bloom levels and are phrased as observable behaviours
- [ ] `concept_graph` prerequisite subgraph is acyclic; a cyclic-input test proves the cycle-breaker works and records a warning
- [ ] Map-reduce triggers above the single-call budget; merge dedupes concepts and unions evidence (tested on a long fixture)
- [ ] Hybrid retrieval returns sane results with `EMBEDDINGS=none` **and** with embeddings enabled
- [ ] Pedagogy registry loads all five profiles and exposes prompt fragments, activity weights, assessment mix, and validation ruleset
- [ ] Stage validates its own output before returning (H-04)

## M4 · Orchestration (LangGraph + Worker + LLMClient)
**Closes:** BR-01, BR-04, NFR-02, NFR-04, NFR-06, NFR-08, H-01, H-03, H-10, T1, T3–T5, T7, S1.

- [ ] Graph compiles with all ten nodes and the conditional validation/repair edges
- [ ] `Send`-based fan-out over periods; reducer merges out-of-order results sorted by `period_no`
- [ ] Checkpointer backed by `stage_outputs`; **kill the worker mid-run, restart, job resumes at the first incomplete stage and completed stages are not re-billed** (integration test)
- [ ] Repair router maps validation issues to owning stages; ≤ 2 cycles, then publishes with warnings
- [ ] `LLMClient.parse()` returns typed models; a malformed-response test proves the one repair attempt, and a twice-malformed test proves the degraded fallback
- [ ] `stop_reason == "refusal"` handled — stage degrades, job continues, refusal recorded
- [ ] Retry with backoff+jitter on 429/5xx; ≤ 4 attempts (test with a stubbed failing transport)
- [ ] Concurrency semaphore enforced (test asserts max in-flight)
- [ ] Token budget enforced pre-call; exhaustion yields `succeeded_partial` with a publishable package
- [ ] **Prompt caching verified**: a test asserts `cache_read_input_tokens > 0` on the second stage of a run
- [ ] Every model call writes an `llm_calls` row with tokens, cost, latency, outcome
- [ ] Document content passes through the injection-guard helper on every stage (test asserts the delimiter wrapper is present)
- [ ] Queue claim uses `SKIP LOCKED` + lease; a two-worker test proves no double-execution
- [ ] Progress weights sum to 100; emitted `stage` strings match the LLD table exactly
- [ ] `orchestration/diagram.py` emits the mermaid graph used in the README

## M5 · Pedagogy Generation (S4–S8)
**Closes:** FR-05…FR-09, NFR-01, H-07, H-08, Q3–Q6.

- [ ] **Period count derived**, not hardcoded — a 3-page fixture and a 40-page fixture produce different counts, both in `[1,20]`
- [ ] Every concept assigned to exactly one period; ordering consistent with a topological sort (test on a DAG fixture)
- [ ] Every objective mapped to ≥ 1 period, or listed in `unmapped_objective_ids`
- [ ] `time_allocation` sums to the period duration ± 5 %
- [ ] All eight per-period artifacts present for every period
- [ ] `mentor_moment` flagged `grounded: false` so validation does not penalise it
- [ ] ≥ 3 distinct activity types on a 5-period package; every activity has duration, materials, teacher instructions, success criteria, and differentiation
- [ ] Activity type weights differ by `pedagogy_profile` (test compares a narrative vs a quantitative fixture)
- [ ] Assessments cover all four kinds where the profile calls for them; **a narrative fixture produces zero numerical items and does not error**
- [ ] Every MCQ has exactly 4 options and exactly one correct
- [ ] Every non-MCQ item has a rubric; every item has answer, marks, Bloom level, concept ids
- [ ] Learning gaps carry severity, ≥ 1 diagnostic question, and ≥ 1 remediation step
- [ ] Each stage validates its own output before returning
- [ ] `output_language` honoured: values translated, JSON keys English

## M6 · Validation Engine (S9)
**Closes:** FR-10, NFR-05, H-04, H-06, H-07, H-09, Q2, Q3, Q7, S1.

- [ ] Schema conformance check against the published JSON Schema
- [ ] Coverage: every concept taught, every objective planned and assessed
- [ ] Consistency: duplicate-concept, prerequisite-violation, timing, and dangling-`activity_ref` checks
- [ ] Grounding: lexical pre-filter + batched LLM judge; `grounding_score` and `unsupported_claims` produced
- [ ] **Profile-conditioned rules**: no rule requires formulae or numerical items unconditionally — proven by a narrative fixture reaching `pass`
- [ ] **Negative-path suite**: a deliberately corrupted TKP trips each rule class (missing concept coverage, duplicated concept, prerequisite inversion, bad timing, unsupported claim, schema violation) — this is the test that proves validation is not theatre
- [ ] Every issue carries a `stage` owner so the repair router can act on it
- [ ] Status resolution `pass | pass_with_warnings | fail` matches the documented rules
- [ ] Judge calls are batched and bounded; a cost test asserts the pre-filter keeps the judge off the majority of claims

## M7 · Publishing (S10)
**Closes:** FR-11, FR-12, DR-06, BR-06, H-11, H-12, T8.

- [ ] `TeacherKnowledgePackage.json` assembled and validates against the schema
- [ ] Lesson Plan, Teacher Guide, and Assessment Book PDFs render from the fixture TKP
- [ ] Equations render correctly in PDF; tables render as tables
- [ ] **Devanagari (or equivalent non-Latin) render test passes with embedded Noto fonts** — no tofu boxes
- [ ] Markdown bundle produced
- [ ] A forced render failure marks that artifact `failed` and **still publishes the JSON package** (test)
- [ ] Artifacts persisted with correct MIME, byte count, and a resolvable URI
- [ ] `provenance` populated: per-stage model ids, tokens, cost, timings, citation list
- [ ] Sample seeding script produces `/samples/*.json` identical to live output

## M8 · API Layer
**Closes:** FR-14, FR-15, NFR-03, NFR-07, NFR-08, H-02, H-15, T2, S3.

- [ ] Every endpoint in the API spec implemented with the documented status codes and error envelope
- [ ] Upload: MIME sniffing, caps, SHA-256 dedupe returning the existing id
- [ ] `POST /jobs` honours `Idempotency-Key` for 24 h (test asserts a repeat returns the same `job_id`)
- [ ] **SSE payloads always contain `stage` and `progress`** — contract test asserts both keys on every event
- [ ] **`Last-Event-ID` replay works**: disconnect mid-run, reconnect, receive every missed event exactly once (integration test)
- [ ] Heartbeat comment every 15 s
- [ ] Replaying a *finished* job returns the full timeline then closes
- [ ] Terminal `completed` / `failed` events close the stream
- [ ] Cancel and retry behave as specified; retry does not re-run completed stages
- [ ] Rate limiting per IP with `Retry-After`; global concurrent-job cap
- [ ] `/healthz`, `/readyz`, `/metrics` correct — `/readyz` fails loudly when migrations are behind
- [ ] Static frontend build mounted and served from the same origin
- [ ] Generated `openapi.json` matches the API spec document

## M9 · Frontend
**Closes:** FR-13, DR-01 (usability), H-02, H-12, BR-02 (visible traceability).

- [ ] Upload with drag-drop, client-side size/type pre-check, and clear error surfaces
- [ ] Stage timeline showing all ten stages with live progress
- [ ] **Refresh mid-run resumes progress with no gap or duplication** (this is the H-02 acceptance test, run manually and scripted)
- [ ] TKP viewer: classification, knowledge, per-period content, activities, assessments, gaps
- [ ] **Evidence popover** — clicking a concept/definition/claim shows its source quote and page. This is what makes BR-02 visible to an evaluator instead of buried in JSON.
- [ ] Validation panel showing status, grounding score, and issues — warnings are shown, not hidden
- [ ] Samples gallery loading from `/samples` with zero model calls
- [ ] All artifacts downloadable
- [ ] Responsive at 1280 and 375 px; keyboard-navigable; visible focus states; images and controls labelled
- [ ] Loading, empty, error, and partial-success states designed — `succeeded_partial` reads as success-with-caveat, not failure
- [ ] No secret or API key in the bundle

## M10 · DevOps & Delivery
**Closes:** DR-01…DR-05, BR-05, NFR-07, NFR-11, D1, S4, S5.

- [ ] Multi-stage Dockerfile: builds the UI, then a slim Python runtime with Noto fonts installed
- [ ] `docker compose up` gives a working local stack (api + worker + postgres/pgvector) from a clean clone
- [ ] Entrypoint runs migrations then seeds samples before serving
- [ ] **Live URL deployed and reachable** — a stranger with the link can upload and get a package
- [ ] Cold start to first byte ≤ 5 s; samples render on a cold container
- [ ] Worker restart mid-job resumes correctly on the deployed environment, not just locally
- [ ] CI: lint, types, unit, integration, contract, schema-drift, boundary check, image build
- [ ] Metrics exposed; log aggregation reachable; a runbook for the three most likely failures
- [ ] Retention purge job scheduled and tested
- [ ] **README complete**: setup instructions verified from a clean clone by someone who did not write them, architecture diagram (generated), orchestration explanation, cost/latency notes, limitations

## M11 · Eval Harness & Samples
**Closes:** NFR-01, NFR-04, NFR-06, NFR-12, DR-06, Q4.

- [ ] Golden set of ≥ 8 documents spanning ≥ 6 subjects, including at least one equation-heavy, one purely narrative, one very short, and one very long document
- [ ] Rubric scoring per dimension: document intelligence, educational understanding, teaching planning, content quality, assessment alignment
- [ ] `run_eval.py` produces a comparable report across runs (schema version, model config, scores, cost, latency)
- [ ] **Every golden document reaches `pass` or `pass_with_warnings`** — this is the NFR-01 gate
- [ ] Structured-output reliability measured ≥ 99 % across the golden set (NFR-04)
- [ ] Median and p95 cost and wall-clock per document reported
- [ ] Reproducibility check: two runs of the same document produce the same period count and concept set (NFR-12)
- [ ] ≥ 2 sample TKPs committed to `/samples`, regenerated from the shipping build, with a README recording the source document and options used
- [ ] At least one documented prompt-iteration cycle showing a measured before/after score change — evidence that quality was engineered, not assumed

---

## Release gate

The project ships when: **all twelve module DoDs pass**, MS-8 is green, and the SRS §7 acceptance
criteria are demonstrated end-to-end on the deployed URL — by someone other than the author.
