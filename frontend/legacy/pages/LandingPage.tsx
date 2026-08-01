import { useEffect, useState } from "react";
import { getSamples } from "../api";
import type { SampleSummary } from "../api/types";
import { Link } from "../router/router";

/**
 * The landing page.
 *
 * Two audiences arrive here and want different things in the first ten seconds:
 * a teacher wants to know what they get and whether to trust it, an evaluator
 * wants to see the system work. The order below serves both — what it produces,
 * then real output, then the versatility proof, then how to run it.
 *
 * Copy is verbatim from `docs/14-design-system.md` §7.1. Every number in the
 * comparison table is a measured run, not an illustration, and the samples the
 * CTAs link to are the ones those numbers came from.
 */

const FEATURES = [
  {
    label: "Multi-period lesson plan",
    body:
      "Not a fixed five periods — the count is derived from how much the chapter actually " +
      "covers, paced to the period length you set.",
  },
  {
    label: "Teacher scripts",
    body:
      "Minute-by-minute: what to say, what to write on the board, the questions students " +
      "are likely to ask.",
  },
  {
    label: "Activities & assessments",
    body:
      "Classroom activities plus an assessment bank with rubrics — the answer key is " +
      "generated as a separate section, kept apart from the questions.",
  },
  {
    label: "Gap analysis, with citations",
    body:
      "Likely misconceptions ranked by how much later material depends on them, and a " +
      "citation back to the source for every concept, definition and claim.",
  },
];

const STEPS = [
  {
    title: "Upload.",
    body:
      "PDF, DOCX, PPTX, TXT or Markdown, up to 25MB. Answer a couple of optional questions — " +
      "period length, teaching style — or skip them; the defaults are good.",
  },
  {
    title: "Watch it build.",
    body:
      "Ten pipeline stages, live progress, about 5–7 minutes. Close the tab if you need to — " +
      "the run keeps going and the page picks up where it left off.",
  },
  {
    title: "Review, download, teach.",
    body:
      "A tabbed package in the browser, plus a Lesson Plan PDF, a Teacher Guide PDF, an " +
      "Assessment Book PDF (questions first, answer key behind a page break), and a " +
      "Markdown bundle.",
  },
];

const COMPARISON: Array<[string, string, string]> = [
  ["Subject → profile", "Physics → quantitative", "History → narrative"],
  ["Formulae extracted", "1", "0"],
  ["Assessment mix", "3 numerical, 2 MCQ, 1 long, 1 short", "0 numerical, 1 MCQ, 3 long, 2 short"],
  ["Activity chosen", "Experiment", "Debate"],
  ["Validation", "Pass with warnings", "Pass with warnings"],
];

const LIMITS = [
  "First version. Scanned or photographed pages are rejected with a clear error, not OCR'd.",
  "Runs on free-tier models by default, so output quality is bounded by what those models can do — swap the config for a stronger model and the same pipeline runs unchanged.",
  "Uploaded documents live in memory today; a server restart clears them mid-run.",
];

