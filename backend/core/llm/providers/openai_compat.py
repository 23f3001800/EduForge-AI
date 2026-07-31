"""Shared base for OpenAI-compatible providers.

AI Pipe and Groq speak the same wire protocol, so they differ only in base URL,
model naming, and price table. Everything else — strict-schema negotiation, the
schema rewrite, refusal detection, usage extraction — is identical and lives here
once.

The one genuinely tricky behaviour is structured-output negotiation. "OpenAI
compatible" is a spectrum: some models honour ``response_format: json_schema``
with ``strict: true``, some accept only ``json_object``, and some ignore
``response_format`` entirely. The adapter tries the strongest form and steps down
on rejection, caching what worked so the cost is paid once per model rather than
on every call.

Stepping down never weakens *our* guarantee: ``LLMClient`` validates the response
against the real Pydantic model regardless of what the provider promised.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from pydantic import BaseModel

from contracts.llm import LLMUsage, ModelSpec
from core.llm.base import ContentRefused, LLMProviderError, RawCompletion

__all__ = ["OpenAICompatibleAdapter", "rewrite_schema_for_strict_mode"]

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

#: Providers with a tokens-per-minute cap count `max_tokens` as *reserved*
#: budget, not as measured usage — so an oversized reservation is rejected before
#: the model runs. The error states both numbers, which is enough to compute a
#: reservation that fits.
_TPM_LIMIT = re.compile(r"Limit\s+(\d+),\s*Requested\s+(\d+)", re.IGNORECASE)

#: Leave room for tokeniser disagreement between our estimate and theirs.
_TPM_SAFETY_MARGIN = 256

#: Below this an answer is not worth attempting; failing loudly beats returning
#: a truncated package that looks complete.
_MIN_USEFUL_MAX_TOKENS = 512

#: Substrings identifying "this model cannot do that response_format", as opposed
#: to a transport failure. Seeing one triggers a step down, not a retry.
_SCHEMA_UNSUPPORTED = (
    "response_format",
    "json_schema",
    "json schema",
    "not supported",
    "unsupported parameter",
    "unsupported value",
    "invalid schema",
    "does not support",
)


#: "Please try again in 4.7475s" / "try again in 1m2.5s"
_RETRY_DELAY = re.compile(r"try again in\s+(?:(\d+)m)?([\d.]+)s", re.IGNORECASE)


class _SalvageableGenerationError(Exception):
    """Provider-side schema validation failed but returned the raw generation."""

    def __init__(self, text: str) -> None:
        super().__init__("provider schema validation failed; raw generation recovered")
        self.text = text


def _salvage_failed_generation(exc: Any) -> str | None:
    """Recover the model's output from a provider-side schema rejection.

    Some providers validate against the requested schema themselves and return a
    400 carrying ``failed_generation`` — the text the model actually produced.
    That output is frequently correct in substance and broken only in form, so it
    is worth far more as input to a repair attempt than as a discarded error.
    """
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None

    # SDKs disagree on whether `body` is the error object or the envelope
    # containing it, so accept either rather than depending on one shape.
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    if error.get("code") != "json_validate_failed":
        return None

    generation = error.get("failed_generation")
    return generation if isinstance(generation, str) and generation.strip() else None


def _stated_retry_delay(exc: Any) -> float | None:
    """The provider's own reopen time, from the Retry-After header or the message.

    Preferred over exponential backoff whenever present: a rate limiter knows
    when its window reopens and we do not.
    """
    header = getattr(getattr(exc, "response", None), "headers", None)
    if header is not None:
        raw = header.get("retry-after")
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass

    match = _RETRY_DELAY.search(str(getattr(exc, "message", "") or exc))
    if match is None:
        return None
    minutes = float(match.group(1) or 0)
    return minutes * 60 + float(match.group(2))


def rewrite_schema_for_strict_mode(schema: Any) -> Any:
    """Make a Pydantic JSON schema acceptable to OpenAI strict mode.

    Strict mode requires every property to appear in ``required`` and forbids
    extra properties. Pydantic omits optional fields from ``required``, which
    strict mode rejects outright — so everything is marked required and optional
    fields simply arrive null. Our own validation is unaffected.
    """
    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: rewrite_schema_for_strict_mode(v) for k, v in value.items()}
        elif key in {"items", "additionalProperties"} and isinstance(value, dict):
            out[key] = rewrite_schema_for_strict_mode(value)
        elif key in {"anyOf", "allOf", "oneOf"} and isinstance(value, list):
            out[key] = [rewrite_schema_for_strict_mode(v) for v in value]
        elif key == "$defs" and isinstance(value, dict):
            out[key] = {k: rewrite_schema_for_strict_mode(v) for k, v in value.items()}
        else:
            out[key] = value

    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"])
        out.setdefault("additionalProperties", False)
    return out


class OpenAICompatibleAdapter:
    """Base for any provider exposing OpenAI chat-completions."""

    name: ClassVar[str] = "openai-compatible"
    default_base_url: ClassVar[str] = ""
    #: Rates per million tokens, keyed by model id. Fallback only — providers that
    #: report actual spend take precedence.
    prices: ClassVar[dict[str, tuple[float, float]]] = {}

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        from openai import AsyncOpenAI

        # max_retries=0: LLMClient owns backoff so retry policy is identical
        # across providers rather than each SDK applying its own.
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url or self.default_base_url, max_retries=0
        )
        # Remembers the strongest response_format each model accepted, so the
        # negotiation cost is paid once rather than on every call.
        self._format_support: dict[str, str] = {}

    # ── cost ────────────────────────────────────────────────────────────────

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        for known, (rate_in, rate_out) in self.prices.items():
            if model.startswith(known):
                return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000
        return 0.0

    # ── main entry point ────────────────────────────────────────────────────

    async def complete(
        self,
        *,
        spec: ModelSpec,
        system: str,
        user_content: str,
        output_model: type[BaseModel],
        extra: dict[str, Any] | None = None,
    ) -> RawCompletion:
        schema = rewrite_schema_for_strict_mode(output_model.model_json_schema())
        base_messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        # Strongest first, stepping down only on a schema-capability rejection.
        ladder = ["json_schema", "json_object", "none"]
        start = self._format_support.get(spec.model)
        if start in ladder:
            ladder = ladder[ladder.index(start) :]

        last_error: LLMProviderError | None = None
        for mode in ladder:
            messages, response_format = self._build_request(
                mode, base_messages, user_content, schema, output_model
            )
            try:
                response = await self._call(spec, messages, response_format)
            except _SalvageableGenerationError as salvaged:
                self._format_support[spec.model] = mode
                return RawCompletion(
                    text=salvaged.text,
                    model=spec.model,
                    usage=LLMUsage(),  # provider bills it, but reports no usage here
                )
            except LLMProviderError as exc:
                fitted = self._fit_to_token_ceiling(spec, exc)
                if fitted is not None:
                    # The reservation was too large for the per-minute ceiling.
                    # Retry once at a size that provably fits rather than making
                    # the caller guess a max_tokens that happens to work today.
                    try:
                        response = await self._call(fitted, messages, response_format)
                    except _SalvageableGenerationError as salvaged:
                        self._format_support[spec.model] = mode
                        return RawCompletion(
                            text=salvaged.text, model=fitted.model, usage=LLMUsage()
                        )
                    self._format_support[spec.model] = mode
                    return self._to_completion(response, fitted)
                if not self._is_capability_error(exc):
                    raise
                last_error = exc
                continue

            self._format_support[spec.model] = mode
            return self._to_completion(response, spec)

        raise last_error or LLMProviderError(
            f"{self.name}: no supported response format for {spec.model}"
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_capability_error(exc: LLMProviderError) -> bool:
        return any(marker in str(exc).lower() for marker in _SCHEMA_UNSUPPORTED)

    @staticmethod
    def _fit_to_token_ceiling(spec: ModelSpec, exc: LLMProviderError) -> ModelSpec | None:
        """Shrink ``max_tokens`` to fit a per-minute token ceiling, or None.

        Returns None when the error is not a reservation-too-large rejection, or
        when the remaining headroom is too small to be worth attempting — a
        truncated package that looks complete is worse than a clear failure.
        """
        message = str(exc)
        if "413" not in message and "too large" not in message.lower():
            return None

        match = _TPM_LIMIT.search(message)
        if match is None:
            return None

        limit, requested = int(match.group(1)), int(match.group(2))
        # `requested` is prompt + reservation, so removing our reservation leaves
        # the prompt cost, and the rest of the ceiling is what we may ask for.
        prompt_cost = max(requested - spec.max_tokens, 0)
        headroom = limit - prompt_cost - _TPM_SAFETY_MARGIN

        if headroom < _MIN_USEFUL_MAX_TOKENS or headroom >= spec.max_tokens:
            return None

        return spec.model_copy(update={"max_tokens": headroom})

    def _build_request(
        self,
        mode: str,
        base_messages: list[dict[str, Any]],
        user_content: str,
        schema: Any,
        output_model: type[BaseModel],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if mode == "json_schema":
            return base_messages, {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "schema": schema,
                    "strict": True,
                },
            }

        # Weaker modes cannot constrain the shape, so the schema goes in the
        # prompt instead. The model is told what to produce rather than forced.
        instructed = [
            base_messages[0],
            {
                "role": "user",
                "content": (
                    f"{user_content}\n\nReturn JSON conforming exactly to this "
                    f"schema. No prose, no code fences.\n{json.dumps(schema)}"
                ),
            },
        ]
        return instructed, {"type": "json_object"} if mode == "json_object" else None

    def _to_completion(self, response: Any, spec: ModelSpec) -> RawCompletion:
        choice = response.choices[0] if getattr(response, "choices", None) else None
        if choice is None:
            raise LLMProviderError(f"{self.name} returned no choices", retryable=True)

        finish = (getattr(choice, "finish_reason", "") or "").lower()
        if finish in {"content_filter", "safety"}:
            raise ContentRefused("Request blocked by provider safety filters.", category=finish)

        text = (choice.message.content or "").strip()
        if not text:
            raise LLMProviderError(
                f"empty response (finish_reason={finish!r}); max_tokens may be too low",
                retryable=False,
            )

        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0

        cost = self.estimate_cost(spec.model, tokens_in, tokens_out)
        reported = getattr(usage, "cost", None)
        if isinstance(reported, int | float) and reported > 0:
            cost = float(reported)

        return RawCompletion(
            text=text,
            model=getattr(response, "model", spec.model),
            usage=LLMUsage(
                tokens_in=tokens_in, tokens_out=tokens_out, tokens_cached=0, cost_usd=cost
            ),
        )

    async def _call(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None,
    ) -> Any:
        import openai

        request: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
            "max_tokens": spec.max_tokens,
        }
        if response_format is not None:
            request["response_format"] = response_format

        try:
            return await self._client.chat.completions.create(**request)
        except openai.APIStatusError as exc:
            salvaged = _salvage_failed_generation(exc)
            if salvaged is not None:
                # The provider's own schema check rejected the output, but it
                # returns what the model actually produced. Discarding that wastes
                # a full generation — often a good one that only broke on
                # serialisation. Hand it to LLMClient, whose validate-and-repair
                # loop is built for exactly this.
                raise _SalvageableGenerationError(salvaged) from exc
            raise LLMProviderError(
                f"{self.name} {exc.status_code}: {exc.message}",
                retryable=exc.status_code in _RETRYABLE_STATUS,
                retry_after=_stated_retry_delay(exc),
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMProviderError(
                f"{self.name} connection error: {exc}", retryable=True
            ) from exc
