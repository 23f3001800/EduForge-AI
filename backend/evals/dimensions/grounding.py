"""Grounding — do the cited spans exist, and do they support what was generated?

Two questions, scored separately, because they fail separately and the fix differs:

1. **Citation integrity.** Does the ``quote`` attached to a claim actually appear
   in the chunk it names? A quote that does not appear is a fabricated citation —
   the most damaging failure mode in the system, because it looks like evidence.
   This is a verbatim containment test after punctuation folding: exact, cheap,
   and impossible to argue with.
2. **Claim support.** Does the cited chunk actually support the claim, once the
   claim has been paraphrased away from the quote? This is a semantic question a
   lexical test can only bound, so it is bounded the same way
   ``stages/s9_validation/grounding.py`` bounds it: above ``TAU_HIGH`` supported,
   below ``TAU_LOW`` unsupported, and the middle band reported as needing
   judgement rather than guessed at.

The thresholds and the normalisation approach are borrowed from stage 9; the
implementation is not. An eval that imported the module it grades would move
whenever that module moved, and would report a clean bill of health for a bug
introduced in the shared code. Re-deriving the measurement is the point.

``MentorMoment`` is excluded by construction: it is never part of ``knowledge`` or
``learning_gaps``, and its contract marks it ``grounded: False`` because a
motivational anecdote is allowed to draw on general knowledge. Counting it as an
unsupported claim would penalise the package for doing the right thing.

With no source chunks supplied the dimension is **not applicable**, and drops out
of the weighted mean rather than scoring zero. Scoring an absent input as a
failure is how a harness starts punishing packages for how they were exported.

That is different from a package that supplies chunks and cites *nothing*. Citation
integrity averaged an empty list to 1.0, so stripping every quote from every claim
scored perfect integrity — the cheapest citation is no citation. Absent chunks are
the evaluator's missing input; absent citations are the package's missing work.
The first is inapplicable, the second is measured by ``claims_cited``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evals.context import EvalContext
from evals.text import contains_verbatim, lexical_overlap
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "TAU_HIGH", "TAU_LOW", "WEIGHT", "score"]

KEY = "grounding"
LABEL = "Grounding"
WEIGHT = 0.12
METHOD = "deterministic"

#: At or above this share of claim tokens present in the cited chunk, the claim is
#: lexically well-supported.
TAU_HIGH = 0.6
#: Below this, the claim shares almost nothing with its own citation.
TAU_LOW = 0.25

#: How each knowledge list renders as one checkable claim. Concatenating the label
#: with the substantive field keeps short claims from being mostly stopwords once
#: normalised.
_CLAIM_TEXT: Mapping[str, Any] = {
    "concepts": lambda i: f"{i.get('name', '')}: {i.get('summary', '')}",
    "definitions": lambda i: f"{i.get('term', '')}: {i.get('definition', '')}",
    "formulae": lambda i: f"{i.get('name') or ''} {i.get('plain', '')}",
    "examples": lambda i: f"{i.get('title') or ''} {i.get('body', '')}",
    "applications": lambda i: f"{i.get('context', '')}: {i.get('description', '')}",
    "misconceptions": lambda i: f"{i.get('statement', '')} {i.get('correction', '')}",
}


def score(ctx: EvalContext) -> DimensionScore:
    if not ctx.chunks:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            applicable=False,
            reason=(
                "no source chunks supplied; citation integrity cannot be verified "
                "without the document the citations point at"
            ),
        )

    findings: list[Finding] = []
    integrity: list[float] = []
    support: list[float] = []
    ambiguous = 0

    claims: list[tuple[str, str, list[Mapping[str, Any]]]] = []
    for field, render in _CLAIM_TEXT.items():
        for index, item in enumerate(ctx.knowledge.get(field) or []):
            claims.append(
                (
                    f"/knowledge/{field}/{index}",
                    str(render(item)).strip(" :"),
                    item.get("evidence") or [],
                )
            )
    for index, gap in enumerate(ctx.learning_gaps):
        evidence = gap.get("evidence") or []
        if evidence:  # a predicted gap legitimately carries none
            claims.append((f"/learning_gaps/{index}", str(gap.get("misconception", "")), evidence))

    if not claims:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            applicable=False,
            reason="no groundable claims in this package",
        )

    for path, text, evidence in claims:
        for offset, span in enumerate(evidence):
            chunk_id = str(span.get("chunk_id") or "")
            chunk = ctx.chunks.get(chunk_id)
            quote = str(span.get("quote") or "")
            if chunk is None:
                integrity.append(0.0)
                findings.append(
                    Finding(
                        "GND_CHUNK_UNRESOLVED",
                        f"{path}/evidence/{offset}",
                        f"cites chunk {chunk_id!r}, which is not in the source document",
                    )
                )
            elif contains_verbatim(quote, chunk):
                integrity.append(1.0)
            else:
                integrity.append(0.0)
                findings.append(
                    Finding(
                        "GND_QUOTE_NOT_IN_SOURCE",
                        f"{path}/evidence/{offset}",
                        f"the quote {quote[:60]!r} does not appear in chunk {chunk_id!r}; "
                        "a citation that cannot be found is worse than none, because it "
                        "reads as authority",
                    )
                )

        first = evidence[0] if evidence else {}
        chunk = ctx.chunks.get(str(first.get("chunk_id") or ""))
        if chunk is None:
            support.append(0.0)
            continue

        overlap = lexical_overlap(text, chunk)
        if overlap >= TAU_HIGH:
            support.append(1.0)
        elif overlap < TAU_LOW:
            support.append(0.0)
            findings.append(
                Finding(
                    "GND_CLAIM_UNSUPPORTED",
                    path,
                    f"shares {overlap:.0%} of its wording with the chunk it cites; the "
                    f"claim {text[:60]!r} was not drawn from that passage",
                )
            )
        else:
            ambiguous += 1
            support.append(0.5)

    # A claim carrying no evidence is uncheckable, not verified. Counting it as
    # neither would let a package earn full grounding by citing nothing at all,
    # which is why this is measured before integrity is averaged.
    cited = sum(1 for _, _, evidence in claims if evidence)
    cited_share = cited / len(claims)
    if cited_share < 1.0:
        findings.append(
            Finding(
                "GND_CLAIM_UNCITED",
                "/knowledge",
                f"{len(claims) - cited} of {len(claims)} claims carry no evidence span at "
                "all; an uncited claim is not a verified one, and a bank of them would "
                "otherwise score perfect citation integrity for having nothing to check",
            )
        )

    metrics = (
        Metric(
            "claims_cited",
            cited_share,
            0.20,
            f"{cited} of {len(claims)} claim(s) cite the source at all",
        ),
        Metric(
            "citation_integrity",
            mean(integrity),
            0.50 if integrity else 0.0,
            f"{len(integrity)} evidence span(s) checked verbatim against the source"
            if integrity
            else "no evidence spans to check; reported, not scored — see claims_cited",
        ),
        Metric(
            "claim_support",
            mean(support),
            0.30,
            f"{len(claims)} claim(s) checked; {ambiguous} in the ambiguous band "
            f"({TAU_LOW}-{TAU_HIGH}), scored 0.5 and left for the judge",
        ),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
