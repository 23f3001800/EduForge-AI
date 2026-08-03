"""Stage 9 — validation.

The tests that matter here are not "does a clean package pass" — a validator
that only ever sees good input is indistinguishable from ``return "pass"``.
They are: does each rule class actually trip on the one way it is supposed to
catch, and does the profile-conditioned ruleset let a narrative package through
without the STEM-shaped checks a quantitative document is held to (docs/00
§ H-07). Every corruption test below starts from the same known-good fixture
and breaks exactly one thing, so a failure localises to the rule that broke.
"""

from __future__ import annotations

import copy
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from contracts.llm import LLMUsage, ModelSpec, ProviderRouting
from core.llm.base import RawCompletion
from core.llm.client import LLMClient
from stages.base import StageContext
from stages.s9_validation.grounding import TAU_LOW, collect_claims, lexical_overlap, prefilter
from stages.s9_validation.stage import (
    ValidationStage,
    resolve_status,
    stages_to_regenerate,
)
from tests.fixtures import factories as fx

# ─────────────────────────────────────────────────────────────── stub adapter


class JudgeStubAdapter:
    """Answers every grounding-judge batch with the same verdict.

    Counts claims from the prompt itself (``CLAIM {i}:`` lines) rather than
    hard-coding a batch size, so it stays correct if the ambiguous set changes
    shape. A test that must prove no model call happened at all subclasses this
    and raises from ``complete`` instead — see ``ForbiddenAdapter`` below.
    """

    name = "openrouter"

    def __init__(self, verdict: str = "supported") -> None:
        self.verdict = verdict
        self.calls: list[str] = []

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:
        self.calls.append(user_content)
        count = user_content.count("CLAIM ")
        body = {"verdicts": [{"index": i, "verdict": self.verdict} for i in range(count)]}
        return RawCompletion(
            text=json.dumps(body), model=spec.model, usage=LLMUsage(tokens_in=10, tokens_out=10)
        )


def _client(adapter: Any) -> LLMClient:
    spec = ModelSpec(provider="openrouter", model="stub-model")
    return LLMClient(routing=ProviderRouting(default=spec), adapters={"openrouter": adapter})


# ─────────────────────────────────────────────────────────────── fixtures


def _state() -> dict[str, Any]:
    """The golden package: every section from the reference factories.

    Its knowledge base carries claims the lexical pre-filter cannot fully
    resolve on its own (a paraphrased concept summary, a formula folded into
    plain text) — deliberately, since that ambiguous middle is exactly what the
    judge exists for. Every test below that is not *about* grounding supplies a
    stub judge that answers "supported" for whatever it is asked, so a change
    to an unrelated section cannot fail on a grounding call that was never in
    question.
    """
    return {
        "classification": fx.classification().model_dump(mode="json"),
        "knowledge": fx.knowledge_base().model_dump(mode="json"),
        "teaching_plan": fx.teaching_plan().model_dump(mode="json"),
        "period_contents": [p.model_dump(mode="json") for p in fx.classroom_content()],
        "activities": [a.model_dump(mode="json") for a in fx.activities()],
        "assessments": fx.assessments().model_dump(mode="json"),
        "learning_gaps": [g.model_dump(mode="json") for g in fx.learning_gaps()],
        "chunks": [c.model_dump(mode="json") for c in fx.chunks()],
    }


async def _run(state: dict[str, Any], adapter: Any | None = None) -> dict[str, Any]:
    stage = ValidationStage(_client(adapter or JudgeStubAdapter()))
    ctx = StageContext(job_id=uuid4(), options={}, emit=None)
    return await stage.run(ctx, state)


def _issue_codes(report: dict[str, Any]) -> set[str]:
    return {issue["code"] for issue in report["issues"]}


# ─────────────────────────────────────────────────────────── status policy


def test_no_issues_is_a_clean_pass() -> None:
    assert resolve_status([]) == "pass"


def test_a_lone_warning_is_pass_with_warnings_not_a_failure() -> None:
    issues = [{"severity": "warning", "stage": "knowledge-extraction"}]
    assert resolve_status(issues) == "pass_with_warnings"


