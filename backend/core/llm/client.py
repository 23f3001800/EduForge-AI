"""LLMClient — the single choke point for every model call in the system.

No stage talks to a provider SDK. Everything goes through ``parse()``, which owns
the policy that must be identical everywhere:

* **Structured output** — the response is validated against the stage's Pydantic
  model. One repair attempt feeds the validation error back; a second failure
  yields a degraded object so one weak stage cannot discard the other nine.
* **Retry** — exponential backoff with jitter on retryable provider errors only.
  Jitter matters: fan-out means several calls fail at the same instant, and
  without it they all retry at the same instant too.
* **Budget** — a per-job token ceiling checked before each call. A runaway job
  stops and publishes what it has rather than billing without limit.
* **Concurrency** — one semaphore for the whole job. Rate limiting lives here,
  not in the graph, so there is a single number to tune.
* **Accounting** — every attempt is recorded, including failures. A retry that
  cost tokens and produced nothing is exactly what you want visible.

Owning this in one place is what makes the provider port worth having: swap
Anthropic for Gemini and none of the above changes.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from contracts.llm import LLMResult, LLMUsage, ModelSpec, ProviderRouting
from contracts.primitives import StageName
from core.llm.base import (
    TPM_SAFETY_MARGIN,
    ContentRefused,
    LLMProviderError,
    ProviderAdapter,
    estimate_tokens,
)
from core.obs import metrics

__all__ = [
    "BudgetExhausted",
    "CallRecord",
    "LLMClient",
    "PlaceholderUnavailable",
    "TokenBudget",
]

MAX_ATTEMPTS = 4
#: Cap for *guessed* exponential backoff.
BACKOFF_CAP_S = 30.0
#: Separate, higher cap for a delay the provider stated itself. Truncating that
#: to the guess cap is actively harmful: we retry before the window reopens and
#: burn an attempt on a failure we were told the exact timing of. Per-minute rate
#: limits routinely ask for 50s+, and this pipeline is built for long-running
#: jobs, so waiting is cheap and a wasted attempt is not.
STATED_DELAY_CAP_S = 120.0
_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class BudgetExhausted(RuntimeError):
    """The job's token ceiling was reached. Publish partial rather than continue."""


class PlaceholderUnavailable(TypeError):
    """No honest placeholder exists for a required field of a degraded model.

    Raised rather than guessed. See :func:`_placeholders`.
    """


@dataclass(slots=True)
class TokenBudget:
    limit: int
    used: int = 0

    def check(self, projected: int) -> None:
        if self.used + projected > self.limit:
            raise BudgetExhausted(
                f"token budget exhausted: {self.used} used of {self.limit}, "
                f"next call projected at ~{projected}"
            )

    def record(self, usage: LLMUsage) -> None:
        self.used += usage.tokens_in + usage.tokens_out


@dataclass(slots=True)
class CallRecord:
    """One attempt, successful or not. Written to `llm_calls` for observability."""

    stage: str
    provider: str
    model: str
    attempt: int
    outcome: str  # ok | repaired | degraded | refused | error
    usage: LLMUsage
    error: str | None = None


def _strip_fences(text: str) -> str:
    """Models wrap JSON in code fences even when told not to. Cheaper to strip."""
    return _FENCE.sub("", text).strip()


def _extract_json(text: str, *, expects_object: bool = True) -> str:
    """Best-effort isolation of the JSON body from surrounding prose.

    Also unwraps ``[ {...} ]`` when a single object was expected. Models wrap
    their answer in an array often enough that rejecting it would spend a repair
    attempt on a formatting slip rather than on a content problem — and repair
    attempts are the scarce resource.
    """
    cleaned = _strip_fences(text)
    if not cleaned.startswith(("{", "[")):
        start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1), default=-1)
        if start == -1:
            return cleaned
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        cleaned = cleaned[start : end + 1] if end > start else cleaned

    if expects_object and cleaned.startswith("["):
        try:
            parsed = json.loads(cleaned)
        except ValueError:
            return cleaned
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            return json.dumps(parsed[0])
    return cleaned


