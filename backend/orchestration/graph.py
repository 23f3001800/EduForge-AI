"""The LangGraph pipeline.

Nodes are stages; edges are the pipeline order. Building the topology from a list
of stages rather than hand-wiring ten `add_edge` calls means a stage cannot be
added to the roster and forgotten in the graph — the two cannot drift.

Checkpointing is ours rather than LangGraph's built-in saver. There is exactly one
source of truth for "what has this job completed": the ``stage_outputs`` store.
Two checkpoint systems that can disagree is a debugging problem nobody wants at
minute nine of a twelve-minute run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from itertools import pairwise
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from contracts.primitives import StageName
from core.obs import metrics
from core.obs.context import bind
from core.obs.logging import get_logger
from core.storage.base import StageOutput, Store
from orchestration.state import GraphState
from stages.base import StageContext

__all__ = ["PipelineResult", "build_graph", "run_pipeline"]

EmitFn = Callable[..., Awaitable[None]]

logger = get_logger("orchestration.graph")


class PipelineResult:
    def __init__(self, state: dict[str, Any], executed: list[str], skipped: list[str]) -> None:
        self.state = state
        self.executed = executed
        self.skipped = skipped

    @property
    def package(self) -> dict[str, Any] | None:
        return self.state.get("package")


def build_graph(stages: list[Any], node_factory: Callable[[Any], Any]) -> Any:
    """Compile a linear graph over ``stages``.

    ``node_factory`` wraps each stage with checkpointing and progress so the graph
    itself stays a pure description of order.
    """
    graph: StateGraph = StateGraph(GraphState)

    for stage in stages:
        graph.add_node(stage.name, node_factory(stage))

    graph.add_edge(START, stages[0].name)
    for current, following in pairwise(stages):
        graph.add_edge(current.name, following.name)
    graph.add_edge(stages[-1].name, END)

    return graph.compile()


def _make_node(
    stage: Any,
    *,
    job_id: UUID,
    store: Store,
    emit: EmitFn,
    options: dict[str, Any],
    completed: dict[str, StageOutput],
    executed: list[str],
    skipped: list[str],
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        # Resume: a completed stage is restored, never re-executed or re-billed.
        checkpoint = completed.get(stage.name)
        if checkpoint is not None:
            skipped.append(stage.name)
            await emit(
                stage=stage.name,
                progress=_progress_for(stage.name),
                message="restored from checkpoint",
            )
            # The WHOLE fragment, not just STAGE_STATE_KEY[stage.name]. Most
            # stages write one key and the difference is invisible, but stage 1
            # writes `structured_document` AND `chunks`; restoring only the
            # mapped key silently drops the chunks, and stage 3 then verifies
            # citations against nothing. STAGE_STATE_KEY names the key a stage
            # *owns* for invalidation — it was never the full list of what a
            # stage writes.
            return dict(checkpoint.output)

        async def put_artifact(kind: str, payload: bytes) -> str:
            """Persist one rendered artifact and return its uri.

            Keyed by job and kind rather than by content hash: re-running
            publishing after a regeneration must *replace* the old lesson plan,
            not accumulate a second one nothing points at.
            """
            uri = f"artifact://{job_id}/{kind}"
            await store.put_blob(uri, payload)
            return uri

        ctx = StageContext(job_id=job_id, options=options, emit=emit, put_artifact=put_artifact)
        # Every log line and metric emitted anywhere inside this stage — including
        # from the LLM client several frames down — carries the job and stage
        # without either being threaded through a signature.
        with bind(job_id=str(job_id), stage=stage.name), metrics.observe_stage(stage.name):
            fragment = await stage.run(ctx, state)
        executed.append(stage.name)
        logger.info("stage completed", extra={"keys": sorted(fragment)})

        await store.put_checkpoint(StageOutput(job_id=job_id, stage=stage.name, output=fragment))
        return fragment

    return node


def _progress_for(stage: StageName) -> int:
    from stages.base import cumulative_progress

    return cumulative_progress(stage, 1.0)


async def run_pipeline(
    *,
    job_id: UUID,
    document_id: UUID,
    options: dict[str, Any],
    stages: list[Any],
    store: Store,
    emit: EmitFn,
) -> PipelineResult:
    """Execute the pipeline for one job, resuming from any existing checkpoints."""
    completed = await store.get_checkpoints(job_id)
    executed: list[str] = []
    skipped: list[str] = []

    compiled = build_graph(
        stages,
        lambda stage: _make_node(
            stage,
            job_id=job_id,
            store=store,
            emit=emit,
            options=options,
            completed=completed,
            executed=executed,
            skipped=skipped,
        ),
    )

    initial: dict[str, Any] = {
        "job_id": str(job_id),
        "document_id": str(document_id),
        "options": options,
        "warnings": [],
    }
    final = await compiled.ainvoke(initial)
    return PipelineResult(dict(final), executed, skipped)
