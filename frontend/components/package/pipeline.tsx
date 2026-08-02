"use client";

import { AlertTriangle, Coins, Cpu, GitBranch, Timer } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/states";
import { formatDuration } from "@/lib/format";
import { STAGE_LABELS, type StageKey } from "@/lib/stages";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = Record<string, any>;

/**
 * How this package was made: what each stage cost, which model wrote it, and
 * why the pipeline chose what it chose.
 *
 * The reasoning comes first and the numbers second, deliberately. A teacher
 * opening this wants to know whether to trust the output — "5 periods, because
 * 9 concepts need 210 minutes" answers that. The token counts matter to whoever
 * pays for it, which is a different person on a different day.
 */

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage as StageKey] ?? stage;
}

export function PipelinePanel({
  provenance,
  generator,
}: {
  provenance: Any;
  generator: Any;
}) {
  const timings: Any[] = provenance?.stage_timings ?? [];
  const decisions: Any[] = provenance?.decisions ?? [];
  const models: Record<string, string> = generator?.models_by_stage ?? {};
  const providers: Record<string, string> = generator?.providers_by_stage ?? {};

  const totalMs = Number(provenance?.total_duration_ms ?? 0);
  const tokensIn = Number(provenance?.total_tokens_in ?? 0);
  const tokensOut = Number(provenance?.total_tokens_out ?? 0);
  const cost = Number(provenance?.total_cost_usd ?? 0);

  // A package generated before per-stage reporting existed has none of this.
  // Saying so is better than rendering a grid of zeroes that reads as "free".
  if (timings.length === 0 && decisions.length === 0) {
    return (
      <EmptyState icon={GitBranch} title="No pipeline record for this package">
        It was generated before per-stage cost and reasoning were recorded. Newer runs carry
        both.
      </EmptyState>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {decisions.length > 0 ? (
        <section aria-labelledby="decisions">
          <h3 id="decisions" className="text-sm font-semibold uppercase tracking-wide text-fg-faint">
            Why it chose this
          </h3>
          <ul className="mt-3 flex flex-col gap-2">
            {decisions.map((decision, index) => (
              <li
                key={`${decision.stage}-${index}`}
                className="rounded-lg border border-border bg-raised p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="accent">{stageLabel(decision.stage)}</Badge>
                  <span className="font-medium">{decision.what}</span>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">
                  {decision.because}
                </p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="cost">
        <h3 id="cost" className="text-sm font-semibold uppercase tracking-wide text-fg-faint">
          What it cost
        </h3>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { icon: Timer, label: "Total time", value: formatDuration(totalMs / 1000) },
            { icon: Cpu, label: "Tokens in", value: tokensIn.toLocaleString() },
            { icon: Cpu, label: "Tokens out", value: tokensOut.toLocaleString() },
            {
              icon: Coins,
              label: "Cost",
              // Free-tier models genuinely report zero. Saying "$0.00" is true;
              // omitting it would look like the number was unavailable.
              value: cost > 0 ? `$${cost.toFixed(4)}` : "$0.00",
            },
          ].map(({ icon: Icon, label, value }) => (
            <Card key={label}>
              <CardContent className="pt-5">
                <Icon className="size-4 text-fg-faint" aria-hidden />
                <p className="mt-2 text-xl font-bold tabular-nums">{value}</p>
                <p className="text-sm text-fg-muted">{label}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-4 font-semibold">Stage</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Model</th>
                <th scope="col" className="py-2 pr-4 text-right font-semibold">Time</th>
                <th scope="col" className="py-2 pr-4 text-right font-semibold">In</th>
                <th scope="col" className="py-2 pr-4 text-right font-semibold">Out</th>
                <th scope="col" className="py-2 text-right font-semibold">Calls</th>
              </tr>
            </thead>
            <tbody>
              {timings.map((timing) => {
                const model = models[timing.stage];
                return (
                  <tr key={timing.stage} className="border-b border-border/60">
                    <th scope="row" className="py-2 pr-4 text-left font-medium">
                      <span className="flex flex-wrap items-center gap-2">
                        {stageLabel(timing.stage)}
                        {timing.degraded ? (
                          <Badge tone="warning">
                            <AlertTriangle className="size-3" aria-hidden /> Degraded
                          </Badge>
                        ) : null}
                      </span>
                    </th>
                    <td className="py-2 pr-4 font-mono text-xs text-fg-muted">
                      {/* A stage with no model did no model work — parsing and
                          publishing are pure code. An em dash says that; "0"
                          would imply a call that returned nothing. */}
                      {model ? (
                        <>
                          {model}
                          {providers[timing.stage] ? (
                            <span className="text-fg-faint"> · {providers[timing.stage]}</span>
                          ) : null}
                        </>
                      ) : (
                        <span className="text-fg-faint">— no model</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">
                      {formatDuration(timing.duration_ms / 1000)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums text-fg-muted">
                      {timing.tokens_in ? timing.tokens_in.toLocaleString() : "—"}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums text-fg-muted">
                      {timing.tokens_out ? timing.tokens_out.toLocaleString() : "—"}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {/* More than one attempt means a retry. Shown rather than
                          summed away: a rising retry rate is the earliest sign a
                          prompt or provider has degraded. */}
                      {timing.attempts > 1 ? (
                        <span className="font-medium text-warning">{timing.attempts}</span>
                      ) : (
                        timing.attempts
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-xs text-fg-faint">
          Publishing does not appear: it assembles this package, so its own duration is not known
          until after the record it would sit in has been built. Failed attempts are counted — a
          stage that succeeded on its second try cost two calls.
        </p>
      </section>
    </div>
  );
}
