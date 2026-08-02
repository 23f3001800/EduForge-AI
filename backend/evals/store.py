"""Historical evaluation storage, and what can honestly be said from it.

Scores are only interesting in a series. One run scoring 93 tells you nothing;
93 after a month at 97 tells you a change broke something. So every evaluation is
appended here, and this module answers the two questions a series can support:
*where does this run sit against the ones before it*, and *did something get
worse*.

**SQLite, from the standard library.** No new dependency, one file, and real
queries — which matters because the interesting questions are grouped ones
("median assessment-generation score for quantitative packages"). The rows are
denormalised on purpose: the full report goes in as JSON alongside the columns
worth indexing, so a schema change to the report never migrates this table.

**The honest part is the gate.** Regression detection over three runs is
astrology. Comparing a run against a baseline requires enough history for the
baseline to mean anything, and against *comparable* history — a narrative package
does not regress because it scores below a corpus of quantitative ones. Both
conditions are checked, and when either fails the answer is
``insufficient_history`` with the count, not a verdict. That is the same rule the
metric layer follows: say what is not known rather than produce a number that
reads as if it were.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.framework import StageEvaluation, aggregate

__all__ = [
    "MIN_BASELINE_RUNS",
    "REGRESSION_POINTS",
    "EvaluationRecord",
    "EvaluationStore",
    "compare",
]

#: Below this, a baseline is a rumour. Five runs is not a lot either, but it is
#: the point at which a median stops being decided by a single outlier.
MIN_BASELINE_RUNS = 5

#: How far a stage may fall below its baseline median before it is called a
#: regression. Chosen to sit outside the run-to-run spread these metrics show on
#: unchanged code — most are deterministic and move 0, and the few that respond
#: to model sampling move a few points.
REGRESSION_POINTS = 5.0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class EvaluationRecord:
    """One evaluation, flattened enough to query and complete enough to re-render."""

    run_id: str
    package_id: str
    subject: str
    grade_band: str
    profile: str
    overall: float | None
    confidence: float
    stage_scores: dict[str, float | None]
    evaluated_at: str = field(default_factory=_now)
    app_version: str = "unknown"
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        package: dict[str, Any],
        evaluations: Sequence[StageEvaluation],
        payload: dict[str, Any] | None = None,
    ) -> EvaluationRecord:
        classification = package.get("classification") or {}
        generator = package.get("generator") or {}
        rolled = aggregate(evaluations)
        return cls(
            run_id=run_id,
            package_id=str(package.get("tkp_id") or "unknown"),
            subject=str(classification.get("subject") or "unknown"),
            grade_band=str(classification.get("grade_band") or "unknown"),
            profile=str(classification.get("pedagogy_profile") or "mixed"),
            overall=rolled["score"],
            confidence=float(rolled["confidence"]),
            stage_scores={e.stage: e.score for e in evaluations},
            app_version=str(generator.get("app_version") or "unknown"),
            payload=payload or {},
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "package_id": self.package_id,
            "subject": self.subject,
            "grade_band": self.grade_band,
            "profile": self.profile,
            "overall": self.overall,
            "confidence": round(self.confidence, 4),
            "stage_scores": self.stage_scores,
            "evaluated_at": self.evaluated_at,
            "app_version": self.app_version,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    run_id       TEXT PRIMARY KEY,
    package_id   TEXT NOT NULL,
    subject      TEXT NOT NULL,
    grade_band   TEXT NOT NULL,
    profile      TEXT NOT NULL,
    overall      REAL,
    confidence   REAL NOT NULL,
    evaluated_at TEXT NOT NULL,
    app_version  TEXT NOT NULL,
    stage_scores TEXT NOT NULL,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evaluations_profile ON evaluations (profile, evaluated_at);
CREATE INDEX IF NOT EXISTS ix_evaluations_package ON evaluations (package_id);
"""