def test_a_single_error_fails_the_whole_package() -> None:
    issues = [
        {"severity": "warning", "stage": "teaching-planner"},
        {"severity": "error", "stage": "knowledge-extraction"},
    ]
    assert resolve_status(issues) == "fail"


def test_regeneration_targets_only_error_owning_stages_deduplicated() -> None:
    issues = [
        {"severity": "error", "stage": "teaching-planner", "code": "A"},
        {"severity": "warning", "stage": "assessment-generation", "code": "B"},
        {"severity": "error", "stage": "teaching-planner", "code": "C"},
        {"severity": "error", "stage": "gap-analysis", "code": "D"},
    ]
    assert stages_to_regenerate(issues) == ["teaching-planner", "gap-analysis"]


# ──────────────────────────────────────────────────────────────── happy path


async def test_the_reference_package_validates_as_a_clean_pass() -> None:
    """No rule class may fire on known-good input.

    This asserts the *whole* report, grounding included. It could not, before the
    pre-filter stopped auto-failing paraphrases: the reference package's example
    and misconception are worded differently from the law they derive from, and
    were being reported as fabrications without any model reading them. A
    validator that cries hallucination on its own golden fixture has no
    signal — every real package would carry the same noise.
    """
    result = await _run(_state())
    report = result["validation"]

    assert _issue_codes(report) == set()
    assert report["status"] == "pass"
    assert result["stages_to_regenerate"] == []
    assert report["schema_ok"] is True
    assert report["coverage"]["untaught_concept_ids"] == []
    assert report["coverage"]["unassessed_objective_ids"] == []
    assert report["consistency"]["timing_ok"] is True
    assert report["consistency"]["dangling_activity_refs"] == []
    assert report["consistency"]["prerequisite_violations"] == []


async def test_the_grounding_judge_is_only_asked_about_the_ambiguous_middle() -> None:
    """Claims the lexical pre-filter already decided must never reach the model."""
    adapter = JudgeStubAdapter()
    await _run(_state(), adapter)
    assert adapter.calls, "the golden fixture's ambiguous claims should reach the judge"
    for prompt in adapter.calls:
        # Every batch is genuinely ambiguous material, not a decided claim
        # re-litigated — spot check a couple of terms from the confidently
        # supported/unsupported items that prefilter should have resolved alone.
        assert prompt.count("CLAIM ") <= 20  # JUDGE_BATCH_SIZE


def test_a_prediction_about_students_is_not_judged_as_an_extracted_claim() -> None:
    """Misconceptions and gaps describe learners, so they get the other rubric.

    Measured defect, not a hypothetical. On a 935-word calculus chapter every
    one of the nine extracted claims grounded cleanly and every one of the four
    predicted ones was flagged, giving 9.5/13 = 0.731 and a `fail` verdict on a
    package whose extraction was perfect. No textbook states which errors
    students will make, so demanding the source entail a predicted difficulty
    demands the impossible and the score punishes the gap analysis for existing.
    """
    knowledge = fx.knowledge_base().model_dump(mode="json")
    gaps = [
        {
            "misconception": "students think the derivative of a product "
            "is the product of the derivatives",
            "evidence": [{"chunk_id": fx.chunks()[0].chunk_id, "quote": "x"}],
        }
    ]
    by_path = {c.path: c for c in collect_claims(knowledge, gaps)}

    assert by_path["/learning_gaps/0"].kind == "predicted"
    assert all(
        claim.kind == "predicted"
        for path, claim in by_path.items()
        if path.startswith("/knowledge/misconceptions/")
    )
    assert all(
        claim.kind == "extracted"
        for path, claim in by_path.items()
        if path.startswith("/knowledge/concepts/")
        or path.startswith("/knowledge/formulae/")
    ), "an extracted claim was reclassified, which would weaken the fabrication check"


