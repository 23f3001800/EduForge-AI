import { ApiError, type ApiErrorBody } from "../types";
import type {
  ArtifactListing,
  CreateJobResponse,
  DocumentDetail,
  JobOptions,
  JobSnapshot,
  JobStageSnapshot,
  SamplesResponse,
  TeacherKnowledgePackage,
  UploadDocumentResponse,
  ValidationReport,
} from "../types";
import { FIXTURE_DOCUMENT_ID, FIXTURE_SAMPLE, FIXTURE_TKP } from "./fixtureData";
import { STAGE_ORDER, getScriptFor, type MockScenario } from "./schedule";
import {
  findDocumentBySha,
  findJobByIdempotencyKey,
  indexDocumentSha,
  indexIdempotencyKey,
  loadMockDocument,
  loadMockJob,
  saveMockDocument,
  saveMockJob,
} from "./store";

/**
 * Demo-mode backend. Every response is either copied verbatim from the
 * fixture TKP or is structural scaffolding (ids, timestamps, progress
 * numbers) — no invented lesson content. A handful of filename substrings
 * let a reviewer preview the error and partial-success states the DoD
 * requires without a live backend; see the hint text on the Upload screen.
 */

function err(status: number, code: string, message: string, details?: Record<string, unknown>) {
  const body: ApiErrorBody = { error: { code, message, details, trace_id: "demo-mode" } };
  return new ApiError(status, body);
}

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function scenarioFromFilename(name: string): MockScenario {
  const lower = name.toLowerCase();
  if (lower.includes("partial")) return "partial";
  if (lower.includes("fail")) return "failed";
  return "pass";
}

async function simulateLatency(ms = 350): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export async function mockUploadDocument(file: File): Promise<UploadDocumentResponse> {
  await simulateLatency();
  const lower = file.name.toLowerCase();

  if (lower.includes("toolarge")) {
    throw err(413, "document_too_large", "File exceeds 25 MB limit.", {
      size_bytes: file.size || 41_231_882,
      limit_bytes: 26_214_400,
    });
  }
  if (lower.includes("wrongtype")) {
    throw err(
      415,
      "unsupported_media_type",
      "The file's sniffed content type is not in the supported list (PDF, DOCX, PPTX, TXT, MD).",
    );
  }
  if (lower.includes("manypages")) {
    throw err(422, "too_many_pages", "Document exceeds the 300-page limit.", { limit: 300 });
  }
  if (lower.includes("corrupt")) {
    throw err(422, "parse_failed", "The document could not be parsed.");
  }
  if (lower.includes("emptydoc")) {
    throw err(422, "empty_document", "No extractable text or slides were found in this document.");
  }

  const sha256 = await sha256Hex(file);
  const existing = findDocumentBySha(sha256);
  if (existing) {
    return {
      document_id: existing.documentId,
      sha256,
      filename: existing.filename,
      mime: file.type || "application/octet-stream",
      page_count: FIXTURE_TKP.source.page_count,
      word_count: FIXTURE_TKP.source.word_count,
      detected_language: FIXTURE_TKP.source.detected_language ?? "en",
      deduplicated: true,
    };
  }

  const scenario = scenarioFromFilename(file.name);
  const documentId = scenario === "pass" ? FIXTURE_DOCUMENT_ID : crypto.randomUUID();
  saveMockDocument({ documentId, filename: file.name, sha256, scenario });
  indexDocumentSha(sha256, documentId);

  return {
    document_id: documentId,
    sha256,
    filename: file.name,
    mime: file.type || "application/pdf",
    page_count: FIXTURE_TKP.source.page_count,
    word_count: FIXTURE_TKP.source.word_count,
    detected_language: FIXTURE_TKP.source.detected_language ?? "en",
    deduplicated: false,
  };
}

export async function mockGetDocument(documentId: string): Promise<DocumentDetail> {
  await simulateLatency(150);
  const doc = loadMockDocument(documentId);
  if (!doc) throw err(404, "not_found", "Document not found.");
  return {
    document_id: documentId,
    sha256: doc.sha256,
    filename: doc.filename,
    mime: "application/pdf",
    page_count: FIXTURE_TKP.source.page_count,
    word_count: FIXTURE_TKP.source.word_count,
    detected_language: FIXTURE_TKP.source.detected_language ?? "en",
    deduplicated: false,
    outline: [],
    stats: { equations: 1, tables: 0, figures: 0, headings: 4 },
    chunk_count: 6,
  };
}

