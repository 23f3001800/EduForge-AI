"""Re-render each sample's PDFs from its committed package.

Rendering is deterministic and calls no model, so the artifacts under
``samples/`` can be regenerated from the packages whenever stage 10's
typography changes — without re-running a pipeline that costs money and would
also change the content, making the two impossible to compare.

    python scripts/rerender_samples.py

The package JSON is the source of truth and is never touched. Only the rendered
files are rewritten, which is the right split: a sample's *content* is evidence
from a real run and must not be edited, while its *presentation* is a pure
function of the current renderer and should track it.
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts.tkp import TeacherKnowledgePackage
from stages.s10_publishing.render.assessment_book import render_assessment_book_pdf
from stages.s10_publishing.render.lesson_plan import render_lesson_plan_pdf
from stages.s10_publishing.render.markdown_bundle import render_markdown_bundle
from stages.s10_publishing.render.teacher_guide import render_teacher_guide_pdf

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
PACKAGE_NAME = "teacher_knowledge_package.json"

RENDERERS = {
    "lesson_plan.pdf": render_lesson_plan_pdf,
    "teacher_guide.pdf": render_teacher_guide_pdf,
    "assessment_book.pdf": render_assessment_book_pdf,
    "markdown.md": render_markdown_bundle,
}


def main() -> int:
    directories = sorted(d for d in SAMPLES.iterdir() if (d / PACKAGE_NAME).is_file())
    if not directories:
        print("no sample packages found")
        return 1

    for directory in directories:
        raw = json.loads((directory / PACKAGE_NAME).read_text(encoding="utf-8"))
        tkp = TeacherKnowledgePackage.model_validate(raw)
        print(directory.name)
        for filename, render in RENDERERS.items():
            target = directory / filename
            # Only rewrite what the capture actually produced. A package with no
            # markdown bundle should not acquire one here.
            if not target.is_file():
                continue
            target.write_bytes(render(tkp))
            print(f"  {filename:22s} {target.stat().st_size / 1024:6.0f} KB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
