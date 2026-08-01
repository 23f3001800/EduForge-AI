"""The optional LLM judge — for the three questions a lexicon genuinely cannot answer.

Everything else in this harness is deterministic, and that is not an accident: a
metric that costs a token is a metric that gets skipped, and a metric that depends
on a model can move for reasons that have nothing to do with the package being
scored. So the judge is confined to the residue the deterministic pass explicitly
marks as undecidable:

* an objective whose leading verb is not in the observable-verb lexicon,
* a success criterion that contains neither an observable verb nor an
  unobservable marker,
* a differentiation instruction that scored in the ambiguous middle band.

Three properties keep this honest:

1. **It only ever fills gaps.** The deterministic estimate is computed first and
   stands wherever the judge has nothing to say. A judge outage degrades the score
   to the deterministic one rather than to zero.
2. **It is batched and schema-bound.** One call per batch of items, a two-field
   verdict per item, nothing free-text — the same shape as the grounding judge in
   stage 9, and for the same reason: the smallest schema that survives a small
   model.
3. **It refuses to run outside ``EVAL_PROFILE``.** Judged numbers from the dev
   profile are not comparable with judged numbers from production, and the least
   useful thing an eval can do is produce a score that quietly means something
   different from the last one.

Nothing in the test suite calls this path. It exists, it is typed, and it is
gated; running it requires a production profile and a real key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from contracts.primitives import StageName, StrictModel
from core.llm.client import LLMClient
from evals.context import EvalContext
from evals.dimensions.activities import criterion_is_observable
from evals.dimensions.differentiation import specificity
from evals.harness import require_eval_profile
from evals.lexicons import BLOOM_VERBS, VAGUE_OBJECTIVE_VERBS, WEAK_OBJECTIVE_VERBS
from evals.text import leading_verb
from evals.types import Judgements

__all__ = ["BATCH_SIZE", "JUDGE_STAGE", "Verdicts", "collect_undecided", "judge"]

#: Judged in batches, never one call per item.
BATCH_SIZE = 20

#: The judge borrows the validation stage's routing. It is a validation-shaped
#: call — small schema, short inputs, no generation — so it belongs on whatever
#: model that profile points validation at rather than on a second entry nobody
#: remembers to configure.
JUDGE_STAGE: StageName = "validation"

_SYSTEM = """You are reviewing generated teaching material for a specific, narrow \
property. Answer only the property asked about. Do not reward text for being \
well written, or penalise it for being brief.

MEASURABLE (learning objectives): does the statement describe a behaviour a \
teacher could observe and mark? "Explain why the tide turns" is measurable; \
"Understand tides" is not, because nothing about the student changes visibly.

OBSERVABLE (success criteria): could a teacher tell, while the lesson is running, \
whether this has happened? "Student names two causes aloud" is observable; \
"Student appreciates the complexity" is not.

SPECIFIC (differentiation): does this tell a teacher what to actually do, with \
this material? "Give the sentence frame 'The tide turns because...'" is specific; \
"Provide extra support as needed" is not.

Return one verdict per index. Cover every index given."""


class _Verdict(StrictModel):
    index: int = Field(ge=0)
    verdict: bool


class Verdicts(StrictModel):
    """A batch's worth of yes/no answers, in one call."""

    verdicts: list[_Verdict] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Question:
    """One thing to judge: where it came from, and what to ask about it."""

    bucket: str  # objective | criterion | differentiation
    key: str
    property_name: str
    text: str


def collect_undecided(ctx: EvalContext) -> list[_Question]:
    """Exactly the items the deterministic pass could not decide.

    Reproducing the deterministic decision here rather than having the metrics
    hand back their own residue keeps the metrics free of any knowledge that a
    judge exists — they compute a number and are done.
    """
    questions: list[_Question] = []

    for objective in ctx.objectives:
        statement = str(objective.get("statement") or "")
        verb = leading_verb(statement)
        known = verb in BLOOM_VERBS or verb in VAGUE_OBJECTIVE_VERBS or verb in WEAK_OBJECTIVE_VERBS
        if not known:
            questions.append(
                _Question(
                    "objective",
                    str(objective.get("objective_id") or ""),
                    "MEASURABLE",
                    statement,
                )
            )

    for activity in ctx.activities:
        activity_id = str(activity.get("activity_id") or "")
        for offset, criterion in enumerate(activity.get("success_criteria") or []):
            if criterion_is_observable(str(criterion)) is None:
                questions.append(
                    _Question("criterion", f"{activity_id}#{offset}", "OBSERVABLE", str(criterion))
                )
        block = activity.get("differentiation") or {}
        for side in ("support", "extension"):
            text = str(block.get(side) or "")
            if text and 0.3 < specificity(text, ctx.vocabulary) < 0.8:
                questions.append(
                    _Question("differentiation", f"{activity_id}#{side}", "SPECIFIC", text)
                )

    return questions


def _prompt(batch: Sequence[_Question]) -> str:
    return "\n\n".join(
        f"ITEM {index} — property: {q.property_name}\nTEXT: {q.text}"
        for index, q in enumerate(batch)
    )


async def judge(llm: LLMClient, ctx: EvalContext) -> Judgements:
    """Resolve the undecided residue. Requires ``EVAL_PROFILE``.

    A batch that comes back short is not treated as evidence against the items it
    omitted: a missing verdict leaves the deterministic estimate in place, because
    a degraded call must never manufacture a finding.
    """
    require_eval_profile()

    questions = collect_undecided(ctx)
    objective: dict[str, bool] = {}
    criterion: dict[str, bool] = {}
    differentiation: dict[str, bool] = {}
    buckets: dict[str, dict[str, bool]] = {
        "objective": objective,
        "criterion": criterion,
        "differentiation": differentiation,
    }

    for start in range(0, len(questions), BATCH_SIZE):
        batch = questions[start : start + BATCH_SIZE]
        outcome: Any = await llm.parse(
            stage=JUDGE_STAGE,
            output_model=Verdicts,
            system=_SYSTEM,
            user_content=_prompt(batch),
        )
        if outcome.degraded:
            continue
        by_index = {v.index: v.verdict for v in outcome.value.verdicts}
        for index, question in enumerate(batch):
            if index in by_index:
                buckets[question.bucket][question.key] = by_index[index]

    return Judgements(
        objective_measurable=objective,
        criterion_observable=criterion,
        differentiation_specific=differentiation,
    )
