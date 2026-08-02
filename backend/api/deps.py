"""Shared API dependencies.

The store is a module-level singleton for the skeleton. When the Postgres backend
lands it becomes a connection-pool-backed instance created at startup — the
dependency signature does not change, so no route is rewritten.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from core.config import Settings, get_settings
from core.storage.base import JobRecord, Store
from core.storage.memory import InMemoryStore
from orchestration.pipeline import Roster, roster_for_job

__all__ = [
    "RosterBuilder",
    "get_app_settings",
    "get_roster_builder",
    "get_store",
    "set_roster_builder",
    "set_store",
]

#: Produces the ordered stage list for one job, plus the LLM client they share —
#: the runner needs the client to attribute tokens and cost per stage.
RosterBuilder = Callable[[Store, JobRecord, Settings], Awaitable[Roster]]

_store: Store = InMemoryStore()

# Injectable for the same reason the store is: the API integration tests prove
# the evaluator path — upload, enqueue, progress, package — and that path must be
# provable without a network, a key, or a real document. Swapping the roster for
# stubs tests the plumbing; swapping the store for Postgres tests persistence.
# Neither should require touching a route.
_roster_builder: RosterBuilder = roster_for_job


def get_store() -> Store:
    return _store


def set_store(store: Store) -> None:
    """Swap the backing store. Used by tests and by startup wiring."""
    global _store
    _store = store


def get_roster_builder() -> RosterBuilder:
    return _roster_builder


def set_roster_builder(builder: RosterBuilder) -> None:
    """Swap how a job's stage list is built. Used by tests and by startup wiring."""
    global _roster_builder
    _roster_builder = builder


def get_app_settings() -> Settings:
    return get_settings()
