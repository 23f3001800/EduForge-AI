import { STAGE_LABELS, STAGE_ORDER } from "../../api/stages";

export type TimelineStageState = "pending" | "current" | "done" | "failed";

export function StageTimeline({
  completedStages,
  currentStage,
  failedStage,
}: {
  completedStages: Set<string>;
  currentStage: string | null;
  failedStage: string | null;
}) {
  return (
    <ol className="ef-stage-timeline" aria-label="Pipeline stages">
      {STAGE_ORDER.map((stage) => {
        let state: TimelineStageState = "pending";
        if (failedStage === stage) state = "failed";
        else if (completedStages.has(stage)) state = "done";
        else if (currentStage === stage) state = "current";

        return (
          <li key={stage} className={`ef-stage-timeline__item ef-stage-timeline__item--${state}`}>
            <span className="ef-stage-timeline__marker" aria-hidden="true">
              {state === "done" ? "✓" : state === "failed" ? "!" : ""}
            </span>
            <span className="ef-stage-timeline__label">
              {STAGE_LABELS[stage]}
              {state === "current" ? <span className="ef-visually-hidden"> — in progress</span> : null}
              {state === "done" ? <span className="ef-visually-hidden"> — complete</span> : null}
              {state === "failed" ? <span className="ef-visually-hidden"> — failed</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
