"""Stage 10 — Publishing.

Assembles the Teacher Knowledge Package from everything the previous nine
stages wrote to graph state (FR-11), then renders it into the artifacts a
teacher actually opens: a Lesson Plan PDF, a Teacher Guide PDF, an Assessment
Book PDF with the answer key as its own section, and a Markdown bundle.

This stage makes no model calls and reaches no network — everything it needs
already exists in ``state``. That is also why it cannot repair anything: if an
earlier stage's output does not cross-reference cleanly,
``TeacherKnowledgePackage`` refuses to construct (docs/00 § H-06) and this
stage fails loudly rather than publish something broken.

``ctx.options["include_artifacts"]`` decides what gets rendered. A caller who
only wants the JSON should not pay for three PDF layouts they will not open —
this is the one place in the pipeline where "asked for" and "produced" are
allowed to differ, everywhere else a stage produces everything it can.
"""

from __future__ import annotations

from typing import Any

from contracts.jobs import ArtifactKind, JobOptions
from stages.base import StageContext, stage_span
from stages.s10_publishing.assemble import assemble_package
from stages.s10_publishing.render import RENDERERS

__all__ = ["PublishingStage"]

#: What a caller gets when `ctx.options` says nothing at all — mirrors
#: `JobOptions.include_artifacts`'s own default rather than redeclaring a
#: separate list that could drift from it.
_DEFAULT_ARTIFACTS: tuple[ArtifactKind, ...] = tuple(
    JobOptions.model_fields["include_artifacts"].default_factory()  # type: ignore[misc]
)


def _requested_artifacts(options: dict[str, Any]) -> list[ArtifactKind]:
    requested = options.get("include_artifacts")
    if requested is None:
        return list(_DEFAULT_ARTIFACTS)
    # Preserve the caller's order but drop anything this stage does not know
    # how to render — `ArtifactKind` is a closed Literal, so an unknown value
    # here means options were built by hand rather than through `JobOptions`,
    # and skipping it is safer than crashing a whole run over one bad string.
    return [kind for kind in requested if kind in RENDERERS]


class PublishingStage:
    """Replaces the stage-10 stub."""

    name = "publishing"

    async def run(self, ctx: StageContext, state: dict[str, Any]) -> dict[str, Any]:
        async with stage_span(ctx, self.name) as span:
            tkp = assemble_package(state)

            wanted = _requested_artifacts(ctx.options or {})
            for index, kind in enumerate(wanted):
                await span.progress(index / max(len(wanted), 1), message=f"rendering {kind}")
                rendered = RENDERERS[kind](tkp)
                if not rendered:
                    span.warn(f"{kind}: rendered zero bytes")

            await span.progress(
                0.98, message=f"published {len(wanted)} artifact(s): {', '.join(wanted) or 'none'}"
            )
            return {"package": tkp.model_dump(mode="json")}
