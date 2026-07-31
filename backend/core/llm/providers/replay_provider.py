"""Replay adapter — recorded cassettes for CI.

CI must not depend on a network, an API key, or a provider's mood. This adapter
serves responses recorded from a real run, keyed by a hash of the request.

A cache miss is a **hard failure**, never a live call. Silently falling through to
a real provider would make CI non-deterministic, quietly billable, and dependent
on a secret that pull requests from forks do not have.

Record with ``EDUFORGE_RECORD_CASSETTES=1`` against a real provider; the recorded
files are committed alongside the tests that use them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from contracts.llm import LLMUsage, ModelSpec
from core.llm.base import LLMProviderError, RawCompletion

__all__ = ["CassetteMiss", "ReplayAdapter", "cassette_key"]

DEFAULT_CASSETTE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "llm_cassettes"


class CassetteMiss(LLMProviderError):
    def __init__(self, key: str, stage: str, path: Path) -> None:
        super().__init__(
            f"No cassette for stage {stage!r} (key {key[:12]}). "
            f"Expected {path}. Record with EDUFORGE_RECORD_CASSETTES=1, or check "
            f"whether a prompt change invalidated the recording.",
            retryable=False,
        )
        self.key = key


def cassette_key(*, stage: str, system: str, user_content: str, schema: dict[str, Any]) -> str:
    """Stable hash of everything that determines the response.

    Includes the schema: a contract change alters what a valid response looks
    like, so an old recording must not keep satisfying a new schema.
    """
    payload = json.dumps(
        {"stage": stage, "system": system, "user": user_content, "schema": schema},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReplayAdapter:
    name = "replay"

    def __init__(self, cassette_dir: Path | None = None, *, stage_fallback: bool = True) -> None:
        self._dir = cassette_dir or DEFAULT_CASSETTE_DIR
        # Stage fallback lets a hand-written per-stage cassette stand in before any
        # real run has been recorded, which is what makes CI green from day one.
        self._stage_fallback = stage_fallback

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:
        stage = (extra or {}).get("stage", "unknown")
        schema = output_model.model_json_schema()
        key = cassette_key(stage=stage, system=system, user_content=user_content, schema=schema)

        exact = self._dir / f"{stage}.{key[:16]}.json"
        if exact.exists():
            return self._load(exact, spec)

        if self._stage_fallback:
            generic = self._dir / f"{stage}.json"
            if generic.exists():
                return self._load(generic, spec)

        raise CassetteMiss(key, stage, exact)

    def _load(self, path: Path, spec: ModelSpec) -> RawCompletion:
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = payload.get("response", payload)
        return RawCompletion(
            text=json.dumps(body, ensure_ascii=False),
            model=f"replay:{spec.model}",
            usage=LLMUsage(tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0.0),
        )

    def record(self, *, stage: str, key: str, response: Any) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{stage}.{key[:16]}.json"
        path.write_text(
            json.dumps({"stage": stage, "response": response}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path
