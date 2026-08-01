"""Classroom readiness — could a teacher who has not pre-read this teach it?

That is the whole test, and it is a harder one than "does it contain a script".
What it decomposes into:

* **A script with board actions.** Speaker notes alone leave the board to
  improvisation, and the board is what the class copies down.
* **Tickets that diagnose.** An entry ticket needs an expected response or the
  teacher cannot tell in ten seconds who is ready; an exit ticket needs a success
  indicator that is *observable*, because it is marked at the door and not at home.
* **Board notes that are board notes.** Headings and short bullets, not a prose
  summary of the lesson. A 40-word bullet does not get written on a blackboard.
* **Checkpoints that check.** With an expected answer, and not every one of them
  at recall.
* **Homework worth setting.** "Revise the chapter" is not a task; it names no
  output and cannot be marked.
* **Periods that differ from each other.** Copy-pasting one period's tickets,
  homework and anecdote across the package is invisible to every schema check and
  obvious to the first teacher who reads two periods in a row. This is scored
  because it is the padding failure that most damages a package's credibility.

Readability against the grade band is measured and *reported at weight zero*.
Sentence length is a proxy for cognitive demand, and a proxy should not decide a
grade — but an obvious mismatch, undergraduate prose in a primary lesson, should
be visible to a reviewer.
"""

from __future__ import annotations

from evals.context import EvalContext
from evals.dimensions.activities import criterion_is_observable
from evals.expectations import readability_window
from evals.text import (
    distinct_ratio,
    has_concrete_anchor,
    long_word_share,
    mean_words_per_sentence,
    word_count,
)
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "classroom"
LABEL = "Classroom readiness"
WEIGHT = 0.08
METHOD = "deterministic"

#: Share of script segments that must say what goes on the board.
BOARD_ACTION_SHARE = 0.4
#: A bullet longer than this is a paragraph pretending to be a bullet.
MAX_BULLET_WORDS = 20
#: Speaker notes shorter than this are a heading, not a script.
MIN_NOTE_WORDS = 8


