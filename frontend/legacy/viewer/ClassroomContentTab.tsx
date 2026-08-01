import type { PeriodContent } from "../api/types";
import { Badge } from "../components/ui/Badge";
import { titleCase } from "../utils/format";
import type { PackageLookups } from "../utils/lookups";
import { ActivityCard } from "./ActivityCard";

export function ClassroomContentTab({
  content,
  lookups,
}: {
  content: PeriodContent[];
  lookups: PackageLookups;
}) {
  return (
    <div className="ef-stack">
      {content.map((period) => (
        <details className="ef-card ef-period-content" key={period.period_no} open={period.period_no === 1}>
          <summary className="ef-section-title">Period {period.period_no}</summary>

          <div className="ef-stack" style={{ marginTop: "var(--ef-space-4)" }}>
            <section>
              <h4 className="ef-subheading">Entry ticket ({period.entry_ticket.duration_minutes} min)</h4>
              <p>{period.entry_ticket.prompt}</p>
              <p className="ef-muted">Expect: {period.entry_ticket.expected_response}</p>
            </section>

            <section>
              <h4 className="ef-subheading">Teacher script</h4>
              <ol className="ef-script">
                {period.teacher_script.map((segment, idx) => (
                  <li key={idx} className="ef-script__segment">
                    <div className="ef-script__time">
                      {segment.minute_start}–{segment.minute_end} min
                    </div>
                    <div className="ef-script__body">
                      <strong>{segment.heading}</strong>
                      <p>{segment.speaker_notes}</p>
                      {segment.board_action ? (
                        <p className="ef-muted">
                          <em>Board:</em> {segment.board_action}
                        </p>
                      ) : null}
                      {segment.anticipated_questions.length > 0 ? (
                        <p className="ef-muted">
                          <em>Anticipate:</em> {segment.anticipated_questions.join(" · ")}
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </section>

            <section>
              <h4 className="ef-subheading">Blackboard notes</h4>
              {period.blackboard_notes.headings.length > 0 ? (
                <p>
                  <strong>{period.blackboard_notes.headings.join(" / ")}</strong>
                </p>
              ) : null}
              {period.blackboard_notes.bullet_points.length > 0 ? (
                <ul className="ef-bullet-list">
                  {period.blackboard_notes.bullet_points.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              ) : null}
              {period.blackboard_notes.formulae_latex.length > 0 ? (
                <ul className="ef-bullet-list ef-bullet-list--mono">
                  {period.blackboard_notes.formulae_latex.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              ) : null}
              {period.blackboard_notes.diagrams_to_draw.length > 0 ? (
                <p className="ef-muted">
                  <em>Diagrams:</em> {period.blackboard_notes.diagrams_to_draw.join(", ")}
                </p>
              ) : null}
            </section>

            {period.activity_refs.length > 0 ? (
              <section>
                <h4 className="ef-subheading">Activities</h4>
                <div className="ef-stack">
                  {period.activity_refs.map((ref) => {
                    const activity = lookups.activityById(ref);
                    if (!activity) return null;
                    return <ActivityCard key={ref} activity={activity} lookups={lookups} />;
                  })}
                </div>
              </section>
            ) : null}

            {period.checkpoint_questions.length > 0 ? (
              <section>
                <h4 className="ef-subheading">Checkpoint questions</h4>
                <ul className="ef-bullet-list">
                  {period.checkpoint_questions.map((q, i) => (
                    <li key={i}>
                      <Badge tone="neutral">{titleCase(q.bloom_level)}</Badge> {q.question}
                      <div className="ef-muted">Expected: {q.expected_answer}</div>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section>
              <h4 className="ef-subheading">Exit ticket ({period.exit_ticket.duration_minutes} min)</h4>
              <p>{period.exit_ticket.prompt}</p>
              <p className="ef-muted">Success: {period.exit_ticket.success_indicator}</p>
            </section>

            {period.homework.tasks.length > 0 ? (
              <section>
                <h4 className="ef-subheading">
                  Homework ({period.homework.estimated_minutes} min · {period.homework.submission_format})
                </h4>
                <ul className="ef-bullet-list">
                  {period.homework.tasks.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            {period.mentor_moment ? (
              <section className="ef-mentor-moment">
                <h4 className="ef-subheading">
                  {period.mentor_moment.title}
                  <span className="ef-badge ef-badge--neutral" style={{ marginLeft: "var(--ef-space-2)" }}>
                    Illustrative — not from source
                  </span>
                </h4>
                <p>{period.mentor_moment.story}</p>
                <p className="ef-muted">
                  <em>Takeaway:</em> {period.mentor_moment.takeaway}
                </p>
              </section>
            ) : null}
          </div>
        </details>
      ))}
    </div>
  );
}
