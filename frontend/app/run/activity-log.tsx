"use client";

import { ArrowDown } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatClock, labelFor } from "@/lib/format";
import { isStageKey, progressAfter, STAGE_LABELS, STAGE_WEIGHTS } from "@/lib/stages";
import type { StreamEvent } from "@/lib/use-job-stream";

/**
 * The run, line by line.
 *
 * A 25-minute build reporting only a percentage is indistinguishable from a
 * 25-minute build that has hung. The stream has always carried the difference —
 * "map-reduce over 2 passes", "item 7 of 24 (numerical)", "period 3 of 5" — and
 * the screen used to keep the last three lines of the current stage and discard
 * the rest. This keeps all of it.
 *
 * The scroll behaviour is the part worth being careful about. Auto-scrolling to
 * the newest line is right until the moment someone scrolls up to read
 * something, at which point yanking them back to the bottom every few seconds
 * makes the log unreadable exactly when they are trying to read it. So the
 * pin is released the moment they scroll away from the bottom and only retaken
 * when they ask for it, or scroll back down themselves.
 */

/**
 * How many rows stay in the DOM.
 *
 * A normal run emits a few hundred events; a fan-out over a large assessment
 * bank emits more, and nothing in the protocol bounds it. Windowing to the tail
 * keeps the DOM flat without a virtualiser — and the tail is the part being
 * watched. The count of what is not shown is rendered, so the window is a
 * stated limit rather than silent truncation.
 */
const MAX_ROWS = 400;

/**
 * How close to the bottom still counts as "at the bottom".
 *
 * Zero would be wrong: sub-pixel layout and a fractional device pixel ratio
 * routinely leave `scrollHeight - scrollTop - clientHeight` at 0.5 or so when
 * the element is scrolled fully down, which would release the pin on the very
 * scroll event that auto-scrolling just caused.
 */
const AT_BOTTOM_SLACK_PX = 24;

interface Row {
  seq: number;
  stageLabel: string;
  /** `+3:42` from the run's origin, or null when the frame carried no usable `ts`. */
  offset: string | null;
  body: string;
  level: "info" | "warning" | "error";
}

/**
 * What a frame says, when it says nothing.
 *
 * `stage_span` (backend/stages/base.py:148,152) brackets every stage with a
 * `progress(0.0)` and a `progress(1.0)` that carry no message. Rendering those
 * as blank rows would be noise, and skipping them would drop the only frames
 * that mark where one stage ends and the next begins.
 *
 * So they are named from the number they do carry. `cumulative_progress` maps a
 * stage's 0.0 to the weight total before it and its 1.0 to the total including
 * it, both of which this client already mirrors — making "started" and
 * "complete" read off the wire rather than assumed.
 */
function bodyOf(event: StreamEvent): string {
  const message = typeof event.message === "string" ? event.message.trim() : "";
  if (message) return message;

  const progress = event.progress;
  if (isStageKey(event.stage) && typeof progress === "number" && Number.isFinite(progress)) {
    const end = progressAfter(event.stage);
    if (progress >= end) return "complete";
    if (progress <= end - STAGE_WEIGHTS[event.stage]) return "started";
  }
  return typeof progress === "number" && Number.isFinite(progress) ? `${progress}%` : "working";
}

/**
 * How far into the run this frame landed.
 *
 * Measured between two server timestamps, so it is unaffected by a browser
 * clock that disagrees with the server's — the one number on this screen that
 * is completely immune to skew.
 */
function offsetOf(event: StreamEvent, originMs: number | null): string | null {
  if (originMs === null || typeof event.ts !== "string") return null;
  const ms = Date.parse(event.ts);
  if (!Number.isFinite(ms)) return null;
  return `+${formatClock(Math.max(0, (ms - originMs) / 1000))}`;
}

function levelOf(level: StreamEvent["level"]): Row["level"] {
  return level === "warning" || level === "error" ? level : "info";
}

interface ActivityLogProps {
  events: StreamEvent[];
  /** Server time the run began, in ms. Row offsets are measured from it. */
  originMs: number | null;
  /** False once the run reached a terminal state; drops the "live" affordances. */
  live: boolean;
}