def score(ctx: EvalContext) -> DimensionScore:
    content = ctx.classroom_content
    if not content:
        return DimensionScore(
            key=KEY,
            label=LABEL,
            method=METHOD,
            weight=WEIGHT,
            metrics=(Metric("content_present", 0.0, 1.0, "no classroom content"),),
            findings=(
                Finding(
                    "CLS_NONE",
                    "/classroom_content",
                    "the package plans periods it supplies no content for",
                ),
            ),
        )

    findings: list[Finding] = []
    scripts: list[float] = []
    tickets: list[float] = []
    boards: list[float] = []
    checkpoints: list[float] = []
    homeworks: list[float] = []
    student_text: list[str] = []
    checkpoint_levels: list[str] = []

    for period in content:
        number = int(period.get("period_no") or 0)
        path = f"/classroom_content/{content.index(period)}"

        # --- script -----------------------------------------------------------
        segments = list(period.get("teacher_script") or [])
        with_board = [s for s in segments if str(s.get("board_action") or "").strip()]
        thin = [
            s for s in segments if word_count(str(s.get("speaker_notes") or "")) < MIN_NOTE_WORDS
        ]
        anticipated = any(s.get("anticipated_questions") for s in segments)
        script_checks = [
            1.0 if len(segments) >= 3 else 0.0,
            1.0 if segments and len(with_board) / len(segments) >= BOARD_ACTION_SHARE else 0.0,
            1.0 if not thin else 0.0,
            1.0 if anticipated else 0.0,
        ]
        scripts.append(sum(script_checks) / len(script_checks))
        if not with_board:
            findings.append(
                Finding(
                    "CLS_NO_BOARD_ACTIONS",
                    f"{path}/teacher_script",
                    f"period {number} never says what to write on the board, so the "
                    "notes the class copies down are improvised",
                )
            )
        if not anticipated:
            findings.append(
                Finding(
                    "CLS_NO_ANTICIPATED_QUESTIONS",
                    f"{path}/teacher_script",
                    f"period {number} anticipates no student question; the script has "
                    "no answer ready for the moment the lesson actually goes wrong",
                )
            )
        if thin:
            findings.append(
                Finding(
                    "CLS_THIN_SCRIPT",
                    f"{path}/teacher_script",
                    f"{len(thin)} of {len(segments)} segments in period {number} are "
                    "too short to be read aloud as written",
                )
            )

        # --- tickets ----------------------------------------------------------
        entry = period.get("entry_ticket") or {}
        exit_ticket = period.get("exit_ticket") or {}
        indicator = str(exit_ticket.get("success_indicator") or "")
        observable = criterion_is_observable(indicator)
        ticket_checks = [
            1.0 if word_count(str(entry.get("expected_response") or "")) >= 4 else 0.0,
            1.0 if has_concrete_anchor(str(entry.get("prompt") or ""), ctx.vocabulary) else 0.0,
            1.0 if observable is None else observable,
            1.0 if has_concrete_anchor(indicator, ctx.vocabulary) else 0.0,
        ]
        tickets.append(sum(ticket_checks) / len(ticket_checks))
        if observable == 0.0:
            findings.append(
                Finding(
                    "CLS_EXIT_TICKET_VAGUE",
                    f"{path}/exit_ticket/success_indicator",
                    f"{indicator[:70]!r} cannot be applied at the door; say what a "
                    "correct response must contain",
                )
            )
        student_text += [str(entry.get("prompt") or ""), str(exit_ticket.get("prompt") or "")]

        # --- board notes ------------------------------------------------------
        notes = period.get("blackboard_notes") or {}
        bullets = [str(b) for b in (notes.get("bullet_points") or [])]
        long_bullets = [b for b in bullets if word_count(b) > MAX_BULLET_WORDS]
        board_checks = [
            1.0 if notes.get("headings") else 0.0,
            1.0 if bullets else 0.0,
            1.0 if not long_bullets else 0.0,
        ]
        boards.append(sum(board_checks) / len(board_checks))
        if long_bullets:
            findings.append(
                Finding(
                    "CLS_BOARD_NOTES_ARE_PROSE",
                    f"{path}/blackboard_notes",
                    f"{len(long_bullets)} bullet(s) run past {MAX_BULLET_WORDS} words; "
                    "nobody writes a paragraph on a blackboard",
                )
            )

        # --- checkpoints ------------------------------------------------------
        questions = list(period.get("checkpoint_questions") or [])
        checkpoint_levels += [str(q.get("bloom_level") or "") for q in questions]
        answered = [q for q in questions if word_count(str(q.get("expected_answer") or "")) >= 4]
        checkpoints.append(len(answered) / len(questions) if questions else 0.0)
        if questions and len(answered) < len(questions):
            findings.append(
                Finding(
                    "CLS_CHECKPOINT_UNANSWERED",
                    f"{path}/checkpoint_questions",
                    f"period {number} poses questions with no usable expected answer",
                )
            )
        student_text += [str(q.get("question") or "") for q in questions]

        # --- homework ---------------------------------------------------------
        tasks = [str(t) for t in ((period.get("homework") or {}).get("tasks") or [])]
        specific = [
            t for t in tasks if word_count(t) >= 6 and has_concrete_anchor(t, ctx.vocabulary)
        ]
        homeworks.append(len(specific) / len(tasks) if tasks else 0.0)
        if tasks and not specific:
            sample = ", ".join(t[:40] for t in tasks[:2])
            findings.append(
                Finding(
                    "CLS_HOMEWORK_GENERIC",
                    f"{path}/homework",
                    f"period {number} sets work that names no output a student could "
                    f"hand in ({sample})",
                )
            )
        student_text += tasks

    # --- checkpoints across the package ---------------------------------------
    if len(checkpoint_levels) >= 2 and set(checkpoint_levels) == {"remember"}:
        checkpoints.append(0.0)
        findings.append(
            Finding(
                "CLS_CHECKPOINTS_ALL_RECALL",
                "/classroom_content",
                "every mid-lesson check is recall; the teacher learns who memorised the "
                "words and nothing about who followed the reasoning",
            )
        )

    # --- padding --------------------------------------------------------------
    signatures = [
        " ".join(
            [
                str((p.get("entry_ticket") or {}).get("prompt") or ""),
                str((p.get("exit_ticket") or {}).get("prompt") or ""),
                " ".join(str(t) for t in ((p.get("homework") or {}).get("tasks") or [])),
                str((p.get("mentor_moment") or {}).get("story") or ""),
            ]
        )
        for p in content
    ]
    distinctness = distinct_ratio(signatures)
    if distinctness < 1.0:
        findings.append(
            Finding(
                "CLS_PERIODS_DUPLICATED",
                "/classroom_content",
                f"only {distinctness:.0%} of periods are distinct in their tickets, "
                "homework and anecdote; a teacher reading two periods in a row will see "
                "the package repeat itself",
            )
        )

    # --- readability (reported, not scored) -----------------------------------
    window = readability_window(ctx.grade_band)
    words_per_sentence = mean_words_per_sentence(student_text)
    long_share = long_word_share(student_text)
    if window is None:
        readability_note = f"grade band {ctx.grade_band!r} names no grade; window not applied"
    else:
        readability_note = (
            f"{words_per_sentence:.1f} words/sentence "
            f"(band allows {window.max_words_per_sentence:.0f}), "
            f"{long_share:.0%} long words (allows {window.max_long_word_share:.0%})"
        )
        if (
            words_per_sentence > window.max_words_per_sentence
            or long_share > window.max_long_word_share
        ):
            findings.append(
                Finding(
                    "CLS_GRADE_MISMATCH",
                    "/classroom_content",
                    f"student-facing text reads above the {ctx.grade_band} band "
                    f"({readability_note}); reported as a proxy, confirm by reading",
                )
            )

    metrics = (
        Metric("script_usability", mean(scripts), 0.25, "timed, board actions, questions ready"),
        Metric("ticket_diagnostics", mean(tickets), 0.20, "entry and exit tickets that diagnose"),
        Metric("board_notes", mean(boards), 0.15, "headings and bullets, not prose"),
        Metric("checkpoints", mean(checkpoints), 0.15, "answerable mid-lesson checks"),
        Metric("homework", mean(homeworks), 0.10, "names an output that can be handed in"),
        Metric("distinct_periods", distinctness, 0.15, "periods differ from each other"),
        Metric("grade_readability", 0.0, 0.0, readability_note),
    )

    return DimensionScore(
        key=KEY,
        label=LABEL,
        method=METHOD,
        weight=WEIGHT,
        metrics=metrics,
        findings=tuple(findings),
    )
