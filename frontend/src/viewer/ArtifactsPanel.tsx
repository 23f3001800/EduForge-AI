import { useEffect, useState } from "react";
import { downloadArtifact, getArtifacts } from "../api";
import type { Artifact } from "../api/types";
import { describeError } from "../utils/errors";

/**
 * The rendered files: three PDFs and a Markdown bundle.
 *
 * These were generated, stored and served by the backend but rendered nowhere,
 * so the most directly useful output of the whole pipeline — the thing a
 * teacher actually prints — was unreachable from the UI.
 *
 * A listing row can come back `status: "failed"`, which happens when a stage
 * ran out of budget and skipped an artifact. Those render as disabled rows with
 * the reason, never as a link that 404s: offering a download that cannot work
 * is worse than saying plainly that it is not there.
 */

const LABELS: Record<string, { title: string; hint: string }> = {
  lesson_plan_pdf: {
    title: "Lesson plan",
    hint: "Per-period plan with timings and concept sequencing.",
  },
  teacher_guide_pdf: {
    title: "Teacher guide",
    hint: "Scripts, activities, misconceptions, gaps and remediation.",
  },
  assessment_book_pdf: {
    title: "Assessment book",
    hint: "Questions first, answer key behind a page break.",
  },
  markdown_bundle: {
    title: "Markdown bundle",
    hint: "The same content as plain text.",
  },
  tkp_json: {
    title: "Package JSON",
    hint: "The complete structured package.",
  },
};

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ArtifactsPanel({ packageId }: { packageId: string }) {
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setArtifacts(null);
    setError(null);
    getArtifacts(packageId)
      .then((listing) => {
        if (!cancelled) setArtifacts(listing.artifacts);
      })
      .catch((err) => {
        if (!cancelled) setError(describeError(err).body);
      });
    return () => {
      cancelled = true;
    };
  }, [packageId]);

  async function onDownload(kind: string) {
    setBusy(kind);
    try {
      await downloadArtifact(packageId, kind);
    } catch (err) {
      setError(describeError(err).body);
    } finally {
      setBusy(null);
    }
  }

  if (error && !artifacts) {
    return (
      <section className="ef-card ef-artifacts" aria-labelledby="ef-artifacts-title">
        <h2 id="ef-artifacts-title" className="ef-card__title">
          Downloads
        </h2>
        <p className="ef-artifacts__error">{error}</p>
      </section>
    );
  }

  if (!artifacts) {
    return (
      <section className="ef-card ef-artifacts" aria-labelledby="ef-artifacts-title">
        <h2 id="ef-artifacts-title" className="ef-card__title">
          Downloads
        </h2>
        <p className="ef-artifacts__hint">Loading files…</p>
      </section>
    );
  }

  // Absent content is omitted, not faked: a package with no rendered artifacts
  // shows nothing here rather than an empty box implying something is missing.
  if (artifacts.length === 0) return null;

  return (
    <section className="ef-card ef-artifacts" aria-labelledby="ef-artifacts-title">
      <h2 id="ef-artifacts-title" className="ef-card__title">
        Downloads
      </h2>
      <ul className="ef-artifacts__list">
        {artifacts.map((artifact) => {
          const label = LABELS[artifact.kind] ?? { title: artifact.kind, hint: "" };
          const ready = artifact.status === "ready" && artifact.bytes > 0;
          return (
            <li key={artifact.kind} className="ef-artifacts__item">
              <div className="ef-artifacts__meta">
                <span className="ef-artifacts__title">{label.title}</span>
                {label.hint ? <span className="ef-artifacts__hint">{label.hint}</span> : null}
              </div>
              <div className="ef-artifacts__action">
                <span className="ef-artifacts__size">{formatBytes(artifact.bytes)}</span>
                {ready ? (
                  <button
                    type="button"
                    className="ef-button ef-button--secondary ef-button--sm"
                    onClick={() => onDownload(artifact.kind)}
                    disabled={busy === artifact.kind}
                  >
                    {busy === artifact.kind ? "Preparing…" : "Download"}
                  </button>
                ) : (
                  <span className="ef-artifacts__unavailable" title="Not produced for this run">
                    Not available
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {error ? <p className="ef-artifacts__error">{error}</p> : null}
    </section>
  );
}
