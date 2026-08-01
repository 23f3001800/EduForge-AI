import { useEffect, useRef } from "react";
import type { JobEvent } from "../../api/types";
import { stageLabel } from "../../api/stages";
import { Badge } from "../ui/Badge";

function levelTone(event: JobEvent): "danger" | "warning" | "success" | "neutral" {
  if (event.event === "failed") return "danger";
  if (event.event === "completed") return "success";
  if (event.event === "warning") return "warning";
  return "neutral";
}

function eventTime(event: JobEvent): string {
  const ts = (event.data as { ts?: string }).ts;
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return "";
  }
}

/** Chronological, append-only activity log — the visible proof that the SSE
 * stream is resumable: after a refresh the earlier entries reappear from the
 * replayed `Last-Event-ID` frames instead of restarting empty. */
export function EventLog({ events }: { events: JobEvent[] }) {
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  if (events.length === 0) {
    return <p className="ef-muted">Waiting for the first progress event…</p>;
  }

  return (
    <ol className="ef-event-log" ref={listRef} aria-label="Progress log" aria-live="polite">
      {events.map((event, idx) => (
        <li key={`${event.seq}-${idx}`} className="ef-event-log__item">
          <Badge tone={levelTone(event)}>{event.event}</Badge>
          <span className="ef-event-log__stage">{stageLabel(event.data.stage)}</span>
          {event.data.message ? <span className="ef-event-log__message">{event.data.message}</span> : null}
          <span className="ef-event-log__progress">{event.data.progress}%</span>
          <span className="ef-event-log__time">{eventTime(event)}</span>
        </li>
      ))}
    </ol>
  );
}
