"""The provider port.

One method: given a Pydantic model and a prompt, return a validated instance.
Everything provider-specific — Anthropic's prompt caching and adaptive thinking,
Gemini's response schemas and thinking budget — lives inside an adapter and is
configured per provider. Stages never learn which provider answered.

Deliberately narrow. A port that also abstracted caching and reasoning controls
would reduce every provider to its weakest common feature set, which is the usual
way a multi-provider layer costs more than it saves (docs/02 ADR #11).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from contracts.llm import LLMUsage, ModelSpec

__all__ = ["ContentRefused", "LLMProviderError", "ProviderAdapter", "RawCompletion"]


class LLMProviderError(RuntimeError):
    """A provider call failed. ``retryable`` decides whether backoff applies."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ContentRefused(LLMProviderError):
    """The provider's safety classifiers declined the request.

    Not retryable — the same prompt refuses again. The stage degrades and the job
    continues, with the refusal recorded in the validation report rather than
    silently producing an empty section.
    """

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message, retryable=False)
        self.category = category


class RawCompletion(BaseModel):
    """A provider response before schema validation."""

    text: str
    usage: LLMUsage
    model: str


class ProviderAdapter(Protocol):
    """Implemented once per provider."""

    name: str

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:
        """Return the model's response as text expected to contain valid JSON.

        Adapters raise :class:`LLMProviderError` with ``retryable`` set correctly;
        the client owns backoff, budget, and schema repair so that policy is
        identical across providers rather than reimplemented three times.
        """
        ...
