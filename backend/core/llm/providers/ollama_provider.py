"""Ollama adapter — open-weight models running on the machine itself.

The point of this provider is that it has no quota, no key, and no network. A
hosted free tier is generous until the day it is not, and "the demo could not
run because someone else's daily limit reset at midnight UTC" is a bad answer.
Ollama removes that failure mode entirely: the model is a file on disk.

It costs latency instead. Inference on a CPU is one to two orders of magnitude
slower than a hosted GPU, so this is a profile for proving the pipeline runs end
to end and for developing without burning quota — not for demonstrating the
quality a large model produces. ``prices`` is empty and every call reports zero
cost, which is true rather than a placeholder: electricity is not billed per
token.

**Why this file is so short.** Ollama serves an OpenAI-compatible
``/v1/chat/completions``, so the entire adapter is a base URL and a name. That
is the port doing its job — the retry loop, the JSON repair, the
response_format capability ladder and the token-ceiling fitting in
:mod:`openai_compat` are all provider-agnostic and were written before this
provider existed. Adding a fourth provider touching nothing else is the
evidence that the abstraction was real rather than decorative.
"""

from __future__ import annotations

from typing import Any, ClassVar

from contracts.llm import ModelSpec
from core.llm.providers.openai_compat import OpenAICompatibleAdapter

__all__ = ["DEFAULT_BASE_URL", "OllamaAdapter"]

#: Ollama's own default. It binds to localhost, so nothing here is reachable
#: off-box and no credential is required — the client sends a placeholder key
#: because the OpenAI SDK insists on one, not because anything checks it.
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"


class OllamaAdapter(OpenAICompatibleAdapter):
    name: ClassVar[str] = "ollama"
    default_base_url: ClassVar[str] = DEFAULT_BASE_URL

    #: Empty on purpose. Local inference has no per-token price, so every call
    #: reports 0.0 — a real zero, not missing data, and cost comparisons should
    #: treat it that way.
    prices: ClassVar[dict[str, tuple[float, float]]] = {}

    def _depth_controls(self, spec: ModelSpec) -> dict[str, Any]:
        """No reasoning-effort knob.

        Ollama exposes thinking depth per-model through its own ``/api/chat``
        options, not through the OpenAI-compatible surface this adapter speaks.
        Sending a field the endpoint ignores would be harmless; sending one it
        rejects would not, and there is no way to tell which from here. So the
        configured effort is deliberately dropped, and this docstring is the
        record of that being a decision rather than an oversight.
        """
        return {}
