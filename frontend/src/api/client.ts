import { API_BASE } from "./constants";
import {
  ApiError,
  type ApiErrorBody,
  type ArtifactListing,
  type CreateJobResponse,
  type DocumentDetail,
  type JobOptions,
  type JobSnapshot,
  type SamplesResponse,
  type TeacherKnowledgePackage,
  type UploadDocumentResponse,
  type ValidationReport,
} from "./types";

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }
  let body: ApiErrorBody;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    body = {
      error: {
        code: "unknown_error",
        message: `Request failed with status ${response.status}.`,
      },
    };
  }
  throw new ApiError(response.status, body);
}

export async function uploadDocument(
  file: File,
  signal?: AbortSignal,
): Promise<UploadDocumentResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/documents`, {
    method: "POST",
    body: form,
    signal,
  });
  return parseJsonOrThrow<UploadDocumentResponse>(response);
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  const response = await fetch(`${API_BASE}/documents/${encodeURIComponent(documentId)}`);
  return parseJsonOrThrow<DocumentDetail>(response);
}

export async function createJob(
  documentId: string,
  options: JobOptions,
  idempotencyKey: string,
): Promise<CreateJobResponse> {
  const response = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ document_id: documentId, options }),
  });
  return parseJsonOrThrow<CreateJobResponse>(response);
}

export async function getJob(jobId: string): Promise<JobSnapshot> {
  const response = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
  return parseJsonOrThrow<JobSnapshot>(response);
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  return parseJsonOrThrow(response);
}

export async function retryJob(
  jobId: string,
  fromStage?: string,
): Promise<CreateJobResponse> {
  const response = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: fromStage ? JSON.stringify({ from_stage: fromStage }) : undefined,
  });
  return parseJsonOrThrow<CreateJobResponse>(response);
}

export async function getPackage(packageId: string): Promise<TeacherKnowledgePackage> {
  const response = await fetch(`${API_BASE}/packages/${encodeURIComponent(packageId)}`);
  return parseJsonOrThrow<TeacherKnowledgePackage>(response);
}

export async function getValidation(packageId: string): Promise<ValidationReport> {
  const response = await fetch(
    `${API_BASE}/packages/${encodeURIComponent(packageId)}/validation`,
  );
  return parseJsonOrThrow<ValidationReport>(response);
}

export async function getArtifacts(packageId: string): Promise<ArtifactListing> {
  const response = await fetch(
    `${API_BASE}/packages/${encodeURIComponent(packageId)}/artifacts`,
  );
  return parseJsonOrThrow<ArtifactListing>(response);
}

export function artifactDownloadUrl(packageId: string, kind: string): string {
  return `${API_BASE}/packages/${encodeURIComponent(packageId)}/artifacts/${encodeURIComponent(kind)}`;
}

export async function getSamples(): Promise<SamplesResponse> {
  const response = await fetch(`${API_BASE}/samples`);
  return parseJsonOrThrow<SamplesResponse>(response);
}
