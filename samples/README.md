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

| | quantitative-physics | narrative-history | multilingual-hindi |
|---|---|---|---|
| Source | NCERT Class 11 Physics, Ch. 1 | *French Revolution* article | NCERT Class 11 Physics, Ch. 1 |
| Pages / words | 44 / 20,603 | 39 / 19,166 | 44 / 20,603 |
| Model | Azure OpenAI `gpt-5-mini` | Azure OpenAI `gpt-5-mini` | Azure OpenAI `gpt-5-mini` |
| Output language | English | English | Hindi (`output_language=hi`) |

NCERT chapters are the benchmark named in FAQ Q1 and Q2. The humanities
counterpart is a substitute: `ncert.nic.in` was unreachable from the build
network, so a comparable real document was used rather than a fabricated one.

## The multilingual result

`multilingual-hindi` runs the *same source PDF* as `quantitative-physics` with
one option changed, so the comparison is controlled: any difference is the
language directive and nothing else.

| | English run | Hindi run |
|---|---|---|
| Assessment stems in Devanagari | 0.0% | **92.7%** |
| Evidence quotes in Devanagari | 0.0% | **0.0%** |
| Grounding score | 0.895 | 0.861 |
| Validation issues | 9 | 11 |

The middle row is the one worth reading, and it is deliberate rather than a
miss. Evidence quotes are extracted at stage 3 and stay in the source language;
only the teacher-facing content generated at stages 4–8 carries the language
directive. That split is what keeps grounding intact — the validator checks each
claim's quote as a verbatim substring of the source, so translating the quote
would fail every claim in the package regardless of whether the translation was
accurate.

The predicted failure of this design was that grounding would collapse. It did
not: 0.895 → 0.861, a 3.4-point drop attributable to two extra ungrounded
claims, not to the language change breaking the check.

The honest limit: this measures that Hindi was *produced* and that grounding
survived. Nobody who reads Hindi has assessed whether the pedagogy survives
translation, and a 92.7% Devanagari share means technical terms remain in Latin
script — which may be correct for a physics classroom or may be an artifact.
That judgement needs a Hindi-speaking teacher, not a character histogram.

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

- `teaching_plan.periods[].time_allocation[].label` holds a full sentence of
  instruction rather than a segment name, so anything rendering it as a label
  gets a paragraph. The `minutes` beside it are correct.
- Equation-bearing chunks lose subscripts and Greek letters, which is the root
  cause of the grounding false positive above.

The script timeline itself is sound: period 1 runs 0-5, 5-15, 15-27, 27-35,
35-40, contiguous and summing to the period. `ScriptSegment` carries
`minute_start`/`minute_end` rather than a duration, which is what lets a teacher
read a wall clock instead of adding up.

## Files

| File | What it is |
|---|---|
| `teacher_knowledge_package.json` | The package, schema-versioned |
| `source.pdf` | The exact input, for reproduction |
| `lesson_plan.pdf`, `teacher_guide.pdf`, `assessment_book.pdf` | Rendered artifacts |
| `eval-report.json`, `eval-report.pdf` | Scored server-side, where the run's chunks are still reachable — so citation integrity actually runs instead of reporting itself unmeasurable |

## The single-file bundle

`teacher_knowledge_packages.json` holds `quantitative-physics` and
`narrative-history` in one file, for a submission portal that takes one upload.
Regenerate it with `python scripts/bundle_samples.py`; the per-directory copies
above are canonical and the bundle is a view over them.

`multilingual-hindi` is deliberately **not** in the bundle. It is a real run and
stays here as the evidence for the multilingual claim, but it is the same NCERT
chapter as `quantitative-physics` — so including it would make two of three
entries the same source document, which reads as padding rather than range.
