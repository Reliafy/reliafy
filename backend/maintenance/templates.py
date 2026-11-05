"""Templates: ready-made positions a workspace can copy into its own tree.

The sample delivery truck: one position with an RCM built on it (two
functions, their functional failures, five failure modes, each with its
consequence and decision, and evidence linked to the sample model and
analyses every account can read). One decision, the legacy run-to-failure
plan on the wheel bearings, is linked to a model that contradicts it (the
bearing Weibull shows wear-out), so the evidence check shows red on purpose.
Each mode is scored as an FME(C)A too (severity, occurrence, detection, the
cause and effects, the recommended action and the criticality figures).

The sample quadcopter UAV: a small tree (airframe, propulsion, power, flight
control, comms, payload) whose sixteen failure modes are all scored, as a
design FME(C)A reads. Three positions carry their modes directly under a
function with no functional failure yet, on purpose, to show how an FMEA row
reads back on the RCM tab. Entirely invented: no real product.

A copy is made through the ordinary service methods, so it is events like
any change a person makes, in the caller's own workspace only. Nothing is
seeded for anyone who never asks.
"""

from __future__ import annotations

import copy
import re
from datetime import date, timedelta

from backend.maintenance import fmea

SAMPLE_TRUCK_NAME = "Delivery truck (sample)"
SAMPLE_TRUCK_DESCRIPTION = (
    "A sample: the brakes and drivetrain of a delivery truck, with every RCM decision linked to its evidence. "
    "One decision is contradicted on purpose: the legacy run-to-failure plan on the wheel bearings, whose own "
    "model shows wear-out."
)

# Functions › functional failures › failure modes, each mode with its decision.
# The ids are the template's own (a copy onto the tree gets new ones).
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
                        "cause": "Normal friction wear, faster with heavy loads",
                        "effect_local": "Pad thickness below 8 mm", "effect_next": "Longer stopping distance",
                        "detection_method": "Pad gauge at each service",
                        "severity": 8, "occurrence": 6, "detection": 2,  # RPN 96, AP M
                        "action": "Fit wear-indicator pads", "action_owner": "Fleet engineer",
                        "action_due": "2026-12-01", "action_status": "open",
                        "failure_rate": 2e-4, "mode_ratio": 0.7, "loss_probability": 0.2, "severity_class": "II",
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
                        "cause": "Seal perishes in the slave cylinder",
                        "effect_local": "Secondary circuit holds no pressure",
                        "effect_next": "No redundancy if the primary circuit fails",
                        "detection_method": "None in normal driving (hidden); function test",
                        "severity": 9, "occurrence": 2, "detection": 9,  # RPN 162, AP M
                        "action": "Monthly function test of the secondary circuit", "action_owner": "Workshop",
                        "action_due": "2026-11-30", "action_status": "in_progress",
                        "failure_rate": 5e-5, "mode_ratio": 0.3, "loss_probability": 0.5, "severity_class": "I",
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
                        "cause": "Rolling-contact fatigue",
                        "effect_local": "Bearing noise and heat", "effect_next": "Wheel seizes",
                        "detection_method": "Temperature check on the hub at each service",
                        "severity": 7, "occurrence": 5, "detection": 4,  # RPN 140, AP M
                        "action": "Replace at 580 hours as the model shows", "action_owner": "Fleet engineer",
                        "action_due": "2026-11-20", "action_status": "done",
                        "failure_rate": 1.5e-4, "mode_ratio": 0.6, "loss_probability": 0.6, "severity_class": "II",
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
                        "cause": "As above", "effect_local": "As above", "effect_next": "As above",
                        "detection_method": "None (run to failure)",
                        "severity": 7, "occurrence": 5, "detection": 10,  # RPN 350, AP H
                        "action": "Retire the legacy plan; follow the fixed-interval decision",
                        "action_owner": "Fleet engineer", "action_due": "2026-11-14", "action_status": "open",
                        "failure_rate": 1.5e-4, "mode_ratio": 0.4, "loss_probability": 0.6, "severity_class": "II",
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
                        "cause": "Fatigue at the spring hanger weld",
                        "effect_local": "Crack at the weld toe", "effect_next": "Hanger separates under load",
                        "detection_method": "Visual check of the hanger welds",
                        "severity": 10, "occurrence": 2, "detection": 5,  # RPN 100, AP M
                        "action": "Reinforce the hanger; dye-penetrant check of the fleet",
                        "action_owner": "Engineering", "action_due": "2026-12-15", "action_status": "open",
                        "failure_rate": 1e-5, "mode_ratio": 1.0, "loss_probability": 1.0, "severity_class": "I",
                    },
                ],
            },
        ],
    },
]
# The truck's criticality figures are all over the same 1000 operating hours.
SAMPLE_TRUCK_BASIS = {"operating_time": 1000.0, "time_unit": "hours", "rate_source": "entered"}

_COPY_NAME = re.compile(r"^Delivery truck \(sample(?: (\d+))?\)$")


def _n(count: int, one: str) -> str:
    return f"{count} {one}" if count == 1 else f"{count} {one}s"


