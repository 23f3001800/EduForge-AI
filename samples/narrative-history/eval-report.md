# Quality evaluation — History (narrative)

**0.87 / 1.00 — exemplary**

`#################...`  profile `narrative`, grade band `9-10`, package `22222222-2222-4222-8222-222222222222`

Deterministic metrics only.

| Dimension | Score | Weight | Method | Notes |
| --- | ---: | ---: | --- | --- |
| Objective quality |  0.95 | 0.12 | deterministic |  |
| Bloom distribution |  0.67 | 0.08 | deterministic |  |
| Coverage |  1.00 | 0.15 | deterministic |  |
| Sequencing and load |  1.00 | 0.08 | deterministic |  |
| Grounding |  0.74 | 0.15 | deterministic |  |
| Activity variety and runnability |  0.88 | 0.14 | deterministic |  |
| Differentiation |  0.97 | 0.08 | deterministic |  |
| Assessment integrity |  0.83 | 0.12 | deterministic |  |
| Classroom readiness |  0.81 | 0.08 | deterministic |  |

## Sub-metrics

**Objective quality** —  0.95

- `measurable_verb` 1.00 (weight 0.30) — leading verb denotes an observable act
- `bloom_honesty` 0.80 (weight 0.25) — declared level matches the verb
- `concept_linkage` 1.00 (weight 0.15) — resolves to a concept in this package
- `behaviour_not_label` 1.00 (weight 0.20) — not a topic with a verb attached
- `specificity` 1.00 (weight 0.10) — names a condition or context

**Bloom distribution** —  0.67

- `level_spread` 0.67 (weight 0.25) — 2 level(s) carry real marks
- `recall_ceiling` 1.00 (weight 0.25) — 0% of marks are recall
- `higher_order_floor` 0.00 (weight 0.25) — 0% of marks at analyze+
- `credible_claims` 1.00 (weight 0.15) — no MCQ claims a level it cannot test
- `objective_ladder` 1.00 (weight 0.10) — objectives span more than one level

**Coverage** —  1.00

- `concepts_taught` 1.00 (weight 0.16) — a period claims each concept
- `concepts_practised` 1.00 (weight 0.14) — an activity or checkpoint uses it
- `concepts_assessed` 1.00 (weight 0.16) — the bank carries marks for it
- `objectives_planned` 1.00 (weight 0.12) — a period is aimed at it
- `objectives_assessed` 1.00 (weight 0.18) — an item measures it
- `profile_required_fields` 1.00 (weight 0.12) — narrative requires concepts, examples
- `core_concepts_marked` 1.00 (weight 0.06) — core concepts carry marks
- `misconceptions_carried` 1.00 (weight 0.06) — extracted errors reach a gap

**Sequencing and load** —  1.00

- `prerequisites_respected` 1.00 (weight 0.35) — 1 prerequisite edge(s) checked
- `load_balance` 1.00 (weight 0.20) — concepts per period: [1, 1]
- `period_load` 1.00 (weight 0.20) — no period over- or under-filled
- `period_arc` 1.00 (weight 0.25) — introduce, practise, check, consolidate
- `periods_per_concept`       (reported, not scored) — 2 period(s) for 2 concepts (reported, not scored: there is no correct ratio)

**Grounding** —  0.74

- `citation_integrity` 1.00 (weight 0.55) — 7 evidence span(s) checked verbatim against the source
- `claim_support` 0.43 (weight 0.45) — 7 claim(s) checked; 2 in the ambiguous band (0.25-0.6), scored 0.5 and left for the judge

**Activity variety and runnability** —  0.88

- `type_variety` 1.00 (weight 0.25) — 2 distinct type(s) across 2
- `profile_fit` 0.00 (weight 0.10) — types the narrative profile weights
- `observable_criteria` 1.00 (weight 0.25) — visible during the lesson
- `instruction_specificity` 0.88 (weight 0.20) — runnable without edits
- `materials_realism` 1.00 (weight 0.10) — 2 activity(ies) list materials; listing none is a pass
- `distinct_activities` 1.00 (weight 0.10) — not the same activity repeated

**Differentiation** —  0.97

