/**
 * The API client.
 *
 * Same origin as the app — FastAPI serves this bundle — so the base path is a
 * relative prefix and there is no environment variable to get wrong between
 * local and deployed.
 *
 * Every response shape here mirrors `backend/contracts/` and
 * `backend/api/routes/`. Where the two disagree, the backend is right.
 */

export const API_BASE = "/api/v1";

// ─────────────────────────────────────────────────────────────── errors

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown>; trace_id?: string };
}

/**
 * Parsed defensively on purpose.
 *
 * The backend normalises every failure into one envelope, but this must not
 * assume it. Reading `body.error.message` off a shape that lacks it is how a
 * user came to be shown "Cannot read properties of undefined (reading
 * 'message')" — the error path throwing its own error is the one failure that
 * leaves someone with nothing at all.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly traceId?: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, body: unknown) {
    const envelope = (body as Partial<ApiErrorBody> | null)?.error;
    const detail = (body as { detail?: unknown } | null)?.detail;

    let message = envelope?.message;
    if (!message && typeof detail === "string") message = detail;
    if (!message && Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      message = typeof first?.msg === "string" ? first.msg : undefined;
    }

    super(message || `Request failed with status ${status}.`);
    this.name = "ApiError";
    this.status = status;
    this.code = envelope?.code ?? "unknown_error";
    this.traceId = envelope?.trace_id;
    this.details = envelope?.details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* a proxy or gateway can return html; ApiError copes with that */
    }
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

// ─────────────────────────────────────────────────────────────── types

export type PedagogyProfile =
  | "quantitative"
  | "conceptual"
  | "narrative"
  | "procedural"
  | "mixed";

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "succeeded_partial"
  | "failed"
  | "cancelled";

export interface JobOptions {
  period_duration_minutes?: number | null;
  teaching_style?: string;
  learning_goals?: string[];
  document_kind?: string;
  target_period_count?: number | null;
  output_language?: string;
  curriculum_board?: string | null;
  include_artifacts?: string[];
}

/**
 * Which pages a machine read, with what, and how sure it was.
 *
 * Mirrors `OcrProvenance` in `backend/contracts/document.py`, and is present on
 * `package.source.ocr` ONLY when some page had no text layer. Absent is the
 * normal case and means every page came from a real text layer.
 *
 * `confidence` is null when the engine does not report one. That is not zero and
 * must never render as a score — the same rule the evaluation panel applies to a
 * `not_measurable` metric, for the same reason: an invented number is worse than
 * an admitted gap.
 */
export interface OcrProvenance {
  engine: string;
  /** 1-based pages read by OCR. */
  pages: number[];
  /** Pages with no text layer that could not be recognised either — content missing. */
  failed_pages: number[];
  confidence: number | null;
  min_confidence: number | null;
}

export interface UploadResponse {
  document_id: string;
  sha256: string;
  filename: string;
  mime: string;
  size_bytes: number;
  deduplicated: boolean;
}

export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
  progress: number;
  events_url: string;
  created_at: string;
  deduplicated: boolean;
}

export interface JobSnapshot {
  job_id: string;
  document_id: string;
  status: JobStatus;
  current_stage: string | null;
  progress: number;
  completed_stages: string[];
  package_id: string | null;
  usage: { tokens: number; cost_usd: number };
  warnings: string[];
  error: { type: string; message: string } | null;
  created_at: string;
  finished_at: string | null;
}

export interface Artifact {
  kind: string;
  mime: string;
  bytes: number;
  status: "ready" | "failed";
  url: string;
}

export interface SampleSummary {
  package_id: string;
  title: string;
  subject: string;
  pedagogy_profile: PedagogyProfile;
  periods: number;
  validation_status: string;
}

export interface BoardOption {
  value: string;
  label: string;
  description: string;
  period_minutes: number;
}

export interface OptionsResponse {
  curriculum_boards: BoardOption[];
  teaching_styles: string[];
  document_kinds: string[];
  artifact_kinds: string[];
}

export interface Stats {
  since_restart: boolean;
  uptime_seconds: number;
  jobs: { succeeded: number; failed: number; finished: number; success_rate: number | null };
  stages: Record<string, { count: number; total_seconds: number; mean_seconds: number }>;
  requests: Record<string, number>;
  llm: {
    attempts: number;
    by_outcome: Record<string, number>;
    retry_rate: number | null;
    tokens: Record<string, number>;
    cost_usd: number;
  };
  packages: {
    total: number;
    by_subject: Record<string, number>;
    by_profile: Record<string, number>;
    by_language: Record<string, number>;
  };
}

// ───────────────────────────────────────────────────────────── requests

