"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  Loader2,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { getJob, retryJob } from "@/lib/api";
import { cn } from "@/lib/cn";
import { describeError } from "@/lib/errors";
import { expectedSeconds, STAGE_BLURBS, STAGE_LABELS, STAGE_ORDER, type StageKey } from "@/lib/stages";
import { useJobStream } from "@/lib/use-job-stream";

type StageState = "pending" | "running" | "done" | "warned";

/**
 * Live progress.
 *
 * The job id is a query parameter rather than a path segment because the app is
 * a static export: a path like /run/<uuid> has no pre-built HTML, whereas a
 * query string is the same document for every job. A refresh still resumes —
 * the query survives it, and the stream reconnects from the stored cursor.
 */
function RunView() {
  const params = useSearchParams();
  const jobId = params?.get("job") ?? null;
  const { events, progress, connection, terminal } = useJobStream(jobId);
  const [stageStartedAt, setStageStartedAt] = useState<number>(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  // Poll the snapshot as a backstop. SSE carries the detail, but a client that
  // arrives after the run finished — or whose stream never opened — must still
  // learn the outcome.
  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: terminal ? false : 5000,
  });

  const stageStates = useMemo(() => {
    const states = new Map<StageKey, StageState>();
    for (const stage of STAGE_ORDER) states.set(stage, "pending");

    let current: StageKey | null = null;
    for (const event of events) {
      const key = event.stage as StageKey;
      if (!states.has(key)) continue;
      if (event.level === "warning" || event.level === "error") {
        states.set(key, "warned");
      } else if (event.progress >= 100 || states.get(key) === "warned") {
        // leave as-is
      } else {
        states.set(key, states.get(key) === "warned" ? "warned" : "running");
      }
      current = key;
    }

    // Everything before the newest stage has necessarily finished — the
    // pipeline is linear, so "we are on stage 6" means 1-5 completed.
    if (current) {
      const index = STAGE_ORDER.indexOf(current);
      STAGE_ORDER.slice(0, index).forEach((stage) => {
        if (states.get(stage) !== "warned") states.set(stage, "done");
      });
      if (terminal === "completed") {
        STAGE_ORDER.forEach((stage) => {
          if (states.get(stage) !== "warned") states.set(stage, "done");
        });
      }
    }
    return { states, current };
  }, [events, terminal]);

  // Reset the per-stage clock whenever the active stage changes, so "slow"
  // measures this stage rather than the whole run.
  useEffect(() => {
    setStageStartedAt(Date.now());
  }, [stageStates.current]);

  useEffect(() => {
    if (terminal) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [terminal]);

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

  const failed = terminal === "failed" || job?.status === "failed";
  const done = terminal === "completed" || job?.status === "succeeded";
  const elapsedOnStage = (now - stageStartedAt) / 1000;
  const slow =
    !terminal &&
    stageStates.current !== null &&
    elapsedOnStage > expectedSeconds(stageStates.current) * 2.5;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
            {done ? "Package ready" : failed ? "This run failed" : "Building your package"}
          </h1>
          <p className="mt-1 font-mono text-xs text-fg-faint">{jobId}</p>
        </div>
        {done && job?.package_id ? (
          <Button asChild>
            <Link href={`/packages?id=${job.package_id}`}>
              Open package <ChevronRight />
            </Link>
          </Button>
        ) : null}
      </div>

      <Card>
        <CardContent className="pt-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">
              {done ? "Complete" : failed ? "Stopped" : "In progress"}
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
              className={cn("h-full rounded-full", failed ? "bg-danger" : "bg-accent")}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.4, ease: "easeOut" }}
            />
          </div>

          {/* Politely announced, so a screen reader learns of stage changes
              without every heartbeat interrupting the user. */}
          <p className="sr-only" aria-live="polite">
            {progress}% complete
            {stageStates.current ? `, ${STAGE_LABELS[stageStates.current]}` : ""}
          </p>

          {connection === "connecting" && !terminal ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-fg-muted">
              <WifiOff className="size-4" aria-hidden /> Reconnecting to the live stream — the run
              keeps going on the server.
            </p>
          ) : null}

          {slow ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-warning">
              <AlertTriangle className="size-4" aria-hidden /> This stage is taking longer than
              usual. Free-tier models queue under load; nothing is lost while it waits.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {failed && job?.error ? (
        <ErrorState
          title="This run failed"
          onRetry={async () => {
            try {
              await retryJob(jobId);
              window.location.reload();
            } catch (error) {
              alert(describeError(error).body);
            }
          }}
          retryLabel="Retry from the last completed stage"
        >
          <span className="font-medium">{job.error.type}:</span> {job.error.message}
        </ErrorState>
      ) : null}

      <ol className="flex flex-col gap-2">
        {STAGE_ORDER.map((stage, index) => {
          const state = stageStates.states.get(stage) ?? "pending";
          const active = stageStates.current === stage && !terminal;
          const stageEvents = events.filter((e) => e.stage === stage && e.message);
          return (
            <li key={stage}>
              <div
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                  active ? "border-accent/40 bg-accent-subtle" : "border-border bg-raised",
                )}
              >
                <span className="mt-0.5 shrink-0" aria-hidden>
                  {state === "done" ? (
                    <Check className="size-5 text-success" />
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
                    <span className="text-xs font-mono text-fg-faint">{index + 1}</span>
                    <span className="font-medium">{STAGE_LABELS[stage]}</span>
                    {state === "warned" ? <Badge tone="warning">Warning</Badge> : null}
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
                              "text-xs",
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