class EvaluationStore:
    """Append-only history of evaluations, and the aggregates drawn from it.

    ``path=None`` gives an in-memory database, which is what the tests and a
    fresh container use. Nothing here fails if the history is empty — every
    method has a defined answer for "no runs yet", because the first run is the
    common case and must not error.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path) if self.path else ":memory:",
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ────────────────────────────────────────────────────────────────── write

    def record(self, record: EvaluationRecord) -> EvaluationRecord:
        """Store one evaluation. Re-recording the same run replaces it."""
        self._conn.execute(
            "INSERT OR REPLACE INTO evaluations "
            "(run_id, package_id, subject, grade_band, profile, overall, confidence, "
            " evaluated_at, app_version, stage_scores, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id,
                record.package_id,
                record.subject,
                record.grade_band,
                record.profile,
                record.overall,
                record.confidence,
                record.evaluated_at,
                record.app_version,
                json.dumps(record.stage_scores),
                json.dumps(record.payload),
            ),
        )
        self._conn.commit()
        return record

    # ─────────────────────────────────────────────────────────────────── read

    def _row(self, row: sqlite3.Row) -> EvaluationRecord:
        return EvaluationRecord(
            run_id=row["run_id"],
            package_id=row["package_id"],
            subject=row["subject"],
            grade_band=row["grade_band"],
            profile=row["profile"],
            overall=row["overall"],
            confidence=row["confidence"],
            stage_scores=json.loads(row["stage_scores"]),
            evaluated_at=row["evaluated_at"],
            app_version=row["app_version"],
            payload=json.loads(row["payload"]),
        )

    def get(self, run_id: str) -> EvaluationRecord | None:
        row = self._conn.execute("SELECT * FROM evaluations WHERE run_id = ?", (run_id,)).fetchone()
        return self._row(row) if row else None

    def history(
        self,
        *,
        profile: str | None = None,
        subject: str | None = None,
        limit: int = 50,
    ) -> list[EvaluationRecord]:
        """Most recent first — the order a trend chart reads backwards from."""
        where, params = [], []
        if profile:
            where.append("profile = ?")
            params.append(profile)
        if subject:
            where.append("subject = ?")
            params.append(subject)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn.execute(
            f"SELECT * FROM evaluations {clause} ORDER BY evaluated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    def count(self, *, profile: str | None = None) -> int:
        if profile:
            sql = "SELECT COUNT(*) FROM evaluations WHERE profile = ?"
            return int(self._conn.execute(sql, (profile,)).fetchone()[0])
        return int(self._conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0])

    # ──────────────────────────────────────────────────────────── benchmarks

    def benchmark(self, *, profile: str | None = None, exclude: str = "") -> dict[str, Any]:
        """Distribution of scores across history, for positioning one run in it.

        Median rather than mean: with a handful of runs, one failed job at 40
        drags a mean somewhere no individual run has ever been. Percentiles are
        reported alongside so the spread is visible rather than implied.

        ``exclude`` drops a run id — used when positioning a run against its own
        history, which must not include itself.
        """
        records = [r for r in self.history(profile=profile, limit=1000) if r.run_id != exclude]
        overalls = [r.overall for r in records if r.overall is not None]

        by_stage: dict[str, list[float]] = {}
        for record in records:
            for stage, score in record.stage_scores.items():
                if score is not None:
                    by_stage.setdefault(stage, []).append(float(score))

        return {
            "profile": profile or "all",
            "runs": len(records),
            "sufficient": len(records) >= MIN_BASELINE_RUNS,
            "overall": _distribution(overalls),
            "stages": {stage: _distribution(values) for stage, values in sorted(by_stage.items())},
        }


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "p25": None, "p75": None}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": round(statistics.median(ordered), 2),
        "min": round(ordered[0], 2),
        "max": round(ordered[-1], 2),
        "p25": round(_percentile(ordered, 0.25), 2),
        "p75": round(_percentile(ordered, 0.75), 2),
    }


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Nearest-rank percentile. Exact, and defined for n=1 — which matters,
    because a store with one run is a store this will be asked about."""
    if not ordered:
        raise ValueError("no values")
    index = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[index]


def compare(record: EvaluationRecord, benchmark: dict[str, Any]) -> dict[str, Any]:
    """Position one run against a baseline, or decline to.

    Returns ``status`` of ``insufficient_history``, ``regression``, or ``ok``.
    The first is not a failure mode to be smoothed over — it is the correct
    answer for most of a project's life, and reporting it plainly stops a
    dashboard from showing a green tick that means nothing.
    """
    if not benchmark.get("sufficient"):
        return {
            "status": "insufficient_history",
            "runs": benchmark.get("runs", 0),
            "needed": MIN_BASELINE_RUNS,
            "detail": (
                f"{benchmark.get('runs', 0)} comparable run(s) on record; a baseline needs at "
                f"least {MIN_BASELINE_RUNS} before a fall in score can be told apart from "
                "run-to-run variation."
            ),
            "regressions": [],
            "improvements": [],
        }

    regressions: list[dict[str, Any]] = []
    improvements: list[dict[str, Any]] = []
    for stage, score in record.stage_scores.items():
        stats = benchmark["stages"].get(stage)
        if score is None or not stats or stats["median"] is None:
            continue
        delta = float(score) - float(stats["median"])
        entry = {
            "stage": stage,
            "score": round(float(score), 2),
            "baseline_median": stats["median"],
            "delta": round(delta, 2),
        }
        if delta <= -REGRESSION_POINTS:
            regressions.append(entry)
        elif delta >= REGRESSION_POINTS:
            improvements.append(entry)

    overall_stats = benchmark["overall"]
    overall_delta = (
        None
        if record.overall is None or overall_stats["median"] is None
        else round(record.overall - overall_stats["median"], 2)
    )

    return {
        "status": "regression" if regressions else "ok",
        "runs": benchmark["runs"],
        "overall_delta": overall_delta,
        "threshold": REGRESSION_POINTS,
        "detail": (
            f"{len(regressions)} stage(s) fell {REGRESSION_POINTS:.0f}+ points below their "
            f"baseline median over {benchmark['runs']} comparable runs."
            if regressions
            else f"No stage fell {REGRESSION_POINTS:.0f}+ points below its baseline median "
            f"over {benchmark['runs']} comparable runs."
        ),
        "regressions": sorted(regressions, key=lambda e: e["delta"]),
        "improvements": sorted(improvements, key=lambda e: -e["delta"]),
    }


def trend(records: Iterable[EvaluationRecord]) -> list[dict[str, Any]]:
    """Oldest-first series for charting. Runs with no measurable score are kept
    as gaps rather than dropped — a run that measured nothing is itself signal."""
    return [
        {
            "run_id": r.run_id,
            "evaluated_at": r.evaluated_at,
            "overall": r.overall,
            "confidence": round(r.confidence, 4),
            "profile": r.profile,
            "subject": r.subject,
        }
        for r in sorted(records, key=lambda r: r.evaluated_at)
    ]
