import * as real from "./client";
import {
  fetchMockArtifact,
  mockArtifactDownloadUrl,
  mockCancelJob,
  mockCreateJob,
  mockGetArtifacts,
  mockGetDocument,
  mockGetJob,
  mockGetPackage,
  mockGetSamples,
  mockGetValidation,
  mockRetryJob,
  mockUploadDocument,
} from "./mock/mockClient";
import { openMockJobEventStream } from "./mock/mockSse";
import { openJobEventStream, type JobEventStreamHandle, type JobEventStreamOptions } from "./sse";
import { isMockMode } from "./mode";
import type {
  ArtifactListing,
  CreateJobResponse,
  DocumentDetail,
  JobOptions,
  JobSnapshot,
  SamplesResponse,
  TeacherKnowledgePackage,
  UploadDocumentResponse,
  ValidationReport,
} from "./types";

export { isMockMode, setMockMode, subscribeMockMode } from "./mode";
export { ApiError } from "./types";

export async function uploadDocument(file: File, signal?: AbortSignal): Promise<UploadDocumentResponse> {
  return isMockMode() ? mockUploadDocument(file) : real.uploadDocument(file, signal);
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  return isMockMode() ? mockGetDocument(documentId) : real.getDocument(documentId);
}

export async function createJob(
  documentId: string,
  options: JobOptions,
  idempotencyKey: string,
): Promise<CreateJobResponse> {
  return isMockMode()
    ? mockCreateJob(documentId, options, idempotencyKey)
    : real.createJob(documentId, options, idempotencyKey);
}

export async function getJob(jobId: string): Promise<JobSnapshot> {
  return isMockMode() ? mockGetJob(jobId) : real.getJob(jobId);
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; status: string }> {
  return isMockMode() ? mockCancelJob(jobId) : real.cancelJob(jobId);
}

export async function retryJob(jobId: string, fromStage?: string): Promise<CreateJobResponse> {
  return isMockMode() ? mockRetryJob(jobId) : real.retryJob(jobId, fromStage);
}

export async function getPackage(packageId: string): Promise<TeacherKnowledgePackage> {
  return isMockMode() ? mockGetPackage(packageId) : real.getPackage(packageId);
}

export async function getValidation(packageId: string): Promise<ValidationReport> {
  return isMockMode() ? mockGetValidation(packageId) : real.getValidation(packageId);
}

export async function getArtifacts(packageId: string): Promise<ArtifactListing> {
  return isMockMode() ? mockGetArtifacts(packageId) : real.getArtifacts(packageId);
}

export function artifactDownloadUrl(packageId: string, kind: string): string {
  return isMockMode() ? mockArtifactDownloadUrl(packageId, kind) : real.artifactDownloadUrl(packageId, kind);
}

export async function getSamples(): Promise<SamplesResponse> {
  return isMockMode() ? mockGetSamples() : real.getSamples();
}

/** Triggers a real browser download for an artifact, using a blob in demo
 * mode (there is no network endpoint to hit) and the server's
 * `Content-Disposition: attachment` response otherwise. */
export async function downloadArtifact(packageId: string, kind: string): Promise<void> {
  if (isMockMode()) {
    const { blob, filename } = await fetchMockArtifact(kind);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return;
  }
  window.location.assign(artifactDownloadUrl(packageId, kind));
}

export function openEventStream(jobId: string, options: JobEventStreamOptions): JobEventStreamHandle {
  return isMockMode() ? openMockJobEventStream(jobId, options) : openJobEventStream(jobId, options);
}
