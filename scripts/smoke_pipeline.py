"""Live end-to-end run of the wired pipeline against a real provider.

Not part of ``make check`` — it costs real calls and needs a real key. It exists
because the test suite deliberately proves the plumbing with fixtures, and
fixtures cannot tell you whether a model actually returns four distinct MCQ
options or a rubric whose levels discriminate. That only shows up live.

    ./.venv/bin/python scripts/smoke_pipeline.py                # physics.pdf
    ./.venv/bin/python scripts/smoke_pipeline.py --doc history  # history.docx

The two documents are the versatility check: the same code path must yield
formulae and numerical questions for physics, and neither for history, without
either run naming its subject anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from core.config import get_settings
from core.llm.factory import build_llm_client
from core.storage.base import JobRecord
from core.storage.memory import InMemoryStore
from orchestration.pipeline import build_stages
from worker.runner import run_job

DOCS = {
    "physics": ("tests/fixtures/documents/physics.pdf", "application/pdf"),
    "history": (
        "tests/fixtures/documents/history.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}


def _resolve(name: str) -> tuple[Path, str]:
    """A known key, or any path on disk.

    Arbitrary paths matter more than the two fixtures: versatility is graded
    across subjects *and complexity ranges*, and two hand-made documents prove
    the mechanism, not the range.
    """
    if name in DOCS:
        relative, mime = DOCS[name]
        return ROOT / "backend" / relative, mime

    candidate = Path(name)
    if not candidate.is_absolute():
        candidate = ROOT / name
    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(candidate.suffix.lower(), "application/octet-stream")
    return candidate, mime


async def main(name: str) -> int:
    path, mime = _resolve(name)
    if not path.is_file():
        print(f"no such document: {path}")
        return 1
    payload = path.read_bytes()

    settings = get_settings()
    store = InMemoryStore()
    llm = build_llm_client(settings)

    job = JobRecord(id=uuid4(), document_id=uuid4(), options={})
    await store.create_job(job)

    seen: set[str] = set()

    async def emit(**event: object) -> None:
        stage = str(event.get("stage"))
        message = event.get("message")
        # One line per stage transition, plus anything carrying a message.
        if stage not in seen or message:
            seen.add(stage)
            suffix = f" — {message}" if message else ""
            print(f"  [{event.get('progress'):>3}%] {stage}{suffix}")

    store_emit = store.append_event

    async def _capture(evt):  # type: ignore[no-untyped-def]
        await emit(stage=evt.stage, progress=evt.progress, message=evt.message)
        return await store_emit(evt)

    store.append_event = _capture  # type: ignore[method-assign]

    print(
        f"\n=== {name}: {path.name} ({len(payload)} bytes), profile={settings.llm_profile} ==="
    )
    stages = build_stages(
        llm=llm,
        payload=payload,
        filename=path.name,
        mime=mime,
        max_bytes=settings.max_upload_bytes,
        max_pages=settings.max_pages,
        parse_timeout_s=float(settings.parse_timeout_s),
    )

    try:
        result = await run_job(store=store, job_id=job.id, stages=stages)
    except Exception as exc:  # noqa: BLE001 — a smoke run reports any failure legibly
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        return 1

    state = result.state
    classification = state.get("classification") or {}
    knowledge = state.get("knowledge") or {}
    plan = state.get("teaching_plan") or {}
    assessments = state.get("assessments") or {}
    items = assessments.get("items") or []

    print("\n--- result ---")
    print(f"  subject          {classification.get('subject')}")
    print(f"  profile          {classification.get('pedagogy_profile')}")
    print(f"  concepts         {len(knowledge.get('concepts') or [])}")
    print(f"  formulae         {len(knowledge.get('formulae') or [])}")
    print(f"  periods          {plan.get('total_periods')}")
    print(f"  period contents  {len(state.get('period_contents') or [])}")
    print(f"  activities       {len(state.get('activities') or [])}")
    print(f"  assessment items {len(items)} ({assessments.get('total_marks')} marks)")
    kinds: dict[str, int] = {}
    for item in items:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    print(f"  item kinds       {kinds}")
    print(f"  learning gaps    {len(state.get('learning_gaps') or [])}")

    usage = llm.usage
    print(
        f"\n  calls {len(llm.calls)} | tokens {usage.tokens_in}+{usage.tokens_out} "
        f"| cost ${usage.cost_usd:.4f}"
    )
    failed = [c for c in llm.calls if getattr(c, "error", None)]
    if failed:
        print(f"  {len(failed)} call(s) reported an error")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default="physics", help="a key from DOCS, or a file path")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.doc)))