def sample_truck_functions() -> list[dict]:
    """The sample truck's RCM, a fresh copy each time (callers may change it)."""
    return copy.deepcopy(SAMPLE_TRUCK_FUNCTIONS)


def _copies(m, pattern: re.Pattern) -> list[dict]:
    """Copies of a sample in this workspace (live positions with its name)."""
    return sorted((p for p in m.s.nodes(m.org, "Position") if not p.get("retired") and pattern.match(p["name"])),
                  key=lambda p: p["name"])


def sample_trucks(m) -> list[dict]:
    """Copies of the sample truck in this workspace (live positions with its name)."""
    return _copies(m, _COPY_NAME)


def _copy_name(existing: list[dict], pattern: re.Pattern, base: str) -> str:
    """The sample's name, or the next free number when a copy is there ("… (sample 2)")."""
    taken = {int(match.group(1) or 1) for p in existing if (match := pattern.match(p["name"]))}
    if 1 not in taken:
        return base
    n = 2
    while n in taken:
        n += 1
    return base.replace("(sample)", f"(sample {n})")


def _scores(mode: dict, basis: dict) -> dict:
    """A template mode's FME(C)A fields, with the common basis (t, unit, source)."""
    return {**basis, **{k: mode[k] for k in fmea.FIELDS if k in mode}}


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
    position = m.create_position(_copy_name(existing, _COPY_NAME, SAMPLE_TRUCK_NAME),
                                 description=SAMPLE_TRUCK_DESCRIPTION)
    pid = position["id"]
    counts = {"functions": 0, "functional_failures": 0, "failure_modes": 0, "decisions": 0, "scored": 0}
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
                scores = _scores(mode, SAMPLE_TRUCK_BASIS)
                if scores:
                    m.score_failure_mode(fm["id"], scores)
                    counts["scored"] += 1
    counts["tasks"] = len(m._tasks_on(pid))
    return {
        "added": True,
        "position": {"id": pid, "name": position["name"]},
        **counts,
        "message": (f"Added “{position['name']}” to your tree: {_n(counts['functions'], 'function')}, "
                    f"{_n(counts['failure_modes'], 'failure mode')}, each with its decision and FME(C)A scores, and "
                    f"{_n(counts['tasks'], 'scheduled task')}. One decision shows as contradicted on purpose: "
                    "its own model shows wear-out."),
    }


# ---- the sample quadcopter UAV ----------------------------------------------------
# Entirely invented: no real product, company or partner. Modes with "ff": None
# sit directly under their function, with no functional failure yet.

SAMPLE_UAV_NAME = "Quadcopter UAV (sample)"
SAMPLE_UAV_DESCRIPTION = (
    "A sample: a small quadcopter's design FME(C)A on its functional tree, every failure mode scored (severity, "
    "occurrence, detection, action priority) with MIL-STD-1629A-style criticality figures. Three positions carry "
    "failure modes directly under a function with no functional failure yet, to show how an FMEA row reads back "
    "on the RCM tab."
)
SAMPLE_UAV_TREE = [
    ("Airframe", []), ("Propulsion", ["Motor", "Speed controller (ESC)", "Propeller"]),
    ("Power", ["Battery pack", "Battery management (BMS)"]),
    ("Flight control", ["Flight controller", "IMU", "GPS receiver"]),
    ("Comms link", []), ("Payload gimbal", []),
]
# The criticality figures are all over the same 100 flight hours.
SAMPLE_UAV_BASIS = {"operating_time": 100.0, "time_unit": "hours", "rate_source": "entered"}

