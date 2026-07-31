"""Application settings.

Fails fast at boot with a message naming the missing key. A service that starts
successfully and then dies on the first upload because a key was absent is worse
than one that refuses to start — the second tells you what is wrong immediately.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

LLMProfile = Literal["production", "dev", "ci"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── LLM provider selection ──────────────────────────────────────────────
    llm_profile: LLMProfile = "production"
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    gemini_api_key: str | None = None

    # Anthropic is implemented but off by default. A key being present in the
    # environment must not be enough to bill against it — enabling the provider
    # is a deliberate act, not a side effect of a config typo.
    anthropic_api_key: str | None = None
    allow_anthropic: bool = False
    models_config_path: Path = REPO_ROOT / "config" / "models.yaml"

    # ── storage ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://eduforge:eduforge@localhost:5432/eduforge"
    blob_backend: Literal["local", "s3"] = "local"
    blob_local_path: Path = REPO_ROOT / "blob"

    # ── retrieval ───────────────────────────────────────────────────────────
    embeddings: Literal["none", "local", "api"] = "none"

    # ── limits & safety ─────────────────────────────────────────────────────
    max_upload_mb: int = Field(default=25, ge=1)
    max_pages: int = Field(default=300, ge=1)
    parse_timeout_s: int = Field(default=90, ge=1)
    llm_concurrency: int = Field(default=4, ge=1)
    job_token_budget: int = Field(default=1_500_000, ge=1)
    retention_days: int = Field(default=30, ge=1)
    demo_access_code: str | None = None

    app_version: str = "0.1.0"

    @model_validator(mode="after")
    def _required_key_for_profile(self) -> Settings:
        """Each profile has exactly one credential it cannot run without.

        `ci` needs none by design — the replay provider serves recorded cassettes,
        so CI never depends on a network or a key.
        """
        required = {"production": "GROQ_API_KEY", "dev": "GEMINI_API_KEY"}.get(
            self.llm_profile
        )
        if required is None:
            return self
        value = self.groq_api_key if self.llm_profile == "production" else self.gemini_api_key
        if not value:
            raise ValueError(
                f"LLM_PROFILE={self.llm_profile!r} requires {required} to be set. "
                f"Set it in .env, or use LLM_PROFILE=ci to run against recorded "
                f"cassettes with no key."
            )
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
