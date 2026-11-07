"""Templates: ready-made samples a workspace can copy in.

The sample product, "Survey quadcopter (sample)": the one sample for the RCM
and FME(C)A tabs, on Products (a design, not an operated asset in the tree).
Its design tree (airframe, propulsion, power, flight control, comms, payload)
carries an RCM on every position: functions (with performance standards where
the function has a measurable limit), their functional failures, the failure
modes, each with its consequence and decision, and each mode scored as a design
FME(C)A reads. The product's and its groups' functional failures are explained
by those on the positions inside them (linked causes). Some decisions link to the evidence behind them, saved analyses
and a model every account can read, so the evidence check shows each case: the
BMS failure-finding test and the propeller replacement are supported; the
legacy run-to-failure plan on the motor bearings is contradicted on purpose
(the bearing life model shows wear-out); the battery retirement can't be
checked yet (its task counts charge cycles, its analysis flight hours). Two
modes still need a decision, on purpose, and three are hidden failures. It
comes with a part and bill of materials, three items built from it, failure
reports and a flight-critical RBD. Entirely invented: no real product.
(Earlier samples, "Delivery truck (sample)" and the asset-tree "Quadcopter UAV
(sample)", are no longer offered; copies already in a workspace stay as they
are.)

A copy is made through the ordinary service methods, so it is events like
any change a person makes, in the caller's own workspace only. Nothing is
seeded for anyone who never asks.
"""

from __future__ import annotations

import copy
import re
from datetime import date, timedelta

from backend.maintenance import fmea


def _n(count: int, one: str) -> str:
    return f"{count} {one}" if count == 1 else f"{count} {one}s"


def _copies(m, pattern: re.Pattern) -> list[dict]:
    """Copies of a sample in this workspace (live positions with its name)."""
    return sorted((p for p in m.s.nodes(m.org, "Position") if not p.get("retired") and pattern.match(p["name"])),
                  key=lambda p: p["name"])


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


# ---- the sample quadcopter's RCM and FME(C)A --------------------------------------
# Entirely invented: no real product, company or partner. The sample product
# ("Survey quadcopter (sample)", below) puts these on its design: the one sample
# for the RCM and FME(C)A tabs, on Products, not in the asset tree.

# The criticality figures are all over the same 100 flight hours.
SAMPLE_UAV_BASIS = {"operating_time": 100.0, "time_unit": "hours", "rate_source": "entered"}

# The evidence some decisions link: shared samples every account can read
# (backend/services/samples.py). The bearing life model shows wear-out, so the
# motors' legacy run-to-failure decision is contradicted on purpose; the battery's
# retirement analysis is in flight hours while its task counts charge cycles, so
# that check is inconclusive until the units agree.
UAV_BEARING_MODEL = "sample-model-bearings-weibull"
UAV_PROPELLER_ANALYSIS = "sample-strategy-quad-propeller-replacement"
UAV_BATTERY_ANALYSIS = "sample-strategy-quad-battery-retirement"
UAV_BMS_ANALYSIS = "sample-strategy-quad-bms-failure-finding"

