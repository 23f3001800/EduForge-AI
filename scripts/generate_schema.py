"""Regenerate the published TKP JSON Schema and the reference fixtures.

Run from the repo root:

    python scripts/generate_schema.py

The generated schema is committed. CI regenerates it and fails on any diff, so a
contract change cannot silently alter the published artifact that nine modules,
the frontend, and the API examples all depend on.

``--check`` regenerates into memory and diffs without writing — that is the CI
invocation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from contracts import SCHEMA_VERSION, TeacherKnowledgePackage
from tests.fixtures import factories

SCHEMA_DIR = BACKEND / "contracts" / "schema"
FIXTURE_DIR = BACKEND / "tests" / "fixtures" / "json"

#: Stage name -> zero-arg factory producing that stage's reference output.
#: Downstream stubs return exactly these.
STAGE_FIXTURES = {
    "structured_document": factories.structured_document,
    "chunks": lambda: factories.chunks(),
    "classification": factories.classification,
    "classification_narrative": factories.narrative_classification,
    "knowledge_base": factories.knowledge_base,
    "teaching_plan": factories.teaching_plan,
    "classroom_content": lambda: factories.classroom_content(),
    "activities": lambda: factories.activities(),
    "assessments": factories.assessments,
    "learning_gaps": lambda: factories.learning_gaps(),
    "validation_report": factories.validation_report,
    "teacher_knowledge_package": factories.teacher_knowledge_package,
}


def _dump(obj: object) -> str:
    if isinstance(obj, list):
        payload = [o.model_dump(mode="json") for o in obj]  # type: ignore[attr-defined]
    else:
        payload = obj.model_dump(mode="json")  # type: ignore[attr-defined]
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build() -> dict[Path, str]:
    """Return every generated file as {path: content}."""
    out: dict[Path, str] = {}

    schema = TeacherKnowledgePackage.model_json_schema(mode="serialization")
    schema["$id"] = f"https://eduforge.ai/schema/tkp-{SCHEMA_VERSION}.json"
    schema["title"] = "TeacherKnowledgePackage"
    schema["version"] = SCHEMA_VERSION
    out[SCHEMA_DIR / f"tkp-{SCHEMA_VERSION}.json"] = (
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )

    for name, factory in STAGE_FIXTURES.items():
        out[FIXTURE_DIR / f"{name}.json"] = _dump(factory())

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated output differs from disk.",
    )
    args = parser.parse_args()

    generated = build()
    drifted: list[Path] = []

    for path, content in generated.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        drifted.append(path)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    if args.check and drifted:
        print("Schema/fixture drift detected in:", file=sys.stderr)
        for path in drifted:
            print(f"  {path.relative_to(ROOT)}", file=sys.stderr)
        print(
            "\nContracts changed without regenerating. Run:\n"
            "  python scripts/generate_schema.py\n"
            "and commit the result.",
            file=sys.stderr,
        )
        return 1

    verb = "would update" if args.check else "wrote"
    print(
        f"{verb} {len(drifted) if drifted else 0} of {len(generated)} generated files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
