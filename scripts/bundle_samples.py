"""Bundle every sample package into one JSON file, for a single-file upload.

Submission portals often take one file. The canonical artifacts stay the
per-directory ones under ``samples/`` — this is a view over them, not a
replacement, and it is regenerated rather than maintained so the two can never
disagree.

    python scripts/bundle_samples.py

Writes ``samples/teacher_knowledge_packages.json``: a header saying what each
package is and how it was produced, then the packages themselves, unmodified.

The header matters more than it looks. A reader handed two packages in one file
has no directory names, no source PDF beside them, and no way to tell whether
they came from a real run or were typed by hand — which is exactly the ambiguity
that made the previous, fabricated samples look plausible. So each entry states
its source document, its model, and its validation status, and the validation
status is copied from the package rather than asserted here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
OUT = SAMPLES / "teacher_knowledge_packages.json"
PACKAGE_NAME = "teacher_knowledge_package.json"


def _entry(directory: Path) -> dict[str, Any]:
    package = json.loads((directory / PACKAGE_NAME).read_text(encoding="utf-8"))
    classification = package.get("classification") or {}
    validation = package.get("validation") or {}
    source = package.get("source") or {}
    generator = package.get("generator") or {}
    knowledge = package.get("knowledge") or {}
    plan = package.get("teaching_plan") or {}

    models = sorted({str(v) for v in (generator.get("models_by_stage") or {}).values()})

    return {
        "name": directory.name,
        "produced_by": (
            "A live run of the ten-stage pipeline through the HTTP API "
            "(scripts/capture_sample.py). Not assembled from fixtures."
        ),
        "source_document": {
            "filename": source.get("filename"),
            "pages": source.get("page_count"),
            "words": source.get("word_count"),
            "also_committed_at": f"samples/{directory.name}/source.pdf",
        },
        "models": models,
        "at_a_glance": {
            "subject": classification.get("subject"),
            "topic": classification.get("topic"),
            "pedagogy_profile": classification.get("pedagogy_profile"),
            "concepts": len(knowledge.get("concepts") or []),
            "formulae": len(knowledge.get("formulae") or []),
            "periods": plan.get("total_periods"),
            "assessment_items": len((package.get("assessments") or {}).get("items") or []),
            # Copied, never asserted: both packages fail validation, and a
            # bundle that quietly presented them as clean would be the same
            # dishonesty the fabricated samples committed.
            "validation_status": validation.get("status"),
            "grounding_score": validation.get("grounding_score"),
        },
        "package": package,
    }


def main() -> int:
    directories = sorted(d for d in SAMPLES.iterdir() if (d / PACKAGE_NAME).is_file())
    if not directories:
        print("no sample packages found; run `make samples` first")
        return 1

    bundle = {
        "schema_version": "1.0.0",
        "bundled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "what_this_is": (
            "Teacher Knowledge Packages produced by EduForge AI, bundled into one "
            "file for submission. Each entry's `package` is the artifact exactly as "
            "the pipeline published it. The per-directory copies under samples/ are "
            "canonical; this file is regenerated from them."
        ),
        "reproduce": (
            "make dev, then: python scripts/capture_sample.py "
            "samples/<name>/source.pdf --name <name>"
        ),
        "packages": [_entry(d) for d in directories],
    }

    OUT.write_text(
        json.dumps(bundle, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    size_mb = OUT.stat().st_size / 1e6
    print(f"wrote {OUT.relative_to(ROOT)} ({size_mb:.1f} MB)")
    for entry in bundle["packages"]:
        glance = entry["at_a_glance"]
        print(
            f"  {entry['name']:22s} {glance['subject']} / {glance['pedagogy_profile']}"
            f"  · {glance['concepts']} concepts · validation {glance['validation_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
