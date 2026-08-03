/**
 * What a run has actually found, read back out of the messages it streamed.
 *
 * The pipeline already says the interesting things — "2693 blocks, 63 chunks",
 * "Physics · quantitative", "10 concepts, 10 objectives" — and until now the
 * screen showed each of them for a few seconds and then dropped them. They are
 * the only concrete facts a watcher gets before the package exists, so they are
 * lifted out of the log and kept for the rest of the run.
 *
 * Parsing a human-readable message is a bet on a string the backend is free to
 * reword, so every parser here is written to lose that bet quietly:
 *
 *   - Each pattern is anchored and specific. A message that does not match
 *     produces no finding at all; it stays in the activity log, where it is
 *     still perfectly readable. Nothing is guessed from a partial match.
 *   - Nothing is derived that the message does not literally contain. There is
 *     no "estimated total" or "projected count" here, only what was said.
 *   - A stage with no parser is not a gap to fill. Most stages emit progress
 *     narration ("verifying citations") rather than a result, and narration
 *     belongs in the log, not in a chip that persists for twenty minutes.
 *
 * The patterns mirror the stage modules under `backend/stages`; each one cites
 * the file and line it came from, so a reworded message can be traced back
 * rather than puzzled over.
 */

import { labelFor } from "./format";
import type { StageKey } from "./stages";

export interface Finding {
  /**
   * Stable across re-parses. Findings are recomputed from the whole event list
   * on every new event, so a stable key is what stops React from tearing down
   * and rebuilding a chip that did not change.
   */
  id: string;
  label: string;
  value: string;
}

/** Returns the findings a message yields, or null if it is not one we read. */
type Parser = (message: string) => Finding[] | null;

/** Digits as a person writes them: 2693 -> "2,693". */
function count(raw: string): string {
  const value = Number.parseInt(raw, 10);
  return Number.isFinite(value) ? value.toLocaleString() : raw;
}

/**
 * Two of these patterns match on punctuation worth naming, because it is not
 * the ASCII a reader will assume: classification separates subject from profile
 * with U+00B7 MIDDLE DOT, and validation separates status from counts with
 * U+2014 EM DASH. Both appear literally in the patterns below, matching the
 * literals in the backend source.
 *
 * The failure mode to know about: an editor or a copy-paste that normalises
 * either character to an ASCII hyphen breaks only the match, silently. Nothing
 * throws and no chip appears — which is indistinguishable from the backend
 * having reworded the message, and is why the affected findings are the ones
 * to check first if a chip stops showing up.
 */
