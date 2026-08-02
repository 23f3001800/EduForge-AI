"use client";

import {
  ChevronDown,
  CircleSlash,
  Download,
  Gauge,
  Lightbulb,
  Scale,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import {
  evaluationPdfUrl,
  getEvaluation,
  type EvaluationDocument,
  type EvaluationMetric,
  type Measurability,
  type StageEvaluation,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { describeError, traceIdOf } from "@/lib/errors";

/**
 * The evaluation view.
 *
 * One rule shapes every decision here: a metric that could not be measured must
 * never look like one that scored badly. So an unmeasurable metric renders in a
 * separate visual register — no bar, no number, no colour from the score
 * scale — and the count of them sits next to every stage score, because a stage
 * showing 100 across two metrics while four were unmeasurable is a different
 * claim from one showing 100 across six.
 *
 * The second rule: nothing is computed in this file. Every number comes from
 * the API. A dashboard that averages its own rows is a second implementation of
 * the rubric that nobody tests, and it will disagree with the PDF eventually.
 */

const TONE_FOR: Record<Measurability, "grounded" | "accent" | "neutral"> = {
  measured: "grounded",
  judged: "accent",
  not_measurable: "neutral",
};

const MEASURABILITY_LABEL: Record<Measurability, string> = {
  measured: "Measured",
  judged: "Judged",
  not_measurable: "Not measurable",
};

const SEVERITY_TONE: Record<string, "danger" | "warning" | "neutral"> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
  info: "neutral",
};

/** Colour follows the band, never the raw number — 71 and 84 read alike. */
function scoreTone(score: number | null): "success" | "accent" | "warning" | "danger" | "neutral" {
  if (score === null) return "neutral";
  if (score >= 85) return "success";
  if (score >= 70) return "accent";
  if (score >= 55) return "warning";
  return "danger";
}

function ScoreBar({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <div className="h-1.5 w-full rounded-full border border-dashed border-border" aria-hidden />
    );
  }
  const tone = scoreTone(score);
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface" aria-hidden>
      <div
        className={cn(
          "h-full rounded-full transition-[width]",
          tone === "success" && "bg-success",
          tone === "accent" && "bg-accent",
          tone === "warning" && "bg-warning",
          tone === "danger" && "bg-danger",
        )}
        style={{ width: `${Math.max(2, score)}%` }}
      />
    </div>
  );
}

