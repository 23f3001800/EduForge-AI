"use client";

import { ChevronDown, Quote, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";

export interface Evidence {
  chunk_id?: string;
  quote?: string;
  page?: number | null;
  confidence?: number | null;
}

/**
 * The citation behind a claim.
 *
 * Grounding is the central claim of this product, so it gets a badge that is
 * visible without interaction and a disclosure for the quote itself. The badge
 * alone used to be a small link at the bottom of a card — technically present,
 * and the easiest thing on the card to miss.
 *
 * Absent evidence renders nothing at all. Some content is legitimately
 * ungrounded (a mentor anecdote the pipeline writes deliberately), and an empty
 * "no citation" chip on every one of those would be noise implying a defect.
 */
export function EvidenceList({ evidence }: { evidence?: Evidence[] | null }) {
  const [open, setOpen] = useState(false);
  if (!evidence || evidence.length === 0) return null;

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-grounded/25 bg-grounded-subtle px-2.5 py-0.5 text-xs font-medium text-grounded transition-colors hover:bg-grounded/15"
      >
        <ShieldCheck className="size-3" aria-hidden />
        Grounded
        <span className="text-grounded/70">
          · {evidence.length} {evidence.length === 1 ? "source" : "sources"}
        </span>
        <ChevronDown
          className={`size-3 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {open ? (
        <ul className="mt-2 space-y-2">
          {evidence.map((item, index) => (
            <li
              key={`${item.chunk_id}-${index}`}
              className="rounded-md border-l-2 border-grounded/40 bg-grounded-subtle px-3 py-2"
            >
              <blockquote className="flex gap-2 text-sm italic text-fg-muted">
                <Quote className="mt-0.5 size-3.5 shrink-0 text-grounded" aria-hidden />
                <span className="[overflow-wrap:anywhere]">{item.quote}</span>
              </blockquote>
              <p className="mt-1 flex flex-wrap gap-x-3 text-xs font-medium text-grounded">
                {item.page ? <span>p. {item.page}</span> : null}
                {item.chunk_id ? <span className="font-mono">{item.chunk_id}</span> : null}
                {typeof item.confidence === "number" ? (
                  <span>confidence {Math.round(item.confidence * 100)}%</span>
                ) : null}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** A claim's provenance, inline — used where a full disclosure is too heavy. */
export function GroundedBadge({ count }: { count: number }) {
  if (!count) return null;
  return (
    <Badge tone="grounded">
      <ShieldCheck className="size-3" aria-hidden /> {count}
    </Badge>
  );
}