export async function mockCreateJob(
  documentId: string,
  _options: JobOptions,
  idempotencyKey?: string,
): Promise<CreateJobResponse> {
  await simulateLatency(250);

  if (idempotencyKey) {
    const existingJobId = findJobByIdempotencyKey(idempotencyKey);
    if (existingJobId) {
      const existing = loadMockJob(existingJobId);
      if (existing) {
        return {
          job_id: existing.jobId,
          status: existing.status,
          progress: 0,
          events_url: `/api/v1/jobs/${existing.jobId}/events`,
          created_at: new Date(existing.createdAtMs).toISOString(),
        };
      }
    }
  }

  const doc = loadMockDocument(documentId);
  const scenario = doc?.scenario ?? "pass";
  const jobId = crypto.randomUUID();
  const createdAtMs = Date.now();

  saveMockJob({
    jobId,
    documentId,
    scenario,
    createdAtMs,
    cancelled: false,
    cancelledAtMs: null,
    status: "queued",
    packageId: null,
    idempotencyKey,
  });
  if (idempotencyKey) indexIdempotencyKey(idempotencyKey, jobId);

  return {
    job_id: jobId,
    status: "queued",
    progress: 0,
    events_url: `/api/v1/jobs/${jobId}/events`,
    created_at: new Date(createdAtMs).toISOString(),
  };
}

function deriveStages(scenario: MockScenario, elapsedMs: number): JobStageSnapshot[] {
  const script = getScriptFor(scenario);
  const frames = script.filter((f) => f.atMs <= elapsedMs);
  const lastFrame = frames[frames.length - 1];
  const reachedIdx = lastFrame ? STAGE_ORDER.indexOf(lastFrame.stage as (typeof STAGE_ORDER)[number]) : -1;

  return STAGE_ORDER.map((stage, idx) => {
    if (lastFrame?.event === "failed" && stage === lastFrame.stage) {
      return { stage, status: "failed" as const };
    }
    if (idx < reachedIdx) return { stage, status: "completed" as const };
    if (idx === reachedIdx) {
      const terminal = lastFrame?.event === "completed" || lastFrame?.event === "failed";
      return { stage, status: terminal ? ("completed" as const) : ("running" as const) };
    }
    return { stage, status: "pending" as const };
  });
}

export async function mockGetJob(jobId: string): Promise<JobSnapshot> {
  await simulateLatency(120);
  const state = loadMockJob(jobId);
  if (!state) throw err(404, "not_found", "Job not found.");

  const elapsed = state.cancelled ? (state.cancelledAtMs ?? 0) : Date.now() - state.createdAtMs;
  const script = getScriptFor(state.scenario);
  const frames = script.filter((f) => f.atMs <= elapsed);
  const lastFrame = frames[frames.length - 1];
  const progress = lastFrame?.progress ?? 0;
  const currentStage = state.cancelled ? null : (lastFrame?.stage ?? STAGE_ORDER[0]);

  let status: JobSnapshot["status"] = state.status;
  if (state.cancelled) {
    status = "cancelled";
  } else if (lastFrame?.event === "completed") {
    status = (lastFrame.extra?.status as JobSnapshot["status"] | undefined) ?? "succeeded";
  } else if (lastFrame?.event === "failed") {
    status = "failed";
  } else if (frames.length > 0) {
    status = "running";
  }

  return {
    job_id: state.jobId,
    document_id: state.documentId,
    status,
    current_stage: currentStage,
    progress,
    stages: deriveStages(state.scenario, elapsed),
    package_id: state.packageId,
    usage: { tokens_in: 184_300, tokens_out: 41_200, cache_read: 121_000, cost_usd: 2.14 },
    warnings: state.scenario === "partial" ? ["assessment-generation degraded — token budget low"] : [],
    error:
      lastFrame?.event === "failed"
        ? ((lastFrame.extra?.error as JobSnapshot["error"]) ?? null)
        : null,
  };
}

export async function mockCancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
  await simulateLatency(150);
  const state = loadMockJob(jobId);
  if (!state) throw err(404, "not_found", "Job not found.");
  state.cancelled = true;
  state.cancelledAtMs = Date.now() - state.createdAtMs;
  state.status = "cancelled";
  saveMockJob(state);
  return { job_id: jobId, status: "cancelled" };
}

