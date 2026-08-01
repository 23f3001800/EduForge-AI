import { useEffect, useMemo, useState } from "react";
import { getJob, retryJob } from "../api";
import { isStageKey, stageIndex, STAGE_ORDER } from "../api/stages";
import { ApiError, type JobSnapshot } from "../api/types";
import { Badge } from "../components/ui/Badge";
import { Banner } from "../components/ui/Banner";
import { EmptyState } from "../components/ui/EmptyState";
import { EventLog } from "../components/run/EventLog";
import { Spinner } from "../components/ui/Spinner";
import { StageTimeline } from "../components/run/StageTimeline";
import { clearJobTimeline, useJobEvents } from "../hooks/useJobEvents";
import { Link, navigate, useRouteParams } from "../router/router";

function connectionLabel(state: string): { text: string; tone: "success" | "warning" | "neutral" } {
  switch (state) {
    case "open":
      return { text: "Live", tone: "success" };
    case "retrying":
      return { text: "Reconnecting…", tone: "warning" };
    case "closed":
      return { text: "Stream closed", tone: "neutral" };
    default:
      return { text: "Connecting…", tone: "neutral" };
  }
}

export function RunPage() {
  const { jobId } = useRouteParams();
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [snapshotError, setSnapshotError] = useState<ApiError | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [resetToken, setResetToken] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  // Fetch the authoritative snapshot on mount / after a retry. This also
  // guards against opening an SSE connection (which retries forever on a
  // network error) against a job id that simply does not exist.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    setSnapshotLoading(true);
    setSnapshotError(null);
    getJob(jobId)
      .then((snap) => {
        if (!cancelled) setSnapshot(snap);
      })
      .catch((err) => {
        if (!cancelled) setSnapshotError(err instanceof ApiError ? err : new ApiError(0, { error: { code: "network_error", message: "Could not reach the server." } }));
      })
      .finally(() => {
        if (!cancelled) setSnapshotLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, resetToken]);

  const foundJob = !snapshotLoading && !snapshotError;
  const { events, connectionState } = useJobEvents(foundJob ? jobId : null, resetToken);

  const latest = events[events.length - 1];
  const terminalEvent = latest && (latest.event === "completed" || latest.event === "failed") ? latest : null;

  // Re-pull the snapshot once the run reaches a terminal event, so warnings /
  // error / package_id come from the authoritative source rather than being
  // reconstructed from the SSE frame alone.
  useEffect(() => {
    if (!jobId || !terminalEvent) return;
    let cancelled = false;
    getJob(jobId)
      .then((snap) => {
        if (!cancelled) setSnapshot(snap);
      })
      .catch(() => {
        // Keep the last-known snapshot; the terminal SSE frame already told
        // the user what happened.
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminalEvent?.seq]);

  const derived = useMemo(() => {
    let currentIdx = -1;
    for (const event of events) {
      const stage = event.data.stage;
      if (isStageKey(stage)) {
        currentIdx = Math.max(currentIdx, stageIndex(stage));
      }
    }
    const completed = new Set<string>(snapshot?.completed_stages ?? []);
    const isDone = events.some((e) => e.event === "completed");
    const isFailed = events.some((e) => e.event === "failed");

    if (isDone) {
      STAGE_ORDER.forEach((s) => completed.add(s));
    } else {
      STAGE_ORDER.slice(0, Math.max(currentIdx, 0)).forEach((s) => completed.add(s));
    }

    const currentStage = !isDone && !isFailed && currentIdx >= 0 ? STAGE_ORDER[currentIdx] : null;
    const failedStage = isFailed && currentIdx >= 0 ? STAGE_ORDER[currentIdx] : null;
    const progress = latest?.data.progress ?? snapshot?.progress ?? 0;
    const message = latest && !isDone && !isFailed ? latest.data.message : undefined;

    return { completed, currentStage, failedStage, progress, message, isDone, isFailed };
  }, [events, snapshot, latest]);

  async function handleRetry() {
    if (!jobId) return;
    setRetrying(true);
    setRetryError(null);
    try {
      await retryJob(jobId);
      clearJobTimeline(jobId);
      setSnapshot(null);
      setResetToken((n) => n + 1);
    } catch (err) {
      setRetryError(err instanceof ApiError ? err.message : "Could not retry this job.");
    } finally {
      setRetrying(false);
    }
  }

  if (!jobId) return null;

  if (snapshotLoading) {
    return (
      <div className="ef-stack">
        <Spinner label="Loading job" />
      </div>
    );
  }

  if (snapshotError) {
    if (snapshotError.status === 404) {
      return (
        <EmptyState title="Job not found" tone="error">
          This run does not exist, or has expired. <Link to="/">Start a new one</Link>.
        </EmptyState>
      );
    }
    return (
      <EmptyState title="Could not load this job" tone="error">
        {snapshotError.message} <Link to="/">Start a new one</Link>.
      </EmptyState>
    );
  }

  const conn = connectionLabel(connectionState);
  const status = snapshot?.status ?? "queued";
  const succeededWithWarnings = status === "succeeded_partial" || (snapshot?.warnings.length ?? 0) > 0;

  return (
    <div className="ef-stack">
      <div className="ef-row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1 className="ef-page-title">Generating your package</h1>
          <p className="ef-page-subtitle ef-muted">Job {jobId}</p>
        </div>
        <Badge tone={conn.tone}>{conn.text}</Badge>
      </div>

      <div className="ef-card ef-stack">
        <div>
          <div className="ef-progress-bar" role="progressbar" aria-valuenow={derived.progress} aria-valuemin={0} aria-valuemax={100}>
            <div className="ef-progress-bar__fill" style={{ width: `${derived.progress}%` }} />
          </div>
          <div className="ef-row" style={{ justifyContent: "space-between", marginTop: "var(--ef-space-2)" }}>
            <span className="ef-muted">
              {derived.currentStage
                ? `Running: ${derived.message ? derived.message : "working…"}`
                : derived.isDone
                  ? "Done"
                  : derived.isFailed
                    ? "Stopped"
                    : "Waiting to start…"}
            </span>
            <strong>{derived.progress}%</strong>
          </div>
        </div>

        <StageTimeline completedStages={derived.completed} currentStage={derived.currentStage} failedStage={derived.failedStage} />
      </div>

      {derived.isFailed || status === "failed" ? (
        <Banner tone="danger" title="This run failed">
          {snapshot?.error ? (
            <p>
              <strong>{snapshot.error.type}:</strong> {snapshot.error.message}
            </p>
          ) : (
            <p>{terminalEvent?.data.message ?? "The pipeline stopped before publishing a package."}</p>
          )}
          <div className="ef-row" style={{ marginTop: "var(--ef-space-3)" }}>
            <button type="button" className="ef-btn ef-btn--secondary" onClick={handleRetry} disabled={retrying}>
              {retrying ? "Retrying…" : "Retry from last completed stage"}
            </button>
            <Link to="/" className="ef-btn ef-btn--secondary">
              Start a different document
            </Link>
          </div>
          {retryError ? <p className="ef-field__error">{retryError}</p> : null}
        </Banner>
      ) : null}

      {derived.isDone && snapshot?.package_id ? (
        <Banner tone={succeededWithWarnings ? "warning" : "success"} title={succeededWithWarnings ? "Package ready — with warnings" : "Package ready"}>
          {snapshot.warnings.length > 0 ? (
            <ul className="ef-stack" style={{ gap: "var(--ef-space-1)" }}>
              {snapshot.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          ) : (
            <p>Your teaching package is ready to review.</p>
          )}
          <div className="ef-row" style={{ marginTop: "var(--ef-space-3)" }}>
            <button
              type="button"
              className="ef-btn ef-btn--primary"
              onClick={() => navigate(`/packages/${snapshot.package_id}`)}
            >
              View package
            </button>
          </div>
        </Banner>
      ) : null}

      <div className="ef-card">
        <h2 className="ef-section-title" style={{ marginBottom: "var(--ef-space-3)" }}>
          Activity log
        </h2>
        <EventLog events={events} />
      </div>
    </div>
  );
}
