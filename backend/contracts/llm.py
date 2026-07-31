"""Provider-agnostic LLM contracts.

Stages never see a provider SDK. They call ``LLMClient.parse(output_model=...)``
and receive a validated Pydantic object. This module defines the narrow port that
makes that possible across Anthropic, Gemini, and recorded replay.

**Deliberately narrow.** We abstract *only* "given a schema, return a validated
instance of it". Provider-specific machinery — Anthropic prompt caching and
adaptive thinking, Gemini context caching and thinking budget — lives behind the
port and is configured per provider, never exposed at the call site. Abstracting
those too would flatten every provider to its dumbest common denominator, which
is the usual way a multi-provider layer quietly costs more than it saves.

Provider selection policy (docs/02 ADR #11):

* ``groq``      — production, the deployed demo, and end-to-end runs. Fast, and
  its free tier is generous enough to run all ten stages repeatedly.
* ``gemini``    — local development and single-stage iteration.
* ``replay``    — CI. Serves recorded cassettes: deterministic, free, offline.
* ``anthropic`` — implemented but **disabled by default**. Calling it requires
  ``ALLOW_ANTHROPIC=true``, because billing against that key is an explicit
  decision rather than something a config typo should be able to trigger.

Quality evaluation (M11) is pinned to the production provider. Tuning prompts
against one model and shipping another means the eval numbers do not transfer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from contracts.primitives import StageName, StrictModel

__all__ = [
    "Effort",
    "LLMProvider",
    "LLMResult",
    "LLMUsage",
    "ModelSpec",
    "ProviderRouting",
    "ReasoningConfig",
]

LLMProvider = Literal["anthropic", "gemini", "groq", "replay"]

#: Reasoning depth, expressed provider-neutrally. Each provider maps it to its own
#: native control: Anthropic to ``output_config.effort`` with adaptive thinking,
#: Gemini to a thinking budget. Callers state intent; providers decide mechanism.
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ReasoningConfig(StrictModel):
    effort: Effort = "high"


class ModelSpec(StrictModel):
    """How one stage should be executed. Loaded from ``config/models.yaml``.

    Model choice is an operator decision expressed in configuration — never a
    hardcoded constant inside a stage.
    """

    provider: LLMProvider
    model: str = Field(
        min_length=1,
        description="Provider-native model id, e.g. 'claude-opus-5' or a Gemini model id.",
    )
    max_tokens: int = Field(default=16000, ge=1)
    reasoning: ReasoningConfig | None = Field(
        default=None,
        description="None means 'provider default'. Not every provider or model "
        "supports depth control; the adapter is responsible for degrading "
        "gracefully rather than erroring.",
    )
    cache_prefix: bool = Field(
        default=True,
        description="Ask the provider to cache the shared system+document prefix. "
        "Advisory: adapters that cannot honour it must ignore it, not fail.",
    )
    provider_options: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        description="Escape hatch for genuinely provider-specific knobs. Anything "
        "used by more than one provider belongs in a first-class field instead.",
    )


class ProviderRouting(StrictModel):
    """Resolved per-stage execution plan for a whole run."""

    default: ModelSpec
    stages: dict[StageName, ModelSpec] = Field(default_factory=dict)

    def for_stage(self, stage: StageName) -> ModelSpec:
        return self.stages.get(stage, self.default)


class LLMUsage(StrictModel):
    """Normalised accounting. Providers report differently; adapters translate.

    ``tokens_cached`` is 0 on providers without prompt caching — that is a real
    zero, not missing data, and cost comparisons should treat it that way.
    """

    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    tokens_cached: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)


class LLMResult[T: BaseModel](BaseModel):
    """Outcome of one structured generation call.

    ``degraded=True`` means the schema could not be satisfied even after the repair
    attempt and ``value`` is a minimal valid fallback. The job continues — a single
    weak stage should not discard the other nine — but the flag propagates into the
    validation report so the shortfall is visible rather than silently shipped.
    """

    value: T
    provider: LLMProvider
    model: str
    usage: LLMUsage
    attempts: int = Field(default=1, ge=1)
    repaired: bool = Field(
        default=False, description="Schema-error feedback was needed to get valid output."
    )
    degraded: bool = Field(default=False)
    issues: list[str] = Field(default_factory=list)
