import { AlertTriangle, FileWarning, ScanLine } from "lucide-react";
import type { OcrProvenance } from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * What a machine read off a page image, and how much to trust it.
 *
 * This is the one caveat in the whole package that cannot be caught further
 * down. Every later stage grounds its claims in evidence spans checked against
 * the source text — so if OCR misread the source, those checks validate the
 * error rather than catching it. Grounding cannot see below itself. The teacher
 * is the only reader who can compare this against the paper original, which is
 * why the notice sits at the top of the package rather than in a provenance tab.
 *
 * Three rules, and they are the whole design:
 *
 *   1. Absent means absent. No OCR, no notice — not an empty card saying "none".
 *   2. A null confidence is unknown, never zero and never a score. It gets a
 *      sentence, not a number and not a bar.
 *   3. `failed_pages` is missing content, not low-quality content, and is said
 *      in those words: nothing in the package covers those pages at all.
 */

/** Beyond this the list is a wall of numbers nobody reads; the count still tells the truth. */
const MAX_PAGES_SHOWN = 20;

function pageNumbers(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value.filter((n): n is number => typeof n === "number" && Number.isFinite(n));
}

function ratio(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Narrow the untyped package payload to the contract.
 *
 * `GET /packages/{id}` is returned as an opaque object, so every field is
 * checked before it is rendered. Assuming a shape is what put an object where
 * React expected a string and took a production page down with error #31.
 */
export function parseOcr(value: unknown): OcrProvenance | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;

  const engine = typeof record.engine === "string" ? record.engine.trim() : "";
  const pages = pageNumbers(record.pages);
  const failedPages = pageNumbers(record.failed_pages);

  // A record naming neither an engine nor a page describes nothing.
  if (!engine && pages.length === 0 && failedPages.length === 0) return null;

  return {
    engine,
    pages,
    failed_pages: failedPages,
    confidence: ratio(record.confidence),
    min_confidence: ratio(record.min_confidence),
  };
}

function pageList(pages: number[]): string {
  const shown = pages.slice(0, MAX_PAGES_SHOWN).join(", ");
  const remaining = pages.length - MAX_PAGES_SHOWN;
  return remaining > 0 ? `${shown} and ${remaining} more` : shown;
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function OcrNotice({ ocr: raw }: { ocr: unknown }) {
  const ocr = parseOcr(raw);
  if (!ocr) return null;

  const engine = ocr.engine || "the OCR engine";
  const { confidence, min_confidence: minConfidence } = ocr;
  // Formatted up front so the JSX below never has to assert a non-null number
  // it cannot prove — the narrowing is done once, here, where it is checkable.
  const confidenceLabel = confidence === null ? null : percent(confidence);
  const thresholdLabel = minConfidence === null ? null : percent(minConfidence);
  const belowThreshold = confidence !== null && minConfidence !== null && confidence < minConfidence;
  const missing = ocr.failed_pages.length > 0;
  const severe = belowThreshold || missing;

  return (
    <section
      aria-labelledby="ocr-provenance"
      className={cn(
        "rounded-lg border p-5",
        missing
          ? "border-danger/30 bg-danger-subtle"
          : belowThreshold
            ? "border-warning/30 bg-warning-subtle"
            : "border-border bg-raised",
      )}
    >
      <div className="flex items-start gap-3">
        {severe ? (
          <AlertTriangle
            className={cn("mt-0.5 size-5 shrink-0", missing ? "text-danger" : "text-warning")}
            aria-hidden
          />
        ) : (
          <ScanLine className="mt-0.5 size-5 shrink-0 text-fg-faint" aria-hidden />
        )}

        <div className="min-w-0 flex-1">
          {/* The heading carries the severity in words. Colour alone would say
              nothing in greyscale, in print, or to a colour-blind reader. */}
          <h2 id="ocr-provenance" className="font-semibold">
            {missing
              ? "Some pages could not be read — content is missing"
              : belowThreshold
                ? "Check these pages: they were read from images, below the accuracy threshold"
                : "Some pages were read by OCR"}
          </h2>

          {ocr.pages.length > 0 ? (
            <p className="mt-1.5 text-sm text-fg-muted">
              {ocr.pages.length} page{ocr.pages.length === 1 ? "" : "s"} had no text layer, so{" "}
              <span className="font-medium">{engine}</span> read {ocr.pages.length === 1 ? "it" : "them"}{" "}
              from the page image
              {/* [overflow-wrap:anywhere] — a long page list must wrap rather
                  than widen the page on a 360px screen. */}
              <span className="[overflow-wrap:anywhere]">: {pageList(ocr.pages)}</span>.
            </p>
          ) : null}

          <p className="mt-2 text-sm text-fg-muted">
            {confidenceLabel === null ? (
              <>
                <span className="font-medium">Accuracy unknown.</span> {engine} does not report a
                confidence score, so there is no measure of how well it read. Unknown is not the same
                as good — treat these pages as unverified until you have compared them with the
                source.
              </>
            ) : belowThreshold ? (
              <>
                <span className="font-medium">
                  Reported confidence {confidenceLabel}, below the {thresholdLabel} threshold for
                  this run.
                </span>{" "}
                Check these pages against the original before teaching from them: at this level a
                misread word is likely, and a misread formula or date changes the meaning without
                looking wrong.
              </>
            ) : (
              <>
                <span className="font-medium">Reported confidence {confidenceLabel}</span>
                {thresholdLabel
                  ? `, at or above the ${thresholdLabel} threshold for this run.`
                  : "."}{" "}
                That is the engine&rsquo;s own estimate of its reading, not a check of the result.
              </>
            )}
          </p>

          {missing ? (
            <p className="mt-2 flex items-start gap-2 text-sm text-fg-muted">
              <FileWarning className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
              <span>
                <span className="font-medium">
                  {ocr.failed_pages.length} page{ocr.failed_pages.length === 1 ? "" : "s"} could not
                  be read at all
                </span>
                <span className="[overflow-wrap:anywhere]"> ({pageList(ocr.failed_pages)})</span>.
                Whatever those pages contained is <span className="font-medium">not in this
                package</span> — not summarised, not cited, not taught. Nothing below is wrong
                because of it, but something may be absent.
              </span>
            </p>
          ) : null}

          <p className="mt-2 text-xs leading-relaxed text-fg-faint">
            Why this is flagged at all: every citation in this package is checked against the text
            extracted from the document. When that text came from OCR, a misreading is checked
            against itself and passes. You are the only reader who can compare it with the paper.
          </p>
        </div>
      </div>
    </section>
  );
}