# Position › function › modes. Each mode: text, ff (None = directly under the
# function), the FME(C)A fields, consequence (RCM) and decision (RCM, or None).
SAMPLE_UAV_MODES = [
    {"position": "Airframe", "function": "Carry the propulsion, power, control and payload modules through flight loads",
     "modes": [
         {"text": "Arm boom fatigue crack at the motor mount", "ff": "A structural member cracks or separates in flight",
          "cause": "Vibration from an unbalanced propeller", "effect_local": "Boom stiffness drops; the mount flexes",
          "effect_next": "Motor thrust axis tilts; attitude control saturates",
          "effects": "Loss of control and an uncontrolled descent.",
          "detection_method": "Pre-flight visual check of booms and mounts",
          "severity": 10, "occurrence": 3, "detection": 5,  # RPN 150, AP M
          "action": "Magnified inspection of the arm roots every 50 flight hours; increase the mount fillet radius",
          "action_owner": "Airframe lead", "action_due": "2026-12-15", "action_status": "open",
          "failure_rate": 2e-5, "mode_ratio": 0.6, "loss_probability": 1.0, "severity_class": "I",  # Cm 1.2e-3
          "consequence": "safety",
          "decision": {"outcome": "on_condition", "task": "Inspect the arm roots with a magnifier", "interval": 50,
                       "interval_unit": "hours"}},
         {"text": "Landing gear leg breaks on touchdown", "ff": "A structural member cracks or separates in flight",
          "cause": "Hard landing beyond the design load", "effect_local": "The leg fails",
          "effect_next": "The airframe tips over on the ground; propellers strike",
          "effects": "Payload damage on landing; no injury.", "detection_method": "Post-flight inspection",
          "severity": 5, "occurrence": 4, "detection": 2,  # RPN 40, AP L
          "action": "Add a crushable foot to the leg", "action_owner": "Airframe lead", "action_due": "2027-01-20",
          "action_status": "open",
          "failure_rate": 5e-5, "mode_ratio": 0.4, "loss_probability": 0.3, "severity_class": "III",  # Cm 6e-4
          "consequence": "operational", "decision": None},
     ]},
    {"position": "Motor", "function": "Turn the propeller at the commanded speed",
     "modes": [
         {"text": "Bearing seizure", "ff": "The motor stops or loses torque",
          "cause": "Bearing wear from dust ingress", "effect_local": "The motor stalls",
          "effect_next": "The speed controller cuts out on overcurrent; thrust lost on one arm",
          "effects": "A quadcopter cannot fly on three motors: uncontrolled descent.",
          "detection_method": "Motor current trend in the flight log; spin check before flight",
          "severity": 9, "occurrence": 4, "detection": 6,  # RPN 216, AP H
          "action": "Fit sealed bearings; spin check every 25 flight hours", "action_owner": "Propulsion lead",
          "action_due": "2026-11-30", "action_status": "open",
          "failure_rate": 8e-5, "mode_ratio": 0.5, "loss_probability": 1.0, "severity_class": "I",  # Cm 4e-3
          "consequence": "safety",
          "decision": {"outcome": "on_condition", "task": "Spin each motor by hand and listen for roughness",
                       "interval": 25, "interval_unit": "hours"}},
         {"text": "Winding insulation breaks down from overheating", "ff": "The motor stops or loses torque",
          "cause": "Sustained overload in hot weather", "effect_local": "A phase shorts",
          "effect_next": "Speed controller fault; thrust lost on one arm", "effects": "Uncontrolled descent.",
          "detection_method": "Motor temperature telemetry alarm",
          "severity": 9, "occurrence": 2, "detection": 4,  # RPN 72, AP L
          "action": "Derate hover power above 35 °C; add the temperature limit to the pre-flight check",
          "action_owner": "Propulsion lead", "action_due": "2026-12-01", "action_status": "in_progress",
          "failure_rate": 8e-5, "mode_ratio": 0.3, "loss_probability": 1.0, "severity_class": "I",  # Cm 2.4e-3
          "consequence": "safety", "decision": None},
     ]},
    {"position": "Speed controller (ESC)", "function": "Convert battery power into the three-phase drive the motor needs",
     "modes": [
         {"text": "Power transistor fails short", "ff": "No drive to the motor",
          "cause": "Voltage spike during regenerative braking", "effect_local": "The controller shuts down",
          "effect_next": "Thrust lost on one arm", "effects": "Uncontrolled descent.",
          "detection_method": "Self-test at arming reports a shorted phase",
          "severity": 9, "occurrence": 3, "detection": 7,  # RPN 189, AP H
          "action": "Add a bulk capacitor on the power rail; limit braking in firmware",
          "action_owner": "Electronics lead", "action_due": "2026-12-10", "action_status": "open",
          "failure_rate": 3e-5, "mode_ratio": 0.6, "loss_probability": 1.0, "severity_class": "I",  # Cm 1.8e-3
          "consequence": "safety",
          "decision": {"outcome": "redesign",
                       "notes": "No task catches a transistor short in flight: the fix is in the design."}},
         {"text": "Loses sync with the motor on a rapid throttle change", "ff": "No drive to the motor",
          "cause": "Timing mismatch with the motor at high load", "effect_local": "The motor stutters",
          "effect_next": "Momentary thrust loss; an attitude excursion", "effects": "A hard landing in gusty conditions.",
          "detection_method": "Flight log review for RPM dropouts after each flight",
          "severity": 7, "occurrence": 5, "detection": 4,  # RPN 140, AP M
          "action": "Tune the controller timing per motor batch; flag RPM dropouts in the log review",
          "action_owner": "Flight test", "action_due": "2026-11-20", "action_status": "done",
          "failure_rate": 1e-4, "mode_ratio": 0.4, "loss_probability": 0.2, "severity_class": "II",  # Cm 8e-4
          "consequence": "operational", "decision": None},
     ]},
    {"position": "Propeller", "function": "Produce thrust at the commanded speed",
     "modes": [
         {"text": "Blade chipped by a ground strike", "ff": "Thrust lower than commanded",
          "cause": "Debris on the take-off pad", "effect_local": "Imbalance and lost efficiency",
          "effect_next": "Vibration into the motor mount", "effects": "Shorter arm life and reduced flight time.",
          "detection_method": "Pre-flight blade check",
          "severity": 4, "occurrence": 6, "detection": 2,  # RPN 48, AP M
          "action": "Issue a blade go/no-go gauge; replace on any chip", "action_owner": "Operations",
          "action_due": "2026-11-15", "action_status": "done",
          "failure_rate": 2e-4, "mode_ratio": 0.7, "loss_probability": 0.1, "severity_class": "III",  # Cm 1.4e-3
          "consequence": "operational",
          "decision": {"outcome": "on_condition", "task": "Check each blade against the go/no-go gauge",
                       "interval": 1, "interval_unit": "days"}},
         {"text": "Propeller nut loosens", "ff": "Thrust lower than commanded",
          "cause": "No thread locker after a blade change", "effect_local": "The propeller spins free",
          "effect_next": "Thrust lost on one arm", "effects": "Uncontrolled descent.",
          "detection_method": "Torque-stripe check before flight",
          "severity": 10, "occurrence": 2, "detection": 3,  # RPN 60, AP L
          "action": "Captive nut with a locking feature; torque stripe on every nut", "action_owner": "Propulsion lead",
          "action_due": "2026-12-05", "action_status": "open",
          "failure_rate": 2e-4, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",  # Cm 2e-3
          "consequence": "safety", "decision": None},
     ]},
    {"position": "Battery pack", "function": "Supply 22.2 V at up to 60 A for the planned flight time",
     "modes": [
         {"text": "Cell capacity fade", "ff": "Voltage drops below the flight-critical limit",
          "cause": "Ageing and deep discharge cycles", "effect_local": "The pack runs down early",
          "effect_next": "Low-voltage warning; return-to-home triggered",
          "effects": "Mission cut short; a controlled landing.",
          "detection_method": "Capacity logged on every charge; retire at 80 %",
          "severity": 4, "occurrence": 7, "detection": 2,  # RPN 56, AP M
          "action": "Retire packs at 80 % of rated capacity", "action_owner": "Operations",
          "action_due": "2026-11-10", "action_status": "done",
          "failure_rate": 3e-4, "mode_ratio": 0.6, "loss_probability": 0.05, "severity_class": "III",  # Cm 9e-4
          "consequence": "operational",
          "decision": {"outcome": "on_condition", "task": "Log the charged capacity and retire the pack at 80 %",
                       "interval": 1, "interval_unit": "days"}},
         {"text": "Internal cell short (thermal runaway)", "ff": "Voltage drops below the flight-critical limit",
          "cause": "Puncture or over-discharge", "effect_local": "The pack overheats",
          "effect_next": "Power lost; fire risk", "effects": "Uncontrolled descent and a fire on the ground.",
          "detection_method": "Cell-temperature alarm from the BMS (only once it is hot)",
          "severity": 10, "occurrence": 2, "detection": 8,  # RPN 160, AP H
          "action": "Puncture-resistant case; store at 50 % charge; charge in a fire-resistant bag",
          "action_owner": "Safety lead", "action_due": "2026-11-25", "action_status": "in_progress",
          "failure_rate": 3e-4, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",  # Cm 3e-3
          "consequence": "safety", "decision": None},
     ]},
    {"position": "Battery management (BMS)", "function": "Balance the cells and cut off outside the safe window",
     "modes": [
         {"text": "Cut-off relay welded closed", "ff": "Does not cut off when a cell is outside its limits",
          "cause": "Inrush current when the pack is connected", "effect_local": "No protection",
          "effect_next": "A cell can be over-discharged unnoticed",
          "effects": "Pack damage, and a possible fire while charging.",
          "detection_method": "None in normal use (hidden); a monthly cut-off function test",
          "severity": 8, "occurrence": 2, "detection": 9,  # RPN 144, AP M
          "action": "Monthly BMS function test; pre-charge resistor on the connector",
          "action_owner": "Electronics lead", "action_due": "2026-12-20", "action_status": "open",
          "failure_rate": 1e-5, "mode_ratio": 0.5, "loss_probability": 0.5, "severity_class": "II",  # Cm 2.5e-4
          "consequence": "hidden",
          "decision": {"outcome": "failure_finding", "task": "Test the BMS cut-off with a bench supply",
                       "interval": 1, "interval_unit": "months"}},
     ]},
    {"position": "Flight controller", "function": "Hold the commanded attitude and position",
     "modes": [
         {"text": "Firmware lock-up (watchdog reset in flight)", "ff": "Loses attitude control",
          "cause": "A software fault under a high logging load",
          "effect_local": "The control loop stops for about a second", "effect_next": "Attitude diverges",
          "effects": "Uncontrolled descent.", "detection_method": "Log review for watchdog events",
          "severity": 10, "occurrence": 2, "detection": 6,  # RPN 120, AP M
          "action": "Reduce the log rate; add watchdog events to the post-flight checklist",
          "action_owner": "Software lead", "action_due": "2026-11-18", "action_status": "in_progress",
          "failure_rate": 1e-5, "mode_ratio": 0.5, "loss_probability": 0.9, "severity_class": "I",  # Cm 4.5e-4
          "consequence": "safety",
          "decision": {"outcome": "redesign", "notes": "A software change; no maintenance task helps."}},
     ]},
    {"position": "IMU", "function": "Measure angular rate and acceleration",
     "modes": [
         {"text": "Gyro bias drifts with temperature", "ff": "Readings drift or freeze",
          "cause": "No temperature compensation after a sensor change",
          "effect_local": "The attitude estimate drifts", "effect_next": "The controller fights a false tilt",
          "effects": "Oscillation and a hard landing.", "detection_method": "Gyro calibration check before flight",
          "severity": 7, "occurrence": 4, "detection": 3,  # RPN 84, AP M
          "action": "Temperature calibration in the production test", "action_owner": "Production",
          "action_due": "2026-12-12", "action_status": "open",
          "failure_rate": 4e-5, "mode_ratio": 0.6, "loss_probability": 0.3, "severity_class": "II",  # Cm 7.2e-4
          "consequence": "operational", "decision": None},
     ]},
    # Three positions with modes DIRECTLY under the function (no functional failure
    # yet): the way an FMEA worksheet reads, and what the RCM tab shows as "No
    # functional failure yet".
    {"position": "GPS receiver", "function": "Give position to within 2 m",
     "modes": [
         {"text": "Antenna connector works loose", "ff": None,
          "cause": "Vibration", "effect_local": "The position fix is lost",
          "effect_next": "Position hold fails; the aircraft drifts in wind", "effects": "Fly-away risk; a geofence breach.",
          "detection_method": "Satellite count in the pre-flight check",
          "severity": 8, "occurrence": 3, "detection": 2,  # RPN 48, AP L
          "action": "Locking connector; satellite count on the pre-flight checklist", "action_owner": "Production",
          "action_due": "2026-11-12", "action_status": "done",
          "failure_rate": 5e-5, "mode_ratio": 0.5, "loss_probability": 0.4, "severity_class": "II",  # Cm 1e-3
          "consequence": "operational", "decision": None},
     ]},
    {"position": "Comms link", "function": "Carry control and telemetry to 2 km",
     "modes": [
         {"text": "Link lost beyond range or behind terrain", "ff": None,
          "cause": "Flying beyond line of sight", "effect_local": "No control input",
          "effect_next": "Failsafe return-to-home",
          "effects": "Mission aborted; a safe landing if return-to-home works.",
          "detection_method": "Signal strength shown on the ground station",
          "severity": 6, "occurrence": 5, "detection": 2,  # RPN 60, AP L
          "action": "Geofence on signal strength; pilot training", "action_owner": "Operations",
          "action_due": "2026-11-08", "action_status": "done",
          "failure_rate": 2e-4, "mode_ratio": 0.8, "loss_probability": 0.1, "severity_class": "III",  # Cm 1.6e-3
          "consequence": "operational", "decision": None},
     ]},
    {"position": "Payload gimbal", "function": "Hold the camera steady on the target",
     "modes": [
         {"text": "Gimbal motor stalls on a snagged cable", "ff": None,
          "cause": "Cable routing without a service loop", "effect_local": "The gimbal locks",
          "effect_next": "Footage unusable", "effects": "The mission is flown again.",
          "detection_method": "Gimbal sweep before flight",
          "severity": 3, "occurrence": 4, "detection": 2,  # RPN 24, AP L
          "action": "Re-route the cable with a service loop", "action_owner": "Payload",
          "action_due": "2026-11-05", "action_status": "done",
          "failure_rate": 1e-4, "mode_ratio": 0.7, "loss_probability": 0.02, "severity_class": "IV",  # Cm 1.4e-4
          "consequence": "non_operational", "decision": None},
     ]},
]