export function ActivityLog({ events, originMs, live }: ActivityLogProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);

  const rows = useMemo<Row[]>(
    () =>
      (events.length > MAX_ROWS ? events.slice(-MAX_ROWS) : events).map((event) => ({
        seq: event.seq,
        stageLabel: isStageKey(event.stage) ? STAGE_LABELS[event.stage] : labelFor(event.stage),
        offset: offsetOf(event, originMs),
        body: bodyOf(event),
        level: levelOf(event.level),
      })),
    [events, originMs],
  );

  const hidden = events.length - rows.length;
  const newest = rows.length ? rows[rows.length - 1] : null;

  const jump = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
    setPinned(true);
  }, []);

  const handleScroll = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    const fromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setPinned(fromBottom <= AT_BOTTOM_SLACK_PX);
  }, []);

  // Keyed on the newest seq rather than on `rows`, so a re-render that did not
  // add a line (a tick of the elapsed clock, one per second) does not scroll.
  const newestSeq = newest?.seq ?? null;
  useEffect(() => {
    if (!pinned) return;
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
    // Assigning scrollTop directly rather than scrollTo({behavior:"smooth"}):
    // a smooth scroll per event is motion nobody asked for, and it would still
    // be animating when the next event arrives.
  }, [newestSeq, pinned]);

  return (
    <section aria-labelledby="activity-heading" className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border px-4 py-3">
        <h2 id="activity-heading" className="text-sm font-semibold">
          Activity
        </h2>
        <p className="font-mono text-xs tabular-nums text-fg-faint">
          {events.length === 1 ? "1 update" : `${events.length} updates`}
        </p>
      </div>

      <div className="relative">
        {/* Focusable so the log can be scrolled from the keyboard. A scrollable
            region that only a mouse wheel can reach is a scrollable region half
            the people here cannot read. */}
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          tabIndex={0}
          role="region"
          aria-label="Run activity log"
          className="max-h-[17rem] overflow-y-auto overscroll-contain px-4 py-3 sm:max-h-[24rem]"
        >
          {rows.length === 0 ? (
            <p className="text-sm text-fg-muted">
              {live
                ? "Waiting for the first update from the worker."
                : "This run recorded no activity."}
            </p>
          ) : (
            <>
              {hidden > 0 ? (
                <p className="mb-2 text-xs text-fg-faint">
                  {hidden.toLocaleString()} earlier {hidden === 1 ? "update is" : "updates are"} not
                  shown.
                </p>
              ) : null}
              <ol className="space-y-2">
                {rows.map((row) => (
                  <li
                    key={row.seq}
                    /* Two columns at 360px with the message on its own line
                       beneath the stage, three columns from `sm` where the
                       message fits beside it. No fixed pixel widths, so a long
                       stage name shrinks its column instead of pushing the
                       page sideways. */
                    className="grid grid-cols-[3rem_minmax(0,1fr)] items-baseline gap-x-2 gap-y-0.5 text-xs sm:grid-cols-[3.25rem_8rem_minmax(0,1fr)]"
                  >
                    <span className="col-start-1 row-start-1 font-mono tabular-nums text-fg-faint">
                      {row.offset}
                    </span>
                    <span className="col-start-2 row-start-1 truncate font-medium text-fg-muted">
                      {row.stageLabel}
                    </span>
                    <span
                      className={cn(
                        "col-start-2 row-start-2 [overflow-wrap:anywhere] sm:col-start-3 sm:row-start-1",
                        row.level === "error"
                          ? "text-danger"
                          : row.level === "warning"
                            ? "text-warning"
                            : "text-fg",
                      )}
                    >
                      {/* Severity is a word before it is a colour, so it
                          survives greyscale and colour blindness. */}
                      {row.level !== "info" ? (
                        <Badge
                          tone={row.level === "error" ? "danger" : "warning"}
                          className="mr-1.5 align-middle"
                        >
                          {row.level === "error" ? "Error" : "Warning"}
                        </Badge>
                      ) : null}
                      {row.body}
                    </span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>

        {/* Only offered when it would do something. A "jump to latest" that is
            always visible while already at the latest is a button that teaches
            people its state means nothing. */}
        {!pinned && rows.length > 0 ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-2 flex justify-center">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={jump}
              className="pointer-events-auto min-h-[2.75rem] shadow-lg"
            >
              <ArrowDown aria-hidden /> Jump to latest
            </Button>
          </div>
        ) : null}
      </div>

      {/* One live region for the whole log, carrying only the newest line.
          Marking up every row as live would announce the entire backlog on
          arrival and then interrupt continuously for the rest of the run. */}
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {newest ? `${newest.stageLabel}: ${newest.body}` : ""}
      </p>
    </section>
  );
}
