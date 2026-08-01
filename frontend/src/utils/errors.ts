import { ApiError } from "../api/types";

/**
 * One place that turns any thrown value into something a teacher can read.
 *
 * Every page used to re-implement this, and each version ended with
 * `if (err instanceof Error) return err.message` — which is how a user came to
 * be shown `TypeError: Failed to fetch`, and, before `ApiError` was hardened,
 * `Cannot read properties of undefined (reading 'message')`. An exception
 * string is a fact about our code; it is never an instruction to the person
 * reading it.
 *
 * Copy is from `docs/14-design-system.md` §10.2. Each entry says what happened
 * and what to do next, because an error without a next step just tells someone
 * they are stuck.
 */

export interface FriendlyError {
  title: string;
  body: string;
  /** Label for the recovery action, when there is one worth offering. */
  action?: string;
}

const GENERIC: FriendlyError = {
  title: "Something went wrong",
  body: "An unexpected error occurred. Try again, or come back in a few minutes.",
  action: "Try again",
};

const BY_CODE: Record<string, FriendlyError> = {
  empty_document: {
    title: "Could not use this file",
    body: "The file is empty. Choose a document with content in it.",
    action: "Choose a different file",
  },
  document_too_large: {
    title: "File is too large",
    body: "That file is over the 25 MB limit. Try a smaller export, or split the chapter into two uploads.",
    action: "Choose a different file",
  },
  unsupported_media_type: {
    title: "Unsupported file type",
    body: "EduForge reads PDF, DOCX, PPTX, TXT and Markdown. This file doesn't match any of those.",
    action: "Choose a different file",
  },
  document_not_found: {
    title: "Could not start the job",
    body:
      "The uploaded document couldn't be found on the server. This can happen if the server " +
      "restarted since you uploaded — documents aren't kept permanently yet. Upload the file again.",
    action: "Upload again",
  },
  job_not_found: {
    title: "Job not found",
    body: "This run doesn't exist, or the record has expired.",
    action: "Start a new one",
  },
  job_not_retryable: {
    title: "Can't retry this run",
    body:
      "Only a failed, cancelled, or partially-succeeded run can be retried, and this one is in " +
      "none of those states.",
    action: "Start a different document",
  },
  package_not_found: {
    title: "Package not found",
    body: "This package doesn't exist, or hasn't finished generating yet.",
    action: "Start a new one",
  },
  internal_error: {
    title: "Something went wrong on our end",
    body:
      "This wasn't caused by anything you did. Try again in a minute — if it keeps happening, " +
      "the server may be restarting.",
    action: "Try again",
  },
  network_unreachable: {
    title: "Could not reach EduForge",
    body: "The connection dropped before the request finished. Check your connection and try again.",
    action: "Try again",
  },
};

/**
 * `invalid_request` is deliberately passed through rather than rewritten.
 *
 * The backend already flattens Pydantic's error list into one plain sentence
 * naming the field that failed ("document_id: Input should be a valid UUID"),
 * which is more useful and more specific than anything a generic string here
 * could say.
 */
function validationError(message: string): FriendlyError {
  return {
    title: "Could not start the job",
    body: message || "The request was rejected. Check the form and try again.",
    action: "Check the form and try again",
  };
}

/** True for the shapes a dropped connection actually throws in a browser. */
function isNetworkFailure(err: unknown): boolean {
  if (err instanceof TypeError) return true; // fetch() rejects with TypeError
  return err instanceof DOMException && err.name === "NetworkError";
}

export function describeError(err: unknown): FriendlyError {
  if (err instanceof ApiError) {
    if (err.code === "invalid_request") return validationError(err.message);
    const known = BY_CODE[err.code];
    if (known) return known;
    // An unmapped code still carries a server-authored message, which beats
    // the generic fallback — but the status is what makes it actionable.
    return {
      title: err.status >= 500 ? "Something went wrong on our end" : "That request was rejected",
      body: err.message || `The server returned status ${err.status}.`,
      action: "Try again",
    };
  }

  if (err instanceof DOMException && err.name === "AbortError") {
    return { title: "Request cancelled", body: "The request was stopped before it finished." };
  }

  if (isNetworkFailure(err)) return BY_CODE.network_unreachable;

  return GENERIC;
}

/** Single-line form, for inline field errors and toasts. */
export function describeErrorText(err: unknown): string {
  const { title, body } = describeError(err);
  return `${title} — ${body}`;
}

/** The trace id, when the server supplied one. Worth showing on a 500: it is
 * how a reported failure gets found in the structured logs. */
export function traceIdOf(err: unknown): string | undefined {
  return err instanceof ApiError ? err.traceId : undefined;
}