_UAV_COPY_NAME = re.compile(r"^Quadcopter UAV \(sample(?: (\d+))?\)$")


def sample_uav_modes() -> list[dict]:
    """The sample UAV's modes, a fresh copy each time (callers may change it)."""
    return copy.deepcopy(SAMPLE_UAV_MODES)


def sample_uavs(m) -> list[dict]:
    """Copies of the sample UAV in this workspace (live positions with its name)."""
    return _copies(m, _UAV_COPY_NAME)


def _add_uav_modes(m, at_of: dict[str, list[str]], counts: dict) -> None:
    """The sample UAV's failure modes, each scored, with its RCM consequence and
    decision, on every position the template's position name maps to (at_of: name ->
    position ids; the sample product has four motors where the FME(C)A sample has one)."""
    for entry in sample_uav_modes():
        for at in at_of[entry["position"]]:
            function = m.add_function(at, entry["function"])
            counts["functions"] += 1
            ffs: dict[str, str] = {}
            for mode in entry["modes"]:
                if mode["ff"]:
                    if mode["ff"] not in ffs:
                        ffs[mode["ff"]] = m.add_functional_failure(function["id"], mode["ff"])["id"]
                        counts["functional_failures"] += 1
                    fm = m.add_failure_mode(at, mode["text"], functional_failure_id=ffs[mode["ff"]])
                else:
                    fm = m.add_failure_mode(at, mode["text"], function_id=function["id"])
                    counts["direct"] += 1
                counts["failure_modes"] += 1
                if mode.get("effects"):
                    m.update_failure_mode(fm["id"], effects=mode["effects"])
                m.score_failure_mode(fm["id"], _scores(mode, SAMPLE_UAV_BASIS))
                counts["scored"] += 1
                m.decide_failure_mode(fm["id"], consequence=mode.get("consequence"),
                                      decision=mode["decision"] if mode.get("decision") else ...)
                counts["decisions"] += bool(mode.get("decision"))


