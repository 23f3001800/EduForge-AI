"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  Coins,
  Loader2,
  ShieldAlert,
  WifiOff,
  X,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { getJob, retryJob, type JobSnapshot } from "@/lib/api";
import { cn } from "@/lib/cn";
import { describeError } from "@/lib/errors";
import { formatCost, formatTokens } from "@/lib/format";
import { expectedSeconds, STAGE_BLURBS, STAGE_LABELS, STAGE_ORDER, type StageKey } from "@/lib/stages";
import { clearTimeline, useJobStream, type StreamEvent } from "@/lib/use-job-stream";

type StageState = "pending" | "running" | "done" | "warned" | "failed";

/**
 * How long a run may report nothing at all before this screen says so.
 *
 * Distinct from the per-stage budget below, and it exists because the two are
 * different failures: a stage that overruns is usually a queued free-tier model,
 * whereas a job that has not emitted a single event is not running at all.
 */
const SILENT_BEFORE_FIRST_EVENT_SECONDS = 45;

/** Statuses after which the server has nothing left to say. Mirrors `backend/api/routes/events.py`. */
const TERMINAL_STATUSES = new Set<string>([
  "succeeded",
  "succeeded_partial",
  "failed",
  "cancelled",
]);

/** Read a value that arrived over the wire as JSON and may be anything. */
function asString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

/**
 * The failure, as a sentence.
 *
 * Returns null rather than a placeholder when the snapshot carries no error, so
 * the caller can decide what to say instead — the one thing it must never do is
 * render an empty red box.
 */
function errorText(error: JobSnapshot["error"] | undefined): string | null {
  if (!error || typeof error !== "object") return null;
  const type = asString((error as { type?: unknown }).type);
  const message = asString((error as { message?: unknown }).message);
  if (type && message) return `${type}: ${message}`;
  return message ?? type;
}

/** The last thing the stream said before it stopped. Often the only explanation. */
function lastFailureMessage(events: StreamEvent[]): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.level === "error" || event.stage === "failed") {
      const message = asString(event.message);
      if (message) return message;
    }
  }
  return null;
}

/**
 * Live progress.
 *
 * The job id is a query parameter rather than a path segment because the app is
 * a static export: a path like /run/<uuid> has no pre-built HTML, whereas a
 * query string is the same document for every job. A refresh still resumes —
 * the query survives it, and the stream reconnects from the stored cursor.
 *
 * Two sources of truth, deliberately merged rather than ranked. SSE carries the
 * detail and arrives instantly; the polled snapshot is the only thing that
 * arrives at all when EventSource is blocked, which a corporate proxy and some
 * mobile networks both do. Reading only the stream left the bar at 0% for a
 * whole run and then jumped it to 100%.
 */
