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

The one thing the surviving auto-pass could not see is polarity. Overlap is a bag
of tokens, so it is blind to word order and therefore to negation: a claim built
by inserting "not" into its own source, or by swapping "attract" for "repel",
keeps almost every token it started with and scores *above* ``TAU_HIGH``. A claim
asserting the exact opposite of its chunk measured 0.70 and was marked
``supported`` without a model ever reading it — the worst failure this rule can
have, because it is the hallucination-detector reporting no hallucination.

:func:`contradiction_risk` closes that. It runs only where the auto-pass would
otherwise fire, so the common path — every claim already destined for the judge —
pays nothing, and it routes to the judge rather than deciding anything itself: a
lexical polarity signal is evidence that a model should look, never evidence of
what the answer is.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

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
    "contradiction_risk",
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


# ─────────────────────────────────────────────────────── the contradiction gate

#: Punctuation-stripped for the gate only. ``lexical_overlap`` deliberately splits
#: on whitespace, but "not." and "not" must not be different negators.
_GATE_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

#: Closed-class negators. Kept closed on purpose: an open list of "negative-ish"
#: words (fails, lacks, absent) would fire on ordinary prose and push the judge
#: bill up for no signal.
_NEGATIONS = frozenset(
    {
        "no", "not", "never", "none", "nor", "neither", "nothing", "nobody", "cannot",
        "without", "cant", "can't", "dont", "don't", "doesnt", "doesn't", "didnt",
        "didn't", "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't", "werent",
        "weren't", "wont", "won't", "wouldnt", "wouldn't", "shouldnt", "shouldn't",
        "couldnt", "couldn't", "hasnt", "hasn't", "havent", "haven't", "hadnt",
        "hadn't", "unlike", "unable",
    }
)  # fmt: skip

#: Antonym pairs, as (side, other side) token sets so morphological variants share
#: one entry. Every pair is general-purpose English polarity — nothing here names a
#: subject, which is the same constraint the rest of the pipeline works under
#: (NFR-01): the gate must behave identically on a physics chapter and a history one.
_ANTONYMS: tuple[tuple[frozenset[str], frozenset[str]], ...] = tuple(
    (frozenset(left.split()), frozenset(right.split()))
    for left, right in (
        (
            "increase increases increased increasing rise rises rising rose grow grows",
            "decrease decreases decreased decreasing fall falls falling fell shrink shrinks",
        ),
        (
            "more greater larger higher bigger longer stronger faster heavier maximum",
            "less fewer smaller lower shorter weaker slower lighter minimum",
        ),
        ("positive positively", "negative negatively"),
        (
            "attract attracts attracted attraction attractive",
            "repel repels repelled repulsion repulsive",
        ),
        (
            "same identical equal equals alike similar",
            "different differs differing unequal opposite",
        ),
        ("above over up upward upwards", "below under down downward downwards"),
        ("before prior earlier preceding", "after later subsequent following"),
        ("directly direct proportional", "inversely inverse"),
        ("always all every", "sometimes some few"),
        ("possible possibly can", "impossible cannot"),
        ("gain gains gained", "lose loses lost"),
        ("true correct valid", "false incorrect invalid"),
    )
)

#: Tokens after a negator that it plausibly scopes over. Six is roughly a clause.
_NEGATION_SCOPE = 6
#: Ignore short function words when deciding whether a claim echoes a negated
#: clause; "is", "the", "a" are in every sentence and prove nothing.
_MIN_CONTENT_LEN = 4
#: Share of a negated clause's content words that must reappear in the claim.
#: Not 1.0: the window is a fixed token count, not a parsed clause, so it runs a
#: word or two past the end of what the negator scopes over and picks up whatever
#: the next phrase starts with.
_NEGATION_ECHO = 0.75


def _gate_tokens(text: str) -> list[str]:
    return _GATE_TOKEN.findall(normalise(text))


def _polarity_conflict(claim_tokens: set[str], span_tokens: set[str]) -> str | None:
    """One side of an antonym pair in the claim, the other side in the passage.

    Both directions require the conflicting term to be *absent* from the other
    text. A passage that says both "increase" and "decrease" is discussing both
    and tells us nothing about which one the claim took.
    """
    for left, right in _ANTONYMS:
        claim_left, claim_right = claim_tokens & left, claim_tokens & right
        span_left, span_right = span_tokens & left, span_tokens & right
        if claim_left and not claim_right and span_right and not span_left:
            return f"claim says {min(claim_left)!r} where its source says {min(span_right)!r}"
        if claim_right and not claim_left and span_left and not span_right:
            return f"claim says {min(claim_right)!r} where its source says {min(span_left)!r}"
    return None