- `present` 1.00 (weight 0.15) — both sides filled in
- `specific` 0.94 (weight 0.40) — names something this package teaches
- `support_differs_from_extension` 1.00 (weight 0.15) — two routes, not one
- `extension_deepens` 1.00 (weight 0.15) — different demand, not more volume
- `distinct_across_activities` 1.00 (weight 0.15) — not copy-pasted between activities

**Assessment integrity** —  0.83

- `mcq_structure` 1.00 (weight 0.20) — 1 MCQ(s) checked
- `distractor_quality` 1.00 (weight 0.20) — plausible, explained, not filler
- `rubric_discrimination` 0.71 (weight 0.25) — 1 rubric(s)
- `marks_and_blueprint` 0.67 (weight 0.15) — 4 marks in the bank
- `kind_mix` 0.50 (weight 0.10) — against the narrative assessment mix
- `misconception_linkage` 1.00 (weight 0.10) — items trace to a diagnosed error

**Classroom readiness** —  0.81

- `script_usability` 0.75 (weight 0.25) — timed, board actions, questions ready
- `ticket_diagnostics` 0.75 (weight 0.20) — entry and exit tickets that diagnose
- `board_notes` 1.00 (weight 0.15) — headings and bullets, not prose
- `checkpoints` 1.00 (weight 0.15) — answerable mid-lesson checks
- `homework` 1.00 (weight 0.10) — names an output that can be handed in
- `distinct_periods` 0.50 (weight 0.15) — periods differ from each other
- `grade_readability`       (reported, not scored) — 9.8 words/sentence (band allows 22), 14% long words (allows 20%)

## Absent by design

Content this profile does not owe. Each line below is a **pass**, recorded so that an empty field is not mistaken for a failure.

- knowledge.formulae: empty, and the narrative profile does not require it — this is a pass, not a gap
- assessments: no 'numerical' items, which is what the narrative profile designs for — their absence is scored as correct

## Findings (13)

### Objective quality

- **OBJ_BLOOM_MISMATCH** `/knowledge/learning_objectives/0` — tagged 'understand' but 'state' denotes 'remember' (1 level(s) apart); either the verb or the tag is wrong

### Bloom distribution

- **BLOOM_NARROW_SPREAD** `/assessments/items` — marks land on 2 Bloom level(s) (apply, understand); the narrative profile expects at least 3
- **BLOOM_LOW_HIGHER_ORDER** `/assessments/items` — 0% of marks sit at analyze or above, against a 30% floor for this profile

### Grounding

- **GND_CLAIM_UNSUPPORTED** `/knowledge/examples/0` — shares 8% of its wording with the chunk it cites; the claim 'Passenger lurching forward When a bus brakes suddenly, passe' was not drawn from that passage
- **GND_CLAIM_UNSUPPORTED** `/knowledge/applications/0` — shares 17% of its wording with the chunk it cites; the claim 'Vehicle safety: Seat belts counter the forward motion a brak' was not drawn from that passage
- **GND_CLAIM_UNSUPPORTED** `/knowledge/misconceptions/0` — shares 24% of its wording with the chunk it cites; the claim 'A moving object must have a force acting on it to keep movin' was not drawn from that passage

### Activity variety and runnability

- **ACT_PROFILE_MISMATCH** `/activities` — no activity uses a type the narrative profile weights (debate, field_task, gallery_walk, group_discussion, role_play)
- **ACT_THIN_INSTRUCTIONS** `/activities/1/teacher_instructions` — 'Computing acceleration' lacks enough steps; a teacher reading this cold would have to invent the middle of it

### Assessment integrity

- **ASM_RUBRIC_WEAK** `/assessments/items/1/rubric` — lacks descriptors with substance, descriptors tied to the content; two markers would not agree on a borderline script
- **ASM_BLUEPRINT_DRIFT** `/assessments/blueprint` — blueprint item counts match the bank is false; the coverage story the package tells about itself no longer describes the bank it contains

### Classroom readiness

- **CLS_THIN_SCRIPT** `/classroom_content/0/teacher_script` — 1 of 5 segments in period 1 are too short to be read aloud as written
- **CLS_THIN_SCRIPT** `/classroom_content/1/teacher_script` — 1 of 5 segments in period 2 are too short to be read aloud as written
- **CLS_PERIODS_DUPLICATED** `/classroom_content` — only 50% of periods are distinct in their tickets, homework and anecdote; a teacher reading two periods in a row will see the package repeat itself
