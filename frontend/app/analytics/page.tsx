"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { getStats } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { formatDuration, formatPercent, labelFor } from "@/lib/format";
import { STAGE_LABELS, type StageKey } from "@/lib/stages";

/**
 * Runtime analytics.
 *
 * Every number here is measured by this instance since it started — never
 * modelled, never seeded with plausible history. Where nothing has happened
 * yet, the panel says so instead of drawing a zero: a chart showing "0% success
 * rate" for a system that has processed nothing is a statement, and a false one.
 *
 * The counters are in-process, so they reset with the app. The page says that
 * out loud rather than implying lifetime totals.
 */

const PIE_COLORS = [
  "hsl(var(--accent))",
  "hsl(var(--grounded))",
  "hsl(var(--warning))",
  "hsl(var(--success))",
  "hsl(var(--danger))",
];

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="pt-5">
        <p className="text-sm text-fg-muted">{label}</p>
        <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
        {hint ? <p className="mt-1 text-xs text-fg-faint">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

function Distribution({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data);
  // Omitted rather than drawn empty — an axis with no series reads as broken.
  if (entries.length === 0) return null;

  const chart = entries.map(([name, value]) => ({ name: labelFor(name), value }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={chart} dataKey="value" nameKey="name" innerRadius={45} outerRadius={80}>
                {chart.map((_, index) => (
                  <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--raised))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="mt-2 flex flex-wrap gap-2">
          {chart.map((entry, index) => (
            <li key={entry.name} className="flex items-center gap-1.5 text-xs text-fg-muted">
              <span
                className="size-2.5 rounded-full"
                style={{ background: PIE_COLORS[index % PIE_COLORS.length] }}
                aria-hidden
              />
              {entry.name} · {entry.value}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
    refetchInterval: 15_000,
  });

  if (isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return <ErrorState title={describeError(error).title}>{describeError(error).body}</ErrorState>;
  }

  const stageRows = Object.entries(data.stages)
    .map(([stage, value]) => ({
      name: STAGE_LABELS[stage as StageKey] ?? labelFor(stage),
      seconds: Number(value.mean_seconds.toFixed(2)),
    }))
    .filter((row) => row.seconds > 0);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Analytics</h1>
          <p className="mt-2 text-fg-muted">
            Measured by this instance. Nothing here is estimated or backfilled.
          </p>
        </div>
        <Badge tone="neutral">Since restart · {formatDuration(data.uptime_seconds)}</Badge>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Jobs finished"
          value={String(data.jobs.finished)}
          hint={`${data.jobs.succeeded} succeeded, ${data.jobs.failed} failed`}
        />
        <Stat
          label="Success rate"
          value={formatPercent(data.jobs.success_rate)}
          hint={data.jobs.success_rate === null ? "No job has finished yet" : undefined}
        />
        <Stat
          label="Model calls"
          value={String(data.llm.attempts)}
          hint={
            data.llm.retry_rate === null
              ? "No calls yet"
              : `${formatPercent(data.llm.retry_rate)} needed a retry`
          }
        />
        <Stat
          label="Spend"
          value={`$${data.llm.cost_usd.toFixed(4)}`}
          hint="Free-tier models report zero"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Mean time per stage</CardTitle>
        </CardHeader>
        <CardContent>
          {stageRows.length === 0 ? (
            <EmptyState title="No stage timings yet">
              Run a package and this fills in. Timings are recorded per stage execution, so a
              resumed run only adds the stages it actually re-ran.
            </EmptyState>
          ) : (
            <div className="h-72 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={stageRows} layout="vertical" margin={{ left: 24, right: 16 }}>
                  <XAxis type="number" tick={{ fontSize: 11 }} stroke="hsl(var(--fg-faint))" />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={140}
                    tick={{ fontSize: 11 }}
                    stroke="hsl(var(--fg-faint))"
                  />
                  <Tooltip
                    formatter={(value) => [`${Number(value ?? 0)}s`, "mean"]}
                    contentStyle={{
                      background: "hsl(var(--raised))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="seconds" fill="hsl(var(--accent))" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Distribution title="Packages by subject" data={data.packages.by_subject} />
        <Distribution title="Packages by profile" data={data.packages.by_profile} />
        <Distribution title="Packages by language" data={data.packages.by_language} />
      </div>

      {Object.keys(data.llm.by_outcome).length ? (
        <Card>
          <CardHeader>
            <CardTitle>Model call outcomes</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-wrap gap-2">
              {Object.entries(data.llm.by_outcome).map(([outcome, count]) => (
                <li key={outcome}>
                  <Badge
                    tone={
                      outcome === "ok"
                        ? "success"
                        : outcome === "error"
                          ? "danger"
                          : "warning"
                    }
                  >
                    {labelFor(outcome)} · {count}
                  </Badge>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-fg-faint">
              Failed attempts are counted alongside successes — a stage that succeeds on its third
              try cost three calls, and a climbing retry rate is the earliest sign a provider or a
              prompt has degraded.
            </p>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
