"""OpenRouter adapter — the production provider.

One credential reaches many vendors' models, and its free tier is generous enough
to run the whole ten-stage pipeline repeatedly. That matters more than it sounds:
a pipeline you cannot afford to run end to end is one whose integration bugs
surface during the demo rather than during development.

Model ids ending ``:free`` cost nothing but carry tighter rate limits and, in
several cases, weaker structured-output support. The shared base already
negotiates that down (strict json_schema → json_object → prompt-only) and our own
Pydantic validation runs regardless, so a weaker model costs quality, never
correctness of shape.

OpenRouter reports actual spend on the response, so the price table here is only a
fallback for models it does not price.
"""

from __future__ import annotations

from typing import ClassVar

from core.llm.providers.openai_compat import OpenAICompatibleAdapter

__all__ = ["DEFAULT_BASE_URL", "OpenRouterAdapter"]

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterAdapter(OpenAICompatibleAdapter):
    name: ClassVar[str] = "openrouter"
    default_base_url: ClassVar[str] = DEFAULT_BASE_URL

    #: Rates per million tokens. `:free` variants are 0/0 by definition; the paid
    #: entries exist so a deliberate upgrade still reports honest cost.
    prices: ClassVar[dict[str, tuple[float, float]]] = {
        "deepseek/deepseek-chat-v3-0324:free": (0.0, 0.0),
        "meta-llama/llama-3.3-70b-instruct:free": (0.0, 0.0),
        "google/gemini-2.0-flash-exp:free": (0.0, 0.0),
        "qwen/qwen-2.5-72b-instruct:free": (0.0, 0.0),
        "mistralai/mistral-small-3.1-24b-instruct:free": (0.0, 0.0),
        "openai/gpt-4.1-nano": (0.10, 0.40),
        "openai/gpt-4.1-mini": (0.40, 1.60),
    }
