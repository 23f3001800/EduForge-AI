"""Shared issue-construction helper for the four rule classes.

Every rule module below builds plain ``dict`` issues rather than
``contracts.validation.ValidationIssue`` instances directly. That is deliberate:
a rule that has already found five problems must keep looking for the sixth
instead of raising on the first one, and a dict is cheap to accumulate. The stage
converts the whole list to typed ``ValidationIssue`` objects once, at the end,
where a genuinely malformed issue (which would indicate a bug in this package,
not in the TKP being checked) is the only thing that should raise.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["IssueDict", "Severity", "make_issue"]

Severity = Literal["error", "warning", "info"]

#: What a rule function hands back. Matches ``contracts.validation.ValidationIssue``
#: field-for-field so ``ValidationIssue.model_validate(d)`` always succeeds.
IssueDict = dict[str, str]


def make_issue(
    *, code: str, message: str, path: str, stage: str, severity: Severity = "error"
) -> IssueDict:
    """Build one issue dict.

    ``stage`` is the owner the repair router acts on (docs/03 § 4.5) — it is not
    necessarily the stage whose *output* looks wrong; it is the stage that must
    regenerate to fix it. A dangling ``activity_ref``, for example, is reported
    against ``lesson-generation`` because that is where the reference was written,
    even though the missing activity itself is stage 6's output.
    """
    return {"code": code, "severity": severity, "message": message, "path": path, "stage": stage}
