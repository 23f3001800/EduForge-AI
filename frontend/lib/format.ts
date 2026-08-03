/** Presentation helpers. Nothing here decides anything — only how it reads. */

export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

/**
 * A duration the way a stopwatch shows it — `0:42`, `12:07`, `1:04:30`.
 *
 * Distinct from `formatDuration`, which writes durations as prose ("12m 7s").
 * Both are correct; they are read differently. Prose is right for a single
 * figure in a sentence, and wrong for a column, because "9m 3s" and "11m 40s"
 * do not line up under each other. The run log is read by scanning down it, so
 * it gets the aligned form and a `tabular-nums` face to go with it.
 *
 * Clamps rather than returning a placeholder: every caller here is displaying a
 * measured elapsed time next to a live one, and a stray "—" in that column
 * reads as a fault rather than as the sub-second rounding it actually is.
 */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const whole = Math.floor(seconds);
  const secs = String(whole % 60).padStart(2, "0");
  const mins = Math.floor(whole / 60) % 60;
  const hours = Math.floor(whole / 3600);
  if (hours > 0) return `${hours}:${String(mins).padStart(2, "0")}:${secs}`;
  return `${mins}:${secs}`;
}

/** Percentages that are unknown must read as unknown, never as zero. */
export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

/**
 * Enum values, written the way a person would write them.
 *
 * The previous implementation title-cased every word, which is wrong twice over:
 * `mcq` came out as "Mcq" on every multiple-choice badge in the assessment tab,
 * and `pass_with_warnings` came out as "Pass With Warnings". Neither is a string
 * anybody would type.
 *
 * So the values that have a real name are named here, and everything else falls
 * back to sentence case rather than title case — "Short answer", not "Short
 * Answer". The map is keyed on the raw wire value from `backend/contracts/`; an
 * unmapped value still reads acceptably, which is what keeps a new enum member
 * on the backend from rendering as a defect here.
 */
const EXPLICIT_LABELS: Record<string, string> = {
  // Assessment item kinds — contracts/assessment.py, ItemKind.
  mcq: "Multiple choice",
  short_answer: "Short answer",
  long_answer: "Long answer",
  numerical: "Numerical",
  // Validation statuses — contracts/validation.py, ValidationStatus.
  pass: "Pass",
  pass_with_warnings: "Pass with warnings",
  fail: "Fail",
  // Activity types — contracts/content.py, ActivityType.
  role_play: "Role play",
  group_discussion: "Group discussion",
  think_pair_share: "Think-pair-share",
  problem_set: "Problem set",
  field_task: "Field task",
  gallery_walk: "Gallery walk",
  // Concept relations — contracts/knowledge.py, RelationType.
  prerequisite_of: "Prerequisite of",
  part_of: "Part of",
  contrasts_with: "Contrasts with",
};

export function labelFor(value: string | null | undefined): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed) return "";

  const explicit = EXPLICIT_LABELS[trimmed.toLowerCase()];
  if (explicit) return explicit;

  const spaced = trimmed.replace(/[_-]+/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Whole tokens, never a bare number with no unit. */
export function formatTokens(tokens: number | null | undefined): string {
  if (typeof tokens !== "number" || !Number.isFinite(tokens) || tokens < 0) return "—";
  return tokens.toLocaleString();
}

/**
 * Cost in USD.
 *
 * A free-tier run genuinely costs nothing, and "$0.00" says that. It is only
 * fractions of a cent that need the extra places — rounding 0.0004 to "$0.00"
 * would make a run that did cost something look free.
 */
export function formatCost(cost: number | null | undefined): string {
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0) return "—";
  if (cost === 0) return "$0.00";
  return cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(2)}`;
}
