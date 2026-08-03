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

LLMProfile = Literal["production", "local", "dev", "ci"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── LLM provider selection ──────────────────────────────────────────────
    llm_profile: LLMProfile = "production"
    open_router_api_key: str | None = None
    open_router_base_url: str = "https://openrouter.ai/api/v1"
    gemini_api_key: str | None = None
    #: Where a local Ollama server listens. No key: it runs on this machine and
    #: has nothing to authenticate against, which is the whole point of the
    #: ``local`` profile — it has no quota and needs no network, so a demo can
    #: never be blocked by someone else's daily limit resetting at midnight UTC.
    ollama_base_url: str = "http://127.0.0.1:11434/v1"

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
    #: Where the evaluation series is kept. ``None`` means in-memory, which a
    #: restart discards — correct for a scratch container, wrong for a deployment
    #: whose trend line is meant to mean something. Point it at a mounted volume
    #: and the same code becomes durable.
    eval_history_path: Path | None = None

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

    # ── ingestion hardening (NFR-09) ────────────────────────────────────────
    #: DOCX and PPTX are ZIP archives, so an upload's size says nothing about
    #: what it expands to. A 2.18 MB DOCX declaring 2.9 GB of members is a
    #: memory-exhaustion attack that every byte-count limit upstream passes.
    #: These three bound the archive itself, before a parser opens it.
    max_archive_uncompressed_mb: int = Field(default=200, ge=1)
    max_archive_ratio: int = Field(default=200, ge=2)
    max_archive_members: int = Field(default=2000, ge=1)

    #: Extraction ceilings, enforced at one choke point for all four parsers.
    #: An NCERT chapter yields ~2.7k blocks and ~98k characters; these sit far
    #: enough above that only an engineered document reaches them.
    max_blocks_per_document: int = Field(default=200_000, ge=1_000)
    max_text_chars: int = Field(default=20_000_000, ge=100_000)

    #: Parsing runs in a child process so ``parse_timeout_s`` can actually end
    #: the work: cancelling a thread is not possible, killing a process is.
    #: Set false to fall back to the in-thread path where a deployment forbids
    #: subprocesses; the timeout then bounds the *wait*, not the work.
    parse_in_subprocess: bool = True
    parse_workers: int = Field(default=2, ge=1)
    #: RLIMIT_AS for a parse child. An NCERT chapter peaks near 430 MB, so this
    #: leaves real headroom while still turning runaway growth into one dead
    #: child instead of an OOM-killed service.
    parse_memory_mb: int = Field(default=2048, ge=256)

    # ── OCR (FAQ Q7: "Scanned PDF" is a declared input kind) ────────────────
    #: Which recogniser runs on pages that carry no text layer. ``auto`` tries
    #: the hosted reader first and falls back through the local engines, so a
    #: deployment without a key still starts. ``none`` disables OCR entirely.
    #: Swapping this is the only change needed to change engines — nothing
    #: downstream of stage 1 knows which one ran.
    ocr_engine: Literal["auto", "azure", "tesseract", "easyocr", "none"] = "auto"
    azure_doc_intel_endpoint: str | None = None
    azure_doc_intel_key: str | None = None

    #: Below this mean confidence the package carries a warning and the teacher
    #: is told which pages were read by machine. Not a rejection threshold: a
    #: 0.72 page is usually still usable, and silently discarding a chapter
    #: helps nobody. 0.80 is where Azure's own per-word scores start
    #: correlating with visible transcription errors on textbook type.
    ocr_min_confidence: float = Field(default=0.80, ge=0.0, le=1.0)
    #: Beyond this many scanned pages, OCR is refused rather than run — the
    #: hosted tier is metered per page and a 400-page scan is a bill, not a
    #: chapter. FAQ Q1 says the expected input is a single chapter.
    ocr_max_pages: int = Field(default=60, ge=1)

    # ── observability ───────────────────────────────────────────────────────
    log_level: str = "INFO"
    #: JSON in a deployment where a log aggregator reads it; plain text is
    #: what you want when reading a local run in a terminal.
    log_json: bool = True

    app_version: str = "0.1.0"

    @model_validator(mode="after")
    def _required_key_for_profile(self) -> Settings:
        """Each profile has exactly one credential it cannot run without.

        `ci` needs none by design — the replay provider serves recorded cassettes,
        so CI never depends on a network or a key.
        """
        requirement = {
            "production": ("Open_Router_API_KEY", self.open_router_api_key),
            "dev": ("Open_Router_API_KEY", self.open_router_api_key),
        }.get(self.llm_profile)
        if requirement is None:
            return self
        required, value = requirement
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

    @property
    def max_archive_uncompressed_bytes(self) -> int:
        return self.max_archive_uncompressed_mb * 1024 * 1024

    @property
    def parse_memory_bytes(self) -> int:
        return self.parse_memory_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
