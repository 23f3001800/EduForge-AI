import type { TeacherKnowledgePackage, ValidationStatus } from "../api/types";
import { Badge } from "../components/ui/Badge";
import { formatDateTime, titleCase } from "../utils/format";

const VALIDATION_TONE: Record<ValidationStatus, "success" | "warning" | "danger"> = {
  pass: "success",
  pass_with_warnings: "warning",
  fail: "danger",
};

const VALIDATION_LABEL: Record<ValidationStatus, string> = {
  pass: "Validation passed",
  pass_with_warnings: "Passed with warnings",
  fail: "Validation failed",
};

export function PackageHeader({ tkp }: { tkp: TeacherKnowledgePackage }) {
  const { classification, source, teaching_plan, validation } = tkp;

  return (
    <div className="ef-card ef-viewer-header">
      <div className="ef-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 className="ef-page-title">{source.title ?? classification.topic}</h1>
          <p className="ef-page-subtitle">
            {classification.subject} · Grade {classification.grade_band}
            {classification.chapter ? ` · ${classification.chapter}` : ""}
          </p>
        </div>
        <Badge tone={VALIDATION_TONE[validation.status]}>{VALIDATION_LABEL[validation.status]}</Badge>
      </div>

      <div className="ef-row" style={{ marginTop: "var(--ef-space-3)" }}>
        <Badge tone="neutral">{titleCase(classification.difficulty)}</Badge>
        <Badge tone="neutral">{titleCase(classification.pedagogy_profile)}</Badge>
        <Badge tone="neutral">{classification.language.toUpperCase()}</Badge>
        {classification.curriculum_alignment ? (
          <Badge tone="info">{classification.curriculum_alignment.board}</Badge>
        ) : null}
        <Badge tone="neutral">
          {teaching_plan.total_periods} period{teaching_plan.total_periods === 1 ? "" : "s"} ·{" "}
          {teaching_plan.period_duration_minutes} min
        </Badge>
      </div>

      <dl className="ef-meta-grid">
        <div>
          <dt>Source</dt>
          <dd>{source.filename}</dd>
        </div>
        <div>
          <dt>Pages</dt>
          <dd>{source.page_count}</dd>
        </div>
        <div>
          <dt>Generated</dt>
          <dd>{formatDateTime(tkp.generated_at)}</dd>
        </div>
      </dl>
    </div>
  );
}
