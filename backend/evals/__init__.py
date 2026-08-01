"""EduForge quality evaluation — is the generated material good *teaching*?

Schema validation answers whether a package parses. Stage 9 answers whether it is
internally consistent. Neither answers the question this package exists for: would
a teacher use this on Monday? That question is ~45% of what this project is graded
on, and it is the one every automated check in the repository currently passes
while remaining silent about.

The rubric has nine dimensions (``evals.dimensions``), weighted to sum to 1.0.
Eight of the nine are fully deterministic; one is hybrid, with a judged component
that is optional, gated, and never load-bearing. That ratio is deliberate:
deterministic metrics are free, reproducible, and cannot flatter the system, so
anything computable is computed rather than asked about.

The property the whole design turns on: **expectations are conditioned on the
pedagogy profile, resolved through data.** A narrative package with zero formulae
and zero numerical questions scores *well* — not because a special case says so,
but because what a package owes is read from ``pedagogy/profiles.yaml``, the same
source the generator used. There is no subject name anywhere in this package and
there cannot be one; a harness that rewarded STEM shape would make the system
worse one score at a time.

Usage:

    from evals import evaluate
    report = evaluate(package, chunks=chunks)
    print(report.overall, report.band)

or from the command line, which is what ``make evals`` runs::

    python -m evals score samples/01-quantitative-newtons-laws
    python -m evals publish --out samples
"""

from evals.harness import EvalProfileError, evaluate, require_eval_profile
from evals.report import to_json, to_markdown, to_table
from evals.types import (
    BANDS,
    DimensionScore,
    EvalReport,
    Finding,
    Judgements,
    Metric,
    band_for,
)

__all__ = [
    "BANDS",
    "DimensionScore",
    "EvalProfileError",
    "EvalReport",
    "Finding",
    "Judgements",
    "Metric",
    "band_for",
    "evaluate",
    "require_eval_profile",
    "to_json",
    "to_markdown",
    "to_table",
]