function useSamples(): SampleSummary[] {
  const [samples, setSamples] = useState<SampleSummary[]>([]);
  useEffect(() => {
    let cancelled = false;
    // Failing to load samples must not break the page — the landing page is
    // still worth reading without them, so this degrades to hiding the links
    // rather than showing an error a visitor can do nothing about.
    getSamples()
      .then((response) => {
        if (!cancelled) setSamples(response.samples);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return samples;
}

function sampleFor(samples: SampleSummary[], profile: string): SampleSummary | undefined {
  return samples.find((s) => s.pedagogy_profile === profile);
}

export function LandingPage() {
  const samples = useSamples();
  const physics = sampleFor(samples, "quantitative");
  const history = sampleFor(samples, "narrative");
  const anySample = physics ?? history ?? samples[0];

  return (
    <div className="ef-landing">
      <section className="ef-landing__hero">
        <div className="ef-landing__hero-copy">
          <p className="ef-eyebrow">Document in → classroom package out</p>
          <h1 className="ef-landing__title">
            Turn a chapter into a week of classroom-ready teaching — with every claim traced
            back to the page it came from.
          </h1>
          <p className="ef-landing__subhead">
            Upload a PDF, DOCX, PPTX or TXT chapter. Get a multi-period lesson plan, teacher
            scripts, activities, an assessment bank with answer keys and rubrics, a
            learning-gap analysis, and a citation on every factual claim — in about 5–7
            minutes.
          </p>
          <div className="ef-landing__cta">
            <Link to="/upload" className="ef-button ef-button--primary">
              Upload a document
            </Link>
            {anySample ? (
              <Link
                to={`/packages/${anySample.package_id}`}
                className="ef-button ef-button--secondary"
              >
                See a sample package
              </Link>
            ) : null}
          </div>
          <p className="ef-landing__microcopy">
            No account. Nothing is billed to you on the default free-tier setup.
          </p>
        </div>

        <aside className="ef-landing__proof" aria-label="Example output">
          <article className="ef-card ef-card--concept">
            <header className="ef-card__head">
              <span className="ef-card__kind">Concept · core</span>
              <span className="ef-badge ef-badge--grounded">◆ Grounded</span>
            </header>
            <h2 className="ef-card__title">Inertia</h2>
            <p className="ef-card__body">
              A body resists any change to its state of rest or uniform motion.
            </p>
            <p className="ef-card__evidence">
              <span className="ef-card__evidence-loc">p. 1</span>
              <q>A body continues in its state of rest or uniform motion</q>
              <span className="ef-card__evidence-conf">confidence 100%</span>
            </p>
          </article>
          <p className="ef-landing__caption">
            Real output from the pipeline — Newton's Laws of Motion, Grade 9–10 Physics.
          </p>
        </aside>
      </section>

      <section className="ef-landing__section" aria-labelledby="ef-what-you-get">
        <h2 id="ef-what-you-get" className="ef-landing__section-title">
          What you get
        </h2>
        <ul className="ef-landing__features">
          {FEATURES.map((feature) => (
            <li key={feature.label} className="ef-landing__feature">
              <h3>{feature.label}</h3>
              <p>{feature.body}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="ef-landing__section" aria-labelledby="ef-versatility">
        <h2 id="ef-versatility" className="ef-landing__section-title">
          The same pipeline. Two different outputs.
        </h2>
        <p className="ef-landing__lede">
          Nothing in this system branches on a subject name — a test in the codebase fails the
          build if it does. A chapter is classified as quantitative, conceptual, narrative,
          procedural or mixed, and that classification is what changes the output, not a switch
          statement reading &ldquo;if physics&rdquo;. Two real runs against the live instance,
          same code path:
        </p>

        <div className="ef-table-scroll">
          <table className="ef-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="ef-visually-hidden">Measure</span>
                </th>
                <th scope="col">physics.pdf</th>
                <th scope="col">history.docx</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map(([label, left, right]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{left}</td>
                  <td>{right}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="ef-landing__caption">
          Zero numerical questions on a history chapter isn&rsquo;t a missing feature — it&rsquo;s
          the narrative profile working as designed. The validator is profile-conditioned, so it
          scores that absence as correct rather than flagging a gap.
        </p>

        {physics || history ? (
          <p className="ef-landing__sample-links">
            {physics ? (
              <Link to={`/packages/${physics.package_id}`}>Open the physics sample →</Link>
            ) : null}
            {history ? (
              <Link to={`/packages/${history.package_id}`}>Open the history sample →</Link>
            ) : null}
          </p>
        ) : null}
      </section>

      <section className="ef-landing__section" aria-labelledby="ef-how">
        <h2 id="ef-how" className="ef-landing__section-title">
          How it works
        </h2>
        <ol className="ef-landing__steps">
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <span className="ef-landing__step-number" aria-hidden="true">
                {index + 1}
              </span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="ef-landing__strip" aria-labelledby="ef-for-review">
        <h2 id="ef-for-review" className="ef-landing__section-title">
          Built for review
        </h2>
        <p>
          This was built for the AI Engineer assignment. The pipeline, the schema, the API and
          the architecture decisions are documented in full.
        </p>
        <p className="ef-landing__links">
          <a href="/api/v1/docs">API docs</a>
          <a href="/healthz">Health</a>
          <a href="/metrics">Metrics</a>
        </p>
      </section>

      <section className="ef-landing__section ef-landing__limits" aria-labelledby="ef-limits">
        <h2 id="ef-limits" className="ef-landing__section-title">
          Honest limits
        </h2>
        <ul>
          {LIMITS.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
