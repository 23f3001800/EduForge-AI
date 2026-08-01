import type { JobStatus } from "../types";
import type { MockScenario } from "./schedule";

/**
 * Mock "server" state, persisted to `sessionStorage` so it survives a real
 * browser reload — which is the whole point: the Run screen's resumable-SSE
 * behaviour needs something durable to resume *from* even when there is no
 * backend. Job progress is derived from `createdAtMs` + wall-clock time, not
 * from a stored event log, so a refreshed tab recomputes exactly which
 * frames "already happened" — the same replay-then-tail shape the real
 * server implements against `job_events.seq`.
 */
export interface MockJobState {
  jobId: string;
  documentId: string;
  scenario: MockScenario;
  createdAtMs: number;
  cancelled: boolean;
  cancelledAtMs: number | null;
  status: JobStatus;
  packageId: string | null;
  idempotencyKey?: string;
}

export interface MockDocumentState {
  documentId: string;
  filename: string;
  sha256: string;
  scenario: MockScenario;
}

const JOB_PREFIX = "eduforge:mockjob:";
const DOC_PREFIX = "eduforge:mockdoc:";
const IDEMPOTENCY_PREFIX = "eduforge:mockidem:";
const SHA_PREFIX = "eduforge:mocksha:";

function store(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveMockJob(state: MockJobState): void {
  store()?.setItem(JOB_PREFIX + state.jobId, JSON.stringify(state));
}

export function loadMockJob(jobId: string): MockJobState | null {
  const raw = store()?.getItem(JOB_PREFIX + jobId);
  return raw ? (JSON.parse(raw) as MockJobState) : null;
}

export function saveMockDocument(doc: MockDocumentState): void {
  store()?.setItem(DOC_PREFIX + doc.documentId, JSON.stringify(doc));
}

export function loadMockDocument(documentId: string): MockDocumentState | null {
  const raw = store()?.getItem(DOC_PREFIX + documentId);
  return raw ? (JSON.parse(raw) as MockDocumentState) : null;
}

export function findDocumentBySha(sha256: string): MockDocumentState | null {
  const raw = store()?.getItem(SHA_PREFIX + sha256);
  return raw ? loadMockDocument(raw) : null;
}

export function indexDocumentSha(sha256: string, documentId: string): void {
  store()?.setItem(SHA_PREFIX + sha256, documentId);
}

export function findJobByIdempotencyKey(key: string): string | null {
  return store()?.getItem(IDEMPOTENCY_PREFIX + key) ?? null;
}

export function indexIdempotencyKey(key: string, jobId: string): void {
  store()?.setItem(IDEMPOTENCY_PREFIX + key, jobId);
}
