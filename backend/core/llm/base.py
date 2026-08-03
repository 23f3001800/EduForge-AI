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

__all__ = [
    "MIN_USEFUL_MAX_TOKENS",
    "TPM_SAFETY_MARGIN",
    "ContentRefused",
    "LLMProviderError",
    "ProviderAdapter",
    "RawCompletion",
    "estimate_tokens",
    "schema_tokens",
]

#: Headroom left between what we compute a request will cost and the provider's
#: hard ceiling. Our estimate and their tokeniser will not agree exactly, and the
#: penalty for being 1% low is a rejected request, not a slightly larger bill.
TPM_SAFETY_MARGIN = 256

#: Below this an answer is not worth attempting: the model will be cut off
#: mid-object and return something that fails schema validation anyway. Failing
#: loudly beats returning a truncated package that looks complete.
MIN_USEFUL_MAX_TOKENS = 512

#: Characters per token. Deliberately one shared constant rather than a per-caller
#: guess: the client's budget check, the adapter's pre-flight clamp, and the
#: stage's prompt-budget arithmetic must agree, or the stage packs to a size the
#: adapter then rejects. ~4 is the usual English/JSON figure and errs high enough
#: for prose; :data:`TPM_SAFETY_MARGIN` covers the remainder.
CHARS_PER_TOKEN = 4


def estimate_tokens(*parts: str) -> int:
    """Cheap, provider-neutral token estimate for one or more prompt fragments.

    A real tokeniser would be more accurate and would mean shipping (and picking)
    one per provider for a number that only ever feeds a conservative bound. The
    safety margin exists precisely so this can stay an estimate.
    """
    return sum(len(part) for part in parts) // CHARS_PER_TOKEN


def schema_tokens(output_model: type[BaseModel]) -> int:
    """What the output schema costs in the request, whichever way it travels.

    Under ``response_format: json_schema`` it rides in the request body; under the
    weaker negotiated modes the adapter puts it in the user message instead.
    Either way the provider counts it, and for our contract models it is thousands
    of tokens — the largest fixed cost in an extraction prompt after the document.
    A stage sizing its document window has to subtract it or the window is fiction.

    The quarter added on top covers the strict-mode rewrite, which republishes
    every property name in a ``required`` list and stamps ``additionalProperties``
    on every object. Erring high here is free; erring low is a rejected request.
    """
    import json

    return estimate_tokens(json.dumps(output_model.model_json_schema())) * 5 // 4


class LLMProviderError(RuntimeError):
    """A provider call failed.

    ``retryable`` decides whether backoff applies. ``retry_after`` carries the
    provider's own stated delay when it gives one — a rate limiter knows exactly
    when its window reopens, and guessing with exponential backoff either wastes
    time or retries too early and burns another attempt.
    """

    def __init__(
        self, message: str, *, retryable: bool = False, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


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
