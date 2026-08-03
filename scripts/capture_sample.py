"""Capture a sample by running the real pipeline through the real API.

This replaces ``scripts/build_samples.py``, which assembled ``samples/`` from
the test fixtures. That approach produced byte-stable, key-free, zero-cost
samples — and samples that had never been near the pipeline. One of them was the
physics package with ``subject`` overwritten to "History", so it presented a
lesson plan about Newton's first law under the heading "The Partition of
Bengal". A reader who diffs two samples built that way does not conclude
"fixture"; they conclude the evidence was manufactured.

So this drives the system the way a teacher does: POST the document, create the
job, watch the stream, download what comes out. Nothing is hand-written and
nothing is post-processed. If the pipeline is broken the sample is broken, which
is the entire point — a sample is evidence, and evidence that cannot fail is not
evidence.

    python scripts/capture_sample.py Books/leph101.pdf --name quantitative-physics

The server must already be running (``make dev``). Costs real model calls.

The evaluation report is captured from the API rather than recomputed offline.
That matters for one specific reason: the API resolves the run's source chunks
from its stage-1 checkpoint, so the citation-integrity check — the only check
that can catch a fabricated quote — actually runs. Scoring the published
package alone would report that metric unmeasurable and quietly drop the most
important number in the report.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"

#: Artifact kind -> filename on disk. Mirrors what the API serves.
FILENAMES = {
    "lesson_plan_pdf": "lesson_plan.pdf",
    "teacher_guide_pdf": "teacher_guide.pdf",
    "assessment_book_pdf": "assessment_book.pdf",
    "markdown_bundle": "markdown.md",
}

TERMINAL = {"succeeded", "succeeded_partial", "failed", "cancelled"}


def _upload(client: httpx.Client, path: Path) -> str:
    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(path.suffix.lower(), "application/octet-stream")

    response = client.post(
        "/api/v1/documents", files={"file": (path.name, path.read_bytes(), mime)}
    )
    response.raise_for_status()
    return str(response.json()["document_id"])


def _run(
    client: httpx.Client, document_id: str, options: dict[str, Any]
) -> dict[str, Any]:
    created = client.post(
        "/api/v1/jobs",
        json={"document_id": document_id, **options},
        headers={"Idempotency-Key": f"capture-{document_id}-{int(time.time())}"},
    )
    created.raise_for_status()
    job_id = created.json()["job_id"]
    print(f"  job {job_id}")

    last = ""
    while True:
        snapshot = client.get(f"/api/v1/jobs/{job_id}").json()
        line = f"  [{snapshot['progress']:>3}%] {snapshot.get('current_stage') or ''}"
        if line != last:
            print(line, flush=True)
            last = line
        if snapshot["status"] in TERMINAL:
            return snapshot
        time.sleep(3)


def capture(
    client: httpx.Client, source: Path, name: str, options: dict[str, Any]
) -> int:
    print(f"\n=== {name} — {source.name} ({source.stat().st_size / 1e6:.1f} MB) ===")

    document_id = _upload(client, source)
    snapshot = _run(client, document_id, options)

    if snapshot["status"] == "failed":
        error = snapshot.get("error") or {}
        print(
            f"  FAILED: {error.get('type')}: {str(error.get('message'))[:300]}",
            file=sys.stderr,
        )
        return 1

    package_id = snapshot["package_id"]
    directory = OUT / name
    directory.mkdir(parents=True, exist_ok=True)

    package = client.get(f"/api/v1/packages/{package_id}").json()
    (directory / "teacher_knowledge_package.json").write_text(
        json.dumps(package, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for artifact in client.get(f"/api/v1/packages/{package_id}/artifacts").json()[
        "artifacts"
    ]:
        filename = FILENAMES.get(artifact["kind"])
        if filename is None or artifact["status"] != "ready":
            continue
        blob = client.get(f"/api/v1/packages/{package_id}/artifacts/{artifact['kind']}")
        (directory / filename).write_bytes(blob.content)

    # The source document, so anyone can reproduce this exact run.
    (directory / f"source{source.suffix}").write_bytes(source.read_bytes())

    # Scored server-side, where the run's chunks are still reachable — see the
    # module docstring. persist=false: capturing a sample is not a new data
    # point in the quality trend line.
    evaluation = client.get(f"/api/v1/packages/{package_id}/evaluation?persist=false")
    if evaluation.status_code == 200:
        report = evaluation.json()
        (directory / "eval-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary = report.get("summary") or {}
        stage_score = summary.get("stage_score")
        print(
            f"  eval: stage {stage_score if stage_score is None else f'{stage_score:.1f}'}"
            f" · rubric {summary.get('rubric_score')}"
            f" · {len(report.get('not_measurable') or [])} not measurable"
        )

    pdf = client.get(f"/api/v1/packages/{package_id}/evaluation.pdf")
    if pdf.status_code == 200:
        (directory / "eval-report.pdf").write_bytes(pdf.content)

    classification = package.get("classification") or {}
    validation = package.get("validation") or {}
    print(
        f"  {classification.get('subject')} / {classification.get('topic')} "
        f"· profile {classification.get('pedagogy_profile')} "
        f"· validation {validation.get('status')} "
        f"· status {snapshot['status']}"
    )
    print(f"  wrote {directory.relative_to(ROOT)}/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", type=Path, help="Document to run through the pipeline."
    )
    parser.add_argument("--name", required=True, help="Directory name under samples/.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--period-minutes", type=int, default=None)
    parser.add_argument("--board", default=None)
    parser.add_argument(
        "--document-kind", default=None, help="FAQ Q7 parse-routing hint."
    )
    parser.add_argument(
        "--language",
        default=None,
        help="BCP-47 output language, e.g. 'hi'. The source document stays as it is.",
    )
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"no such file: {args.source}", file=sys.stderr)
        return 2

    options: dict[str, Any] = {}
    if args.period_minutes:
        options["period_duration_minutes"] = args.period_minutes
    if args.board:
        options["curriculum_board"] = args.board
    if args.document_kind:
        options["document_kind"] = args.document_kind
    if args.language:
        options["output_language"] = args.language

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        try:
            client.get("/healthz").raise_for_status()
        except httpx.HTTPError:
            print(
                f"no server at {args.base_url} — start one with `make dev`",
                file=sys.stderr,
            )
            return 2
        return capture(client, args.source, args.name, options)


if __name__ == "__main__":
    raise SystemExit(main())