# Position › function (with its performance standards, if any) › modes. Each mode:
# text, ff (its functional failure), the FME(C)A fields, consequence and decision
# (RCM; None = still to decide, on purpose, with notes saying why). "breaches" maps a
# functional failure to the standard (by its text) it breaches; any other breaches
# the whole function, as a total loss does.
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
          "consequence": "operational", "decision": None,
          "notes": "Still to decide, on purpose: the decision waits on the crushable-foot trial."},
     ]},
    {"position": "Motor", "function": "Turn the propeller at the commanded speed",
     "modes": [
         {"text": "Bearing seizure", "ff": "The motor stops or loses torque",
          "cause": "Bearing wear from dust ingress", "effect_local": "The motor stalls",
          "effect_next": "The speed controller cuts out on overcurrent; thrust lost on one arm",
          "effects": "A quadcopter cannot fly on three motors: uncontrolled descent.",
          "detection_method": "Motor current trend in the flight log; spin check before flight",
          "severity": 9, "occurrence": 4, "detection": 6,  # RPN 216, AP H
          "action": "Retire the legacy run-to-failure plan: spin check every 25 flight hours; fit sealed bearings",
          "action_owner": "Propulsion lead", "action_due": "2026-11-30", "action_status": "open",
          "failure_rate": 8e-5, "mode_ratio": 0.5, "loss_probability": 1.0, "severity_class": "I",  # Cm 4e-3
          "consequence": "safety",
          "decision": {"outcome": "rtf", "rtf_basis": "random",
                       "notes": "Legacy decision from the first build's plan, kept to show the evidence check: the "
                                "bearing life model shows wear-out, so running to failure isn't justified.",
                       "evidence": {"type": "model", "id": UAV_BEARING_MODEL}}},
         {"text": "Winding insulation breaks down from overheating", "ff": "The motor stops or loses torque",
          "cause": "Sustained overload in hot weather", "effect_local": "A phase shorts",
          "effect_next": "Speed controller fault; thrust lost on one arm", "effects": "Uncontrolled descent.",
          "detection_method": "Motor temperature telemetry alarm",
          "severity": 9, "occurrence": 2, "detection": 4,  # RPN 72, AP L
          "action": "Derate hover power above 35 °C; add the temperature limit to the pre-flight check",
          "action_owner": "Propulsion lead", "action_due": "2026-12-01", "action_status": "in_progress",
          "failure_rate": 8e-5, "mode_ratio": 0.3, "loss_probability": 1.0, "severity_class": "I",  # Cm 2.4e-3
          "consequence": "safety",
          "decision": {"outcome": "on_condition", "task": "Review the motor temperature trend in the flight log",
                       "interval": 10, "interval_unit": "hours"}},
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
          "consequence": "operational",
          "decision": {"outcome": "on_condition", "task": "Review the flight log for RPM dropouts", "interval": 10,
                       "interval_unit": "hours"}},
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
          "failure_rate": 2e-4, "mode_ratio": 0.6, "loss_probability": 0.1, "severity_class": "III",  # Cm 1.2e-3
          "consequence": "operational",
          "decision": {"outcome": "on_condition", "task": "Check each blade against the go/no-go gauge",
                       "interval": 1, "interval_unit": "days"}},
         {"text": "Propeller nut loosens", "ff": "Thrust lost on one arm",
          "cause": "No thread locker after a blade change", "effect_local": "The propeller spins free",
          "effect_next": "Thrust lost on one arm", "effects": "Uncontrolled descent.",
          "detection_method": "Torque-stripe check before flight",
          "severity": 10, "occurrence": 2, "detection": 3,  # RPN 60, AP L
          "action": "Captive nut with a locking feature; torque stripe on every nut", "action_owner": "Propulsion lead",
          "action_due": "2026-12-05", "action_status": "open",
          "failure_rate": 2e-4, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",  # Cm 2e-3
          "consequence": "safety",
          "decision": {"outcome": "on_condition", "task": "Check the torque stripe on every propeller nut",
                       "interval": 1, "interval_unit": "days"}},
         {"text": "Blade fatigue crack at the hub", "ff": "Thrust lost on one arm",
          "cause": "Cyclic bending in flight", "effect_local": "A crack grows from the hub",
          "effect_next": "The blade separates; thrust lost on one arm", "effects": "Uncontrolled descent.",
          "detection_method": "None reliable before the crack shows",
          "severity": 10, "occurrence": 3, "detection": 7,  # RPN 210, AP H
          "action": "Replace the propellers every 130 flight hours, as the replacement analysis shows",
          "action_owner": "Propulsion lead", "action_due": "2026-11-28", "action_status": "done",
          "failure_rate": 2e-4, "mode_ratio": 0.3, "loss_probability": 1.0, "severity_class": "I",  # Cm 6e-3
          "consequence": "safety",
          "decision": {"outcome": "fixed_interval", "task": "Replace the propeller", "interval": 130,
                       "interval_unit": "hours", "evidence": {"type": "strategy_analysis", "id": UAV_PROPELLER_ANALYSIS}}},
     ]},
    {"position": "Battery pack", "function": "Supply power for the planned flight",
     "standards": [
         {"text": "At least 25 minutes' flight on a full charge", "parameter": "Flight time", "comparator": ">=",
          "value": 25, "unit": "min"},
     ],
     "breaches": {"Flight time on a full charge under 25 minutes": "At least 25 minutes' flight on a full charge"},
     "modes": [
         {"text": "Cell capacity fade", "ff": "Flight time on a full charge under 25 minutes",
          "cause": "Ageing and deep discharge cycles", "effect_local": "The pack runs down early",
          "effect_next": "Low-voltage warning; return-to-home triggered",
          "effects": "Mission cut short; a controlled landing.",
          "detection_method": "Capacity logged on every charge",
          "severity": 4, "occurrence": 7, "detection": 2,  # RPN 56, AP M
          "action": "Retire packs at 300 charge cycles; redo the retirement analysis in cycles",
          "action_owner": "Operations", "action_due": "2026-11-10", "action_status": "open",
          "failure_rate": 3e-4, "mode_ratio": 0.6, "loss_probability": 0.05, "severity_class": "III",  # Cm 9e-4
          "consequence": "operational",
          "decision": {"outcome": "fixed_interval", "task": "Retire the battery pack", "interval": 300,
                       "interval_unit": "cycles",
                       "notes": "The task counts charge cycles but the analysis behind it is in flight hours, so the "
                                "evidence check can't compare them until the units agree.",
                       "evidence": {"type": "strategy_analysis", "id": UAV_BATTERY_ANALYSIS}}},
         {"text": "Internal cell short (thermal runaway)", "ff": "Power lost in flight",
          "cause": "Puncture or over-discharge", "effect_local": "The pack overheats",
          "effect_next": "Power lost; fire risk", "effects": "Uncontrolled descent and a fire on the ground.",
          "detection_method": "Cell-temperature alarm from the BMS (only once it is hot)",
          "severity": 10, "occurrence": 2, "detection": 8,  # RPN 160, AP H
          "action": "Puncture-resistant case; store at 50 % charge; charge in a fire-resistant bag",
          "action_owner": "Safety lead", "action_due": "2026-11-25", "action_status": "in_progress",
          "failure_rate": 3e-4, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",  # Cm 3e-3
          "consequence": "safety", "decision": None,
          "notes": "Still to decide, on purpose: the decision waits on the case redesign and the charging trial."},
     ]},
    {"position": "Battery management (BMS)", "function": "Balance the cells and cut off outside the safe window",
     "standards": [
         {"text": "Cut off when any cell is below 3.0 V or above 4.25 V", "parameter": "Cell voltage",
          "comparator": "between", "value": "3.0-4.25", "unit": "V"},
     ],
     "breaches": {"Does not cut off when a cell is outside its limits":
                  "Cut off when any cell is below 3.0 V or above 4.25 V"},
     "modes": [
         {"text": "Cut-off relay welded closed", "ff": "Does not cut off when a cell is outside its limits",
          "cause": "Inrush current when the pack is connected", "effect_local": "No protection",
          "effect_next": "A cell can be over-discharged unnoticed",
          "effects": "Pack damage, and a possible fire while charging.",
          "detection_method": "None in normal use (hidden); a cut-off function test",
          "severity": 8, "occurrence": 2, "detection": 9,  # RPN 144, AP M
          "action": "Function test of the BMS cut-off every 160 flight hours; pre-charge resistor on the connector",
          "action_owner": "Electronics lead", "action_due": "2026-12-20", "action_status": "open",
          "failure_rate": 5e-5, "mode_ratio": 0.5, "loss_probability": 0.5, "severity_class": "II",  # Cm 1.25e-3
          "consequence": "hidden",
          "decision": {"outcome": "failure_finding", "task": "Test the BMS cut-off with a bench supply",
                       "interval": 160, "interval_unit": "hours",
                       "evidence": {"type": "strategy_analysis", "id": UAV_BMS_ANALYSIS}}},
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
          "consequence": "operational",
          "decision": {"outcome": "on_condition", "task": "Check the gyro calibration", "interval": 1,
                       "interval_unit": "days"}},
         {"text": "Fails silently while the other IMU carries on", "ff": "No usable reading",
          "cause": "A solder joint cracks from vibration", "effect_local": "This IMU's readings stop",
          "effect_next": "The flight controller uses the other IMU; nothing tells the pilot",
          "effects": "No backup left: the next IMU failure loses attitude control.",
          "detection_method": "None in flight (hidden); the arming self-test compares both IMUs",
          "severity": 8, "occurrence": 3, "detection": 8,  # RPN 192, AP M
          "action": "Show an IMU disagreement in the arming checks", "action_owner": "Software lead",
          "action_due": "2026-12-12", "action_status": "open",
          "failure_rate": 4e-5, "mode_ratio": 0.4, "loss_probability": 0.5, "severity_class": "II",  # Cm 8e-4
          "consequence": "hidden",
          "decision": {"outcome": "failure_finding", "task": "Compare both IMUs in the arming self-test log",
                       "interval": 10, "interval_unit": "hours"}},
     ]},
    {"position": "GPS receiver", "function": "Give the aircraft's position",
     "standards": [
         {"text": "Horizontal position within 2 m", "parameter": "Horizontal error", "comparator": "<=", "value": 2,
          "unit": "m"},
     ],
     "breaches": {"Position error over 2 m, or no fix": "Horizontal position within 2 m"},
     "modes": [
         {"text": "Antenna connector works loose", "ff": "Position error over 2 m, or no fix",
          "cause": "Vibration", "effect_local": "The position fix is lost",
          "effect_next": "Position hold fails; the aircraft drifts in wind", "effects": "Fly-away risk; a geofence breach.",
          "detection_method": "Satellite count in the pre-flight check",
          "severity": 8, "occurrence": 3, "detection": 2,  # RPN 48, AP L
          "action": "Locking connector; satellite count on the pre-flight checklist", "action_owner": "Production",
          "action_due": "2026-11-12", "action_status": "done",
          "failure_rate": 5e-5, "mode_ratio": 0.5, "loss_probability": 0.4, "severity_class": "II",  # Cm 1e-3
          "consequence": "operational",
          "decision": {"outcome": "on_condition", "task": "Check the satellite count before flight", "interval": 1,
                       "interval_unit": "days"}},
     ]},
    {"position": "Comms link", "function": "Carry control and telemetry between the aircraft and the ground station",
     "standards": [
         {"text": "Range of at least 2 km in line of sight", "parameter": "Range", "comparator": ">=", "value": 2,
          "unit": "km"},
     ],
     "breaches": {"Link lost inside 2 km": "Range of at least 2 km in line of sight"},
     "modes": [
         {"text": "Link lost behind terrain or to interference", "ff": "Link lost inside 2 km",
          "cause": "Flying out of line of sight", "effect_local": "No control input",
          "effect_next": "Failsafe return-to-home",
          "effects": "Mission aborted; a safe landing if return-to-home works.",
          "detection_method": "Signal strength shown on the ground station",
          "severity": 6, "occurrence": 5, "detection": 2,  # RPN 60, AP L
          "action": "Geofence on signal strength; pilot training", "action_owner": "Operations",
          "action_due": "2026-11-08", "action_status": "done",
          "failure_rate": 2e-4, "mode_ratio": 0.8, "loss_probability": 0.1, "severity_class": "III",  # Cm 1.6e-3
          "consequence": "operational",
          "decision": {"outcome": "redesign",
                       "notes": "A geofence on signal strength in the firmware, and pilots trained to keep line of "
                                "sight: no maintenance task helps."}},
     ]},
    {"position": "Payload gimbal", "function": "Hold the camera steady on the target",
     "modes": [
         {"text": "Gimbal motor stalls on a snagged cable", "ff": "Camera not held on the target",
          "cause": "Cable routing without a service loop", "effect_local": "The gimbal locks",
          "effect_next": "Footage unusable", "effects": "The mission is flown again.",
          "detection_method": "Gimbal sweep before flight",
          "severity": 3, "occurrence": 4, "detection": 2,  # RPN 24, AP L
          "action": "Re-route the cable with a service loop", "action_owner": "Payload",
          "action_due": "2026-11-05", "action_status": "done",
          "failure_rate": 1e-4, "mode_ratio": 0.7, "loss_probability": 0.02, "severity_class": "IV",  # Cm 1.4e-4
          "consequence": "non_operational",
          "decision": {"outcome": "rtf", "rtf_basis": "uneconomic",
                       "notes": "A stall costs a repeat flight, less than any task would; the cable now has a "
                                "service loop."}},
     ]},
]


