"""Seed a store with packages, for tests that need one to already exist.

Tests used to call ``api.samples.seed_samples``, which reads ``samples/*/`` off
disk. That coupled the suite to the contents of a directory whose whole purpose
is to hold **output of real pipeline runs** — so regenerating the samples, or
deleting them because they turned out to be hand-built, broke ten tests that
have nothing to do with samples.

The dependency was also backwards. ``samples/`` is a demonstration for a human
reading the repository; it is not a fixture. A test that needs "a package in the
store" should say so and build one, which is what this does.

``seed_samples`` itself is still covered — by the tests that are actually about
sample loading, pointed at a temporary directory they control.
"""

from __future__ import annotations

from uuid import UUID, uuid5

from contracts.primitives import SCHEMA_VERSION
from core.storage.base import PackageRecord, Store
from tests.fixtures import factories as fx

__all__ = ["seed_packages"]

#: Fixed so a package id is stable across runs and a test can hard-code one.
_NAMESPACE = UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


def _record(name: str, tkp: dict) -> PackageRecord:
    package_id = uuid5(_NAMESPACE, name)
    return PackageRecord(
        id=package_id,
        # No job and no upload sit behind a seeded package. Reusing the id for
        # all three keeps the record self-consistent without inventing a job
        # that never ran — the same choice api.samples makes.
        job_id=package_id,
        document_id=package_id,
        schema_version=str(tkp.get("schema_version") or SCHEMA_VERSION),
        tkp=tkp,
        status=str((tkp.get("validation") or {}).get("status") or "pass"),
        artifacts={kind: f"artifact://seeded/{name}/{kind}" for kind in _ARTIFACT_KINDS},
        is_sample=True,
    )


#: Rendered for real rather than stubbed, so a test that downloads one is
#: exercising the actual renderer and the actual blob round trip. Stubbing the
#: bytes would let a broken renderer pass the download test.
_ARTIFACT_KINDS = ("lesson_plan_pdf", "teacher_guide_pdf", "assessment_book_pdf", "markdown_bundle")


async def _store_artifacts(store: Store, record: PackageRecord) -> None:
    from contracts import TeacherKnowledgePackage
    from stages.s10_publishing.render import RENDERERS

    tkp = TeacherKnowledgePackage.model_validate(record.tkp)
    for kind, uri in record.artifacts.items():
        render = RENDERERS.get(kind)
        if render is None:  # pragma: no cover - the kind list is ours
            continue
        data = render(tkp)
        await store.put_blob(uri, data if isinstance(data, bytes) else data.encode("utf-8"))


async def seed_packages(store: Store) -> list[PackageRecord]:
    """Put two packages in ``store``: one quantitative, one narrative.

    Two rather than one, and of different profiles, because several callers
    assert that profile-conditioned behaviour differs between them — a single
    package would let a bug that ignores the profile pass unnoticed.
    """
    quantitative = fx.teacher_knowledge_package().model_dump(mode="json")

    narrative = fx.teacher_knowledge_package().model_dump(mode="json")
    narrative["classification"] = fx.narrative_classification().model_dump(mode="json")

    records = [
        _record("quantitative", quantitative),
        _record("narrative", narrative),
    ]
    for record in records:
        await store.save_package(record)
        await _store_artifacts(store, record)
    return records
