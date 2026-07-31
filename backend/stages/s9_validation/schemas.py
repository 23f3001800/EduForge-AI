"""The grounding judge's output schema — deliberately tiny.

Stage 3's extraction schemas were split in two after a wide schema produced
``json_validate_failed`` with an *empty* generation on a small model
(``stages/s3_knowledge/schemas.py``): the schema itself, before the document even
arrives, ate the output budget. The judge here asks for even less — an index and
a three-way verdict per claim, nothing nested, nothing free-text — because it
only ever has to resolve the ambiguous middle band the lexical pre-filter could
not decide (``stages/s9_validation/grounding.py``), and that has to survive on
whatever model a given deployment profile points ``validation`` at.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from contracts.primitives import StrictModel

__all__ = ["ClaimVerdict", "GroundingJudgement", "Verdict"]

Verdict = Literal["supported", "partially_supported", "unsupported"]


class ClaimVerdict(StrictModel):
    """One judged claim. ``index`` ties it back to the batch position it was sent at."""

    index: int = Field(ge=0)
    verdict: Verdict


class GroundingJudgement(StrictModel):
    """A whole batch's worth of verdicts, in one call."""

    verdicts: list[ClaimVerdict] = Field(default_factory=list)
