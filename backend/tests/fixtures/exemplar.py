"""The exemplar package the degradation suite breaks.

Separate from ``factories.py``, and deliberately so. That fixture is the minimum
package the *contracts* were written against — two concepts, two items, two
periods — which is the right shape for testing that a validator validates. It is
the wrong shape for testing that a rubric discriminates, for two reasons.

**It is too small.** "Every distractor is nonsense" applied to a bank with one
MCQ moves one number. Whether a rubric notices a defect should not depend on the
bank being big enough for the defect to appear twice, and a suite that measures a
two-item bank cannot tell the difference.

**It is not good enough.** ``factories._period_content`` builds period 2 by
calling the same function as period 1 with a different title, so the reference
package ships period 1's entry ticket, exit ticket, homework and mentor moment in
period 2 — the exact defect ``period_integrity`` exists to catch. Degrading a
package that already carries the degradation measures nothing: "duplicate the
periods" moved the score by 0.003 against that fixture, not because the check was
weak but because there was nothing left to break.

So this is a package with no headroom taken up by pre-existing faults: four
concepts on a real prerequisite chain, four periods whose content belongs to
them, an assessment bank with rubrics whose levels name different work, and
citations that appear in the chunks they cite. It scores near the top of the
rubric on purpose. Every point of that headroom is a point a sabotage can take
away, and a degradation suite is only as sharp as the distance between its
baseline and its floor.

It is *engineered*, not typical, and no conclusion about live pipeline output
should be drawn from its score. What it supports is a difference: this package
minus one defect, measured.
"""

from __future__ import annotations

import copy
from typing import Any

