"""Command line for the evaluation framework.

``make evals`` runs the test suite, which proves the harness discriminates. This
is the other half: pointing it at a package and reading the answer. It exists so
the framework is usable without the API running — a reviewer with a checkout and
no key can score every sample in the repo in under a second.

    python -m evals score samples/quantitative-physics
    python -m evals score samples/*/ --format markdown
    python -m evals score samples/quantitative-physics --pdf report.pdf
    python -m evals benchmark --history var/evals.sqlite3

Exit code 1 when a package has a high-severity recommendation, so this can gate
a build. Not on the score: a threshold on an aggregate invites tuning the
aggregate, whereas a high-severity finding names a specific defect someone has
to look at.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals.export import to_markdown, to_pdf
from evals.service import evaluate_package
from evals.store import EvaluationStore

_PACKAGE_NAME = "teacher_knowledge_package.json"


def _load(target: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a package and, if one sits beside it, the chunks it came from."""
    path = target / _PACKAGE_NAME if target.is_dir() else target
    package = json.loads(path.read_text(encoding="utf-8"))

    chunks: list[dict[str, Any]] = []
    beside = path.parent / "chunks.json"
    if beside.is_file():
        loaded = json.loads(beside.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            chunks = [c for c in loaded if isinstance(c, dict)]
    return package, chunks


def _print_table(document: dict[str, Any]) -> None:
    summary = document["summary"]
    stage = summary["stage_score"]
    print(f"\n{document['subject']} · {document['profile']} · {document['package_id']}")
    print(
        f"  stage score   {stage if stage is None else f'{stage:.1f}'} / 100"
        f"   (confidence {summary['stage_confidence']:.0%}, "
        f"{summary['stages_scored']}/{summary['stages_total']} stages)"
    )
    print(f"  rubric score  {summary['rubric_score']:.1f} / 100   ({summary['rubric_band']})")
    print()
    for entry in document["stages"]:
        score = entry["score"]
        shown = "   n/a" if score is None else f"{score:6.1f}"
        blocked = f"  ({entry['not_measurable']} not measurable)" if entry["not_measurable"] else ""
        print(f"  {shown}  {entry['label']:<30}{blocked}")

    high = [r for r in document["recommendations"] if r["severity"] == "high"]
    print(f"\n  {len(document['recommendations'])} recommendation(s), {len(high)} high severity")
    for rec in high:
        print(f"    ! {rec['stage']}/{rec['metric']}: {rec['action']}")
    print(f"  {len(document['not_measurable'])} metric(s) carry no score — see the report")
    print(f"  history: {document['comparison']['detail']}")


def _score(args: argparse.Namespace) -> int:
    history = EvaluationStore(args.history) if args.history else None
    worst = 0

    for target in args.targets:
        path = Path(target)
        if not path.exists():
            print(f"no such path: {target}", file=sys.stderr)
            return 2

        package, chunks = _load(path)
        document = evaluate_package(
            package,
            chunks=chunks,
            run_id=args.run_id or (path.name if path.is_dir() else path.stem),
            store=history,
            persist=history is not None,
        )

        if args.format == "json":
            print(json.dumps(document, indent=2, sort_keys=True))
        elif args.format == "markdown":
            print(to_markdown(document))
        else:
            _print_table(document)

        if args.pdf:
            Path(args.pdf).write_bytes(to_pdf(document))
            print(f"\n  wrote {args.pdf}")

        if any(r["severity"] == "high" for r in document["recommendations"]):
            worst = 1

    if history:
        history.close()
    return worst


def _benchmark(args: argparse.Namespace) -> int:
    history = EvaluationStore(args.history)
    print(json.dumps(history.benchmark(profile=args.profile), indent=2, sort_keys=True))
    history.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score", help="Evaluate one or more packages.")
    score.add_argument("targets", nargs="+", help="Package JSON files, or directories holding one.")
    score.add_argument("--format", choices=("table", "json", "markdown"), default="table")
    score.add_argument("--pdf", help="Also write the report to this path.")
    score.add_argument("--history", help="SQLite file to append this run to.")
    score.add_argument("--run-id", help="Identify this run in the history series.")
    score.set_defaults(func=_score)

    bench = sub.add_parser("benchmark", help="Score distribution across stored history.")
    bench.add_argument("--history", required=True)
    bench.add_argument("--profile", default=None)
    bench.set_defaults(func=_benchmark)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
