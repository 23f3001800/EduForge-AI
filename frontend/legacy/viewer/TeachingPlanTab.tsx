import type { TeachingPlan } from "../api/types";
import { Banner } from "../components/ui/Banner";
import type { PackageLookups } from "../utils/lookups";

export function TeachingPlanTab({ plan, lookups }: { plan: TeachingPlan; lookups: PackageLookups }) {
  return (
    <div className="ef-stack">
      <p className="ef-muted">
        {plan.total_periods} periods of {plan.period_duration_minutes} minutes each.
      </p>

      {plan.periods.map((period) => {
        const totalMinutes = period.time_allocation.reduce((sum, slot) => sum + slot.minutes, 0);
        return (
          <article className="ef-card" key={period.period_no}>
            <h3 className="ef-section-title">
              Period {period.period_no}: {period.title}
            </h3>
            <p className="ef-muted">{period.sequence_rationale}</p>

            <div className="ef-time-allocation" aria-label={`Time allocation for period ${period.period_no}`}>
              {period.time_allocation.map((slot) => (
                <div
                  key={slot.label}
                  className="ef-time-allocation__slot"
                  style={{ flexGrow: slot.minutes }}
                  title={`${slot.label}: ${slot.minutes} min`}
                >
                  <span className="ef-time-allocation__label">{slot.label}</span>
                  <span className="ef-time-allocation__minutes">{slot.minutes}m</span>
                </div>
              ))}
            </div>
            <p className="ef-muted" style={{ fontSize: "var(--ef-font-size-xs)" }}>
              {totalMinutes} of {plan.period_duration_minutes} minutes allocated
            </p>

            {period.objective_ids.length > 0 ? (
              <div>
                <h4 className="ef-subheading">Objectives</h4>
                <ul className="ef-bullet-list">
                  {period.objective_ids.map((id) => (
                    <li key={id}>{lookups.objectiveStatement(id)}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {period.concept_ids.length > 0 ? (
              <div className="ef-row">
                {period.concept_ids.map((id) => (
                  <span className="ef-tag" key={id}>
                    {lookups.conceptName(id)}
                  </span>
                ))}
              </div>
            ) : null}
          </article>
        );
      })}

      {plan.unmapped_objective_ids.length > 0 ? (
        <Banner tone="warning" title="Objectives not placed in any period">
          <ul className="ef-bullet-list">
            {plan.unmapped_objective_ids.map((id) => (
              <li key={id}>{lookups.objectiveStatement(id)}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
    </div>
  );
}
