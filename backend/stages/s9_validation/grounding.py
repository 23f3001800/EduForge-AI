"""Rule class 4 — grounding verification (SRS-6.4, LLD § 4.4).

This checks a different thing than ``stages/s3_knowledge/grounding.py`` does, even
though the shape looks similar (normalisation, lexical overlap, a threshold). That
module verifies *citation integrity at extraction time*: does the quote a model
attached to a claim actually appear, verbatim, in the chunk it named? This module
verifies *the claim itself*, downstream, after the concept's ``summary`` or a
misconception's ``statement`` has been paraphrased away from the quote entirely —
the question here is whether the source passage as a whole still supports what
was generated from it. That is a semantic judgement a lexical check can only
bound, not answer, which is why the ambiguous middle goes to an LLM judge.

The normalisation approach is intentionally the same idea as stage 3's (fold
punctuation and whitespace before comparing) because PDF extraction artefacts are
not the model's fault there either — but this is a fresh, self-contained
implementation. Cross-stage imports fail the CI boundary check (docs/07), and
depending on stage 3's internals would also be the wrong coupling even if it were
allowed: stage 3 verifies a quote against one chunk; this verifies a claim against
a chunk's *content*, a different comparison with a different pair of thresholds.

The pre-filter keeps the judge off most claims (LLD § 4.4), but only in the one
direction where skipping it is safe:

* overlap ``>= TAU_HIGH``  -> supported, no model call.
* anything else            -> batched to the judge.

The asymmetry is deliberate and was originally got wrong. High overlap means the
claim nearly restates its chunk, and text that near-copies its source cannot be a
fabrication, so resolving it without a model call risks nothing. Low overlap means
only that the claim is *worded differently* from the chunk — which is what a good
summary, worked example, or misconception looks like. Deciding "unsupported" from
that signal alone reports a hallucination on the basis of paraphrase.

That is not hypothetical: the reference physics package has an example
("when a bus brakes suddenly, passengers continue moving forward") that scores
0.08 against the law it illustrates, and a misconception that scores 0.16, both
carrying a verbatim quote stage 3 already verified against that same chunk. Under
the old ``overlap < TAU_LOW -> unsupported`` rule, four of its seven claims were
declared fabrications without any model ever reading them.

``TAU_LOW`` survives as a *reporting* signal — it separates "the judge had to
work for this" from "the judge confirmed something close to the text" — and no
longer decides anything on its own. The only deterministic failure left is a
citation whose chunk id does not resolve, which is dispositive: there is no
source to be entailed by.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from contracts.primitives import StageName
from core.llm.client import LLMClient
from stages.s9_validation.issues import IssueDict, make_issue
from stages.s9_validation.schemas import GroundingJudgement

__all__ = [
    "JUDGE_BATCH_SIZE",
    "TAU_HIGH",
    "TAU_LOW",
    "GroundableClaim",
    "Verdicted",
    "check_grounding",
    "collect_claims",
    "judge_claims",
    "lexical_overlap",
    "normalise",
    "prefilter",
]

_WHITESPACE = re.compile(r"\s+")
# Keyed by code point rather than literal character: the glyphs themselves are
# exactly what ruff's RUF001 flags as "ambiguous unicode" wherever they appear
# unescaped in a string literal.
_QUOTES = str.maketrans(
    {
        0x2018: "'",  # left single quote
        0x2019: "'",  # right single quote
        0x201C: '"',  # left double quote
        0x201D: '"',  # right double quote
        0x2013: "-",  # en dash
        0x2014: "-",  # em dash
    }
)

#: At or above this fraction of claim tokens found in the chunk, the claim is
#: lexically well-supported and needs no judge call.
TAU_HIGH = 0.6
#: Below this fraction, the claim shares almost nothing with its cited chunk and
#: is confidently unsupported — also no judge call.
TAU_LOW = 0.25
#: LLD § 4.4: judge in batches, never one call per claim.
JUDGE_BATCH_SIZE = 20
_CHUNK_EXCERPT_CHARS = 800

Verdict = str  # "supported" | "partially_supported" | "unsupported"


def normalise(text: str) -> str:
    """Collapse extraction artefacts (smart quotes, stray whitespace) before comparing."""
    folded = unicodedata.normalize("NFKD", text).translate(_QUOTES)
    return _WHITESPACE.sub(" ", folded).strip().casefold()


def lexical_overlap(claim: str, span: str) -> float:
    """Share of the claim's tokens that also appear in the span, order-insensitive.

    A cheap stand-in for entailment — good enough to separate "clearly supported",
    "clearly unrelated", and "needs a real read", which is the only distinction
    this pre-filter needs to make.
    """
    claim_tokens = normalise(claim).split()
    if not claim_tokens:
        return 0.0
    span_tokens = set(normalise(span).split())
    hits = sum(1 for token in claim_tokens if token in span_tokens)
    return hits / len(claim_tokens)


@dataclass(slots=True, frozen=True)
class GroundableClaim:
    """One generated statement that must trace back to the source document."""

    path: str
    text: str
    chunk_id: str | None
    stage: StageName


@dataclass(slots=True, frozen=True)
class Verdicted:
    claim: GroundableClaim
    verdict: Verdict
    reason: str


#: How to render each knowledge-base list's items as one checkable claim string.
#: Concatenating the label field with the substantive one keeps short claims (a
#: bare formula, a one-line definition) from being mostly noise once normalised.
_KNOWLEDGE_CLAIM_TEXT: dict[str, Any] = {
    "concepts": lambda item: f"{item.get('name', '')}: {item.get('summary', '')}",
    "definitions": lambda item: f"{item.get('term', '')}: {item.get('definition', '')}",
    "formulae": lambda item: f"{item.get('name') or ''} {item.get('plain', '')}",
    "examples": lambda item: f"{item.get('title') or ''} {item.get('body', '')}",
    "applications": lambda item: f"{item.get('context', '')}: {item.get('description', '')}",
    "misconceptions": lambda item: f"{item.get('statement', '')} {item.get('correction', '')}",
}


def collect_claims(
    knowledge: dict[str, Any], learning_gaps: list[dict[str, Any]]
) -> list[GroundableClaim]:
    """Every groundable item that carries evidence.

    ``mentor_moment`` is excluded by construction — it is never part of
    ``knowledge`` or ``learning_gaps``, and its own contract marks it
    ``grounded: False`` for exactly this reason (SRS-5.2). An item with no
    evidence at all is skipped here rather than flagged: schema conformance
    already rejects it, since every field this loop reads inherits
    ``contracts.primitives.Grounded`` with ``evidence`` at ``min_length=1``.
    """
    claims: list[GroundableClaim] = []

    for field, build_text in _KNOWLEDGE_CLAIM_TEXT.items():
        for index, item in enumerate(knowledge.get(field) or []):
            evidence = item.get("evidence") or []
            if not evidence:
                continue
            claims.append(
                GroundableClaim(
                    path=f"/knowledge/{field}/{index}",
                    text=build_text(item).strip(" :"),
                    chunk_id=evidence[0].get("chunk_id"),
                    stage="knowledge-extraction",
                )
            )

    for index, gap in enumerate(learning_gaps):
        evidence = gap.get("evidence") or []
        if not evidence:
            continue  # learning gaps may legitimately be predicted, not cited
        claims.append(
            GroundableClaim(
                path=f"/learning_gaps/{index}",
                text=str(gap.get("misconception", "")),
                chunk_id=evidence[0].get("chunk_id"),
                stage="gap-analysis",
            )
        )

    return claims


def prefilter(
    claims: list[GroundableClaim], chunks_by_id: dict[str, str]
) -> tuple[list[Verdicted], list[GroundableClaim]]:
    """Resolve every claim the lexical thresholds can decide; queue the rest."""
    decided: list[Verdicted] = []
    ambiguous: list[GroundableClaim] = []

    for claim in claims:
        span = chunks_by_id.get(claim.chunk_id or "")
        if span is None:
            decided.append(Verdicted(claim, "unsupported", "cited chunk id does not resolve"))
            continue

        overlap = lexical_overlap(claim.text, span)
        if overlap >= TAU_HIGH:
            decided.append(Verdicted(claim, "supported", f"lexical overlap {overlap:.2f}"))
        else:
            # Everything else needs a real read. Low overlap is a paraphrase
            # signal, not a fabrication signal — see the module docstring.
            ambiguous.append(claim)

    return decided, ambiguous


_JUDGE_SYSTEM = """You check whether a short generated claim is supported by the \
source passage cited for it. Judge only what the passage states or clearly \
entails — do not use outside knowledge to fill gaps, and do not reward a claim \
for being true in general if this passage does not say it.

