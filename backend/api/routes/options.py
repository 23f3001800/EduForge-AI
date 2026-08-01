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

from fastapi import APIRouter

from contracts.jobs import ArtifactKind, DocumentKind, TeachingStyle
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