def sample_uav_modes() -> list[dict]:
    """The sample quadcopter's RCM, a fresh copy each time (callers may change it)."""
    return copy.deepcopy(SAMPLE_UAV_MODES)


# The design's higher positions (the product itself and its groups): what each does,
# as a function with functional failures explained by those on the positions inside
# it (linked causes, no failure modes of their own), so the RCM reads top down.
# A cause names a position (SAMPLE_UAV_MODES's name, or a group's) and one of its
# functional failures; it means every position that name maps to. Inner groups
# first: a cause must be written before it is linked.
SAMPLE_UAV_GROUPS = [
    {"position": "Propulsion", "function": "Lift the aircraft and steer it by the thrust on each arm",
     "failures": [
         {"text": "Thrust lost or reduced on an arm",
          "caused_by": [("Motor", "The motor stops or loses torque"), ("Speed controller (ESC)", "No drive to the motor"),
                        ("Propeller", "Thrust lost on one arm"), ("Propeller", "Thrust lower than commanded")]},
     ]},
    {"position": "Flight control", "function": "Keep the aircraft stable and on its planned path",
     "failures": [
         {"text": "Loses control of attitude or position",
          "caused_by": [("Flight controller", "Loses attitude control"), ("IMU", "Readings drift or freeze"),
                        ("GPS receiver", "Position error over 2 m, or no fix")]},
     ]},
    {"position": "Power", "function": "Power every system for the planned flight",
     "failures": [
         {"text": "Power lost in flight", "caused_by": [("Battery pack", "Power lost in flight")]},
         {"text": "Flight shorter than planned",
          "caused_by": [("Battery pack", "Flight time on a full charge under 25 minutes")]},
     ]},
    {"position": "", "function": "Fly a planned survey and land safely",
     "failures": [
         {"text": "Aircraft lost or crashes",
          "caused_by": [("Airframe", "A structural member cracks or separates in flight"),
                        ("Propulsion", "Thrust lost or reduced on an arm"),
                        ("Flight control", "Loses control of attitude or position"), ("Power", "Power lost in flight")]},
         {"text": "Survey not completed",
          "caused_by": [("Comms link", "Link lost inside 2 km"), ("Payload gimbal", "Camera not held on the target"),
                        ("Power", "Flight shorter than planned")]},
     ]},
]


