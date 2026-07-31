"""In-memory :class:`Store` — the reference implementation.

Used by tests, by local development, and by the walking skeleton. It is not a
toy: it implements the same lease-based claiming and monotonic event sequencing
as the Postgres backend, so behaviour that passes here is behaviour the real
backend must reproduce. Where it differs (no cross-process durability), the
difference is documented rather than papered over.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from contracts.primitives import StageName
from core.storage.base import (
    DocumentRecord,
    JobEvent,
    JobRecord,
    PackageRecord,
    StageOutput,
    Store,
)

__all__ = ["InMemoryStore"]


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._documents: dict[UUID, DocumentRecord] = {}
        self._by_sha: dict[str, UUID] = {}
        self._jobs: dict[UUID, JobRecord] = {}
        self._by_idem: dict[str, UUID] = {}
        self._events: dict[UUID, list[JobEvent]] = {}
        self._checkpoints: dict[UUID, dict[str, StageOutput]] = {}
        self._packages: dict[UUID, PackageRecord] = {}
        self._blobs: dict[str, bytes] = {}
        self._seq = 0
        self._lock = asyncio.Lock()
        # One condition per job; SSE readers wait on it instead of polling.
        self._waiters: dict[UUID, asyncio.Condition] = {}

    def _condition(self, job_id: UUID) -> asyncio.Condition:
        if job_id not in self._waiters:
            self._waiters[job_id] = asyncio.Condition()
        return self._waiters[job_id]

    # ── documents ───────────────────────────────────────────────────────────

    async def add_document(self, record: DocumentRecord) -> DocumentRecord:
        async with self._lock:
            existing_id = self._by_sha.get(record.sha256)
            if existing_id is not None:
                return self._documents[existing_id]
            self._documents[record.id] = record
            self._by_sha[record.sha256] = record.id
            return record

    async def get_document(self, document_id: UUID) -> DocumentRecord | None:
        return self._documents.get(document_id)

    # ── blobs ───────────────────────────────────────────────────────────────

    async def put_blob(self, uri: str, payload: bytes) -> None:
        # Keyed by uri, which is content-addressed upstream, so a re-upload of an
        # identical file overwrites with identical bytes.
        self._blobs[uri] = payload

    async def get_blob(self, uri: str) -> bytes | None:
        return self._blobs.get(uri)

    # ── jobs ────────────────────────────────────────────────────────────────

    async def create_job(self, record: JobRecord) -> JobRecord:
        async with self._lock:
            if record.idempotency_key:
                existing_id = self._by_idem.get(record.idempotency_key)
                if existing_id is not None:
                    return self._jobs[existing_id]
                self._by_idem[record.idempotency_key] = record.id
            self._jobs[record.id] = record
            self._events.setdefault(record.id, [])
            return record

    async def get_job(self, job_id: UUID) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def update_job(self, job: JobRecord) -> JobRecord:
        self._jobs[job.id] = job
        return job

    async def claim_job(self, worker_id: str, lease_seconds: int = 300) -> JobRecord | None:
        now = datetime.now(UTC)
        async with self._lock:
            claimable = [
                j
                for j in self._jobs.values()
                if j.status == "queued"
                or (j.status == "running" and j.lease_until is not None and j.lease_until < now)
            ]
            if not claimable:
                return None
            job = min(claimable, key=lambda j: j.created_at)
            job.status = "running"
            job.worker_id = worker_id
            job.lease_until = now + timedelta(seconds=lease_seconds)
            job.started_at = job.started_at or now
            return job

    # ── progress events ─────────────────────────────────────────────────────

    async def append_event(self, event: JobEvent) -> JobEvent:
        condition = self._condition(event.job_id)
        async with condition:
            async with self._lock:
                self._seq += 1
                event.seq = self._seq
                self._events.setdefault(event.job_id, []).append(event)
            condition.notify_all()
        return event

    async def events_since(self, job_id: UUID, after_seq: int = 0) -> list[JobEvent]:
        return [e for e in self._events.get(job_id, []) if e.seq > after_seq]

    async def wait_for_events(self, job_id: UUID, after_seq: int, timeout: float) -> None:
        condition = self._condition(job_id)
        try:
            async with condition:
                await asyncio.wait_for(
                    condition.wait_for(
                        lambda: any(e.seq > after_seq for e in self._events.get(job_id, []))
                    ),
                    timeout=timeout,
                )
        except TimeoutError:
            return  # caller emits a heartbeat and loops

    # ── checkpoints ─────────────────────────────────────────────────────────

    async def put_checkpoint(self, checkpoint: StageOutput) -> StageOutput:
        self._checkpoints.setdefault(checkpoint.job_id, {})[checkpoint.stage] = checkpoint
        return checkpoint

    async def get_checkpoints(self, job_id: UUID) -> dict[str, StageOutput]:
        return dict(self._checkpoints.get(job_id, {}))

    async def clear_checkpoints(self, job_id: UUID, stages: list[StageName]) -> None:
        stored = self._checkpoints.get(job_id, {})
        for stage in stages:
            stored.pop(stage, None)

    # ── packages ────────────────────────────────────────────────────────────

    async def save_package(self, record: PackageRecord) -> PackageRecord:
        self._packages[record.id] = record
        return record

    async def get_package(self, package_id: UUID) -> PackageRecord | None:
        return self._packages.get(package_id)

    async def list_samples(self) -> list[PackageRecord]:
        return [p for p in self._packages.values() if p.is_sample]
