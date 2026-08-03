"""Azure OpenAI adapter.

Same wire protocol as OpenAI, three differences that matter, each of which is a
real incompatibility rather than a preference:

1. **The model name is a deployment name.** Azure routes on a deployment you
   created, not on a catalogue id, and the two need not match. ``ModelSpec.model``
   therefore carries the *deployment*, and ``config/models.yaml`` says so.

2. **Auth and URL shape differ** — an ``api-key`` header against
   ``/openai/deployments/{deployment}/...`` with a pinned ``api-version``, not a
   bearer token against ``/v1``. ``AsyncAzureOpenAI`` handles that, which is why
   this overrides the client rather than passing a ``base_url`` to the base
   class; a hand-built base URL would work until the SDK changed its path
   construction.

3. **Reasoning models reject ``max_tokens``.** The gpt-5 family requires
   ``max_completion_tokens``, and sending the older field is a 400 before the
   request reaches a model. That is the whole reason ``_call`` is overridden
   here — verified against a live deployment, not inferred from documentation.

Cost is deliberately not modelled. Azure prices per deployment, per region and
per agreement, and a hardcoded table would report confident, wrong numbers into
provenance that a reader would have no reason to doubt. ``estimate_cost``
returning 0.0 with no price table means every call reports zero, and the
platform's own billing stays authoritative — the same reasoning the evaluation
framework applies to metrics it cannot measure.
"""

from __future__ import annotations

from typing import Any, ClassVar

from contracts.llm import ModelSpec
from core.llm.base import LLMProviderError
from core.llm.providers.openai_compat import (
    _RETRYABLE_STATUS,
    OpenAICompatibleAdapter,
    _salvage_failed_generation,
    _SalvageableGenerationError,
    _stated_retry_delay,
)

__all__ = ["AzureOpenAIAdapter"]

#: Model families that take ``max_completion_tokens`` instead of ``max_tokens``.
#: Matched by prefix because deployments are named freely — a deployment called
#: ``gpt-5-mini`` and one called ``gpt-5-mini-prod`` are the same family.
_COMPLETION_TOKEN_FAMILIES = ("gpt-5", "o1", "o3", "o4")


class AzureOpenAIAdapter(OpenAICompatibleAdapter):
    name: ClassVar[str] = "azure_openai"
    default_base_url: ClassVar[str] = ""

    #: Empty on purpose — see the module docstring. Azure pricing is per
    #: deployment and per agreement, so any table here would be a guess
    #: presented as a measurement.
    prices: ClassVar[dict[str, tuple[float, float]]] = {}

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        *,
        api_version: str = "2024-12-01-preview",
    ) -> None:
        from openai import AsyncAzureOpenAI

        # max_retries=0 for the same reason as every other adapter: LLMClient
        # owns backoff, so retry policy is identical across providers rather
        # than each SDK applying its own on top.
        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            max_retries=0,
        )
        self._format_support: dict[str, str] = {}

    def _depth_controls(self, spec: ModelSpec) -> dict[str, Any]:
        """Reasoning depth, where the deployed family accepts it.

        ``reasoning_effort`` is native on the gpt-5 and o-series deployments and
        rejected by the rest, so it is sent only to the families that take it.
        Guessing wrong here costs a 400 on every call, not a degraded answer.
        """
        if not self._takes_completion_tokens(spec.model):
            return {}
        effort = self._effort(spec)
        return {"reasoning_effort": effort} if effort else {}

    @staticmethod
    def _takes_completion_tokens(model: str) -> bool:
        name = model.lower()
        return any(name.startswith(family) for family in _COMPLETION_TOKEN_FAMILIES)

    async def _call(
        self,
        spec: ModelSpec,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None,
    ) -> Any:
        import openai

        request: dict[str, Any] = {"model": spec.model, "messages": messages}
        if self._takes_completion_tokens(spec.model):
            request["max_completion_tokens"] = spec.max_tokens
        else:
            request["max_tokens"] = spec.max_tokens

        if response_format is not None:
            request["response_format"] = response_format
        request.update(self._depth_controls(spec))

        try:
            return await self._client.chat.completions.create(**request)
        except openai.APIStatusError as exc:
            # Same salvage path as the base class: a provider-side schema
            # rejection still carries the generation the model produced, and
            # that is worth more to the repair loop than a discarded error.
            salvaged = _salvage_failed_generation(exc)
            if salvaged is not None:
                raise _SalvageableGenerationError(salvaged) from exc
            # Translate into the port's own error type. This is not cosmetic:
            # `complete()`'s response_format ladder catches `LLMProviderError`
            # to step json_schema -> json_object -> none, so re-raising the raw
            # SDK exception makes every capability difference fatal instead of
            # negotiable. Azure rejects our schemas outright — it requires
            # `required` to name every property, and Pydantic omits optional
            # fields — so without this the very first classification call dies.
            raise LLMProviderError(
                f"{self.name} {exc.status_code}: {exc.message}",
                retryable=exc.status_code in _RETRYABLE_STATUS,
                retry_after=_stated_retry_delay(exc),
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMProviderError(f"{self.name} connection error: {exc}", retryable=True) from exc