For every numbered claim, return exactly one verdict:
- supported: the passage states or directly entails the claim.
- partially_supported: the passage is related but does not fully establish it.
- unsupported: the passage does not support the claim.

Return one verdict per index. Cover every index given."""


def _judge_prompt(batch: list[GroundableClaim], chunks_by_id: dict[str, str]) -> str:
    blocks = []
    for index, claim in enumerate(batch):
        span = (chunks_by_id.get(claim.chunk_id or "") or "")[:_CHUNK_EXCERPT_CHARS]
        blocks.append(f"CLAIM {index}: {claim.text}\nSOURCE PASSAGE {index}: {span}")
    return "\n\n".join(blocks)


async def judge_claims(
    llm: LLMClient,
    claims: list[GroundableClaim],
    chunks_by_id: dict[str, str],
    *,
    stage: StageName,
) -> tuple[list[Verdicted], bool]:
    """Judge exactly the claims the pre-filter could not decide, in bounded batches.

    Returns the verdicts and whether any batch came back degraded, so the caller
    can record that once rather than once per claim in the batch.
    """
    results: list[Verdicted] = []
    any_degraded = False

    for start in range(0, len(claims), JUDGE_BATCH_SIZE):
        batch = claims[start : start + JUDGE_BATCH_SIZE]
        outcome = await llm.parse(
            stage=stage,
            output_model=GroundingJudgement,
            system=_JUDGE_SYSTEM,
            user_content=_judge_prompt(batch, chunks_by_id),
        )
        if outcome.degraded:
            any_degraded = True

        verdict_by_index = {v.index: v.verdict for v in outcome.value.verdicts}
        for index, claim in enumerate(batch):
            verdict = verdict_by_index.get(index)
            if verdict is None:
                # A missing verdict is the judge's failure, not evidence the claim
                # is bad — defaulting to "unsupported" would manufacture a false
                # hallucination finding out of a degraded call.
                results.append(Verdicted(claim, "partially_supported", "judge returned no verdict"))
            else:
                results.append(Verdicted(claim, verdict, f"judge rated this {verdict}"))

    return results, any_degraded


_VERDICT_WEIGHT: dict[Verdict, float] = {
    "supported": 1.0,
    "partially_supported": 0.5,
    "unsupported": 0.0,
}


async def check_grounding(
    llm: LLMClient,
    *,
    knowledge: dict[str, Any],
    learning_gaps: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    stage: StageName,
) -> tuple[float, list[dict[str, Any]], list[IssueDict]]:
    """Run the full rule: collect claims, pre-filter, judge the remainder, score."""
    chunks_by_id = {c["chunk_id"]: c.get("text", "") for c in chunks if c.get("chunk_id")}
    claims = collect_claims(knowledge, learning_gaps)
    if not claims:
        return 1.0, [], []

    decided, ambiguous = prefilter(claims, chunks_by_id)
    any_degraded = False
    if ambiguous:
        judged, any_degraded = await judge_claims(llm, ambiguous, chunks_by_id, stage=stage)
        decided.extend(judged)

    score = sum(_VERDICT_WEIGHT[v.verdict] for v in decided) / len(decided)

    unsupported_claims: list[dict[str, Any]] = []
    issues: list[IssueDict] = []
    for verdict in decided:
        claim_text = verdict.claim.text[:600] or "(empty claim text)"
        if verdict.verdict == "unsupported":
            unsupported_claims.append(
                {
                    "path": verdict.claim.path,
                    "claim": claim_text,
                    "cited_chunk_id": verdict.claim.chunk_id,
                    "reason": verdict.reason,
                }
            )
            issues.append(
                make_issue(
                    code="GROUNDING_UNSUPPORTED_CLAIM",
                    message=(
                        f"claim at {verdict.claim.path} is not supported by its "
                        f"cited source ({verdict.reason})"
                    ),
                    path=verdict.claim.path,
                    stage=verdict.claim.stage,
                )
            )
        elif verdict.verdict == "partially_supported":
            unsupported_claims.append(
                {
                    "path": verdict.claim.path,
                    "claim": claim_text,
                    "cited_chunk_id": verdict.claim.chunk_id,
                    "reason": verdict.reason,
                }
            )
            issues.append(
                make_issue(
                    code="GROUNDING_PARTIALLY_SUPPORTED_CLAIM",
                    message=(
                        f"claim at {verdict.claim.path} is only partially supported "
                        f"by its cited source ({verdict.reason})"
                    ),
                    path=verdict.claim.path,
                    stage=verdict.claim.stage,
                    severity="warning",
                )
            )

    if any_degraded:
        issues.append(
            make_issue(
                code="GROUNDING_JUDGE_DEGRADED",
                message=(
                    "the grounding judge did not return valid verdicts for one "
                    "batch; affected claims were scored as partially supported "
                    "rather than treated as a hallucination finding"
                ),
                path="/validation",
                stage="validation",
                severity="warning",
            )
        )

    return score, unsupported_claims, issues