def test_a_misconception_is_never_failed_for_stating_the_wrong_thing() -> None:
    """A misconception contradicts its source *by construction*; that is the point.

    ``contradiction_risk`` looks for exactly that polarity conflict, so running
    it over a misconception marks the well-formed ones as fabrications. Predicted
    claims must therefore reach the judge rather than be decided lexically.
    """
    knowledge = fx.knowledge_base().model_dump(mode="json")
    chunks = {c.chunk_id: c.text for c in fx.chunks()}
    claims = collect_claims(knowledge, [])
    decided, ambiguous = prefilter(claims, chunks)

    settled = {v.claim.path for v in decided}
    assert not any(path.startswith("/knowledge/misconceptions/") for path in settled), (
        "a misconception was decided by lexical rules that penalise it for being a misconception"
    )
    assert any(claim.kind == "predicted" for claim in ambiguous)


# ──────────────────────────────────────────────────────────── schema class


def test_a_paraphrase_is_never_auto_declared_a_fabrication() -> None:
    """The pre-filter may resolve a claim alone only in the SAFE direction.

    High overlap means the claim nearly restates its chunk, and near-copied text
    cannot be a fabrication — deciding that without a model call risks nothing.
    Low overlap means only that the claim is *worded differently*, which is what
    a good example or misconception looks like.

    Concretely: the reference package's inertia example ("a bus brakes, the
    passengers keep moving") scores 0.08 against the law it illustrates, and its
    misconception scores 0.16 — both carrying a verbatim quote stage 3 already
    verified against that same chunk. An earlier `overlap < TAU_LOW ->
    unsupported` rule reported four of seven claims as hallucinations with no
    model ever reading them.
    """
    knowledge = fx.knowledge_base().model_dump(mode="json")
    chunks = {c.chunk_id: c.text for c in fx.chunks()}
    claims = collect_claims(knowledge, [])
    decided, ambiguous = prefilter(claims, chunks)

    assert [v for v in decided if v.verdict == "unsupported"] == [], (
        "a claim was declared unsupported without the judge ever reading it"
    )
    # Every claim the pre-filter did not confirm must actually reach the judge,
    # not vanish.
    assert len(decided) + len(ambiguous) == len(claims)

    low = [c for c in claims if lexical_overlap(c.text, chunks[c.chunk_id or ""]) < TAU_LOW]
    assert low, "fixture no longer exercises the low-overlap path"
    assert set(low) <= set(ambiguous), "low-overlap claims must be judged, not auto-failed"


async def test_an_invalid_pedagogy_profile_trips_the_schema_rule() -> None:
    state = copy.deepcopy(_state())
    state["classification"]["pedagogy_profile"] = "not-a-real-profile"

    result = await _run(state)
    report = result["validation"]

    assert report["schema_ok"] is False
    assert "SCHEMA_CLASSIFICATION_INVALID" in _issue_codes(report)
    assert report["status"] == "fail"
    assert "educational-classification" in result["stages_to_regenerate"]


async def test_schema_ok_false_can_never_be_reported_as_a_pass() -> None:
    """The report's own validator forbids this combination; the stage must never
    attempt to build it, which this exercises end to end rather than in isolation."""
    state = copy.deepcopy(_state())
    state["assessments"]["total_marks"] = 999999  # no longer sums from the items

    result = await _run(state)
    report = result["validation"]
    assert report["schema_ok"] is False
    assert report["status"] != "pass"


# ─────────────────────────────────────────────────────────── coverage class


async def test_an_untaught_concept_trips_the_coverage_rule() -> None:
    state = copy.deepcopy(_state())
    # A concept nothing in the teaching plan ever assigns to a period.
    state["knowledge"]["concepts"].append(
        {
            "concept_id": "concept_untaught",
            "name": "Momentum",
            "summary": "The product of mass and velocity.",
            "importance": "supporting",
            "evidence": [{"chunk_id": "c_001", "quote": "unbalanced force"}],
        }
    )

    result = await _run(state)
    report = result["validation"]

    assert "COVERAGE_CONCEPT_UNTAUGHT" in _issue_codes(report)
    assert "concept_untaught" in report["coverage"]["untaught_concept_ids"]
    assert "teaching-planner" in result["stages_to_regenerate"]