def _validate_tolerantly[T: BaseModel](payload: str, model: type[T]) -> T:
    """Validate, retrying once with unknown keys removed.

    Our contract models set ``extra="forbid"``, which is right internally — a
    stage inventing a field should fail loudly rather than have data silently
    dropped. At the *provider* boundary it is wrong: a model that returns every
    required field correctly plus one invented extra would lose the entire
    result, and spend a repair attempt on it.

    So unknown keys are stripped and validation retried locally. This costs
    nothing, consumes no attempt, and cannot mask a real problem — every
    remaining error still surfaces.
    """
    try:
        return model.model_validate_json(payload)
    except ValidationError as first:
        extra_keys = {
            str(err["loc"][-1])
            for err in first.errors()
            if err["type"] == "extra_forbidden" and err.get("loc")
        }
        if not extra_keys or len(extra_keys) != len(first.errors()):
            raise

        data = json.loads(payload)
        if not isinstance(data, dict):
            raise
        return model.model_validate({k: v for k, v in data.items() if k not in extra_keys})


#: Literal members that mean "we do not know", in preference order. A degraded
#: object may only be filled with a member that *says* it carries no information.
_NEUTRAL_LITERALS = ("unknown", "unspecified", "mixed", "other", "none", "n/a", "na")


def _neutral_literal(name: str, args: tuple[Any, ...]) -> Any:
    """The member of a Literal that honestly means "no answer", or raise.

    The alternative — taking ``args[0]`` — is the bug this exists to prevent.
    Literal member order is a declaration accident, but every member is a
    *semantic* value that something downstream routes on. ``PedagogyProfile``
    happens to start with ``quantitative``, so a failed classification call used
    to route a poetry chapter through the quantitative strategy for the remaining
    eight stages, while the stage's own warning claimed it had defaulted to
    ``mixed``. Nothing in the package distinguished that from a real judgement.

    So: take a member that means "unknown" if the vocabulary offers one, and
    otherwise refuse. A caller that needs a degraded instance of such a model
    knows what its neutral value is and can pass ``degraded_value`` to
    :meth:`LLMClient.parse`; this generic helper does not and must not guess.
    """
    lowered = {str(arg).strip().casefold(): arg for arg in args}
    for candidate in _NEUTRAL_LITERALS:
        if candidate in lowered:
            return lowered[candidate]
    raise PlaceholderUnavailable(
        f"cannot build a degraded placeholder for {name!r}: none of its allowed "
        f"values {list(args)} means 'unknown', and picking one would invent a "
        f"semantic judgement the model never made. Pass an explicit "
        f"`degraded_value` to LLMClient.parse() for this output model."
    )


def _placeholders(model: type[BaseModel]) -> dict[str, Any]:
    """Typed empty values for every field, for a degraded instance.

    Constraints are deliberately ignored — validation has already failed, and the
    point is an object downstream code can read without exploding, clearly marked
    degraded, rather than one that satisfies constraints it never earned.

    *Semantics* are not ignored, which is the distinction that matters: an empty
    string, an empty list, and a zero all announce that nothing was extracted,
    whereas an arbitrary Literal member announces a decision. See
    :func:`_neutral_literal`.
    """
    from typing import get_args, get_origin

    values: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        if not info.is_required():
            values[name] = info.get_default(call_default_factory=True)
            continue

        annotation = info.annotation
        origin = get_origin(annotation) or annotation

        if origin in (list, set, tuple):
            values[name] = []
        elif origin is dict:
            values[name] = {}
        elif annotation is bool:
            values[name] = False
        elif annotation in (int, float):
            values[name] = 0
        elif get_origin(annotation) is Literal:
            values[name] = _neutral_literal(f"{model.__name__}.{name}", get_args(annotation))
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            values[name] = annotation.model_construct(**_placeholders(annotation))
        else:
            values[name] = ""
    return values


