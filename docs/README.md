# EduForge AI — Architecture Set

Source of truth: `../Task Intern-2.pdf` ("AI Engineer Assignment: Teacher AI Platform").
Status: **proposed, pending approval.** No production code until approved.

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

New to the project: 00 → 02 → 05 → 08.
About to implement: 11 (your brief) → 03 → 10 (your DoD).