def _dropped_negation(claim_tokens: set[str], span_sequence: list[str]) -> str | None:
    """The passage negates a clause that the claim restates affirmatively.

    Deliberately strict — nearly every content word the negator scopes over has to
    reappear in the claim — because a long passage contains negations about all
    sorts of things, and only the one this claim is actually about is a signal.
    """
    for index, token in enumerate(span_sequence):
        if token not in _NEGATIONS:
            continue
        window = span_sequence[index + 1 : index + 1 + _NEGATION_SCOPE]
        content = [word for word in window if len(word) >= _MIN_CONTENT_LEN]
        if len(content) < 2:
            continue
        echoed = sum(1 for word in content if word in claim_tokens)
        if echoed >= _NEGATION_ECHO * len(content):
            phrase = " ".join([token, *window])
            return f"source negates {phrase!r}; the claim restates it affirmatively"
    return None


def contradiction_risk(claim: str, span: str) -> str | None:
    """Why this claim might assert the opposite of its source, or ``None``.

    Purely lexical and deliberately cheap: three set operations and one linear
    scan, run only on claims the overlap threshold was about to wave through. It
    never decides a verdict — a hit routes the claim to the judge, which is the
    only thing that can actually read for entailment.
    """
    claim_sequence = _gate_tokens(claim)
    claim_tokens = set(claim_sequence)
    span_sequence = _gate_tokens(span)
    span_tokens = set(span_sequence)

    # Inserted negation: the claim negates something its source never negates.
    # High overlap means the claim near-copies the passage, so a negator the
    # passage does not contain anywhere is the claim's own addition.
    added = (claim_tokens & _NEGATIONS) - span_tokens
    if added:
        return f"claim contains the negation {min(added)!r}, which its source does not"

    conflict = _polarity_conflict(claim_tokens, span_tokens)
    if conflict is not None:
        return conflict

    # Dropped negation, the mirror image. Only checked when the claim itself is
    # affirmative; otherwise the negators simply moved and the first two rules
    # already had their chance.
    if not (claim_tokens & _NEGATIONS):
        return _dropped_negation(claim_tokens, span_sequence)
    return None


#: What kind of statement a claim is, which decides *which question* grounding
#: asks of it. The distinction is not a softening — it is the difference between
#: two genuinely different failure modes.
#:
#: An *extracted* claim asserts something the document says. If the cited passage
#: does not establish it, the model invented it, and that is the fabrication this
#: whole module exists to catch.
#:
#: A *predicted* claim — a misconception, a learning gap — asserts something
#: about **students**, not about the document. No textbook records which errors
#: learners make on its own hardest ideas; that is precisely why a teacher needs
#: the prediction. Demanding that the source entail it is demanding the
#: impossible, and it was measured doing exactly that: on a 935-word calculus
#: chapter, all nine extracted claims grounded cleanly and all four predicted
#: ones were flagged, dragging a genuinely good package to 0.73 and `fail`.
#:
#: So a predicted claim's evidence is a *pointer to the material the difficulty
#: concerns*, and the honest question is whether it points at the right passage,
#: not whether the passage proves the prediction.
ClaimKind = Literal["extracted", "predicted"]


@dataclass(slots=True, frozen=True)
class GroundableClaim:
    """One generated statement that must trace back to the source document."""

    path: str
    text: str
    chunk_id: str | None
    stage: StageName
    kind: ClaimKind = "extracted"


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

#: Knowledge fields that describe students rather than the document. See
#: ``ClaimKind``. Only misconceptions qualify — every other field in
#: ``_KNOWLEDGE_CLAIM_TEXT`` asserts something the chapter itself says.
_PREDICTED_FIELDS: dict[str, ClaimKind] = {"misconceptions": "predicted"}


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
                    kind=_PREDICTED_FIELDS.get(field, "extracted"),
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
                kind="predicted",
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
        # Contradiction detection is meaningless on a predicted claim and worse
        # than meaningless on a misconception: a misconception *states the wrong
        # thing on purpose*, so conflicting with the source's polarity is the
        # shape of a correct one. Flagging that conflict penalises the field for
        # doing its job. Predicted claims go to the judge, which is asked a
        # question the conflict does not corrupt.
        if claim.kind == "predicted":
            ambiguous.append(claim)
        elif overlap >= TAU_HIGH and contradiction_risk(claim.text, span) is None:
            decided.append(Verdicted(claim, "supported", f"lexical overlap {overlap:.2f}"))
        else:
            # Everything else needs a real read. Low overlap is a paraphrase
            # signal, not a fabrication signal — see the module docstring. High
            # overlap with a polarity conflict is the reverse: the tokens match
            # because the claim was built by flipping its own source.
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