const PARSERS: Partial<Record<StageKey, Parser>> = {
  // s1_document_intelligence/stage.py:558 — f"{len(document.blocks)} blocks, {len(chunks)} chunks"
  "document-intelligence": (message) => {
    const hit = /^(\d+) blocks?, (\d+) chunks?$/.exec(message);
    if (!hit) return null;
    return [{ id: "source", label: "Parsed", value: `${count(hit[1])} blocks, ${count(hit[2])} chunks` }];
  },

  // s2_classification/stage.py:198 — f"{classification.subject} · {classification.pedagogy_profile}"
  "educational-classification": (message) => {
    const hit = /^([^·]{1,60}) · ([^·]{1,60})$/.exec(message);
    if (!hit) return null;
    const subject = hit[1].trim();
    const profile = hit[2].trim();
    if (!subject || !profile) return null;
    return [
      { id: "subject", label: "Subject", value: labelFor(subject) },
      { id: "profile", label: "Pedagogy profile", value: labelFor(profile) },
    ];
  },

  // s3_knowledge/stage.py:690 — f"{n} concepts, {m} objectives"
  "knowledge-extraction": (message) => {
    const hit = /^(\d+) concepts?, (\d+) objectives?$/.exec(message);
    if (!hit) return null;
    return [
      { id: "concepts", label: "Concepts", value: count(hit[1]) },
      { id: "objectives", label: "Objectives", value: count(hit[2]) },
    ];
  },

  // s4_planner/stage.py:368 — f"{n} periods x {d} min, {c} concepts sequenced"
  "teaching-planner": (message) => {
    const hit = /^(\d+) periods? x (\d+) min, (\d+) concepts? sequenced$/.exec(message);
    if (!hit) return null;
    return [{ id: "periods", label: "Periods", value: `${count(hit[1])} × ${hit[2]} min` }];
  },

  // s6_activities/stage.py:301 — f"{n} activities, {m} distinct types"
  "activity-generation": (message) => {
    const hit = /^(\d+) activities, (\d+) distinct types?$/.exec(message);
    if (!hit) return null;
    return [
      { id: "activities", label: "Activities", value: `${count(hit[1])}, ${hit[2]} types` },
    ];
  },

  // s7_assessments/stage.py:463 — f"{len(items)} items, {bank.total_marks} marks"
  "assessment-generation": (message) => {
    const hit = /^(\d+) items?, (\d+) marks?$/.exec(message);
    if (!hit) return null;
    return [{ id: "questions", label: "Questions", value: `${count(hit[1])}, ${count(hit[2])} marks` }];
  },

  // s8_gaps/stage.py:287 — f"{len(gaps)} gaps, {high} high severity"
  "gap-analysis": (message) => {
    const hit = /^(\d+) gaps?, (\d+) high severity$/.exec(message);
    if (!hit) return null;
    // "0 high" is worth saying — it is a result, not an absence — but it does
    // not deserve the same phrasing as a run that found six.
    const high = Number.parseInt(hit[2], 10);
    return [
      {
        id: "gaps",
        label: "Learning gaps",
        value: high > 0 ? `${count(hit[1])}, ${high} high severity` : count(hit[1]),
      },
    ];
  },

  // s9_validation/stage.py:178 — f"{status} — {len(issues)} issue(s), grounding {score:.2f}"
  validation: (message) => {
    const hit = /^(\S+) — (\d+) issue\(s\), grounding ([\d.]+)$/.exec(message);
    if (!hit) return null;
    const findings: Finding[] = [
      { id: "validation", label: "Validation", value: labelFor(hit[1]) },
    ];
    const grounding = Number.parseFloat(hit[3]);
    // A score outside 0..1 is not a score this screen understands. Dropping it
    // costs one chip; rendering it would put "1400% grounded" on the page.
    if (Number.isFinite(grounding) && grounding >= 0 && grounding <= 1) {
      findings.push({
        id: "grounding",
        label: "Grounding",
        value: `${Math.round(grounding * 100)}%`,
      });
    }
    return findings;
  },

  // s10_publishing/stage.py:82 — f"published {n} of {m} artifact(s): {names}"
  // Deliberately unanchored at the end: the message continues with the artifact
  // names, which belong in the log rather than in a chip.
  publishing: (message) => {
    const hit = /^published (\d+) of (\d+) artifact\(s\)/.exec(message);
    if (!hit) return null;
    return [{ id: "artifacts", label: "Files", value: `${hit[1]} of ${hit[2]}` }];
  },
};

/**
 * The order chips appear in, which is the order the pipeline discovers them.
 *
 * Fixed rather than insertion-ordered so a chip cannot jump position when a
 * later stage revises an earlier value — a row of facts that reshuffles while
 * being read is harder to follow than one that simply grows.
 */
const ORDER = [
  "source",
  "subject",
  "profile",
  "concepts",
  "objectives",
  "periods",
  "activities",
  "questions",
  "gaps",
  "validation",
  "grounding",
  "artifacts",
];

interface ParsableEvent {
  stage: string;
  message?: string | null;
}

/**
 * Every finding the run has revealed so far, oldest fact first.
 *
 * Derived from the full event list rather than accumulated into state: the list
 * is already the durable record — it survives a refresh through sessionStorage
 * and a reconnect through `Last-Event-ID` replay — so mirroring it into a
 * second store would only create something to keep in sync.
 */
export function findingsFrom(events: readonly ParsableEvent[]): Finding[] {
  const found = new Map<string, Finding>();

  for (const event of events) {
    if (typeof event.message !== "string") continue;
    const message = event.message.trim();
    if (!message) continue;

    const parse = PARSERS[event.stage as StageKey];
    if (!parse) continue;

    let parsed: Finding[] | null = null;
    try {
      parsed = parse(message);
    } catch {
      // A parser is a nicety; a run screen that throws is not. Whatever the
      // message was, it is already rendered in the activity log.
      continue;
    }
    // A later event legitimately supersedes an earlier one for the same id —
    // a stage that retried reports its final count last.
    for (const finding of parsed ?? []) found.set(finding.id, finding);
  }

  return ORDER.map((id) => found.get(id)).filter((f): f is Finding => f !== undefined);
}
