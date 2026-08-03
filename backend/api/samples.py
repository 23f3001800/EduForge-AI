"""Seeding the reference packages at startup.

``samples/`` holds two complete packages — one quantitative, one narrative —
built from the repository fixtures by ``scripts/build_samples.py``. Loading them
into the store when the app boots means an evaluator can open a finished Teacher
Knowledge Package on the first click, before uploading anything.

That matters more than it sounds. A full run takes five to seven minutes and the
free model tier allows fifty requests a day, so "upload something and wait" is a
poor first impression and a rationed one. The samples cost nothing, are identical
on every deploy, and demonstrate the claim the whole system rests on: the same
pipeline yields numerical questions for physics and none for history.

Seeding is best-effort. A missing or malformed samples directory must not stop
the API from serving — the samples are a demonstration, not a dependency.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from contracts.primitives import SCHEMA_VERSION
from core.config import REPO_ROOT
from core.storage.base import PackageRecord, Store

__all__ = ["SAMPLES_DIR", "seed_samples"]

SAMPLES_DIR = REPO_ROOT / "samples"

logger = logging.getLogger(__name__)


def _stable_id(name: str) -> UUID:
    """A deterministic id per sample directory.

    Deterministic so a redeploy does not invalidate a URL someone bookmarked or
    pasted into a report. A random uuid per boot would mean every restart breaks
    every link to a sample.
    """
    return uuid5(NAMESPACE_URL, f"eduforge:sample:{name}")


async def seed_samples(store: Store, directory: Path = SAMPLES_DIR) -> int:
    """Load ``samples/*/teacher_knowledge_package.json`` into ``store``.

    Returns how many were loaded. Never raises: a broken sample is logged and
    skipped, because the API serving is worth more than the demonstration.
    """
    if not directory.is_dir():
        logger.info("no samples directory at %s; skipping seed", directory)
        return 0

    loaded = 0
    for path in sorted(directory.glob("*/teacher_knowledge_package.json")):
        name = path.parent.name
        try:
            tkp = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("sample %s could not be read; skipping", name, exc_info=True)
            continue

        package_id = _stable_id(name)
        record = PackageRecord(
            id=package_id,
            # Samples have no job and no upload behind them. Reusing the package
            # id for both keeps the record self-consistent without inventing a
            # job that never ran.
            job_id=package_id,
            document_id=package_id,
            schema_version=str(tkp.get("schema_version") or SCHEMA_VERSION),
            tkp=tkp,
            status=str((tkp.get("validation") or {}).get("status") or "pass"),
            artifacts=_artifact_uris(path.parent),
            is_sample=True,
        )
        await store.save_package(record)
        for kind, uri in record.artifacts.items():
            await store.put_blob(uri, (path.parent / _FILENAMES[kind]).read_bytes())
        loaded += 1

    logger.info("seeded %d sample package(s) from %s", loaded, directory)
    return loaded


async def score_samples(store: Store) -> int:
    """Score every seeded sample into the evaluation history.

    Without this the cross-run dashboard opens empty on a fresh instance, under
    a heading promising a distribution and a series — which is the worst version
    of a feature to show an evaluator, since it explains what it would do rather
    than doing it. Three packages is not a benchmark, and the dashboard says so
    itself via ``sufficient``, but it is a series that renders.

    Affordable because scoring is deterministic and calls no model: it walks the
    package and recomputes metrics. The samples carry no stage-1 checkpoint, so
    citation integrity reports itself unmeasurable here — correct, and visible
    in the report rather than papered over.

    Best-effort like the seeding above. Scoring is a convenience; failing it
    must not stop the API from serving — so the import sits inside the guard
    too. It did not, and an ImportError in this function took the whole
    application down on startup, which is precisely the failure the guard was
    written to prevent.
    """
    scored = 0
    try:
        from api.routes.evaluations import evaluate_sample, get_history

        history = get_history()
    except Exception:  # pragma: no cover - see docstring
        logger.warning("evaluation history unavailable; samples not scored", exc_info=True)
        return 0

    for record in await store.list_samples():
        try:
            await evaluate_sample(record, history)
        except Exception:  # pragma: no cover - see docstring
            logger.warning("could not score sample %s; skipping", record.id, exc_info=True)
            continue
        scored += 1

    logger.info("scored %d seeded sample(s) into the evaluation history", scored)
    return scored


#: Rendered artifacts as ``scripts/build_samples.py`` names them on disk.
_FILENAMES = {
    "lesson_plan_pdf": "lesson_plan.pdf",
    "teacher_guide_pdf": "teacher_guide.pdf",
    "assessment_book_pdf": "assessment_book.pdf",
    "markdown_bundle": "markdown.md",
}


def _artifact_uris(directory: Path) -> dict[str, str]:
    """Only the artifacts that actually exist on disk get advertised."""
    return {
        kind: f"artifact://sample/{directory.name}/{kind}"
        for kind, filename in _FILENAMES.items()
        if (directory / filename).is_file()
    }