def add_sample_uav(m, again: bool = False) -> dict:
    """Copy the sample quadcopter UAV into ``m``'s workspace: its tree, every
    failure mode scored as an FME(C)A, with its RCM consequence and (where
    there is one) decision. Three functions carry their modes directly, with
    no functional failure yet. Once only, unless ``again``."""
    existing = sample_uavs(m)
    if existing and not again:
        have = existing[0]
        return {
            "added": False,
            "position": {"id": have["id"], "name": have["name"]},
            "message": f"The sample UAV is already in your tree as “{have['name']}”. "
                       "Ask again to add another copy.",
        }
    root = m.create_position(_copy_name(existing, _UAV_COPY_NAME, SAMPLE_UAV_NAME), description=SAMPLE_UAV_DESCRIPTION)
    pid = root["id"]
    by_name: dict[str, str] = {}
    counts = {"positions": 1, "functions": 0, "functional_failures": 0, "failure_modes": 0, "scored": 0,
              "direct": 0, "decisions": 0}
    for name, children in SAMPLE_UAV_TREE:
        parent = m.create_position(name, parent_id=pid)
        by_name[name] = parent["id"]
        counts["positions"] += 1
        for child in children:
            by_name[child] = m.create_position(child, parent_id=parent["id"])["id"]
            counts["positions"] += 1
    _add_uav_modes(m, {name: [at] for name, at in by_name.items()}, counts)
    return {
        "added": True,
        "position": {"id": pid, "name": root["name"]},
        **counts,
        "message": (f"Added “{root['name']}” to your tree: {_n(counts['positions'], 'position')}, "
                    f"{_n(counts['functions'], 'function')} and {_n(counts['failure_modes'], 'failure mode')}, every "
                    f"one scored as an FME(C)A; {counts['direct']} of them sit directly under a function with no "
                    "functional failure yet, so the RCM tab shows what's left to finish."),
    }


