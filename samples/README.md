# Samples

Two packages, both produced by running the real pipeline through the real API.
Nothing here is hand-written or post-processed. `source.pdf` in each directory is
the exact input, so any claim below can be re-derived:

```bash
make dev                                  # start the server
python scripts/capture_sample.py samples/quantitative-physics/source.pdf \
    --name quantitative-physics
```

An earlier version of this directory was assembled from test fixtures. One of
those "samples" was the physics package with `subject` overwritten to `History`,
so it presented a lesson plan about Newton's first law under the heading "The
Partition of Bengal". Those files are gone, and so is `scripts/build_samples.py`,
which produced them. A sample that cannot fail is not evidence.

## What was run

| | quantitative-physics | narrative-history |
|---|---|---|
| Source | NCERT Class 11 Physics, Ch. 1 | *French Revolution* article |
| Pages / words | 44 / 20,603 | 39 / 19,166 |
| Model | Azure OpenAI `gpt-5-mini` | Azure OpenAI `gpt-5-mini` |

NCERT chapters are the benchmark named in FAQ Q1 and Q2. The humanities
counterpart is a substitute: `ncert.nic.in` was unreachable from the build
network, so a comparable real document was used rather than a fabricated one.

## The versatility result

Both documents take the identical code path. No stage branches on a subject
name — a test greps for that and fails the build.

| | Physics | History |
|---|---|---|
| Subject → profile | Physics → `quantitative` | History → `narrative` |
| Formulae | 15 | **0** |
| Concepts | 22 | 26 |
| Periods (derived, not fixed) | 6 | 7 |
| Assessment mix | 10 numerical, 7 mcq, 5 short, 2 long | **0 numerical**, 5 mcq, 7 short, 12 long |
| Activities | experiment, problem_set, demonstration, simulation | debate, group_discussion, role_play, gallery_walk |

Zero numerical items and zero formulae in the humanities package, and no overlap
at all in activity type. That absence is the designed output of the narrative
profile rather than a gap: the profile weights `numerical` at zero, so no
numerical item is ever requested.

## Both packages fail validation, and that is the system working

Both report `status: succeeded_partial` — the package exists, and its own
validator found problems it will not paper over.

Physics fails on one grounding claim: Gauss's law. **The claim and its citation
are both correct.** PDF extraction flattened `ε₀` to `e` in the chunk text, so
the grounding judge compared a correct claim against corrupted source and ruled
it unsupported at confidence 1.0. The model had reconstructed the mathematics
properly — `\dfrac{1}{4\pi\epsilon_0}` — and grounding penalised it for being
more accurate than the text it was checked against.

That is a real defect, in extraction rather than in generation, and it is
recorded here rather than tuned away. Loosening the judge to make this pass would
also stop it catching genuine fabrication, which is the one thing it exists for.

## Known rough edges in this output

- `duration_minutes` is `null` on every teacher-script segment, so a teacher
  cannot pace a lesson from the script alone.
- `time_allocation` labels are full sentences rather than segment names.
- Equation-bearing chunks lose subscripts and Greek letters, which is the root
  cause of the grounding false positive above.

## Files

| File | What it is |
|---|---|
| `teacher_knowledge_package.json` | The package, schema-versioned |
| `source.pdf` | The exact input, for reproduction |
| `lesson_plan.pdf`, `teacher_guide.pdf`, `assessment_book.pdf` | Rendered artifacts |
| `eval-report.json`, `eval-report.pdf` | Scored server-side, where the run's chunks are still reachable — so citation integrity actually runs instead of reporting itself unmeasurable |
