import { useEffect, useRef, useState } from "react";
import { openEventStream } from "../api";
import type { JobEvent } from "../api/types";

/**
 * Consumes `GET /jobs/{id}/events` and keeps a durable, replayable timeline.
 *
 * The event log (and the highest `seq` seen) is mirrored to `sessionStorage`
 * keyed by job id. That is what makes a hard page refresh mid-run survivable
 * (H-02): on mount this hook seeds its state from whatever was persisted,
 * then reconnects passing that `seq` as `Last-Event-ID` — the server (real
 * or mock) replays only the frames that arrived after the tab was closed,
 * and the existing timeline in the UI does not flash or reset.
 *
 * `openEventStream` (see `api/sse.ts`) already handles the *within-session*
 * reconnect case (a dropped TCP connection) by tracking its own cursor and
 * retrying with backoff — this hook only has to handle the cross-reload
 * case, which needs storage `openJobEventStream` cannot own itself.
 */

const STORAGE_PREFIX = "eduforge:jobtimeline:";

interface PersistedTimeline {
  lastEventId: number;
  events: JobEvent[];
}

function storageKey(jobId: string): string {
  return STORAGE_PREFIX + jobId;
}

function loadPersisted(jobId: string): PersistedTimeline {
  try {
    const raw = window.sessionStorage.getItem(storageKey(jobId));
    if (!raw) return { lastEventId: 0, events: [] };
    const parsed = JSON.parse(raw) as PersistedTimeline;
    if (!Array.isArray(parsed.events)) return { lastEventId: 0, events: [] };
    return parsed;
  } catch {
    return { lastEventId: 0, events: [] };
  }
}

function savePersisted(jobId: string, timeline: PersistedTimeline): void {
  try {
    window.sessionStorage.setItem(storageKey(jobId), JSON.stringify(timeline));
  } catch {
    // Storage unavailable (private mode, quota) — the live stream still
    // works for the current page life, it just cannot survive a reload.
  }
}

/** Clears the persisted timeline for a job — used before a retry, so the
 * timeline restarts cleanly instead of appending a second run's events onto
 * the failed one's. */
export function clearJobTimeline(jobId: string): void {
  try {
    window.sessionStorage.removeItem(storageKey(jobId));
  } catch {
    // ignore
  }
}

export type ConnectionState = "connecting" | "open" | "retrying" | "closed";

export interface UseJobEventsResult {
  events: JobEvent[];
  connectionState: ConnectionState;
  resumed: boolean;
}

export function useJobEvents(jobId: string | null, resetToken: number = 0): UseJobEventsResult {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [resumed, setResumed] = useState(false);
  const lastSeqRef = useRef(0);

  useEffect(() => {
    if (!jobId) return;

    const persisted = loadPersisted(jobId);
    lastSeqRef.current = persisted.lastEventId;
    setEvents(persisted.events);
    setResumed(persisted.events.length > 0);
    setConnectionState("connecting");

    let cancelled = false;

    const handle = openEventStream(jobId, {
      lastEventId: persisted.lastEventId || null,
      onOpen: () => {
        if (!cancelled) setConnectionState("open");
      },
      onEvent: (event) => {
        if (cancelled) return;
        if (event.seq > 0) lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
        setEvents((prev) => {
          const next = [...prev, event];
          savePersisted(jobId, { lastEventId: lastSeqRef.current, events: next });
          return next;
        });
        if (event.event === "completed" || event.event === "failed") {
          setConnectionState("closed");
        }
      },
      onError: (_err, willRetry) => {
        if (cancelled) return;
        setConnectionState(willRetry ? "retrying" : "closed");
      },
    });

    return () => {
      cancelled = true;
      handle.close();
    };
  }, [jobId, resetToken]);

  return { events, connectionState, resumed };
}
