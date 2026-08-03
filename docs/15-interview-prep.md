# EduForge AI — Interview Prep

A beginner-friendly answer sheet for the questions people ask about this project.

**How to use this.** Each answer has a **short version** (what you say out loud, 20–40
seconds) and a **deeper version** (what you say when they follow up). Where the honest
answer is "we didn't build that", it says so — and explains why that's a *better* answer
than bluffing. Interviewers can tell when you're guessing; they can't tell when you're
being precise, but they always notice when you're honest about a limit.

**The single most important rule for this project:** we do **not** have a vector database
or embedding-based retrieval. `EMBEDDINGS=none`. Several questions below assume RAG. Do
not pretend. The real answer — "we built traceability without vector retrieval, here's
why, and here's exactly when I'd add it" — is stronger than a fake one, and it's the kind
of answer that gets you hired.

---

## Table of contents

- [Level 1 — Product understanding](#level-1--product-understanding)
- [Level 2 — AI engineering](#level-2--ai-engineering)
- [Level 3 — RAG and retrieval](#level-3--rag-and-retrieval)
- [Level 4 — LLM specifics](#level-4--llm-specifics)
- [Level 5 — Evaluation](#level-5--evaluation)
- [Level 6 — System design](#level-6--system-design)
- [Educational AI](#educational-ai)
- [Security](#security)
- [Product questions](#product-questions)
- [The top 15](#the-top-15)
- [Vocabulary](#vocabulary-for-beginners)
- [Known weak spots](#known-weak-spots-be-ready)

---

# Level 1 — Product understanding

### Q1. What problem does EduForge AI solve?

**Short version.** A teacher gets handed a textbook chapter and has to turn it into a
week of actual teaching — a lesson plan split across periods, explanations they can say
out loud, classroom activities, a question paper with an answer key, and some idea of
where students will get stuck. That's 4–6 hours of prep per chapter, repeated by every
teacher teaching that chapter. EduForge takes the chapter file and produces all of it in
about six minutes, with a citation back to the source for every factual claim.

**The deeper version.** The important word is *prep*, not *content*. Content is
everywhere — the textbook already exists. What doesn't exist is the translation from
"here is the material" to "here is how I teach it on Tuesday." That translation is
skilled work, it's unpaid, it happens at night, and it's duplicated across every teacher
teaching the same chapter. That duplication is the business value.

The citation requirement is what makes it usable rather than merely impressive. A teacher
cannot use material they'd have to fact-check line by line — checking would cost more
than writing it themselves. So every factual claim carries a pointer to the exact span of
the source document it came from, and the teacher can click and verify in two seconds
instead of two minutes.

### Q2. Why is this better than ChatGPT?

**Short version.** You can absolutely paste a chapter into ChatGPT and ask for a lesson
plan. You'll get something decent. What you won't get is: the same structure every time,
a citation for every claim, an answer key that's guaranteed complete, a machine-checkable
quality score, or the ability to regenerate just the assessment section without touching
the rest. EduForge produces a *typed artifact*, not a conversation.

**The deeper version.** Four concrete differences:

1. **Structure is guaranteed, not requested.** The output is validated against a JSON
   Schema. Every question has an answer. Every MCQ has exactly one correct option. If the
   model produces something malformed, it's repaired or dropped before a teacher sees it.
   With ChatGPT, "please include an answer key" is a request the model may quietly ignore
   on question 14 of 20 — and you won't notice until you're standing in the classroom.

2. **Grounding is enforced by the type system.** Claims from stage 3 onward are literally
   unconstructable without an evidence span (`Grounded.evidence` has `min_length=1`). Not
   "the prompt asks for citations" — the object cannot be built without one. Then quotes
   are verified against the cited chunk *deterministically*, before any model gets
   involved. Fabricated quotes are dropped for free.

3. **It adapts without being told the subject.** Nothing in the codebase branches on a
   subject name (there's a test that greps for that and fails the build). A history
   chapter gets zero numerical questions and a debate activity; a physics chapter gets
   numerical items and an experiment. Same code path.

4. **It's measurable.** Every package gets scored on nine pedagogical dimensions with
   evidence pointers. You can tell whether run #40 is better than run #12. A chat
   transcript has no such property.

**The honest caveat, if pressed.** For *one* teacher doing *one* chapter, ChatGPT is
faster and probably fine. The value here shows up at scale and where trust matters — a
school standardising material, or anywhere the output gets reused rather than read once.

### Q3. Why a pipeline instead of one large prompt?

**Short version.** Five reasons: quality, debuggability, cost, resumability, and
testability. One giant prompt asking for everything at once produces material that's
uniformly mediocre — the model spreads attention thin. Ten focused stages each do one
thing with a small prompt and a narrow slice of context.

**The deeper version.**

- **Attention dilution is real.** Ask for lesson plan + activities + assessments +
  gap analysis in one call and every section gets shallower. Ask for just the assessment
  bank, given the extracted concepts, and you get a better assessment bank.
- **You can't debug a monolith.** When output is bad, "which part of the prompt failed?"
  has no answer. With stages, a bad question paper is stage 7 — I can look at exactly what
  it received and what it returned.
- **Failure is contained.** If stage 7 degrades, stages 1–6 still produced good work.
  With one call, a malformed response loses everything.
- **Resume is possible.** A 12-minute run that dies at minute 9 resumes at the first
  incomplete stage and doesn't re-bill the eight that succeeded. Impossible with one call.
- **Small prompts fit small models.** Because each stage sees only its slice, prompts stay
  small enough for a *free-tier* model to answer well. The whole thing runs at $0.00.
- **Stages are independently testable.** Each stage has fixtures for its input and output,
  so I can test stage 7 without running stages 1–6.

**The honest trade-off.** More moving parts, more latency, more code. For a simpler
product this would be over-engineering. It's justified here because the output is long,
structured, and has to be trustworthy.

### Q4. Why a "Teacher Knowledge Package"?

**Short version.** Because a lesson plan alone isn't usable. A teacher who has a plan but
no activities, or activities but no answer key, still has hours of work left. The package
is the *complete unit of prep* — the smallest thing you can hand a teacher that means
"you're ready for this chapter."

**The deeper version.** It's one artifact with one schema and one version number, which
matters for three reasons: the parts stay consistent with each other (the assessment tests
what the lesson plan taught, because both derive from the same extracted concepts); it can
be stored, diffed, and re-rendered into multiple formats (JSON, three PDFs, Markdown); and
it can be scored as a whole. Naming it a "package" was a deliberate product decision — it
sets the expectation that you get everything, not a starting point.

---

# Level 2 — AI engineering

### Q5. Explain your AI pipeline, stage by stage.

Ten stages, strictly linear. Here's each one: what goes in, what comes out, why it exists,
and how it fails.

**Stage 1 — Document Intelligence**
- *In:* the uploaded file (PDF / DOCX / PPTX / TXT).
- *Out:* `structured_document` (typed blocks — headings, paragraphs, tables, equations)
  and `chunks`.
- *Why:* everything downstream needs clean, structured text with position information. If
  you flatten a PDF to a string, tables and equations are destroyed and citations have
  nothing to point at.
- *Fails:* no extractable text → raises `EmptyDocument` (this is how scanned PDFs are
  rejected — deliberately, rather than OCR-guessing). Parse exceeds the timeout →
  `ParseTimeout`. **Zero model calls in this stage** — it's all deterministic parsing.

**Stage 2 — Educational Classification**
- *In:* `structured_document`.
- *Out:* `classification` — subject, grade band, difficulty, and critically the
  **`pedagogy_profile`** (`quantitative` / `conceptual` / `narrative` / `procedural` /
  `mixed`).
- *Why:* this is the routing decision the entire rest of the pipeline keys off. It's why
  the system handles history and physics without knowing what a subject is.
- *Fails:* if the model degrades twice, we get a typed placeholder and the profile falls
  back to `mixed` — deliberately the least opinionated profile, so a classification
  failure produces bland-but-valid output rather than wrong-shaped output.

**Stage 3 — Knowledge Extraction**
- *In:* `chunks`, `classification`.
- *Out:* `knowledge` — concepts, learning objectives, definitions, formulae,
  misconceptions, and a **concept DAG** (which concept is a prerequisite for which).
- *Why:* this is the factual backbone. Every later stage generates *from this*, not from
  the raw document. It's also where grounding is established.
- *Fails:* a claim whose quote isn't actually in the chunk it cites gets **dropped** —
  deterministic string matching, no model call, free. Cycles in the prerequisite graph are
  broken at the lowest-confidence edge and recorded as a warning rather than crashing.
  Above a token budget, extraction splits into two calls and merges with dedup.

**Stage 4 — Teaching Planner**
- *In:* `knowledge`, `classification`, user options.
- *Out:* `teaching_plan` — how many periods, and which concepts in which period.
- *Why:* sequencing is a correctness problem, not a writing problem. Teaching a concept
  before its prerequisite is a real defect.
- *Fails:* if the model omits time allocations, a deterministic default is computed. No
  concepts at all → hard error. **Note:** the period count and the concept ordering are
  computed *in Python*; the model only writes period titles and framing. It cannot reorder
  concepts.

**Stage 5 — Classroom Content**
- *In:* one period's concepts and objectives, plus neighbouring period titles for
  continuity.
- *Out:* `period_contents` — teacher scripts, explanations, checks for understanding.
- *Why:* the actual "what do I say" layer.
- *Fails:* each period generates independently and concurrently (`asyncio.gather`, bounded
  by the LLM client's semaphore), so one degraded period damages one period, not the run.
  This stage is ~25% of total runtime, which is why it's parallelised.

**Stage 6 — Activities**
- *In:* `teaching_plan`, `knowledge`, `classification`.
- *Out:* `activities` — profile-weighted mix (experiment, debate, role-play, problem set…).
- *Why:* teaching isn't just talking. The mix is weighted by pedagogy profile, which is why
  history gets a debate and physics gets an experiment.
- *Fails:* missing instructions or success criteria are backfilled deterministically from
  the slot's own concepts, with a warning.

**Stage 7 — Assessments**
- *In:* `knowledge`, `classification`.
- *Out:* `assessments` — question bank, answer keys, rubrics.
- *Why:* the highest-stakes output. A wrong answer key is worse than no answer key.
- *Fails:* an item with an empty stem or answer is **dropped**, not repaired. An MCQ with
  fewer than four distinct options is **reissued as a short-answer question** rather than
  discarded. Zero surviving items → hard error. The blueprint (how many of each type, at
  which Bloom level, worth how many marks) is computed in Python *before* generation.

**Stage 8 — Gap Analysis**
- *In:* `knowledge`, `classification`.
- *Out:* `learning_gaps` — predicted misconceptions, diagnostic questions, remediation.
- *Why:* the thing experienced teachers know and new teachers don't — where students trip.
- *Fails:* a gap without a diagnostic or remediation is dropped. Zero gaps is a legitimate
  empty result, not an error.

**Stage 9 — Validation**
- *In:* everything.
- *Out:* `validation` — status plus issues.
- *Why:* the gate. Checks schema, coverage, internal consistency, and grounding.
- *Fails:* status is *derived*, not judged — any error-level issue → `fail`; only warnings
  → `pass_with_warnings`; none → `pass`. Cheap checks run before the expensive grounding
  check so a schema failure doesn't burn model calls.

**Stage 10 — Publishing**
- *In:* everything.
- *Out:* the assembled `package` plus rendered artifacts (3 PDFs + Markdown).
- *Why:* turns state into the thing a teacher downloads.
- *Fails:* a missing required state key raises an error naming it. **Known weakness:**
  there's no try/except around individual renderers, so a renderer exception fails the
  whole job instead of publishing the JSON with one artifact marked failed. The design docs
  say it should degrade; the code currently doesn't. *(Flag this yourself if asked about
  weaknesses — see [Known weak spots](#known-weak-spots-be-ready).)*

### Q6. Why LangGraph — not LangChain, CrewAI, or AutoGen?

**Short version.** I needed explicit control over a *stateful, resumable, checkpointed*
graph. LangGraph gives topology and state reduction as first-class concepts and stays out
of the way of the model calls. The others each impose something I didn't want.

**The deeper version.**

- **Not plain LangChain:** chains are good at linear prompt→parse→prompt flows, but they
  abstract over the provider call. I wanted the provider SDK directly so structured
  outputs, prompt caching, and exact token accounting survive. So the model calls go
  through my own `LLMClient`, and LangGraph only owns topology and state.
- **Not CrewAI:** it's built around agents with *roles* that talk to each other and decide
  who acts next. My stages are deterministic and ordered — stage 7 always follows stage 6.
  Role-playing agents would add nondeterminism to something that benefits from having none.
- **Not AutoGen:** it's strongest at open-ended multi-agent conversation and negotiation.
  My problem is a fixed assembly line with typed handoffs. Conversation is the wrong shape;
  I'd be paying for flexibility I'd then have to constrain back out.

**The honest bit.** Given how much I ended up controlling myself — my own checkpointing,
my own LLM client, my own state contracts — LangGraph is doing less work here than the
name suggests. It gives topology-from-a-list and state reduction. If I were starting again
I'd seriously consider whether a plain `for` loop over the stage roster would do. That's
not a criticism of LangGraph; it's the honest scope of what it contributes to *this*
design.

### Q7. Why multiple agents instead of one GPT call?

Same reasoning as Q3 (pipeline vs. one prompt), plus one thing worth stating separately:
**"agent" here means a bounded specialist, not an autonomous decision-maker.** Each stage
has one responsibility, one input contract, one output contract, and no knowledge of any
other stage. `import-linter` fails the build if one stage imports another.

That enforcement is the whole point. It meant stages could be built in parallel against
fixtures, and it means replacing stage 7 today is a local edit rather than an archaeology
exercise. Without the boundary rule, ten "agents" degrade into one tangled module with ten
filenames.

### Q8. How do agents communicate?

**Shared state, not messages.** There is no agent-to-agent messaging, no negotiation, no
memory in the conversational sense.

Each stage receives a **narrowed view** of a shared state dictionary, and returns a
fragment containing only the keys it owns. LangGraph merges that fragment into the state.
Stage 5 doesn't know stage 3 exists — it knows it receives `knowledge` and returns
`period_contents`.

Three properties fall out of this:
- **Narrowing keeps prompts small.** A stage never sees the whole document, only its slice.
  That's why free-tier models cope.
- **Ownership prevents collisions.** Two stages never write the same key.
- **The fragment is the checkpoint.** What a stage returns is exactly what gets persisted,
  so resume is trivially correct.

Progress *events* are a separate channel — stages emit them, they're persisted, and the UI
streams them over SSE. That's observability, not inter-agent communication.

### Q9. How is state managed — checkpoint, persistence, resume?

**Checkpointing is ours, not LangGraph's built-in saver.** That was deliberate: one source
of truth for "what has this job completed" beats two that can disagree at minute nine of a
twelve-minute run.

- **Checkpoint:** after each stage, its returned fragment is written to a `stage_outputs`
  store keyed by `(job_id, stage)`.
- **Resume:** on retry, completed stages are restored from checkpoint and skipped —
  re-emitted as "restored from checkpoint", never re-executed, never re-billed.
- **A subtle correctness detail worth mentioning:** resume restores the **whole fragment**,
  not just the stage's primary key. Stage 1 writes both `structured_document` *and*
  `chunks`; restoring only the mapped key would silently drop the chunks, and stage 3 would
  then verify citations against nothing. That's a bug that would look like a quality
  problem, not a state problem.
- **Persistence:** the `Store` interface is abstract, but the running implementation is
  **in-memory**. A restart loses everything. The Postgres implementation sits behind the
  same interface and is not written. This is also why the deployment runs a single
  instance. Say this plainly — it's the project's biggest infrastructure limitation and
  pretending otherwise collapses under one follow-up question.

### Q10. What happens if one agent fails?

Four layers, cheapest first:

1. **Retry inside the LLM client.** Up to 4 attempts, exponential backoff with jitter,
   capped at 30s — or the provider's own stated `retry_after` if it sends one, capped at
   120s. This handles transient failures and 429s.
2. **One schema-repair attempt.** If the response doesn't validate, the validation error is
   fed back to the model once. This fixes most structured-output drift.
3. **Degrade to a typed placeholder.** If it still fails, the client constructs a valid-but-
   empty instance of the expected type (empty lists, zeros, first `Literal` value) flagged
   `degraded=True` with the issues attached. The stage sees this, warns, and continues.
   **The pipeline does not halt** — a thin section is better than no package.
4. **Hard error only where output would be meaningless.** Stage 7 with zero surviving
   questions raises rather than publishing an empty assessment bank. The job is marked
   failed with the error type and message, checkpoints are kept, and retry resumes at the
   first incomplete stage.

**Rollback:** there is none, and deliberately. Stages only ever append to state; nothing
mutates a previous stage's output. So there's nothing to roll back — a failed run leaves
valid partial state that a retry builds on.

**One thing to be honest about:** stage 9 *computes* which stages should be regenerated
when validation fails, and the field exists in graph state — but nothing currently reads it
to route back. **The self-healing regeneration loop is designed and not wired.** Validation
reports; it doesn't yet repair. Say this before they find it.

---

# Level 3 — RAG and retrieval

> **Read this first.** This project does **not** use a vector database, embeddings, or
> semantic retrieval. `EMBEDDINGS=none`. Chunks go to the model whole. The README says so
> explicitly rather than claiming RAG. Every answer below is framed honestly. An
> interviewer who asks "why ChromaDB?" is testing whether you'll invent an answer.

### Q11. Why use RAG? (And why we didn't)

**Short version.** RAG exists to solve a specific problem: *the source material doesn't fit
in the context window, so you need to fetch the relevant parts.* We don't have that
problem. The input is a single textbook chapter — typically 10–40 pages. It fits. Adding
vector retrieval would have introduced an approximate-recall failure mode to solve a
problem we didn't have.

**The deeper version.** What people usually *want* from RAG in an education product is two
things: (a) fit large sources into a small context, and (b) trace claims back to sources.
We needed (b) and not (a). So we built (b) directly, and built it *stronger* than retrieval
would have:

- Evidence spans are a **required contract field** from stage 3 onward — `min_length=1`. An
  ungrounded claim is not merely discouraged; it's unconstructable.
- Quotes are verified **deterministically** against the cited chunk before any judge model
  runs. Fabricated quotes are dropped for free.

Retrieval gives you "this chunk was probably relevant." Mandatory evidence gives you "this
exact sentence supports this exact claim, and we checked." For traceability, the second is
strictly better.

**When I'd add retrieval:** the moment input grows past a chapter — a whole textbook, or
cross-chapter question generation, or a "teach this using our school's past papers too"
feature. Then chunk selection becomes a real problem and BM25 or dense retrieval earns its
complexity. The config flag (`EMBEDDINGS=none|local|api`) exists precisely so that's a
config change and not a rewrite. That was a deliberate cut, listed as item #1 on the
roadmap's cut list.

### Q12. Explain your retrieval pipeline, end to end.

Honest walkthrough of what actually runs:

| Step | What we do | What a RAG system would do |
|---|---|---|
| **Parse** | Format-specific parsers → typed blocks (headings, paragraphs, tables, equations), structure preserved | same |
| **Chunk** | Structure-aware chunking on document boundaries, position retained so citations can point back | same |
| **Embed** | **Nothing.** `EMBEDDINGS=none` | embed each chunk |
| **Store** | In-memory, chunks held in job state | vector DB |
| **Retrieve** | **Nothing** — the relevant chunks are passed to each stage by *narrowing*, decided structurally, not by similarity | top-k similarity search |
| **Re-rank** | **Nothing** | cross-encoder rerank |
| **Generate** | Stage-specific prompt with narrowed context + mandatory evidence requirement | prompt with retrieved context |
| **Verify** | **Deterministic quote verification, then batched LLM judge** — see Q15/Q16 | usually nothing |

The row that matters is the last one. Most RAG pipelines retrieve carefully and then trust
the generation. We select context structurally and then **verify the output**. For this
workload that's the better place to spend the effort.

### Q13. Why this chunk size?

Chunking is **structure-aware rather than fixed-size** — it splits on document boundaries
(sections, headings, paragraph groups) rather than at every N tokens.

**Why:** a fixed-size splitter will cut a worked example in half, or separate a formula
from the sentence defining its variables. Then a citation points at a fragment that doesn't
support the claim on its own, and the deterministic verifier — correctly — drops a claim
that was actually fine. Chunk boundaries that respect document structure make citations
land on coherent units.

**The trade-off:** chunks are uneven in size. That would be a problem for embedding-based
retrieval (uneven chunks embed unevenly and skew similarity). It's not a problem here,
because we don't embed. The chunking strategy and the no-retrieval decision are consistent
with each other.

### Q14. Why this embedding model?

**We don't use one.** `EMBEDDINGS=none` — see Q11.

If asked what I *would* use: for this workload, a small local model (something in the
`bge-small` / `all-MiniLM` class) rather than an API embedding model, for three reasons —
document chunks are the bulk of the tokens so API embedding costs would dominate; local
means no per-run network dependency; and retrieval quality over a single well-structured
chapter doesn't demand a frontier embedding model. The config already has a `local` option
for exactly this. There's also a memory-ceiling consideration on a small host, which is
part of why the flag defaults to `none`.

### Q15. How do you avoid hallucinations?

Four layers, and the ordering is the interesting part — **cheapest and most reliable
first**:

1. **Make ungrounded claims unconstructable.** `Grounded.evidence` has `min_length=1`. A
   claim without an evidence span cannot be built. This is a type-system guarantee, not a
   prompt instruction.
2. **Deterministic quote verification at extraction (stage 3).** Every quoted span is
   checked against the chunk it cites — fuzzy string match at a 0.88 threshold. Fails →
   the claim is **dropped**. Costs nothing, runs before six downstream stages could
   propagate the fabrication.
3. **Deterministic lexical pre-filter at validation (stage 9).** Token-overlap score between
   claim and cited evidence. Above 0.6 → marked supported with **no model call at all**.
   Most claims resolve here for free.
4. **Batched LLM judge for the ambiguous remainder.** Only claims the pre-filter can't
   resolve go to a judge model, **20 claims per call** — never one call per claim. Verdicts
   are `supported` / `partially_supported` / `unsupported`.

Plus a structural guarantee: **most of what shapes a package is decided in Python, not by
the model.** Period count, concept ordering, question counts, Bloom levels, marks, activity
types, gap severity — all deterministic. The model writes prose into slots whose shape was
already decided. A model can hallucinate a sentence; it cannot hallucinate a fifth period
into a four-period plan.

**A detail worth mentioning if they go deep:** there's a low threshold (0.25) that is
**reporting-only** and deliberately *not* used as an automatic "unsupported" cutoff. It was
changed to reporting-only after a bug where correctly-grounded claims with low lexical
overlap (paraphrases) were being flagged as fabrications. Low word overlap means "I can't
tell", not "this is false" — that distinction cost a real bug to learn.

### Q16. How do citations work?

Every factual claim carries an **evidence span**: a quote plus a pointer to the chunk it
came from, which resolves back to a position in the source document.

Lifecycle:
1. **Stage 3 requires it** — the model must return the supporting quote alongside every
   concept, definition, formula, and misconception. No quote, no object.
2. **Immediately verified** — is this quote actually in that chunk? Fuzzy match at 0.88.
   No → dropped.
3. **Carried downstream** — later stages generate *from* extracted knowledge, so citations
   propagate to lesson content and assessments.
4. **Re-checked at stage 9** — grounding validation (Q15) scores the whole package.
5. **Surfaced in the UI** — evidence popovers on claims. A teacher clicks and sees the
   source text.

The property that makes this trustworthy: **verification is deterministic and happens
before any model judges anything.** We are not asking an AI whether the AI was honest.
We're doing string matching, and only using a model for the genuinely ambiguous cases.

### Q17. Why ChromaDB — or Pinecone, Weaviate, FAISS?

**We use none of them.** No vector database. See Q11.

If asked to choose: for a single-container deployment of this shape, **FAISS or Chroma
local**, because the whole architecture is one process with no external services, and
adding a hosted vector DB (Pinecone, Weaviate Cloud) would introduce a network dependency,
a second failure mode, and a bill — to serve a corpus that's one chapter. Pinecone earns
its keep at millions of vectors with real availability requirements; that's not this. If
this became a multi-tenant product with per-school document libraries, that calculus flips
and a managed service becomes the right answer.

---

# Level 4 — LLM specifics

### Q18. Which model, and why?

**Production uses OpenRouter free-tier models** — primarily
`nvidia/nemotron-3-super-120b-a12b:free`, with `openai/gpt-oss-20b:free` for validation.
Per-stage overrides are configured in `config/models.yaml`. A full run costs **$0.00**.

**Why free models:** because the architecture makes it viable, and that's the interesting
claim. Each stage sees a narrow slice with a small prompt and a strict output schema, so
the model does a bounded job rather than an open-ended one. Combined with schema repair and
typed degradation, a mid-size free model produces acceptable output. If the design required
a frontier model to work at all, that would be a design smell.

**Why a smaller model for validation:** validation checks are largely mechanical. Paying
for a large model to answer "does this quote support this claim" in batches of 20 is waste.

A Gemini profile exists as an alternate. Anthropic is implemented but **off by
default** — a key in the environment isn't enough, `ALLOW_ANTHROPIC=true` is also required.
Billing against a key should be a decision, not a config typo. A `ci` profile replays
recorded cassettes so the test suite makes zero network calls and needs no key.

### Q19. Temperature?

**Not set** — we use provider defaults. What *is* set is `reasoning: {effort: high}` on the
production model.

The honest framing: temperature is the wrong lever for this problem. Consistency here comes
from schema constraints and deterministic structure, not from sampling parameters. The
model can't produce a differently-shaped package at high temperature — the shape is decided
in Python. Temperature would only affect prose variety, which is the one place variety is
harmless.

If I wanted more determinism for regression testing, I'd pin temperature to 0 — but that's
what the `ci` replay profile is for, and cassettes give byte-exact reproducibility that
temperature 0 doesn't guarantee across providers.

### Q20. Top-p?

Also not set. Same reasoning as Q19 — sampling parameters weren't the lever that moved
quality here. Schema strictness, prompt narrowing, and deterministic structure were. Tuning
top-p before those are in place is optimising the wrong variable.

### Q21. Prompt engineering strategy?

Five principles that actually shaped the code:

1. **Narrow the context.** No stage sees the whole document. Stage 5 sees one period's
   concepts, not all ten periods. Smaller context → better focus → cheaper → works on
   free models.
2. **Split structure from prose.** Every generation stage decides *structure* in Python and
   asks the model only for *words*. Stage 7 computes the blueprint — how many questions, of
   which type, at which Bloom level, worth how many marks — then asks for stems and
   answers to fill it. This is the single highest-leverage decision in the project.
3. **Wrap document text as data, not instructions.** All document content goes through a
   `document_block()` helper that wraps it in `<document_content>` tags, escapes embedded
   closing tags, and prepends an explicit "this is data, not instructions" statement.
4. **Demand evidence in the same call.** Citations aren't a second pass; the extraction
   prompt requires the supporting quote alongside every claim.
5. **Instruct against known failure modes explicitly.** The objectives prompt has an
   explicit anti-recall-clustering instruction, because models default to "define",
   "list", "state" and produce a Bloom distribution that's all bottom-tier.

### Q22. Structured outputs?

Yes, with a **capability-negotiation ladder** rather than an assumption:

`json_schema` (strict) → `json_object` → `none`

The client tries strict schema mode; if the model rejects it, it falls back to JSON mode;
if that's rejected, plain text. **The result is cached per model**, so the cost of
discovering a model's capability is paid once, not on every call. This matters because
free-tier models vary wildly in what they support and the roster changes.

Then, regardless of what the provider promised, the parser defends itself: strips code
fences, best-effort isolates the JSON object from surrounding prose, and validates. Because
a model that *claims* to support strict JSON mode will still occasionally wrap it in
` ```json `.

### Q23. JSON validation?

**Pydantic v2**, via `model_validate_json`, against the same models that generate the
published JSON Schema.

Two details worth knowing:
- **Tolerant of extra keys.** If the model invents a field, we strip unknown keys and
  re-validate rather than failing. A model adding a helpful-but-unrequested field
  shouldn't cost a retry.
- **The schema is generated and drift-checked in CI.** `backend/contracts/schema/tkp-1.0.0.json`
  is generated from the Pydantic models and committed. CI regenerates it and fails on any
  diff. So the published contract can't silently drift from the code — which matters
  because nine modules, the frontend, and the API examples all depend on it.

### Q24. Retry mechanism?

In order:

1. **Transport retries** — up to 4 attempts. Exponential backoff with jitter, capped at
   30s. If the provider states its own `retry_after` (429s usually do), that's honoured
   instead, capped at 120s. Jitter matters because stage 5's concurrent period generation
   would otherwise retry in lockstep and re-create the burst that caused the 429.
2. **One schema-repair attempt** — feed the validation error back to the model.
3. **Degrade** — typed placeholder, `degraded=True`, stage warns and continues.
4. **Concurrency control** — a single semaphore in the LLM client (default 4), not in the
   graph. One place to reason about the rate-limit ceiling, respected across every stage at
   once.
5. **Budget ceiling** — a per-job token budget checked *before* each call. Exhaustion
   raises `BudgetExhausted` and publishes a partial package rather than running unbounded.
   A pathological document stops at a known limit instead of discovering it on a bill.

**And the accounting is honest:** failed attempts are counted. A stage that succeeded on
its third try cost three calls. Usage is attributed by snapshotting the call log *around*
each stage rather than by stages self-reporting — bookkeeping that goes stale the first
time someone adds a call.

---

# Level 5 — Evaluation

> This is the section that differentiates the project. The core idea: **never generate a
> number you can't justify.** Most eval frameworks output a confident 0.85 for things
> they haven't measured. This one refuses to.

### Q25. How do you score knowledge extraction?

Two separate graders that are **deliberately never averaged together**:

- **The rubric** (9 dimensions) asks *"is this good teaching?"* — it reads the finished
  package.
- **The per-stage framework** (11 evaluators) asks *"did stage N do its job?"* — it checks
  each stage's contract with the next one.

The distinction earns its keep: a package can score well on the rubric while stage 4
quietly scheduled a concept before its own prerequisite. The rubric reads the artifact; the
per-stage framework reads the seams.

For extraction specifically: coverage (did extracted content make it into teaching,
practice, and assessment?), grounding (do cited spans exist and support the claim?), and
concept-graph integrity (is the prerequisite DAG acyclic and sensibly ordered?).

### Q26. What makes a lesson "90/100"?

Nine weighted dimensions:

| Dimension | Weight | What it measures |
|---|---|---|
| Coverage | 0.15 | extracted content actually taught, practised, and assessed |
| Grounding | 0.15 | cited spans exist and genuinely support the claim |
| Activities | 0.14 | variety, runnability, observable success criteria |
| Objectives | 0.12 | assessable behaviour, not a restated topic label |
| Assessment integrity | 0.12 | markability, diagnostic value |
| Bloom | 0.08 | mark-weighted cognitive spread |
| Sequencing | 0.08 | prerequisites before dependents, load spread evenly |
| Differentiation | 0.08 | support/extension that's usable, not just present |
| Classroom | 0.08 | teachable by someone who hasn't pre-read it |

Weights sum to 1.0, asserted at import time so they can't silently drift.

A 90 means: nearly everything extracted is taught *and* assessed; citations check out;
activities are varied and actually runnable; objectives describe observable behaviour;
questions are markable and span cognitive levels. The heaviest weights are on coverage and
grounding because those are the two failures a teacher can't work around — thin
differentiation is annoying, but an uncited claim or an untaught assessed concept is
unusable.

### Q27. How do you calculate confidence?

Confidence is bounded by **method**, and the type system enforces it:

| Method | Meaning | Confidence ceiling |
|---|---|---|
| `deterministic` | computed with arithmetic, reproducible, no model | up to 1.0 |
| `hybrid` | deterministic signal plus model judgement | between |
| `judged` | a model read it, reasoning attached | **capped at 0.9** |
| *not applicable* | no ground truth, or the data doesn't exist | **no score at all** |

Constructing a not-applicable metric *with* a score **raises**. So does a judged metric
claiming certainty, and any metric with no reasoning. These aren't conventions — they're
constructor invariants. You cannot write the fabricating code.

### Q28. How do you detect hallucinations?

See Q15 — mandatory evidence, deterministic quote verification, lexical pre-filter, batched
judge for the remainder. Evaluation adds a layer: **grounding is one of the nine scored
dimensions**, so hallucination rate is a reported number on every package rather than a
pass/fail hidden in the logs.

### Q29. Explain groundedness.

**Groundedness = every factual claim is traceable to, and supported by, a specific span of
the source document.**

Three distinct things, often conflated:
- **Citation exists** — the claim points somewhere. (Guaranteed by the type system.)
- **Citation is real** — the quoted text is actually in the chunk cited. (Deterministic
  check, fuzzy 0.88.)
- **Citation supports the claim** — the evidence actually backs what's asserted. (Lexical
  pre-filter above 0.6; ambiguous cases judged in batches of 20.)

Most systems that claim "grounded" only do the first. The gap between the first and the
third is where fabrication lives.

Secondary sources are allowed for *pedagogy* — teaching strategies, analogies, activity
design — but must not introduce subject matter beyond the primary source. That distinction
is a product requirement, not just an implementation detail.

### Q30. Explain citation coverage.

What fraction of factual claims carry verified evidence. Because evidence is contract-
mandatory from stage 3, the *existence* rate is 100% by construction — the interesting
number is the **verification** rate: how many survived deterministic quote-checking, and of
the ambiguous remainder, how many the judge marked supported.

The number that gets reported in pipeline transparency is the honest one: *"3 claims
dropped — their quotes did not appear in the chunk they cited."* A system that silently
dropped them would show a perfect score.

### Q31. Explain pedagogical quality.

The dimensions a teacher would actually notice, which are mostly *not* about factual
correctness:

- **Objectives** describe observable, assessable behaviour ("calculate the resultant force")
  rather than restating a topic ("understand forces").
- **Bloom distribution** is measured **in marks, not item count** — ten one-mark recall
  MCQs plus one twenty-mark analysis essay is *not* a recall-heavy paper, and counting
  items would say it was.
- **Sequencing** — prerequisites before dependents, cognitive load spread across periods.
- **Activities** — variety, runnability, observable success criteria.
- **Differentiation** — support and extension that a teacher could actually use.
- **Classroom content** — teachable by someone who hasn't pre-read the chapter.

**The property I'd defend hardest:** a humanities package is *not* marked down for absent
STEM content. Coverage scoring is identical across profiles. A grader that rewarded subject
shape would push the whole system toward producing it, and no other test would catch that.

### Q32. Why should we trust your score? *(the important one)*

**Because most of it isn't a judgement — it's arithmetic, and the parts that are
judgements are labelled as such and capped.**

Four reasons, in order of strength:

1. **Method is a type, not a footnote.** Deterministic metrics are recomputed from the
   package with arithmetic; anyone can rerun them and get the same number. Judged metrics
   are capped at 0.9 confidence and must carry reasoning.

2. **The framework refuses to score what it can't measure.** Ten metrics report themselves
   unmeasurable on every run — subject-classification accuracy needs a labelled corpus,
   student learning effectiveness needs students, OCR accuracy needs OCR. Each says what it
   would take to measure. Unmeasurable metrics are **excluded from aggregates rather than
   counted as zero**, and a stage that measured nothing scores `None` — not 0, because zero
   says "this is bad" and the truth is "we don't know". *A framework that reports 0.85 for
   "teacher satisfaction" has not measured teacher satisfaction.*

3. **Every score carries evidence you can check.** Score, confidence, reasoning, a **JSON
   pointer into the package** so a reader can go look, and recommendations with stated
   impact and severity.

4. **It found real bugs — including in its own project.** Building it immediately surfaced
   two: the narrative sample's blueprint claimed a `numerical` item its own profile designs
   away, and the reference fixture published provenance for 1 stage of 10. A framework that
   never catches anything isn't measuring.

**And the scoring can't be gamed by tuning:** exit code 1 fires on a *high-severity
finding*, never on the score itself. A threshold on an aggregate invites tuning the
aggregate.

### Q33. Is the evaluation objective or AI-generated?

**Mostly objective; the AI parts are labelled and capped.**

Five of nine dimensions are fully deterministic (coverage, sequencing, grounding, bloom,
assessment integrity). Three are hybrid. The LLM judge in the rubric is **optional and
never load-bearing** — the framework produces scores without it.

Where a model *is* used — the grounding judge on ambiguous claims — it runs only after the
deterministic pre-filter has resolved everything it can, and its verdicts carry reasoning.

**The self-aware version, if they push:** yes, there's circularity risk in using an LLM to
grade LLM output. That's exactly why judged metrics are capped at 0.9, why the judge is
optional, why the heaviest-weighted dimensions are deterministic, and why the per-stage
framework recomputes stages' self-reported numbers independently rather than trusting them.

### Q34. How would you validate your evaluator?

This is where I'd want to be honest about what's built and what isn't.

**Built — discrimination testing.** The tests are about *discrimination*, not about a good
package scoring well:
- **Sabotage tests:** deliberately break one thing, assert the score drops on the stage that
  owns it **and on no other**. A framework where every metric moves together is measuring
  one thing under eleven names.
- **Attack the guards directly:** the suite tries to construct a fabricated score and
  asserts that construction *fails*.
- **The profile-fairness property:** a humanities package must not score lower for absent
  STEM content.
- **Self-consistency:** stage 9 publishes a coverage summary; the framework recounts it from
  the package and compares. This is the check that finds real bugs.

**Not built — human correlation.** The thing that would actually validate it is: give 30
packages to experienced teachers, have them rank quality, and measure rank correlation
against the framework's scores. Without that, I can prove the evaluator is *self-consistent
and discriminating*, but not that it agrees with a teacher. That's the honest ceiling on
the current claim, and it's the first thing I'd build with more time.

Also: regression detection stays silent below five comparable runs and says so — a baseline
drawn from three runs is astrology. And history is partitioned by pedagogy profile, because
a narrative package doesn't regress by scoring below a corpus of quantitative ones.

---

# Level 6 — System design

### Q35. Explain the architecture.

**A modular monolith with CI-enforced boundaries** — not ten microservices.

```
backend/
  contracts/      frozen Pydantic models + published JSON Schema (imports nothing else)
  core/           LLM client & providers, storage, progress, observability, config
  pedagogy/       pedagogy profiles + curriculum boards (declarative YAML)
  stages/         s1…s10, one package each — never import one another
  orchestration/  LangGraph topology, state, checkpointing, the stage roster
  worker/         job execution and resume
  api/            FastAPI routes, SSE, middleware
  evals/          9-dimension quality rubric
frontend/         Next.js static export, served single-origin by the API
```

**Three rules enforced by `import-linter` in CI:**
1. A stage may never import another stage.
2. Nothing may import *into* `contracts` (it's a leaf).
3. Layers may not reach upward.

**Why a monolith:** the live prototype was the real delivery risk. Distribution costs
(network, deployment, debugging across services) buy nothing at this scale. The boundaries
keep the option of splitting later without paying for it now — which is the actual point of
enforcing them.

**Request flow:** `POST /documents` (dedup by SHA-256) → `POST /jobs` returns `202`
immediately → pipeline runs in the background → progress streams over SSE → `GET
/packages/{id}`. The pipeline **outlives the HTTP request** by design.

### Q36. Why FastAPI?

- **Async-native**, which this workload demands — see Q37.
- **Pydantic is the same library the contracts are written in**, so request/response models,
  the internal state contracts, and the published JSON Schema are all one type system. No
  translation layer, no drift.
- **OpenAPI is generated**, so the frontend could be built against the spec starting in
  week one, before any real data existed.
- **SSE is straightforward** with `StreamingResponse`.

Django would have brought an ORM and admin I don't need; Flask would have meant bolting
async and validation on by hand.

### Q37. Why async?

Because this workload is **almost entirely I/O wait**. A run makes 60–120 model calls, each
taking seconds. Sync code would block a worker thread doing nothing but waiting on network.

Two places it pays concretely:
- **Stage 5 generates periods concurrently** (`asyncio.gather`) — it's ~25% of a run and
  periods share no state. Sequential would be several minutes slower.
- **SSE connections are long-lived.** Dozens of clients watching progress cost almost
  nothing async; sync would need a thread each.

Concurrency is bounded by a **single semaphore in the LLM client**, not in the graph — so
the rate-limit ceiling lives in one place and is respected across every stage at once.

**Worth saying:** the concurrency tests measure *overlap*, not output. A test that only
checked the result would pass just as happily against the sequential version.

### Q38. How do you scale?

**Honestly: right now, I don't.** Storage is in-memory, so the deployment is a **single
instance** — the constraint isn't compute, it's that an in-memory store can't be shared
across processes. This is the project's main infrastructure limitation and I'd rather state
it than have it discovered.

**What the architecture already got right for scaling:**
- The `Store` interface is abstract; the Postgres implementation slots in behind it.
- Jobs are durable rows, not in-flight requests — the pipeline already outlives the HTTP
  connection.
- Checkpointing per stage is already there.
- Progress is a persisted event log with replay, not in-memory pub/sub.

**The actual path, in order:**
1. **Postgres store** — unblocks everything else. `FOR UPDATE SKIP LOCKED` for job claiming,
   lease + heartbeat so a dead worker's job gets reclaimed. The unique `(job_id, stage)`
   checkpoint constraint makes double execution idempotent anyway.
2. **Split the worker from the API** — they scale on different axes. API scales with
   concurrent viewers; workers scale with concurrent runs.
3. **Horizontal workers** behind the queue.
4. **Provider quota becomes the real ceiling.** Past a few hundred concurrent runs the
   bottleneck is the model provider, not our infrastructure — which means paid tiers,
   multiple keys, or provider fallback.

### Q39. Explain caching.

**Not built** — and it's the most obvious remaining performance win, listed as such in the
README.

What exists: **prompt caching on the shared document prefix**, so repeated calls within a
run don't re-pay for the document context.

What I'd build: a **content-hash cache across runs**. Key on `(document_hash, stage,
prompt_version, model)`. Two documents that are byte-identical produce identical stage 1–3
output, so a second upload of the same chapter should cost nothing up to the point where
user options diverge. Given documents are deduplicated by SHA-256 already, the key material
is right there. This matters most for the realistic usage pattern — many teachers uploading
the *same* NCERT chapter.

### Q40. Explain queues.

**Currently there is no separate queue process.** Jobs are durable rows; the API drives the
pipeline itself, because an in-memory store can't be shared across processes. `POST /jobs`
returns `202` immediately and the run proceeds in the background — so the *API contract* is
already queue-shaped even though the implementation isn't.

With Postgres: claim with `SELECT … FOR UPDATE SKIP LOCKED`, lease with heartbeat so a dead
worker's job is reclaimed rather than stuck, and rely on the unique `(job_id, stage)`
checkpoint constraint to make accidental double-execution idempotent.

**Why Postgres rather than Celery/RQ/SQS:** job state, checkpoints, and the event log all
need to be transactionally consistent with each other. Splitting the queue into a separate
system means two sources of truth about "what has this job done" — the exact problem I
avoided by not using LangGraph's checkpointer. At this scale, `SKIP LOCKED` is enough.

### Q41. How do you stream progress?

**Server-Sent Events**, resumable.

- Stages emit progress events; each is persisted with a **monotonic sequence number**.
- `GET /jobs/{id}/events` streams them.
- **Resume:** the client sends `Last-Event-ID` and gets everything after that sequence.
  Both the header *and* a `last_event_id` query parameter are accepted — because browser
  `EventSource` can't set custom headers on the *initial* connection, only on automatic
  reconnects. That's a real browser constraint that a header-only implementation gets wrong.
- **Heartbeat** comment every 15s to keep proxies from killing an idle connection.
- A **finished** job replays its entire timeline and closes — so opening a completed job
  shows the full history rather than nothing.

**Why SSE not WebSockets:** progress is one-directional server→client. SSE is plain HTTP,
survives proxies, and has automatic browser reconnection with resume built into the
protocol. WebSockets would mean building reconnection and replay by hand.

**Tested by:** cutting the stream mid-run, reconnecting with `Last-Event-ID`, and asserting
the halves join exactly — no gap, no duplicate.

### Q42. How do you process a 2000-page PDF?

**Honestly: currently, I wouldn't — and that's deliberate.** There's a page cap (300) and a
parse timeout (90s). A 2000-page textbook is rejected with a clear error rather than
accepted and then failing badly nine minutes in.

The design target is a **chapter**, not a textbook — that's the actual unit of teaching prep
and it was a product decision, not just a technical limit.

**What already handles large-ish documents:** structure-aware chunking; map-reduce
extraction with dedup merge (stage 3 splits into multiple calls above a 12k-token budget);
per-stage narrowing so no stage ever sees the whole document; and a per-job token budget so
a pathological document stops at a known limit.

**What I'd add for genuine textbook scale:**
1. **Chapter segmentation first** — treat a textbook as N chapters and run N pipelines. The
   unit of work stays a chapter.
2. **This is where retrieval finally earns its complexity** (Q11) — cross-chapter context
   selection is a real retrieval problem.
3. **Streaming parse** rather than loading the document into memory.

### Q43. How do you reduce latency?

Current run: 5–7 minutes. What's already done:
- **Concurrent per-period generation** in stage 5 (~25% of a run).
- **Batched grounding judge** — 20 claims per call, never one per claim.
- **Deterministic pre-filter** resolves most grounding claims with **no model call at all**.
- **Cheap validation checks run before expensive ones** — schema and coverage before
  grounding.
- **Narrowed prompts** — smaller inputs are faster as well as cheaper.

What I'd do next: the **cross-run cache** (Q39) — the biggest win, since re-uploading a
known chapter should skip stages 1–3 entirely. Then look at whether stages 6, 7, and 8 can
overlap; they're currently serialised to keep the burst profile flat for rate limits, which
is a deliberate latency-for-reliability trade.

**The honest framing:** for a task that replaces 4–6 hours of work, six minutes is not the
constraint. I'd spend engineering effort on quality and cost before latency.

### Q44. How do you reduce cost?

The run already costs **$0.00** — free-tier models. But the techniques are the same ones
that would matter at paid scale:

- **Narrow context.** The dominant cost driver is input tokens. Never sending the whole
  document to any stage is the single biggest saving.
- **Deterministic-first.** Every check that resolves without a model call is free. The
  grounding pre-filter resolves most claims at zero cost; quote verification is pure string
  matching.
- **Structure in Python, prose from the model.** We don't pay a model to decide how many
  questions to write.
- **Batching.** 20 claims per judge call instead of 20 calls.
- **Right-sized models per stage** — validation uses a smaller model than generation.
- **Prompt caching** on the shared document prefix.
- **A hard token budget per job**, checked before every call, publishing a partial package
  rather than running unbounded.

Next win is **caching across runs** (Q39) — for the realistic pattern where many teachers
upload the same NCERT chapter, that's most of the cost.

### Q45. Explain observability.

Three pillars, all deliberately lightweight — no external dependencies in the serving
image:

- **Structured JSON logs**, one object per line, with `request_id`, `job_id`, and `stage`
  merged in automatically via **contextvars** — so a log line emitted five frames deep
  inside the LLM client carries the job and stage without either being threaded through a
  function signature.
- **`/metrics`** in Prometheus text format: requests, job outcomes, stage durations, model
  calls by outcome. **Failures included** — a climbing retry rate is the earliest sign a
  provider or prompt has degraded.
- **`trace_id` on every error response**, matching the `X-Request-ID` header and the logs.
  An inbound request ID from a proxy is honoured rather than renamed, so traces join up
  across a load balancer.

Plus something most systems don't have: **pipeline transparency in the product itself**.
Every package carries its own record — why it chose 2 periods, why there are no numerical
items, how many claims were dropped and why, and per-stage model/provider/duration/tokens/
attempts. Decisions are recorded in a `finally` block, so a stage that *raised* still
surrenders its reasoning — the run where it matters most.

### Q46. Explain logging.

Standard-library `logging` with a custom `JsonFormatter` — deliberately not `structlog`, to
keep dependencies out of the serving image.

- One JSON object per line, machine-parseable.
- Correlation IDs merged automatically via contextvars.
- **Provider SDK debug logs are forced to `WARNING`** — because at `DEBUG` the OpenAI-
  compatible client logs full request bodies, which means logging the entire uploaded
  document. That's both a noise problem and a privacy problem.
- Secrets are redacted; the error envelope never echoes config.

### Q47. Explain tracing.

**Honest answer: distributed tracing is not implemented.** OpenTelemetry was an explicit
item on the cut list — with a single-process monolith, spans across services have nothing to
cross.

What exists instead, which covers most of what tracing would give at this scale:
- `trace_id` on every error, matching `X-Request-ID` and every log line for that request.
- Per-stage timing, tokens, and attempt counts recorded in the package's own provenance.
- Contextvar-bound `job_id`/`stage` on every log line — so filtering logs by `job_id`
  reconstructs a run's timeline.

The moment the worker splits from the API (Q38), OTel earns its place, because then a trace
genuinely spans processes.

### Q48. Explain metrics.

A hand-rolled Prometheus-text registry — counters and histograms, in-process, deliberately
not `prometheus-client` (same "keep the serving image small" reasoning as logging).
Exposed at `/metrics`.

What's tracked: HTTP requests and latency; job outcomes (succeeded/failed); stage durations;
model calls **by outcome** — `ok`, `error`, `repaired`, `degraded`; token counts by
direction; cost by provider.

**The one I'd watch in production:** model calls by outcome. Absolute failures are obvious,
but a rising `repaired` or `degraded` rate is the early warning that a provider has silently
swapped a model or a prompt has drifted — and it shows up in the metric before it shows up
in anyone's complaint.

Caveat: in-process means metrics reset on restart, and with multiple instances you'd need
aggregation. Fine for one instance; part of the Postgres/horizontal-scaling work otherwise.

### Q49. Explain retries.

Covered in Q24 and Q10. The short form: 4 attempts with jittered exponential backoff
(provider-stated `retry_after` honoured when present), then one schema-repair attempt, then
typed degradation rather than failure. Failed attempts are counted in cost reporting.

### Q50. Explain rate limiting.

**Two different things, both relevant:**

**Outbound (us → model provider).** A single `asyncio.Semaphore` in the LLM client, default
4. Deliberately in the *client*, not the graph — so the ceiling is respected across every
stage at once rather than each stage having its own. Plus jittered backoff honouring the
provider's `retry_after`, and stages 6→7→8 kept serialised to flatten the burst profile.
The free tier is 50 requests/day, so a 429 mid-run on the live demo is the quota, not a
defect — and the preloaded samples cost nothing and always work.

**Inbound (users → us).** Designed but **not implemented**: per-IP limits, a global
concurrent-job cap, and an optional `DEMO_ACCESS_CODE`. The controls that *do* exist are the
per-job token budget and unguessable IDs. For a public demo with no auth this is a genuine
gap — it's the second thing I'd add after authentication.

---

# Educational AI

### Why Bloom's Taxonomy?

Because "is this a good question paper?" needs an objective handle, and Bloom's gives one:
questions are classified by cognitive demand — remember, understand, apply, analyse,
evaluate, create.

Without it, models default to recall. Ask for ten questions and you get ten "define X"
questions, which is a paper that tests memory and nothing else. Bloom levels are assigned
in the **blueprint, before generation** — the blueprint says "one analyse-level 8-mark
question" and the model writes to that slot.

Two implementation details worth mentioning:
- **MCQs are capped at `apply`.** A four-option multiple-choice question genuinely cannot
  test `create`. Pretending otherwise produces a paper that claims higher-order coverage it
  doesn't have.
- **Distribution is measured in marks, not item count.** Ten one-mark recall MCQs plus one
  twenty-mark analysis essay is not a recall-heavy paper — but counting items would say it
  was. This is the kind of detail that shows you thought about the metric, not just the
  feature.

### How do you identify misconceptions?

Two sources:
- **Observed** — misconceptions extracted directly from the document in stage 3 (textbooks
  often flag common errors explicitly), carrying evidence like every other claim.
- **Predicted** — load-bearing concepts that *don't* have a documented misconception. If a
  concept is a prerequisite for several others and nothing warns about it, that's where
  trouble compounds.

**Severity is structural, not model-judged** — which is the part worth explaining. We walk
the concept DAG and compute `downstream_load`: how many concepts transitively depend on
this one. Reach ≥ 2 → high severity. The reasoning: misunderstanding a leaf concept costs
one topic; misunderstanding a foundational one silently breaks everything built on it.

Predicted gaps are capped (4 of a maximum 10 total) so observed, evidence-backed gaps aren't
crowded out by speculation.

### How are lesson plans generated?

**Structure deterministically, prose by the model.**

Python decides: how many periods, which concepts in which period, in what order
(topologically sorted from the prerequisite DAG), and the time budget. The model writes:
period titles, framing, and narrative.

The model **cannot reorder concepts**. Sequencing is a correctness property — teaching a
concept before its prerequisite is a defect, not a style choice — so it isn't delegated.

Band partitioning uses an **exact dynamic-programming solution** that minimises the heaviest
period rather than greedily filling periods in order. Greedy produces a punishing first
period and a trivial last one.

### How do you estimate classroom time?

An explicit formula:

```
load     = Σ importance_weight(concept)      # core 1.0, supporting 0.5, enrichment 0.25
capacity = period_duration_minutes / 12.0    # ~12 min per core-equivalent concept
periods  = ceil(load / capacity)             # clamped to [1, 20] and to concept count
```

So a chapter with 6 core concepts and a 40-minute period: load 6.0, capacity ≈ 3.33,
periods = 2.

**The important property:** this is *derived and reported*. The package says *"2 periods of
40 minutes — derived from 2 concepts weighted by importance against a 40-minute period."* A
teacher can't tell a derived number from an arbitrary one unless you show the derivation —
so the derivation is part of the output.

`MINUTES_PER_CORE_CONCEPT = 12.0` is a calibration constant. It's a defensible starting
estimate, not a measured one — and with real classroom data it's exactly the parameter I'd
tune first.

### How do you generate assessments?

**Blueprint first, questions second.** Before any generation:

1. The **pedagogy profile** sets the question-type mix (narrative weights numerical at zero).
2. The **curriculum board** multiplies its bias over that, then renormalises.
3. The blueprint fixes counts, types, Bloom levels, marks, and concept coverage.
4. *Then* the model writes stems, distractors, answers, and rubrics into those slots.

This is why absence is **reliable rather than lucky**: a narrative profile weights numerical
at zero, so no numerical item is ever *requested*. Contrast with prompting "don't include
numerical questions" and hoping.

Quality gates after generation: an item with an empty stem or answer is dropped; an MCQ with
fewer than four distinct options is reissued as a short-answer question rather than
discarded; the schema requires exactly one correct MCQ option; stage 9 verifies every item
has an answer, marks, and (for non-MCQ) a rubric.

### How do you balance question difficulty?

Through the blueprint — mark-weighted Bloom distribution with a **recall ceiling** and a
**higher-order floor**. The paper can't be all easy or all hard because the blueprint won't
allow either shape.

Difficulty also composes with two other inputs: the classification's difficulty assessment
(grade band and content complexity), and the curriculum board's marks scale — ICSE's 1.2×
scale produces longer, heavier papers than CBSE's MCQ-leaning mix.

### How do you align with CBSE?

**A board configures the output; it doesn't merely label it.** Profile and board compose by
**multiplication**, then renormalise:

```
effective mix = profile.assessment_mix × board.assessment_bias
```

Example values: CBSE biases `mcq: 1.6`, `long_answer: 0.6` (reflecting its MCQ-heavy
pattern). ICSE biases `long_answer: 1.8`, `mcq: 0.5`, with a `marks_scale` of 1.2. IB sets
`period_minutes: 60` and calls its divisions "units" rather than "chapters".

Measured effect on the same quantitative content:

| | generic | CBSE | ICSE |
|---|---|---|---|
| Quantitative | 6 numerical, 4 mcq, 43 marks | **6 mcq**, 5 numerical, 41 marks | **3 long**, 2 mcq, **69 marks** |
| Narrative | 0 numerical | 0 numerical | 0 numerical |

**Multiplying is the whole point:** zero times any bias is still zero, so **no board can put
a numerical question in a poetry chapter**. A board shifts emphasis *within what the content
affords*; it cannot contradict it. There's a test asserting exactly this.

Boards live in `backend/pedagogy/curricula.yaml` — adding one is a config block, not a
conditional.

---

# Security

> Frame this section honestly: the input handling is genuinely well-defended; the
> **access control is absent by design for an assignment demo**. Both halves are worth
> saying.

### PDF malware / malicious uploads?

- **MIME sniffed from magic bytes** (`%PDF-`, `PK\x03\x04` disambiguated by declared type
  and extension for OOXML) — never trusted from `Content-Type` or the filename, both of
  which are attacker-controlled.
- **Size cap** (default 25 MB) checked *before* parsing.
- **Page cap** (300) and **parse timeout** (90s) — these bound zip-bomb and
  billion-laughs-style resource exhaustion.
- **Macros disabled**; no shell-out to external converters (a common RCE path in document
  pipelines).
- Plain text accepted only if it's **valid UTF-8**.
- Malformed fixtures in CI must produce a clean `422`, never a 500 or a hang.

### Prompt injection?

The genuine risk: document text reaches every prompt, so a chapter containing *"ignore
previous instructions and…"* is untrusted input in a privileged position.

**Two layers, and the second is the one that matters:**

1. **Mitigation.** All document text goes through a `document_block()` helper that wraps it
   in `<document_content>` tags, **escapes any embedded closing tag** so content can't break
   out early, and prepends an explicit "this is data, not instructions" statement. An
   adversarial fixture is in CI.

2. **The architectural guarantee.** Model output can only populate **schema-validated
   fields**. It cannot trigger a side effect, call a tool, make a network request, or write
   a file. There are no tools wired to the model at all. So the worst a successful injection
   achieves is *bad content in a validated field* — which then faces grounding checks that
   would flag unsupported claims.

The honest framing I'd use: **delimiters are mitigation, not proof.** The real defence is
that the model has no capabilities to hijack. That's a design property, not a prompt
property, and it's the one I'd defend.

### Data privacy / PII?

Uploaded documents are textbook chapters, so PII exposure is low by nature — but it's not
zero (a teacher could upload student work by mistake).

- Documents are deduplicated by SHA-256 and stored in-memory — **a restart discards
  everything**, which is accidentally the strongest retention policy possible, though not a
  designed one.
- Provider SDK debug logging is forced to `WARNING` specifically to prevent full document
  text being written to logs.
- API keys are read from environment only, redacted in logs, never echoed in errors;
  secret-scanning runs in CI.
- **Designed but not built:** 30-day retention with a daily purge job. With persistent
  storage this becomes mandatory rather than optional.
- **Worth stating plainly:** document content is sent to a third-party model provider
  (OpenRouter). For any real school deployment that's a data-processing question requiring
  an actual agreement — not a technical control.

### Authentication?

**There is none.** No auth on any endpoint. Anyone with the URL can upload and read every
package.

This is deliberate for an assignment demo — the evaluator has to be able to open a URL and
use it — and it's documented as the first thing to add for real use. Don't defend it as a
design choice beyond that context; it's a scoping decision with a stated cost.

### Authorization?

Also none — no users, no teams, no ownership model. Package IDs are UUIDs, so they're
unguessable, but that's obscurity, not authorization. Anyone who obtains an ID can read the
package.

**What I'd build:** teacher accounts → documents and packages owned by a user → schools as
tenants with row-level isolation → sharing as an explicit grant. The `Store` interface is
where the ownership filter would go, which keeps it out of every route.

### File validation?

Covered above: magic-byte MIME sniffing, size cap, page cap, parse timeout, UTF-8
validation for text, macros disabled, no external converter shell-out, and adversarial
fixtures in CI asserting clean rejection.

Rejections return the standard error envelope with a `trace_id`:
```json
{"error": {"code": "document_not_found", "message": "…", "trace_id": "c1a666c5d2c9"}}
```

---

# Product questions

### If 100,000 teachers upload tomorrow, what breaks first?

**In order — and the first one isn't a scaling problem, it's a correctness cliff:**

1. **The in-memory store.** Not "gets slow" — the process runs out of memory and *loses
   every job and package*. Before that, the single instance means no horizontal scaling at
   all. This is the wall, and it's at a few hundred concurrent jobs, not 100,000.
2. **The model provider quota.** Free tier is 50 requests/day. At ~60–120 calls per run,
   that's under one run. Even on paid tiers, 100k runs × ~100 calls = 10M calls/day would
   need negotiated capacity.
3. **No inbound rate limiting.** Nothing stops one client from queueing thousands of jobs.
4. **Cost, with no per-user budget.** There's a per-*job* token budget but no per-user or
   global spend ceiling.
5. **Then** the usual: connection pools, blob storage, SSE connection count.

**The order matters more than the list** — the honest answer is that #1 makes #2–#5
hypothetical.

### How would you monetize?

Per-seat SaaS for teachers is the obvious model but probably the wrong one — individual
teachers have no budget and schools don't buy per-seat tools easily.

I'd sell to **schools and school chains**: an annual per-school licence, priced against the
prep hours it replaces across a department. The buyer is a head of department or principal
with an actual budget, and the value story is concrete (a 12-person science department × 4
hours × 30 chapters).

Second, **publishers and edtech platforms**: whoever owns the textbook has both the content
rights and an incentive to ship "and here's how to teach it" alongside. That's a licensing
or white-label deal, and it fixes the content-rights question rather than skirting it.

The free tier should be generous per-teacher, because teacher enthusiasm is what gets the
tool in front of the person with the budget.

### Enterprise features?

In the order a school would actually ask for them: SSO and role-based access; a shared
department library with review-and-approve before material reaches students; school-level
curriculum and style configuration (the board system is already the seed of this); audit
logs; usage analytics per department; and a data-processing agreement with regional data
residency. Almost all of it depends on the auth and persistence work — which is the honest
reason it isn't built.

### Offline schools?

The real constraint in many Indian schools, and it changes the architecture rather than
adding a feature.

The generation step fundamentally needs a model. Two viable shapes: **batch/async** — a
school uploads chapters when connectivity exists, packages generate server-side, and PDFs
sync down for offline use (the artifacts are static PDFs and Markdown, so offline
*consumption* already works today); or **on-premise** with a local model on a school server,
which the provider abstraction makes tractable but which would need a much smaller model and
honest quality expectations.

The batch route is right for most schools. On-prem is a real option for a chain with
infrastructure.

### LMS integration — Google Classroom, Teams, Moodle?

The right shape: **export targets, not rewrites.** The package is already structured JSON
that renders to multiple formats, so each integration is a renderer plus an auth flow.

- **Google Classroom** — first, by market share in Indian schools. Push the lesson plan as
  material, the assessment as an assignment with the key held back, activities as
  coursework. OAuth plus the Classroom API.
- **Microsoft Teams for Education** — same shape via Graph API; matters for schools already
  on Microsoft 365.
- **Moodle** — a different bet: it's self-hosted, so it fits the offline/on-prem story, and
  **QTI export** is the standards-based path that works for Moodle *and* several other LMSes
  from one implementation. Best effort-to-reach ratio of the three.

The prerequisite for all of them is authentication — you can't push to a teacher's
Classroom without knowing who they are.

---

# The top 15

The ones to know cold. Most are answered in full above; this is the recall list plus the
five that aren't.

| # | Question | Where |
|---|---|---|
| 1 | What problem does it solve? | [Q1](#q1-what-problem-does-eduforge-ai-solve) |
| 2 | Walk through the architecture. | [Q35](#q35-explain-the-architecture) |
| 3 | Why multi-agent, not one prompt? | [Q3](#q3-why-a-pipeline-instead-of-one-large-prompt), [Q7](#q7-why-multiple-agents-instead-of-one-gpt-call) |
| 4 | Explain the RAG pipeline. | [Q11](#q11-why-use-rag-and-why-we-didnt), [Q12](#q12-explain-your-retrieval-pipeline-end-to-end) — **we don't use RAG; say so** |
| 5 | How do you prevent hallucinations? | [Q15](#q15-how-do-you-avoid-hallucinations) |
| 6 | How do citations and grounding work? | [Q16](#q16-how-do-citations-work), [Q29](#q29-explain-groundedness) |
| 7 | How does evaluation assign scores? | [Q26](#q26-what-makes-a-lesson-90100), [Q27](#q27-how-do-you-calculate-confidence) |
| 8 | Why trust those scores? | [Q32](#q32-why-should-we-trust-your-score-the-important-one) |
| 9 | Why this LLM and orchestrator? | [Q6](#q6-why-langgraph--not-langchain-crewai-or-autogen), [Q18](#q18-which-model-and-why) |
| 10 | How do you scale? | [Q38](#q38-how-do-you-scale), [Q42](#q42-how-do-you-process-a-2000-page-pdf) |
| 11 | What happens when a stage fails? | [Q10](#q10-what-happens-if-one-agent-fails) |
| 12 | How do you validate before publishing? | below |
| 13 | Improve quality without raising cost? | below |
| 14 | What trade-offs did you make? | below |
| 15 | Three more months — what next? | below |

### 12. How do you validate outputs before publishing?

Four rule classes in stage 9, cheapest first: **schema** (does it satisfy the contract),
**coverage** (is extracted content actually taught and assessed), **consistency**
(referential integrity — every referenced concept exists, every question has an answer,
every MCQ has exactly one correct option), and **grounding** (the expensive one, deferred
until the free checks pass).

Status is **derived, not judged**: any error-level issue → `fail`; warnings only →
`pass_with_warnings`; none → `pass`.

Validation status is displayed prominently in the UI — deliberately, because a permanently-
green validator would then be *visibly* implausible. And negative-path tests require a
deliberately corrupted package to trip **each** rule class: a validator only ever tested on
good input is indistinguishable from `return "pass"`.

**What I'd flag honestly:** stage 9 computes which stages should be regenerated on failure,
and the state field exists — but the routing back is not wired. Validation reports; it
doesn't yet self-heal.

### 13. How would you improve quality without greatly increasing cost?

In order of expected return per rupee:

1. **Prompt iteration driven by the eval harness.** The framework exists and gives per-
   dimension scores with evidence. Improving the weakest dimension costs prompt work, not
   inference. This is free quality and it's why the eval harness was built before tuning.
2. **Move more decisions into Python.** Every structural choice made deterministically is a
   choice the model can't get wrong, and it shrinks prompts. The blueprint pattern already
   proved this in stage 7; stages 5 and 8 have room left.
3. **Spend selectively, not uniformly.** Use a stronger model *only* for stage 3
   (extraction), because every downstream stage generates from it — an error there
   propagates through seven stages, while an error in stage 6 affects one activity. Cost
   scales with one stage; quality scales with all of them.
4. **Better few-shot examples** from packages the eval framework scored highly. No extra
   calls, slightly longer prompts.
5. **Cross-run caching** (Q39) — frees budget that can be spent on quality elsewhere.

The unifying principle: **measure first.** Quality that isn't measured doesn't improve, and
without the harness every one of these is a guess.

### 14. What trade-offs did you make?

State these as decisions with costs, not as features:

| Trade-off | Chose | Cost | Why |
|---|---|---|---|
| Accuracy vs. latency | Accuracy — 10 stages, 5–7 min | Slower than one prompt | Replacing 4–6 hours; six minutes isn't the constraint |
| Cost vs. quality | Free-tier models + narrow prompts | Ceiling on prose quality | Architecture makes free models viable; keeps the demo permanently runnable |
| Simplicity vs. flexibility | Modular monolith, enforced boundaries | Boundary rules to maintain | Splitting later stays possible; distribution costs nothing now |
| Retrieval vs. traceability | Mandatory evidence, no vector DB | No cross-chapter retrieval | Solved the problem we had, not the one that sounds impressive |
| Determinism vs. model freedom | Structure in Python | More code; less "creative" output | Sequencing and coverage are correctness, not style |
| Persistence vs. delivery | In-memory store | Restart loses everything | **The one I'd revisit first** — bought delivery speed, cost production-readiness |
| Auth vs. demo access | No auth | Anyone with the URL sees everything | Correct for an assignment demo, wrong for anything else |

**If asked which I'd reverse:** the in-memory store. It was right for the deadline and it's
the single thing standing between this and a deployable product.

### 15. Three more months — what would you build?

Ordered by what unblocks the most:

**Month 1 — make it real.**
Postgres behind the existing `Store` interface; split the worker from the API; authentication
and per-teacher ownership; inbound rate limiting; the 30-day retention purge. None of this
is glamorous, and all of it is the difference between a prototype and a product.

**Month 2 — prove the quality claim.**
Human correlation for the evaluator (Q34) — 30 packages, real teachers, rank correlation.
Right now I can prove the evaluator is self-consistent and discriminating, not that it
agrees with a teacher. Then wire the regeneration loop that stage 9 already computes, add
cross-run caching, and drive prompt iteration from measured per-dimension scores.

**Month 3 — make it reach teachers.**
Google Classroom export first; then a shared department library with review-before-publish,
because the multiplier is a *department* reusing material, not one teacher. Then multi-
chapter support, which is where retrieval finally earns its complexity.

**What I'd deliberately *not* build:** more content types, more subjects, more languages.
The system already handles those by construction — adding them is config, not engineering,
and it would be motion rather than progress.

---

# Vocabulary for beginners

Terms you'll need to use fluently.

| Term | Plain meaning |
|---|---|
| **Pipeline / stage** | An assembly line; each station does one job and hands off |
| **Agent** | Here: a bounded specialist stage — not an autonomous decision-maker |
| **State** | The shared dictionary stages read from and write to |
| **Checkpoint** | A saved copy of one stage's output, so a crash can resume |
| **Contract** | The typed shape of data crossing a boundary (Pydantic models here) |
| **Schema validation** | Checking data matches its declared shape |
| **Structured output** | Forcing the model to return JSON matching a schema |
| **Grounding** | Every claim traceable to, and supported by, source text |
| **Evidence span** | The quote + pointer proving a claim |
| **Hallucination** | Model states something confident and unsupported |
| **RAG** | Retrieval-Augmented Generation — fetch relevant chunks, then generate. **We don't do this** |
| **Embedding** | Text as a vector, so similar text is nearby. **Not used here** |
| **Chunking** | Splitting a document into pieces |
| **DAG** | Directed acyclic graph — here, which concept must precede which |
| **Topological sort** | Ordering a DAG so nothing comes before its prerequisite |
| **SSE** | Server-Sent Events — one-way server→client stream over plain HTTP |
| **Idempotent** | Doing it twice has the same effect as once |
| **Semaphore** | A counter limiting how many things run at once |
| **Backoff / jitter** | Wait longer between retries; randomise so clients don't sync up |
| **Degraded output** | A valid-but-empty typed placeholder when the model fails |
| **Bloom's taxonomy** | Six levels of cognitive demand, remember → create |
| **Pedagogy profile** | quantitative / conceptual / narrative / procedural / mixed — the routing key |

---

# Known weak spots (be ready)

Raise these before they're found. Naming your own gaps precisely reads as engineering
maturity; being caught reads as not knowing your own system.

| Gap | The honest line |
|---|---|
| **In-memory storage** | "Restart loses everything. Postgres sits behind the same interface, unwritten. It's why the deployment is single-instance and it's the first thing I'd fix." |
| **No auth or authorization** | "None. Deliberate for a demo, disqualifying for production." |
| **No RAG despite it being asked about** | "No vector retrieval, `EMBEDDINGS=none`. We built traceability instead, which is stronger for this workload. Retrieval earns its place at multi-chapter scale." |
| **Regeneration loop not wired** | "Stage 9 computes which stages to regenerate; nothing routes back yet. Validation reports, it doesn't self-heal." |
| **Stage 10 renderer has no try/except** | "The design says a failed renderer should still publish the JSON with that artifact marked failed. The code doesn't do that yet — a renderer exception fails the job. Real gap, small fix." |
| **Evaluator not validated against humans** | "I can prove it's self-consistent and discriminating. I can't yet prove it agrees with a teacher. That needs 30 packages and real teachers." |
| **No caching across runs** | "Biggest remaining perf and cost win. Documents are already SHA-256 deduplicated, so the cache key is sitting right there." |
| **No inbound rate limiting** | "Designed, not built. Per-IP limits and a global job cap. Second thing after auth." |
| **Free-tier quota** | "50 requests/day, about 1.5 runs. A 429 on the live demo is the quota, not a bug — the preloaded samples always work." |
| **Multilingual unverified end-to-end** | "Plumbed and unit-tested; never run against a live model in a non-English language. Devanagari glyphs are proven by round-tripping text out of a rendered PDF, but conjunct shaping uses fpdf2's engine, not HarfBuzz." |
| **Scanned PDFs rejected** | "Rejected with a clear error rather than OCR-guessed. Deliberate — bad OCR silently poisons every downstream stage and every citation." |
| **No provider fallback** | "Retries cover transient failures; a sustained provider outage fails the job with a clear message. A cross-provider abstraction would cost more than it's worth and would give up structured outputs and prompt caching." |
| **LangGraph is doing less than the name suggests** | "Given I built my own checkpointing and LLM client, it contributes topology and state reduction. A loop over the stage roster would arguably do. Honest scoping, not a criticism of the library." |

---

## Two closing habits

**When you don't know:** "I don't know — here's how I'd find out." Never invent a number, a
library you didn't use, or a benchmark you didn't run. One fabricated detail costs more
credibility than ten gaps.

**When you do know:** lead with the decision, then the reason, then the cost. *"We don't use
a vector DB. The input is one chapter, so it fits in context — retrieval would have added an
approximate-recall failure mode to solve a problem we don't have. The cost is that
cross-chapter features would need it, which is why the flag exists."* Decision, reason,
cost. That's what a senior engineer sounds like.