def _add_uav_groups(m, at_of: dict[str, list[str]], ffs: dict[tuple[str, str], str], counts: dict) -> None:
    """The higher positions' functions and functional failures, each linked to its
    causes below (ffs: (position id, functional failure text) -> id, filled as they're
    written)."""
    for entry in copy.deepcopy(SAMPLE_UAV_GROUPS):
        for at in at_of[entry["position"]]:
            function = m.add_function(at, entry["function"])
            counts["functions"] += 1
            for failure in entry["failures"]:
                ff = m.add_functional_failure(function["id"], failure["text"])
                ffs[(at, failure["text"])] = ff["id"]
                counts["functional_failures"] += 1
                for below, text in failure["caused_by"]:
                    for cause_at in at_of[below]:
                        m.link_cause(ff["id"], ffs[(cause_at, text)])
                        counts["causes_linked"] += 1


def _add_uav_modes(m, at_of: dict[str, list[str]], counts: dict) -> dict[tuple[str, str], str]:
    """The sample quadcopter's RCM on every position the template's position name maps
    to (at_of: name -> position ids; the sample product has four motors where the
    template names one): each function with its performance standards, its functional
    failures (breaching a standard where the template says so), and each failure mode
    scored, with its consequence, decision and notes. Returns the functional failures
    written: (position id, text) -> id."""
    written: dict[tuple[str, str], str] = {}
    for entry in sample_uav_modes():
        for at in at_of[entry["position"]]:
            function = m.add_function(at, entry["function"])
            counts["functions"] += 1
            standards = {}
            for st in entry.get("standards") or []:
                standards[st["text"]] = m.add_standard(function["id"], **st)["id"]
                counts["standards"] += 1
            ffs: dict[str, str] = {}
            for mode in entry["modes"]:
                if mode["ff"] not in ffs:
                    breach = (entry.get("breaches") or {}).get(mode["ff"])
                    ffs[mode["ff"]] = m.add_functional_failure(
                        function["id"], mode["ff"], standard_id=standards[breach] if breach else None)["id"]
                    written[(at, mode["ff"])] = ffs[mode["ff"]]
                    counts["functional_failures"] += 1
                fm = m.add_failure_mode(at, mode["text"], functional_failure_id=ffs[mode["ff"]])
                counts["failure_modes"] += 1
                if mode.get("effects") or mode.get("notes"):
                    m.update_failure_mode(fm["id"], effects=mode.get("effects"), notes=mode.get("notes"))
                m.score_failure_mode(fm["id"], _scores(mode, SAMPLE_UAV_BASIS))
                counts["scored"] += 1
                m.decide_failure_mode(fm["id"], consequence=mode.get("consequence"),
                                      decision=mode["decision"] if mode.get("decision") else ...)
                counts["decisions"] += bool(mode.get("decision"))
    return written