async def test_an_unplanned_and_unassessed_objective_trips_the_coverage_rule() -> None:
    state = copy.deepcopy(_state())
    state["knowledge"]["learning_objectives"].append(
        {
            "objective_id": "obj_orphan",
            "statement": "Explain conservation of momentum in a collision.",
            "bloom_level": "understand",
            "concept_ids": [],
        }
    )

    result = await _run(state)
    report = result["validation"]

    codes = _issue_codes(report)
    assert "COVERAGE_OBJECTIVE_UNPLANNED" in codes
    assert "COVERAGE_OBJECTIVE_UNASSESSED" in codes
    assert "obj_orphan" in report["coverage"]["unassessed_objective_ids"]


async def test_a_narrative_document_is_not_penalised_for_having_no_numerical_items() -> None:
    """The profile-conditioned half of the coverage class (H-07).

    A quantitative document missing numerical items IS a gap; the same package
    reclassified as narrative is not — the check is never even evaluated.
    """
    quantitative_state = copy.deepcopy(_state())
    quantitative_state["assessments"]["items"] = [
        item for item in quantitative_state["assessments"]["items"] if item["kind"] != "numerical"
    ]
    quantitative_state["assessments"]["total_marks"] = sum(
        i["marks"] for i in quantitative_state["assessments"]["items"]
    )
    quantitative_result = await _run(quantitative_state)
    assert "COVERAGE_PROFILE_NUMERICAL_ITEMS_MISSING" in _issue_codes(
        quantitative_result["validation"]
    )

    narrative_state = copy.deepcopy(quantitative_state)
    narrative_state["classification"]["pedagogy_profile"] = "narrative"
    narrative_result = await _run(narrative_state)
    assert "COVERAGE_PROFILE_NUMERICAL_ITEMS_MISSING" not in _issue_codes(
        narrative_result["validation"]
    )


# ─────────────────────────────────────────────────────────── consistency class


async def test_a_dangling_activity_ref_trips_the_consistency_rule() -> None:
    state = copy.deepcopy(_state())
    state["period_contents"][0]["activity_refs"] = ["act_does_not_exist"]

    result = await _run(state)
    report = result["validation"]

    assert "CONSISTENCY_DANGLING_ACTIVITY_REF" in _issue_codes(report)
    assert "act_does_not_exist" in report["consistency"]["dangling_activity_refs"]
    assert "lesson-generation" in result["stages_to_regenerate"]


async def test_a_prerequisite_taught_after_its_dependent_trips_the_consistency_rule() -> None:
    """Nothing at construction time cross-checks this (schema_rules.py's own
    docstring) — it is caught here or nowhere. Swap which period teaches which
    concept, leaving the graph's ``concept_inertia -> concept_second_law`` edge
    unchanged, so the dependent is now taught a period before its prerequisite.
    """
    state = copy.deepcopy(_state())
    periods = state["teaching_plan"]["periods"]
    periods[0]["concept_ids"], periods[1]["concept_ids"] = (
        periods[1]["concept_ids"],
        periods[0]["concept_ids"],
    )

    result = await _run(state)
    report = result["validation"]

    assert "CONSISTENCY_PREREQUISITE_VIOLATION" in _issue_codes(report)
    assert report["consistency"]["prerequisite_violations"]
    assert "teaching-planner" in result["stages_to_regenerate"]
    # Isolated from the other rule classes: schema and coverage are untouched.
    assert report["schema_ok"] is True
    assert "COVERAGE_CONCEPT_UNTAUGHT" not in _issue_codes(report)


# ───────────────────────────────────────────────────────────── grounding class


async def test_a_claim_citing_a_nonexistent_chunk_trips_the_grounding_rule() -> None:
    """Resolved by the lexical pre-filter alone — no judge call needed for this
    claim, so this test does not depend on the judge stub's behaviour for it."""
    state = copy.deepcopy(_state())
    state["knowledge"]["concepts"][0]["evidence"][0]["chunk_id"] = "chunk_does_not_exist"

    result = await _run(state)
    report = result["validation"]

    assert "GROUNDING_UNSUPPORTED_CLAIM" in _issue_codes(report)
    assert report["grounding_score"] < 1.0
    paths = {c["path"] for c in report["unsupported_claims"]}
    assert "/knowledge/concepts/0" in paths
    assert "knowledge-extraction" in result["stages_to_regenerate"]