CONCEPTS = [
    {
        "concept_id": "concept_inertia",
        "entry_note": (
            "Collect three answers about inertia and write them up without correcting any."
        ),
        "misconception": "A moving object must have a force acting on it to keep moving.",
        "why": "Everyday motion always involves friction, which hides the frictionless case.",
        "correction": (
            "Uniform motion needs no net force; inertia maintains it until friction acts."
        ),
        "checkpoint_note": (
            "Pose the resting book question and count the hands claiming no force acts."
        ),
        "exit_note": "Sort the collected tickets by whether inertia is named in the explanation.",
        "name": "Inertia",
        "summary": "A body resists any change to its state of rest or uniform motion.",
        "chunk": "c_001",
        "quote": "A body continues in its state of rest or uniform motion",
        "board": ["Inertia resists change in motion", "Needs an external unbalanced force"],
        "entry": "Name one moment when inertia kept something moving after you stopped pushing it.",
        "expected": "Any example of continued motion, such as a rolling ball on a smooth floor.",
        "exit": "In one sentence, why do passengers lurch forward when a bus brakes?",
        "indicator": (
            "Answer states that inertia keeps the passenger moving, not that a force pushes."
        ),
        "check": "A book rests on a table. Does inertia mean no force acts on it?",
        "answer": "No - gravity and the normal force act and balance to zero net force.",
        "homework": "Find two examples of inertia at home and explain each in one sentence.",
        "story": "Galileo rolled balls down ramps for years before inertia had a name.",
        "activity_title": "Coin and card inertia demonstration",
        "activity_type": "demonstration",
        "steps": [
            "Balance a card on a glass and place a coin on the card.",
            "Flick the card sideways and ask the class to watch the coin closely.",
            "Ask why inertia left the coin behind when the card moved away.",
        ],
        "student": ["Predict where the coin lands before the card is flicked."],
        "support": "Give the sentence frame: 'The coin stayed because inertia means...'",
        "extension": "Repeat with a heavier coin and explain what changed about the inertia.",
        "criteria": ["Student predicts the coin falls into the glass and says why."],
        "stem": "A bus brakes suddenly and passengers lurch forward. Why?",
        "options": [
            (
                "A forward force acts on them",
                False,
                "Targets the belief that motion needs a force.",
            ),
            ("Their inertia keeps them moving while the bus slows", True, None),
            ("Gravity increases during braking", False, "Confuses weight with motion."),
            ("Air pressure pushes them forward", False, "Invents a force with no source."),
        ],
        "answer_key": "B",
        "bloom": "understand",
    },
    {
        "concept_id": "concept_second_law",
        "entry_note": "Take two predictions about acceleration and hold both until the derivation.",
        "misconception": "Heavier objects always accelerate faster because they weigh more.",
        "why": "Weight and mass are used interchangeably in ordinary speech.",
        "correction": "For a fixed net force a larger mass accelerates less, not more.",
        "checkpoint_note": "Ask which trolley accelerates more and insist the answer names mass.",
        "exit_note": "Take in the tickets and mark any answer that omits the acceleration unit.",
        "name": "Newton's Second Law",
        "summary": "Net force equals mass times acceleration.",
        "chunk": "c_002",
        "quote": "The acceleration of a body is proportional to the net force",
        "board": ["Net force = mass x acceleration", "Acceleration follows the net force"],
        "entry": "Write down what happens to acceleration if the net force doubles.",
        "expected": "Acceleration doubles, because acceleration is proportional to net force.",
        "exit": "A 2 kg block accelerates at 3 m/s2. What net force acts on it?",
        "indicator": "Answer gives 6 N and states the acceleration formula used.",
        "check": "Two trolleys of different mass feel the same net force. Which accelerates more?",
        "answer": (
            "The lighter trolley, because acceleration falls as mass rises for a fixed force."
        ),
        "homework": "Calculate the acceleration for three force and mass pairs given on the sheet.",
        "story": "Newton wrote the second law as a statement about momentum, not acceleration.",
        "activity_title": "Net force and acceleration problem set",
        "activity_type": "problem_set",
        "steps": [
            "Write the rearranged form a = F/m on the board before handing out the sheet.",
            "Work the first net force problem aloud, naming each substitution as you make it.",
            "Circulate while pairs complete the remaining acceleration problems.",
        ],
        "student": ["Solve each problem showing the substitution into a = F/m."],
        "support": "Give the rearranged form a = F/m at the top of the sheet.",
        "extension": "Introduce a two-force problem that requires finding the net force first.",
        "criteria": ["Student writes a = F/m and substitutes the given mass and force."],
        "stem": "A 4 kg trolley experiences a net force of 12 N. Find its acceleration.",
        "options": None,
        "answer_key": "3 m/s^2",
        "bloom": "apply",
    },
    {
        "concept_id": "concept_third_law",
        "entry_note": (
            "Ask four students to name the force the wall returns, and record each reply."
        ),
        "misconception": "The reaction force is weaker than the action force.",
        "why": "The pushed object often moves more, which looks like a smaller push back.",
        "correction": "The two forces are equal in size and act on different bodies.",
        "checkpoint_note": (
            "Ask the swimmer question and require the reaction force to be named aloud."
        ),
        "exit_note": (
            "Read the tickets at the door and set aside any naming one body in the reaction."
        ),
        "name": "Action and Reaction",
        "summary": "Every force on a body is matched by an equal opposite force on another body.",
        "chunk": "c_003",
        "quote": "To every action there is an equal and opposite reaction",
        "board": ["Action and reaction act on different bodies", "Equal size, opposite direction"],
        "entry": "When you push a wall, name the force the wall applies back to you.",
        "expected": "The wall pushes back on the hand with an equal and opposite reaction force.",
        "exit": "Why does an action reaction pair never cancel out on one body?",
        "indicator": "Answer states the reaction acts on the other body, so nothing cancels.",
        "check": "A swimmer pushes water backwards. Name the reaction and say what it acts on.",
        "answer": "The water pushes the swimmer forwards; the reaction acts on the swimmer.",
        "homework": "List three action reaction pairs at home and name the two bodies in each.",
        "story": "Rocket engines were doubted because critics forgot reaction needs no air.",
        "activity_title": "Balloon rocket reaction race",
        "activity_type": "experiment",
        "steps": [
            "Thread a straw on a line and tape an inflated balloon under the straw.",
            "Release the balloon and ask which reaction force drove it along the line.",
            "Repeat with two balloon sizes and compare the reaction each produced.",
        ],
        "student": ["Record how far the balloon travels and name the action reaction pair."],
        "support": "Label the two bodies on the board before pairs name the reaction force.",
        "extension": "Predict the effect of narrowing the balloon neck on the reaction force.",
        "criteria": ["Student names both bodies in the action reaction pair aloud."],
        "stem": "A swimmer pushes water backwards and moves forwards. Which pair is correct?",
        "options": [
            ("The swimmer pushes water back; water pushes the swimmer forward", True, None),
            (
                "The swimmer pushes water back; water pushes the water forward",
                False,
                "Puts both forces of the pair on the same body.",
            ),
            (
                "Gravity pushes the swimmer forward",
                False,
                "Substitutes a familiar force for the reaction.",
            ),
            (
                "The reaction acts later than the action",
                False,
                "Treats the pair as sequential rather than simultaneous.",
            ),
        ],
        "answer_key": "A",
        "bloom": "analyze",
    },
    {
        "concept_id": "concept_momentum",
        "entry_note": (
            "Gather a show of hands on the lorry, then ask one student to defend momentum."
        ),
        "misconception": "A crumple zone works by making the car stronger.",
        "why": "Damage is read as failure, so a bending car looks like a worse car.",
        "correction": (
            "Crumpling lengthens the stopping time, so the same momentum change needs less force."
        ),
        "checkpoint_note": (
            "Ask about the cricketer catching and listen for momentum and stopping time."
        ),
        "exit_note": "Gather the tickets and note which ones mention time as well as momentum.",
        "name": "Momentum",
        "summary": "Momentum is mass times velocity and changes only when a net force acts.",
        "chunk": "c_004",
        "quote": "the rate of change of momentum is proportional to the force applied",
        "board": ["Momentum = mass x velocity", "Force changes momentum over time"],
        "entry": "Which has more momentum: a slow lorry or a fast bicycle? Say why.",
        "expected": "The lorry, because momentum depends on mass as well as velocity.",
        "exit": "Explain why a longer stopping time reduces the force in a collision.",
        "indicator": (
            "Answer links the same momentum change spread over a longer time to less force."
        ),
        "check": "Why does a cricketer pull the hands back when catching a fast ball?",
        "answer": "Pulling back lengthens the time, so the momentum change needs less force.",
        "homework": "Compare the momentum of two vehicles from the table and justify the larger.",
        "story": "Crumple zones were resisted for years because a bent car looked like a failure.",
        "activity_title": "Egg drop momentum investigation",
        "activity_type": "think_pair_share",
        "steps": [
            "Drop an egg onto a hard tray and then onto a folded cloth of the same height.",
            "Ask pairs to explain the different outcomes using momentum and stopping time.",
            "Record the class explanations and correct any that omit the stopping time.",
        ],
        "student": ["Explain each outcome using momentum and the time taken to stop."],
        "support": "Give the prompt: 'The momentum change was the same, but the time was...'",
        "extension": (
            "Design a package that would let the egg survive a drop from twice the height."
        ),
        "criteria": ["Student names stopping time as the variable that changed."],
        "stem": "Why does a crumple zone reduce the force on a passenger in a crash?",
        "options": [
            (
                "It lengthens the time over which momentum changes",
                True,
                None,
            ),
            (
                "It reduces the momentum the car had before the crash",
                False,
                "Confuses reducing force with reducing the momentum itself.",
            ),
            (
                "It makes the car lighter during the collision",
                False,
                "Assumes mass changes during the impact.",
            ),
            (
                "It removes the reaction force from the barrier",
                False,
                "Denies the third law rather than applying momentum.",
            ),
        ],
        "answer_key": "A",
        "bloom": "analyze",
    },
]