# ---- the sample product: a quadcopter design and three items built from it ---------
# Entirely invented: no real product, company or partner. The design reuses the
# FME(C)A sample's failure modes on every position they belong to (four motors,
# four speed controllers, four propellers, two IMUs), so its FME(C)A tab is full.

SAMPLE_PRODUCT_NAME = "Survey quadcopter (sample)"
SAMPLE_PRODUCT_PART = "SQ-4"
SAMPLE_PRODUCT_REV = "C"
SAMPLE_PRODUCT_DESCRIPTION = (
    "A sample product: a small survey quadcopter's design (its functional structure, with every failure mode "
    "scored as an FME(C)A), its part with a small bill of materials, three items built from it, a replaced motor "
    "and two failure reports. Entirely invented."
)
_PRODUCT_COPY_NAME = re.compile(r"^Survey quadcopter \(sample(?: (\d+))?\)$")

ARMS = 4
# The design tree: (name, position class, children); the classes pool like positions' life data.
SAMPLE_PRODUCT_TREE: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("Airframe", "", []),
    ("Propulsion", "", [(f"Motor {i}", "Brushless motor") for i in range(1, ARMS + 1)]
     + [(f"ESC {i}", "Speed controller (ESC)") for i in range(1, ARMS + 1)]
     + [(f"Propeller {i}", "Propeller") for i in range(1, ARMS + 1)]),
    ("Flight control", "", [("Flight controller", "Flight controller"), ("IMU 1", "IMU"), ("IMU 2", "IMU"),
                            ("GPS", "GPS module")]),
    ("Power", "", [("Battery pack", "Battery pack"), ("BMS", "Battery management (BMS)")]),
    ("Comms", "", []),
    ("Payload gimbal", "", []),
]
# Where each of the FME(C)A sample's positions sits in the product's design.
SAMPLE_PRODUCT_MODES_AT = {
    "Airframe": ["Airframe"], "Motor": [f"Motor {i}" for i in range(1, ARMS + 1)],
    "Speed controller (ESC)": [f"ESC {i}" for i in range(1, ARMS + 1)],
    "Propeller": [f"Propeller {i}" for i in range(1, ARMS + 1)],
    "Battery pack": ["Battery pack"], "Battery management (BMS)": ["BMS"], "Flight controller": ["Flight controller"],
    "IMU": ["IMU 1", "IMU 2"], "GPS receiver": ["GPS"], "Comms link": ["Comms"], "Payload gimbal": ["Payload gimbal"],
}
# The bill of materials: (part number, name, quantity in one quadcopter, indenture level).
SAMPLE_PRODUCT_BOM = [
    ("SQ-AF", "Airframe kit, carbon arms", 1, "Assembly"),
    ("SQ-M2210", "Brushless motor 2210", ARMS, "LRU"),
    ("SQ-ESC30", "Speed controller 30 A", ARMS, "LRU"),
    ("SQ-P1045", "Propeller 10x4.5", ARMS, "LRU"),
    ("SQ-FC7", "Flight controller", 1, "LRU"),
    ("SQ-IMU9", "Inertial measurement unit", 2, "LRU"),
    ("SQ-GPS8", "GPS module", 1, "LRU"),
    ("SQ-BP6S", "Battery pack 6S 10 Ah", 1, "LRU"),
    ("SQ-BMS6", "Battery management board", 1, "SRU"),
    ("SQ-RL24", "Telemetry radio 2.4 GHz", 1, "LRU"),
    ("SQ-GB2", "Camera gimbal, 2 axis", 1, "LRU"),
]
# The items built: serial, revision, flight hours read now.
SAMPLE_PRODUCT_ITEMS = [("0007", "C", 212.0), ("0008", "C", 31.0), ("0009", "B", 640.0)]
# The flight-critical RBD's blocks: a guessed constant failure rate per flight hour each
# (placeholder=true on every block: no real data).
SAMPLE_RBD_RATES = {"Battery pack": 1e-4, "BMS": 5e-5, "Flight controller": 2e-5, "IMU": 1e-4, "GPS": 5e-5,
                    "ESC": 3e-5, "Motor": 4e-5, "Propeller": 2e-5}