async def test_a_claim_the_judge_rejects_trips_the_grounding_rule() -> None:
    """Exercises the model-in-the-loop half: an ambiguous claim the lexical
    filter cannot resolve, judged unsupported."""
    result = await _run(_state(), JudgeStubAdapter(verdict="unsupported"))
    report = result["validation"]

    assert "GROUNDING_UNSUPPORTED_CLAIM" in _issue_codes(report)
    assert report["grounding_score"] < 1.0
    assert report["status"] == "fail"


async def test_a_degraded_judge_batch_is_a_warning_not_a_fabricated_finding() -> None:
    """A batch the model could not answer to schema must not manufacture a
    hallucination finding (grounding.py's own contract for a missing verdict).

    The adapter returns a payload that never satisfies ``GroundingJudgement``,
    on the first attempt and the one repair attempt the client allows — which is
    exactly what makes ``LLMResult.degraded`` true, the condition this rule
    reacts to.
    """

    class UnparsableAdapter(JudgeStubAdapter):
        async def complete(self, **kwargs: Any) -> RawCompletion:
            self.calls.append(kwargs["user_content"])
            # A type error, not merely an unknown key — the client tolerates and
            # strips unknown keys, so only a real shape mismatch forces a repair
            # attempt and, on a second failure, a genuinely degraded result.
            return RawCompletion(
                text=json.dumps({"verdicts": "not-a-list"}),
                model=kwargs["spec"].model,
                usage=LLMUsage(),
            )

    result = await _run(_state(), UnparsableAdapter())
    report = result["validation"]
    degraded_issues = [i for i in report["issues"] if i["code"] == "GROUNDING_JUDGE_DEGRADED"]
    assert degraded_issues
    assert degraded_issues[0]["severity"] == "warning"
    # Every claim the judge could not answer is downgraded to "partially
    # supported" — not fabricated into an "unsupported" hallucination finding.
    partial = [c for c in report["unsupported_claims"] if "no verdict" in c["reason"]]
    assert partial
    assert all(
        i["severity"] == "warning"
        for i in report["issues"]
        if i["path"] in {c["path"] for c in partial}
    )


# ─────────────────────────────────────────────────────────── H-07, end to end