PERIOD_MINUTES = 40


def _evidence(concept: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"chunk_id": concept["chunk"], "quote": concept["quote"], "page": 1}]


def build(base: dict[str, Any]) -> dict[str, Any]:
    package = copy.deepcopy(base)

    package["knowledge"]["concepts"] = [
        {
            "concept_id": c["concept_id"],
            "name": c["name"],
            "summary": c["summary"],
            "importance": "core",
            "concept_ids": [],
            "evidence": _evidence(c),
        }
        for c in CONCEPTS
    ]
    package["knowledge"]["keywords"] = [
        "inertia",
        "force",
        "acceleration",
        "mass",
        "reaction",
        "momentum",
        "velocity",
    ]
    package["knowledge"]["learning_objectives"] = [
        {
            "objective_id": f"obj_{i + 1}",
            "statement": statement,
            "bloom_level": bloom,
            "concept_ids": [CONCEPTS[i]["concept_id"]],
        }
        for i, (statement, bloom) in enumerate(
            [
                (
                    "Explain how inertia keeps a passenger moving when a vehicle brakes suddenly.",
                    "understand",
                ),
                (
                    "Calculate the acceleration of a body given its mass and the net force on it.",
                    "apply",
                ),
                (
                    "Distinguish the two bodies in an action reaction pair for a "
                    "situation students meet every day.",
                    "analyze",
                ),
                (
                    "Justify why a longer stopping time reduces the force in a collision.",
                    "evaluate",
                ),
            ]
        )
    ]
    package["knowledge"]["concept_graph"] = {
        "node_ids": [c["concept_id"] for c in CONCEPTS],
        "edges": [
            {
                "from_id": "concept_inertia",
                "to_id": "concept_second_law",
                "relation": "prerequisite_of",
                "confidence": 0.9,
            },
            {
                "from_id": "concept_second_law",
                "to_id": "concept_third_law",
                "relation": "prerequisite_of",
                "confidence": 0.85,
            },
            {
                "from_id": "concept_second_law",
                "to_id": "concept_momentum",
                "relation": "prerequisite_of",
                "confidence": 0.88,
            },
        ],
    }
    package["knowledge"]["definitions"] = [
        {
            "term": c["name"],
            "definition": c["summary"],
            "concept_ids": [c["concept_id"]],
            "evidence": _evidence(c),
        }
        for c in CONCEPTS
    ]
    package["knowledge"]["examples"] = [
        {
            "title": c["activity_title"],
            "body": c["summary"],
            "concept_ids": [c["concept_id"]],
            "evidence": _evidence(c),
        }
        for c in CONCEPTS[:2]
    ]
    package["knowledge"]["formulae"] = [
        {
            "name": "Newton's Second Law",
            "latex": r"ec{F} = mec{a}",
            "plain": "Net force equals mass times acceleration",
            "variables": [
                {"symbol": "F", "meaning": "net force", "unit": "N"},
                {"symbol": "m", "meaning": "mass", "unit": "kg"},
                {"symbol": "a", "meaning": "acceleration", "unit": "m/s^2"},
            ],
            "concept_ids": ["concept_second_law"],
            "evidence": _evidence(CONCEPTS[1]),
        }
    ]
    package["knowledge"]["applications"] = [
        {
            "context": c["name"],
            "description": c["summary"],
            "concept_ids": [c["concept_id"]],
            "evidence": _evidence(c),
        }
        for c in CONCEPTS[2:]
    ]
    package["knowledge"]["misconceptions"] = [
        {
            "misconception_id": f"mis_{i + 1}",
            "statement": c["misconception"],
            "why_it_happens": c["why"],
            "correction": c["correction"],
            "concept_ids": [c["concept_id"]],
            "evidence": _evidence(c),
        }
        for i, c in enumerate(CONCEPTS)
    ]

    package["teaching_plan"] = {
        "total_periods": len(CONCEPTS),
        "period_duration_minutes": PERIOD_MINUTES,
        "periods": [
            {
                "period_no": i + 1,
                "title": f"{c['name']} in everyday motion",
                "objective_ids": [f"obj_{i + 1}"],
                "concept_ids": [c["concept_id"]],
                "time_allocation": [
                    {"label": "Entry ticket", "minutes": 5},
                    {"label": "Direct instruction", "minutes": 15},
                    {"label": "Activity", "minutes": 12},
                    {"label": "Checkpoint", "minutes": 5},
                    {"label": "Exit ticket", "minutes": 3},
                ],
                "sequence_rationale": f"{c['name']} follows from the previous period's concept.",
            }
            for i, c in enumerate(CONCEPTS)
        ],
        "rationale": "Period count follows the four core concepts at one concept per period.",
    }

    package["classroom_content"] = [
        {
            "period_no": i + 1,
            "entry_ticket": {
                "prompt": c["entry"],
                "expected_response": c["expected"],
                "duration_minutes": 5,
            },
            "teacher_script": [
                {
                    "minute_start": 0,
                    "minute_end": 5,
                    "heading": "Entry ticket",
                    "speaker_notes": c["entry_note"],
                    "board_action": f"Write the three best {c['name']} examples in a column.",
                },
                {
                    "minute_start": 5,
                    "minute_end": 20,
                    "heading": f"{c['name']}",
                    "speaker_notes": f"Introduce {c['name']} using the student examples already "
                    f"on the board, then state it formally: {c['summary']}",
                    "board_action": f"Write '{c['board'][0]}' beneath the examples.",
                    "anticipated_questions": [c["check"]],
                },
                {
                    "minute_start": 20,
                    "minute_end": 32,
                    "heading": "Activity",
                    "speaker_notes": f"Run the {c['activity_title']}. Circulate and listen for "
                    f"anyone explaining the result without naming {c['name']}, then ask them "
                    f"directly: {c['check']}",
                    "board_action": f"Add the class result for {c['name']} under the statement.",
                },
                {
                    "minute_start": 32,
                    "minute_end": 37,
                    "heading": "Checkpoint",
                    "speaker_notes": c["checkpoint_note"],
                    "board_action": f"Tally the two answer types for {c['name']} on the board.",
                },
                {
                    "minute_start": 37,
                    "minute_end": 40,
                    "heading": "Exit ticket",
                    "speaker_notes": c["exit_note"],
                    "board_action": f"Leave '{c['board'][0]}' on the board as they write.",
                },
            ],
            "blackboard_notes": {
                "headings": [c["name"]],
                "bullet_points": c["board"],
                "diagrams_to_draw": [f"Force arrows illustrating {c['name']}"],
                "formulae_latex": [],
            },
            "activity_refs": [f"act_{i + 1}"],
            "checkpoint_questions": [
                {
                    "question": c["check"],
                    "expected_answer": c["answer"],
                    "bloom_level": c["bloom"],
                    "concept_ids": [c["concept_id"]],
                }
            ],
            "exit_ticket": {
                "prompt": c["exit"],
                "success_indicator": c["indicator"],
                "duration_minutes": 3,
            },
            "homework": {
                "tasks": [c["homework"]],
                "estimated_minutes": 20,
                "submission_format": "Notebook",
            },
            "mentor_moment": {
                "title": f"{c['name']} in its own time",
                "story": c["story"],
                "takeaway": "Ideas that look obvious now were argued over for decades.",
            },
        }
        for i, c in enumerate(CONCEPTS)
    ]

    package["activities"] = [
        {
            "activity_id": f"act_{i + 1}",
            "period_no": i + 1,
            "type": c["activity_type"],
            "title": c["activity_title"],
            "duration_minutes": 12,
            "grouping": "pairs",
            "materials": ["Coin", "Card", "Glass"] if i == 0 else [],
            "teacher_instructions": c["steps"],
            "student_instructions": c["student"],
            "success_criteria": c["criteria"],
            "differentiation": {"support": c["support"], "extension": c["extension"]},
            "concept_ids": [c["concept_id"]],
        }
        for i, c in enumerate(CONCEPTS)
    ]

    items: list[dict[str, Any]] = []
    for i, c in enumerate(CONCEPTS):
        if c["options"]:
            items.append(
                {
                    "item_id": f"item_mcq_{i + 1}",
                    "kind": "mcq",
                    "stem": c["stem"],
                    "options": [
                        {
                            "label": "ABCD"[n],
                            "text": text,
                            "is_correct": correct,
                            "rationale": rationale,
                        }
                        for n, (text, correct, rationale) in enumerate(c["options"])
                    ],
                    "answer": c["answer_key"],
                    "marks": 1,
                    "bloom_level": "understand" if c["bloom"] == "understand" else "apply",
                    "concept_ids": [c["concept_id"]],
                    "linked_misconception_id": f"mis_{i + 1}",
                }
            )
        else:
            items.append(
                {
                    "item_id": f"item_num_{i + 1}",
                    "kind": "numerical",
                    "stem": c["stem"],
                    "answer": c["answer_key"],
                    "working": "a = F/m = 12 N / 4 kg = 3 m/s^2",
                    "marks": 3,
                    "bloom_level": "apply",
                    "concept_ids": [c["concept_id"]],
                    "rubric": {
                        "criteria": "Method, substitution and units",
                        "levels": [
                            {
                                "label": "Complete",
                                "descriptor": "States acceleration = net force / mass, substitutes "
                                "12 N and 4 kg, and gives 3 with units.",
                                "marks": 3,
                            },
                            {
                                "label": "Partial",
                                "descriptor": (
                                    "Substitutes the net force and mass but omits the units."
                                ),
                                "marks": 2,
                            },
                            {
                                "label": "Minimal",
                                "descriptor": (
                                    "Quotes the acceleration formula with nothing substituted."
                                ),
                                "marks": 1,
                            },
                        ],
                    },
                }
            )

    items.append(
        {
            "item_id": "item_essay_1",
            "kind": "short_answer",
            "stem": "Explain why a crumple zone reduces the force on a passenger, using momentum.",
            "answer": "The crumple zone lengthens the stopping time for the same momentum change.",
            "marks": 6,
            "bloom_level": "evaluate",
            "concept_ids": ["concept_momentum", "concept_third_law"],
            "rubric": {
                "criteria": "Momentum change, stopping time, and the link to force",
                "levels": [
                    {
                        "label": "Complete",
                        "descriptor": "Names the momentum change, the longer stopping time, "
                        "and links both to the smaller force.",
                        "marks": 6,
                    },
                    {
                        "label": "Substantial",
                        "descriptor": "Names the momentum change and the stopping time but "
                        "does not link them to force.",
                        "marks": 4,
                    },
                    {
                        "label": "Partial",
                        "descriptor": "Mentions the stopping time only, with no momentum.",
                        "marks": 2,
                    },
                    {
                        "label": "Minimal",
                        "descriptor": "Asserts the crumple zone helps without naming momentum "
                        "or time.",
                        "marks": 1,
                    },
                ],
            },
        }
    )

    by_kind: dict[str, int] = {}
    by_bloom: dict[str, int] = {}
    marks_by_concept: dict[str, int] = {}
    for item in items:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
        by_bloom[item["bloom_level"]] = by_bloom.get(item["bloom_level"], 0) + 1
        for cid in item["concept_ids"]:
            marks_by_concept[cid] = marks_by_concept.get(cid, 0) + item["marks"]

    package["assessments"] = {
        "items": items,
        "blueprint": {
            "items_by_kind": by_kind,
            "items_by_bloom": by_bloom,
            "marks_by_concept": marks_by_concept,
        },
        "total_marks": sum(int(i["marks"]) for i in items),
    }

    package["learning_gaps"] = [
        {
            "gap_id": f"gap_{i + 2}",
            "misconception": c["misconception"],
            "concept_ids": [c["concept_id"]],
            "severity": "medium",
            "diagnostic_questions": [
                {
                    "question": c["check"],
                    "reveals": f"A wrong answer shows the student still believes "
                    f"{c['misconception']}",
                    "expected_wrong_answer": c["misconception"],
                }
            ],
            "remediation": [
                {
                    "action": f"Re-run the {c['activity_title']} and stop at the moment the "
                    "misconception would predict a different outcome.",
                    "rationale": c["correction"],
                    "estimated_minutes": 10,
                }
            ],
            "evidence": _evidence(c),
        }
        for i, c in enumerate(CONCEPTS[1:])
    ] + [
        {
            "gap_id": "gap_1",
            "misconception": "Motion requires a continuously applied force.",
            "concept_ids": ["concept_inertia"],
            "severity": "high",
            "diagnostic_questions": [
                {
                    "question": "A puck slides on frictionless ice. What force keeps it moving?",
                    "reveals": "Naming any force shows the inertia misconception is still held.",
                    "expected_wrong_answer": "A forward force left over from the push.",
                }
            ],
            "remediation": [
                {
                    "action": "Contrast a low friction and a high friction surface side by side.",
                    "rationale": "Isolates friction as the cause of stopping, not absent force.",
                    "estimated_minutes": 10,
                }
            ],
            "evidence": _evidence(CONCEPTS[0]),
        }
    ]
    return package


def chunk_texts() -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": c["chunk"],
            "text": (
                f"{c['quote']}. {c['summary']} {c['name']} is discussed here with "
                f"{c['board'][0]} and {c['board'][1]}. Students often think that "
                f"{c['misconception']} {c['correction']} {c['why']}"
            ),
        }
        for c in CONCEPTS
    ]
