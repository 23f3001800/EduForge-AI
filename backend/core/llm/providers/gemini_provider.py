"""Gemini adapter.

The development provider: cheap enough to run the full pipeline repeatedly while
wiring stages together.

Provider-specific handling kept inside this adapter:

* ``response_schema`` + ``response_mime_type="application/json"`` for structured
  output, which is Gemini's equivalent of a constrained format.
* ``thinking_config.thinking_budget`` for reasoning depth. Our provider-neutral
  ``effort`` is mapped to a token budget here, because that is the control Gemini
  actually exposes.
* Implicit context caching — Gemini caches long shared prefixes automatically, so
  ``cache_prefix`` needs no explicit breakpoint the way Anthropic's does.

``tokens_cached`` is reported when the API supplies it and is 0 otherwise. That
zero is a real measurement, not missing data, so cost comparisons across
providers stay honest.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from contracts.llm import Effort, LLMUsage, ModelSpec
from core.llm.base import ContentRefused, LLMProviderError, RawCompletion

__all__ = ["GeminiAdapter"]

#: Our provider-neutral effort mapped onto Gemini's thinking-token budget.
#: -1 lets the model decide, which is the closest analogue to adaptive thinking.
_EFFORT_TO_BUDGET: dict[Effort, int] = {
    "low": 0,
    "medium": 4096,
    "high": 12288,
    "xhigh": 24576,
    "max": -1,
}

_RETRYABLE_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "resource_exhausted",
    "unavailable",
    "deadline",
    "internal error",
)

_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    for known, (rate_in, rate_out) in _PRICES.items():
        if model.startswith(known):
            return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000
    return 0.0


#: JSON Schema keywords the Gemini Developer API rejects or ignores. Pydantic
#: emits several of them for any model using `extra="forbid"` — which ours all do.
_UNSUPPORTED_KEYS = {
    "additionalProperties",
    "$schema",
    "$id",
    "discriminator",
    "patternProperties",
    "const",
    "examples",
    "default",
    "exclusiveMinimum",
    "exclusiveMaximum",
}

_MAX_INLINE_DEPTH = 12


def sanitise_schema(
    schema: dict[str, Any], defs: dict[str, Any] | None = None, depth: int = 0
) -> dict[str, Any]:
    """Rewrite a Pydantic JSON schema into the subset Gemini accepts.

    Three transformations, each forced by a real rejection:

    * ``additionalProperties`` (and friends) are stripped — the Developer API
      errors on them outright.
    * ``$ref``/``$defs`` are inlined, because reference resolution is unreliable
      here and a dangling ref silently degrades the constraint to "any object".
    * ``anyOf: [T, null]`` — how Pydantic renders an optional field — is folded
      into Gemini's ``nullable`` form.

    Depth-bounded: ``OutlineNode`` is self-referential, so naive inlining would
    not terminate. Past the limit the node degrades to an unconstrained object,
    which is a weaker constraint but still valid.
    """
    if defs is None:
        defs = schema.get("$defs", {}) or schema.get("definitions", {}) or {}

    if depth > _MAX_INLINE_DEPTH:
        return {"type": "object"}

    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        target = defs.get(name)
        if target is None:
            return {"type": "object"}
        return sanitise_schema(target, defs, depth + 1)

    # Optional fields: anyOf [T, null] -> T with nullable.
    any_of = schema.get("anyOf")
    if any_of:
        non_null = [s for s in any_of if s.get("type") != "null"]
        nullable = len(non_null) != len(any_of)
        if len(non_null) == 1:
            inner = sanitise_schema(non_null[0], defs, depth + 1)
            if nullable:
                inner["nullable"] = True
            for key in ("description", "title"):
                if key in schema and key not in inner:
                    inner[key] = schema[key]
            return inner
        cleaned = {k: v for k, v in schema.items() if k not in _UNSUPPORTED_KEYS}
        cleaned["anyOf"] = [sanitise_schema(s, defs, depth + 1) for s in non_null]
        if nullable:
            cleaned["nullable"] = True
        return cleaned

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYS or key in {"$defs", "definitions"}:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: sanitise_schema(v, defs, depth + 1) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = sanitise_schema(value, defs, depth + 1)
        else:
            out[key] = value
    return out


class GeminiAdapter:
    name = "gemini"

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:
        from google.genai import types

        config: dict[str, Any] = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            # A sanitised dict, not the Pydantic model: passing the model lets the
            # SDK emit keywords the Developer API rejects. Validation against the
            # real model still happens in LLMClient, so nothing is loosened.
            "response_schema": sanitise_schema(output_model.model_json_schema()),
            "max_output_tokens": spec.max_tokens,
        }

        if spec.reasoning is not None:
            budget = _EFFORT_TO_BUDGET.get(spec.reasoning.effort, 4096)
            config["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)

        try:
            response = await self._client.aio.models.generate_content(
                model=spec.model,
                contents=user_content,
                config=types.GenerateContentConfig(**config),
            )
        except Exception as exc:  # SDK raises a wide range of transport errors
            message = str(exc).lower()
            raise LLMProviderError(
                f"gemini error: {exc}",
                retryable=any(marker in message for marker in _RETRYABLE_MARKERS),
            ) from exc

        # A blocked prompt returns a response with no candidates rather than an
        # error, so it has to be detected rather than caught.
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ContentRefused(
                "Request blocked by provider safety filters.",
                category=str(feedback.block_reason),
            )

        text = (response.text or "").strip()
        if not text:
            finish = None
            if getattr(response, "candidates", None):
                finish = getattr(response.candidates[0], "finish_reason", None)
            if finish is not None and "safety" in str(finish).lower():
                raise ContentRefused("Response blocked by provider safety filters.")
            raise LLMProviderError(
                f"empty response (finish_reason={finish!r}); max_tokens may be too low",
                retryable=False,
            )

        usage = getattr(response, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", 0) or 0
        tokens_out = getattr(usage, "candidates_token_count", 0) or 0
        cached = getattr(usage, "cached_content_token_count", 0) or 0

        return RawCompletion(
            text=text,
            model=spec.model,
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cached=cached,
                cost_usd=_estimate_cost(spec.model, tokens_in, tokens_out),
            ),
        )
