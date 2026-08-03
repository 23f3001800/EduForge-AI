"use client";

import { useQuery } from "@tanstack/react-query";
import * as Tabs from "@radix-ui/react-tabs";
import {
  BookOpen,
  ClipboardCheck,
  GitBranch,
  Gauge,
  GraduationCap,
  Layers,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ArtifactsPanel } from "@/components/package/artifacts";
import { EvaluationPanel } from "@/components/package/evaluation";
import { PipelinePanel } from "@/components/package/pipeline";
import { EvidenceList, type Evidence } from "@/components/package/evidence";
import { OcrNotice } from "@/components/package/ocr";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { getPackage } from "@/lib/api";
import { describeError, traceIdOf } from "@/lib/errors";
import { labelFor } from "@/lib/format";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = Record<string, any>;

const TABS = [
  { id: "overview", label: "Overview", icon: Layers },
  { id: "plan", label: "Teaching plan", icon: GraduationCap },
  { id: "content", label: "Classroom content", icon: BookOpen },
  { id: "knowledge", label: "Knowledge", icon: Layers },
  { id: "activities", label: "Activities", icon: BookOpen },
  { id: "assessments", label: "Assessments", icon: ClipboardCheck },
  { id: "gaps", label: "Learning gaps", icon: TriangleAlert },
  { id: "validation", label: "Validation", icon: ShieldCheck },
  { id: "pipeline", label: "Pipeline", icon: GitBranch },
  { id: "evaluation", label: "Evaluation", icon: Gauge },
];

const VALIDATION_TONE: Record<string, "success" | "warning" | "danger"> = {
  pass: "success",
  pass_with_warnings: "warning",
  fail: "danger",
};

/**
 * An entry or exit ticket.
 *
 * These are objects — `{prompt, duration_minutes, expected_response}` — not
 * strings. Rendering one directly put an object where React expects a child and
 * took the whole page down with error #31, which is the failure mode of
 * assuming a shape instead of reading the contract.
 */
function Ticket({ label, ticket }: { label: string; ticket?: Any | null }) {
  if (!ticket?.prompt) return null;
  return (
    <div>
      <h4 className="text-sm font-semibold">
        {label}
        {ticket.duration_minutes ? (
          <span className="ml-2 font-normal text-fg-faint">{ticket.duration_minutes} min</span>
        ) : null}
      </h4>
      <p className="mt-1 text-sm text-fg-muted">{ticket.prompt}</p>
      {ticket.expected_response ? (
        <p className="mt-1 text-xs text-fg-faint">
          <span className="font-medium">Expect:</span> {ticket.expected_response}
        </p>
      ) : null}
      {ticket.success_indicator ? (
        <p className="mt-1 text-xs text-fg-faint">
          <span className="font-medium">Success looks like:</span> {ticket.success_indicator}
        </p>
      ) : null}
    </div>
  );
}

/** Absent sections are omitted entirely — a humanities package has no formulae,
 *  and an empty card labelled "Formulae" would imply something went missing. */
function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (!count) return null;
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-fg-faint">
        {title} <span className="ml-1 font-normal normal-case">({count})</span>
      </h3>
      {children}
    </section>
  );
}

