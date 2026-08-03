"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowRight, FileText, Quote, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getSamples } from "@/lib/api";

/**
 * The landing page.
 *
 * Two audiences arrive here wanting different things: a teacher wants to know
 * what they get and whether to trust it; an evaluator wants to see the system
 * work. Hence the order — what it produces, real output, the versatility proof,
 * then how to run it.
 *
 * Every number below is measured from a real run, and the limits section is on
 * the page rather than buried, because a product page that only lists strengths
 * is the kind nobody believes.
 */

const FEATURES = [
  {
    label: "Multi-period lesson plan",
    body: "Not a fixed five periods — the count is derived from how much the chapter actually covers, paced to the period length you set.",
  },
  {
    label: "Teacher scripts",
    body: "Minute-by-minute: what to say, what to write on the board, the questions students are likely to ask.",
  },
  {
    label: "Activities & assessments",
    body: "Classroom activities plus an assessment bank with rubrics — the answer key is a separate section, kept apart from the questions.",
  },
  {
    label: "Gap analysis, with citations",
    body: "Likely misconceptions ranked by how much later material depends on them, and a citation for every concept and claim.",
  },
];

const COMPARISON: Array<[string, string, string]> = [
  ["Subject → profile", "Physics → quantitative", "History → narrative"],
  ["Formulae extracted", "1", "0"],
  ["Assessment mix", "3 numerical, 2 MCQ, 1 long, 1 short", "0 numerical, 1 MCQ, 3 long, 2 short"],
  ["Activity chosen", "Experiment", "Debate"],
];

const STEPS = [
  ["Upload", "PDF, DOCX, PPTX or TXT, up to 25 MB. Answer a couple of optional questions, or skip them — the defaults are good."],
  ["Watch it build", "Ten pipeline stages, live progress, about 5–7 minutes. Close the tab; the run keeps going and the page picks it up."],
  ["Review and teach", "A tabbed package in the browser, plus lesson plan, teacher guide and assessment book PDFs."],
];

const LIMITS = [
  "Pages with no text layer are read by OCR. The package names those pages and what the engine's confidence was, because a misread there is checked against itself by everything downstream — a teacher is the only one who can catch it.",
  "Runs on free-tier models by default, so quality is bounded by what those models can do — the config swaps to a stronger model unchanged.",
  "Uploaded documents live in memory today; a server restart clears them.",
];

