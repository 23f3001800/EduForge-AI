"use client";

import { useQuery } from "@tanstack/react-query";
import { Gauge, Info, LineChart } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import {
  getBenchmark,
  getEvaluations,
  type Benchmark,
  type EvaluationSummary,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { describeError, traceIdOf } from "@/lib/errors";
import { STAGE_LABELS, type StageKey } from "@/lib/stages";

/**
 * The evaluation dashboard: every scored run, and the distribution they form.
 *
 * Two things this screen deliberately does not do.
 *
 * It does not draw a trend line through two points. A sparkline over a handful
 * of runs invites reading a slope that is noise, so the chart appears only once
 * there is enough history for the shape to mean something — and until then the
 * panel says how many more runs it needs.
 *
 * It does not compute anything. Medians and percentiles come from the API,
 * which is where the rubric lives. A dashboard that averaged its own rows would
 * be a second implementation nobody tests.
 */

/** Below this a chart is decoration. Mirrors MIN_BASELINE_RUNS on the backend. */
const MIN_FOR_TREND = 5;

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage as StageKey] ?? stage;
}

function scoreClass(score: number | null): string {
  if (score === null) return "text-fg-faint";
  if (score >= 85) return "text-success";
  if (score >= 70) return "text-accent";
  if (score >= 55) return "text-warning";
  return "text-danger";
}

/**
 * A box plot, drawn as a bar with the quartile range shaded.
 *
 * Chosen over a mean-with-error-bar because the interesting question about a
 * stage is how *consistent* it is: a stage whose scores run 60-100 needs
 * attention that its median of 85 does not reveal.
 */
function Spread({ stats }: { stats: Benchmark["stages"][string] }) {
  if (stats.median === null || stats.min === null || stats.max === null) return null;
  const p25 = stats.p25 ?? stats.min;
  const p75 = stats.p75 ?? stats.max;

  return (
    <div className="relative h-2 w-full rounded-full bg-surface" aria-hidden>
      <div
        className="absolute h-full rounded-full bg-accent/25"
        style={{ left: `${p25}%`, width: `${Math.max(1, p75 - p25)}%` }}
      />
      <div
        className="absolute top-1/2 h-3.5 w-0.5 -translate-y-1/2 rounded-full bg-accent"
        style={{ left: `${stats.median}%` }}
      />
    </div>
  );
}

function TrendChart({ runs }: { runs: EvaluationSummary[] }) {
  const points = runs
    .filter((r) => r.overall !== null)
    .slice()
    .reverse();

  if (points.length < MIN_FOR_TREND) {
    return (
      <EmptyState icon={LineChart} title="Not enough runs to plot a trend">
        {points.length} scored run{points.length === 1 ? "" : "s"} on record.{" "}
        {MIN_FOR_TREND - points.length} more and a slope here would mean something rather
        than tracing noise.
      </EmptyState>
    );
  }

  const values = points.map((p) => p.overall as number);
  const low = Math.min(...values, 50);
  const high = Math.max(...values, 100);
  const span = Math.max(1, high - low);

  const path = points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * 100;
      const y = 100 - (((point.overall as number) - low) / span) * 100;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <figure>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="h-40 w-full"
        role="img"
        aria-label={`Stage score across ${points.length} runs, from ${values[0].toFixed(
          0,
        )} to ${values[values.length - 1].toFixed(0)}.`}
      >
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5"
          vectorEffect="non-scaling-stroke" className="text-accent" />
      </svg>
      <figcaption className="mt-2 flex justify-between text-xs text-fg-faint">
        <span>{new Date(points[0].evaluated_at).toLocaleDateString()}</span>
        <span>
          {low.toFixed(0)}–{high.toFixed(0)} range · {points.length} runs
        </span>
        <span>{new Date(points[points.length - 1].evaluated_at).toLocaleDateString()}</span>
      </figcaption>
    </figure>
  );
}

