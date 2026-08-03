"use client";

import { useQuery } from "@tanstack/react-query";
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
import { formatClock, formatCost, formatDuration, formatTokens } from "@/lib/format";
import { findingsFrom } from "@/lib/run-findings";
import {
  expectedSeconds,
  isStageKey,
  STAGE_BLURBS,
  STAGE_LABELS,
  STAGE_ORDER,
  type StageKey,
} from "@/lib/stages";
import { clearTimeline, useJobStream, type StreamEvent } from "@/lib/use-job-stream";
import { ActivityLog } from "./activity-log";

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

/** An ISO timestamp as epoch ms, or null if it was absent or unparseable. */
function parseTime(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
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

/** When each stage first and last spoke, on the server's clock. */
interface StageTiming {
  firstMs: number;
  lastMs: number;
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
 *
 * On time. Three clocks are in play and mixing them produces nonsense, so each
 * number below states which one it is on:
 *
 *   - Server timestamps (`ts`, `created_at`) compared to each other give exact
 *     durations regardless of what this browser thinks the time is.
 *   - The browser's clock compared to a server timestamp gives "how long ago",
 *     and is wrong by whatever the two clocks disagree by.
 *   - The browser's clock compared to a moment this page recorded itself is
 *     exact, but only measures the part of the run it was open for.
 *
 * Nothing here interpolates. Every duration shown is the distance between two
 * things that actually happened.
 */
function RunView() {
  const params = useSearchParams();
  const jobId = params?.get("job") ?? null;
  const { events, progress: streamProgress, connection, terminal } = useJobStream(jobId);
  const [stageStartedAt, setStageStartedAt] = useState<number>(() => Date.now());
  const [lastEventAt, setLastEventAt] = useState<number>(() => Date.now());
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
    // Stopped on the snapshot's own status, and deliberately *not* on the
    // stream's terminal frame.
    //
    // Stopping on `terminal` looks right and is a data-loss bug: the SSE
    // `completed` frame arrives well before the poll that follows it, so
    // cancelling the poll then freezes the snapshot at its last in-flight
    // value. Everything the worker writes only at the end — `usage.tokens`,
    // `cost_usd`, `warnings` — is written *after* that frame
    // (worker/runner.py:171-187), so the run would render its final accounting
    // as "0 tokens, $0.00" and then say that zero was the true figure.
    //
    // The snapshot's own status is the condition that both terminates and is
    // late enough to be complete: the worker sets it in the same update that
    // writes the totals, so the first poll to observe a terminal status is also
    // the first to carry them. It is reached whether or not EventSource ever
    // opened, which is what stops a finished run being polled forever.
    refetchInterval: (query) =>
      TERMINAL_STATUSES.has(query.state.data?.status ?? "") ? false : 5000,
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

  /**
   * The first and last server timestamp seen for each stage, plus the run's own
   * bounds. Events arrive sorted by `seq`, so first and last are simply the
   * first and last usable `ts` in each group.
   */
  const timing = useMemo(() => {
    const stages = new Map<StageKey, StageTiming>();
    let first: number | null = null;
    let last: number | null = null;

    for (const event of events) {
      const ms = parseTime(event.ts);
      if (ms === null) continue;
      if (first === null) first = ms;
      last = ms;

      if (!isStageKey(event.stage)) continue;
      const existing = stages.get(event.stage);
      if (existing) existing.lastMs = ms;
      else stages.set(event.stage, { firstMs: ms, lastMs: ms });
    }

    return { stages, first, last };
  }, [events]);

  const findings = useMemo(() => findingsFrom(events), [events]);

  // Reset the per-stage clock whenever the active stage changes, so "slow"
  // measures this stage rather than the whole run.
  useEffect(() => {
    setStageStartedAt(Date.now());
  }, [stageStates.active]);

  // When the newest frame arrived, on this browser's clock. Seeded at mount so
  // a page opened onto a restored timeline measures silence from the moment it
  // could first have observed one, never from a server timestamp it cannot
  // trust — this understates a gap that began before the page opened, which is
  // the safe direction: it delays the warning rather than inventing one.
  const newestSeq = events.length ? events[events.length - 1].seq : null;
  useEffect(() => {
    setLastEventAt(Date.now());
  }, [newestSeq]);

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
  const sinceLastEvent = Math.max(0, (now - lastEventAt) / 1000);
  // Either the stage has outrun its budget or the stream has gone quiet for
  // longer than the stage should have taken in total. The second case is the
  // one a local Ollama profile hits: a single call can hold for minutes.
  const slow = !finished && (elapsedOnStage > budget || sinceLastEvent > budget);

  /**
   * Total wall-clock time, floored by the stream's own span.
   *
   * The anchor is `created_at`, so the queue wait counts — a job sitting behind
   * another one has genuinely been running that long from the operator's chair.
   * Comparing that server timestamp to `Date.now()` is the one figure here that
   * a skewed browser clock can distort, so it is floored by first-to-last event
   * distance, which is measured entirely server-side. A slow clock can no
   * longer report a twelve-minute run as four minutes old.
   */
  const finishedMs = parseTime(job?.finished_at);
  const createdMs = parseTime(job?.created_at);
  const endMs = finished && finishedMs !== null ? finishedMs : now;
  const streamSpan =
    timing.first !== null && timing.last !== null ? (timing.last - timing.first) / 1000 : 0;
  const anchorMs = createdMs ?? timing.first;
  const elapsed = Math.max(0, anchorMs !== null ? (endMs - anchorMs) / 1000 : 0, streamSpan);

  /** `+0:00` on the log is the first thing the run said. */
  const logOrigin = timing.first ?? createdMs;

  /**
   * How long the current stage has been going.
   *
   * Server-measured from its first event to its most recent one, plus the time
   * this page has watched since that event arrived. Both halves are differences
   * within a single clock, so neither carries skew. Falls back to the page's own
   * stage clock when the stage has not produced a timestamped event yet.
   */
  const activeTiming = stageStates.active ? timing.stages.get(stageStates.active) : undefined;
  const activeStageElapsed = activeTiming
    ? (activeTiming.lastMs - activeTiming.firstMs) / 1000 + sinceLastEvent
    : elapsedOnStage;

  /** A finished stage's duration, or null when it cannot be measured honestly. */
  function stageDuration(stage: StageKey): number | null {
    const measured = timing.stages.get(stage);
    if (!measured) return null;
    // A stage still holding the baton has not got a duration yet, only an
    // elapsed — reporting the gap between its first and latest event as a
    // duration would show it finishing over and over.
    if (!finished && stage === stageStates.active) return null;
    const seconds = (measured.lastMs - measured.firstMs) / 1000;
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  }

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
  // Zero tokens on a run that has not finished is the worker not having written
  // its total yet, not a run that spent nothing. The two must not render alike.
  const usageCounted = typeof usage?.tokens === "number" && usage.tokens > 0;

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
          {/* Elapsed leads. Someone watching a twenty-five minute build is
              asking "is this moving?", and a percentage that legitimately sits
              still for four minutes answers that badly where a clock that
              visibly ticks answers it well. */}
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <p className="flex items-baseline gap-2">
              <span className="font-mono text-3xl font-bold tabular-nums">
                {formatClock(elapsed)}
              </span>
              <span className="text-sm text-fg-muted">elapsed</span>
            </p>
            <p className="flex items-baseline gap-2 text-sm">
              <span className="font-medium">
                {done ? "Complete" : failed || cancelled ? "Stopped" : "In progress"}
              </span>
              <span className="font-mono tabular-nums text-fg-muted">{progress}%</span>
            </p>
          </div>

          <div
            className="mt-3 h-2 overflow-hidden rounded-full bg-fg/10"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Overall progress"
          >
            {/* A CSS transition, not an animation library: it moves only when
                `progress` actually changes, and the global reduced-motion rule
                already neutralises it. Dropping framer-motion from this route
                took ~40 kB off its first load. */}
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500 ease-out",
                failed || cancelled ? "bg-danger" : partialLikely ? "bg-warning" : "bg-accent",
              )}
              style={{ width: `${progress}%` }}
            />
          </div>

          {/* Liveness, all of it measured. The pulse says the page is connected
              and the clock says when the run last spoke; neither implies work is
              happening that the server has not reported. */}
          {!finished ? (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
              <span className="inline-flex items-center gap-2">
                <span className="relative flex size-2 shrink-0" aria-hidden>
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-70 motion-reduce:hidden" />
                  <span className="relative inline-flex size-2 rounded-full bg-accent" />
                </span>
                Working
              </span>
              {stageStates.active ? (
                <span className="tabular-nums">
                  {STAGE_LABELS[stageStates.active]} · {formatClock(activeStageElapsed)}
                </span>
              ) : null}
              <span className="tabular-nums">
                Last update {formatClock(sinceLastEvent)} ago
              </span>
            </div>
          ) : null}

          {/* Politely announced, so a screen reader learns of stage changes
              without every heartbeat interrupting the user. The percentage is
              deliberately not in here: it changes on every one of a few hundred
              events, and re-announcing the whole sentence each time buries the
              stage change that actually matters. It stays available on demand
              through the progressbar's aria-valuenow above. */}
          <p className="sr-only" aria-live="polite">
            {headline}
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
                  This stage is taking longer than usual. Free-tier models queue under load and a
                  local model can hold a single call for several minutes; nothing is lost while it
                  waits.
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

      {/* Only once there is something to show. An empty "Found so far" card
          with dashes in it would be worse than the absence it is describing. */}
      {findings.length ? (
        <section aria-labelledby="findings" className="card p-4 sm:p-5">
          <h2 id="findings" className="text-sm font-semibold">
            Found so far
          </h2>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
            {findings.map((finding) => (
              <div key={finding.id} className="min-w-0">
                <dt className="text-xs text-fg-muted">{finding.label}</dt>
                <dd className="mt-0.5 text-sm font-medium [overflow-wrap:anywhere]">
                  {finding.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <ActivityLog events={events} originMs={logOrigin} live={!finished} />

      <section aria-labelledby="stages">
        <h2 id="stages" className="sr-only">
          Pipeline stages
        </h2>
        <ol className="flex flex-col gap-2">
          {STAGE_ORDER.map((stage, index) => {
            const state = stageStates.states.get(stage) ?? "pending";
            const active = state === "running" && !finished;
            // Only the stage holding the baton, and any stage that stopped the
            // run, get the full treatment. Everything else collapses to one
            // line so the active stage has room — the detail they used to show
            // now lives in the log above, in full and permanently.
            const expanded = active || state === "failed";
            const duration = stageDuration(stage);

            return (
              <li key={stage}>
                <div
                  className={cn(
                    "flex items-start gap-3 rounded-lg border transition-colors",
                    expanded ? "p-3" : "px-3 py-2",
                    active
                      ? "border-accent/40 bg-accent-subtle"
                      : state === "failed"
                        ? "border-danger/40 bg-danger-subtle"
                        : "border-border bg-raised",
                  )}
                >
                  <span className={cn("shrink-0", expanded ? "mt-0.5" : "")} aria-hidden>
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
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="font-mono text-xs text-fg-faint">{index + 1}</span>
                      <span className={cn("font-medium", expanded ? "" : "text-sm")}>
                        {STAGE_LABELS[stage]}
                      </span>
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
                      {/* Measured between this stage's first and last event.
                          Omitted entirely when those timestamps are missing,
                          rather than shown as a dash. */}
                      {duration !== null ? (
                        <span className="font-mono text-xs tabular-nums text-fg-faint">
                          {formatDuration(duration)}
                        </span>
                      ) : null}
                      {active ? (
                        <span className="font-mono text-xs tabular-nums text-accent">
                          {formatClock(activeStageElapsed)}
                        </span>
                      ) : null}
                    </div>
                    {expanded ? (
                      <p className="mt-0.5 text-sm text-fg-muted">{STAGE_BLURBS[stage]}</p>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

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

      {/* Shown throughout the run rather than only at the end, but driven by the
          figure itself rather than by the run's status: the moment `usage.tokens`
          is non-zero it renders, whenever that happens.

          Today it happens once, at the end. `worker/runner.py` writes
          `job.tokens_used` only on its terminal paths (lines 130 and 183), and
          `ProgressEmitter._advance_job` — the one thing that updates the job
          record mid-run — has no access to the LLM client to read a running
          total from. So the running case below says that plainly instead of
          animating a zero, which would read as "this run is free". */}
      {usage ? (
        <Card>
          <CardContent className="pt-5">
            <h2 className="text-sm font-semibold">
              {finished ? "What this run used" : "What this run has used"}
            </h2>
            {usageCounted || finished ? (
              <>
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
                  Every attempt is counted, including retries that spent tokens and returned
                  nothing.
                  {usage.cost_usd === 0
                    ? " Free-tier models report no cost, so $0.00 here is the true figure rather than a missing one."
                    : ""}
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-fg-muted">
                Not counted yet. The worker totals tokens and cost when the run reaches a terminal
                state, so this stays blank until then rather than showing a zero that would read as
                a free run.
              </p>
            )}
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
