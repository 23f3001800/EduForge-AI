"""Evidence verification at extraction time.

A model asked for verbatim quotes will sometimes paraphrase, sometimes cite a
chunk that does not contain the claim, and occasionally invent a chunk id. All
three produce an item that *looks* cited and is not.

Catching this here rather than at stage 9 matters for two reasons: it is free
(pure string work, no model call), and a bad item removed now cannot propagate
into the teaching plan, the lesson content, and the assessments before anyone
notices. Stage 9 still runs the semantic check — this is the cheap deterministic
filter in front of it.

Quotes are normalised before comparison because PDF extraction mangles
whitespace, ligatures, and quotation marks in ways that are not the model's
fault. A quote that differs only in those respects is still verbatim.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

__all__ = ["EvidenceAudit", "normalise", "verify_items"]

_WHITESPACE = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})

#: Below this, a quote is treated as absent rather than merely reformatted.
FUZZY_THRESHOLD = 0.88
MIN_QUOTE_CHARS = 8


def normalise(text: str) -> str:
    """Collapse the differences that are extraction artefacts, not paraphrase."""
    folded = unicodedata.normalize("NFKD", text).translate(_QUOTES)
    return _WHITESPACE.sub(" ", folded).strip().casefold()


def _token_overlap(needle: str, haystack: str) -> float:
    """Share of the quote's tokens present in the chunk, in order-insensitive form.

    A cheap stand-in for alignment. Good enough to separate "reformatted" from
    "invented", which is the only distinction this filter needs to make.
    """
    needle_tokens = needle.split()
    if not needle_tokens:
        return 0.0
    haystack_tokens = set(haystack.split())
    hits = sum(1 for token in needle_tokens if token in haystack_tokens)
    return hits / len(needle_tokens)


@dataclass(slots=True)
class EvidenceAudit:
    """What verification did, so the outcome is reportable rather than silent."""

    kept: int = 0
    dropped_no_evidence: int = 0
    dropped_unknown_chunk: int = 0
    dropped_quote_absent: int = 0
    repaired_quote: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return (
            self.dropped_no_evidence + self.dropped_unknown_chunk + self.dropped_quote_absent
        )

    def summary(self) -> str:
        return (
            f"kept {self.kept}, dropped {self.dropped} "
            f"(no evidence {self.dropped_no_evidence}, "
            f"unknown chunk {self.dropped_unknown_chunk}, "
            f"quote absent {self.dropped_quote_absent}), "
            f"repaired {self.repaired_quote}"
        )


def verify_items(
    items: list[dict[str, Any]],
    chunks_by_id: dict[str, str],
    *,
    label: str,
    audit: EvidenceAudit | None = None,
) -> tuple[list[dict[str, Any]], EvidenceAudit]:
    """Keep only items whose citations actually check out.

    An item survives if at least one of its evidence entries names a real chunk
    and quotes text that chunk genuinely contains. Surviving items have their
    unverifiable evidence entries stripped, so nothing downstream inherits a
    citation that does not hold.
    """
    audit = audit or EvidenceAudit()
    normalised_chunks = {cid: normalise(text) for cid, text in chunks_by_id.items()}
    kept: list[dict[str, Any]] = []

    for item in items:
        evidence = item.get("evidence") or []
        if not evidence:
            audit.dropped_no_evidence += 1
            continue

        verified: list[dict[str, Any]] = []
        reasons: set[str] = set()

        for entry in evidence:
            chunk_id = entry.get("chunk_id")
            quote = (entry.get("quote") or "").strip()

            if chunk_id not in normalised_chunks:
                reasons.add("unknown_chunk")
                continue
            if len(quote) < MIN_QUOTE_CHARS:
                reasons.add("quote_absent")
                continue

            haystack = normalised_chunks[chunk_id]
            needle = normalise(quote)

            if needle in haystack:
                verified.append(entry)
                continue

            # Not an exact substring: decide between "reformatted" and "invented".
            if _token_overlap(needle, haystack) >= FUZZY_THRESHOLD:
                entry = {**entry, "confidence": min(entry.get("confidence", 1.0), 0.7)}
                verified.append(entry)
                audit.repaired_quote += 1
                continue

            reasons.add("quote_absent")

        if verified:
            item = {**item, "evidence": verified}
            kept.append(item)
            audit.kept += 1
            continue

        if "unknown_chunk" in reasons:
            audit.dropped_unknown_chunk += 1
        else:
            audit.dropped_quote_absent += 1

    if audit.dropped:
        audit.notes.append(f"{label}: {audit.summary()}")

    return kept, audit
