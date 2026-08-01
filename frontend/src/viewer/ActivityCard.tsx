import type { Activity } from "../api/types";
import { Badge } from "../components/ui/Badge";
import { titleCase } from "../utils/format";
import type { PackageLookups } from "../utils/lookups";

export function ActivityCard({ activity, lookups }: { activity: Activity; lookups: PackageLookups }) {
  return (
    <div className="ef-activity-card">
      <div className="ef-row" style={{ justifyContent: "space-between" }}>
        <h4 className="ef-subheading">{activity.title}</h4>
        <div className="ef-row" style={{ gap: "var(--ef-space-1)" }}>
          <Badge tone="info">{titleCase(activity.type)}</Badge>
          <Badge tone="neutral">{activity.duration_minutes} min</Badge>
        </div>
      </div>

      {activity.materials.length > 0 ? (
        <p className="ef-muted">
          <strong>Materials:</strong> {activity.materials.join(", ")}
        </p>
      ) : null}

      <div className="ef-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <div>
          <h5 className="ef-subheading ef-subheading--sm">Teacher does</h5>
          <ol className="ef-bullet-list ef-bullet-list--numbered">
            {activity.teacher_instructions.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
        <div>
          <h5 className="ef-subheading ef-subheading--sm">Students do</h5>
          <ol className="ef-bullet-list ef-bullet-list--numbered">
            {activity.student_instructions.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
      </div>

      {activity.success_criteria.length > 0 ? (
        <div>
          <h5 className="ef-subheading ef-subheading--sm">Success looks like</h5>
          <ul className="ef-bullet-list">
            {activity.success_criteria.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {activity.differentiation.support || activity.differentiation.extension ? (
        <div className="ef-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          {activity.differentiation.support ? (
            <p>
              <strong>Support:</strong> {activity.differentiation.support}
            </p>
          ) : null}
          {activity.differentiation.extension ? (
            <p>
              <strong>Extension:</strong> {activity.differentiation.extension}
            </p>
          ) : null}
        </div>
      ) : null}

      {activity.concept_ids.length > 0 ? (
        <div className="ef-row">
          {activity.concept_ids.map((id) => (
            <span className="ef-tag" key={id}>
              {lookups.conceptName(id)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