function RunView() {
  const params = useSearchParams();
  const jobId = params?.get("job") ?? null;
  const { events, progress: streamProgress, connection, terminal } = useJobStream(jobId);
  const [stageStartedAt, setStageStartedAt] = useState<number>(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  // Poll the snapshot as a backstop. SSE carries the detail, but a client that
  // arrives after the run finished — or whose stream never opened — must still
  // learn the outcome.
  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: Boolean(jobId),
    // Stopped on the snapshot's own status as well as on the stream's terminal
    // frame: when EventSource never opened, `terminal` stays null forever and a
    // finished run would otherwise be polled every five seconds for as long as
    // the tab stayed open.
    refetchInterval: (query) =>
      terminal || TERMINAL_STATUSES.has(query.state.data?.status ?? "") ? false : 5000,
  });

  const status = job?.status ?? null;
  const failed = terminal === "failed" || status === "failed";
  const cancelled = status === "cancelled";
  const partial = status === "succeeded_partial";
  const done = !failed && !cancelled && (terminal === "completed" || status === "succeeded" || partial);
  const finished = done || failed || cancelled;

  const completedEvent = events.find((event) => event.stage === "completed");
  // The terminal frame carries the package id, so the "Open package" button
  // works in the seconds before the next poll lands.
  const packageId = job?.package_id ?? asString(completedEvent?.package_id);
  // …and the validation status, which is what made the run partial.
  const validationStatus = asString(completedEvent?.status);
  const partialLikely = partial || (done && validationStatus !== null && validationStatus !== "pass");

  const progress = Math.max(streamProgress, job?.progress ?? 0, done ? 100 : 0);

  const stageStates = useMemo(() => {
    const states = new Map<StageKey, StageState>();
    for (const stage of STAGE_ORDER) states.set(stage, "pending");

    // 1. The snapshot first. `completed_stages` is the checkpoint list, which is
    //    authoritative about what finished and, unlike the stream, survives a
    //    blocked EventSource.
    for (const stage of job?.completed_stages ?? []) {
      if (states.has(stage as StageKey)) states.set(stage as StageKey, "done");
    }
    const snapshotStage =
      job?.current_stage && states.has(job.current_stage as StageKey)
        ? (job.current_stage as StageKey)
        : null;

    // 2. Then the events, which add the detail the snapshot has no room for:
    //    which stages warned, and which one is live right now.
    let eventStage: StageKey | null = null;
    for (const event of events) {
      const key = event.stage as StageKey;
      if (!states.has(key)) continue;
      if (event.level === "warning" || event.level === "error") {
        states.set(key, "warned");
      } else if (states.get(key) === "pending") {
        states.set(key, "running");
      }
      eventStage = key;
    }

    // Whichever source is further along wins: the stream is normally ahead of a
    // five-second poll, but it is also the one that can be missing entirely.
    const candidates = [snapshotStage, eventStage].filter((s): s is StageKey => s !== null);
    const active = candidates.reduce<StageKey | null>(
      (best, stage) =>
        best === null || STAGE_ORDER.indexOf(stage) > STAGE_ORDER.indexOf(best) ? stage : best,
      null,
    );

    // Everything before the newest stage has necessarily finished — the
    // pipeline is linear, so "we are on stage 6" means 1-5 completed.
    if (active) {
      const index = STAGE_ORDER.indexOf(active);
      STAGE_ORDER.slice(0, index).forEach((stage) => {
        if (states.get(stage) === "pending" || states.get(stage) === "running") {
          states.set(stage, "done");
        }
      });
      if (states.get(active) === "pending") states.set(active, "running");
    }

    if (done) {
      STAGE_ORDER.forEach((stage) => {
        if (states.get(stage) !== "warned") states.set(stage, "done");
      });
    } else if ((failed || cancelled) && active && states.get(active) !== "done") {
      // Mark *where* it stopped. A red bar with ten identical grey rows tells a
      // reader the run failed but not which stage to look at.
      states.set(active, "failed");
    }

    return { states, active };
  }, [events, job?.completed_stages, job?.current_stage, done, failed, cancelled]);

  // Reset the per-stage clock whenever the active stage changes, so "slow"
  // measures this stage rather than the whole run.
  useEffect(() => {
    setStageStartedAt(Date.now());
  }, [stageStates.active]);

  useEffect(() => {
    if (finished) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [finished]);

  const elapsedOnStage = (now - stageStartedAt) / 1000;
  // The old condition required a current stage, which disabled the detector in
  // precisely the case it exists for: a job that hangs before emitting anything
  // has no current stage, so it never warned.
  const budget = stageStates.active
    ? expectedSeconds(stageStates.active) * 2.5
    : SILENT_BEFORE_FIRST_EVENT_SECONDS;
  const slow = !finished && elapsedOnStage > budget;

  async function retry() {
    // Guarded rather than merely relabelled: a second POST while the first is in
    // flight comes back 409 `job_not_retryable`, which would toast an error for
    // a retry that is actually working.
    if (!jobId || retrying) return;
    setRetrying(true);
    setRetryError(null);
    try {
      await retryJob(jobId);
      // The stored timeline ends in a terminal frame; left in place, the resumed
      // run would restore as already finished.
      clearTimeline(jobId);
      window.location.reload();
    } catch (error) {
      // Rendered in place rather than toasted: this is the outcome of the only
      // action on the screen, it needs to persist until it is read, and a toast
      // here would have pulled the toast library into this route's first load
      // for one error path.
      const { title, body } = describeError(error);
      setRetryError(`${title} — ${body}`);
      setRetrying(false);
    }
  }

  const retryFailure = retryError ? (
    <p role="alert" className="mt-2 text-sm font-medium text-danger">
      {retryError}
    </p>
  ) : null;

  if (!jobId) {
    return (
      <EmptyState title="No run selected">
        Start one from the{" "}
        <Link className="text-accent hover:underline" href="/upload">
          upload page
        </Link>
        .
      </EmptyState>
    );
  }

  const headline = done
    ? partialLikely
      ? "Package ready, with problems"
      : "Package ready"
    : failed
      ? "This run failed"
      : cancelled
        ? "This run was cancelled"
        : "Building your package";

  const usage = job?.usage;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{headline}</h1>
          <p className="mt-1 break-all font-mono text-xs text-fg-faint">{jobId}</p>
        </div>
        {done && packageId ? (
          <Button asChild>
            <Link href={`/packages?id=${packageId}`}>
              Open package <ChevronRight />
            </Link>
          </Button>
        ) : null}
      </div>

      <Card>
        <CardContent className="pt-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">
              {done ? "Complete" : failed || cancelled ? "Stopped" : "In progress"}
            </span>
            <span className="font-mono tabular-nums text-fg-muted">{progress}%</span>
          </div>
          <div
            className="mt-2 h-2 overflow-hidden rounded-full bg-fg/10"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Overall progress"
          >
            <motion.div
              className={cn(
                "h-full rounded-full",
                failed || cancelled ? "bg-danger" : partialLikely ? "bg-warning" : "bg-accent",
              )}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.4, ease: "easeOut" }}
            />
          </div>

          {/* Politely announced, so a screen reader learns of stage changes
              without every heartbeat interrupting the user. */}
          <p className="sr-only" aria-live="polite">
            {headline}. {progress}% complete
            {stageStates.active ? `, ${STAGE_LABELS[stageStates.active]}` : ""}
          </p>

          {connection === "connecting" && !finished ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-fg-muted">
              <WifiOff className="size-4 shrink-0" aria-hidden /> Reconnecting to the live stream —
              progress below still updates from the server every few seconds, and the run keeps
              going either way.
            </p>
          ) : null}

          {slow ? (
            <p className="mt-3 flex items-start gap-2 text-sm text-warning">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              {stageStates.active ? (
                <span>
                  This stage is taking longer than usual. Free-tier models queue under load;
                  nothing is lost while it waits.
                </span>
              ) : (
                <span>
                  This run has not reported any progress yet. It may still be queued behind another
                  job — nothing is lost, but if this persists the worker may not have picked it up.
                </span>
              )}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {/* Always rendered when the run stopped, never conditional on the snapshot
          having resolved or on `job.error` being populated. A terminal event can
          arrive before the poll does, and a red bar with no explanation is the
          worst state this screen can be in. */}
      {failed || cancelled ? (
        <ErrorState
          title={cancelled ? "This run was cancelled" : "This run failed"}
          onRetry={retry}
          retryLabel={retrying ? "Retrying…" : "Retry from the last completed stage"}
        >
          {errorText(job?.error) ??
            lastFailureMessage(events) ??
            (cancelled
              ? "It was stopped before it produced a package. Retrying resumes from the last completed stage."
              : "The server did not report a reason. Retrying resumes from the last completed stage, so nothing that already succeeded is repeated.")}
          {stageStates.active ? (
            <p className="mt-1">
              It stopped during <span className="font-medium">{STAGE_LABELS[stageStates.active]}</span>.
            </p>
          ) : null}
          {retryFailure}
        </ErrorState>
      ) : null}

      {/* `succeeded_partial`: the run finished and there is a package, but
          validation did not fully pass. Both halves have to be said — linking to
          the package without the caveat overstates it, and the caveat without
          the link strands work that was done. */}
      {done && partialLikely ? (
        <section
          aria-labelledby="partial"
          className="rounded-lg border border-warning/30 bg-warning-subtle p-5"
        >
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden />
            <div className="min-w-0 flex-1">
              <h2 id="partial" className="font-medium">
                Validation did not fully pass
              </h2>
              <p className="mt-1 text-sm text-fg-muted">
                The package was built and you can open it, but the validator
                {validationStatus === "fail"
                  ? " rejected it"
                  : " raised problems it could not clear"}
                . Read the Validation tab before teaching from it. Retrying re-runs the stages after
                the last checkpoint rather than the whole pipeline.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {packageId ? (
                  <Button asChild size="sm">
                    <Link href={`/packages?id=${packageId}`}>Open package</Link>
                  </Button>
                ) : null}
                <Button variant="secondary" size="sm" onClick={retry} disabled={retrying}>
                  {retrying ? "Retrying…" : "Retry this run"}
                </Button>
              </div>
              {retryFailure}
            </div>
          </div>
        </section>
      ) : null}

      <ol className="flex flex-col gap-2">
        {STAGE_ORDER.map((stage, index) => {
          const state = stageStates.states.get(stage) ?? "pending";
          const active = state === "running" && !finished;
          const stageEvents = events.filter((e) => e.stage === stage && e.message);
          return (
            <li key={stage}>
              <div
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                  active
                    ? "border-accent/40 bg-accent-subtle"
                    : state === "failed"
                      ? "border-danger/40 bg-danger-subtle"
                      : "border-border bg-raised",
                )}
              >
                <span className="mt-0.5 shrink-0" aria-hidden>
                  {state === "done" ? (
                    <Check className="size-5 text-success" />
                  ) : state === "failed" ? (
                    <X className="size-5 text-danger" />
                  ) : state === "warned" ? (
                    <AlertTriangle className="size-5 text-warning" />
                  ) : active ? (
                    <Loader2 className="size-5 animate-spin text-accent" />
                  ) : (
                    <CircleDashed className="size-5 text-fg-faint" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-fg-faint">{index + 1}</span>
                    <span className="font-medium">{STAGE_LABELS[stage]}</span>
                    {/* State is never colour alone: every non-default state
                        carries a word as well as an icon. */}
                    {state === "failed" ? (
                      <Badge tone="danger">Stopped here</Badge>
                    ) : state === "warned" ? (
                      <Badge tone="warning">Warning</Badge>
                    ) : state === "done" ? (
                      <Badge tone="success">Done</Badge>
                    ) : active ? (
                      <Badge tone="accent">Running</Badge>
                    ) : (
                      <Badge>Not started</Badge>
                    )}
                  </div>
                  <p className="mt-0.5 text-sm text-fg-muted">{STAGE_BLURBS[stage]}</p>
                  <AnimatePresence initial={false}>
                    {stageEvents.length ? (
                      <motion.ul
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        className="mt-2 space-y-1 border-l-2 border-border pl-3"
                      >
                        {stageEvents.slice(-3).map((event) => (
                          <li
                            key={event.seq}
                            className={cn(
                              "text-xs [overflow-wrap:anywhere]",
                              event.level === "info" ? "text-fg-faint" : "text-warning",
                            )}
                          >
                            {event.message}
                          </li>
                        ))}
                      </motion.ul>
                    ) : null}
                  </AnimatePresence>
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      {job?.warnings?.length ? (
        <Card>
          <CardContent className="pt-5">
            <h2 className="text-sm font-semibold">Warnings from this run</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-fg-muted">
              {job.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {/* Written by the worker when the run ends, so it is shown then rather than
          during — a running total that is structurally always zero would be a
          worse claim than no claim. */}
      {finished && usage ? (
        <Card>
          <CardContent className="pt-5">
            <h2 className="text-sm font-semibold">What this run used</h2>
            <dl className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <dt className="text-sm text-fg-muted">Tokens</dt>
                <dd className="mt-0.5 text-xl font-bold tabular-nums">
                  {formatTokens(usage.tokens)}
                </dd>
              </div>
              <div>
                <dt className="flex items-center gap-1.5 text-sm text-fg-muted">
                  <Coins className="size-4" aria-hidden /> Cost
                </dt>
                <dd className="mt-0.5 text-xl font-bold tabular-nums">
                  {formatCost(usage.cost_usd)}
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-fg-faint">
              Every attempt is counted, including retries that spent tokens and returned nothing.
              {usage.cost_usd === 0
                ? " Free-tier models report no cost, so $0.00 here is the true figure rather than a missing one."
                : ""}
            </p>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

export default function RunPage() {
  // useSearchParams needs a Suspense boundary in an exported app.
  return (
    <Suspense fallback={<div className="skeleton h-64 w-full" />}>
      <RunView />
    </Suspense>
  );
}
