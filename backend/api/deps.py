"""Shared API dependencies.

The store is a module-level singleton for the skeleton. When the Postgres backend
lands it becomes a connection-pool-backed instance created at startup — the
dependency signature does not change, so no route is rewritten.
"""

from __future__ import annotations

from core.config import Settings, get_settings
from core.storage.base import Store
from core.storage.memory import InMemoryStore

__all__ = ["get_app_settings", "get_store", "set_store"]

_store: Store = InMemoryStore()


def get_store() -> Store:
    return _store


def set_store(store: Store) -> None:
    """Swap the backing store. Used by tests and by startup wiring."""
    global _store
    _store = store


def get_app_settings() -> Settings:
    return get_settings()
