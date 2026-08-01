"""Runtime statistics, as JSON, for the analytics screens.

`/metrics` already exposes all of this in Prometheus text format, which is the
right thing for a scraper and the wrong thing for a chart component — parsing
exposition format in the browser to draw a bar chart would be a silly amount of
client code for data the server can hand over shaped.

Everything here is **measured**, never modelled. Where the system does not track
something the UI would like to plot, this returns an empty series and the chart
says so, because a plausible-looking invented trend is worse than a blank panel:
one of them is honest about what we know.

In-process and therefore reset by a restart, exactly like the registry behind
`/metrics`. That is stated in the payload itself (`since_restart`) so a screen
can say "since the last restart" rather than implying lifetime totals.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import get_store
from core.obs import metrics
from core.storage.base import Store

router = APIRouter(tags=["stats"])

_STARTED = time.time()


def _counter_totals(prefix: str, label: str) -> dict[str, float]:
    """Sum one counter family, grouped by a single label."""
    totals: dict[str, float] = defaultdict(float)
    for (name, labels), value in metrics.counters().items():
        if name != prefix:
            continue
        key = dict(labels).get(label)
        if key is not None:
            totals[key] += value
    return dict(totals)


def _histogram_stats(name: str, label: str) -> dict[str, dict[str, float]]:
    """Count and mean per label value, from the recorded observations."""
    out: dict[str, dict[str, float]] = {}
    for (metric, labels), values in metrics.histograms().items():
        if metric != name or not values:
            continue
        key = dict(labels).get(label)
        if key is None:
            continue
        bucket = out.setdefault(key, {"count": 0.0, "total_seconds": 0.0})
        bucket["count"] += len(values)
        bucket["total_seconds"] += sum(values)
    for bucket in out.values():
        bucket["mean_seconds"] = (
            bucket["total_seconds"] / bucket["count"] if bucket["count"] else 0.0
        )
    return out


@router.get("/stats")
async def get_stats(store: Store = Depends(get_store)) -> dict[str, Any]:
    """What this instance has actually done since it started."""
    jobs = _counter_totals("eduforge_jobs_total", "status")
    succeeded = jobs.get("succeeded", 0.0)
    failed = jobs.get("failed", 0.0)
    finished = succeeded + failed

    llm_calls = _counter_totals("eduforge_llm_calls_total", "outcome")
    attempts = sum(llm_calls.values())
    clean = llm_calls.get("ok", 0.0)

    packages = await store.list_packages() if hasattr(store, "list_packages") else []
    subjects: dict[str, int] = defaultdict(int)
    profiles: dict[str, int] = defaultdict(int)
    languages: dict[str, int] = defaultdict(int)
    for record in packages:
        classification = record.tkp.get("classification") or {}
        subjects[str(classification.get("subject") or "Unknown")] += 1
        profiles[str(classification.get("pedagogy_profile") or "mixed")] += 1
        languages[str(record.tkp.get("language") or "en")] += 1

    return {
        "since_restart": True,
        "uptime_seconds": round(time.time() - _STARTED, 1),
        "jobs": {
            "succeeded": succeeded,
            "failed": failed,
            "finished": finished,
            # None rather than 0 when nothing has run: a success rate of "0%"
            # for a system that has processed nothing is a lie a chart will
            # happily draw.
            "success_rate": (succeeded / finished) if finished else None,
        },
        "stages": _histogram_stats("eduforge_stage_duration_seconds", "stage"),
        "requests": _counter_totals("eduforge_requests_total", "route"),
        "llm": {
            "attempts": attempts,
            "by_outcome": llm_calls,
            "retry_rate": ((attempts - clean) / attempts) if attempts else None,
            "tokens": _counter_totals("eduforge_llm_tokens_total", "direction"),
            "cost_usd": sum(_counter_totals("eduforge_llm_cost_usd_total", "provider").values()),
        },
        "packages": {
            "total": len(packages),
            "by_subject": dict(subjects),
            "by_profile": dict(profiles),
            "by_language": dict(languages),
        },
    }
