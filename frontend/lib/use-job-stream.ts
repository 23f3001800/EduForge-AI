"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "./api";

/**
 * The live progress stream.
 *
 * Two separate resume problems, needing different mechanisms:
 *
 *   1. The connection drops mid-run. `EventSource` reconnects on its own and
 *      resends the last event id it saw, so the server replays only what was
 *      missed.
 *   2. The tab is refreshed, or closed and reopened. The browser remembers
 *      nothing, so the timeline is mirrored into sessionStorage keyed by job.
 *      On mount we seed from that and reconnect past it.
 *
 * Without (2), a refresh at minute nine shows an empty timeline for a run that
 * is three quarters done — which reads as "it broke", the exact impression the
 * resumable stream exists to prevent.
 *
 * Events are keyed by `seq`, so a replay overlapping what we already have is
 * idempotent rather than duplicating rows.
 */

export interface StreamEvent {
  seq: number;
  stage: string;
  progress: number;
  level: "info" | "warning" | "error";
  message?: string | null;
  ts?: string | null;
  /**
   * Additive keys the emitter puts on the terminal `completed` frame: the id of
   * the package that was published, and the validation status that decided
   * whether the job ended `succeeded` or `succeeded_partial`.
   *
   * Optional and typed `unknown`-ish on purpose — these come out of
   * `JSON.parse`, so every reader narrows before rendering.
   */
  package_id?: string | null;
  status?: string | null;
}

export type ConnectionState = "connecting" | "open" | "closed";

const STORAGE_PREFIX = "eduforge:timeline:";

function load(jobId: string): StreamEvent[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_PREFIX + jobId);
    const parsed = raw ? (JSON.parse(raw) as StreamEvent[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function save(jobId: string, events: StreamEvent[]): void {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + jobId, JSON.stringify(events));
  } catch {
    // Private mode or quota. The live stream still works for this page's life;
    // it just cannot survive a reload. Not worth surfacing to a user.
  }
}

/**
 * The terminal marker inside a timeline, if it is already there.
 *
 * Needed because of how (2) above interacts with replay: after a refresh the
 * restored timeline may already contain the `completed` or `failed` frame, and
 * the reconnect resumes *past* it — so the server correctly sends nothing, and a
 * `terminal` state derived only from newly arriving frames stays null forever.
 * That left a finished run rendering as "Building your package", reconnecting to
 * a stream that had nothing left to say.
 */
function terminalOf(events: StreamEvent[]): "completed" | "failed" | null {
  for (const event of events) {
    if (event.stage === "completed") return "completed";
    if (event.stage === "failed") return "failed";
  }
  return null;
}

export function clearTimeline(jobId: string): void {
  try {
    sessionStorage.removeItem(STORAGE_PREFIX + jobId);
  } catch {
    /* ignore */
  }
}

export function useJobStream(jobId: string | null, enabled = true) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [terminal, setTerminal] = useState<"completed" | "failed" | null>(null);
  const seen = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!jobId || !enabled) return;

    const restored = load(jobId);
    seen.current = new Set(restored.map((e) => e.seq));
    setEvents(restored);

    const restoredTerminal = terminalOf(restored);
    if (restoredTerminal) {
      // The run is over and its whole timeline is in hand. Opening a stream here
      // would connect, receive nothing, be closed by the server and be retried
      // by the browser, forever — for a job that can never emit again.
      setTerminal(restoredTerminal);
      setConnection("closed");
      return;
    }

    const lastSeq = restored.reduce((max, e) => Math.max(max, e.seq), 0);
    // EventSource cannot set request headers, so the cursor goes in the query
    // string; the endpoint accepts either form precisely because of that.
    const url = `${API_BASE}/jobs/${jobId}/events${lastSeq ? `?last_event_id=${lastSeq}` : ""}`;
    const source = new EventSource(url);

    source.onopen = () => setConnection("open");

    const handle = (raw: MessageEvent) => {
      let event: StreamEvent;
      try {
        event = JSON.parse(raw.data) as StreamEvent;
      } catch {
        return; // one malformed frame must not take down the stream
      }
      if (seen.current.has(event.seq)) return;
      seen.current.add(event.seq);

      setEvents((previous) => {
        const next = [...previous, event].sort((a, b) => a.seq - b.seq);
        save(jobId, next);
        return next;
      });

      if (event.stage === "completed" || event.stage === "failed") {
        setTerminal(event.stage === "completed" ? "completed" : "failed");
        // Same reasoning as the restore path: the server closes the stream after
        // a terminal frame, and an EventSource left open reconnects on its own.
        source.close();
        setConnection("closed");
      }
    };

    // Every name the server can put in an SSE `event:` field, from
    // `backend/api/routes/events.py::_event_name`. A frame whose name has no
    // listener is not delivered to `onmessage` — that only receives frames with
    // no name at all — so a missing name here is a frame the UI never sees.
    //
    // "warning" was missing, and it is the name the server uses for *every*
    // frame at level warning or error that is not the terminal one. So the
    // stages that reported trouble streamed it, the server persisted it, replay
    // resent it, and the client dropped it on the floor: no warning ever
    // reached the timeline, no stage was ever marked as having warned, and a
    // mid-run error was invisible unless it also killed the job.
    source.onmessage = handle;
    source.addEventListener("progress", handle as EventListener);
    source.addEventListener("warning", handle as EventListener);
    source.addEventListener("completed", handle as EventListener);
    source.addEventListener("failed", handle as EventListener);

    source.onerror = () => {
      // EventSource retries by itself; report the gap rather than tearing down,
      // so the UI can say "reconnecting" instead of "broken".
      setConnection((state) => (state === "open" ? "connecting" : state));
    };

    return () => {
      source.close();
      setConnection("closed");
    };
  }, [jobId, enabled]);

  const reset = useCallback(() => {
    if (jobId) clearTimeline(jobId);
    seen.current = new Set();
    setEvents([]);
    setTerminal(null);
  }, [jobId]);

  const progress = events.reduce((max, event) => Math.max(max, event.progress), 0);

  return { events, progress, connection, terminal, reset };
}
