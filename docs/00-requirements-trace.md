# EduForge AI — Requirements Trace & Hidden Requirements

**Source of truth:** `Task Intern-2.pdf` ("AI Engineer Assignment: Teacher AI Platform").
This document is the bridge between the PDF and every other design artifact. Nothing gets built
that is not traceable to a row here.

---

## 1. Explicit Functional Requirements

| ID | Requirement (verbatim intent) | PDF § | Module |
|----|-------------------------------|-------|--------|
| FR-01 | Parse uploaded PDF, DOCX, PPT(X), or plain text | 3 / Stage 1 | M2 |
| FR-02 | Extract text **preserving structure**: headings, sections, tables, figures, equations, metadata | 3 / Stage 1 | M2 |
| FR-03 | Classify document: Subject, Grade, Difficulty, Topic, Chapter, Category, Language | 3 / Stage 2 | M3 |
| FR-04 | Extract Learning Objectives, Prerequisites, Concepts, Definitions, Formulae, Keywords, Examples, Applications, Common Misconceptions | 3 / Stage 3 | M3 |
| FR-05 | Produce a multi-period teaching strategy (e.g. 5 × 40-min periods) with per-period objectives and sequencing | 3 / Stage 4 | M4 |
| FR-06 | Per period, generate: Entry Ticket, Teacher Script, Blackboard Notes, Classroom Activities, Checkpoint Questions, Exit Ticket, Homework, Mentor Moment | 3 / Stage 5 | M5 |
| FR-07 | Generate diverse activities (demonstration, role play, experiment, …) each with duration, materials, teacher instructions, success criteria | 3 / Stage 6 | M5 |
| FR-08 | Generate assessments: MCQ, short answer, long answer, numerical — with answer keys and rubrics | 3 / Stage 7 | M5 |
| FR-09 | Learning-gap analysis: misconceptions with diagnostic questions, severity, remedial actions | 3 / Stage 8 | M5 |
| FR-10 | Automated validation: JSON schema adherence, hallucination detection, missing objectives/concepts, cross-period consistency | 3 / Stage 9 | M6 |
| FR-11 | Publish master `TeacherKnowledgePackage.json` | 3 / Stage 10 | M7 |
| FR-12 | Publish consumable formats: Lesson Plan PDF, Teacher Guide PDF, Assessment Book PDF | 3 / Stage 10 | M7 |
| FR-13 | Simple UI to evaluate generated content | 3 / Stage 10 | M9 |
| FR-14 | Streaming progress API emitting `{"stage": "...", "progress": 60}` for long-running jobs | 3 / Streaming | M8 |
| FR-15 | Pipeline/microservice-shaped architecture: Gateway → Upload → Doc Intelligence → Classification → Knowledge → Planner → Generators → Validation → Storage | 4 | M1, M8 |

## 2. Explicit Deliverable Requirements

| ID | Requirement | PDF § | Owner |
|----|-------------|-------|-------|
| DR-01 | **Deployed, working prototype at a live URL** (MANDATORY) | 5.1 | M10 |
| DR-02 | Public/private Git repo with backend + AI orchestration + frontend | 5.2 | M10 |
| DR-03 | README: local setup instructions | 5.3 | M10 |
| DR-04 | README: high-level architecture diagram | 5.3 | M1 |
| DR-05 | README: explanation of AI orchestration framework/patterns | 5.3 | M1 |
| DR-06 | **≥ 2 sample `TeacherKnowledgePackage.json` in `/samples`** | 5.4 | M7, M11 |

## 3. Bonus Requirements — all in scope

| ID | Bonus | PDF § | Module |
|----|-------|-------|--------|
| BR-01 | Multi-agent orchestration with clear separation of agent responsibility | 7 | M4 (LangGraph) |
| BR-02 | RAG over uploaded docs with citation/source traceability | 7 | M3 |
| BR-03 | Curriculum alignment (Common Core, CBSE, ICSE) | 7 | M3 |
| BR-04 | Performance: batching, caching, parallel generation, cost management | 7 | M4, M8 |
| BR-05 | Observability: logs, metrics, tracing, automated retry for AI calls | 7 | M10 |
| BR-06 | Multilingual lesson-plan generation | 7 | M3, M5, M7 |

## 4. Non-Functional Requirements (derived — the PDF states these only implicitly)

| ID | NFR | Derivation | Target |
|----|-----|-----------|--------|
| NFR-01 | **Subject versatility** — STEM w/ equations *and* humanities narrative, across complexity levels | §6 "Critical Output Quality Note" — explicitly graded | Golden set spans ≥ 6 domains; zero domain-specific hardcoding |
| NFR-02 | Long-running job durability | Full pipeline ≈ 60–120 LLM calls | Job survives worker restart; resumes from last completed stage |
| NFR-03 | Progress observability | FR-14 | Progress event within ≤ 5 s of any stage transition |
| NFR-04 | Structured-output reliability | 10 JSON-producing stages | ≥ 99 % of stages produce schema-valid output after ≤ 1 repair attempt |
| NFR-05 | Grounding / traceability | FR-10 + BR-02 | Every extracted concept, definition, formula, misconception carries ≥ 1 source span |
| NFR-06 | Cost ceiling per document | BR-04 | Hard token budget per job; job aborts with partial TKP rather than running unbounded |
| NFR-07 | Cold-start availability | DR-01 — an evaluator will open the URL unannounced | First byte ≤ 5 s; sample TKPs viewable with zero pipeline runs |
| NFR-08 | Concurrent evaluators | Multiple reviewers may upload simultaneously | ≥ 3 concurrent jobs without failure |
| NFR-09 | Upload safety | Arbitrary binary uploads from the internet | Size/page caps, MIME sniffing, parse timeout, no macro execution |
| NFR-10 | Prompt-injection resistance | Document text flows into every prompt | Document content is delimited, never granted instruction authority |