@dataclass
class LLMClient:
    routing: ProviderRouting
    adapters: dict[str, ProviderAdapter]
    budget: TokenBudget | None = None
    concurrency: int = 4
    calls: list[CallRecord] = field(default_factory=list)
    _semaphore: asyncio.Semaphore | None = None

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.concurrency)

    def _record(self, record: CallRecord) -> None:
        """Log one attempt and export it as a metric.

        A single choke point so a new call site cannot record an attempt and
        forget the metric — the four existing ones each handle a different
        failure mode, and they will not stay four forever. Failures are exported
        too: a stage that succeeds on its third try costs three calls, and a
        climbing retry rate is the earliest sign a provider or a prompt has
        degraded.
        """
        self.calls.append(record)
        metrics.record_llm_call(
            stage=record.stage,
            provider=record.provider,
            outcome=record.outcome,
            tokens_in=record.usage.tokens_in,
            tokens_out=record.usage.tokens_out,
            cost_usd=record.usage.cost_usd,
        )

    @property
    def usage(self) -> LLMUsage:
        """Aggregate across every attempt, including the ones that failed."""
        total = LLMUsage()
        for call in self.calls:
            total.tokens_in += call.usage.tokens_in
            total.tokens_out += call.usage.tokens_out
            total.tokens_cached += call.usage.tokens_cached
            total.cost_usd += call.usage.cost_usd
        return total

    def prompt_budget(
        self,
        stage: StageName | None = None,
        *,
        spec: ModelSpec | None = None,
        overhead_tokens: int = 0,
    ) -> int | None:
        """How many prompt tokens this route can actually spend, or ``None``.

        Providers with a tokens-per-minute cap count ``max_tokens`` as *reserved*
        budget rather than as measured usage, so the real constraint is
        ``prompt + max_tokens <= tpm_ceiling``. A stage that wants to *fit* rather
        than to be clamped after the fact has to know that number before it builds
        a prompt, and it is the only party that knows its own fixed overhead — the
        system prompt, the JSON schema, the evidence rules — so that comes in as
        ``overhead_tokens`` and what comes back is the room left for document text.

        ``None`` means the route declares no ceiling worth planning around; the
        caller keeps whatever default it had. That is deliberately distinct from
        ``0``, which means "this route has a ceiling and the overhead has already
        consumed it" — a real, reportable configuration problem.
        """
        resolved = spec or (self.routing.for_stage(stage) if stage else self.routing.default)
        if resolved.tpm_ceiling is None:
            return None
        room = resolved.tpm_ceiling - resolved.max_tokens - TPM_SAFETY_MARGIN - overhead_tokens
        return max(room, 0)

    async def parse[T: BaseModel](
        self,
        *,
        stage: StageName,
        output_model: type[T],
        system: str,
        user_content: str,
        spec: ModelSpec | None = None,
        degraded_value: T | None = None,
    ) -> LLMResult[T]:
        """Call the model and return a validated instance of ``output_model``.

        ``degraded_value`` is the caller's own fallback for the case where the
        schema could not be satisfied. Supply it whenever the output model has a
        required field whose value carries meaning that cannot be expressed as
        "empty" — a Literal routing key, most obviously. The generic placeholder
        builder refuses to invent those (see :func:`_neutral_literal`), so without
        one such a model raises instead of degrading, which is the correct
        outcome: the choice belongs to the stage that understands the vocabulary.
        """
        resolved = spec or self.routing.for_stage(stage)
        adapter = self.adapters.get(resolved.provider)
        if adapter is None:
            raise LLMProviderError(
                f"no adapter registered for provider {resolved.provider!r}; "
                f"available: {sorted(self.adapters)}"
            )

        if self.budget is not None:
            # Rough projection from prompt size plus the output ceiling. Only has
            # to be conservative enough to stop a runaway before it runs away.
            self.budget.check(estimate_tokens(system, user_content) + resolved.max_tokens)

        assert self._semaphore is not None
        async with self._semaphore:
            return await self._attempt_loop(
                stage=stage,
                adapter=adapter,
                spec=resolved,
                output_model=output_model,
                system=system,
                user_content=user_content,
                degraded_value=degraded_value,
            )

    async def _attempt_loop[T: BaseModel](
        self,
        *,
        stage: StageName,
        adapter: ProviderAdapter,
        spec: ModelSpec,
        output_model: type[T],
        system: str,
        user_content: str,
        degraded_value: T | None = None,
    ) -> LLMResult[T]:
        content = user_content
        repaired = False
        total = LLMUsage()
        last_error: str | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                raw = await adapter.complete(
                    spec=spec,
                    system=system,
                    user_content=content,
                    output_model=output_model,
                    extra={"stage": stage},
                )
            except ContentRefused as exc:
                self._record(
                    CallRecord(
                        stage, adapter.name, spec.model, attempt, "refused", LLMUsage(), str(exc)
                    )
                )
                # Not retryable: the same prompt refuses again. Degrade so the
                # remaining nine stages still produce a package.
                return self._degraded(
                    stage=stage,
                    output_model=output_model,
                    provider=adapter.name,
                    model=spec.model,
                    usage=total,
                    attempts=attempt,
                    issues=[f"provider refused: {exc}"],
                    degraded_value=degraded_value,
                )
            except LLMProviderError as exc:
                last_error = str(exc)
                self._record(
                    CallRecord(
                        stage, adapter.name, spec.model, attempt, "error", LLMUsage(), last_error
                    )
                )
                if not exc.retryable or attempt == MAX_ATTEMPTS:
                    raise
                # Prefer the provider's stated reopen time over a guess. Jitter is
                # still added: under fan-out several calls fail at the same
                # instant, and without it they all retry at the same instant too.
                stated = getattr(exc, "retry_after", None)
                if stated is not None:
                    delay = min(stated + random.random(), STATED_DELAY_CAP_S)
                else:
                    delay = min(2**attempt + random.random(), BACKOFF_CAP_S)
                await asyncio.sleep(delay)
                continue

            raw.usage.latency_ms = int((time.monotonic() - started) * 1000)
            total.tokens_in += raw.usage.tokens_in
            total.tokens_out += raw.usage.tokens_out
            total.tokens_cached += raw.usage.tokens_cached
            total.cost_usd += raw.usage.cost_usd
            if self.budget is not None:
                self.budget.record(raw.usage)

            try:
                payload = _extract_json(
                    raw.text,
                    expects_object=output_model.model_json_schema().get("type") == "object",
                )
                value = _validate_tolerantly(payload, output_model)
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)
                self._record(
                    CallRecord(
                        stage, adapter.name, raw.model, attempt, "error", raw.usage, last_error
                    )
                )
                if repaired or attempt == MAX_ATTEMPTS:
                    # One repair is the budget. A model that fails the schema twice
                    # is not going to succeed on a third identical nudge.
                    return self._degraded(
                        stage=stage,
                        output_model=output_model,
                        provider=adapter.name,
                        model=raw.model,
                        usage=total,
                        attempts=attempt,
                        issues=[f"schema validation failed: {last_error[:300]}"],
                        degraded_value=degraded_value,
                    )
                repaired = True
                content = self._repair_prompt(user_content, raw.text, last_error)
                continue

            self._record(
                CallRecord(
                    stage,
                    adapter.name,
                    raw.model,
                    attempt,
                    "repaired" if repaired else "ok",
                    raw.usage,
                )
            )
            return LLMResult[T](
                value=value,
                provider=adapter.name,  # type: ignore[arg-type]
                model=raw.model,
                usage=total,
                attempts=attempt,
                repaired=repaired,
            )

        raise LLMProviderError(f"exhausted {MAX_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    def _repair_prompt(original: str, bad_output: str, error: str) -> str:
        return (
            f"{original}\n\n"
            "--- CORRECTION REQUIRED ---\n"
            "Your previous response did not satisfy the required JSON schema.\n\n"
            f"Validator error:\n{error[:1500]}\n\n"
            f"Your previous output:\n{bad_output[:3000]}\n\n"
            "Return only corrected JSON matching the schema exactly. "
            "No prose, no explanation, no code fences."
        )

    def _degraded[T: BaseModel](
        self,
        *,
        stage: StageName,
        output_model: type[T],
        provider: str,
        model: str,
        usage: LLMUsage,
        attempts: int,
        issues: list[str],
        degraded_value: T | None = None,
    ) -> LLMResult[T]:
        """Minimal valid instance so the pipeline continues, flagged as degraded.

        The flag propagates into the validation report, so a shortfall is visible
        in the finished package rather than silently shipped as if it were fine.

        That propagation is why this records a ``CallRecord`` of its own. The
        per-stage provenance in the published package derives ``degraded`` from
        ``any(call.outcome == "degraded")``, and every path that reached here used
        to record only the *attempt* that failed — ``refused`` or ``error`` — and
        then return without recording the fallback. ``"degraded"`` was therefore
        never a recorded outcome anywhere in the system, so that flag was hardcoded
        false in every package ever published: a stage could fall back to a
        placeholder and the provenance would still say the run was clean. The
        record carries no usage, because the fallback cost nothing; it exists to
        state that a placeholder, not a model, produced this stage's output.
        """
        if degraded_value is not None:
            # The caller's own fallback. Preferred whenever it exists: it is the
            # only party that knows what "no answer" means for its vocabulary.
            value = degraded_value
        else:
            try:
                value = output_model.model_validate({})
            except ValidationError:
                # model_construct() with no values yields an object that looks
                # valid and then raises AttributeError on the first field access —
                # which would turn "degrade gracefully" into a crash two lines
                # later, in a different module, with a misleading traceback.
                # Supply a typed placeholder for every required field so the
                # object is genuinely usable and `degraded` is what callers react
                # to. May raise PlaceholderUnavailable; see _neutral_literal.
                value = output_model.model_construct(**_placeholders(output_model))

        self._record(
            CallRecord(
                stage,
                provider,
                model,
                attempts,
                "degraded",
                LLMUsage(),
                "; ".join(issues)[:300] or None,
            )
        )
        return LLMResult[T](
            value=value,
            provider=provider,  # type: ignore[arg-type]
            model=model,
            usage=usage,
            attempts=attempts,
            degraded=True,
            issues=issues,
        )


def build_adapters(
    *,
    openrouter_key: str | None = None,
    openrouter_base_url: str | None = None,
    groq_key: str | None = None,
    groq_base_url: str | None = None,
    gemini_key: str | None = None,
    anthropic_key: str | None = None,
    allow_anthropic: bool = False,
) -> dict[str, ProviderAdapter]:
    """Register only the providers that are both credentialled and permitted.

    A missing key means the adapter is absent, so naming that provider fails with
    a clear message at call time rather than a cryptic auth error later.

    Anthropic is deliberately gated on allow_anthropic rather than on key
    presence alone. A key sitting in the environment should not be sufficient to
    bill against it — that has to be an explicit decision.
    """
    from core.llm.providers.replay_provider import ReplayAdapter

    adapters: dict[str, ProviderAdapter] = {"replay": ReplayAdapter()}

    if openrouter_key:
        from core.llm.providers.openrouter_provider import (
            DEFAULT_BASE_URL,
            OpenRouterAdapter,
        )

        adapters["openrouter"] = OpenRouterAdapter(
            openrouter_key, openrouter_base_url or DEFAULT_BASE_URL
        )

    if groq_key:
        from core.llm.providers.groq_provider import DEFAULT_BASE_URL, GroqAdapter

        adapters["groq"] = GroqAdapter(groq_key, groq_base_url or DEFAULT_BASE_URL)

    if gemini_key:
        from core.llm.providers.gemini_provider import GeminiAdapter

        adapters["gemini"] = GeminiAdapter(gemini_key)

    if anthropic_key and allow_anthropic:
        from core.llm.providers.anthropic_provider import AnthropicAdapter

        adapters["anthropic"] = AnthropicAdapter(anthropic_key)

    return adapters


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
