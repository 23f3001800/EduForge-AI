import { API_BASE } from "./constants";
import type { JobEvent, JobEventName } from "./types";

/**
 * Resumable SSE client for `GET /jobs/{id}/events` (docs/06-api-spec.md §3, H-02).
 *
 * Deliberately NOT the native `EventSource`. `EventSource` cannot set arbitrary
 * request headers on its *initial* connection — it only ever sends
 * `Last-Event-ID` automatically on a reconnect it initiates itself, while the
 * page stays open. That covers a dropped TCP connection, but it does nothing
 * for the case the spec actually grades: the user hits refresh, JS re-runs
 * from scratch, and a brand new `EventSource` has no memory of what it saw
 * before. To resume across a real page reload we have to send
 * `Last-Event-ID` on the *first* request too, which requires a header we
 * control — so this is a small hand-rolled reader over `fetch` +
 * `ReadableStream` instead. No dependency added: `fetch`/`ReadableStream`/
 * `TextDecoder` are platform APIs.
 *
 * The caller is responsible for persisting `seq` across reloads (see
 * `useJobEvents`) and passing it back in as `lastEventId`.
 */

export interface JobEventStreamHandlers {
  onEvent: (event: JobEvent) => void;
  /** Fired once the HTTP response headers arrive and the stream is live. */
  onOpen?: () => void;
  /** Fired on a connection failure. The stream will still try to reconnect
   * unless `terminal` is true or the stream was closed. */
  onError?: (error: unknown, willRetry: boolean) => void;
}

export interface JobEventStreamOptions extends JobEventStreamHandlers {
  lastEventId?: number | null;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  /** Milliseconds with no bytes (including heartbeats) before the connection
   * is considered stale and force-reconnected. Server heartbeats every 15s
   * per the spec, so 40s gives it margin for jitter/proxies. */
  staleTimeoutMs?: number;
  maxBackoffMs?: number;
}

export interface JobEventStreamHandle {
  close: () => void;
}

const TERMINAL_EVENTS: ReadonlySet<JobEventName> = new Set(["completed", "failed"]);

function parseSseBlock(block: string): { id?: string; event?: string; data: string } | null {
  const lines = block.split("\n");
  let id: string | undefined;
  let event: string | undefined;
  const dataLines: string[] = [];

  for (const rawLine of lines) {
    if (rawLine === "" || rawLine.startsWith(":")) continue; // comment / heartbeat
    const colonIdx = rawLine.indexOf(":");
    const field = colonIdx === -1 ? rawLine : rawLine.slice(0, colonIdx);
    const value = colonIdx === -1 ? "" : rawLine.slice(colonIdx + 1).replace(/^ /, "");
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
  }

  if (dataLines.length === 0 && !id && !event) return null;
  return { id, event, data: dataLines.join("\n") };
}

export function openJobEventStream(
  jobId: string,
  options: JobEventStreamOptions,
): JobEventStreamHandle {
  const {
    lastEventId = null,
    baseUrl = API_BASE,
    fetchImpl = fetch,
    staleTimeoutMs = 40_000,
    maxBackoffMs = 15_000,
    onEvent,
    onOpen,
    onError,
  } = options;

  let closed = false;
  let attempt = 0;
  let currentLastEventId: number | null = lastEventId;
  let controller: AbortController | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  function clearStaleTimer() {
    if (staleTimer) {
      clearTimeout(staleTimer);
      staleTimer = null;
    }
  }

  function armStaleTimer() {
    clearStaleTimer();
    staleTimer = setTimeout(() => {
      controller?.abort();
    }, staleTimeoutMs);
  }

  async function connectOnce(): Promise<"terminal" | "ended" | "aborted"> {
    controller = new AbortController();
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (currentLastEventId != null) {
      headers["Last-Event-ID"] = String(currentLastEventId);
    }

    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}/jobs/${encodeURIComponent(jobId)}/events`, {
        headers,
        signal: controller.signal,
      });
    } catch (err) {
      if (controller.signal.aborted && closed) return "aborted";
      throw err;
    }

    if (!response.ok || !response.body) {
      throw new Error(`Event stream request failed with status ${response.status}`);
    }

    onOpen?.();
    armStaleTimer();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        armStaleTimer();
        buffer += decoder.decode(value, { stream: true });

        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const rawBlock = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const parsed = parseSseBlock(rawBlock);
          if (parsed && parsed.data) {
            const seq = parsed.id ? Number(parsed.id) : NaN;
            // Defensive dedup: never hand the caller a seq we've already
            // delivered, even if a reconnect races with the tail of the
            // previous response.
            if (!Number.isNaN(seq) && currentLastEventId != null && seq <= currentLastEventId) {
              boundary = buffer.indexOf("\n\n");
              continue;
            }
            try {
              const data = JSON.parse(parsed.data);
              const eventName = (parsed.event as JobEventName) ?? "progress";
              if (!Number.isNaN(seq)) currentLastEventId = seq;
              onEvent({ seq: Number.isNaN(seq) ? -1 : seq, event: eventName, data });
              if (TERMINAL_EVENTS.has(eventName)) {
                clearStaleTimer();
                controller.abort();
                return "terminal";
              }
            } catch {
              // A malformed frame should never take down the whole stream.
            }
          }
          boundary = buffer.indexOf("\n\n");
        }
      }
      return "ended";
    } catch (err) {
      if (controller.signal.aborted) {
        return closed ? "aborted" : "ended";
      }
      throw err;
    } finally {
      clearStaleTimer();
      reader.releaseLock();
    }
  }

  async function runLoop() {
    while (!closed) {
      try {
        const outcome = await connectOnce();
        if (outcome === "terminal" || outcome === "aborted") return;
        // "ended": server closed the stream without a terminal event
        // (e.g. proxy timeout). Reconnect from the last seq we saw.
        attempt = 0;
      } catch (err) {
        attempt += 1;
        const willRetry = !closed;
        onError?.(err, willRetry);
        if (!willRetry) return;
        const backoff = Math.min(maxBackoffMs, 500 * 2 ** attempt) + Math.random() * 300;
        await new Promise<void>((resolve) => {
          retryTimer = setTimeout(resolve, backoff);
        });
      }
    }
  }

  void runLoop();

  return {
    close() {
      if (closed) return;
      closed = true;
      clearStaleTimer();
      if (retryTimer) clearTimeout(retryTimer);
      controller?.abort();
    },
  };
}