export default function EvaluationDashboard() {
  const runs = useQuery({ queryKey: ["evaluations"], queryFn: () => getEvaluations(100) });
  const benchmark = useQuery({ queryKey: ["benchmark"], queryFn: () => getBenchmark() });

  if (runs.isPending || benchmark.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (runs.isError) {
    return (
      <ErrorState
        title="Could not load the evaluation history"
        traceId={traceIdOf(runs.error)}
        onRetry={() => runs.refetch()}
      >
        {describeError(runs.error).body}
      </ErrorState>
    );
  }

  const { evaluations, total, durable } = runs.data;
  const stats = benchmark.data;

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Evaluation</h1>
        <p className="mt-2 max-w-2xl text-fg-muted">
          Every package this instance has scored, and the distribution they form. Scores are
          deterministic — the same package evaluates to the same numbers every time, which is
          what makes a series worth reading.
        </p>
      </header>

      {!durable ? (
        <div className="flex items-start gap-3 rounded-lg border border-border bg-raised p-4 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-fg-faint" aria-hidden />
          <p className="text-fg-muted">
            This history lives in memory and is lost on restart. Set{" "}
            <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs">
              EVAL_HISTORY_PATH
            </code>{" "}
            to a mounted volume to keep the series across deployments.
          </p>
        </div>
      ) : null}

      {total === 0 ? (
        <EmptyState
          icon={Gauge}
          title="Nothing scored yet"
          action={
            <Link className="text-accent hover:underline" href="/samples">
              Open a sample and view its evaluation
            </Link>
          }
        >
          A package is scored the first time someone opens its evaluation tab, or when{" "}
          <code className="font-mono text-xs">python -m evals score</code> is run against it.
        </EmptyState>
      ) : (
        <>
          <section aria-labelledby="trend">
            <h2 id="trend" className="text-sm font-semibold uppercase tracking-wide text-fg-faint">
              Stage score over time
            </h2>
            <Card className="mt-3">
              <CardContent className="pt-5">
                <TrendChart runs={evaluations} />
              </CardContent>
            </Card>
          </section>

          {stats && stats.runs > 0 ? (
            <section aria-labelledby="spread">
              <h2
                id="spread"
                className="text-sm font-semibold uppercase tracking-wide text-fg-faint"
              >
                Where each stage sits
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-fg-muted">
                Median with the interquartile range shaded, across {stats.runs} run
                {stats.runs === 1 ? "" : "s"}.{" "}
                {stats.sufficient
                  ? "Enough history for a regression against these to mean something."
                  : `Below the ${MIN_FOR_TREND}-run minimum, so nothing is called a regression against them yet.`}
              </p>
              <Card className="mt-3">
                <CardContent className="flex flex-col gap-4 pt-5">
                  {Object.entries(stats.stages).map(([stage, distribution]) => (
                    <div key={stage}>
                      <div className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="truncate font-medium">{stageLabel(stage)}</span>
                        <span className={cn("shrink-0 tabular-nums", scoreClass(distribution.median))}>
                          {distribution.median?.toFixed(1) ?? "n/a"}
                          <span className="ml-2 text-xs text-fg-faint">
                            {distribution.min?.toFixed(0)}–{distribution.max?.toFixed(0)}
                          </span>
                        </span>
                      </div>
                      <div className="mt-1.5">
                        <Spread stats={distribution} />
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </section>
          ) : null}

          <section aria-labelledby="runs">
            <h2 id="runs" className="text-sm font-semibold uppercase tracking-wide text-fg-faint">
              Runs ({total})
            </h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[42rem] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-fg-faint">
                    <th scope="col" className="py-2 pr-4 font-medium">Package</th>
                    <th scope="col" className="py-2 pr-4 font-medium">Profile</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Score</th>
                    <th scope="col" className="py-2 pr-4 text-right font-medium">Confidence</th>
                    <th scope="col" className="py-2 font-medium">Evaluated</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluations.map((run) => (
                    <tr key={run.run_id} className="border-b border-border/60">
                      <td className="py-2.5 pr-4">
                        <Link
                          className="text-accent hover:underline"
                          href={`/packages?id=${run.package_id}`}
                        >
                          {run.subject}
                        </Link>
                      </td>
                      <td className="py-2.5 pr-4">
                        <Badge tone="accent">{run.profile}</Badge>
                      </td>
                      <td className={cn("py-2.5 pr-4 text-right tabular-nums", scoreClass(run.overall))}>
                        {run.overall === null ? "n/a" : run.overall.toFixed(1)}
                      </td>
                      <td className="py-2.5 pr-4 text-right tabular-nums text-fg-muted">
                        {(run.confidence * 100).toFixed(0)}%
                      </td>
                      <td className="py-2.5 text-fg-muted">
                        {new Date(run.evaluated_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
