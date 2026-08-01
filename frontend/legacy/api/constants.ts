/**
 * Values mirrored from docs/01-srs.md §4.1 and docs/03-lld.md (`config/models.yaml` defaults:
 * MAX_UPLOAD_MB=25, MAX_PAGES=300). These are for the *client-side pre-check* only — the server
 * remains the source of truth (it sniffs MIME, not just extension) and every one of these limits
 * is re-validated there. Getting the pre-check wrong only costs the user an extra round trip, never
 * correctness.
 */
export const MAX_UPLOAD_MB = 25;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
export const MAX_PAGES = 300;

export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".txt", ".md"] as const;

export const ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "text/plain",
  "text/markdown",
] as const;

export const API_BASE = "/api/v1";
