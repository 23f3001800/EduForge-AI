"""Canonical fixtures — the reference instance of every stage contract.

Every downstream module codes against these instead of against each other. A
stubbed stage returns its fixture; a test asserts against it; the frontend renders
it before any real pipeline exists. That is what makes Wave 2 parallelism work.

This is deliberately a *factory*, not a checked-in blob of JSON. Hand-maintaining
a 700-line JSON document across contract changes is how fixtures rot; generating
it means a contract change either still builds a valid package or fails loudly in
CI. ``scripts/generate_fixtures.py`` serialises these to JSON for consumers that
need a file (the frontend, the API examples).

The subject is deliberately quantitative (physics, with formulae and a numerical
item). ``narrative_classification()`` provides the humanities counterpart used to
prove that profile-conditioned validation does not require formulae.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from contracts import (
    Activity,
    Application,
    AssessmentBank,
    AssessmentBlueprint,
    AssessmentItem,
    BlackboardNotes,
    Block,
    CheckpointQuestion,
    Chunk,
    Classification,
    Concept,
    ConceptEdge,
    ConceptGraph,
    ConsistencyReport,
    CoverageReport,
    Definition,
    DiagnosticQuestion,
    Differentiation,
    DocumentMetadata,
    DocumentStats,
    EntryTicket,
    Evidence,
    Example,
    ExitTicket,
    Formula,
    GeneratorInfo,
    Homework,
    JobOptions,
    KnowledgeBase,
    LearningGap,
    LearningObjective,
    MCQOption,
    MentorMoment,
    Misconception,
    Period,
    PeriodContent,
    Prerequisite,
    Provenance,
    RemediationStep,
    Rubric,
    RubricLevel,
    ScriptSegment,
    StageTiming,
    StructuredDocument,
    TeacherKnowledgePackage,
    TeachingPlan,
    TimeSlot,
    VariableDef,
)

DOC_ID = UUID("11111111-1111-4111-8111-111111111111")
TKP_ID = UUID("22222222-2222-4222-8222-222222222222")
FIXED_TIME = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)

PERIOD_MINUTES = 40


def _ev(chunk: str, quote: str, page: int = 1) -> list[Evidence]:
    return [Evidence(chunk_id=chunk, page=page, quote=quote)]


# ----------------------------------------------------------------- stage 1 ---


def document_metadata() -> DocumentMetadata:
    return DocumentMetadata(
        filename="newtons-laws.pdf",
        mime="application/pdf",
        sha256="a" * 64,
        size_bytes=184_320,
        page_count=12,
        word_count=3_400,
        title="Newton's Laws of Motion",
        author="NCERT",
        created_at=FIXED_TIME,
        detected_language="en",
    )


def structured_document() -> StructuredDocument:
    return StructuredDocument(
        document_id=DOC_ID,
        metadata=document_metadata(),
        blocks=[
            Block(
                block_id="b_001",
                type="heading",
                text="Newton's Laws of Motion",
                page=1,
                section_path=["Chapter 5"],
                level=1,
                char_start=0,
                char_end=24,
            ),
            Block(
                block_id="b_002",
                type="paragraph",
                text=(
                    "A body continues in its state of rest or uniform motion in a "
                    "straight line unless acted upon by an external unbalanced force."
                ),
                page=1,
                section_path=["Chapter 5", "5.1 First Law"],
                char_start=25,
                char_end=160,
            ),
            Block(
                block_id="b_003",
                type="equation",
                text="F = m a",
                latex=r"\vec{F} = m\vec{a}",
                page=2,
                section_path=["Chapter 5", "5.2 Second Law"],
                char_start=161,
                char_end=168,
            ),
        ],
        outline=[],
        stats=DocumentStats(headings=1, paragraphs=1, equations=1),
    )


def chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id="c_001",
            document_id=DOC_ID,
            ordinal=0,
            text=(
                "A body continues in its state of rest or uniform motion in a straight "
                "line unless acted upon by an external unbalanced force."
            ),
            page=1,
            section_path=["Chapter 5", "5.1 First Law"],
            token_count=28,
            block_ids=["b_002"],
        ),
        Chunk(
            chunk_id="c_002",
            document_id=DOC_ID,
            ordinal=1,
            text="The acceleration of a body is proportional to the net force: F = m a.",
            page=2,
            section_path=["Chapter 5", "5.2 Second Law"],
            token_count=18,
            block_ids=["b_003"],
        ),
    ]


# ----------------------------------------------------------------- stage 2 ---


def classification() -> Classification:
    return Classification(
        subject="Physics",
        grade_band="9-10",
        difficulty="intermediate",
        topic="Newton's Laws of Motion",
        chapter="Chapter 5",
        category="textbook_chapter",
        language="en",
        pedagogy_profile="quantitative",
        confidences={"subject": 0.97, "grade_band": 0.88, "topic": 0.95},
        low_confidence_fields=[],
    )


def narrative_classification() -> Classification:
    """Humanities counterpart.

    Used to prove that a package with zero formulae and zero numerical items is a
    *pass*, not a gap — the versatility criterion is explicitly graded and a
    STEM-shaped validator would fail every document like this one.
    """
    return Classification(
        subject="History",
        grade_band="9-10",
        difficulty="intermediate",
        topic="The Partition of Bengal",
        chapter="Chapter 2",
        category="textbook_chapter",
        language="en",
        pedagogy_profile="narrative",
        confidences={"subject": 0.94, "grade_band": 0.71, "chapter": 0.42},
        low_confidence_fields=["chapter"],
    )


# ----------------------------------------------------------------- stage 3 ---


def knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        learning_objectives=[
            LearningObjective(
                objective_id="obj_1",
                statement="State Newton's first law and identify it acting in everyday situations.",
                bloom_level="understand",
                concept_ids=["concept_inertia"],
            ),
            LearningObjective(
                objective_id="obj_2",
                statement="Calculate the acceleration of a body given net force and mass.",
                bloom_level="apply",
                concept_ids=["concept_second_law"],
            ),
        ],
        prerequisites=[
            Prerequisite(statement="Familiarity with speed, velocity, and mass.", concept_ids=[])
        ],
        concepts=[
            Concept(
                concept_id="concept_inertia",
                name="Inertia",
                summary="A body resists any change to its state of rest or uniform motion.",
                importance="core",
                evidence=_ev("c_001", "A body continues in its state of rest or uniform motion"),
            ),
            Concept(
                concept_id="concept_second_law",
                name="Newton's Second Law",
                summary="Net force equals mass times acceleration.",
                importance="core",
                evidence=_ev(
                    "c_002", "The acceleration of a body is proportional to the net force", 2
                ),
            ),
        ],
        definitions=[
            Definition(
                term="Inertia",
                definition="The tendency of a body to resist a change in its state of motion.",
                concept_ids=["concept_inertia"],
                evidence=_ev("c_001", "unless acted upon by an external unbalanced force"),
            )
        ],
        formulae=[
            Formula(
                name="Newton's Second Law",
                latex=r"\vec{F} = m\vec{a}",
                plain="F equals m times a",
                variables=[
                    VariableDef(symbol="F", meaning="net force", unit="N"),
                    VariableDef(symbol="m", meaning="mass", unit="kg"),
                    VariableDef(symbol="a", meaning="acceleration", unit="m/s^2"),
                ],
                concept_ids=["concept_second_law"],
                evidence=_ev("c_002", "the net force: F = m a", 2),
            )
        ],
        keywords=["inertia", "force", "acceleration", "mass"],
        examples=[
            Example(
                title="Passenger lurching forward",
                body="When a bus brakes suddenly, passengers continue moving forward.",
                concept_ids=["concept_inertia"],
                evidence=_ev("c_001", "continues in its state of rest or uniform motion"),
            )
        ],
        applications=[
            Application(
                context="Vehicle safety",
                description="Seat belts counter the forward motion a braking passenger retains.",
                concept_ids=["concept_inertia"],
                evidence=_ev("c_001", "unless acted upon by an external unbalanced force"),
            )
        ],
        misconceptions=[
            Misconception(
                misconception_id="mis_1",
                statement="A moving object must have a force acting on it to keep moving.",
                why_it_happens="Everyday motion always involves friction, hiding the ideal case.",
                correction=(
                    "Uniform motion needs no net force; friction is what requires opposing it."
                ),
                concept_ids=["concept_inertia"],
                evidence=_ev("c_001", "unless acted upon by an external unbalanced force"),
            )
        ],
        concept_graph=ConceptGraph(
            node_ids=["concept_inertia", "concept_second_law"],
            edges=[
                ConceptEdge(
                    from_id="concept_inertia",
                    to_id="concept_second_law",
                    relation="prerequisite_of",
                    confidence=0.9,
                )
            ],
        ),
    )


# ----------------------------------------------------------------- stage 4 ---


def teaching_plan() -> TeachingPlan:
    return TeachingPlan(
        total_periods=2,
        period_duration_minutes=PERIOD_MINUTES,
        periods=[
            Period(
                period_no=1,
                title="Inertia and the First Law",
                objective_ids=["obj_1"],
                concept_ids=["concept_inertia"],
                time_allocation=[
                    TimeSlot(label="Entry ticket", minutes=5),
                    TimeSlot(label="Direct instruction", minutes=15),
                    TimeSlot(label="Activity", minutes=12),
                    TimeSlot(label="Checkpoint", minutes=5),
                    TimeSlot(label="Exit ticket", minutes=3),
                ],
                sequence_rationale=(
                    "Inertia is the prerequisite for the second law, so it is taught first."
                ),
            ),
            Period(
                period_no=2,
                title="Force, Mass and Acceleration",
                objective_ids=["obj_2"],
                concept_ids=["concept_second_law"],
                time_allocation=[
                    TimeSlot(label="Entry ticket", minutes=5),
                    TimeSlot(label="Derivation", minutes=15),
                    TimeSlot(label="Problem set", minutes=12),
                    TimeSlot(label="Checkpoint", minutes=5),
                    TimeSlot(label="Exit ticket", minutes=3),
                ],
                sequence_rationale="Builds quantitatively on the qualitative idea of inertia.",
            ),
        ],
    )


# ------------------------------------------------------------- stages 5 & 6 ---


def activities() -> list[Activity]:
    return [
        Activity(
            activity_id="act_1",
            period_no=1,
            type="demonstration",
            title="Coin and card",
            duration_minutes=12,
            materials=["A stiff card", "A coin", "A glass"],
            teacher_instructions=[
                "Balance the card on the glass with the coin on top.",
                "Flick the card horizontally and have students predict what happens.",
            ],
            student_instructions=["Predict, then observe, then explain using inertia."],
            success_criteria=[
                "Student predicts the coin falls into the glass.",
                "Student explains it using resistance to a change in motion.",
            ],
            differentiation=Differentiation(
                support="Provide a sentence frame: 'The coin stayed still because...'",
                extension="Ask what changes if the card is flicked slowly, and why.",
            ),
            concept_ids=["concept_inertia"],
        ),
        Activity(
            activity_id="act_2",
            period_no=2,
            type="problem_set",
            title="Computing acceleration",
            duration_minutes=12,
            materials=["Worksheet", "Calculator"],
            teacher_instructions=["Work the first item aloud, then release students to pairs."],
            student_instructions=["Solve for a given F and m; state units at every step."],
            success_criteria=["Correct value with correct units on at least three items."],
            differentiation=Differentiation(
                support="Provide the rearranged formula a = F/m on the sheet.",
                extension="Introduce a two-force problem requiring a net force first.",
            ),
            concept_ids=["concept_second_law"],
        ),
    ]


def _period_content(period_no: int, title: str, activity_ref: str) -> PeriodContent:
    return PeriodContent(
        period_no=period_no,
        entry_ticket=EntryTicket(
            prompt="Name one situation where something kept moving after you stopped pushing it.",
            expected_response="Any example of continued motion, e.g. a rolling ball.",
            duration_minutes=5,
        ),
        teacher_script=[
            ScriptSegment(
                minute_start=0,
                minute_end=5,
                heading="Entry ticket",
                speaker_notes="Collect two or three answers without correcting them yet.",
                board_action="Write the three best student examples in a column.",
            ),
            ScriptSegment(
                minute_start=5,
                minute_end=20,
                heading=title,
                speaker_notes=(
                    "Introduce the idea using the student examples already on the board, "
                    "then state the law formally."
                ),
                board_action="Write the formal statement beneath the examples.",
                anticipated_questions=["Why does a rolling ball eventually stop?"],
            ),
            ScriptSegment(
                minute_start=20,
                minute_end=32,
                heading="Activity",
                speaker_notes="Run the activity; circulate and listen for the misconception.",
            ),
            ScriptSegment(
                minute_start=32,
                minute_end=37,
                heading="Checkpoint",
                speaker_notes="Pose the checkpoint question; take a show of hands before answers.",
            ),
            ScriptSegment(
                minute_start=37,
                minute_end=40,
                heading="Exit ticket",
                speaker_notes="Collect exit tickets at the door.",
            ),
        ],
        blackboard_notes=BlackboardNotes(
            headings=[title],
            bullet_points=["Resists change in motion", "Needs an external unbalanced force"],
            diagrams_to_draw=["Block on a surface with force arrows"],
            formulae_latex=[r"\vec{F} = m\vec{a}"],
        ),
        activity_refs=[activity_ref],
        checkpoint_questions=[
            CheckpointQuestion(
                question="A book rests on a table. Is a force acting on it?",
                expected_answer=(
                    "Yes — gravity and the normal force, which balance to zero net force."
                ),
                bloom_level="understand",
                concept_ids=["concept_inertia"],
            )
        ],
        exit_ticket=ExitTicket(
            prompt="In one sentence, why do passengers lurch forward when a bus brakes?",
            success_indicator="Answer refers to continued motion, not to a forward force.",
            duration_minutes=3,
        ),
        homework=Homework(
            tasks=["Find two examples of inertia at home and explain each in one sentence."],
            estimated_minutes=20,
            submission_format="Notebook",
        ),
        mentor_moment=MentorMoment(
            title="Newton in a plague year",
            story=(
                "Newton developed much of his work on motion while Cambridge was closed "
                "during an outbreak, working alone at his family home."
            ),
            takeaway="Progress often comes from steady thinking in unpromising conditions.",
        ),
    )


def classroom_content() -> list[PeriodContent]:
    return [
        _period_content(1, "Inertia and the First Law", "act_1"),
        _period_content(2, "Force, Mass and Acceleration", "act_2"),
    ]


# ----------------------------------------------------------------- stage 7 ---


def assessments() -> AssessmentBank:
    items = [
        AssessmentItem(
            item_id="item_1",
            kind="mcq",
            stem="A bus brakes suddenly and passengers lurch forward. Why?",
            options=[
                MCQOption(
                    label="A",
                    text="A forward force acts on them",
                    is_correct=False,
                    rationale="Targets the belief that motion requires a force.",
                ),
                MCQOption(
                    label="B", text="They continue moving while the bus slows", is_correct=True
                ),
                MCQOption(
                    label="C",
                    text="Gravity increases during braking",
                    is_correct=False,
                    rationale="Confuses weight with motion.",
                ),
                MCQOption(label="D", text="Air pressure pushes them forward", is_correct=False),
            ],
            answer="B",
            marks=1,
            bloom_level="understand",
            concept_ids=["concept_inertia"],
            linked_misconception_id="mis_1",
        ),
        AssessmentItem(
            item_id="item_2",
            kind="numerical",
            stem="A 4 kg trolley experiences a net force of 12 N. Find its acceleration.",
            answer="3 m/s^2",
            working="a = F/m = 12 N / 4 kg = 3 m/s^2",
            marks=3,
            bloom_level="apply",
            concept_ids=["concept_second_law"],
            rubric=Rubric(
                criteria="Correct method, substitution, and units",
                levels=[
                    RubricLevel(label="Complete", descriptor="Correct value with units.", marks=3),
                    RubricLevel(
                        label="Partial", descriptor="Correct method, wrong units.", marks=2
                    ),
                    RubricLevel(label="Minimal", descriptor="Formula stated only.", marks=1),
                ],
            ),
        ),
    ]
    return AssessmentBank(
        items=items,
        blueprint=AssessmentBlueprint(
            items_by_kind={"mcq": 1, "numerical": 1},
            items_by_bloom={"understand": 1, "apply": 1},
            marks_by_concept={"concept_inertia": 1, "concept_second_law": 3},
        ),
        total_marks=4,
    )


# ----------------------------------------------------------------- stage 8 ---


def learning_gaps() -> list[LearningGap]:
    return [
        LearningGap(
            gap_id="gap_1",
            misconception="Motion requires a continuously applied force.",
            concept_ids=["concept_inertia"],
            severity="high",
            diagnostic_questions=[
                DiagnosticQuestion(
                    question="A puck slides on frictionless ice. What force keeps it moving?",
                    reveals="Naming any force shows the misconception is still held.",
                    expected_wrong_answer="A forward force from the push.",
                )
            ],
            remediation=[
                RemediationStep(
                    action="Contrast a low-friction and a high-friction surface side by side.",
                    rationale=(
                        "Isolates friction as the cause of stopping, not the absence of force."
                    ),
                    estimated_minutes=10,
                )
            ],
            evidence=_ev("c_001", "unless acted upon by an external unbalanced force"),
        )
    ]


# ----------------------------------------------------------------- stage 9 ---


def validation_report() -> object:
    from contracts import ValidationReport

    return ValidationReport(
        status="pass",
        schema_ok=True,
        coverage=CoverageReport(
            concepts_total=2,
            concepts_taught=2,
            objectives_total=2,
            objectives_planned=2,
            objectives_assessed=2,
        ),
        consistency=ConsistencyReport(timing_ok=True),
        grounding_score=1.0,
        unsupported_claims=[],
        issues=[],
        profile_ruleset="quantitative",
        checked_at=FIXED_TIME,
    )


# ---------------------------------------------------------------- stage 10 ---


def job_options() -> JobOptions:
    return JobOptions(period_duration_minutes=PERIOD_MINUTES)


def teacher_knowledge_package() -> TeacherKnowledgePackage:
    """The reference TKP. If this stops building, a contract change broke something."""
    return TeacherKnowledgePackage(
        tkp_id=TKP_ID,
        generated_at=FIXED_TIME,
        generator=GeneratorInfo(
            app_version="0.1.0",
            models_by_stage={"knowledge-extraction": "claude-opus-5"},
            providers_by_stage={"knowledge-extraction": "anthropic"},
        ),
        source=document_metadata(),
        classification=classification(),
        knowledge=knowledge_base(),
        teaching_plan=teaching_plan(),
        classroom_content=classroom_content(),
        activities=activities(),
        assessments=assessments(),
        learning_gaps=learning_gaps(),
        validation=validation_report(),  # type: ignore[arg-type]
        provenance=Provenance(
            stage_timings=[StageTiming(stage="knowledge-extraction", duration_ms=31_500)],
            total_tokens_in=184_300,
            total_tokens_out=41_200,
            total_cost_usd=2.14,
            total_duration_ms=96_000,
        ),
    )