export default function LandingPage() {
  const { data } = useQuery({ queryKey: ["samples"], queryFn: getSamples });
  const samples = data?.samples ?? [];
  const physics = samples.find((s) => s.pedagogy_profile === "quantitative");
  const history = samples.find((s) => s.pedagogy_profile === "narrative");

  return (
    <div className="flex flex-col gap-16 md:gap-24">
      <section className="grid items-center gap-10 md:grid-cols-[1.1fr_1fr]">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        >
          <p className="text-xs font-bold uppercase tracking-[0.08em] text-fg-faint">
            Document in → classroom package out
          </p>
          <h1 className="mt-3 text-balance text-3xl font-extrabold leading-[1.1] tracking-tight sm:text-4xl lg:text-5xl">
            Turn a chapter into a week of classroom-ready teaching
          </h1>
          <p className="mt-4 max-w-xl text-pretty text-base leading-relaxed text-fg-muted">
            Upload a chapter and get a multi-period lesson plan, teacher scripts, activities, an
            assessment bank with answer keys and rubrics, and a learning-gap analysis — with a
            citation on every factual claim, in about 5–7 minutes.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button asChild size="lg">
              <Link href="/upload">
                Upload a document <ArrowRight />
              </Link>
            </Button>
            {samples.length > 0 ? (
              <Button asChild variant="secondary" size="lg">
                {/* `/packages?id=` and never `/packages/<id>`: this is a static
                    export, so there is no pre-built HTML at a path segment and
                    the request falls through to the SPA fallback — which
                    re-rendered this very page and made the primary CTA a no-op. */}
                <Link href={`/packages?id=${(physics ?? samples[0]).package_id}`}>
                  See a sample package
                </Link>
              </Button>
            ) : null}
          </div>
          <p className="mt-3 text-xs text-fg-faint">
            No account. Nothing is billed to you on the default free-tier setup.
          </p>
        </motion.div>

        <motion.aside
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.08, ease: [0.16, 1, 0.3, 1] }}
          aria-label="Example output"
        >
          <Card className="border-l-2 border-l-accent shadow-sm">
            <CardContent className="pt-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs font-bold uppercase tracking-wide text-fg-faint">
                  Concept · core
                </span>
                <Badge tone="grounded">
                  <ShieldCheck className="size-3" aria-hidden /> Grounded
                </Badge>
              </div>
              <h2 className="mt-2 text-lg font-semibold">Inertia</h2>
              <p className="mt-1 text-sm text-fg-muted">
                A body resists any change to its state of rest or uniform motion.
              </p>
              <figure className="mt-4 rounded-md border-l-2 border-grounded/40 bg-grounded-subtle px-3 py-2">
                <blockquote className="flex gap-2 text-sm italic text-fg-muted">
                  <Quote className="mt-0.5 size-3.5 shrink-0 text-grounded" aria-hidden />
                  <span className="[overflow-wrap:anywhere]">
                    A body continues in its state of rest or uniform motion
                  </span>
                </blockquote>
                <figcaption className="mt-1 text-xs font-medium text-grounded">
                  p. 1 · confidence 100%
                </figcaption>
              </figure>
            </CardContent>
          </Card>
          <p className="mt-2 text-xs text-fg-faint">
            Real output from the pipeline — Newton&rsquo;s Laws of Motion, Grade 9–10 Physics.
          </p>
        </motion.aside>
      </section>

      <section aria-labelledby="what-you-get">
        <h2 id="what-you-get" className="text-2xl font-bold tracking-tight">
          What you get
        </h2>
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((feature) => (
            <li key={feature.label}>
              <Card className="h-full transition-colors hover:border-accent/40">
                <CardContent className="pt-5">
                  <FileText className="size-5 text-accent" aria-hidden />
                  <h3 className="mt-3 font-semibold">{feature.label}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{feature.body}</p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="versatility">
        <h2 id="versatility" className="text-2xl font-bold tracking-tight">
          The same pipeline. Two different outputs.
        </h2>
        <p className="mt-3 max-w-3xl text-pretty leading-relaxed text-fg-muted">
          Nothing here branches on a subject name — a test fails the build if it does. A chapter is
          classified as quantitative, conceptual, narrative, procedural or mixed, and that
          classification changes the output. Two real runs against this instance, same code path:
        </p>

        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-3 pr-4 font-semibold" scope="col">
                  <span className="sr-only">Measure</span>
                </th>
                <th className="py-3 pr-4 font-semibold" scope="col">physics.pdf</th>
                <th className="py-3 font-semibold" scope="col">history.docx</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map(([label, left, right]) => (
                <tr key={label} className="border-b border-border/60">
                  <th scope="row" className="py-3 pr-4 text-left font-medium text-fg-muted">
                    {label}
                  </th>
                  <td className="py-3 pr-4">{left}</td>
                  <td className="py-3 font-medium text-grounded">{right}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-3 max-w-3xl text-sm text-fg-faint">
          Zero numerical questions on a history chapter isn&rsquo;t a missing feature — it&rsquo;s
          the narrative profile working as designed, and the validator is profile-conditioned so it
          scores that absence as correct.
        </p>

        {physics || history ? (
          <div className="mt-4 flex flex-wrap gap-4 text-sm font-semibold">
            {physics ? (
              <Link
                className="inline-flex min-h-11 items-center text-accent hover:underline"
                href={`/packages?id=${physics.package_id}`}
              >
                Open the physics sample →
              </Link>
            ) : null}
            {history ? (
              <Link
                className="inline-flex min-h-11 items-center text-accent hover:underline"
                href={`/packages?id=${history.package_id}`}
              >
                Open the history sample →
              </Link>
            ) : null}
          </div>
        ) : null}
      </section>

      <section aria-labelledby="how">
        <h2 id="how" className="text-2xl font-bold tracking-tight">
          How it works
        </h2>
        <ol className="mt-6 grid gap-6 md:grid-cols-3">
          {STEPS.map(([title, body], index) => (
            <li key={title} className="flex gap-3">
              <span
                aria-hidden
                className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-subtle text-sm font-bold text-accent"
              >
                {index + 1}
              </span>
              <div>
                <h3 className="font-semibold">{title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-fg-muted">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="limits" className="rounded-lg border border-border bg-surface p-6">
        <h2 id="limits" className="text-lg font-semibold">
          Honest limits
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed text-fg-muted">
          {LIMITS.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