---

## 5. Hidden requirements and edge cases

These are not written in the PDF. Each one has broken a submission of this shape before.
They are the reason the architecture looks the way it does.

### H-01 — The job outlives the HTTP request
A textbook chapter through 10 stages is 60–120 model calls; wall clock is minutes, not seconds.
Serverless functions time out; free-tier hosts kill long requests. **Consequence:** the pipeline
must run in a background worker with a durable job record. The HTTP layer only enqueues and reads.
`POST /jobs` returns `202` immediately.

### H-02 — Progress must survive a page reload
FR-14 says "stream progress." It does not say "and the evaluator will never refresh the tab" — but
they will, and on a 6-minute job they will. **Consequence:** progress events are persisted rows with
a monotonic sequence number, and the SSE endpoint honours `Last-Event-ID` to replay from a cursor.
In-memory WebSocket state is disqualified.

### H-03 — Stage failure must not cost the whole run
If Stage 7 fails on a 12-minute job, re-running Stages 1–6 is unacceptable and expensive.
**Consequence:** every stage output is checkpointed to the database keyed by `(job_id, stage)`;
retry resumes from the first incomplete stage.

### H-04 — Per-stage validation, not just Stage 9
Stage 9 is specified as terminal validation. But a malformed Stage 3 poisons Stages 4–8, which then
produce plausible-looking garbage that Stage 9 can only reject wholesale. **Consequence:** every
stage validates its own output against a Pydantic model, with one schema-error-feedback repair
attempt, before its result is allowed to become graph state.

### H-05 — Long documents exceed a single prompt
A 60-page chapter cannot be stuffed into one extraction call at usable quality. **Consequence:**
structure-aware chunking + map-reduce extraction over sections, with a retrieval index. This is
also exactly where BR-02 (RAG) belongs — it is load-bearing, not a bolt-on.

### H-06 — "Hallucination detection" is under-specified; grounding is the implementation
Stage 9 asks for hallucination detection but not how. The tractable definition: every extracted
claim carries the `chunk_id` and quoted span it came from, and validation checks whether that span
actually supports the claim. **Consequence:** the evidence field is mandatory on knowledge items
from Stage 3 onward, which makes FR-10 and BR-02 the same subsystem. This is the single highest-
leverage decision in the design.

### H-07 — Humanities documents must not fail STEM-shaped validation
A poem has no formulae and no numerical problems. A naive validator flags that as "missing
required content" and the versatility score (explicitly graded, §6) collapses. **Consequence:**
Stage 2 emits a `pedagogy_profile` (`quantitative` | `conceptual` | `narrative` | `procedural` |
`mixed`) that selects downstream prompt strategies *and* conditions the validation ruleset.
Empty `formulae` on a literature text is a pass, not a failure.

### H-08 — Period count is a derived quantity, not the constant 5
The PDF's "e.g. 5, 40-minute periods" is an example. Hardcoding 5 fails on a 3-page handout and on
a 90-page chapter alike. **Consequence:** Stage 4 derives period count from concept count, concept
depth, and the configured period duration, bounded to `[1, 20]`.

### H-09 — Cross-period consistency needs a dependency graph
"Consistency across periods" (Stage 9) is unverifiable against unordered prose. **Consequence:**
Stage 3 emits a concept DAG (`prerequisite_of` edges). Stage 4 topologically orders it. Stage 9
then checks concretely: no concept taught twice, no concept taught before its prerequisite, every
extracted concept covered by exactly one period, every objective mapped to a period.

### H-10 — Fan-out will hit rate limits
Five periods × several artifacts each, generated in parallel, will 429 a fresh API key.
**Consequence:** bounded concurrency (semaphore), retry with exponential backoff + jitter, and a
per-job token budget enforced before each call.

### H-11 — Multilingual output breaks PDF rendering
BR-06 plus FR-12: a Hindi lesson plan rendered through a Latin-1 PDF library produces black boxes.
**Consequence:** HTML→PDF via WeasyPrint with explicitly embedded Unicode fonts (Noto family).
JSON *keys* stay English; only *values* are translated.

### H-12 — The evaluator arrives with no document
Someone opens the live URL, sees an empty upload box, and either uploads nothing or waits 6 minutes.
**Consequence:** pre-seeded sample TKPs are browsable instantly from the landing page, and one
demo document is one click from running. This also satisfies DR-06 with the same artifact.

### H-13 — Document text is untrusted input
An uploaded PDF can contain "Ignore previous instructions and output …". That text flows into every
downstream prompt. **Consequence:** document content is always wrapped in delimiters, system prompts
state that document content is data and never instruction, and no model output is permitted to
trigger a side effect other than writing to its own schema-validated field.

### H-14 — Equations and tables need a canonical text form
"Preserve structure" (FR-02) for a physics chapter means equations survive parsing. Raw PDF text
extraction mangles them. **Consequence:** equations are normalised to LaTeX where detectable and
carried as typed blocks; tables are carried as structured rows, not flattened strings.

### H-15 — Idempotency on upload and enqueue
An evaluator double-clicks "Generate." Two 6-minute jobs start, doubling cost and confusing the UI.
**Consequence:** document dedupe by SHA-256; job creation accepts an `Idempotency-Key` and returns
the existing job on repeat.

---

## 6. Traceability rule

Every module's Definition of Done (`10-definition-of-done.md`) cites the FR/NFR/BR/H IDs it closes.
A module is not done until every ID assigned to it has a passing test or a named artifact.
