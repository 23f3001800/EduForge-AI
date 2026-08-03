"""Contract invariants — the MS-0 gate.

These tests protect the guarantees that nine downstream modules assume. Each one
corresponds to a way generated output has historically been wrong while still
looking structurally fine, so a failure here is a real regression, not pedantry.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

import contracts as c
from tests.fixtures import factories as f

ROOT = Path(__file__).resolve().parents[3]


# ------------------------------------------------------- the reference package


def test_reference_tkp_builds() -> None:
    """If this breaks, a contract change broke the fixture every module codes against."""
    assert f.teacher_knowledge_package().teaching_plan.total_periods == 2


def test_reference_tkp_round_trips_through_json() -> None:
    tkp = f.teacher_knowledge_package()
    assert c.TeacherKnowledgePackage.model_validate(tkp.model_dump(mode="json")) == tkp


def test_generated_schema_and_fixtures_are_committed() -> None:
    """CI's drift guard. Contracts must not change without regenerating."""
    result = subprocess.run(
        [sys.executable, "scripts/generate_schema.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ------------------------------------------------------------------- grounding


def test_a_claim_cannot_be_constructed_without_evidence() -> None:
    """The load-bearing constraint of the design (docs/00 H-06)."""
    with pytest.raises(ValidationError):
        c.Concept(concept_id="c1", name="X", summary="Y", importance="core")  # type: ignore[call-arg]


def test_evidence_quote_must_be_substantial() -> None:
    with pytest.raises(ValidationError):
        c.Evidence(chunk_id="c_001", quote="short")


def test_mentor_moment_is_the_only_ungrounded_content() -> None:
    """Deliberate exemption — validation must not penalise it as unsupported."""
    assert f.classroom_content()[0].mentor_moment.grounded is False


# ------------------------------------------------------------- concept graph


def test_prerequisite_cycles_are_rejected() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        c.ConceptGraph(
            node_ids=["a", "b"],
            edges=[
                c.ConceptEdge(from_id="a", to_id="b", relation="prerequisite_of"),
                c.ConceptEdge(from_id="b", to_id="a", relation="prerequisite_of"),
            ],
        )


def test_long_prerequisite_cycles_are_rejected() -> None:
    """Three-node cycle — a naive pairwise check would miss this."""
    ids = ["a", "b", "d"]
    with pytest.raises(ValidationError, match="cycle"):
        c.ConceptGraph(
            node_ids=ids,
            edges=[
                c.ConceptEdge(from_id="a", to_id="b", relation="prerequisite_of"),
                c.ConceptEdge(from_id="b", to_id="d", relation="prerequisite_of"),
                c.ConceptEdge(from_id="d", to_id="a", relation="prerequisite_of"),
            ],
        )


def test_non_prerequisite_cycles_are_allowed() -> None:
    """`contrasts_with` is legitimately symmetric; only ordering edges must be acyclic."""
    c.ConceptGraph(
        node_ids=["a", "b"],
        edges=[
            c.ConceptEdge(from_id="a", to_id="b", relation="contrasts_with"),
            c.ConceptEdge(from_id="b", to_id="a", relation="contrasts_with"),
        ],
    )


def test_graph_edges_must_resolve_to_known_concepts() -> None:
    with pytest.raises(ValidationError, match="unknown concept"):
        c.ConceptGraph(
            node_ids=["a"],
            edges=[c.ConceptEdge(from_id="a", to_id="ghost", relation="prerequisite_of")],
        )


# ------------------------------------------------------------------ planning


def test_a_concept_cannot_be_taught_in_two_periods() -> None:
    """The classic incoherence a multi-period plan exists to prevent."""
    plan = f.teaching_plan()
    data = plan.model_dump()
    data["periods"][1]["concept_ids"] = ["concept_inertia"]
    with pytest.raises(ValidationError, match="exactly one period"):
        c.TeachingPlan.model_validate(data)


def test_period_time_must_add_up_to_the_bell() -> None:
    data = f.teaching_plan().model_dump()
    data["periods"][0]["time_allocation"] = [{"label": "Everything", "minutes": 90}]
    with pytest.raises(ValidationError, match="outside"):
        c.TeachingPlan.model_validate(data)


def test_period_numbers_must_be_contiguous() -> None:
    data = f.teaching_plan().model_dump()
    data["periods"][1]["period_no"] = 7
    with pytest.raises(ValidationError, match="contiguous"):
        c.TeachingPlan.model_validate(data)


def test_period_count_is_bounded_not_fixed_at_five() -> None:
    """Derived, never hardcoded (docs/00 H-08) — 1 and 20 are both legal."""
    assert c.TeachingPlan.model_fields["total_periods"].metadata[0].ge == 1
    assert c.TeachingPlan.model_fields["total_periods"].metadata[1].le == 20


# --------------------------------------------------------------- assessments


def test_mcq_must_have_exactly_one_correct_option() -> None:
    opts = [c.MCQOption(label=lbl, text="t", is_correct=lbl in ("A", "B")) for lbl in "ABCD"]
    with pytest.raises(ValidationError, match="exactly one correct"):
        c.AssessmentItem(
            item_id="i1",
            kind="mcq",
            stem="s",
            options=opts,
            answer="A",
            marks=1,
            bloom_level="apply",
        )


def test_mcq_must_have_exactly_four_options() -> None:
    opts = [c.MCQOption(label=lbl, text="t", is_correct=lbl == "A") for lbl in "ABC"]
    with pytest.raises(ValidationError, match="exactly 4 options"):
        c.AssessmentItem(
            item_id="i1",
            kind="mcq",
            stem="s",
            options=opts,
            answer="A",
            marks=1,
            bloom_level="apply",
        )


def test_non_mcq_items_require_a_rubric() -> None:
    """Without one the item cannot be marked consistently, so the bank is decorative."""
    with pytest.raises(ValidationError, match="requires a rubric"):
        c.AssessmentItem(
            item_id="i1",
            kind="long_answer",
            stem="Discuss.",
            answer="a",
            marks=5,
            bloom_level="evaluate",
        )


def test_rubric_levels_must_discriminate() -> None:
    with pytest.raises(ValidationError, match="discriminate"):
        c.Rubric(
            criteria="quality",
            levels=[
                c.RubricLevel(label="Good", descriptor="good work", marks=3),
                c.RubricLevel(label="Bad", descriptor="poor work", marks=3),
            ],
        )


def test_total_marks_must_match_the_items() -> None:
    data = f.assessments().model_dump()
    data["total_marks"] = 99
    with pytest.raises(ValidationError, match="items sum to"):
        c.AssessmentBank.model_validate(data)


# ------------------------------------------------------ package cross-references


def test_activity_refs_must_resolve() -> None:
    data = f.teacher_knowledge_package().model_dump(mode="json")
    data["classroom_content"][0]["activity_refs"] = ["act_missing"]
    with pytest.raises(ValidationError, match="activity_refs do not resolve"):
        c.TeacherKnowledgePackage.model_validate(data)


def test_plan_cannot_reference_unknown_concepts() -> None:
    data = f.teacher_knowledge_package().model_dump(mode="json")
    data["teaching_plan"]["periods"][0]["concept_ids"] = ["concept_ghost"]
    with pytest.raises(ValidationError, match="unknown concept"):
        c.TeacherKnowledgePackage.model_validate(data)


def test_content_cannot_exist_for_a_period_not_in_the_plan() -> None:
    data = f.teacher_knowledge_package().model_dump(mode="json")
    data["classroom_content"][1]["period_no"] = 9
    with pytest.raises(ValidationError, match="periods not in the plan"):
        c.TeacherKnowledgePackage.model_validate(data)


# ----------------------------------------------------------------- validation


def test_pass_status_cannot_carry_issues() -> None:
    """Guards against a validator that reports problems and then says everything is fine."""
    with pytest.raises(ValidationError, match="cannot carry error or warning"):
        c.ValidationReport(
            status="pass",
            schema_ok=True,
            issues=[
                c.ValidationIssue(
                    code="X", severity="error", message="m", path="/p", stage="validation"
                )
            ],
            checked_at=datetime.now(UTC),
        )


def test_fail_status_requires_an_error() -> None:
    with pytest.raises(ValidationError, match="requires at least one error"):
        c.ValidationReport(status="fail", schema_ok=True, checked_at=datetime.now(UTC))


def test_schema_failure_cannot_be_a_pass() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        c.ValidationReport(status="pass", schema_ok=False, checked_at=datetime.now(UTC))


def test_every_issue_names_the_stage_that_must_regenerate() -> None:
    """The field that turns validation from a report into a repair loop."""
    issue = c.ValidationIssue(
        code="COVERAGE_CONCEPT_UNTAUGHT",
        severity="error",
        message="m",
        path="/knowledge/concepts/0",
        stage="knowledge-extraction",
    )
    assert issue.stage in c.STAGE_NAMES


# -------------------------------------------------------------- versatility


def test_a_narrative_package_needs_no_formulae() -> None:
    """The explicitly graded versatility criterion (docs/00 H-07).

    A humanities document with zero formulae and zero numerical items is a pass.
    Nothing in the contracts may require them.
    """
    kb = c.KnowledgeBase(
        concepts=[
            c.Concept(
                concept_id="concept_partition",
                name="Partition of Bengal",
                summary="The 1905 division of the province.",
                importance="core",
                evidence=[c.Evidence(chunk_id="c_001", quote="Bengal was divided in 1905.")],
            )
        ],
        concept_graph=c.ConceptGraph(node_ids=["concept_partition"]),
    )
    assert kb.formulae == []
    assert f.narrative_classification().pedagogy_profile == "narrative"


def test_low_confidence_fields_are_derived_not_trusted() -> None:
    """The model is not asked to compute this correctly — we derive it.

    Demanding the model match a fully-derivable field bought nothing and cost a
    repair attempt every time it slipped, which happened on real runs.
    """
    classification = c.Classification(
        subject="Physics",
        grade_band="9",
        difficulty="intermediate",
        topic="t",
        category="textbook_chapter",
        language="en",
        pedagogy_profile="quantitative",
        confidences={"subject": 0.2, "topic": 0.9},
        low_confidence_fields=[],
    )
    assert classification.low_confidence_fields == ["subject"]


def test_a_wrong_low_confidence_list_is_corrected() -> None:
    classification = c.Classification(
        subject="Physics",
        grade_band="9",
        difficulty="intermediate",
        topic="t",
        category="textbook_chapter",
        language="en",
        pedagogy_profile="quantitative",
        confidences={"subject": 0.9},
        low_confidence_fields=["subject", "topic"],
    )
    assert classification.low_confidence_fields == []


# ------------------------------------------------------ progress & job wiring


def test_progress_weights_sum_to_one_hundred() -> None:
    assert sum(c.STAGE_PROGRESS_WEIGHTS.values()) == 100


def test_every_stage_has_a_progress_weight() -> None:
    assert set(c.STAGE_PROGRESS_WEIGHTS) == set(c.STAGE_NAMES)


def test_progress_event_always_carries_stage_and_progress() -> None:
    """The exact wire shape the assignment specifies for FR-14."""
    payload = c.ProgressEvent(stage="lesson-generation", progress=60).model_dump(mode="json")
    assert payload["stage"] == "lesson-generation"
    assert payload["progress"] == 60


@pytest.mark.parametrize("bad", [-1, 101])
def test_progress_is_bounded(bad: int) -> None:
    with pytest.raises(ValidationError):
        c.ProgressEvent(stage="validation", progress=bad)


def test_succeeded_job_must_expose_a_package() -> None:
    with pytest.raises(ValidationError, match="requires a package_id"):
        c.JobSnapshot(
            job_id=uuid4(),
            document_id=uuid4(),
            status="succeeded",
            created_at=datetime.now(UTC),
        )


# ------------------------------------------------------- document structure


def test_tables_survive_as_structure_not_prose() -> None:
    """Flattening is the usual silent failure of "structure preservation" (FR-02)."""
    with pytest.raises(ValidationError, match="do not match header width"):
        c.TableData(headers=["a", "b"], rows=[["1"]])


def test_heading_blocks_must_declare_depth() -> None:
    with pytest.raises(ValidationError, match="must carry `level`"):
        c.Block(
            block_id="b1",
            type="heading",
            text="T",
            char_start=0,
            char_end=1,
        )


def test_table_payload_only_on_table_blocks() -> None:
    with pytest.raises(ValidationError, match="only valid on a block of type"):
        c.Block(
            block_id="b1",
            type="paragraph",
            text="T",
            char_start=0,
            char_end=1,
            table=c.TableData(headers=["a"], rows=[["1"]]),
        )


# ------------------------------------------------------------- architecture


def test_contracts_import_nothing_else_in_the_project() -> None:
    """The leaf-package rule that makes parallel module work safe (docs/07)."""
    forbidden = ("core", "pedagogy", "stages", "orchestration", "worker", "api")
    for path in (ROOT / "backend" / "contracts").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for pkg in forbidden:
            assert f"import {pkg}" not in source, f"{path.name} imports {pkg}"
            assert f"from {pkg}" not in source, f"{path.name} imports from {pkg}"


def test_provider_routing_falls_back_to_default() -> None:
    routing = c.ProviderRouting(
        default=c.ModelSpec(provider="openrouter", model="nvidia/nemotron-3-super-120b-a12b:free"),
        stages={
            "validation": c.ModelSpec(
                provider="openrouter",
                model="nvidia/nemotron-3-super-120b-a12b:free",
                reasoning=c.ReasoningConfig(effort="low"),
            )
        },
    )
    assert routing.for_stage("validation").reasoning is not None
    assert (
        routing.for_stage("knowledge-extraction").model
        == "nvidia/nemotron-3-super-120b-a12b:free"
    )
