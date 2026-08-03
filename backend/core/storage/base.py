"""Storage records and the store interface.

The interface is the real M1 contract; the in-memory implementation in
``memory.py`` exists so the pipeline, the worker, and the API can be built and
tested without Postgres. The SQLAlchemy implementation lands behind this same
interface, and every caller stays unchanged.

That split is not just convenience. It means CI never needs a database to prove
that the graph runs, progress streams, and checkpoints resume — which keeps the
feedback loop in seconds rather than minutes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts.jobs import JobStatus
from contracts.primitives import StageName

__all__ = [
    "DocumentRecord",
    "JobEvent",
    "JobRecord",
    "PackageRecord",
    "StageOutput",
    "Store",
]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class DocumentRecord:
    id: UUID
    sha256: str
    filename: str
    mime: str
    size_bytes: int
    blob_uri: str
    page_count: int | None = None
    word_count: int | None = None
    detected_language: str | None = None
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class JobRecord:
    id: UUID
    document_id: UUID
    status: JobStatus = "queued"
    current_stage: StageName | None = None
    progress: int = 0
    options: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    package_id: UUID | None = None
    worker_id: str | None = None
    lease_until: datetime | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(slots=True)
class JobEvent:
    """One progress frame. ``seq`` is the SSE event id — monotonic per store."""

    seq: int
    job_id: UUID
    stage: str
    progress: int
    level: str = "info"
    message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class StageOutput:
    """A stage checkpoint. Its existence is what makes a stage skippable on resume."""

    job_id: UUID
    stage: StageName
    output: dict[str, Any]
    attempt: int = 1
    duration_ms: int = 0
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class PackageRecord:
    id: UUID
    job_id: UUID
    document_id: UUID
    schema_version: str
    tkp: dict[str, Any]
    status: str
    #: Artifact kind -> blob uri, as written by stage 10. Kept on the record
    #: rather than inside the TKP because it is storage detail, not curriculum
    #: content: the same package re-rendered to a different backend is the same
    #: package.
    artifacts: dict[str, str] = field(default_factory=dict)
    is_sample: bool = False
    created_at: datetime = field(default_factory=_now)


class Store(ABC):
    """Persistence port. One implementation per backend; callers never branch."""

    # ── documents ───────────────────────────────────────────────────────────
    @abstractmethod
    async def add_document(self, record: DocumentRecord) -> DocumentRecord:
        """Insert, or return the existing record when the sha256 already exists."""

    @abstractmethod
    async def get_document(self, document_id: UUID) -> DocumentRecord | None: ...

    # ── blobs ───────────────────────────────────────────────────────────────
    # The uploaded bytes, kept separately from the metadata record. Stage 1 reads
    # them at job time rather than at upload time: the job outlives the request
    # that created it (H-01), so the payload cannot be held in the request scope,
    # and re-running a failed job must not require the teacher to upload again.
    @abstractmethod
    async def put_blob(self, uri: str, payload: bytes) -> None:
        """Store bytes under ``DocumentRecord.blob_uri``. Idempotent by uri."""

    @abstractmethod
    async def get_blob(self, uri: str) -> bytes | None: ...

    # ── jobs ────────────────────────────────────────────────────────────────
    @abstractmethod
    async def create_job(self, record: JobRecord) -> JobRecord:
        """Insert, or return the existing job when the idempotency key was seen."""

    @abstractmethod
    async def get_job(self, job_id: UUID) -> JobRecord | None: ...

    @abstractmethod
    async def update_job(self, job: JobRecord) -> JobRecord: ...

    @abstractmethod
    async def claim_job(self, worker_id: str, lease_seconds: int = 300) -> JobRecord | None:
        """Atomically claim the oldest claimable job.

        Claimable means queued, or running with an expired lease — the latter is
        how a crashed worker's job is recovered without an external supervisor.
        """

    # ── progress events ─────────────────────────────────────────────────────
    @abstractmethod
    async def append_event(self, event: JobEvent) -> JobEvent:
        """Persist first. A dropped notification costs latency, never correctness."""

    @abstractmethod
    async def events_since(self, job_id: UUID, after_seq: int = 0) -> list[JobEvent]: ...

    @abstractmethod
    async def wait_for_events(self, job_id: UUID, after_seq: int, timeout: float) -> None:
        """Block until an event past ``after_seq`` exists, or the timeout elapses."""

    # ── checkpoints ─────────────────────────────────────────────────────────
    @abstractmethod
    async def put_checkpoint(self, checkpoint: StageOutput) -> StageOutput: ...

    @abstractmethod
    async def get_checkpoints(self, job_id: UUID) -> dict[str, StageOutput]: ...

    @abstractmethod
    async def clear_checkpoints(self, job_id: UUID, stages: list[StageName]) -> None:
        """Invalidate specific stages so targeted regeneration re-runs only those."""

    # ── packages ────────────────────────────────────────────────────────────
    @abstractmethod
    async def save_package(self, record: PackageRecord) -> PackageRecord: ...

    @abstractmethod
    async def get_package(self, package_id: UUID) -> PackageRecord | None: ...

    @abstractmethod
    async def delete_package(self, package_id: UUID) -> bool:
        """Remove a package. Returns whether one was there to remove.

        Implementations must refuse to delete a sample: the seeded packages are
        the instance's shared reference set, and one visitor clearing them would
        empty the demonstration for everyone who arrives afterwards.
        """

    @abstractmethod
    async def list_samples(self) -> list[PackageRecord]: ...

    @abstractmethod
    async def list_packages(self) -> list[PackageRecord]:
        """Every package, samples included. Read-only, for stats views."""
