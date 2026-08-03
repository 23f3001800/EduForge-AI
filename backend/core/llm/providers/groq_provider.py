"""Groq adapter — the end-to-end testing provider.

Chosen for full-pipeline runs because it is fast and its free tier is generous
enough to run all ten stages repeatedly. That matters more than it sounds: a
pipeline you cannot afford to run end to end is a pipeline whose integration bugs
you find during the demo.

Expect weaker pedagogical output than a frontier model. That is the accepted
trade for this profile — it exists to prove the stages compose, not to produce
the graded package.
"""

from __future__ import annotations

from typing import Any, ClassVar

from contracts.llm import ModelSpec
from core.llm.providers.openai_compat import OpenAICompatibleAdapter

__all__ = ["DEFAULT_BASE_URL", "GroqAdapter"]

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"


class GroqAdapter(OpenAICompatibleAdapter):
    name: ClassVar[str] = "groq"
    default_base_url: ClassVar[str] = DEFAULT_BASE_URL

    #: Rates per million tokens. Groq does not report spend per response, so these
    #: are what the cost figures in the package's provenance are built from.
    prices: ClassVar[dict[str, tuple[float, float]]] = {
        "openai/gpt-oss-120b": (0.15, 0.75),
        "openai/gpt-oss-20b": (0.10, 0.50),
        "llama-3.3-70b-versatile": (0.59, 0.79),
        "llama-3.1-8b-instant": (0.05, 0.08),
        "moonshotai/kimi-k2-instruct": (1.00, 3.00),
        "qwen/qwen3-32b": (0.29, 0.59),
    }

    #: Model families that accept `reasoning_effort`. Groq rejects the field with
    #: a 400 on models that do not reason, so this is an allow-list rather than a
    #: hope — an advisory knob must never be able to fail a call.
    reasoning_models: ClassVar[tuple[str, ...]] = ("openai/gpt-oss", "qwen/qwen3")

    def _depth_controls(self, spec: ModelSpec) -> dict[str, Any]:
        """Groq's `reasoning_effort`, for the models that have one.

        The stage-level effort in `config/models.yaml` reached nothing before
        this: every profile configured it and the request never carried it. On
        this profile it is not cosmetic — effort drives how many tokens the model
        spends thinking, and thinking tokens are billed against the same 8000 TPM
        ceiling as everything else, so `effort: low` on the validation stage is
        part of how the profile fits at all.
        """
        effort = self._effort(spec)
        if effort is None or not spec.model.startswith(self.reasoning_models):
            return {}
        return {"reasoning_effort": effort}
