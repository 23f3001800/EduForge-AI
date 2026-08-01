/**
 * The pipeline stages, mirrored from `backend/contracts/primitives.py`
 * (STAGE_NAMES) and `backend/contracts/jobs.py` (STAGE_PROGRESS_WEIGHTS).
 *
 * Mirrored rather than fetched: this list must be renderable before any request
 * resolves, so the progress screen can draw all ten rows as "pending" the
 * instant it mounts instead of appearing empty until the first event lands.
 * A contract test asserts the weights sum to 100 on the backend side.
 */

export const STAGE_ORDER = [
  "document-intelligence",
  "educational-classification",
  "knowledge-extraction",
  "teaching-planner",
  "lesson-generation",
  "activity-generation",
  "assessment-generation",
  "gap-analysis",
  "validation",
  "publishing",
] as const;

export type StageKey = (typeof STAGE_ORDER)[number];

export const STAGE_LABELS: Record<StageKey, string> = {
  "document-intelligence": "Document intelligence",
  "educational-classification": "Classification",
  "knowledge-extraction": "Knowledge extraction",
  "teaching-planner": "Teaching planner",
  "lesson-generation": "Classroom content",
  "activity-generation": "Activities",
  "assessment-generation": "Assessments",
  "gap-analysis": "Gap analysis",
  validation: "Validation",
  publishing: "Publishing",
};

export const STAGE_BLURBS: Record<StageKey, string> = {
  "document-intelligence": "Parsing the document and preserving its structure.",
  "educational-classification": "Subject, grade band, and the pedagogy profile.",
  "knowledge-extraction": "Concepts and objectives, each with verified evidence.",
  "teaching-planner": "Deriving the period count and sequencing concepts.",
  "lesson-generation": "Writing what happens in each period.",
  "activity-generation": "Classroom activities suited to this profile.",
  "assessment-generation": "Questions, answer keys and rubrics.",
  "gap-analysis": "Likely misconceptions, with diagnostics and fixes.",
  validation: "Checking coverage, consistency and grounding.",
  publishing: "Assembling the package and rendering the files.",
};

export const STAGE_WEIGHTS: Record<StageKey, number> = {
  "document-intelligence": 8,
  "educational-classification": 5,
  "knowledge-extraction": 17,
  "teaching-planner": 10,
  "lesson-generation": 25,
  "activity-generation": 10,
  "assessment-generation": 10,
  "gap-analysis": 5,
  validation: 5,
  publishing: 5,
};

/**
 * Roughly how long a stage should take, for the slow-vs-stuck signal.
 *
 * Derived from the progress weights against a ~6 minute typical run, not
 * measured per stage — so it is used only to decide when to say "this is taking
 * longer than usual", never to display a countdown. A wrong ETA is worse than
 * no ETA; "still working" that turns into "this is unusually slow" is honest at
 * both ends.
 */
const TYPICAL_RUN_SECONDS = 360;

export function expectedSeconds(stage: StageKey): number {
  return (STAGE_WEIGHTS[stage] / 100) * TYPICAL_RUN_SECONDS;
}

/** Cumulative progress at the point a stage completes. */
export function progressAfter(stage: StageKey): number {
  let total = 0;
  for (const key of STAGE_ORDER) {
    total += STAGE_WEIGHTS[key];
    if (key === stage) break;
  }
  return total;
}
