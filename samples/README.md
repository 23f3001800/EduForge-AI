# Sample packages

Two Teacher Knowledge Packages, and the quality report for each. They exist to
show the one claim that is hard to demonstrate any other way: **the same code
path produces genuinely different teaching material for a STEM chapter and a
humanities chapter, without anything in the system knowing what a "subject" is.**

| | [`quantitative-physics/`](quantitative-physics/) | [`narrative-history/`](narrative-history/) |
|---|---|---|
| `pedagogy_profile` | `quantitative` | `narrative` |
| Formulae | present | **none** |
| Numerical questions | present | **none** |
| Eval score | **0.917** | **0.874** |
| Absences excused by design | 0 | **2** |

Each directory holds the package itself, the three teacher-facing PDFs, the
Markdown bundle, and the eval report in both JSON and Markdown.

```
quantitative-physics/
  teacher_knowledge_package.json   the artifact — everything below is derived from it
  lesson_plan.pdf                  per-period plan
  teacher_guide.pdf                scripts, activities, gaps, remediation
  assessment_book.pdf              questions, then the answer key behind a page break
  markdown.md
  eval-report.json / .md           scored on 9 dimensions, all deterministic
```

## What to look at

**The absences.** Open `narrative-history/eval-report.md` and find
`absent_by_design`. The harness records that this package has no formulae and no
numerical items, and scores both as *correct* rather than missing. That is the
whole versatility mechanism made visible: stage 2 classifies the content as
`narrative`, that profile weights `numerical` at zero, so stage 7 never designs a
numerical item and stage 9 never asks for one.

**Coverage is identical — 1.00 in both.** This is the number that matters. It
asks whether everything the package teaches is also practised and assessed, and
it is the dimension that would punish absent content hardest. It does not move
between the two profiles, which is the evidence that the grader is measuring
teaching quality rather than subject shape.

**The answer key is a separate section.** In `assessment_book.pdf` the questions
come first, then a page break, then the key. A teacher hands out the first half.
Correct answers, distractor rationales, worked solutions and rubrics appear only
after the break — there is a test asserting exactly that.

**Every factual claim carries a citation.** In the JSON, look at any concept,
definition, or misconception: `evidence` is `min_length=1`, so an ungrounded
claim is not constructible. Stage 3 verifies each quote appears verbatim in the
chunk it cites before anything downstream sees it.

**The gaps are ranked structurally.** In `teacher_guide.pdf`, gap severity comes
from transitive downstream load in the concept dependency graph — "three later
concepts are built on this one" — not from asking a model how serious it thinks
something is, which returns "medium" almost every time.

## Honest caveats

These two packages are built from the repository's reference fixtures, not from a
fresh live run. That is deliberate and it is a real limitation:

- Fixtures are **stable**, so the numbers above are reproducible by anyone who
  checks out the repo and runs `make evals`. A live run's output moves with the
  model.
- The free-tier daily quota (50 requests) is consumed by roughly one and a half
  full pipeline runs, so regenerating these from scratch is rate-limited rather
  than free.

The pipeline *has* been verified end to end against live models — stages 1
through 7 completed on `physics.pdf` before the daily quota was exhausted, with
the period count derived (not fixed) and the quantitative profile correctly
designing a numerical first item. To reproduce:

```bash
./.venv/bin/python scripts/smoke_pipeline.py --doc physics
./.venv/bin/python scripts/smoke_pipeline.py --doc history
```

To regenerate everything in this directory from the fixtures:

```bash
make samples
```