function MetricRow({ metric }: { metric: EvaluationMetric }) {
  const [open, setOpen] = useState(false);
  const unmeasurable = metric.measurability === "not_measurable";
  const detailId = `metric-${metric.key}`;

  return (
    <li className={cn("rounded-lg border p-4", unmeasurable ? "border-dashed border-border bg-bg" : "border-border bg-raised")}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{metric.label}</span>
            <Badge tone={TONE_FOR[metric.measurability]}>
              {MEASURABILITY_LABEL[metric.measurability]}
            </Badge>
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{metric.reasoning}</p>
        </div>

        <div className="shrink-0 text-right">
          {unmeasurable ? (
            <span className="inline-flex items-center gap-1.5 text-sm text-fg-faint">
              <CircleSlash className="size-4" aria-hidden />
              No score
            </span>
          ) : (
            <>
              <p className="text-xl font-bold tabular-nums">{metric.score?.toFixed(0)}</p>
              <p className="text-xs text-fg-faint">
                confidence {(metric.confidence * 100).toFixed(0)}%
              </p>
            </>
          )}
        </div>
      </div>

      {!unmeasurable ? <div className="mt-3"><ScoreBar score={metric.score} /></div> : null}

      {metric.evidence.length > 0 || metric.recommendations.length > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls={detailId}
            className="mt-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-accent"
          >
            <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />
            {metric.evidence.length} evidence
            {metric.recommendations.length > 0
              ? `, ${metric.recommendations.length} recommendation${metric.recommendations.length > 1 ? "s" : ""}`
              : ""}
          </button>

          {open ? (
            <div id={detailId} className="mt-3 flex flex-col gap-3 border-t border-border pt-3">
              {metric.evidence.map((item, index) => (
                <div key={`${item.path}-${index}`} className="text-sm">
                  {/* The pointer is what makes a score checkable rather than
                      asserted — a reader can go and look at exactly this node. */}
                  <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs text-fg-muted">
                    {item.path}
                  </code>
                  <p className="mt-1 text-fg-muted">{item.observation}</p>
                </div>
              ))}
              {metric.recommendations.map((rec, index) => (
                <div key={index} className="rounded-md border border-border bg-surface p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge tone={SEVERITY_TONE[rec.severity] ?? "neutral"}>{rec.severity}</Badge>
                    <span className="font-medium">{rec.action}</span>
                  </div>
                  <p className="mt-1 text-fg-muted">{rec.impact}</p>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

function StageCard({ stage }: { stage: StageEvaluation }) {
  const [open, setOpen] = useState(false);
  const panelId = `stage-${stage.stage}`;

  return (
    <Card>
      <CardContent className="pt-5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={panelId}
          className="flex w-full items-center gap-4 text-left"
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{stage.label}</span>
              {stage.not_measurable > 0 ? (
                <Badge tone="neutral">{stage.not_measurable} not measurable</Badge>
              ) : null}
            </div>
            <div className="mt-2">
              <ScoreBar score={stage.score} />
            </div>
            <p className="mt-1.5 text-xs text-fg-faint">
              {stage.measured} measured
              {stage.judged > 0 ? `, ${stage.judged} judged` : ""} · confidence{" "}
              {(stage.confidence * 100).toFixed(0)}%
            </p>
          </div>

          <div className="shrink-0 text-right">
            {stage.score === null ? (
              <span className="text-sm text-fg-faint">n/a</span>
            ) : (
              <span className="text-2xl font-bold tabular-nums">{stage.score.toFixed(0)}</span>
            )}
          </div>

          <ChevronDown
            className={cn("size-5 shrink-0 text-fg-faint transition-transform", open && "rotate-180")}
            aria-hidden
          />
        </button>

        {open ? (
          <ul id={panelId} className="mt-4 flex flex-col gap-3">
            {stage.metrics.map((metric) => (
              <MetricRow key={metric.key} metric={metric} />
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Verdict({ document }: { document: EvaluationDocument }) {
  const { summary, comparison } = document;
  const delta = comparison.overall_delta;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardContent className="pt-5">
          <div className="grid gap-6 sm:grid-cols-2">
            <div>
              <p className="flex items-center gap-2 text-sm font-medium text-fg-muted">
                <Gauge className="size-4" aria-hidden /> Stage score
              </p>
              <p className="mt-1 text-4xl font-bold tabular-nums">
                {summary.stage_score === null ? "n/a" : summary.stage_score.toFixed(1)}
                <span className="ml-1 text-base font-normal text-fg-faint">/ 100</span>
              </p>
              <p className="mt-1 text-sm text-fg-muted">
                {summary.stages_scored} of {summary.stages_total} stages · confidence{" "}
                {(summary.stage_confidence * 100).toFixed(0)}%
              </p>
              <p className="mt-2 text-xs leading-relaxed text-fg-faint">
                Did each pipeline stage meet its contract with the next one.
              </p>
            </div>

            <div>
              <p className="flex items-center gap-2 text-sm font-medium text-fg-muted">
                <Scale className="size-4" aria-hidden /> Rubric score
              </p>
              <p className="mt-1 text-4xl font-bold tabular-nums">
                {summary.rubric_score.toFixed(1)}
                <span className="ml-1 text-base font-normal text-fg-faint">/ 100</span>
              </p>
              <p className="mt-1 text-sm text-fg-muted">{summary.rubric_band}</p>
              <p className="mt-2 text-xs leading-relaxed text-fg-faint">
                Is the result good teaching. Reported separately — averaging the two
                would give a number that answers neither question.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-5">
          <p className="text-sm font-medium text-fg-muted">Against history</p>
          <div className="mt-2 flex items-center gap-2">
            {comparison.status === "regression" ? (
              <Badge tone="danger">
                <TrendingDown className="size-3.5" aria-hidden /> Regression
              </Badge>
            ) : comparison.status === "ok" ? (
              <Badge tone="success">
                <TrendingUp className="size-3.5" aria-hidden /> No regression
              </Badge>
            ) : (
              <Badge tone="neutral">Not enough history</Badge>
            )}
            {typeof delta === "number" ? (
              <span className="text-sm tabular-nums text-fg-muted">
                {delta > 0 ? "+" : ""}
                {delta.toFixed(1)} vs median
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm leading-relaxed text-fg-muted">{comparison.detail}</p>

          {comparison.regressions.length > 0 ? (
            <ul className="mt-3 flex flex-col gap-1.5 text-sm">
              {comparison.regressions.map((entry) => (
                <li key={entry.stage} className="flex justify-between gap-2">
                  <span className="truncate text-fg-muted">{entry.stage}</span>
                  <span className="shrink-0 tabular-nums text-danger">
                    {entry.delta.toFixed(1)}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

export function EvaluationPanel({ packageId }: { packageId: string }) {
  const query = useQuery({
    queryKey: ["evaluation", packageId],
    // `persist: false` — opening a tab is reading, not running. A view that
    // appended to the series would let a refresh move the baseline it is
    // judged against.
    queryFn: () => getEvaluation(packageId, false),
  });

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-36 w-full" />
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <ErrorState
        title="Could not evaluate this package"
        traceId={traceIdOf(query.error)}
        onRetry={() => query.refetch()}
      >
        {describeError(query.error).body}
      </ErrorState>
    );
  }

  const document = query.data;
  const high = document.recommendations.filter((r) => r.severity === "high");

  return (
    <div className="flex flex-col gap-8">
      <Verdict document={document} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">
          Evaluated {new Date(document.evaluated_at).toLocaleString()} · deterministic, no
          model call
        </p>
        <Button asChild variant="secondary" size="sm">
          <a href={evaluationPdfUrl(packageId)} download>
            <Download className="size-4" aria-hidden />
            Download report
          </a>
        </Button>
      </div>

      {document.recommendations.length > 0 ? (
        <section aria-labelledby="recommendations">
          <h3
            id="recommendations"
            className="text-sm font-semibold uppercase tracking-wide text-fg-faint"
          >
            What to fix ({high.length} high severity of {document.recommendations.length})
          </h3>
          <ul className="mt-3 flex flex-col gap-2">
            {document.recommendations.map((rec, index) => (
              <li
                key={`${rec.stage}-${rec.metric}-${index}`}
                className="rounded-lg border border-border bg-raised p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={SEVERITY_TONE[rec.severity] ?? "neutral"}>{rec.severity}</Badge>
                  <span className="text-sm text-fg-faint">
                    {rec.stage_label} · {rec.metric_label}
                  </span>
                </div>
                <p className="mt-1.5 font-medium">{rec.action}</p>
                <p className="mt-1 text-sm text-fg-muted">{rec.impact}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="stages">
        <h3 id="stages" className="text-sm font-semibold uppercase tracking-wide text-fg-faint">
          Per stage
        </h3>
        <div className="mt-3 flex flex-col gap-3">
          {document.stages.map((stage) => (
            <StageCard key={stage.stage} stage={stage} />
          ))}
        </div>
      </section>

      {/* Placed before nothing and after everything scored, but never omitted:
          a report that lists ten green stages and stays silent about what it
          could not see has misled the reader with true numbers. */}
      <section aria-labelledby="unmeasurable">
        <h3
          id="unmeasurable"
          className="text-sm font-semibold uppercase tracking-wide text-fg-faint"
        >
          Not measurable ({document.not_measurable.length})
        </h3>
        <p className="mt-2 max-w-2xl text-sm text-fg-muted">
          These carry no score. Each says what it would take to measure — a labelled corpus,
          a classroom trial, response data. Reporting a number here would mean inventing one.
        </p>
        <ul className="mt-3 grid gap-2 md:grid-cols-2">
          {document.not_measurable.map((entry) => (
            <li
              key={`${entry.stage}-${entry.metric}`}
              className="rounded-lg border border-dashed border-border p-4"
            >
              <div className="flex items-center gap-2">
                <Lightbulb className="size-4 shrink-0 text-fg-faint" aria-hidden />
                <span className="font-medium">{entry.label}</span>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{entry.reason}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
