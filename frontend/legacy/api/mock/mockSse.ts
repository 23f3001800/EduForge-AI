import type { JobEventStreamHandle, JobEventStreamOptions } from "../sse";
import type { JobEvent, JobStatus } from "../types";
import { getScriptFor } from "./schedule";
import { loadMockJob, saveMockJob } from "./store";

/**
 * Drop-in replacement for `openJobEventStream` used when demo mode is on.
 * Same contract as the real thing: every event carries `stage` + `progress`,
 * `Last-Event-ID` (here, `options.lastEventId`) causes exactly the missed
 * frames to replay before it "goes live", and terminal events end the
 * stream. Because scheduling is derived from `Date.now() - createdAtMs`
 * rather than an interval that starts over on each connect, a page refresh
 * mid-run reconnects with no gap and no duplicate — the same property the
 * real SSE endpoint has to prove (H-02).
 */
export function openMockJobEventStream(
  jobId: string,
  options: JobEventStreamOptions,
): JobEventStreamHandle {
  let closed = false;
  const timers: ReturnType<typeof setTimeout>[] = [];

  const state = loadMockJob(jobId);
  if (!state) {
    queueMicrotask(() => {
      if (!closed) options.onError?.(new Error(`Unknown demo job "${jobId}".`), false);
    });
    return {
      close() {
        closed = true;
      },
    };
  }

  const script = getScriptFor(state.scenario);
  const alreadySeen = options.lastEventId ?? 0;

  function finalize(frame: (typeof script)[number]) {
    const fresh = loadMockJob(jobId);
    if (!fresh) return;
    const status: JobStatus =
      frame.event === "completed"
        ? ((frame.extra?.status as JobStatus | undefined) ?? "succeeded")
        : "failed";
    fresh.status = status;
    fresh.packageId = (frame.extra?.package_id as string | undefined) ?? fresh.packageId;
    saveMockJob(fresh);
  }

  queueMicrotask(() => {
    if (closed) return;
    options.onOpen?.();

    const nowElapsed = Date.now() - state.createdAtMs;
    script.forEach((frame, idx) => {
      const seq = idx + 1;
      if (seq <= alreadySeen) return; // already delivered before the reconnect
      const fireInMs = Math.max(0, frame.atMs - nowElapsed);
      const timer = setTimeout(() => {
        if (closed) return;
        const current = loadMockJob(jobId);
        if (current?.cancelled) return;

        const event: JobEvent = {
          seq,
          event: frame.event,
          data: {
            stage: frame.stage,
            progress: frame.progress,
            ...(frame.message ? { message: frame.message } : {}),
            ...(frame.extra ?? {}),
          },
        };
        options.onEvent(event);

        if (frame.event === "completed" || frame.event === "failed") {
          finalize(frame);
        }
      }, fireInMs);
      timers.push(timer);
    });
  });

  return {
    close() {
      closed = true;
      timers.forEach(clearTimeout);
    },
  };
}