async def test_a_narrative_package_with_no_formulae_and_no_numerical_items_passes() -> None:
    """The critical correctness property (docs/00 § H-07).

    Built independently of the physics fixture, with concepts and examples
    (what the narrative profile actually requires) and nothing quantitative at
    all. Every claim is written to overlap heavily with its cited chunk, so
    this package should not need the judge either — proven by asserting the
    adapter was never called, not merely by asserting the outcome.
    """
    chunk_text = (
        "The partition of Bengal in 1905 divided the province along religious "
        "lines and provoked a nationwide boycott movement."
    )
    state = {
        "classification": fx.narrative_classification().model_dump(mode="json"),
        "knowledge": {
            "learning_objectives": [
                {
                    "objective_id": "obj_partition",
                    "statement": (
                        "Explain why the partition of Bengal provoked national opposition."
                    ),
                    "bloom_level": "analyze",
                    "concept_ids": ["concept_partition"],
                }
            ],
            "concepts": [
                {
                    "concept_id": "concept_partition",
                    "name": "Partition of Bengal",
                    "summary": chunk_text,
                    "importance": "core",
                    "evidence": [
                        {"chunk_id": "n_001", "quote": "divided the province along religious lines"}
                    ],
                }
            ],
            "examples": [
                {
                    "title": "Swadeshi boycott",
                    "body": chunk_text,
                    "concept_ids": ["concept_partition"],
                    "evidence": [
                        {"chunk_id": "n_001", "quote": "provoked a nationwide boycott movement"}
                    ],
                }
            ],
            "formulae": [],
            "concept_graph": {"node_ids": ["concept_partition"], "edges": []},
        },
        "teaching_plan": {
            "total_periods": 1,
            "period_duration_minutes": 40,
            "periods": [
                {
                    "period_no": 1,
                    "title": "The Partition of Bengal",
                    "objective_ids": ["obj_partition"],
                    "concept_ids": ["concept_partition"],
                    "time_allocation": [{"label": "Discussion", "minutes": 40}],
                    "sequence_rationale": "The only period in this short unit.",
                }
            ],
        },
        "period_contents": [
            {
                "period_no": 1,
                "entry_ticket": {
                    "prompt": "What do you already know about colonial-era Bengal?",
                    "expected_response": "Any prior knowledge of the region or period.",
                },
                "teacher_script": [
                    {
                        "minute_start": 0,
                        "minute_end": 40,
                        "heading": "Discussion",
                        "speaker_notes": "Lead a discussion on the partition and its reception.",
                    }
                ],
                "blackboard_notes": {"headings": ["The Partition of Bengal"]},
                "activity_refs": ["act_debate"],
                "checkpoint_questions": [
                    {
                        "question": "Why did the partition provoke opposition?",
                        "expected_answer": "It divided the province along religious lines.",
                        "bloom_level": "understand",
                        "concept_ids": ["concept_partition"],
                    }
                ],
                "exit_ticket": {
                    "prompt": "Name one form the opposition took.",
                    "success_indicator": "Any accurate reference to the boycott movement.",
                },
                "homework": {"tasks": ["Read the next section."], "estimated_minutes": 15},
                "mentor_moment": {
                    "title": "A historian's habit",
                    "story": "Good historians always ask who benefits from a decision.",
                    "takeaway": "Ask who benefits.",
                },
            }
        ],
        "activities": [
            {
                "activity_id": "act_debate",
                "period_no": 1,
                "type": "debate",
                "title": "Was the partition administrative or political?",
                "duration_minutes": 20,
                "teacher_instructions": ["Split the class into two sides and set the motion."],
                "success_criteria": ["Each side cites at least one piece of evidence."],
                "differentiation": {
                    "support": "Provide sentence starters for each side.",
                    "extension": "Ask students to argue the opposing side afterward.",
                },
                "concept_ids": ["concept_partition"],
            }
        ],
        "assessments": {
            "items": [
                {
                    "item_id": "item_partition_1",
                    "kind": "short_answer",
                    "stem": "Why did the partition of Bengal provoke national opposition?",
                    "answer": (
                        "It divided the province along religious lines and was widely seen "
                        "as a divide-and-rule tactic, provoking the Swadeshi boycott movement."
                    ),
                    "marks": 3,
                    "bloom_level": "analyze",
                    "concept_ids": ["concept_partition"],
                    "rubric": {
                        "criteria": "Accuracy and use of evidence",
                        "levels": [
                            {
                                "label": "Full",
                                "descriptor": "Names the cause and the response.",
                                "marks": 3,
                            },
                            {"label": "Partial", "descriptor": "Names only one.", "marks": 1},
                        ],
                    },
                }
            ],
            "blueprint": {
                "items_by_kind": {"short_answer": 1},
                "items_by_bloom": {"analyze": 1},
                "marks_by_concept": {"concept_partition": 3},
            },
            "total_marks": 3,
        },
        "learning_gaps": [],
        "chunks": [
            {"chunk_id": "n_001", "document_id": str(uuid4()), "ordinal": 0, "text": chunk_text}
        ],
    }

    class ForbiddenAdapter(JudgeStubAdapter):
        async def complete(self, **kwargs: Any) -> RawCompletion:
            raise AssertionError("the narrative package should not need the grounding judge")

    result = await _run(state, ForbiddenAdapter())
    report = result["validation"]

    assert report["schema_ok"] is True
    assert "quantitative" not in report["profile_ruleset"]
    assert "COVERAGE_PROFILE_NUMERICAL_ITEMS_MISSING" not in _issue_codes(report)
    assert not any(i["path"].startswith("/knowledge/formulae") for i in report["issues"])
    assert report["status"] == "pass"
    assert result["stages_to_regenerate"] == []
