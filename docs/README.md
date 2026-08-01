# EduForge AI — Architecture Set

Source of truth: `../Task Intern-2.pdf` ("AI Engineer Assignment: Teacher AI
Platform"), plus the follow-up clarifications in `../FAQ.md`.

**Status: built and deployed.** All ten stages are implemented and wired; the
system runs at <https://eduforge-ai.azurewebsites.net>. Start at
[`../README.md`](../README.md) for what it does and how to run it — these
documents are the design behind it.

Where a document and the code disagree, **the code is right**. Some of these were
written before implementation and record intent rather than outcome; the ones
that were revised by contact with reality say so.

| # | Document | What it answers |
|---|----------|-----------------|
| [00](00-requirements-trace.md) | Requirements Trace | Every explicit requirement, plus 15 hidden requirements and edge cases the PDF does not state |
| [01](01-srs.md) | SRS | Functional + non-functional requirements, constraints, acceptance criteria |
| [02](02-hld.md) | HLD | System architecture, flows, failure model, security, deployment, ADRs |
| [03](03-lld.md) | LLD | Contracts, LLMClient, stage interface, algorithms, queue, config |
| [04](04-data-model.md) | Data Model | ER diagram, full DDL, hybrid retrieval query, retention |
| [05](05-agent-graph.md) | LangGraph Agent Graph | Topology, agent roster, state, fan-out, repair routing, checkpointing |
| [06](06-api-spec.md) | API Spec | Every endpoint, the SSE contract, conventions |
| [07](07-folder-structure.md) | Folder Structure | Repository layout + the import-boundary rule that enables parallel work |
| [08](08-roadmap.md) | Roadmap | 12 modules, 9 milestones, 5 execution waves, ordered cut list |
| [09](09-risks.md) | Risk Analysis | Scored risks with mitigations traced to design decisions |
| [10](10-definition-of-done.md) | Definition of Done | Per-module DoD, each closing named requirement IDs |
| [11](11-module-briefs.md) | Module Briefs | Ready-to-issue prompts, one per agent |
| [12](12-deployment.md) | Deployment (generic) | Container image, CI, and a platform-agnostic deploy |
| [13](13-azure-deployment.md) | Azure Deployment | What actually runs, and why App Service over Container Apps |
| [14](14-design-system.md) | Design System | Tokens, breakpoints, component specs, UI states, error copy |

## The five decisions that shape everything else

1. **Modular monolith with hard internal boundaries**, not ten deployed services — 85 % of the grade
   is output quality, and the mandatory live prototype is the real delivery risk.
2. **Mandatory evidence spans from Stage 3.** Hallucination detection (FR-10) and RAG traceability
   (BR-02) become one subsystem instead of two half-built ones.
3. **`pedagogy_profile` routing.** The only scalable answer to the explicitly graded versatility
   criterion; no subject name appears anywhere in code.
4. **Durable jobs + persisted event log with SSE replay.** The pipeline outlives the HTTP request,
   the browser refresh, and the worker restart.
5. **Contracts frozen first (M0).** The one serialization point that buys parallel work for eleven
   agents afterwards.

## Reading order

- **New to the project:** [`../README.md`](../README.md) → 00 → 02 → 05.
- **Evaluating it:** [`../README.md`](../README.md) → [`../samples/`](../samples/)
  → 00 (requirements trace) → the live URL.
- **Changing the code:** 03 (LLD) → 07 (boundaries) → the stage's own module
  docstring, which is where the reasoning that survived implementation lives.
- **Deploying it:** 13.

## What changed after implementation

Kept honest here because a design set that never records being wrong is not worth
reading:

- **`backend/platform/` became `backend/core/`** — the original name shadowed the
  standard library's `platform` module.
- **Stage 3 was split** into core and pedagogical extraction. One schema covering
  the whole knowledge base was wide enough that a small model returned an empty
  generation rather than failing cleanly.
- **Stage 9's grounding pre-filter was made one-directional.** It had been
  resolving claims as *unsupported* without a model call whenever lexical overlap
  was low — but low overlap means paraphrase, not fabrication, and four of seven
  claims in the reference package were being reported as hallucinations that
  nothing had read.
- **Curriculum boards became a composition mechanism**, not a label: a board
  multiplies the pedagogy profile's assessment mix rather than overriding it.
