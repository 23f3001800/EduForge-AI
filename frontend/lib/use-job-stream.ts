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

      if (event.stage === "completed") setTerminal("completed");
      if (event.stage === "failed") setTerminal("failed");
    };

    source.onmessage = handle;
    source.addEventListener("progress", handle as EventListener);
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
