# EduForge AI — Risk Analysis

Scored `Likelihood × Impact` on 1–5. **Exposure ≥ 12 = must be mitigated in v1 architecture, not
deferred.** Every high-exposure row already has a corresponding design decision in the HLD/LLD —
that is the point of this document.

---

## 1. Delivery risks

| # | Risk | L | I | Exp | Mitigation | Owner |
|---|------|---|---|-----|-----------|-------|
| D1 | **The live deployment breaks or sleeps when the evaluator opens it.** DR-01 is mandatory and binary. | 4 | 5 | **20** | Deploy at MS-1 with stubs, weeks before real content. Single container, single origin (no CORS/env drift). Keep-alive ping. `/samples` renders on a cold container with zero model calls. Health + readiness endpoints. | M10 |
| D2 | **Contract churn after parallel work starts** — one field rename cascades into eleven rebases. | 4 | 4 | **16** | MS-0 contract freeze is a hard gate. Committed JSON Schema with CI drift check. Additive-only changes after freeze; breaking changes require a version bump and an architect sign-off. | M0 |
| D3 | Scope sprawl — six bonus tracks plus ten stages. | 3 | 4 | 12 | Explicit ordered cut list in the roadmap. Bonuses are severable by construction (embeddings pluggable, curriculum optional, language a parameter). | Architect |
| D4 | Integration big-bang at the end. | 3 | 5 | 15 | Walking skeleton at MS-1; every module replaces a stub inside an already-working pipeline rather than being integrated at the end. | M4 |
| D5 | Agents duplicate or collide on shared files. | 3 | 3 | 9 | Disjoint directory ownership in the folder structure; import-boundary lint; one owner per migration file. | Architect |

## 2. Technical risks

| # | Risk | L | I | Exp | Mitigation | Owner |
|---|------|---|---|-----|-----------|-------|
| T1 | **Long-running job exceeds request/platform timeouts** (H-01). | 5 | 5 | **25** | Background worker + durable job row; API only enqueues. `202` + SSE. Nothing about correctness depends on an HTTP connection staying open. | M4, M8 |
| T2 | **Progress lost on browser refresh** (H-02) — looks broken to an evaluator even though the job is fine. | 4 | 4 | **16** | Persisted `job_events` with monotonic `seq`; SSE honours `Last-Event-ID` and replays. A finished job replays its whole timeline. | M8 |
| T3 | **Structured-output drift** — a stage returns unparseable or schema-invalid JSON. | 4 | 4 | **16** | `messages.parse()` with Pydantic output models; one schema-error-feedback repair; deterministic degraded object as the floor. Per-stage validation (H-04) so one bad stage cannot poison six downstream ones. | M4 |
| T4 | **Rate limits / 429 storms** during per-period fan-out (H-10). | 4 | 3 | 12 | Single concurrency semaphore in `LLMClient` (not in the graph). Exponential backoff + jitter, ≤ 4 attempts. Serialised S6→S7→S8 to keep the burst profile flat. | M4 |
| T5 | **Cost blowout** — 60–120 calls per document with no ceiling. | 3 | 4 | 12 | Per-job token budget checked before every call; `BudgetExhausted` publishes a partial package rather than running unbounded. Prompt caching on the shared document prefix. Per-call cost recorded in `llm_calls`. | M4 |
| T6 | **Context-window overflow on long documents** (H-05). | 4 | 4 | **16** | Structure-aware chunking; map-reduce extraction with dedup merge; retrieval-scoped stage prompts. | M2, M3 |
| T7 | Worker crash loses ten minutes of work (H-03). | 3 | 4 | 12 | Per-stage checkpoints in `stage_outputs`; lease-based reclaim; retry resumes at the first incomplete stage without re-billing. | M4 |
| T8 | **Multilingual PDFs render as black boxes** (H-11). | 3 | 4 | 12 | WeasyPrint with Noto fonts explicitly embedded in the image; a Devanagari render test in CI. JSON keys stay English. | M7 |
| T9 | Equation/table structure destroyed by naive PDF text extraction (H-14). | 4 | 3 | 12 | Typed blocks with LaTeX normalisation and structured table rows; per-format fixtures with structure assertions. | M2 |
| T10 | Memory ceiling on a small host (embedding model + PDF rendering). | 3 | 3 | 9 | `EMBEDDINGS=none` degrades to BM25 with no call-site change; render streamed to disk, not held in memory; documented instance sizing. | M10 |
| T11 | Concept DAG contains cycles, breaking topological ordering. | 3 | 3 | 9 | Cycle detection with lowest-confidence-edge breaking, recorded as a validation warning rather than a crash. | M3 |
| T12 | Postgres job queue starves or double-runs a job. | 2 | 4 | 8 | `FOR UPDATE SKIP LOCKED` + lease with heartbeat; unique `(job_id, stage)` checkpoint constraint makes double execution idempotent anyway. | M4 |

## 3. AI-quality risks — the ones that actually move the grade

