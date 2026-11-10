"""The sample RCM study's worksheet: a delivery truck's brakes and drivetrain,
with each decision linked to the sample model or analysis that stands behind
it (backend/services/samples.py seeds it)."""

from __future__ import annotations

import copy

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


def sample_truck_functions() -> list[dict]:
    """The sample study's worksheet, a fresh copy each time."""
    return copy.deepcopy(SAMPLE_TRUCK_FUNCTIONS)