def sample_products(m) -> list[dict]:
    """Copies of the sample product in this workspace (live product designs with its name)."""
    return [p for p in _copies(m, _PRODUCT_COPY_NAME) if p.get("design")]


def _part(m, number: str, name: str) -> dict:
    """The catalogue part with this number, made when there's none (a second copy of the
    sample shares the component parts)."""
    found = next((pt for pt in m.s.nodes(m.org, "Part") if pt["part_number"].lower() == number.lower()), None)
    return found or m.create_part(number, name)


def _free_number(m, base: str) -> str:
    taken = {pt["part_number"].lower() for pt in m.s.nodes(m.org, "Part")}
    if base.lower() not in taken:
        return base
    n = 2
    while f"{base}-{n}".lower() in taken:
        n += 1
    return f"{base}-{n}"


def sample_rbd_graph() -> dict:
    """The quadcopter's flight-critical RBD (compact form, hours): power, then flight
    control with its two IMUs as 1-of-2 redundancy, then the GPS, then the four arms
    in series (a quadcopter can't fly on three). Each arm is its ESC, motor and
    propeller in series: the design has one ESC per motor, so no ESC redundancy is drawn.
    Every block's failure rate is a placeholder."""
    def block(bid: str, label: str, rate_of: str) -> dict:
        return {"id": bid, "type": "component", "label": label,
                "model": {"distribution_id": "exponential",
                          "params": [{"name": "failure_rate", "value": SAMPLE_RBD_RATES[rate_of]}],
                          "placeholder": True}}

    nodes = [{"id": "in", "type": "input"}, {"id": "out", "type": "output"},
             block("bp", "Battery pack", "Battery pack"), block("bms", "BMS", "BMS"),
             block("fc", "Flight controller", "Flight controller"),
             block("imu1", "IMU 1", "IMU"), block("imu2", "IMU 2", "IMU"),
             {"id": "imus", "type": "knode", "label": "IMUs (1 of 2)", "n": 1, "k": 2},
             block("gps", "GPS", "GPS")]
    edges = [("in", "bp"), ("bp", "bms"), ("bms", "fc"), ("fc", "imu1"), ("fc", "imu2"), ("imu1", "imus"),
             ("imu2", "imus"), ("imus", "gps")]
    last = "gps"
    for i in range(1, ARMS + 1):
        for kind, label in (("esc", "ESC"), ("m", "Motor"), ("p", "Propeller")):
            nodes.append(block(f"{kind}{i}", f"{label} {i}", label))
            edges.append((last, f"{kind}{i}"))
            last = f"{kind}{i}"
    edges.append((last, "out"))
    return {"nodes": nodes, "unit": "hours", "edges": [{"source": a, "target": b} for a, b in edges]}


def _save_sample_rbd(m, db, name: str) -> dict:
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import normalize_graph

    rbd = rbds_service.save_rbd(db, name, normalize_graph(sample_rbd_graph()), m.org)
    return {"id": rbd.id, "name": rbd.name}


