import type { JobEventName } from "../types";
import { FIXTURE_PACKAGE_ID } from "./fixtureData";

/**
 * Stage identifiers for the ten-stage pipeline (docs/05-agent-graph.md §2:
 * parse, classify, extract, plan, period, activities, assess, gaps,
 * validate, publish).
 *
 * Six of these strings are given verbatim in the docs (marked ✓ below, from
 * docs/06-api-spec.md's `GET /jobs/{id}` example and the SSE example). The
 * other four are this module's best inference from the same naming
 * convention used for the first six — the API spec never shows a `stages[]`
 * entry or SSE frame for S7/S8/S9/S10. **This should be confirmed against
 * the worker's actual emitted strings once M4/M8 land**; the timeline UI
 * keys off `stage` string equality, so a mismatch here would just show an
 * "unknown stage" pill rather than break anything, but the labels would be
 * wrong. See the module report for the full flag.
 */
export const STAGE_ORDER = [
  "document-intelligence", // ✓ spec (S1)
  "educational-classification", // ✓ spec (S2)
  "knowledge-extraction", // ✓ spec (S3)
  "teaching-planner", // ✓ spec (S4)
  "lesson-generation", // ✓ spec (S5 — per-period fan-out, weight 25)
  "activity-generation", // ✓ spec (S6)
  "assessment-generation", // inferred (S7)
  "gap-analysis", // inferred (S8)
  "validation", // inferred (S9)
  "publishing", // inferred (S10)
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

export interface ScheduledFrame {
  atMs: number;
  event: JobEventName;
  stage: string;
  progress: number;
  message?: string;
  extra?: Record<string, unknown>;
}

export type MockScenario = "pass" | "partial" | "failed";

/** A clean run ending in `succeeded` / validation `pass` — matches the
 * fixture TKP's own `validation.status: "pass"` exactly. The two `message`
 * strings below are copied verbatim from the SSE example in
 * docs/06-api-spec.md §3, not invented here. */
function passScript(): ScheduledFrame[] {
  return [
    { atMs: 300, event: "progress", stage: "document-intelligence", progress: 4 },
    { atMs: 900, event: "progress", stage: "document-intelligence", progress: 8 },
    { atMs: 1600, event: "progress", stage: "educational-classification", progress: 13 },
    { atMs: 2300, event: "progress", stage: "educational-classification", progress: 17 },
    { atMs: 3100, event: "progress", stage: "knowledge-extraction", progress: 24 },
    {
      atMs: 4200,
      event: "progress",
      stage: "knowledge-extraction",
      progress: 30,
      message: "merged 4 sections",
    },
    { atMs: 5100, event: "progress", stage: "knowledge-extraction", progress: 37 },
    { atMs: 5900, event: "progress", stage: "teaching-planner", progress: 44 },
    { atMs: 6600, event: "progress", stage: "teaching-planner", progress: 48 },
    { atMs: 7300, event: "progress", stage: "lesson-generation", progress: 55 },
    {
      atMs: 8100,
      event: "progress",
      stage: "lesson-generation",
      progress: 60,
      message: "period 3 of 5",
    },
    { atMs: 8900, event: "progress", stage: "lesson-generation", progress: 68 },
    { atMs: 9500, event: "progress", stage: "activity-generation", progress: 75 },
    { atMs: 10200, event: "progress", stage: "assessment-generation", progress: 83 },
    { atMs: 10900, event: "progress", stage: "gap-analysis", progress: 89 },
    { atMs: 11500, event: "progress", stage: "validation", progress: 95 },
    { atMs: 12100, event: "progress", stage: "publishing", progress: 99 },
    {
      atMs: 12600,
      event: "completed",
      stage: "completed",
      progress: 100,
      extra: { package_id: FIXTURE_PACKAGE_ID, status: "succeeded" },
    },
  ];
}

/** Budget-exhaustion scenario (docs/06-api-spec.md: `succeeded_partial` "means
 * the package exists but is incomplete"). The pipeline still reaches
 * `publish` — S10's own contract is to publish the JSON even when a stage
 * degrades — but assessment-generation is flagged degraded and the
 * assessment-book PDF artifact fails to render (see `mockClient.ts`). */
function partialScript(): ScheduledFrame[] {
  const base = passScript();
  return base.map((frame) => {
    if (frame.stage === "assessment-generation") {
      return {
        ...frame,
        event: "warning" as JobEventName,
        message: "token budget low — assessment-generation degraded",
      };
    }
    if (frame.event === "completed") {
      return {
        ...frame,
        extra: { package_id: FIXTURE_PACKAGE_ID, status: "succeeded_partial" },
      };
    }
    return frame;
  });
}

/** A hard failure before publishing — no package is produced. */
function failedScript(): ScheduledFrame[] {
  return [
    { atMs: 300, event: "progress", stage: "document-intelligence", progress: 4 },
    { atMs: 1000, event: "progress", stage: "document-intelligence", progress: 8 },
    { atMs: 1800, event: "progress", stage: "educational-classification", progress: 15 },
    { atMs: 2700, event: "progress", stage: "knowledge-extraction", progress: 24 },
    {
      atMs: 4200,
      event: "failed",
      stage: "knowledge-extraction",
      progress: 30,
      extra: {
        error: {
          code: "model_provider_error",
          message: "The model provider returned a non-retryable error after 4 attempts.",
        },
      },
    },
  ];
}

export function getScriptFor(scenario: MockScenario): ScheduledFrame[] {
  switch (scenario) {
    case "partial":
      return partialScript();
    case "failed":
      return failedScript();
    case "pass":
    default:
      return passScript();
  }
}
