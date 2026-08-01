import type { Evidence } from "../api/types";
import { formatPercent } from "../utils/format";

/**
 * Surfaces the source-document citation behind an extracted claim. Grounding
 * is the project's central claim, so evidence is never hidden entirely —
 * it is tucked behind a `<details>` disclosure (native, no JS state, works
 * with find-in-page) to keep dense sections scannable while staying one
 * click from proof.
 */
export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null;

  return (
    <details className="ef-evidence">
      <summary className="ef-evidence__summary">
        Source{evidence.length > 1 ? `s (${evidence.length})` : ""}
      </summary>
      <ul className="ef-evidence__list">
        {evidence.map((item, idx) => (
          <li key={`${item.chunk_id}-${idx}`} className="ef-evidence__item">
            <blockquote className="ef-evidence__quote">&ldquo;{item.quote}&rdquo;</blockquote>
            <div className="ef-evidence__meta">
              {item.page != null ? <span>p. {item.page}</span> : null}
              <span>confidence {formatPercent(item.confidence)}</span>
              <span className="ef-muted">{item.chunk_id}</span>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
