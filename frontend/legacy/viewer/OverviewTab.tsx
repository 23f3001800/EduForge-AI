import type { TeacherKnowledgePackage } from "../api/types";
import { formatDurationMs } from "../utils/format";

export function OverviewTab({ tkp }: { tkp: TeacherKnowledgePackage }) {
  const { knowledge, activities, assessments, learning_gaps, provenance, source } = tkp;

  const stats: { label: string; value: number | string }[] = [
    { label: "Concepts", value: knowledge.concepts.length },
    { label: "Learning objectives", value: knowledge.learning_objectives.length },
    { label: "Activities", value: activities.length },
    { label: "Assessment items", value: assessments.items.length },
    { label: "Total marks", value: assessments.total_marks },
    { label: "Learning gaps flagged", value: learning_gaps.length },
  ];

  return (
    <div className="ef-stack">
      <div className="ef-card">
        <h3 className="ef-section-title">At a glance</h3>
        <div className="ef-grid">
          {stats.map((s) => (
            <div key={s.label} className="ef-stat">
              <div className="ef-stat__value">{s.value}</div>
              <div className="ef-stat__label">{s.label}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="ef-card">
        <h3 className="ef-section-title">Source document</h3>
        <dl className="ef-meta-grid">
          <div>
            <dt>Filename</dt>
            <dd>{source.filename}</dd>
          </div>
          <div>
            <dt>Author</dt>
            <dd>{source.author ?? "—"}</dd>
          </div>
          <div>
            <dt>Pages</dt>
            <dd>{source.page_count}</dd>
          </div>
          <div>
            <dt>Words</dt>
            <dd>{source.word_count.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Language</dt>
            <dd>{source.detected_language ?? "—"}</dd>
          </div>
        </dl>
      </div>

      {provenance.stage_timings.length > 0 ? (
        <div className="ef-card">
          <h3 className="ef-section-title">Generation cost</h3>
          <dl className="ef-meta-grid">
            <div>
              <dt>Total time</dt>
              <dd>{formatDurationMs(provenance.total_duration_ms)}</dd>
            </div>
            <div>
              <dt>Tokens in / out</dt>
              <dd>
                {provenance.total_tokens_in.toLocaleString()} / {provenance.total_tokens_out.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt>Estimated cost</dt>
              <dd>${provenance.total_cost_usd.toFixed(2)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}
