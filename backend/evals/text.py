"""Text primitives shared by the deterministic metrics.

The normalisation idea is the same one ``stages/s9_validation/grounding.py`` uses
— fold extraction artefacts before comparing, because smart quotes and stray
whitespace are the PDF's fault, not the generator's. This is a fresh
implementation rather than an import, deliberately: an eval that calls the code it
is grading regresses in lockstep with it and stops being independent evidence.

Two deviations from the stage-9 implementation, both intentional:

* Tokens are punctuation-stripped, so ``motion.`` and ``motion`` match. Stage 9
  splits on whitespace and treats those as different tokens, which understates
  overlap on any claim that ends a sentence.
* ``contains_verbatim`` compares folded token streams rather than raw substrings,
  so ``F = m a.`` is found inside ``F = m a``. Citation integrity should not turn
  on an equals sign.

:func:`mentions_vocabulary` is the workhorse behind every specificity check in the
harness. "Provide extra support to weaker students" and "Give the rearranged form
a = F/m on the sheet" are indistinguishable by length, sentiment, or grammar; they
are trivially distinguishable by whether they mention anything this package
actually teaches. That test is subject-agnostic by construction — the vocabulary
comes from the package, never from a word list about a subject.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

__all__ = [
    "build_vocabulary",
    "contains_verbatim",
    "distinct_ratio",
    "fold",
    "has_concrete_anchor",
    "jaccard",
    "leading_verb",
    "lexical_overlap",
    "long_word_share",
    "mean_words_per_sentence",
    "mentions_vocabulary",
    "normalise",
    "sentences",
    "tokens",
    "word_count",
]

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_SENTENCE_SPLIT = re.compile(r"[.!?;]+\s+|\n+")
_VOWEL_GROUP = re.compile(r"[aeiouy]+")
# Keyed by code point: the glyphs themselves are what ruff flags as ambiguous
# unicode wherever they appear unescaped in a literal.
_PUNCT_FOLD = str.maketrans(
    {
        0x2018: "'",
        0x2019: "'",
        0x201C: '"',
        0x201D: '"',
        0x2013: "-",
        0x2014: "-",
    }
)

#: Words too short or too common to prove that a sentence is about this package.
#: Length alone is the filter — no domain terms, so no subject leaks in here.
_MIN_VOCAB_TERM = 4

#: Above this token overlap two strings are the same string with the serial
#: numbers filed off. Copy-paste across periods is the most common way generated
#: content is padded, and it is invisible to every schema check.
NEAR_DUPLICATE = 0.85


def normalise(text: str) -> str:
    """Fold case, unicode form, smart punctuation, and whitespace."""
    folded = unicodedata.normalize("NFKD", text).translate(_PUNCT_FOLD)
    return _WHITESPACE.sub(" ", folded).strip().casefold()


def tokens(text: str) -> list[str]:
    """Alphanumeric tokens, punctuation discarded."""
    return _TOKEN.findall(normalise(text))


def fold(text: str) -> str:
    """Token stream rejoined — punctuation-insensitive comparison surface."""
    return " ".join(tokens(text))


def contains_verbatim(quote: str, span: str) -> bool:
    """Does ``quote`` appear in ``span``, ignoring punctuation and case?"""
    needle = fold(quote)
    return bool(needle) and needle in fold(span)


def lexical_overlap(claim: str, span: str) -> float:
    """Share of the claim's tokens that also occur in the span, order-insensitive.

    A cheap bound on entailment: enough to separate "clearly supported", "clearly
    unrelated", and "a human or a judge has to read this", which is the only
    distinction a pre-filter needs to make.
    """
    claim_tokens = tokens(claim)
    if not claim_tokens:
        return 0.0
    span_tokens = set(tokens(span))
    return sum(1 for token in claim_tokens if token in span_tokens) / len(claim_tokens)


def jaccard(left: str, right: str) -> float:
    a, b = set(tokens(left)), set(tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def distinct_ratio(texts: Sequence[str], threshold: float = NEAR_DUPLICATE) -> float:
    """Fraction of the strings that are not near-duplicates of an earlier one.

    Greedy clustering, which is fine at these sizes and has the property that
    matters: five paraphrases of one instruction score 0.2, not 1.0.
    """
    if not texts:
        return 1.0
    kept: list[str] = []
    for text in texts:
        if not any(jaccard(text, seen) >= threshold for seen in kept):
            kept.append(text)
    return len(kept) / len(texts)


def word_count(text: str) -> int:
    return len(tokens(text))


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


def mean_words_per_sentence(texts: Iterable[str]) -> float:
    counts = [word_count(sentence) for text in texts for sentence in sentences(text)]
    counts = [c for c in counts if c]
    return sum(counts) / len(counts) if counts else 0.0


def _syllables(word: str) -> int:
    return len(_VOWEL_GROUP.findall(word)) or 1


def long_word_share(texts: Iterable[str]) -> float:
    """Share of words with three or more vowel groups.

    A crude readability proxy, and labelled as one everywhere it is used: it is
    reported, never scored, because polysyllabic words are also just what some
    topics are made of.
    """
    words = [w for text in texts for w in tokens(text)]
    if not words:
        return 0.0
    return sum(1 for w in words if _syllables(w) >= 3) / len(words)


def leading_verb(statement: str) -> str:
    """First token of a statement, which for an objective is its verb.

    Objectives are written in the imperative-of-the-learner form the contract asks
    for ("Explain how...", "Calculate the..."), so the first token is the verb in
    every well-formed case — and where it is not, that is itself the finding.
    """
    found = tokens(statement)
    return found[0] if found else ""


def build_vocabulary(package: Mapping[str, Any]) -> frozenset[str]:
    """The terms this package itself teaches, for use as a specificity probe.

    Sourced from concept names, keywords, defined terms, formula names, and period
    and activity titles. Nothing here is domain-specific: the same code yields
    ``{inertia, acceleration, ...}`` for one document and ``{partition, swadeshi,
    ...}`` for another, which is exactly why it can measure specificity without
    knowing what subject it is looking at.
    """
    knowledge: Mapping[str, Any] = package.get("knowledge") or {}
    raw: list[str] = []

    raw += [str(c.get("name", "")) for c in knowledge.get("concepts") or []]
    raw += [str(k) for k in knowledge.get("keywords") or []]
    raw += [str(d.get("term", "")) for d in knowledge.get("definitions") or []]
    raw += [str(f.get("name") or "") for f in knowledge.get("formulae") or []]
    periods = (package.get("teaching_plan") or {}).get("periods") or []
    raw += [str(p.get("title", "")) for p in periods]
    raw += [str(a.get("title", "")) for a in package.get("activities") or []]

    terms: set[str] = set()
    for entry in raw:
        folded = fold(entry)
        if not folded:
            continue
        if len(folded) >= _MIN_VOCAB_TERM:
            terms.add(folded)
        terms.update(t for t in tokens(entry) if len(t) >= _MIN_VOCAB_TERM)
    return frozenset(terms)


def mentions_vocabulary(text: str, vocabulary: frozenset[str]) -> bool:
    """Does this sentence name anything the package actually teaches?"""
    if not vocabulary:
        return False
    folded = fold(text)
    if not folded:
        return False
    present = set(tokens(text))
    return any(term in present if " " not in term else term in folded for term in vocabulary)


_DIGIT = re.compile(r"\d")
_FRAME = re.compile(r"['\"]|\bsentence (?:frame|starter)\b|\btemplate\b|:\s*\S")


def has_concrete_anchor(text: str, vocabulary: frozenset[str]) -> bool:
    """Is this instruction anchored to something a teacher could point at?

    Three ways to qualify, any one of which is enough: it names package
    vocabulary, it contains a number, or it supplies a literal (a quoted sentence
    frame, a worked form after a colon). Generic advice does none of the three.
    """
    return bool(mentions_vocabulary(text, vocabulary) or _DIGIT.search(text) or _FRAME.search(text))
