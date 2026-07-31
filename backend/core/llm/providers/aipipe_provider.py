"""AI Pipe adapter — OpenAI-compatible proxy fronting OpenRouter.

One credential reaches many models, which is why this is the production provider:
changing model is a config edit, not a new integration.

Two things this adapter has to handle that the direct providers do not:

* **Model-dependent structured output.** OpenRouter proxies many vendors, and not
  all support ``response_format: json_schema``. The adapter attempts the strict
  form, and on rejection falls back to ``json_object`` plus a schema in the
  prompt. ``LLMClient`` validates against the real Pydantic model either way, so
  the fallback loosens the provider's guarantee, never ours.

* **A tight budget.** The free tier is roughly $0.10/week and a full pipeline run
  is 20-60 calls, so cost is reported per call and the default models are the
  cheap ones. Read the usage numbers before promoting a stage to a larger model.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from contracts.llm import LLMUsage, ModelSpec
from core.llm.base import ContentRefused, LLMProviderError, RawCompletion

__all__ = ["DEFAULT_BASE_URL", "AIPipeAdapter"]

DEFAULT_BASE_URL = "https://aipipe.org/openrouter/v1"

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

#: OpenRouter reports real cost in its response, so this is only a fallback for
#: models it does not price. Rates per million tokens.
_FALLBACK_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-4.1-nano": (0.10, 0.40),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
}

#: Markers that mean "this model cannot do strict json_schema", as opposed to a
#: transport failure. Seeing one flips the request to the looser json_object form.
_SCHEMA_UNSUPPORTED = (
    "response_format",
    "json_schema",
    "not supported",
    "unsupported parameter",
    "invalid schema",
)


def _fallback_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    rate_in, rate_out = _FALLBACK_PRICES.get(model, (0.0, 0.0))
    return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000


def _strip_unsupported(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict mode requires every property to be listed in `required`.

    Pydantic marks optional fields absent from `required`, which strict mode
    rejects outright. Since our own validation runs afterwards regardless, the
    pragmatic fix is to require everything and let optional fields arrive null.
    """
    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: _strip_unsupported(v) for k, v in value.items()}
        elif key in {"items", "additionalProperties"} and isinstance(value, dict):
            out[key] = _strip_unsupported(value)
        elif key in {"anyOf", "allOf", "oneOf"} and isinstance(value, list):
            out[key] = [_strip_unsupported(v) for v in value]
        elif key == "$defs" and isinstance(value, dict):
            out[key] = {k: _strip_unsupported(v) for k, v in value.items()}
        else:
            out[key] = value

    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"])
        out.setdefault("additionalProperties", False)
    return out


class AIPipeAdapter:
    name = "aipipe"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        from openai import AsyncOpenAI

        # max_retries=0: LLMClient owns backoff so the policy is identical across
        # providers rather than each SDK applying its own.
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:

        schema = _strip_unsupported(output_model.model_json_schema())
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        strict_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_model.__name__,
                "schema": schema,
                "strict": True,
            },
        }

        try:
            response = await self._call(spec, messages, strict_format)
        except LLMProviderError as exc:
            if not any(marker in str(exc).lower() for marker in _SCHEMA_UNSUPPORTED):
                raise
            # Model cannot honour a strict schema. Ask for JSON and put the shape
            # in the prompt; our own validation is unchanged.
            loosened = [
                messages[0],
                {
                    "role": "user",
                    "content": (
                        f"{user_content}\n\nReturn JSON conforming exactly to this "
                        f"schema:\n{json.dumps(schema)}"
                    ),
                },
            ]
            response = await self._call(spec, loosened, {"type": "json_object"})

        choice = response.choices[0] if response.choices else None
        if choice is None:
            raise LLMProviderError("aipipe returned no choices", retryable=True)

        finish = (choice.finish_reason or "").lower()
        if finish in {"content_filter", "safety"}:
            raise ContentRefused("Request blocked by provider safety filters.", category=finish)

        text = (choice.message.content or "").strip()
        if not text:
            raise LLMProviderError(
                f"empty response (finish_reason={finish!r}); max_tokens may be too low",
                retryable=False,
            )

        usage = response.usage
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0

        # OpenRouter reports actual spend; prefer it over our rate table.
        cost = _fallback_cost(spec.model, tokens_in, tokens_out)
        reported = getattr(response, "usage", None)
        actual = getattr(reported, "cost", None) if reported is not None else None
        if isinstance(actual, int | float) and actual > 0:
            cost = float(actual)

        return RawCompletion(
            text=text,
            model=getattr(response, "model", spec.model),
            usage=LLMUsage(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cached=0,
                cost_usd=cost,
            ),
        )

    async def _call(
        self, spec: ModelSpec, messages: list[dict[str, Any]], response_format: dict[str, Any]
    ) -> Any:
        import openai

        try:
            return await self._client.chat.completions.create(
                model=spec.model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=spec.max_tokens,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except openai.APIStatusError as exc:
            raise LLMProviderError(
                f"aipipe {exc.status_code}: {exc.message}",
                retryable=exc.status_code in _RETRYABLE_STATUS,
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMProviderError(f"aipipe connection error: {exc}", retryable=True) from exc
