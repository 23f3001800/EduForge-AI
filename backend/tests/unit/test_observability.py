"""Structured logging, correlation, and metrics.

The value of this layer is entirely in what it lets you ask at 2am, so the tests
are about that: can I filter the log to one job, can I tell what a run spent, and
can telemetry itself take the service down.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from core.obs import metrics
from core.obs.context import bind, current_context, new_request_id
from core.obs.logging import JsonFormatter


@pytest.fixture(autouse=True)
def _clean_metrics() -> Any:
    """One test's counts must never leak into another's assertions."""
    metrics.reset()
    yield
    metrics.reset()


def _record(message: str = "hello", **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# ───────────────────────────────────────────────────────────────── logging


def test_a_log_line_is_one_json_object() -> None:
    payload = json.loads(JsonFormatter().format(_record()))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["ts"]


def test_extra_fields_are_queryable_top_level_keys() -> None:
    """`extra={"duration_ms": 812}` must not end up inside the message string."""
    payload = json.loads(JsonFormatter().format(_record(duration_ms=812, stage="publishing")))
    assert payload["duration_ms"] == 812
    assert payload["stage"] == "publishing"


def test_correlation_is_merged_without_the_caller_passing_it() -> None:
    """The whole point: a stage logs, and the job id is already there."""
    with bind(job_id="job-1", stage="knowledge-extraction"):
        payload = json.loads(JsonFormatter().format(_record()))
    assert payload["job_id"] == "job-1"
    assert payload["stage"] == "knowledge-extraction"


def test_an_exception_is_summarised_not_dumped() -> None:
    """A full traceback per line makes JSON logs unreadable."""
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record("failed")
        record.exc_info = sys.exc_info()
        payload = json.loads(JsonFormatter().format(record))

    assert payload["error_type"] == "ValueError"
    assert payload["error"] == "boom"


def test_a_log_line_survives_a_value_json_cannot_encode() -> None:
    """Logging must never be the thing that raises."""
    payload = json.loads(JsonFormatter().format(_record(obj=object())))
    assert "obj" in payload


# ─────────────────────────────────────────────────────────────── context


def test_binding_restores_the_outer_value_rather_than_clearing_it() -> None:
    """Nested binds are normal — a job binds, then each stage binds inside it."""
    with bind(job_id="outer", stage="s1"):
        with bind(stage="s2"):
            assert current_context()["stage"] == "s2"
        assert current_context()["stage"] == "s1"
        assert current_context()["job_id"] == "outer"
    assert current_context() == {}


def test_unset_correlation_is_omitted_not_null() -> None:
    assert "job_id" not in current_context()


async def test_correlation_does_not_leak_between_concurrent_jobs() -> None:
    """Several jobs run in one process and one thread; a global would interleave."""
    seen: dict[str, str] = {}

    async def run(job: str) -> None:
        with bind(job_id=job):
            await asyncio.sleep(0.01)
            seen[job] = current_context()["job_id"]

    await asyncio.gather(run("a"), run("b"), run("c"))
    assert seen == {"a": "a", "b": "b", "c": "c"}


def test_request_ids_are_short_enough_to_read_aloud() -> None:
    """This gets quoted in bug reports and read over a call."""
    request_id = new_request_id()
    assert 8 <= len(request_id) <= 16
    assert request_id != new_request_id()


# ─────────────────────────────────────────────────────────────── metrics


def test_counters_accumulate_by_label() -> None:
    metrics.record_request("GET", "/api/v1/jobs/{job_id}", 200, 0.1)
    metrics.record_request("GET", "/api/v1/jobs/{job_id}", 200, 0.2)
    metrics.record_request("GET", "/api/v1/jobs/{job_id}", 404, 0.05)

    rendered = metrics.render()
    assert (
        'eduforge_requests_total{method="GET",route="/api/v1/jobs/{job_id}",status="200"} 2'
        in rendered
    )
    assert 'status="404"' in rendered


def test_failed_model_attempts_are_counted_too() -> None:
    """A stage that succeeds on its third try cost three calls, not one."""
    for outcome in ("error", "repaired", "ok"):
        metrics.record_llm_call(
            stage="knowledge-extraction",
            provider="openrouter",
            outcome=outcome,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.0,
        )
    rendered = metrics.render()
    assert 'outcome="error"' in rendered
    assert 'eduforge_llm_tokens_total{direction="in",stage="knowledge-extraction"} 300' in rendered


def test_a_histogram_renders_buckets_sum_and_count() -> None:
    with metrics.observe_stage("publishing"):
        pass
    rendered = metrics.render()
    assert "eduforge_stage_duration_seconds_bucket" in rendered
    assert "eduforge_stage_duration_seconds_count" in rendered
    assert 'le="+Inf"' in rendered


def test_a_raising_stage_is_timed_and_labelled_as_an_error() -> None:
    with pytest.raises(RuntimeError), metrics.observe_stage("validation"):
        raise RuntimeError("boom")

    rendered = metrics.render()
    assert 'outcome="error"' in rendered
    assert 'stage="validation"' in rendered


def test_the_exposition_is_parseable_when_empty() -> None:
    """A scrape before any traffic must not return something Prometheus rejects."""
    assert metrics.render().strip() == ""


def test_every_metric_declares_help_and_type() -> None:
    """Prometheus tolerates their absence; a human reading /metrics does not."""
    metrics.record_job("succeeded")
    with metrics.observe_stage("publishing"):
        pass

    lines = metrics.render().splitlines()
    for name in ("eduforge_jobs_total", "eduforge_stage_duration_seconds"):
        help_line = next((ln for ln in lines if ln.startswith(f"# HELP {name} ")), None)
        assert help_line, f"{name} has no HELP"
        # A help string that just repeats the metric name helps nobody.
        assert help_line.removeprefix(f"# HELP {name} ").strip() != name
        assert any(ln.startswith(f"# TYPE {name} ") for ln in lines)
