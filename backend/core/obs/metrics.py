"""Metrics, in Prometheus text format.

A tiny in-process registry rather than ``prometheus-client``. The dependency is
declared in ``platform_deps``, which the deployed image deliberately does not
install, and this needs three metric types with no exemplars, no multiprocess
mode, and no pushgateway. Fifty lines of dict arithmetic against a wire format
that has been stable for a decade is a better trade than a dependency in the
serving image — and it keeps ``/metrics`` working in every profile, including CI.

What is measured is chosen to answer the questions this system actually raises at
2am: is it working, what is it spending, and where is the time going.

Counters and histograms only — no gauges beyond process info — because everything
worth alerting on here is a rate or a distribution. In-process means the numbers
reset when the app restarts and would be per-instance if this ever scaled out;
both are documented rather than papered over, and both stop mattering the moment
a real backend is put behind the same ``record_*`` calls.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager

__all__ = [
    "counters",
    "histograms",
    "observe_stage",
    "record_job",
    "record_llm_call",
    "record_request",
    "render",
    "reset",
]

#: Seconds. Tuned to this pipeline: model calls run 2-60s and whole stages can
#: run minutes, so the default Prometheus buckets (which top out at 10s) would
#: put almost everything in +Inf and tell us nothing.
_DURATION_BUCKETS = (0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600)

Key = tuple[str, tuple[tuple[str, str], ...]]

_lock = threading.Lock()
_counters: dict[Key, float] = defaultdict(float)
#: Cumulative counts per bucket bound (plus "+Inf"), not raw observations.
#: A process that lives for weeks records stage durations and request
#: latencies continuously; keeping every observation ever made in a
#: never-trimmed list is unbounded growth for the lifetime of the process.
#: Bucket counters are the standard Prometheus representation for exactly
#: this reason — O(len(_DURATION_BUCKETS)) per series forever, regardless of
#: how many observations were made.
_histogram_buckets: dict[Key, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_histogram_sum: dict[Key, float] = defaultdict(float)
_histogram_count: dict[Key, int] = defaultdict(int)

_HELP = {
    "eduforge_requests_total": ("counter", "HTTP requests by method, route and status."),
    "eduforge_request_duration_seconds": ("histogram", "HTTP request latency."),
    "eduforge_jobs_total": ("counter", "Pipeline jobs by terminal status."),
    "eduforge_stage_duration_seconds": ("histogram", "Stage execution time."),
    "eduforge_llm_calls_total": ("counter", "Model calls by stage, provider and outcome."),
    "eduforge_llm_tokens_total": ("counter", "Tokens by stage and direction."),
    "eduforge_llm_cost_usd_total": ("counter", "Spend by provider."),
}


def _key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


def _inc(name: str, labels: dict[str, str], value: float = 1.0) -> None:
    with _lock:
        _counters[(name, _key(labels))] += value


def _observe(name: str, labels: dict[str, str], value: float) -> None:
    key = (name, _key(labels))
    with _lock:
        buckets = _histogram_buckets[key]
        # Prometheus buckets are cumulative: a bound counts every observation
        # at or below it, so one observation increments every bound it clears,
        # not just the tightest one.
        for bound in _DURATION_BUCKETS:
            if value <= bound:
                buckets[str(bound)] += 1
        buckets["+Inf"] += 1
        _histogram_sum[key] += value
        _histogram_count[key] += 1


def record_request(method: str, route: str, status: int, seconds: float) -> None:
    """One HTTP request.

    ``route`` must be the *template* (``/api/v1/jobs/{job_id}``), never the
    resolved path: labelling by resolved path would mint a new time series per
    job id and blow up the registry within a day.
    """
    labels = {"method": method, "route": route, "status": str(status)}
    _inc("eduforge_requests_total", labels)
    _observe("eduforge_request_duration_seconds", {"method": method, "route": route}, seconds)


def record_job(status: str) -> None:
    _inc("eduforge_jobs_total", {"status": status})


def record_llm_call(
    *, stage: str, provider: str, outcome: str, tokens_in: int, tokens_out: int, cost_usd: float
) -> None:
    """One model attempt, successful or not.

    Failed attempts are counted too — a stage that succeeds on its third try
    costs three calls, and a retry rate climbing is the earliest signal that a
    provider or a prompt has degraded.
    """
    _inc("eduforge_llm_calls_total", {"stage": stage, "provider": provider, "outcome": outcome})
    if tokens_in:
        _inc("eduforge_llm_tokens_total", {"stage": stage, "direction": "in"}, tokens_in)
    if tokens_out:
        _inc("eduforge_llm_tokens_total", {"stage": stage, "direction": "out"}, tokens_out)
    if cost_usd:
        _inc("eduforge_llm_cost_usd_total", {"provider": provider}, cost_usd)


@contextmanager
def observe_stage(stage: str) -> Iterator[None]:
    """Time a stage, recording whether it raised."""
    started = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        _observe(
            "eduforge_stage_duration_seconds",
            {"stage": stage, "outcome": outcome},
            time.perf_counter() - started,
        )


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in labels)
    return "{" + inner + "}"


def render() -> str:
    """The registry in Prometheus text exposition format."""
    with _lock:
        counters = dict(_counters)
        buckets = {k: dict(v) for k, v in _histogram_buckets.items()}
        sums = dict(_histogram_sum)
        counts = dict(_histogram_count)

    lines: list[str] = []
    emitted: set[str] = set()

    def header(name: str) -> None:
        if name in emitted:
            return
        kind, help_text = _HELP.get(name, ("counter", name))
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        emitted.add(name)

    for (name, labels), value in sorted(counters.items()):
        header(name)
        lines.append(f"{name}{_format_labels(labels)} {value}")

    for key in sorted(buckets):
        name, labels = key
        header(name)
        series = buckets[key]
        for bound in _DURATION_BUCKETS:
            count = series.get(str(bound), 0)
            lines.append(f"{name}_bucket{_format_labels((*labels, ('le', str(bound))))} {count}")
        lines.append(
            f"{name}_bucket{_format_labels((*labels, ('le', '+Inf')))} {series.get('+Inf', 0)}"
        )
        lines.append(f"{name}_sum{_format_labels(labels)} {sums.get(key, 0.0)}")
        lines.append(f"{name}_count{_format_labels(labels)} {counts.get(key, 0)}")

    return "\n".join(lines) + "\n"


def counters() -> dict[Key, float]:
    """A snapshot of every counter.

    A copy, taken under the lock: handing out the live dict would let a caller
    iterate it while a request thread mutates it, which is a RuntimeError in the
    middle of rendering a page.
    """
    with _lock:
        return dict(_counters)


def histograms() -> dict[Key, dict[str, float]]:
    """A snapshot of every series' exact count and sum, same copying rule.

    Individual observations are not retained (see the bucket-counter comment
    above), so this reports the two numbers that survive aggregation exactly —
    enough to compute a mean, which is the only thing any caller has ever
    needed from it. The per-bucket distribution is in ``render()``.
    """
    with _lock:
        return {
            key: {"count": float(_histogram_count[key]), "sum": _histogram_sum[key]}
            for key in _histogram_count
        }


def reset() -> None:
    """Clear the registry. For tests — one test's counts must not leak into another."""
    with _lock:
        _counters.clear()
        _histogram_buckets.clear()
        _histogram_sum.clear()
        _histogram_count.clear()
