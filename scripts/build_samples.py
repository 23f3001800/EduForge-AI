"""Regenerate `samples/` from the reference fixtures.

Built from fixtures rather than from a live run, deliberately: the numbers in
`samples/README.md` are quoted as evidence, and evidence a reader cannot
reproduce is not evidence. A fixture-built sample is byte-stable, needs no API
key, and costs nothing, so anyone who checks out the repo gets the same scores.

The live path is `scripts/smoke_pipeline.py`, which is where model output is
actually exercised.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from contracts import TeacherKnowledgePackage
from evals.harness import evaluate
from evals.report import to_json, to_markdown
from stages.s10_publishing.render import RENDERERS
from tests.fixtures import factories as fx

OUT = ROOT / "samples"

#: Rendered artifact filenames. `tkp_json` is skipped — the package is already
#: written out under its own name.
FILENAMES = {
    "lesson_plan_pdf": "lesson_plan.pdf",
    "teacher_guide_pdf": "teacher_guide.pdf",
    "assessment_book_pdf": "assessment_book.pdf",
    "markdown_bundle": "markdown.md",
}


def quantitative() -> dict[str, Any]:
    return fx.teacher_knowledge_package().model_dump(mode="json")


def narrative() -> dict[str, Any]:
    """The humanities counterpart: no formulae, no numerical items.

    Numerical items are substituted rather than deleted — removing them would
    shrink the bank and depress coverage for reasons that have nothing to do with
    the profile, which would misrepresent the very comparison this sample exists
    to make.
    """
    package = copy.deepcopy(quantitative())
    package["classification"] = fx.narrative_classification().model_dump(mode="json")
    package["knowledge"]["formulae"] = []

    for item in package["assessments"]["items"]:
        if item["kind"] != "numerical":
            continue
        item["kind"] = "short_answer"
        item["working"] = None
        item["options"] = None
        if not item.get("rubric"):
            item["rubric"] = {
                "criteria": "Whether the answer names the cause and justifies it.",
                "levels": [
                    {
                        "label": "Complete",
                        "descriptor": "Names the cause and justifies it from the source.",
                        "marks": item["marks"],
                    },
                    {
                        "label": "Partial",
                        "descriptor": "Names the cause without justifying it.",
                        "marks": max(1, item["marks"] // 2),
                    },
                ],
            }
    return package


def write(name: str, payload: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
    directory = OUT / name
    directory.mkdir(parents=True, exist_ok=True)

    (directory / "teacher_knowledge_package.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    tkp = TeacherKnowledgePackage.model_validate(payload)
    for kind, filename in FILENAMES.items():
        render = RENDERERS.get(kind)
        if render is None:
            continue
        data = render(tkp)
        (directory / filename).write_bytes(
            data if isinstance(data, bytes) else data.encode("utf-8")
        )

    report = evaluate(payload, chunks=chunks)
    (directory / "eval-report.json").write_text(
        json.dumps(to_json(report), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (directory / "eval-report.md").write_text(to_markdown(report), encoding="utf-8")

    excused = len(report.absent_by_design)
    print(f"  {name:22} overall {report.overall:.3f}  absent_by_design={excused}")


def main() -> int:
    chunks = [c.model_dump(mode="json") for c in fx.chunks()]
    print(f"writing {OUT.relative_to(ROOT)}/")
    write("quantitative-physics", quantitative(), chunks)
    write("narrative-history", narrative(), chunks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