export async function uploadDocument(file: File, signal?: AbortSignal): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/documents`, { method: "POST", body: form, signal });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as UploadResponse;
}

export function createJob(
  documentId: string,
  options: JobOptions,
  idempotencyKey: string,
): Promise<CreateJobResponse> {
  return request<CreateJobResponse>("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    // FLAT, not nested under `options`: the endpoint's body model extends
    // JobOptions and adds document_id, and JobOptions forbids unknown fields —
    // so sending `{document_id, options}` was rejected with 422 and every job
    // creation from the UI failed.
    body: JSON.stringify({ document_id: documentId, ...options }),
  });
}

export const getJob = (jobId: string) => request<JobSnapshot>(`/jobs/${jobId}`);
export const retryJob = (jobId: string) =>
  request<{ job_id: string; status: JobStatus }>(`/jobs/${jobId}/retry`, { method: "POST" });

export const getPackage = (packageId: string) =>
  request<Record<string, unknown>>(`/packages/${packageId}`);
export const getArtifacts = (packageId: string) =>
  request<{ artifacts: Artifact[] }>(`/packages/${packageId}/artifacts`);
export const getSamples = () => request<{ samples: SampleSummary[] }>("/samples");
export const getOptions = () => request<OptionsResponse>("/options");
export const getStats = () => request<Stats>("/stats");

export const artifactUrl = (packageId: string, kind: string) =>
  `${API_BASE}/packages/${packageId}/artifacts/${kind}`;

// ─────────────────────────────────────────────────── evaluation framework

/**
 * How a score was arrived at. The UI must render these three differently:
 * a `not_measurable` metric has no number and showing a placeholder like "0"
 * or "—" in the same slot a score usually occupies invites reading it as one.
 */
export type Measurability = "measured" | "judged" | "not_measurable";

export interface MetricEvidence {
  path: string;
  observation: string;
}

export interface MetricRecommendation {
  action: string;
  impact: string;
  severity: "info" | "low" | "medium" | "high";
}

export interface EvaluationMetric {
  key: string;
  label: string;
  measurability: Measurability;
  /** Null whenever `measurability` is `not_measurable`. Never render a fallback number. */
  score: number | null;
  confidence: number;
  weight: number;
  reasoning: string;
  evidence: MetricEvidence[];
  recommendations: MetricRecommendation[];
}

export interface StageEvaluation {
  stage: string;
  label: string;
  score: number | null;
  confidence: number;
  measured: number;
  judged: number;
  not_measurable: number;
  missing: string[];
  metrics: EvaluationMetric[];
}

export interface Distribution {
  n: number;
  median: number | null;
  min: number | null;
  max: number | null;
  p25: number | null;
  p75: number | null;
}

export interface Benchmark {
  profile: string;
  runs: number;
  sufficient: boolean;
  overall: Distribution;
  stages: Record<string, Distribution>;
}

export interface Comparison {
  status: "insufficient_history" | "regression" | "ok";
  detail: string;
  runs?: number;
  needed?: number;
  threshold?: number;
  overall_delta?: number | null;
  regressions: { stage: string; score: number; baseline_median: number; delta: number }[];
  improvements: { stage: string; score: number; baseline_median: number; delta: number }[];
}

/**
 * The rubric half of the report — `EvalReport.as_dict()` in `evals/types.py`.
 *
 * Its `dimensions` list is open: the backend adds members (content_fidelity and
 * period_integrity are the two most recent), so nothing in the UI may hardcode
 * which dimensions exist. Rendering is driven entirely by this array.
 */
export interface RubricMetric {
  key: string;
  /** 0-1. Carries no weight in the dimension score when `weight` is 0 — those are reported, not scored. */
  value: number;
  weight: number;
  note: string;
}

export interface RubricFinding {
  code: string;
  /** A JSON pointer into the package. A finding without one is an opinion. */
  path: string;
  detail: string;
}

export interface RubricDimension {
  key: string;
  label: string;
  method: string;
  weight: number;
  /** 0-1, and null exactly when `applicable` is false. Never render a fallback number. */
  score: number | null;
  applicable: boolean;
  /** Why it was not applicable. Empty string when it was. */
  reason: string;
  metrics: RubricMetric[];
  findings: RubricFinding[];
}

export interface Rubric {
  package_id: string;
  profile: string;
  subject: string;
  grade_band: string;
  overall: number;
  band: string;
  judged: boolean;
  llm_profile: string;
  transferable: boolean;
  absent_by_design: string[];
  dimensions: RubricDimension[];
}

export interface EvaluationDocument {
  run_id: string;
  package_id: string;
  evaluated_at: string;
  subject: string;
  grade_band: string;
  profile: PedagogyProfile;
  summary: {
    stage_score: number | null;
    stage_confidence: number;
    stages_scored: number;
    stages_total: number;
    rubric_score: number;
    rubric_band: string;
    band: string;
    judged: boolean;
    transferable: boolean;
  };
  stages: StageEvaluation[];
  rubric: Rubric;
  recommendations: {
    stage: string;
    stage_label: string;
    metric: string;
    metric_label: string;
    score: number | null;
    severity: "info" | "low" | "medium" | "high";
    action: string;
    impact: string;
  }[];
  not_measurable: { stage: string; metric: string; label: string; reason: string }[];
  benchmark: Benchmark;
  comparison: Comparison;
  history: {
    run_id: string;
    evaluated_at: string;
    overall: number | null;
    confidence: number;
    profile: string;
    subject: string;
  }[];
}

export interface EvaluationSummary {
  run_id: string;
  package_id: string;
  subject: string;
  grade_band: string;
  profile: string;
  overall: number | null;
  confidence: number;
  stage_scores: Record<string, number | null>;
  evaluated_at: string;
  app_version: string;
}

/**
 * `persist=false` when the caller is only looking.
 *
 * Every fetch appending to the trend line would mean a reviewer refreshing a
 * page rewrites the baseline the next regression is judged against.
 */
export const getEvaluation = (packageId: string, persist = true) =>
  request<EvaluationDocument>(`/packages/${packageId}/evaluation?persist=${persist}`);

export const getEvaluations = (limit = 50) =>
  request<{ durable: boolean; total: number; evaluations: EvaluationSummary[] }>(
    `/evaluations?limit=${limit}`,
  );

export const getBenchmark = (profile?: string) =>
  request<Benchmark>(`/evaluations/benchmark${profile ? `?profile=${profile}` : ""}`);

export const evaluationPdfUrl = (packageId: string) =>
  `${API_BASE}/packages/${packageId}/evaluation.pdf`;