#: The predicted-claim judge. Deliberately not a softer version of the extracted
#: one — it asks a different question, because entailment is unanswerable here.
#:
#: A misconception or learning gap describes an error *students* make. The
#: passage is cited to say which material the error concerns, so the only
#: honest test is whether it points at the right material. The rubric below
#: still fails a prediction that wanders off the passage's topic entirely,
#: which is the real failure mode: a gap about integration filed against a
#: passage on set notation is a routing error worth catching.
#:
#: The instruction not to penalise a claim for contradicting the passage is
#: load-bearing. A misconception states something false on purpose; a judge left
#: to its own instincts marks that "unsupported" every time, which is what made
#: this check unpassable for the field.
_PREDICTED_JUDGE_SYSTEM = """You check whether a predicted student difficulty is \
filed against the right source passage.

Each claim describes a mistake, misconception or gap that STUDENTS are expected \
to have. The passage is not evidence that students make this mistake — no \
textbook records that. The passage identifies the material the difficulty is \
about.

So judge topical fit, not proof:
- supported: the difficulty plainly concerns what this passage teaches.
- partially_supported: loosely related — it touches the passage's topic but \
centres on something else.
- unsupported: the difficulty is about different material than this passage.

Do NOT mark a claim unsupported for stating something incorrect, or for \
contradicting the passage. A misconception is *meant* to state the wrong thing; \
that is the error being described, not a fault in the claim.

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

    # Batched by kind, never mixed: the two kinds are graded against different
    # rubrics, and one prompt cannot carry both without inviting the judge to
    # apply the wrong one to half its batch.
    batches = [
        (kind, [claim for claim in claims if claim.kind == kind])
        for kind in ("extracted", "predicted")
    ]

    for kind, of_kind in batches:
        system = _JUDGE_SYSTEM if kind == "extracted" else _PREDICTED_JUDGE_SYSTEM
        for start in range(0, len(of_kind), JUDGE_BATCH_SIZE):
            batch = of_kind[start : start + JUDGE_BATCH_SIZE]
            outcome = await llm.parse(
                stage=stage,
                output_model=GroundingJudgement,
                system=system,
                user_content=_judge_prompt(batch, chunks_by_id),
            )
            if outcome.degraded:
                any_degraded = True

            verdict_by_index = {v.index: v.verdict for v in outcome.value.verdicts}
            for index, claim in enumerate(batch):
                verdict = verdict_by_index.get(index)
                if verdict is None:
                    # A missing verdict is the judge's failure, not evidence the
                    # claim is bad — defaulting to "unsupported" would manufacture
                    # a false hallucination finding out of a degraded call.
                    results.append(
                        Verdicted(claim, "partially_supported", "judge returned no verdict")
                    )
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
            # Named for what actually went wrong. A mis-filed prediction is a
            # routing error — the difficulty is real, the passage is the wrong
            # one — and reporting it as an unsupported claim tells a teacher the
            # system invented something, which it did not.
            predicted = verdict.claim.kind == "predicted"
            issues.append(
                make_issue(
                    code=(
                        "GROUNDING_MISFILED_PREDICTION"
                        if predicted
                        else "GROUNDING_UNSUPPORTED_CLAIM"
                    ),
                    message=(
                        (
                            f"predicted difficulty at {verdict.claim.path} concerns "
                            f"different material than the passage it cites ({verdict.reason})"
                        )
                        if predicted
                        else (
                            f"claim at {verdict.claim.path} is not supported by its "
                            f"cited source ({verdict.reason})"
                        )
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
            predicted = verdict.claim.kind == "predicted"
            issues.append(
                make_issue(
                    code=(
                        "GROUNDING_LOOSELY_FILED_PREDICTION"
                        if predicted
                        else "GROUNDING_PARTIALLY_SUPPORTED_CLAIM"
                    ),
                    message=(
                        (
                            f"predicted difficulty at {verdict.claim.path} is only "
                            f"loosely related to the passage it cites ({verdict.reason})"
                        )
                        if predicted
                        else (
                            f"claim at {verdict.claim.path} is only partially supported "
                            f"by its cited source ({verdict.reason})"
                        )
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
