/**
 * Canonical pipeline stage identifiers, mirrored verbatim from
 * `backend/contracts/primitives.py::STAGE_NAMES` and the progress weights in
 * `backend/contracts/jobs.py::STAGE_PROGRESS_WEIGHTS`. Single source of truth
 * for both the real SSE-driven progress UI and the demo-mode mock scheduler,
 * so the two never drift into showing different stage lists.
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
  "document-intelligence": "Document Intelligence",
  "educational-classification": "Classification",
  "knowledge-extraction": "Knowledge Extraction",
  "teaching-planner": "Teaching Planner",
  "lesson-generation": "Lesson Generation",
  "activity-generation": "Activity Generation",
  "assessment-generation": "Assessment Generation",
  "gap-analysis": "Gap Analysis",
  validation: "Validation",
  publishing: "Publishing",
};

/** Must sum to 100 — mirrors the backend assertion in the contract test suite. */
export const STAGE_PROGRESS_WEIGHTS: Record<StageKey, number> = {
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

export function isStageKey(value: string): value is StageKey {
  return (STAGE_ORDER as readonly string[]).includes(value);
}

export function stageLabel(stage: string): string {
  if (isStageKey(stage)) return STAGE_LABELS[stage];
  if (stage === "queued") return "Queued";
  if (stage === "completed") return "Completed";
  if (stage === "failed") return "Failed";
  if (stage === "cancelled") return "Cancelled";
  return stage;
}

export function stageIndex(stage: string): number {
  return STAGE_ORDER.indexOf(stage as StageKey);
}