| # | Risk | L | I | Exp | Mitigation | Owner |
|---|------|---|---|-----|-----------|-------|
| Q1 | **The system is implicitly STEM-shaped and collapses on humanities** — explicitly graded in §6 (H-07). | 4 | 5 | **20** | `pedagogy_profile` from S2 routes prompts, activity weights, assessment mix, **and** the validation ruleset. No subject names in code. Golden set spans ≥ 6 subjects and is a release gate (MS-8). | M3, M5, M6, M11 |
| Q2 | **Hallucinated concepts, definitions, or applications** presented with confidence. | 4 | 5 | **20** | Mandatory `evidence` spans from S3 (contract-enforced, not convention). S9 grounding check with lexical pre-filter + LLM judge. `grounding_score` and `unsupported_claims` surfaced in the UI, not hidden. | M3, M6 |
| Q3 | **Incoherent multi-period sequencing** — concepts taught before prerequisites, or twice (H-09). | 4 | 4 | **16** | Concept DAG from S3; deterministic topological ordering in S4 (the model titles and narrates bands, it does not reorder them); S9 checks duplicates and prerequisite violations concretely. | M3, M5, M6 |
| Q4 | Generic, low-value lesson content that is technically valid and pedagogically useless. | 3 | 5 | 15 | Rubric-scored eval harness (M11) on lesson quality, activity diversity, assessment alignment — prompt iteration is driven by measured scores, not vibes. Per-period narrowed context keeps content specific. | M11, M5 |
| Q5 | Period count hardcoded to 5, absurd on short or very long documents (H-08). | 3 | 4 | 12 | Derived from concept load and period duration, bounded `[1,20]`; eval fixtures deliberately include a 3-page handout and a 40-page chapter. | M5 |
| Q6 | Assessment answer keys that are wrong, or MCQs with multiple correct options. | 3 | 4 | 12 | Schema constraint: exactly one correct MCQ option. S9 rule: every item has an answer, marks, and (non-MCQ) a rubric. Distractors linked to misconception ids where possible. | M5, M6 |
| Q7 | Validation is theatre — always returns `pass`. | 3 | 4 | 12 | Negative-path tests: deliberately corrupted TKPs must trip each rule class. Validation status is displayed prominently in the UI, so a permanently-green validator would be visibly implausible. | M6 |
| Q8 | Classification confidently wrong on ambiguous documents. | 3 | 3 | 9 | Per-field confidences; `low_confidence_fields` surfaced in the UI rather than silently propagated. | M3 |

## 4. Security & safety risks

| # | Risk | L | I | Exp | Mitigation | Owner |
|---|------|---|---|-----|-----------|-------|
| S1 | **Prompt injection via uploaded document** (H-13) — document text reaches every prompt. | 3 | 4 | 12 | Content wrapped in `<document_content>` delimiters with an explicit data-not-instruction system statement; no model output may trigger a side effect beyond writing its own validated field; adversarial fixture in CI. | M4, M6 |
| S2 | Malicious upload — zip bomb, malformed PDF, macro-bearing DOCX (NFR-09). | 3 | 4 | 12 | MIME sniffing, size/page caps, parse timeout, macros disabled, no shell-out to external converters. Malformed fixtures in CI. | M2 |
| S3 | Public demo abused for free inference. | 3 | 3 | 9 | Per-IP rate limits, global concurrent-job cap, optional `DEMO_ACCESS_CODE`, per-job token budget. | M8, M10 |
| S4 | API key leakage via logs or error responses. | 2 | 5 | 10 | Key read from env only; redaction filter in the logger; error envelope never echoes config; secret-scanning in CI. | M10 |
| S5 | Uploaded documents contain PII and are retained indefinitely. | 3 | 3 | 9 | 30-day retention with a daily purge job; documented in the README; samples exempt via flag. | M1, M10 |

---

## 5. Top five, and where they are answered

| Risk | Exposure | Answered by |
|---|---|---|
| T1 — job outlives the request | 25 | Worker + durable job + SSE (HLD §3, LLD §5) |
| D1 — dead deployment on demo day | 20 | Deploy at MS-1; samples with zero model calls (Roadmap §4) |
| Q1 — humanities collapse | 20 | `pedagogy_profile` routing (HLD §6) |
| Q2 — hallucination | 20 | Mandatory evidence + grounding check (LLD §4.4) |
| D2 — contract churn | 16 | MS-0 freeze + schema drift CI (Roadmap MS-0) |

## 6. Accepted risks (deliberately not mitigated in v1)

- **No per-teacher authentication.** Out of scope; rate limits and unguessable IDs are the control.
- **Single-region, single-instance deployment.** No HA target for an evaluation prototype.
- **No human-in-the-loop content review.** Validation is automated; the UI surfaces warnings so a
  teacher can judge before using the material.
- **Model-provider outage has no fallback provider.** Retries cover transient failures; a sustained
  outage fails the job with a clear message. A cross-provider abstraction would cost more than it is
  worth here and would give up structured outputs and prompt caching.
