"""Anthropic adapter.

Uses the official ``anthropic`` SDK. Three provider-specific capabilities are
exercised here that a generic wrapper would flatten away:

* **Structured outputs** via ``output_config.format`` with the stage's JSON
  schema, so the response is constrained rather than parsed hopefully.
* **Adaptive thinking** with a per-stage effort level, which is how reasoning
  depth is tuned on stages 3, 4, 5, and 9.
* **Prompt caching** on the system + document prefix. Stages 3 through 8 all run
  over the same document, so the cached prefix is read seven times after being
  written once. Stable content goes first and volatile content last — a single
  varying byte in the prefix silently disables the whole saving.

Refusals arrive as a successful response with ``stop_reason == "refusal"``, not
as an exception, so ``stop_reason`` is checked before reading content.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from contracts.llm import LLMUsage, ModelSpec
from core.llm.base import ContentRefused, LLMProviderError, RawCompletion

__all__ = ["AnthropicAdapter"]

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

# Published rates per million tokens. Used for reporting only; the provider's
# invoice is authoritative.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    rate_in, rate_out = _PRICES.get(model, (0.0, 0.0))
    return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key, max_retries=0)  # client owns retry

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:
        import anthropic

        # Cache the stable prefix. Everything volatile is in the user turn, after
        # the breakpoint, so the cached portion stays byte-identical across stages.
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if spec.cache_prefix:
            system_blocks[-1]["cache_control"] = {"type": "ephemeral"}

        request: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            "system": system_blocks,
            "messages": [{"role": "user", "content": user_content}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": output_model.model_json_schema(),
                }
            },
        }

        if spec.reasoning is not None:
            request["thinking"] = {"type": "adaptive"}
            request["output_config"]["effort"] = spec.reasoning.effort

        try:
            response = await self._client.messages.create(**request)
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(
                f"anthropic {exc.status_code}: {exc.message}",
                retryable=exc.status_code in _RETRYABLE_STATUS,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError(f"anthropic connection error: {exc}", retryable=True) from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ContentRefused(
                "Request declined by provider safety classifiers.", category=category
            )

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            # max_tokens reached during thinking is the usual cause; surfacing it
            # as retryable-false avoids burning attempts on a budget problem.
            raise LLMProviderError(
                f"empty response (stop_reason={response.stop_reason!r}); "
                "max_tokens may be too low for this stage",
                retryable=False,
            )

        usage = response.usage
        tokens_in = usage.input_tokens
        tokens_out = usage.output_tokens
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0

        return RawCompletion(
            text=text,
            model=response.model,
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cached=cached,
                cost_usd=_estimate_cost(spec.model, tokens_in, tokens_out),
            ),
        )

    @staticmethod
    def format_schema_error(payload: str, error: str) -> str:
        """Repair turn: hand back the invalid output plus the validator's complaint."""
        return (
            "The JSON you returned did not satisfy the required schema.\n\n"
            f"Validation error:\n{error}\n\n"
            f"Your previous output:\n{payload[:4000]}\n\n"
            "Return corrected JSON only. No prose, no code fences."
        )


def build_user_content(document_block: str, instructions: str) -> str:
    """Stable document context first, volatile instructions last (cache order)."""
    return f"{document_block}\n\n{instructions}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