export async function mockRetryJob(jobId: string): Promise<CreateJobResponse> {
  await simulateLatency(200);
  const state = loadMockJob(jobId);
  if (!state) throw err(404, "not_found", "Job not found.");
  if (!["failed", "cancelled", "succeeded_partial"].includes(state.status)) {
    throw err(409, "invalid_state", `Cannot retry a job in status "${state.status}".`);
  }
  // Resume as a clean completion from "now" — completed stages are not
  // re-executed. The demo scenario always switches to `pass` on retry so the
  // affordance is visibly meaningful.
  state.scenario = "pass";
  state.createdAtMs = Date.now();
  state.cancelled = false;
  state.cancelledAtMs = null;
  state.status = "queued";
  state.packageId = null;
  saveMockJob(state);

  return {
    job_id: state.jobId,
    status: "queued",
    progress: 0,
    events_url: `/api/v1/jobs/${state.jobId}/events`,
    created_at: new Date(state.createdAtMs).toISOString(),
  };
}

export async function mockGetPackage(packageId: string): Promise<TeacherKnowledgePackage> {
  await simulateLatency(200);
  if (packageId !== FIXTURE_TKP.tkp_id) throw err(404, "not_found", "Package not found.");
  return FIXTURE_TKP;
}

export async function mockGetValidation(packageId: string): Promise<ValidationReport> {
  await simulateLatency(150);
  if (packageId !== FIXTURE_TKP.tkp_id) throw err(404, "not_found", "Package not found.");
  return FIXTURE_TKP.validation;
}

export async function mockGetArtifacts(packageId: string): Promise<ArtifactListing> {
  await simulateLatency(150);
  if (packageId !== FIXTURE_TKP.tkp_id) throw err(404, "not_found", "Package not found.");
  const tkpJsonBytes = new TextEncoder().encode(JSON.stringify(FIXTURE_TKP)).byteLength;
  return {
    artifacts: [
      {
        kind: "tkp_json",
        mime: "application/json",
        bytes: tkpJsonBytes,
        status: "ready",
        url: `/api/v1/packages/${packageId}/artifacts/tkp_json`,
      },
      {
        kind: "lesson_plan_pdf",
        mime: "application/pdf",
        bytes: 412_880,
        status: "ready",
        url: `/api/v1/packages/${packageId}/artifacts/lesson_plan_pdf`,
      },
      {
        kind: "teacher_guide_pdf",
        mime: "application/pdf",
        bytes: 690_214,
        status: "ready",
        url: `/api/v1/packages/${packageId}/artifacts/teacher_guide_pdf`,
      },
      {
        kind: "assessment_book_pdf",
        mime: "application/pdf",
        bytes: 0,
        status: "failed",
        url: `/api/v1/packages/${packageId}/artifacts/assessment_book_pdf`,
      },
      {
        kind: "markdown_bundle",
        mime: "application/zip",
        bytes: 48_211,
        status: "ready",
        url: `/api/v1/packages/${packageId}/artifacts/markdown_bundle`,
      },
    ],
  };
}

export function mockArtifactDownloadUrl(packageId: string, kind: string): string {
  return `/api/v1/packages/${packageId}/artifacts/${kind}`;
}

/** Intercepted by `fetchMockArtifact` — the real anchor `download` flow calls
 * this instead of hitting the network when demo mode is on. */
export async function fetchMockArtifact(kind: string): Promise<{ blob: Blob; filename: string }> {
  if (kind === "tkp_json") {
    return {
      blob: new Blob([JSON.stringify(FIXTURE_TKP, null, 2)], { type: "application/json" }),
      filename: "teacher_knowledge_package.json",
    };
  }
  const placeholder =
    "This is a demo-mode placeholder.\n\n" +
    "PDF and Markdown rendering is owned by Stage 10 (Publishing) and requires a live backend.\n" +
    `Requested artifact: ${kind}`;
  return {
    blob: new Blob([placeholder], { type: "text/plain" }),
    filename: `${kind}.demo.txt`,
  };
}

export async function mockGetSamples(): Promise<SamplesResponse> {
  await simulateLatency(200);
  return { samples: [FIXTURE_SAMPLE] };
}
