"""Per-stage model routing — resolves `config/models.yaml` into a `ProviderRouting`.

Stages ask for a stage name and receive a `ModelSpec`. They never learn which
provider answered, which is what allows the same pipeline to run on OpenRouter
in production and development, and recorded cassettes in CI.

Inheritance is two-level and shallow on purpose: a stage entry overrides
individual fields of its profile's `default`, and anything it omits is inherited.
Deeper config inheritance is where model routing becomes impossible to reason
about at 2am.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts import ModelSpec, ProviderRouting, ReasoningConfig
from contracts.primitives import STAGE_NAMES

__all__ = ["EVAL_PROFILE", "load_routing"]

#: Quality evaluation (M11) runs only under this profile. Tuning prompts against
#: one model and shipping another means the scores do not transfer, so the eval
#: harness refuses to run elsewhere rather than producing numbers that mislead.
EVAL_PROFILE = "production"


def _merge(default: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(default)
    for key, value in override.items():
        if (
            key == "reasoning"
            and isinstance(value, dict)
            and isinstance(merged.get("reasoning"), dict)
        ):
            merged["reasoning"] = {**merged["reasoning"], **value}
        else:
            merged[key] = value
    return merged


def _to_spec(raw: dict[str, Any]) -> ModelSpec:
    data = dict(raw)
    reasoning = data.pop("reasoning", None)
    return ModelSpec(
        **data,
        reasoning=ReasoningConfig(**reasoning) if reasoning else None,
    )


def load_routing(path: Path, profile: str) -> ProviderRouting:
    """Load one profile from the routing config.

    Raises with the available profile names rather than a KeyError, because the
    usual cause is a typo in ``LLM_PROFILE`` and the fix should be obvious from
    the error alone.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profiles = document.get("profiles") or {}

    if profile not in profiles:
        available = ", ".join(sorted(profiles)) or "<none>"
        raise ValueError(f"LLM profile {profile!r} not found in {path}. Available: {available}")

    block = profiles[profile]
    default_raw = block.get("default")
    if not default_raw:
        raise ValueError(f"profile {profile!r} has no `default` model spec")

    default = _to_spec(default_raw)

    stages: dict[str, ModelSpec] = {}
    for stage_name, override in (block.get("stages") or {}).items():
        if stage_name not in STAGE_NAMES:
            raise ValueError(
                f"profile {profile!r} configures unknown stage {stage_name!r}. "
                f"Valid stages: {', '.join(STAGE_NAMES)}"
            )
        stages[stage_name] = _to_spec(_merge(default_raw, override or {}))

    return ProviderRouting(default=default, stages=stages)  # type: ignore[arg-type]