function ViewerBody() {
  const params = useSearchParams();
  const packageId = params?.get("id") ?? null;

  const { data, isPending, isError, error } = useQuery({
    queryKey: ["package", packageId],
    queryFn: () => getPackage(packageId as string),
    enabled: Boolean(packageId),
  });

  if (!packageId) {
    return (
      <EmptyState title="No package selected">
        Pick one from{" "}
        <Link className="text-accent hover:underline" href="/samples">
          the samples
        </Link>{" "}
        or start a{" "}
        <Link className="text-accent hover:underline" href="/upload">
          new run
        </Link>
        .
      </EmptyState>
    );
  }

  if (isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    const { title, body } = describeError(error);
    return (
      <ErrorState title={title} traceId={traceIdOf(error)}>
        {body}
      </ErrorState>
    );
  }

  const tkp = data as Any;
  const classification = (tkp.classification ?? {}) as Any;
  const knowledge = (tkp.knowledge ?? {}) as Any;
  const plan = (tkp.teaching_plan ?? {}) as Any;
  const content = (tkp.classroom_content ?? []) as Any[];
  const activities = (tkp.activities ?? []) as Any[];
  const assessments = (tkp.assessments ?? {}) as Any;
  const gaps = (tkp.learning_gaps ?? []) as Any[];
  const validation = (tkp.validation ?? {}) as Any;

  const items = (assessments.items ?? []) as Any[];
  const mcqs = items.filter((i) => i.kind === "mcq");
  const written = items.filter((i) => i.kind !== "mcq");

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">
              {tkp.source?.title ?? classification.topic ?? "Teacher Knowledge Package"}
            </h1>
            <p className="mt-1 text-fg-muted">
              {classification.subject} · Grade {classification.grade_band}
              {classification.chapter ? ` · ${classification.chapter}` : ""}
            </p>
          </div>
          <Badge tone={VALIDATION_TONE[validation.status] ?? "neutral"}>
            {labelFor(String(validation.status ?? "unknown"))}
          </Badge>
        </div>

        <div className="flex flex-wrap gap-2">
          <Badge tone="accent">{labelFor(String(classification.pedagogy_profile ?? "mixed"))}</Badge>
          <Badge>{plan.total_periods} periods</Badge>
          <Badge>{plan.period_duration_minutes} min each</Badge>
          {typeof validation.grounding_score === "number" ? (
            <Badge tone="grounded">
              <ShieldCheck className="size-3" aria-hidden />
              {Math.round(validation.grounding_score * 100)}% grounded
            </Badge>
          ) : null}
        </div>
      </header>

      {/* Above everything, because it qualifies everything: if the source text
          was misread, every citation below was checked against the misreading.
          Renders nothing at all when no page needed OCR, which is the usual case. */}
      <OcrNotice ocr={tkp.source?.ocr} />

      <ArtifactsPanel packageId={packageId} />

      <Tabs.Root defaultValue="overview">
        <Tabs.List
          className="-mx-4 flex gap-1 overflow-x-auto border-b border-border px-4 pb-px"
          aria-label="Package sections"
        >
          {TABS.map((tab) => (
            <Tabs.Trigger
              key={tab.id}
              value={tab.id}
              className="whitespace-nowrap border-b-2 border-transparent px-3 py-2.5 text-sm font-medium text-fg-muted transition-colors hover:text-fg data-[state=active]:border-accent data-[state=active]:text-accent"
            >
              {tab.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <div className="pt-6">
          <Tabs.Content value="overview" className="flex flex-col gap-6">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ["Concepts", (knowledge.concepts ?? []).length],
                ["Objectives", (knowledge.learning_objectives ?? []).length],
                ["Activities", activities.length],
                ["Assessment items", items.length],
              ].map(([label, value]) => (
                <Card key={label as string}>
                  <CardContent className="pt-5">
                    <p className="text-2xl font-bold tabular-nums">{value as number}</p>
                    <p className="text-sm text-fg-muted">{label as string}</p>
                  </CardContent>
                </Card>
              ))}
            </div>

            <Section title="Learning objectives" count={(knowledge.learning_objectives ?? []).length}>
              <ul className="flex flex-col gap-2">
                {(knowledge.learning_objectives as Any[]).map((objective) => (
                  <li
                    key={objective.objective_id}
                    className="flex flex-wrap items-start gap-2 rounded-md border border-border p-3"
                  >
                    <Badge tone="accent">{labelFor(objective.bloom_level)}</Badge>
                    <span className="min-w-0 flex-1 text-sm">{objective.statement}</span>
                  </li>
                ))}
              </ul>
            </Section>
          </Tabs.Content>

          <Tabs.Content value="plan" className="flex flex-col gap-3">
            {(plan.periods ?? []).map((period: Any) => (
              <Card key={period.period_no} className="border-l-2 border-l-accent">
                <CardContent className="pt-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>Period {period.period_no}</Badge>
                    <h3 className="font-semibold">{period.title}</h3>
                  </div>
                  {period.sequence_rationale ? (
                    <p className="mt-2 text-sm text-fg-muted">{period.sequence_rationale}</p>
                  ) : null}
                  {/* A LIST of {label, minutes}, not a mapping. Treating it as
                      one rendered the object itself as a child and crashed the
                      page with React error #31. */}
                  {(period.time_allocation ?? []).length ? (
                    <ul className="mt-3 flex flex-wrap gap-2 text-xs">
                      {(period.time_allocation as Any[]).map((slot, index) => (
                        <li
                          key={`${slot.label}-${index}`}
                          className="rounded-full bg-surface px-2 py-0.5"
                        >
                          {slot.label} · {slot.minutes}m
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </CardContent>
              </Card>
            ))}
          </Tabs.Content>

          <Tabs.Content value="content" className="flex flex-col gap-4">
            {content.map((period: Any) => (
              <Card key={period.period_no}>
                <CardContent className="flex flex-col gap-4 pt-5">
                  <Badge>Period {period.period_no}</Badge>

                  <Ticket label="Entry ticket" ticket={period.entry_ticket} />

                  {(period.teacher_script ?? []).length ? (
                    <div>
                      <h4 className="text-sm font-semibold">Teacher script</h4>
                      <ol className="mt-2 space-y-2">
                        {(period.teacher_script as Any[]).map((beat, index) => (
                          <li key={index} className="rounded-md bg-surface p-3">
                            <div className="flex flex-wrap items-baseline justify-between gap-2">
                              <span className="text-sm font-medium">{beat.heading}</span>
                              <span className="font-mono text-xs text-fg-faint">
                                {beat.minute_start}–{beat.minute_end} min
                              </span>
                            </div>
                            {beat.speaker_notes ? (
                              <p className="mt-1 text-sm text-fg-muted">{beat.speaker_notes}</p>
                            ) : null}
                            {beat.board_action ? (
                              <p className="mt-1.5 text-xs text-fg-faint">
                                <span className="font-medium">On the board:</span>{" "}
                                {beat.board_action}
                              </p>
                            ) : null}
                            {(beat.anticipated_questions ?? []).length ? (
                              <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs text-fg-faint">
                                {(beat.anticipated_questions as string[]).map((question, i) => (
                                  <li key={i}>{question}</li>
                                ))}
                              </ul>
                            ) : null}
                          </li>
                        ))}
                      </ol>
                    </div>
                  ) : null}

                  {period.blackboard_notes ? (
                    <div>
                      <h4 className="text-sm font-semibold">Blackboard</h4>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-fg-muted">
                        {(period.blackboard_notes.bullet_points ?? []).map(
                          (point: string, index: number) => (
                            <li key={index}>{point}</li>
                          ),
                        )}
                        {(period.blackboard_notes.diagrams_to_draw ?? []).map(
                          (diagram: string, index: number) => (
                            <li key={`d-${index}`} className="italic">
                              Draw: {diagram}
                            </li>
                          ),
                        )}
                      </ul>
                    </div>
                  ) : null}

                  {(period.checkpoint_questions ?? []).length ? (
                    <div>
                      <h4 className="text-sm font-semibold">Checks for understanding</h4>
                      <ul className="mt-2 space-y-2">
                        {(period.checkpoint_questions as Any[]).map((question, index) => (
                          <li key={index} className="rounded-md border border-border p-3 text-sm">
                            <p>{question.question}</p>
                            {question.expected_answer ? (
                              <p className="mt-1 text-xs text-fg-faint">
                                <span className="font-medium">Expect:</span>{" "}
                                {question.expected_answer}
                              </p>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <Ticket label="Exit ticket" ticket={period.exit_ticket} />

                  {period.mentor_moment ? (
                    <div className="rounded-md border-l-2 border-l-warning bg-warning-subtle p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="text-sm font-semibold">{period.mentor_moment.title}</h4>
                        {/* The one thing the pipeline writes without a source.
                            Labelled, so it is never mistaken for extracted fact. */}
                        {period.mentor_moment.grounded === false ? (
                          <Badge tone="warning">Illustrative — not from the source</Badge>
                        ) : null}
                      </div>
                      <p className="mt-1 text-sm text-fg-muted">{period.mentor_moment.story}</p>
                      {period.mentor_moment.takeaway ? (
                        <p className="mt-1 text-sm font-medium">{period.mentor_moment.takeaway}</p>
                      ) : null}
                    </div>
                  ) : null}

                  {period.homework ? (
                    <div>
                      <h4 className="text-sm font-semibold">
                        Homework
                        <span className="ml-2 font-normal text-fg-faint">
                          ~{period.homework.estimated_minutes} min ·{" "}
                          {period.homework.submission_format}
                        </span>
                      </h4>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-fg-muted">
                        {(period.homework.tasks ?? []).map((task: string, index: number) => (
                          <li key={index}>{task}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            ))}
          </Tabs.Content>

          <Tabs.Content value="knowledge" className="flex flex-col gap-8">
            <Section title="Concepts" count={(knowledge.concepts ?? []).length}>
              <div className="grid gap-3 md:grid-cols-2">
                {(knowledge.concepts as Any[]).map((concept) => (
                  <Card key={concept.concept_id} className="border-l-2 border-l-accent">
                    <CardContent className="pt-5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-bold uppercase tracking-wide text-fg-faint">
                          {labelFor(concept.importance ?? "")}
                        </span>
                      </div>
                      <h4 className="mt-1 font-semibold">{concept.name}</h4>
                      <p className="mt-1 text-sm text-fg-muted">{concept.summary}</p>
                      <EvidenceList evidence={concept.evidence as Evidence[]} />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </Section>

            <Section title="Formulae" count={(knowledge.formulae ?? []).length}>
              <div className="grid gap-3 md:grid-cols-2">
                {(knowledge.formulae as Any[]).map((formula, index) => (
                  <Card key={index} className="border-l-2 border-l-grounded">
                    <CardContent className="pt-5">
                      <h4 className="font-semibold">{formula.name}</h4>
                      <p className="mt-1 font-mono text-sm">{formula.expression ?? formula.plain}</p>
                      <EvidenceList evidence={formula.evidence as Evidence[]} />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </Section>

            <Section title="Misconceptions" count={(knowledge.misconceptions ?? []).length}>
              <div className="flex flex-col gap-3">
                {(knowledge.misconceptions as Any[]).map((item) => (
                  <Card key={item.misconception_id} className="border-l-2 border-l-warning">
                    <CardContent className="pt-5">
                      <p className="font-medium">{item.statement}</p>
                      <p className="mt-1 text-sm text-fg-muted">
                        <span className="font-medium">Why:</span> {item.why_it_happens}
                      </p>
                      <p className="mt-1 text-sm text-fg-muted">
                        <span className="font-medium">Correction:</span> {item.correction}
                      </p>
                      <EvidenceList evidence={item.evidence as Evidence[]} />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </Section>
          </Tabs.Content>

          <Tabs.Content value="activities" className="grid gap-3 md:grid-cols-2">
            {activities.map((activity) => (
              <Card key={activity.activity_id}>
                <CardContent className="pt-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="accent">{labelFor(activity.type)}</Badge>
                    <Badge>{activity.duration_minutes} min</Badge>
                  </div>
                  <h4 className="mt-2 font-semibold">{activity.title}</h4>
                  {(activity.materials ?? []).length ? (
                    <p className="mt-2 text-xs text-fg-faint">
                      Materials: {(activity.materials as string[]).join(", ")}
                    </p>
                  ) : null}
                  <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-fg-muted">
                    {(activity.teacher_instructions as string[]).map((step, index) => (
                      <li key={index}>{step}</li>
                    ))}
                  </ol>
                  {activity.differentiation ? (
                    <dl className="mt-3 space-y-1 text-sm">
                      <div>
                        <dt className="inline font-medium">Support: </dt>
                        <dd className="inline text-fg-muted">{activity.differentiation.support}</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Extension: </dt>
                        <dd className="inline text-fg-muted">
                          {activity.differentiation.extension}
                        </dd>
                      </div>
                    </dl>
                  ) : null}
                </CardContent>
              </Card>
            ))}
          </Tabs.Content>

          <Tabs.Content value="assessments" className="flex flex-col gap-8">
            <div className="flex flex-wrap gap-2">
              <Badge>{items.length} items</Badge>
              <Badge>{assessments.total_marks} marks</Badge>
            </div>

            <Section title="Questions" count={items.length}>
              <ol className="flex flex-col gap-3">
                {items.map((item, index) => (
                  <li key={item.item_id}>
                    <Card>
                      <CardContent className="pt-5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-xs text-fg-faint">Q{index + 1}</span>
                          <Badge tone="accent">{labelFor(item.kind)}</Badge>
                          <Badge>{labelFor(item.bloom_level)}</Badge>
                          <Badge>{item.marks} marks</Badge>
                        </div>
                        <p className="mt-2">{item.stem}</p>
                        {item.options ? (
                          <ol className="mt-3 space-y-1.5 text-sm">
                            {(item.options as Any[]).map((option) => (
                              <li key={option.label} className="flex gap-2">
                                <span className="font-mono font-semibold">{option.label}.</span>
                                <span>{option.text}</span>
                              </li>
                            ))}
                          </ol>
                        ) : null}
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ol>
            </Section>

            {/* The answer key is a distinct section, mirroring the PDF where it
                sits behind a page break. A teacher hands out the questions. */}
            <Section title="Answer key" count={items.length}>
              <div className="rounded-lg border-2 border-dashed border-warning/40 bg-warning-subtle p-4">
                <p className="mb-4 text-sm font-medium text-warning">
                  Answers and rubrics — keep separate from the question paper.
                </p>
                <ol className="flex flex-col gap-3">
                  {items.map((item, index) => (
                    <li key={item.item_id} className="rounded-md bg-raised p-3">
                      <p className="text-sm">
                        <span className="font-mono text-xs text-fg-faint">Q{index + 1}. </span>
                        <span className="font-medium">
                          {item.options
                            ? (item.options as Any[]).find((o) => o.is_correct)?.label
                            : null}{" "}
                        </span>
                        {item.answer}
                      </p>
                      {item.working ? (
                        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded bg-surface p-2 text-xs">
                          {item.working}
                        </pre>
                      ) : null}
                      {item.rubric ? (
                        <ul className="mt-2 space-y-1 text-xs text-fg-muted">
                          {(item.rubric.levels as Any[]).map((level) => (
                            <li key={level.label}>
                              <span className="font-medium">
                                {level.label} ({level.marks}):
                              </span>{" "}
                              {level.descriptor}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </div>
            </Section>

            {mcqs.length === 0 && written.length === 0 ? (
              <EmptyState title="No assessment items" />
            ) : null}
          </Tabs.Content>

          <Tabs.Content value="gaps" className="flex flex-col gap-3">
            {gaps.length === 0 ? (
              <EmptyState title="No learning gaps recorded">
                This package did not identify predictable misconceptions for its concepts.
              </EmptyState>
            ) : null}
            {gaps.map((gap) => (
              <Card key={gap.gap_id} className="border-l-2 border-l-danger">
                <CardContent className="pt-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      tone={
                        gap.severity === "high"
                          ? "danger"
                          : gap.severity === "medium"
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {labelFor(gap.severity)} severity
                    </Badge>
                  </div>
                  <p className="mt-2 font-medium">{gap.misconception}</p>

                  <h4 className="mt-3 text-sm font-semibold">Diagnostics</h4>
                  <ul className="mt-1 space-y-2">
                    {(gap.diagnostic_questions as Any[]).map((question, index) => (
                      <li key={index} className="rounded-md bg-surface p-3 text-sm">
                        <p>{question.question}</p>
                        <p className="mt-1 text-xs text-fg-faint">Reveals: {question.reveals}</p>
                      </li>
                    ))}
                  </ul>

                  <h4 className="mt-3 text-sm font-semibold">Remediation</h4>
                  <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-fg-muted">
                    {(gap.remediation as Any[]).map((step, index) => (
                      <li key={index}>
                        {step.action}
                        <span className="block text-xs text-fg-faint">{step.rationale}</span>
                      </li>
                    ))}
                  </ol>

                  <EvidenceList evidence={gap.evidence as Evidence[]} />
                </CardContent>
              </Card>
            ))}
          </Tabs.Content>

          <Tabs.Content value="validation" className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Card>
                <CardContent className="pt-5">
                  <p className="text-sm text-fg-muted">Status</p>
                  <Badge tone={VALIDATION_TONE[validation.status] ?? "neutral"} className="mt-1">
                    {labelFor(String(validation.status ?? ""))}
                  </Badge>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-5">
                  <p className="text-sm text-fg-muted">Grounding score</p>
                  <p className="mt-1 text-2xl font-bold tabular-nums">
                    {typeof validation.grounding_score === "number"
                      ? `${Math.round(validation.grounding_score * 100)}%`
                      : "—"}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-5">
                  <p className="text-sm text-fg-muted">Profile ruleset</p>
                  <p className="mt-1 font-medium">{labelFor(String(validation.profile_ruleset ?? "—"))}</p>
                </CardContent>
              </Card>
            </div>

            {(validation.issues ?? []).length ? (
              <Card>
                <CardContent className="pt-5">
                  <h3 className="text-sm font-semibold">Issues</h3>
                  <ul className="mt-2 space-y-2">
                    {(validation.issues as Any[]).map((issue, index) => (
                      <li key={index} className="rounded-md border border-border p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge tone={issue.severity === "error" ? "danger" : "warning"}>
                            {labelFor(issue.severity ?? "")}
                          </Badge>
                          <span className="font-mono text-xs text-fg-faint">{issue.code}</span>
                        </div>
                        <p className="mt-1 text-fg-muted">{issue.message ?? issue.detail}</p>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ) : (
              <EmptyState title="No issues found">
                Every rule class — schema, coverage, consistency and grounding — passed.
              </EmptyState>
            )}
          </Tabs.Content>
          <Tabs.Content value="pipeline">
            <PipelinePanel provenance={tkp.provenance} generator={tkp.generator} />
          </Tabs.Content>
          <Tabs.Content value="evaluation">
            {/* Mounted only when the tab is active — Radix unmounts inactive
                content, so the evaluation request is not made until asked for. */}
            {packageId ? <EvaluationPanel packageId={packageId} /> : null}
          </Tabs.Content>
        </div>
      </Tabs.Root>
    </div>
  );
}

export default function PackagePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <ViewerBody />
    </Suspense>
  );
}
