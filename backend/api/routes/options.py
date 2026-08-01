"""What the client may choose, served from the same config the pipeline reads.

The upload form needs a curriculum-board list, a teaching-style list, and the
artifact kinds. Every one of those already exists somewhere authoritative — in
``pedagogy/curricula.yaml`` or in ``contracts.jobs`` — and a UI that hardcodes its
own copy drifts the moment a board is added, offering a choice the backend then
silently falls back to ``generic`` on.

So the options come from the same source the pipeline uses. Adding a board is a
block of YAML, and the dropdown gains it without a frontend change.
"""

from __future__ import annotations

from typing import Any, get_args

from fastapi import APIRouter, Depends

from api.deps import get_store
from contracts.jobs import ArtifactKind, DocumentKind, TeachingStyle
from core.storage.base import Store
from pedagogy.curriculum import load_boards

router = APIRouter(tags=["options"])


@router.get("/options")
async def get_options() -> dict[str, Any]:
    """Everything the job-creation form needs to render itself."""
    boards = load_boards()
    return {
        "curriculum_boards": [
            {
                "value": name,
                "label": profile.label,
                "description": profile.description,
                "period_minutes": profile.period_minutes,
            }
            # `generic` first: it is the right answer for most teachers and must
            # not sit at the bottom of an alphabetical list.
            for name, profile in sorted(boards.items(), key=lambda kv: (kv[0] != "generic", kv[0]))
        ],
        "teaching_styles": list(get_args(TeachingStyle)),
        "document_kinds": list(get_args(DocumentKind)),
        "artifact_kinds": list(get_args(ArtifactKind)),
    }


@router.get("/samples")
async def list_samples(store: Store = Depends(get_store)) -> dict[str, Any]:
    """The reference packages, ready to open without running anything.

    The frontend has called this since it was written; the route did not exist,
    so the physics-vs-history comparison — the clearest demonstration the product
    has — had no live path into the UI at all.

    A summary rather than the packages themselves: this renders a chooser, and
    two full TKPs are hundreds of kilobytes nobody has asked for yet.
    """
    samples = await store.list_samples()
    return {
        "samples": [
            {
                "package_id": str(record.id),
                "title": _title(record.tkp),
                "subject": str(
                    (record.tkp.get("classification") or {}).get("subject") or "Unknown"
                ),
                "pedagogy_profile": str(
                    (record.tkp.get("classification") or {}).get("pedagogy_profile") or "mixed"
                ),
                "periods": int((record.tkp.get("teaching_plan") or {}).get("total_periods") or 0),
                "validation_status": record.status,
            }
            for record in samples
        ]
    }


def _title(tkp: dict[str, Any]) -> str:
    """Whatever the package calls itself, falling back through what exists."""
    classification = tkp.get("classification") or {}
    for key in ("chapter", "topic", "subject"):
        value = classification.get(key)
        if value:
            return str(value)
    return "Sample package"