# ---- the sample product: a quadcopter design and three items built from it ---------
# Entirely invented: no real product, company or partner. The design carries the
# sample failure modes (SAMPLE_UAV_MODES) on every position they belong to (four motors,
# four speed controllers, four propellers, two IMUs), so its FME(C)A tab is full.

SAMPLE_PRODUCT_NAME = "Survey quadcopter (sample)"
SAMPLE_PRODUCT_PART = "SQ-4"
SAMPLE_PRODUCT_REV = "C"
SAMPLE_PRODUCT_DESCRIPTION = (
    "A sample product: a small survey quadcopter's design, with an RCM on its functional structure (functions, "
    "performance standards, functional failures, failure modes and a decision for each) and every failure mode "
    "scored as an FME(C)A. Some decisions link the analysis or model behind them: one is contradicted on purpose "
    "(the legacy run-to-failure plan on the motor bearings, whose life model shows wear-out), one can't be checked "
    "until its units agree, and two failure modes still need a decision. With its part and a small bill of "
    "materials, three items built from it, a replaced motor and two failure reports. Entirely invented."
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
# Where each of SAMPLE_UAV_MODES's positions sits in the product's design.
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
    sample failure modes scored on it, its part with a small bill of materials,
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
              "standards": 0, "decisions": 0, "causes_linked": 0}
    for group, cls, children in SAMPLE_PRODUCT_TREE:
        at[group] = m.create_position(group, parent_id=pid, position_class=cls)["id"]
        counts["positions"] += 1
        for child, child_cls in children:
            at[child] = m.create_position(child, parent_id=at[group], position_class=child_cls)["id"]
            counts["positions"] += 1
    at_of = {k: [at[n] for n in names] for k, names in SAMPLE_PRODUCT_MODES_AT.items()}
    ffs = _add_uav_modes(m, at_of, counts)
    _add_uav_groups(m, at_of | {group: [at[group]] for group, _, _ in SAMPLE_PRODUCT_TREE} | {"": [pid]}, ffs, counts)

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
        "message": (f"Added “{name}”: a design of {_n(counts['positions'], 'position')} with an RCM and "
                    f"{_n(counts['failure_modes'], 'failure mode')} scored as an FME(C)A (one decision shows as "
                    "contradicted on purpose: the motor bearings' own model shows wear-out), its part with a bill of "
                    f"materials, {_n(len(items), 'item')} built from it (serials "
                    f"{', '.join(it['serial'] for it in items)}), a replaced motor and two failure reports. "
                    f"The RBD “{rbd['name']}” is in your RBDs: its failure rates are placeholders, not data. "
                    "Each arm's ESC, "
                    "motor and propeller are in series there: the design has one ESC per motor."),
    }
