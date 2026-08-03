"""Checks that separate quality from length.

Every metric replaced by this module had the same defect: a word count standing
in for a judgement. ``MIN_DESCRIPTOR_WORDS = 5`` says a five-word rubric level is
substantial; ``MIN_NOTE_WORDS = 8`` says an eight-word speaker note is a script.
Both are false in the direction that matters, because the failure mode being
measured is *padding*, and padding is long by construction. A harness whose only
substance test is length hands the generator a gradient pointing straight at more
words, and the measured result was exactly that: filler speaker notes scored
**above** the reference package they replaced.

Three replacements live here, and each asks a question length cannot answer.

**Do adjacent rubric levels differ in what the work contains?** Not "do the
strings differ" — a Jaccard test passes for "an excellent response" against "a
good response", which is one adjective apart and cannot separate two scripts.
The comparison strips function words *and evaluative words* first, so what is
left is the substance each level claims: a value, a unit, a method, a cause, a
citation. Two levels whose remainders are equal do not discriminate however
different their adjectives, and a level whose remainder is empty describes no
work at all.

**Does a speaker note instruct?** A script segment is read aloud and acted on, so
it must contain an imperative and must name something this package teaches.
"Take a moment here to engage the students in a meaningful way" has the
imperative and names nothing; it would fit any lesson on any topic, which is the
definition of the failure. Generic-script phrasing is matched explicitly, because
the phrases generated padding uses are a small and stable set.

**Is an instruction anchored to this package?** :func:`evals.text.has_concrete_anchor`
accepts a digit, a quotation mark, or a colon as proof of concreteness. "Spend
5 minutes on this" and "Do the following:" both pass, and neither names any
content. :func:`names_package_content` accepts only the package's own teaching
vocabulary, which is the one probe that cannot be satisfied by formatting.

Nothing here knows what subject it is reading. The word lists are closed-class
function words and grading adjectives; the content probe is the package's own
vocabulary. A poetry package and a mechanics package are measured by identical
code against their own terms.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise

from evals.lexicons import (
    EVALUATIVE_MARKERS,
    FUNCTION_WORDS,
    GENERIC_SCRIPT_MARKERS,
    IMPERATIVE_TEACHING_VERBS,
    UNOBSERVABLE_MARKERS,
)
from evals.text import mentions_vocabulary, normalise, sentences, tokens

__all__ = [
    "content_words",
    "descriptor_discrimination",
    "has_imperative",
    "is_generic_script",
    "names_package_content",
    "note_is_actionable",
]

#: A token shorter than this carries no content on its own. Deliberately low — it
#: keeps "ice", "sun", "war" — because the cut has to be safe across content
#: shapes, and it is the stop-lists rather than the length that do the work.
_MIN_CONTENT_TOKEN = 3

#: Everything filtered out before a text is asked what it names: closed-class
#: function words, grading adjectives, and the unobservable-state nouns that make
#: a descriptor sound substantive while describing nothing observable.
_NOISE: frozenset[str] = (
    FUNCTION_WORDS | EVALUATIVE_MARKERS | frozenset(m for m in UNOBSERVABLE_MARKERS if " " not in m)
)

#: Strips a possessive or plural so "units" and "unit" count as the same content.
#: Crude on purpose: a real stemmer would be a dependency and a subject-shaped
#: opinion, and the only thing needed here is that trivial morphology does not
#: read as a difference in substance.
_SUFFIX = re.compile(r"(?:'s|s)$")


def _stem(token: str) -> str:
    if len(token) <= 3:
        return token
    return _SUFFIX.sub("", token) or token


def content_words(text: str) -> set[str]:
    """What this text actually names, with tone and grammar removed.

    "The response demonstrates an excellent understanding overall" reduces to the
    empty set, which is the correct reading: it names nothing the work contains.
    "Correct method, wrong units" reduces to ``{method, unit}``.
    """
    return {
        _stem(token)
        for token in tokens(text)
        if len(token) >= _MIN_CONTENT_TOKEN and token not in _NOISE and not token.isdigit()
    }


def descriptor_discrimination(descriptors: Sequence[str]) -> float:
    """Can a marker tell these levels apart by what the work contains?

    Two components, both necessary:

    * every level must name *something* — an empty content set is a level that
      grades a feeling;
    * every adjacent pair must differ in that naming — the higher level has to
      claim content the lower one does not, which is what a marker looks for on
      a borderline script.

    Returns 1.0 only when both hold for every level and every pair. A rubric of
    one level cannot discriminate at all and scores 0.0 rather than trivially
    passing for having no adjacent pair to check.
    """
    if len(descriptors) < 2:
        return 0.0

    sets = [content_words(d) for d in descriptors]
    substantive = sum(1 for s in sets if s) / len(sets)

    pairs = list(pairwise(sets))
    distinct = sum(1 for a, b in pairs if (a - b) or (b - a)) / len(pairs)

    return (substantive + distinct) / 2


def has_imperative(text: str) -> bool:
    """Does any sentence here open with an instruction to the teacher?

    Read at sentence starts rather than anywhere in the string, because that is
    where an imperative sits in English and because a note *mentioning* "ask" is
    not the same as a note that says "Ask...".
    """
    for sentence in sentences(text) or [text]:
        found = tokens(sentence)
        if found and found[0] in IMPERATIVE_TEACHING_VERBS:
            return True
    return False


def is_generic_script(text: str) -> bool:
    """Is this a sentence about teaching rather than an instruction to teach?"""
    folded = normalise(text)
    return any(marker in folded for marker in GENERIC_SCRIPT_MARKERS)


def names_package_content(text: str, vocabulary: frozenset[str]) -> bool:
    """Does this name something *this package* teaches?

    The strict counterpart to ``has_concrete_anchor``, which also accepts a digit
    or a colon. Formatting is not specificity, and an instruction that survives
    having the topic swapped out was never anchored to the topic.
    """
    return mentions_vocabulary(text, vocabulary)


def note_is_actionable(text: str, vocabulary: frozenset[str], *, context: str = "") -> bool:
    """Could a teacher who has not pre-read this act on it as written?

    Three conditions, and the length of the note is not one of them: it must
    instruct, it must not be generic-teaching prose, and it must name content
    from this package. ``context`` folds in the segment's heading and board
    action, which are part of the same instruction and often carry the referent.
    """
    if is_generic_script(text):
        return False
    if not has_imperative(text):
        return False
    return names_package_content(f"{text} {context}", vocabulary)
