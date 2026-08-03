"""Building a configured :class:`LLMClient` from settings.

Separate from ``client.py`` so that module stays free of configuration concerns
— it can be constructed directly with a hand-built routing table in a test, which
is what makes the retry, repair, and budget logic testable without a config file
on disk or an environment variable in scope.

The budget is per client and therefore per job. A run that goes pathological —
a repair loop, a document that fans out further than expected — stops at a known
ceiling instead of discovering the limit on a bill.
"""

from __future__ import annotations

from core.config import Settings
from core.llm.client import LLMClient, TokenBudget, build_adapters
from core.llm.router import load_routing

__all__ = ["build_llm_client"]


def build_llm_client(settings: Settings) -> LLMClient:
    """Resolve routing and adapters for the configured profile."""
    return LLMClient(
        routing=load_routing(settings.models_config_path, settings.llm_profile),
        adapters=build_adapters(
            openrouter_key=settings.open_router_api_key,
            openrouter_base_url=settings.open_router_base_url,
            azure_openai_endpoint=settings.azure_openai_endpoint,
            azure_openai_key=settings.azure_openai_key,
            azure_openai_api_version=settings.azure_openai_api_version,
        ),
        budget=TokenBudget(limit=settings.job_token_budget),
        concurrency=settings.llm_concurrency,
    )
