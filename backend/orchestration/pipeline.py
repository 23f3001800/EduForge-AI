"""Assembling the stage roster for one job.

This is the only module that knows the pipeline's composition, and it is
deliberately the *only* one: the graph builds itself from
whatever list it is handed, the worker runs whatever the graph compiled, and the
API asks for a roster without knowing what is in it. Replacing a stub is an edit
here and nowhere else.

It lives in ``orchestration`` rather than in ``stages`` because it is the one
place allowed to see every stage at once. A module inside ``stages`` that
imported all ten would be a stage importing other stages, which is exactly what
the independence rule forbids — and the rule is worth more than the convenience.

Stage 1 is constructed per job because it closes over that job's document bytes.
Stages 2-9 close over the LLM client. Stage 10 makes no model calls at all —
it assembles and renders what the other nine produced.
"""

from __future__ import annotations

from typing import Any

from core.config import Settings
from core.llm.client import LLMClient
from core.llm.factory import build_llm_client
from core.storage.base import JobRecord, Store
from stages.s1_document_intelligence.stage import DocumentIntelligenceStage
from stages.s2_classification.stage import ClassificationStage
from stages.s3_knowledge.stage import KnowledgeExtractionStage
from stages.s4_planner.stage import TeachingPlannerStage
from stages.s5_classroom_content.stage import ClassroomContentStage
from stages.s6_activities.stage import ActivityGenerationStage
from stages.s7_assessments.stage import AssessmentGenerationStage
from stages.s8_gaps.stage import GapAnalysisStage
from stages.s9_validation.stage import ValidationStage
from stages.s10_publishing.stage import PublishingStage

__all__ = ["REMAINING_STUBS", "build_stages", "roster_for_job"]

#: Stages still served by fixtures. Now empty: every stage is real. The name and
#: the roster test that reads it stay, because an empty list is the assertion —
#: a stub reintroduced during a refactor has to be declared here to pass.
REMAINING_STUBS: tuple[str, ...] = ()


def build_stages(
    *,
    llm: LLMClient,
    payload: bytes,
    filename: str,
    mime: str,
    max_bytes: int,
    max_pages: int,
    parse_timeout_s: float,
) -> list[Any]:
    """The ordered roster for one job: all ten stages, real.

    Order comes from this list alone — ``build_graph`` chains it pairwise — so a
    stage inserted here is a stage in the pipeline, with no second place to
    update and no way for the two to disagree.
    """
    return [
        DocumentIntelligenceStage(
            payload=payload,
            filename=filename,
            mime=mime,
            max_bytes=max_bytes,
            max_pages=max_pages,
            timeout_s=parse_timeout_s,
        ),
        ClassificationStage(llm),
        KnowledgeExtractionStage(llm),
        TeachingPlannerStage(llm),
        ClassroomContentStage(llm),
        ActivityGenerationStage(llm),
        AssessmentGenerationStage(llm),
        GapAnalysisStage(llm),
        ValidationStage(llm),
        PublishingStage(),
    ]


async def roster_for_job(store: Store, job: JobRecord, settings: Settings) -> list[Any]:
    """The production roster for one job, with its document bound into stage 1.

    Built at spawn time rather than at import time because stage 1 closes over
    the document's bytes. Reading them back from the store rather than carrying
    them from the upload request is what lets a retry re-run the parse without
    the teacher uploading the file a second time.
    """
    document = await store.get_document(job.document_id)
    if document is None:
        raise LookupError(f"document {job.document_id} not found")
    payload = await store.get_blob(document.blob_uri)
    if payload is None:
        raise LookupError(f"no stored bytes for document {job.document_id}")

    return build_stages(
        llm=build_llm_client(settings),
        payload=payload,
        filename=document.filename,
        mime=document.mime,
        max_bytes=settings.max_upload_bytes,
        max_pages=settings.max_pages,
        parse_timeout_s=float(settings.parse_timeout_s),
    )
