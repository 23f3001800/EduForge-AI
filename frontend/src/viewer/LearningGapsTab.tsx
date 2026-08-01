import type { LearningGap, Severity } from "../api/types";
import { Badge } from "../components/ui/Badge";
import type { BadgeTone } from "../components/ui/Badge";
import type { PackageLookups } from "../utils/lookups";
import { EvidenceList } from "./EvidenceList";

const SEVERITY_ORDER: Severity[] = ["high", "medium", "low"];
const SEVERITY_TONE: Record<Severity, BadgeTone> = { high: "danger", medium: "warning", low: "info" };

export function LearningGapsTab({ gaps, lookups }: { gaps: LearningGap[]; lookups: PackageLookups }) {
  if (gaps.length === 0) return null;

  const bySeverity = SEVERITY_ORDER.map((severity) => ({
    severity,
    items: gaps.filter((g) => g.severity === severity),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="ef-stack">
      <p className="ef-muted">
        Anticipated misconceptions, sorted by severity, with a diagnostic question and remediation
        for each.
      </p>
      {bySeverity.map(({ severity, items }) => (
        <div key={severity} className="ef-stack">
          <h3 className="ef-section-title">
            <Badge tone={SEVERITY_TONE[severity]}>{severity} severity</Badge>
          </h3>
          {items.map((gap) => (
            <article className="ef-card" key={gap.gap_id}>
              <p className="ef-assessment-item__stem">{gap.misconception}</p>

              {gap.concept_ids.length > 0 ? (
                <div className="ef-row">
                  {gap.concept_ids.map((id) => (
                    <span className="ef-tag" key={id}>
                      {lookups.conceptName(id)}
                    </span>
                  ))}
                </div>
              ) : null}

              {gap.diagnostic_questions.length > 0 ? (
                <div>
                  <h4 className="ef-subheading ef-subheading--sm">Diagnostic questions</h4>
                  <ul className="ef-bullet-list">
                    {gap.diagnostic_questions.map((q, i) => (
                      <li key={i}>
                        {q.question}
                        <div className="ef-muted">
                          A wrong answer like &ldquo;{q.expected_wrong_answer}&rdquo; reveals: {q.reveals}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {gap.remediation.length > 0 ? (
                <div>
                  <h4 className="ef-subheading ef-subheading--sm">Remediation</h4>
                  <ul className="ef-bullet-list">
                    {gap.remediation.map((step, i) => (
                      <li key={i}>
                        {step.action} <span className="ef-muted">({step.estimated_minutes} min)</span>
                        <div className="ef-muted">{step.rationale}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <EvidenceList evidence={gap.evidence} />
            </article>
          ))}
        </div>
      ))}
    </div>
  );
}
