"""Templates: ready-made positions a workspace can copy into its own tree.

The sample delivery truck: one position with an RCM built on it (two
functions, their functional failures, five failure modes, each with its
consequence and decision, and evidence linked to the sample model and
analyses every account can read). One decision, the legacy run-to-failure
plan on the wheel bearings, is linked to a model that contradicts it (the
bearing Weibull shows wear-out), so the evidence check shows red on purpose.

A copy is made through the ordinary service methods, so it is events like
any change a person makes, in the caller's own workspace only. Nothing is
seeded for anyone who never asks. The read-only sample RCM study is seeded
from the same content (backend/services/samples.py), so the two can't drift.
"""

from __future__ import annotations

import copy
import re

SAMPLE_TRUCK_NAME = "Delivery truck (sample)"
SAMPLE_TRUCK_DESCRIPTION = (
    "A sample: the brakes and drivetrain of a delivery truck, with every RCM decision linked to its evidence. "
    "One decision is contradicted on purpose: the legacy run-to-failure plan on the wheel bearings, whose own "
    "model shows wear-out."
)

# Functions › functional failures › failure modes, each mode with its decision.
# The ids are the sample study's (a copy onto the tree gets new ones).
SAMPLE_TRUCK_FUNCTIONS = [
    {
        "id": "sample-rcm-f1",
        "text": "Stop the vehicle within the rated distance",
        "failures": [
            {
                "id": "sample-rcm-f1-ff1",
                "text": "Insufficient braking force",
                "modes": [
                    {
                        "id": "sample-rcm-m1",
                        "text": "Brake pad wear beyond the 8 mm limit",
                        "effects": "Extended stopping distance; risk of collision.",
                        "consequence": "safety",
                        "decision": {
                            "outcome": "on_condition",
                            "task": "Measure pad wear at each service; replace before the 8 mm threshold.",
                            "evidence": {"type": "degradation_model", "id": "sample-deg-brake-wear"},
                        },
                    },
                    {
                        "id": "sample-rcm-m2",
                        "text": "Secondary hydraulic circuit failed (hidden until demanded)",
                        "effects": "No redundancy on primary circuit failure.",
                        "consequence": "hidden",
                        "decision": {
                            "outcome": "failure_finding",
                            "task": "Function-test the secondary circuit.",
                            "evidence": {"type": "strategy_analysis", "id": "sample-strategy-ffi-brake-circuit"},
                        },
                    },
                ],
            },
        ],
    },
    {
        "id": "sample-rcm-f2",
        "text": "Transmit drive to the wheels",
        "failures": [
            {
                "id": "sample-rcm-f2-ff1",
                "text": "Wheel does not rotate freely",
                "modes": [
                    {
                        "id": "sample-rcm-m3",
                        "text": "Wheel-bearing fatigue",
                        "effects": "Vehicle immobilised; tow required.",
                        "consequence": "operational",
                        "decision": {
                            "outcome": "fixed_interval",
                            "task": "Replace wheel bearings preventively.",
                            "interval": 580,
                            "interval_unit": "hours",
                            "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"},
                        },
                    },
                    {
                        "id": "sample-rcm-m4",
                        "text": "Wheel-bearing failure — legacy run-to-failure plan",
                        "effects": "As above; inherited from the old maintenance plan.",
                        "consequence": "operational",
                        "decision": {
                            "outcome": "rtf",
                            "rtf_basis": "random",
                            "notes": "Legacy decision — kept to demonstrate live evidence validation.",
                            "evidence": {"type": "model", "id": "sample-model-bearings-weibull"},
                        },
                    },
                    {
                        "id": "sample-rcm-m5",
                        "text": "Chassis cracking at the spring hanger",
                        "effects": "Structural risk under load.",
                        "consequence": "safety",
                        "decision": {
                            "outcome": "redesign",
                            "notes": "No task can manage the risk — reinforcement redesign raised with engineering.",
                        },
                    },
                ],
            },
        ],
    },
]

_COPY_NAME = re.compile(r"^Delivery truck \(sample(?: (\d+))?\)$")


def _n(count: int, one: str) -> str:
    return f"{count} {one}" if count == 1 else f"{count} {one}s"


def sample_truck_functions() -> list[dict]:
    """The sample truck's RCM, a fresh copy each time (callers may change it)."""
    return copy.deepcopy(SAMPLE_TRUCK_FUNCTIONS)


def sample_trucks(m) -> list[dict]:
    """Copies of the sample truck in this workspace (live positions with its name)."""
    return sorted((p for p in m.s.nodes(m.org, "Position") if not p.get("retired") and _COPY_NAME.match(p["name"])),
                  key=lambda p: p["name"])


def _copy_name(existing: list[dict]) -> str:
    taken = {int(match.group(1) or 1) for p in existing if (match := _COPY_NAME.match(p["name"]))}
    if 1 not in taken:
        return SAMPLE_TRUCK_NAME
    n = 2
    while n in taken:
        n += 1
    return f"Delivery truck (sample {n})"


def add_sample_truck(m, again: bool = False) -> dict:
    """Copy the sample truck into ``m``'s workspace as a new top-level position
    with its RCM. When a copy is already there, nothing is added unless
    ``again`` (then it's another copy, numbered)."""
    existing = sample_trucks(m)
    if existing and not again:
        have = existing[0]
        return {
            "added": False,
            "position": {"id": have["id"], "name": have["name"]},
            "message": f"The sample truck is already in your tree as “{have['name']}”. "
                       "Ask again to add another copy.",
        }
    position = m.create_position(_copy_name(existing), description=SAMPLE_TRUCK_DESCRIPTION)
    pid = position["id"]
    counts = {"functions": 0, "functional_failures": 0, "failure_modes": 0, "decisions": 0}
    for fn in sample_truck_functions():
        function = m.add_function(pid, fn["text"], fn.get("standard", ""))
        counts["functions"] += 1
        for failure in fn["failures"]:
            ff = m.add_functional_failure(function["id"], failure["text"])
            counts["functional_failures"] += 1
            for mode in failure["modes"]:
                fm = m.add_failure_mode(pid, mode["text"], functional_failure_id=ff["id"])
                counts["failure_modes"] += 1
                if mode.get("effects") or mode.get("notes"):
                    m.update_failure_mode(fm["id"], effects=mode.get("effects"), notes=mode.get("notes"))
                m.decide_failure_mode(fm["id"], consequence=mode.get("consequence"), decision=mode.get("decision"))
                counts["decisions"] += bool(mode.get("decision"))
    counts["tasks"] = len(m._tasks_on(pid))
    return {
        "added": True,
        "position": {"id": pid, "name": position["name"]},
        **counts,
        "message": (f"Added “{position['name']}” to your tree: {_n(counts['functions'], 'function')}, "
                    f"{_n(counts['failure_modes'], 'failure mode')}, each with its decision, and "
                    f"{_n(counts['tasks'], 'scheduled task')}. One decision shows as contradicted on purpose: "
                    "its own model shows wear-out."),
    }
