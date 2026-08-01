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
