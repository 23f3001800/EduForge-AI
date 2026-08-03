"""Classroom readiness — could a teacher who has not pre-read this teach it?

That is the whole test, and it is a harder one than "does it contain a script".
What it decomposes into:

* **A script with board actions.** Speaker notes alone leave the board to
  improvisation, and the board is what the class copies down.
* **Speaker notes that instruct.** This dimension used to test note *length*: a
  segment under eight words was thin, and anything longer passed. Padding is long
  by construction, so the measured effect was that replacing every note in the
  reference package with one sentence of filler — the same sentence, twelve times
  — **raised** the package's score. A note now has to contain an imperative, avoid
  generic-teaching phrasing, and name something this package teaches; and the
  notes have to differ from each other, because one sentence repeated twelve times
  is one note, not twelve.
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

from evals.context import EvalContext, coerce_int
from evals.dimensions.activities import criterion_is_observable
from evals.discrimination import has_imperative, is_generic_script, names_package_content
from evals.expectations import readability_window
from evals.text import (
    distinct_ratio,
    long_word_share,
    mean_words_per_sentence,
    word_count,
)
from evals.types import DimensionScore, Finding, Metric, mean

__all__ = ["KEY", "LABEL", "METHOD", "WEIGHT", "score"]

KEY = "classroom"
LABEL = "Classroom readiness"
WEIGHT = 0.15
METHOD = "deterministic"

#: Share of script segments that must say what goes on the board.
BOARD_ACTION_SHARE = 0.4
#: A bullet longer than this is a paragraph pretending to be a bullet.
MAX_BULLET_WORDS = 20
#: Share of a period's segments whose notes must be actionable — an imperative,
#: no generic-teaching phrasing, and a referent from this package. Not 1.0: a
#: transition segment ("Collect exit tickets at the door") is a legitimate part of
#: a script and names nothing subject-specific, and demanding otherwise would push
#: the generator toward stuffing keywords into stage directions.
ACTIONABLE_NOTE_SHARE = 0.4


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
    segment_scores: list[float] = []
    tickets: list[float] = []
    boards: list[float] = []
    checkpoints: list[float] = []
    homeworks: list[float] = []
    student_text: list[str] = []
    checkpoint_levels: list[str] = []
    all_notes: list[str] = []

    for period in content:
        number = coerce_int(period.get("period_no"))
        path = f"/classroom_content/{content.index(period)}"

        # --- script -----------------------------------------------------------
        segments = list(period.get("teacher_script") or [])
        with_board = [s for s in segments if str(s.get("board_action") or "").strip()]

        all_notes += [str(s.get("speaker_notes") or "") for s in segments]

        # Every segment is scored on its own, and the note carries most of the
        # weight, because the note *is* the script — the heading is a label and
        # the board action is one line. Under the old checklist a period could
        # lose a single one-of-five check for having twelve identical filler
        # notes, which is how filler came to score above the real thing.
        actionable = []
        referenced = []
        filler = []
        for segment in segments:
            notes = str(segment.get("speaker_notes") or "")
            instructs = has_imperative(notes) and not is_generic_script(notes)
            # The referent is looked for in the note first: a board action that
            # names the concept does not rescue a note that says nothing.
            names_it = names_package_content(
                f"{notes} {segment.get('heading') or ''}", ctx.vocabulary
            )
            has_board = bool(str(segment.get("board_action") or "").strip())
            segment_scores.append(
                0.50 * (1.0 if instructs else 0.0)
                + 0.35 * (1.0 if names_it else 0.0)
                + 0.15 * (1.0 if has_board else 0.0)
            )
            if instructs:
                actionable.append(segment)
            if names_it:
                referenced.append(segment)
            if is_generic_script(notes):
                filler.append(segment)

        anticipated = any(s.get("anticipated_questions") for s in segments)
        completeness_checks = [
            1.0 if len(segments) >= 3 else 0.0,
            1.0 if segments and len(with_board) / len(segments) >= BOARD_ACTION_SHARE else 0.0,
            1.0 if anticipated else 0.0,
        ]
        scripts.append(sum(completeness_checks) / len(completeness_checks))
        if filler:
            findings.append(
                Finding(
                    "CLS_SCRIPT_IS_FILLER",
                    f"{path}/teacher_script",
                    f"{len(filler)} of {len(segments)} segments in period {number} are prose "
                    "about teaching rather than instructions to teach ('engage the students', "
                    "'ensure everyone is following'); a teacher reading this aloud is told "
                    "nothing to do",
                )
            )
        if segments and len(referenced) / len(segments) < ACTIONABLE_NOTE_SHARE:
            findings.append(
                Finding(
                    "CLS_SCRIPT_UNANCHORED",
                    f"{path}/teacher_script",
                    f"only {len(referenced)} of {len(segments)} segments in period {number} "
                    "name anything this package teaches; the script would fit any lesson on "
                    "any topic, which means it was not written for this one",
                )
            )
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
        # --- tickets ----------------------------------------------------------
        entry = period.get("entry_ticket") or {}
        exit_ticket = period.get("exit_ticket") or {}
        indicator = str(exit_ticket.get("success_indicator") or "")
        observable = criterion_is_observable(indicator)
        # `names_package_content` rather than `has_concrete_anchor`: the latter
        # accepts any digit or colon as evidence of concreteness, so "Spend 5
        # minutes recalling yesterday" scored as an anchored prompt.
        ticket_checks = [
            1.0 if word_count(str(entry.get("expected_response") or "")) >= 4 else 0.0,
            1.0 if names_package_content(str(entry.get("prompt") or ""), ctx.vocabulary) else 0.0,
            1.0 if observable is None else observable,
            1.0 if names_package_content(indicator, ctx.vocabulary) else 0.0,
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
        board = period.get("blackboard_notes") or {}
        bullets = [str(b) for b in (board.get("bullet_points") or [])]
        long_bullets = [b for b in bullets if word_count(b) > MAX_BULLET_WORDS]
        board_checks = [
            1.0 if board.get("headings") else 0.0,
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
            t for t in tasks if word_count(t) >= 6 and names_package_content(t, ctx.vocabulary)
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

    # One sentence of filler repeated across twelve segments is one note, not
    # twelve, and every length-based check reads it as a fuller script than the
    # twelve different notes it replaced.
    note_distinctness = distinct_ratio(all_notes)
    if note_distinctness < 1.0:
        findings.append(
            Finding(
                "CLS_SCRIPT_SELF_REPEATING",
                "/classroom_content",
                f"only {note_distinctness:.0%} of speaker notes across the package are "
                "distinct; the same sentence is standing in for a script in more than one "
                "segment",
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
        Metric(
            "script_actionability",
            mean(segment_scores),
            0.28,
            f"{len(segment_scores)} segment(s): does the note instruct, name this "
            "package's content, and say what goes on the board?",
        ),
        Metric(
            "distinct_speaker_notes",
            note_distinctness,
            0.14,
            f"{len(all_notes)} script segment(s); one sentence repeated is one note",
        ),
        Metric(
            "script_completeness",
            mean(scripts),
            0.05,
            "enough segments, board actions across them, a question anticipated",
        ),
        Metric("ticket_diagnostics", mean(tickets), 0.16, "entry and exit tickets that diagnose"),
        Metric("board_notes", mean(boards), 0.10, "headings and bullets, not prose"),
        Metric("checkpoints", mean(checkpoints), 0.12, "answerable mid-lesson checks"),
        Metric("homework", mean(homeworks), 0.05, "names an output that can be handed in"),
        Metric("distinct_periods", distinctness, 0.10, "periods differ from each other"),
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
