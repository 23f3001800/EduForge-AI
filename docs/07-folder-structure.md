# EduForge AI — Repository Structure

Layout follows the module boundaries exactly, so each agent owns disjoint directories and merge
conflicts are structurally rare.

```
EduForge-AI/
├── README.md                          # DR-03/04/05: setup, architecture diagram, orchestration
├── docs/                              # this architecture set
├── samples/                           # DR-06 — committed sample outputs
│   ├── physics-newtons-laws.TeacherKnowledgePackage.json
│   ├── history-partition-of-bengal.TeacherKnowledgePackage.json
│   └── README.md                      # how each was generated (doc, options, version)
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                       # migrations (M1 owns 0001; each module adds its own)
│   │   └── versions/
│   │
│   ├── contracts/                     # ── M0 · frozen first, architect-owned ──
│   │   ├── primitives.py              # Evidence, Grounded, enums
│   │   ├── document.py                # StructuredDocument, Block, Chunk
│   │   ├── classification.py
│   │   ├── knowledge.py               # KnowledgeBase, ConceptGraph
│   │   ├── plan.py                    # TeachingPlan, Period
│   │   ├── content.py                 # PeriodContent, Activity
│   │   ├── assessment.py
│   │   ├── gaps.py
│   │   ├── validation.py
│   │   ├── tkp.py                     # TeacherKnowledgePackage (the master artifact)
│   │   ├── jobs.py                    # JobOptions, JobStatus, ProgressEvent
│   │   └── schema/
│   │       └── tkp-1.0.0.json         # generated + committed; CI fails on drift
│   │
│   ├── core/                      # ── cross-cutting, no stage may be imported here ──
│   │   ├── llm/
│   │   │   ├── client.py              # LLMClient: parse, retry, cache, budget, accounting
│   │   │   ├── budget.py
│   │   │   ├── prompts.py             # document_block(), delimiters, injection guard
│   │   │   └── models.py              # config/models.yaml loader
│   │   ├── retrieval/
│   │   │   ├── index.py               # chunk upsert, tsvector, optional embeddings
│   │   │   ├── search.py              # BM25 + dense + RRF
│   │   │   └── embeddings.py          # none | local | api backends
│   │   ├── storage/
│   │   │   ├── db.py                  # engine, session, unit of work
│   │   │   ├── repositories/          # documents, jobs, events, checkpoints, packages
│   │   │   └── blob.py                # local fs | S3-compatible
│   │   ├── progress/
│   │   │   └── emitter.py             # persist-then-notify
│   │   ├── observability/
│   │   │   ├── logging.py             # structlog, job_id/trace_id binding
│   │   │   ├── metrics.py             # Prometheus registry
│   │   │   └── tracing.py             # OpenTelemetry spans
│   │   └── config.py                  # settings, fail-fast validation at boot
│   │
│   ├── stages/                        # ── one package per pipeline stage ──
│   │   ├── base.py                    # Stage protocol, StageContext, stage_span
│   │   ├── s1_document_intelligence/
│   │   │   ├── stage.py
│   │   │   ├── parsers/               # pdf.py, docx.py, pptx.py, text.py
│   │   │   ├── structure.py           # heading/outline detection
│   │   │   ├── equations.py           # detection + LaTeX normalisation
│   │   │   ├── tables.py
│   │   │   └── chunking.py
│   │   ├── s2_classification/
│   │   │   ├── stage.py
│   │   │   ├── prompts.py
│   │   │   └── curriculum/            # CBSE / ICSE / CommonCore standard tables
│   │   ├── s3_knowledge/
│   │   │   ├── stage.py
│   │   │   ├── prompts.py
│   │   │   ├── mapreduce.py
│   │   │   ├── merge.py               # concept dedupe + evidence union
│   │   │   └── concept_graph.py       # DAG build, cycle breaking
│   │   ├── s4_planner/
│   │   │   ├── stage.py
│   │   │   ├── prompts.py
│   │   │   └── sequencing.py          # topo sort, load balancing, period derivation
│   │   ├── s5_classroom_content/
│   │   ├── s6_activities/
│   │   ├── s7_assessments/
│   │   ├── s8_gaps/
│   │   ├── s9_validation/
│   │   │   ├── stage.py
│   │   │   ├── rules/                 # schema.py, coverage.py, consistency.py, grounding.py
│   │   │   └── profiles.py            # pedagogy_profile → active ruleset
│   │   └── s10_publishing/
│   │       ├── stage.py
│   │       ├── assemble.py            # TKP assembly
│   │       └── render/
│   │           ├── html.py            # Jinja2 → HTML
│   │           ├── pdf.py             # WeasyPrint, Noto fonts embedded
│   │           ├── markdown.py
│   │           └── templates/
│   │               ├── lesson_plan.html.j2
│   │               ├── teacher_guide.html.j2
│   │               ├── assessment_book.html.j2
│   │               └── styles.css
│   │
│   ├── pedagogy/                      # profile-driven strategy registry (NFR-01)
│   │   ├── registry.py
│   │   └── profiles/                  # quantitative.yaml, narrative.yaml, ...
│   │
│   ├── orchestration/                 # ── M4 · LangGraph ──
│   │   ├── graph.py                   # nodes, edges, conditional routing
│   │   ├── state.py                   # GraphState + reducers
│   │   ├── checkpointer.py            # backed by stage_outputs
│   │   ├── fanout.py                  # Send builders
│   │   ├── repair.py                  # validation-issue → owning stage router
│   │   └── diagram.py                 # graph → mermaid (feeds the README, DR-04)
│   │
│   ├── worker/
│   │   ├── main.py                    # entrypoint
│   │   ├── queue.py                   # SKIP LOCKED claim + lease heartbeat
│   │   └── runner.py                  # resume logic, budget wiring
│   │
│   ├── api/                           # ── M8 · FastAPI ──
│   │   ├── main.py                    # app factory, static mount, error handlers
│   │   ├── deps.py
│   │   ├── middleware/                # rate limit, request id, access code
│   │   └── routes/
│   │       ├── documents.py
│   │       ├── jobs.py
│   │       ├── events.py              # SSE with Last-Event-ID replay
│   │       ├── packages.py
│   │       ├── samples.py
│   │       └── ops.py
│   │
│   └── tests/
│       ├── unit/                      # mirrors package layout
│       ├── integration/               # DB + API, LLM stubbed
│       ├── contract/                  # schema drift, stage IO conformance
│       ├── e2e/                       # full pipeline against recorded model responses
│       └── fixtures/
│           ├── documents/             # tiny per-format + adversarial + malformed
│           └── llm_cassettes/         # recorded responses for deterministic CI
│
├── frontend/                          # ── M9 · React + Vite + TS ──
│   ├── src/
│   │   ├── api/                       # generated client from openapi.json
│   │   ├── hooks/useJobStream.ts      # EventSource + Last-Event-ID resume
│   │   ├── pages/                     # Upload, Run, Package, Samples
│   │   ├── components/
│   │   │   ├── StageTimeline.tsx
│   │   │   ├── PeriodViewer.tsx
│   │   │   ├── AssessmentViewer.tsx
│   │   │   ├── EvidencePopover.tsx    # click a claim → see its source span (BR-02, visible)
│   │   │   └── ValidationPanel.tsx
│   │   └── styles/
│   └── vite.config.ts
│
├── evals/                             # ── M11 · quality harness ──
│   ├── golden/                        # ≥8 docs across ≥6 subjects
│   ├── rubrics/                       # per-dimension scoring rubrics
│   ├── run_eval.py
│   └── reports/
│
├── config/
│   ├── models.yaml                    # per-stage model + effort + max_tokens
│   └── limits.yaml
│
├── deploy/
│   ├── Dockerfile                     # multi-stage: build UI → python runtime
│   ├── docker-compose.yml             # api + worker + postgres/pgvector, local dev
│   ├── entrypoint.sh                  # migrate → seed samples → start api + worker
│   ├── render.yaml
│   └── fonts/                         # Noto family, embedded for multilingual PDF (H-11)
│
├── scripts/
│   ├── seed_samples.py
│   ├── generate_schema.py             # regenerate contracts/schema/*.json
│   └── export_diagram.py              # orchestration/diagram.py → README
│
├── .github/workflows/ci.yml           # lint, types, tests, schema-drift, boundary check, image
├── .env.example
└── Makefile                           # dev, test, lint, migrate, seed, eval, docker
```

## Boundary enforcement (this is what makes parallel work safe)

A CI check (`import-linter` or equivalent) enforces:

```
contracts      → depends on nothing in-project
core/*     → contracts only
pedagogy       → contracts only
stages/sN_*    → contracts, core, pedagogy         (NEVER another stage)
orchestration  → contracts, core, stages
worker         → contracts, core, orchestration
api            → contracts, core (repositories), NOT stages
```

A pull request that imports `stages.s5_classroom_content` from `stages.s7_assessments` fails CI. That
single rule is what lets eleven agents build simultaneously without coordinating.
