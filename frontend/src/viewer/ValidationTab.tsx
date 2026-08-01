import type { ValidationReport, ValidationStatus } from "../api/types";
import { Badge } from "../components/ui/Badge";
import type { BadgeTone } from "../components/ui/Badge";
import { Banner } from "../components/ui/Banner";
import { formatDateTime, formatPercent } from "../utils/format";

const STATUS_TONE: Record<ValidationStatus, "success" | "warning" | "danger"> = {
  pass: "success",
  pass_with_warnings: "warning",
  fail: "danger",
};

const STATUS_COPY: Record<ValidationStatus, { title: string; body: string }> = {
  pass: { title: "Validation passed", body: "Every automated check on this package passed." },
  pass_with_warnings: {
    title: "Passed with warnings",
    body: "The package is usable, but review the warnings below before class.",
  },
  fail: {
    title: "Validation failed",
    body: "This package did not pass automated checks — review carefully before using it.",
  },
};

const ISSUE_TONE: Record<string, BadgeTone> = { error: "danger", warning: "warning", info: "info" };

export function ValidationTab({ validation }: { validation: ValidationReport }) {
  const { coverage, consistency, unsupported_claims, issues } = validation;
  const duplicateConcepts = consistency.duplicate_concept_ids ?? consistency.duplicate_concepts ?? [];
  const danglingActivities = consistency.dangling_activity_refs ?? [];
  const prereqViolations = consistency.prerequisite_violations ?? [];

  const consistencyProblems =
    duplicateConcepts.length + danglingActivities.length + prereqViolations.length + (consistency.timing_ok ? 0 : 1);

  return (
    <div className="ef-stack">
      <Banner tone={STATUS_TONE[validation.status]} title={STATUS_COPY[validation.status].title}>
        <p>{STATUS_COPY[validation.status].body}</p>
        <p className="ef-muted">Checked {formatDateTime(validation.checked_at)}</p>
      </Banner>

      <div className="ef-grid">
        <div className="ef-card">
          <h3 className="ef-section-title">Coverage</h3>
          <dl className="ef-meta-grid">
            <div>
              <dt>Concepts taught</dt>
              <dd>
                {coverage.concepts_taught} / {coverage.concepts_total}
              </dd>
            </div>
            <div>
              <dt>Objectives assessed</dt>
              <dd>
                {coverage.objectives_assessed} / {coverage.objectives_total}
              </dd>
            </div>
            {coverage.objectives_planned != null ? (
              <div>
                <dt>Objectives planned</dt>
                <dd>
                  {coverage.objectives_planned} / {coverage.objectives_total}
                </dd>
              </div>
            ) : null}
          </dl>
          {(coverage.untaught_concept_ids?.length ?? 0) > 0 || (coverage.unassessed_objective_ids?.length ?? 0) > 0 ? (
            <p className="ef-muted">
              {coverage.untaught_concept_ids?.length ? `${coverage.untaught_concept_ids.length} concept(s) not taught. ` : ""}
              {coverage.unassessed_objective_ids?.length
                ? `${coverage.unassessed_objective_ids.length} objective(s) not assessed.`
                : ""}
            </p>
          ) : null}
        </div>

        <div className="ef-card">
          <h3 className="ef-section-title">Grounding</h3>
          <p className="ef-page-title" style={{ fontSize: "var(--ef-font-size-2xl)" }}>
            {formatPercent(validation.grounding_score)}
          </p>
          <p className="ef-muted">Share of claims traced back to a citation in the source document.</p>
        </div>
      </div>

      {consistencyProblems > 0 ? (
        <div className="ef-card">
          <h3 className="ef-section-title">Consistency</h3>
          <ul className="ef-bullet-list">
            {!consistency.timing_ok ? <li>Period timing does not add up.</li> : null}
            {duplicateConcepts.length > 0 ? <li>Duplicate concepts: {duplicateConcepts.join(", ")}</li> : null}
            {danglingActivities.length > 0 ? (
              <li>Activities referenced but missing: {danglingActivities.join(", ")}</li>
            ) : null}
            {prereqViolations.length > 0 ? <li>{prereqViolations.length} prerequisite ordering violation(s).</li> : null}
          </ul>
        </div>
      ) : null}

      {unsupported_claims.length > 0 ? (
        <div className="ef-card">
          <h3 className="ef-section-title">Unsupported claims</h3>
          <ul className="ef-bullet-list">
            {unsupported_claims.map((claim, i) => (
              <li key={i}>
                <strong>{claim.path}</strong>: {claim.claim}
                <div className="ef-muted">{claim.reason}</div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {issues.length > 0 ? (
        <div className="ef-card">
          <h3 className="ef-section-title">Issues</h3>
          <ul className="ef-bullet-list">
            {issues.map((issue, i) => (
              <li key={i}>
                <Badge tone={ISSUE_TONE[issue.severity] ?? "neutral"}>{issue.severity}</Badge> {issue.message}
                <div className="ef-muted">
                  {issue.stage} · {issue.path}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