def add_sample_product(m, db, again: bool = False) -> dict:
    """Add the sample product to ``m``'s workspace: a quadcopter's design tree with the
    FME(C)A sample's failure modes scored on it, its part with a small bill of materials,
    three items built from it (each with a flight-hours counter), a replaced motor on one,
    two failure reports, and a flight-critical RBD in the RBDs (placeholder failure rates,
    said so in its name). Once only, unless ``again``."""
    existing = sample_products(m)
    if existing and not again:
        have = existing[0]
        return {
            "added": False,
            "product": {"id": have["id"], "name": have["name"]},
            "position": {"id": have["id"], "name": have["name"]},
            "message": f"The sample product is already in your workspace as “{have['name']}”. "
                       "Ask again to add another copy.",
        }
    name = _copy_name(_copies(m, _PRODUCT_COPY_NAME), _PRODUCT_COPY_NAME, SAMPLE_PRODUCT_NAME)
    product = m.create_product(name, _free_number(m, SAMPLE_PRODUCT_PART), SAMPLE_PRODUCT_REV,
                               SAMPLE_PRODUCT_DESCRIPTION)
    pid = product["id"]
    top_part = product["part"]["id"]
    levels = set(m.part_levels())
    for number, part_name, qty, level in SAMPLE_PRODUCT_BOM:
        part = _part(m, number, part_name)
        if level in levels and not part.get("level"):
            m.set_part_level(part["id"], level)
        m.add_component(top_part, part["id"], quantity=qty)
    if "System" in levels:
        m.set_part_level(top_part, "System")

    at: dict[str, str] = {}
    counts = {"positions": 1, "functions": 0, "functional_failures": 0, "failure_modes": 0, "scored": 0,
              "direct": 0, "decisions": 0}
    for group, cls, children in SAMPLE_PRODUCT_TREE:
        at[group] = m.create_position(group, parent_id=pid, position_class=cls)["id"]
        counts["positions"] += 1
        for child, child_cls in children:
            at[child] = m.create_position(child, parent_id=at[group], position_class=child_cls)["id"]
            counts["positions"] += 1
    _add_uav_modes(m, {k: [at[n] for n in names] for k, names in SAMPLE_PRODUCT_MODES_AT.items()}, counts)

    today = date.fromisoformat(m.today())

    def ago(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()

    motor = next(pt for pt in m.s.nodes(m.org, "Part") if pt["part_number"] == "SQ-M2210")
    gps = next(pt for pt in m.s.nodes(m.org, "Part") if pt["part_number"] == "SQ-GPS8")
    items = []
    for serial, rev, hours in SAMPLE_PRODUCT_ITEMS:
        built = m.build_item(pid, serial, rev=rev, dry_run=False)
        tree = {row["path"].split(" › ")[-1]: row["id"] for row in built["positions"]}
        point = m.add_point(None, "Flight hours", kind="counter", unit="hours", item_id=built["item"]["id"])
        m.record_reading(point["id"], hours)
        items.append({"serial": serial, "rev": rev, "item_id": built["item"]["id"],
                      "top_position_id": built["top_position_id"], "positions": tree})
    # 0007: the four motors as fitted, Motor 1's first one replaced after a bearing seized.
    first = items[0]
    m.add_past_fitment(first["positions"]["Motor 1"], ago(300), ago(120), reason="failure",
                       failure_mode_text="Bearing seizure",
                       new_item={"name": "Brushless motor 2210", "serial": "M-0007a", "part_number": "SQ-M2210"})
    for i in range(1, ARMS + 1):
        m.fit(first["positions"][f"Motor {i}"], on=ago(120 if i == 1 else 300),
              new_item={"name": "Brushless motor 2210", "serial": f"M-0007{'b' if i == 1 else chr(ord('a') + i)}",
                        "part_id": motor["id"]})
    m.fit(items[2]["positions"]["GPS"], on=ago(400),
          new_item={"name": "GPS module", "serial": "G-0009", "part_id": gps["id"]})
    reports = [
        m.file_failure_report(first["positions"]["Motor 1"], "Motor 1 seized in hover",
                              "Motor current rose for two flights, then the motor stopped; the aircraft landed on "
                              "its failsafe.", occurred_on=ago(120), found_by="Pilot", consequence="safety",
                              failure_mode_text="Bearing seizure"),
        m.file_failure_report(items[2]["positions"]["GPS"], "GPS lost its fix during a survey",
                              "Position hold dropped out twice in one flight; the connector was loose.",
                              occurred_on=ago(9), found_by="Pilot", consequence="operational",
                              failure_mode_text="Antenna connector works loose"),
    ]
    m.set_failure_report_status(reports[0]["id"], "investigating", note="Bearing sent for teardown.")
    rbd = _save_sample_rbd(m, db, f"{name}: flight-critical RBD (placeholder failure rates)")
    return {
        "added": True,
        "product": {"id": pid, "name": name},
        "position": {"id": pid, "name": name},
        "items": [{k: it[k] for k in ("serial", "rev", "item_id", "top_position_id")} for it in items],
        "reports": [{"id": r["id"], "label": r.get("label") or r["title"]} for r in reports],
        "rbd": rbd,
        **counts,
        "message": (f"Added “{name}”: a design of {_n(counts['positions'], 'position')} with "
                    f"{_n(counts['failure_modes'], 'failure mode')} scored as an FME(C)A, its part with a bill of "
                    f"materials, {_n(len(items), 'item')} built from it (serials "
                    f"{', '.join(it['serial'] for it in items)}), a replaced motor and two failure reports. "
                    f"The RBD “{rbd['name']}” is in your RBDs: its failure rates are placeholders, not data. "
                    "Each arm's ESC, "
                    "motor and propeller are in series there: the design has one ESC per motor."),
    }
