"""Templates: ready-made samples a workspace can copy in.

The sample product, "Survey quadcopter (sample)": the one sample for the RCM
and FME(C)A tabs, on Products (a design, not an operated asset in the tree).
It is a complete RCM study of a small inspection quadcopter, written the way a
reliability engineer would write one for a drone maker: a mission (routine
corridor inspection of a rural distribution feeder, in the product's
description and the top position's operating context) from which every
performance standard takes its numbers; functions with those standards on
every position of the design tree (airframe, arms and landing gear;
propulsion; flight control with its protective functions; power; comms;
payload); the functional failures, each breaching a standard; the failure
modes that cause them, each with full FME(C)A fields, a consequence class and
a decision (on condition, scheduled discard or restoration, failure finding
for the hidden protective functions, redesign, run to failure, or risk
accepted); and the tasks those decisions schedule, read together as the
aircraft's maintenance programme (the pre-flight check, the flight log
review, the 25-hour, 100-hour and annual inspections, the monthly failsafe
function tests, the three-monthly battery storage check, and the propeller and
battery limits). The higher positions' functional failures are explained by
those on the positions inside them (linked causes), so the RCM tab reads top
down. Each programme task carries its LSA record (who does it and for how
long, the tools, spares and consumables, access and the method), which the
items built from the design copy; the calendar tasks (the failsafe tests, the
battery storage check and the annual inspection) are packaged into one
monthly visit on the first item built. The motors, propellers, battery pack
and radio carry life models: shared samples, invented like the rest, each
link saying so.

Some decisions link the evidence behind them, saved analyses and models every
account can read, so the evidence check shows each case: the propeller
replacement, the BMS failure-finding test, the speed controllers' thermal-pad
check (a degradation model), the radio's run-to-failure (an exponential fit)
and the gimbal motor's (a replacement analysis with no worthwhile interval)
are supported; the legacy run-to-failure plan on the motor bearings is
contradicted on purpose (the bearing life model shows wear-out); the battery
retirement can't be checked yet (its task counts charge cycles, its analysis
flight hours). Two modes still need a decision, on purpose, and eight are
hidden failures with failure-finding tasks. It comes with a part and bill of
materials, three items built from it, failure reports, a flight-critical
RBD and a maintainability prediction attached to the product (the shared
sample prediction's lines). Entirely invented: no real product, company,
operator or partner.
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

from backend.maintenance import fmea, products


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


# ---- the sample quadcopter's mission ------------------------------------------------
# Entirely invented: no real product, company, operator or partner. The sample
# product ("Survey quadcopter (sample)", below) puts the RCM on its design: the one
# sample for the RCM and FME(C)A tabs, on Products, not in the asset tree.

# The product's description (what the product page shows).
SAMPLE_PRODUCT_DESCRIPTION = (
    "A sample product: a small inspection quadcopter's design with a complete RCM study on it and every failure "
    "mode scored as an FME(C)A. The mission it is designed for (invented, like everything here): routine corridor "
    "inspection of a 12 km rural 11 kV distribution feeder, flown monthly in sorties of up to 25 minutes, 30 m above "
    "the conductors at 5 m/s, with a 4K camera and a thermal imager on a gimbal; about 150 flight hours a year per "
    "aircraft. Each position carries its functions with their performance standards (numbers from the mission), "
    "the ways each fails, the failure modes that cause them, and a decision for each: the checks before every "
    "flight, the flight log review, the 25-hour, 100-hour and annual inspections, the monthly failsafe function "
    "tests, the three-monthly battery storage check, the propeller and battery limits, and the things to redesign, "
    "run to failure or accept. Each programme task has its LSA record (labour, tools, spares, method). Some "
    "decisions link the "
    "analysis or model behind them: the legacy run-to-failure plan on the motor bearings is contradicted on purpose "
    "(their life model shows wear-out), the battery retirement can't be checked until its units agree, and two "
    "failure modes still need a decision. The motors, propellers, battery pack and radio carry sample life models. "
    "With its part and bill of materials, three items built from it (the first with its calendar tasks in a "
    "monthly work package), a replaced motor and two failure reports. Entirely invented: no real product, company "
    "or operator."
)

# The top position's operating context: the mission every performance standard
# below takes its numbers from.
SAMPLE_PRODUCT_CONTEXT = (
    "Mission: routine corridor inspection of a 12 km rural 11 kV distribution feeder, once a month. The feeder is "
    "flown in 6 to 8 sorties over two days, 3 or 4 sorties a day, each of up to 25 minutes on one battery pack.\n\n"
    "Flight profile: 30 m above the conductors (about 40 m above ground) at 5 m/s along the line, with a hover of up "
    "to 30 s at each pole; take-off and landing from a marked pad, never more than 2 km from the aircraft; 4K video "
    "and thermal imaging of the conductors, insulators and fittings, 10 mm per pixel at 30 m.\n\n"
    "Limits: 0 to 40 °C, wind up to 10 m/s, no rain, daylight only. A geofence on the corridor and a 120 m height "
    "limit, both loaded before each day's flying. Return-to-home within 3 s of losing the control link, and at 20 % "
    "charge; landed with at least 15 % left.\n\n"
    "Use: about 150 flight hours a year per aircraft (around 400 sorties); 1.6 kg all-up mass; gravel and grass "
    "pads.\n\n"
    "Crew and rules: a pilot and an observer; a pre-flight check before every sortie; flight logs reviewed every 10 "
    "flight hours; battery packs retired at a cycle count. Maintenance by the operator's own technician, with an "
    "annual inspection at the maker's service centre."
)

# The criticality figures are all over a year's flying: 150 flight hours per aircraft.
SAMPLE_UAV_BASIS = {"operating_time": 150.0, "time_unit": "hours", "rate_source": "entered"}

# The evidence some decisions link: shared samples every account can read
# (backend/services/samples.py). The bearing life model shows wear-out, so the
# motors' legacy run-to-failure decision is contradicted on purpose; the battery's
# retirement analysis is in flight hours while its task counts charge cycles, so
# that check is inconclusive until the units agree. The rest are supported: the
# propeller replacement and the gimbal motor's run-to-failure (replacement
# analyses, one with a worthwhile interval and one without), the BMS cut-off's
# failure-finding interval, the speed controllers' temperature-rise degradation
# model, and the avionics boards' exponential fit (random failures).
UAV_BEARING_MODEL = "sample-model-bearings-weibull"
UAV_AVIONICS_MODEL = "sample-model-quad-avionics-exponential"
UAV_ESC_DEGRADATION = "sample-deg-quad-esc-temperature"
UAV_PROPELLER_ANALYSIS = "sample-strategy-quad-propeller-replacement"
UAV_BATTERY_ANALYSIS = "sample-strategy-quad-battery-retirement"
UAV_BMS_ANALYSIS = "sample-strategy-quad-bms-failure-finding"
UAV_GIMBAL_ANALYSIS = "sample-strategy-quad-gimbal-replacement"

# The maintenance programme: the shared tasks on the product (the top position), each
# serving every failure mode whose decision names it (decision "programme": its key;
# "check": the line it adds to the task's checklist). A task on a position may serve
# the failure modes on the positions inside it, so these read as one schedule on each
# aircraft built from the design: before every flight, every 10 flight hours (the log),
# every 25 and 100 flight hours, and by the calendar: the failsafe tests every month,
# the battery storage check every three months and the annual inspection. The use-based
# tasks go by flight hours or flights because wear does; the calendar ones go by the
# calendar because what they find doesn't come from flying (a configuration change, a
# pack draining in storage, rubber and memory cards ageing).
SAMPLE_UAV_PROGRAMME = {
    "pre_flight": {
        "name": "Pre-flight check", "interval": 1, "unit": "flights", "outcome": "on_condition",
        "instructions": "Before every sortie, by the pilot with the observer reading the list. Any item not as it "
                        "should be grounds the aircraft until it is.",
    },
    "log_review": {
        "name": "Flight log review", "interval": 10, "unit": "hours", "outcome": "on_condition",
        "instructions": "Every 10 flight hours, on the planner: the motor and speed controller temperatures, RPM "
                        "dropouts, watchdog events and the arming self-tests over the flights since the last review.",
    },
    "25h": {
        "name": "25-hour inspection", "interval": 25, "unit": "hours", "outcome": "on_condition",
        "instructions": "Every 25 flight hours, by the technician, with the arms unfolded and the propellers off.",
    },
    "100h": {
        "name": "100-hour inspection", "interval": 100, "unit": "hours", "outcome": "on_condition",
        "instructions": "Every 100 flight hours, by the technician: the 25-hour items, then the centre frame with "
                        "the arms off.",
    },
    "annual": {
        "name": "Annual inspection", "interval": 12, "unit": "months", "outcome": "on_condition",
        "instructions": "Once a year at the maker's service centre: the 100-hour items, the age-limited parts "
                        "replaced, and the aircraft's logs reviewed for the year.",
    },
    "failsafe": {
        "name": "Failsafe function tests", "interval": 1, "unit": "months", "outcome": "failure_finding",
        "instructions": "Every month, before the month's survey flying, and after any firmware or configuration "
                        "change: each protective function tested over the pad, so a hidden failure is found "
                        "before it is needed.",
    },
    "battery": {
        "name": "Battery storage check", "interval": 3, "unit": "months", "outcome": "on_condition",
        "instructions": "Every three months, on every pack, flown or not: packs drain in storage whether the "
                        "aircraft flies or not.",
    },
}
SAMPLE_UAV_PROGRAMME_NAMES = tuple(spec["name"] for spec in SAMPLE_UAV_PROGRAMME.values())

# The RCM, position by position: each entry names a template position (mapped to one
# or more positions of the design: four arms, four motors), its operating context, and
# its functions, each with its performance standards (numbers from the mission) and
# the functional failures that breach them ("standard": the standard's text; none: the
# whole function, as a total loss does). A functional failure carries its failure
# modes (the FME(C)A fields, consequence and decision; None = still to decide, on
# purpose, with notes saying why) and, on the higher positions, the lower functional
# failures that cause it ("caused_by": template position and failure text; it means
# every position that name maps to). Lower positions come first: a cause must be
# written before it is linked. A decision with "programme" joins that shared task.
SAMPLE_UAV_RCM = [
    # ---- the airframe: arms, centre frame, landing gear -----------------------------
    {"position": "Arm",
     "context": "16 mm carbon tube, 230 mm long, with a folding latch at the root; carries one motor at up to 12 N "
                "of thrust (about 4 N in the hover); folded for transport after every day's flying.",
     "functions": [
         {"text": "Carry the motor's thrust and torque into the centre frame",
          "standards": [{"text": "Carries 12 N of thrust with a 3 g manoeuvring margin", "parameter": "Thrust carried",
                         "comparator": ">=", "value": 12, "unit": "N"}],
          "failures": [
              {"text": "The boom cracks or separates in flight",
               "standard": "Carries 12 N of thrust with a 3 g manoeuvring margin",
               "modes": [
                   {"text": "Arm boom fatigue crack at the motor mount",
                    "cause": "Vibration from an unbalanced propeller, cycled at every take-off and landing",
                    "effect_local": "Boom stiffness drops; the mount flexes",
                    "effect_next": "Motor thrust axis tilts; attitude control saturates",
                    "effects": "Loss of control and an uncontrolled descent.",
                    "detection_method": "Magnified look at the arm roots and mounts at the 25-hour inspection; the "
                                        "pre-flight look sees a crack only once it is open",
                    "severity": 10, "occurrence": 3, "detection": 5,  # RPN 150, AP M
                    "action": "Magnified inspection of the arm roots every 25 flight hours; a larger mount fillet "
                              "radius at rev D",
                    "action_owner": "Airframe lead", "action_due": "2026-12-15", "action_status": "open",
                    "failure_rate": 2e-5, "mode_ratio": 0.6, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "25h",
                                 "check": "Arm roots and motor mounts: magnified look for cracks; replace the arm at "
                                          "any crack",
                                 "notes": "P-F interval: on the fatigue coupons a crack at the mount grows from "
                                          "visible under a magnifier (0.5 mm) to separation in about 60 flight "
                                          "hours, so a look every 25 hours gives at least two chances to catch it."}},
               ]},
          ]},
         {"text": "Lock in the flying position when unfolded",
          "standards": [{"text": "The latch holds the arm locked at three times the hover load",
                         "parameter": "Latch holding load", "comparator": ">=", "value": 12, "unit": "N"}],
          "failures": [
              {"text": "The arm unfolds or swings in flight",
               "standard": "The latch holds the arm locked at three times the hover load",
               "modes": [
                   {"text": "Folding latch wears and no longer locks",
                    "cause": "Latch pawl worn by sand from the pad, over hundreds of folds",
                    "effect_local": "The latch closes but does not click home",
                    "effect_next": "The arm swings back under thrust; the propeller strikes the body",
                    "effects": "Loss of control and an uncontrolled descent.",
                    "detection_method": "Pre-flight: each arm pushed against its latch; a locked latch does not move",
                    "severity": 10, "occurrence": 2, "detection": 2,  # RPN 40, AP L
                    "action": "Hardened pawl at rev D; the push test on the pre-flight check",
                    "action_owner": "Airframe lead", "action_due": "2027-02-01", "action_status": "open",
                    "failure_rate": 2e-5, "mode_ratio": 0.4, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Arms: each unfolded and pushed against its latch; the latch holds",
                                 "notes": "A worn latch still closes, so it is found by a push test before each "
                                          "flight; it wears over months, not flights."}},
               ]},
          ]},
     ]},
    {"position": "Centre frame",
     "context": "Two carbon plates on aluminium standoffs; each arm clamps to it with four M3 bolts at 2.5 N·m.",
     "functions": [
         {"text": "Hold the arms, the centre body and the landing gear together",
          "standards": [{"text": "Arm clamp bolts at 2.5 N·m with no measurable play", "parameter": "Arm clamp bolt torque",
                         "comparator": "=", "value": 2.5, "unit": "N·m"}],
          "failures": [
              {"text": "The frame cracks or an arm joint loosens",
               "standard": "Arm clamp bolts at 2.5 N·m with no measurable play",
               "modes": [
                   {"text": "Frame plate cracks at an arm bolt hole",
                    "cause": "Fatigue at the bolt hole from arm bending loads, worse after a hard landing",
                    "effect_local": "The plate loses stiffness around the hole",
                    "effect_next": "The arm works loose; the motor axis wanders",
                    "effects": "Loss of control if the arm separates.",
                    "detection_method": "Magnified look at the bolt holes at the 100-hour inspection, and after any "
                                        "hard landing",
                    "severity": 10, "occurrence": 2, "detection": 5,  # RPN 100, AP M
                    "action": "Magnified inspection of the plates at the bolt holes every 100 hours and after a hard "
                              "landing",
                    "action_owner": "Airframe lead", "action_due": "2026-12-15", "action_status": "done",
                    "failure_rate": 1e-5, "mode_ratio": 0.5, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "100h",
                                 "check": "Centre plates: magnified look at every arm bolt hole for cracks",
                                 "notes": "P-F interval: on the test frames a crack from a bolt hole takes well over "
                                          "100 hours to reach the plate's edge, so 100 hours leaves a margin; a hard "
                                          "landing brings the look forward."}},
                   {"text": "Arm clamp bolts lose preload",
                    "cause": "Vibration; no thread locker after an arm change",
                    "effect_local": "Play at the arm joint",
                    "effect_next": "The motor axis wanders; vibration rises; the bolt holes elongate",
                    "effects": "An arm separates in flight.",
                    "detection_method": "Torque check at the 100-hour inspection; vibration in the flight log rises "
                                        "first",
                    "severity": 9, "occurrence": 3, "detection": 4,  # RPN 108, AP L
                    "action": "Torque stripe on every clamp bolt; re-torque at the 100-hour inspection",
                    "action_owner": "Airframe lead", "action_due": "2026-11-30", "action_status": "done",
                    "failure_rate": 1e-5, "mode_ratio": 0.5, "loss_probability": 0.5, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "fixed_interval", "programme": "100h",
                                 "check": "Arm clamp bolts: re-torque to 2.5 N·m and renew the torque stripes",
                                 "notes": "Scheduled restoration: the bolts are brought back to 2.5 N·m every 100 "
                                          "hours whether or not they have moved, because a loose bolt shows no sign "
                                          "before the joint has play."}},
               ]},
          ]},
     ]},
    {"position": "Landing gear",
     "context": "Two fixed carbon legs with rubber feet; lands on gravel and grass pads; 120 mm of clearance under "
                "the camera.",
     "functions": [
         {"text": "Hold the aircraft level on the ground and take the landing load",
          "standards": [
              {"text": "Takes a landing at 2 m/s descent without damage", "parameter": "Landing descent rate",
               "comparator": ">=", "value": 2, "unit": "m/s"},
              {"text": "Keeps the camera 120 mm clear of the ground", "parameter": "Camera ground clearance",
               "comparator": ">=", "value": 120, "unit": "mm"},
          ],
          "failures": [
              {"text": "A leg breaks or collapses on touchdown",
               "standard": "Takes a landing at 2 m/s descent without damage",
               "modes": [
                   {"text": "Landing gear leg breaks on touchdown",
                    "cause": "Hard landing beyond the design load", "effect_local": "The leg fails",
                    "effect_next": "The airframe tips over on the ground; the propellers strike",
                    "effects": "Payload damage on landing; no injury.", "detection_method": "Post-flight look at the legs",
                    "severity": 5, "occurrence": 4, "detection": 2,  # RPN 40, AP L
                    "action": "Add a crushable foot to the leg", "action_owner": "Airframe lead",
                    "action_due": "2027-01-20", "action_status": "open",
                    "failure_rate": 5e-5, "mode_ratio": 0.4, "loss_probability": 0.3, "severity_class": "III",
                    "consequence": "operational", "decision": None,
                    "notes": "Still to decide, on purpose: the decision waits on the crushable-foot trial."},
               ]},
              {"text": "Ground clearance under 120 mm",
               "standard": "Keeps the camera 120 mm clear of the ground",
               "modes": [
                   {"text": "Rubber foot wears through on gravel pads",
                    "cause": "Abrasion on gravel; the foot is soft rubber",
                    "effect_local": "The foot wears down to the carbon leg",
                    "effect_next": "Clearance drops; the camera touches down on a rough pad",
                    "effects": "A scratched lens and a repeat sortie.", "detection_method": "Obvious at a glance",
                    "severity": 3, "occurrence": 6, "detection": 1,  # RPN 18, AP L
                    "action": "Spare feet in the field kit", "action_owner": "Operations",
                    "action_due": "2026-11-10", "action_status": "done",
                    "failure_rate": 5e-5, "mode_ratio": 0.6, "loss_probability": 0.02, "severity_class": "IV",
                    "consequence": "non_operational",
                    "decision": {"outcome": "rtf", "rtf_basis": "uneconomic",
                                 "task": "Replace the foot when it has worn through",
                                 "notes": "A foot costs less than any inspection would; it is seen at a glance and "
                                          "replaced on the spot."}},
               ]},
          ]},
     ]},
    {"position": "Airframe",
     "context": "Carbon-fibre tube arms on an aluminium and carbon centre frame, with fixed landing gear; 1.6 kg "
                "all-up mass; designed for 3 g manoeuvring and a 2 m/s landing.",
     "functions": [
         {"text": "Carry the propulsion, power, control and payload modules through flight loads and landings",
          "standards": [
              {"text": "Withstands 3 g manoeuvring with no permanent set", "parameter": "Manoeuvring load",
               "comparator": ">=", "value": 3, "unit": "g"},
              {"text": "Takes a landing at 2 m/s descent without damage", "parameter": "Landing descent rate",
               "comparator": ">=", "value": 2, "unit": "m/s"},
          ],
          "failures": [
              {"text": "A structural member cracks or separates in flight",
               "standard": "Withstands 3 g manoeuvring with no permanent set",
               "caused_by": [("Arm", "The boom cracks or separates in flight"),
                             ("Arm", "The arm unfolds or swings in flight"),
                             ("Centre frame", "The frame cracks or an arm joint loosens")]},
              {"text": "The aircraft tips over or is damaged on landing",
               "standard": "Takes a landing at 2 m/s descent without damage",
               "caused_by": [("Landing gear", "A leg breaks or collapses on touchdown"),
                             ("Landing gear", "Ground clearance under 120 mm")]},
          ]},
     ]},
    # ---- propulsion: a propeller, a motor and a speed controller on each arm ---------
    {"position": "Propeller",
     "context": "10×4.5 two-blade plastic propeller, balanced at the factory; 12 N at 9,000 rpm; changed at 130 "
                "flight hours or at any chip.",
     "functions": [
         {"text": "Produce thrust at the commanded speed",
          "standards": [{"text": "12 N of thrust at 9,000 rpm", "parameter": "Thrust at 9,000 rpm", "comparator": ">=",
                         "value": 12, "unit": "N"}],
          "failures": [
              {"text": "Thrust lower than commanded", "standard": "12 N of thrust at 9,000 rpm",
               "modes": [
                   {"text": "Blade chipped by a ground strike",
                    "cause": "Debris on the take-off pad", "effect_local": "Imbalance and lost efficiency",
                    "effect_next": "Vibration into the motor mount", "effects": "Shorter arm life and reduced flight time.",
                    "detection_method": "Pre-flight blade check against the go/no-go gauge",
                    "severity": 4, "occurrence": 6, "detection": 2,  # RPN 48, AP M
                    "action": "Issue a blade go/no-go gauge; replace on any chip", "action_owner": "Operations",
                    "action_due": "2026-11-15", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.6, "loss_probability": 0.1, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Propellers: each blade against the go/no-go gauge; replace on any chip",
                                 "notes": "A chip happens in a moment, on the pad, so only a check before each "
                                          "flight catches it; the gauge makes the call the same for every pilot."}},
               ]},
              {"text": "Thrust lost on one arm",
               "modes": [
                   {"text": "Propeller nut loosens",
                    "cause": "No thread locker after a blade change", "effect_local": "The propeller spins free",
                    "effect_next": "Thrust lost on one arm", "effects": "Uncontrolled descent.",
                    "detection_method": "Torque-stripe check before flight",
                    "severity": 10, "occurrence": 2, "detection": 3,  # RPN 60, AP L
                    "action": "Captive nut with a locking feature; torque stripe on every nut",
                    "action_owner": "Propulsion lead", "action_due": "2026-12-05", "action_status": "open",
                    "failure_rate": 2e-4, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Propeller nuts: the torque stripe unbroken on every nut",
                                 "notes": "A nut loosens over a few flights once it starts; a broken stripe before "
                                          "each flight is the warning."}},
                   {"text": "Blade fatigue crack at the hub",
                    "cause": "Cyclic bending in flight", "effect_local": "A crack grows from the hub",
                    "effect_next": "The blade separates; thrust lost on one arm", "effects": "Uncontrolled descent.",
                    "detection_method": "None reliable before the crack shows",
                    "severity": 10, "occurrence": 3, "detection": 7,  # RPN 210, AP H
                    "action": "Replace the propellers every 130 flight hours, as the replacement analysis shows",
                    "action_owner": "Propulsion lead", "action_due": "2026-11-28", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.3, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "fixed_interval", "task": "Replace the propeller", "interval": 130,
                                 "interval_unit": "hours",
                                 "notes": "Scheduled discard: a hub crack can't be seen before the blade lets go, "
                                          "so the propeller is replaced at 130 hours, the interval the "
                                          "optimal-replacement analysis finds.",
                                 "evidence": {"type": "strategy_analysis", "id": UAV_PROPELLER_ANALYSIS}}},
               ]},
          ]},
     ]},
    {"position": "Motor",
     "context": "2210 brushless outrunner, 920 kV, on a 30 A speed controller; about 9,000 rpm at full throttle on "
                "the 10×4.5 propeller and 5,500 rpm in the hover; sealed bearings from rev C.",
     "functions": [
         {"text": "Turn the propeller at the commanded speed",
          "standards": [{"text": "Reaches 9,000 rpm at full throttle with the 10×4.5 propeller",
                         "parameter": "Full-throttle speed", "comparator": ">=", "value": 9000, "unit": "rpm"}],
          "failures": [
              {"text": "The motor stops or loses torque",
               "standard": "Reaches 9,000 rpm at full throttle with the 10×4.5 propeller",
               "modes": [
                   {"text": "Bearing seizure",
                    "cause": "Bearing wear from dust ingress", "effect_local": "The motor stalls",
                    "effect_next": "The speed controller cuts out on overcurrent; thrust lost on one arm",
                    "effects": "A quadcopter cannot fly on three motors: uncontrolled descent.",
                    "detection_method": "Motor current trend in the flight log; spin check before flight",
                    "severity": 9, "occurrence": 4, "detection": 6,  # RPN 216, AP H
                    "action": "Retire the legacy run-to-failure plan: spin check before every flight; fit sealed "
                              "bearings",
                    "action_owner": "Propulsion lead", "action_due": "2026-11-30", "action_status": "open",
                    "failure_rate": 8e-5, "mode_ratio": 0.5, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "rtf", "rtf_basis": "random",
                                 "notes": "Legacy decision from the first build's plan, kept to show the evidence "
                                          "check: the bearing life model shows wear-out, so running to failure isn't "
                                          "justified.",
                                 "evidence": {"type": "model", "id": UAV_BEARING_MODEL}}},
                   {"text": "Winding insulation breaks down from overheating",
                    "cause": "Sustained overload in hot weather", "effect_local": "A phase shorts",
                    "effect_next": "Speed controller fault; thrust lost on one arm", "effects": "Uncontrolled descent.",
                    "detection_method": "Motor temperature in the flight log, reviewed every 10 hours",
                    "severity": 9, "occurrence": 2, "detection": 4,  # RPN 72, AP L
                    "action": "Derate hover power above 35 °C; add the temperature limit to the pre-flight check",
                    "action_owner": "Propulsion lead", "action_due": "2026-12-01", "action_status": "in_progress",
                    "failure_rate": 8e-5, "mode_ratio": 0.3, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "log_review",
                                 "check": "Motor temperatures: no motor above 80 °C in the hover; the trend over the "
                                          "last 10 hours flat",
                                 "notes": "P-F interval: insulation that is cooking shows as a rising temperature at "
                                          "the same hover power for tens of hours before it shorts, so the 10-hour "
                                          "log review sees it coming."}},
                   {"text": "Rotor bell screws back out",
                    "cause": "Vibration; screws fitted without thread locker at a bearing change",
                    "effect_local": "The bell lifts on the shaft",
                    "effect_next": "The bell rubs the stator; the motor stalls",
                    "effects": "Thrust lost on one arm: uncontrolled descent.",
                    "detection_method": "Pre-flight spin check: a rubbing or scraping bell is felt by hand",
                    "severity": 10, "occurrence": 2, "detection": 2,  # RPN 40, AP L
                    "action": "Thread locker on the bell screws written into the bearing-change procedure",
                    "action_owner": "Propulsion lead", "action_due": "2026-11-20", "action_status": "done",
                    "failure_rate": 8e-5, "mode_ratio": 0.2, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Motors: spin each by hand; smooth, with no roughness, rubbing or play",
                                 "notes": "A screw backing out rubs for many flights before the bell lifts; the spin "
                                          "check before each flight is enough."}},
               ]},
          ]},
     ]},
    {"position": "Speed controller (ESC)",
     "context": "30 A, 6S; inside the arm under a cover, cooled by the propeller wash, with a silicone thermal pad "
                "to the arm tube; derates above a 45 °C rise over ambient.",
     "functions": [
         {"text": "Convert pack power into the three-phase drive the motor needs",
          "standards": [{"text": "Delivers 30 A continuously at 40 °C without cutting back",
                         "parameter": "Continuous current", "comparator": ">=", "value": 30, "unit": "A"}],
          "failures": [
              {"text": "No drive to the motor",
               "modes": [
                   {"text": "Power transistor fails short",
                    "cause": "Voltage spike during regenerative braking", "effect_local": "The controller shuts down",
                    "effect_next": "Thrust lost on one arm", "effects": "Uncontrolled descent.",
                    "detection_method": "Self-test at arming reports a shorted phase",
                    "severity": 9, "occurrence": 3, "detection": 7,  # RPN 189, AP H
                    "action": "Add a bulk capacitor on the power rail; limit braking in firmware",
                    "action_owner": "Electronics lead", "action_due": "2026-12-10", "action_status": "open",
                    "failure_rate": 3e-5, "mode_ratio": 0.5, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "redesign",
                                 "notes": "No task catches a transistor short in flight: the fix is in the design."}},
                   {"text": "Loses sync with the motor on a rapid throttle change",
                    "cause": "Timing mismatch with the motor at high load", "effect_local": "The motor stutters",
                    "effect_next": "Momentary thrust loss; an attitude excursion",
                    "effects": "A hard landing in gusty conditions.",
                    "detection_method": "Flight log review for RPM dropouts",
                    "severity": 7, "occurrence": 5, "detection": 4,  # RPN 140, AP M
                    "action": "Tune the controller timing per motor batch; flag RPM dropouts in the log review",
                    "action_owner": "Flight test", "action_due": "2026-11-20", "action_status": "done",
                    "failure_rate": 3e-5, "mode_ratio": 0.3, "loss_probability": 0.2, "severity_class": "II",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "log_review",
                                 "check": "RPM dropouts: none in the log; any dropout grounds the aircraft until the "
                                          "controller timing is re-tuned",
                                 "notes": "A dropout in the log is the warning; it repeats for many flights before "
                                          "it becomes a fall, so the 10-hour review is soon enough."}},
               ]},
              {"text": "Current cut back below 30 A",
               "standard": "Delivers 30 A continuously at 40 °C without cutting back",
               "modes": [
                   {"text": "Thermal pad dries out; the controller runs hot and limits current",
                    "cause": "The silicone pad between the controller and the arm hardens and shrinks with heat cycles",
                    "effect_local": "The controller's temperature rise in the hover climbs from 20 °C toward 45 °C",
                    "effect_next": "Thermal limiting cuts the current on a climb: a slow climb, then a stutter",
                    "effects": "A hard landing in gusty conditions; a sortie cut short.",
                    "detection_method": "Controller temperature in the flight log, read every 10 hours; the "
                                        "degradation model gives the hours left to the 45 °C limit",
                    "severity": 7, "occurrence": 4, "detection": 3,  # RPN 84, AP M
                    "action": "Trend the temperature rise against the 45 °C limit; replace the pad at 35 °C",
                    "action_owner": "Electronics lead", "action_due": "2026-12-01", "action_status": "in_progress",
                    "failure_rate": 3e-5, "mode_ratio": 0.2, "loss_probability": 0.2, "severity_class": "II",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "log_review",
                                 "check": "Speed controller temperature rise in the hover: under 35 °C above "
                                          "ambient; replace the thermal pad at 35 °C (the limit is 45 °C)",
                                 "notes": "P-F interval: the rise climbs about 0.1 °C per flight hour (the "
                                          "degradation model), so from 35 °C to the 45 °C limit is about 100 "
                                          "hours; a 10-hour log review is well inside that.",
                                 "evidence": {"type": "degradation_model", "id": UAV_ESC_DEGRADATION}}},
               ]},
          ]},
     ]},
    {"position": "Propulsion",
     "context": "Four arms, each a 2210 motor on a 30 A speed controller turning a 10×4.5 propeller; hover at about "
                "55 % throttle at 1.6 kg; 12 N of thrust per arm at full throttle. A quadcopter can't fly on three "
                "arms.",
     "functions": [
         {"text": "Lift the aircraft and steer it by the thrust on each arm",
          "standards": [{"text": "Hovers at no more than 60 % throttle at 1.6 kg", "parameter": "Hover throttle",
                         "comparator": "<=", "value": 60, "unit": "%"}],
          "failures": [
              {"text": "Thrust lost or reduced on an arm",
               "caused_by": [("Motor", "The motor stops or loses torque"), ("Speed controller (ESC)", "No drive to the motor"),
                             ("Propeller", "Thrust lost on one arm")]},
              {"text": "Hover throttle above 60 %", "standard": "Hovers at no more than 60 % throttle at 1.6 kg",
               "caused_by": [("Propeller", "Thrust lower than commanded"),
                             ("Speed controller (ESC)", "Current cut back below 30 A")]},
          ]},
     ]},
    # ---- power: the pack and its management board -----------------------------------
    {"position": "Battery pack",
     "context": "6S 10 Ah lithium-polymer, 1.3 kg; a 25-minute sortie uses about 80 % of its capacity; charged at "
                "1C in a fire-resistant bag; stored at 50 % charge; retired at 300 cycles.",
     "functions": [
         {"text": "Supply power for the planned flight",
          "standards": [{"text": "At least 25 minutes' flight on a full charge", "parameter": "Flight time",
                         "comparator": ">=", "value": 25, "unit": "min"}],
          "failures": [
              {"text": "Flight time on a full charge under 25 minutes",
               "standard": "At least 25 minutes' flight on a full charge",
               "modes": [
                   {"text": "Cell capacity fade",
                    "cause": "Ageing and deep discharge cycles", "effect_local": "The pack runs down early",
                    "effect_next": "Low-voltage warning; return-to-home triggered",
                    "effects": "Mission cut short; a controlled landing.",
                    "detection_method": "Capacity logged on every charge",
                    "severity": 4, "occurrence": 7, "detection": 2,  # RPN 56, AP M
                    "action": "Retire packs at 300 charge cycles; redo the retirement analysis in cycles",
                    "action_owner": "Operations", "action_due": "2026-11-10", "action_status": "open",
                    "failure_rate": 3e-4, "mode_ratio": 0.4, "loss_probability": 0.05, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "fixed_interval", "task": "Retire the battery pack", "interval": 300,
                                 "interval_unit": "cycles",
                                 "notes": "Scheduled discard. The task counts charge cycles but the analysis behind "
                                          "it is in flight hours, so the evidence check can't compare them until "
                                          "the units agree.",
                                 "evidence": {"type": "strategy_analysis", "id": UAV_BATTERY_ANALYSIS}}},
                   {"text": "Cells puff (swell) after storage at full charge",
                    "cause": "Packs left full for days in a hot vehicle",
                    "effect_local": "The pack swells; its internal resistance rises",
                    "effect_next": "Flight time drops; the pack is a fire risk on charge",
                    "effects": "A sortie cut short; a charging fire in the worst case.",
                    "detection_method": "Pre-flight: the pack is flat-sided and fits the bay without force",
                    "severity": 8, "occurrence": 4, "detection": 2,  # RPN 64, AP M
                    "action": "A 50 % storage-charge rule in the field procedure; a storage-mode charger",
                    "action_owner": "Safety lead", "action_due": "2026-11-20", "action_status": "done",
                    "failure_rate": 3e-4, "mode_ratio": 0.2, "loss_probability": 0.1, "severity_class": "II",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Packs: flat-sided, no puffing; a swollen pack is retired on the spot",
                                 "notes": "A swollen pack shows days before it fails; the look before each flight, "
                                          "and the 50 % storage rule, cover it."}},
                   {"text": "Stored pack self-discharges below its safe voltage",
                    "cause": "Spare packs left for weeks between the monthly survey days; the BMS draws a small "
                             "standby current",
                    "effect_local": "Cells fall below 3.0 V in storage",
                    "effect_next": "Capacity lost for good; a deeply discharged pack is unsafe to charge",
                    "effects": "Shorter flights or a pack retired early; a charging fire if one is charged anyway.",
                    "detection_method": "Cell voltages read on every pack at the battery storage check",
                    "severity": 7, "occurrence": 3, "detection": 3,  # RPN 63, AP L
                    "action": "Store packs at 3.8 V a cell; a BMS that sleeps when the pack is unplugged",
                    "action_owner": "Operations", "action_due": "2026-12-01", "action_status": "open",
                    "failure_rate": 3e-4, "mode_ratio": 0.1, "loss_probability": 0.1, "severity_class": "II",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "battery",
                                 "check": "Every pack: cells at 3.75 to 3.85 V; a pack below 3.6 V a cell is set "
                                          "aside and checked before it is charged",
                                 "notes": "P-F interval: a stored pack drains over months, not days, so a check "
                                          "every three months finds it before a cell reaches 3.0 V. By the "
                                          "calendar, not flight hours: the pack drains while it sits."}},
               ]},
              {"text": "Power lost in flight",
               "modes": [
                   {"text": "Internal cell short (thermal runaway)",
                    "cause": "Puncture or over-discharge", "effect_local": "The pack overheats",
                    "effect_next": "Power lost; fire risk", "effects": "Uncontrolled descent and a fire on the ground.",
                    "detection_method": "Cell-temperature alarm from the BMS (only once it is hot)",
                    "severity": 10, "occurrence": 2, "detection": 8,  # RPN 160, AP H
                    "action": "Puncture-resistant case; store at 50 % charge; charge in a fire-resistant bag",
                    "action_owner": "Safety lead", "action_due": "2026-11-25", "action_status": "in_progress",
                    "failure_rate": 3e-4, "mode_ratio": 0.05, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety", "decision": None,
                    "notes": "Still to decide, on purpose: the decision waits on the case redesign and the charging "
                             "trial."},
                   {"text": "Pack connector contacts wear and overheat",
                    "cause": "The spring contacts lose tension after hundreds of connections; resistance rises",
                    "effect_local": "The connector runs hot at the 60 A climb current",
                    "effect_next": "The contact arcs, then opens: power lost",
                    "effects": "Uncontrolled descent.",
                    "detection_method": "A hot connector by hand after a flight; a discoloured housing",
                    "severity": 10, "occurrence": 3, "detection": 5,  # RPN 150, AP M
                    "action": "Replace the pack connector every 200 cycles", "action_owner": "Electronics lead",
                    "action_due": "2026-12-10", "action_status": "open",
                    "failure_rate": 3e-4, "mode_ratio": 0.15, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "fixed_interval", "task": "Replace the pack connector", "interval": 200,
                                 "interval_unit": "cycles",
                                 "notes": "Scheduled discard: the contacts lose tension with every mating and the "
                                          "loss can't be seen. The supplier rates them at 500 matings; 200 cycles "
                                          "leaves a margin for the ones that run hot."}},
               ]},
          ]},
         {"text": "Stay in the bay through flight loads",
          "standards": [{"text": "The latch holds the pack at 5 g", "parameter": "Latch holding load", "comparator": ">=",
                         "value": 5, "unit": "g"}],
          "failures": [
              {"text": "The pack slides or falls out in flight", "standard": "The latch holds the pack at 5 g",
               "modes": [
                   {"text": "Bay latch worn and does not lock",
                    "cause": "The latch tab worn by hundreds of pack changes",
                    "effect_local": "The latch closes without locking",
                    "effect_next": "The pack slides back on a hard climb and the connector parts",
                    "effects": "Power lost in flight: uncontrolled descent.",
                    "detection_method": "Pre-flight pull test on the pack",
                    "severity": 10, "occurrence": 2, "detection": 2,  # RPN 40, AP L
                    "action": "A replaceable latch tab at rev D", "action_owner": "Airframe lead",
                    "action_due": "2027-02-01", "action_status": "open",
                    "failure_rate": 3e-4, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Battery pack: latched, with a pull test; the latch clicks home",
                                 "notes": "A worn latch is found by the pull test well before it lets go; it wears "
                                          "over hundreds of changes."}},
               ]},
          ]},
     ]},
    {"position": "Battery management (BMS)",
     "context": "The pack's management board: balances the cells on charge, reports the state of charge to the "
                "flight controller, and cuts off outside the safe window; passes up to 80 A.",
     "functions": [
         {"text": "Balance the cells and cut off outside the safe window",
          "standards": [
              {"text": "Cut off when any cell is below 3.0 V or above 4.25 V", "parameter": "Cell voltage",
               "comparator": "between", "value": "3.0-4.25", "unit": "V"},
              {"text": "Cells within 30 mV of each other at the end of charge", "parameter": "Cell spread at end of charge",
               "comparator": "<=", "value": 30, "unit": "mV"},
              {"text": "State of charge within 5 % of a measured discharge", "parameter": "State-of-charge error",
               "comparator": "<=", "value": 5, "unit": "%"},
          ],
          "failures": [
              {"text": "Does not cut off when a cell is outside its limits",
               "standard": "Cut off when any cell is below 3.0 V or above 4.25 V",
               "modes": [
                   {"text": "Cut-off relay welded closed",
                    "cause": "Inrush current when the pack is connected", "effect_local": "No protection",
                    "effect_next": "A cell can be over-discharged unnoticed",
                    "effects": "Pack damage, and a possible fire while charging.",
                    "detection_method": "None in normal use (hidden); a cut-off function test",
                    "severity": 8, "occurrence": 2, "detection": 9,  # RPN 144, AP M
                    "action": "Function test of the BMS cut-off every 160 flight hours; pre-charge resistor on the "
                              "connector",
                    "action_owner": "Electronics lead", "action_due": "2026-12-20", "action_status": "open",
                    "failure_rate": 5e-5, "mode_ratio": 0.4, "loss_probability": 0.5, "severity_class": "II",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding", "task": "Test the BMS cut-off with a bench supply",
                                 "interval": 160, "interval_unit": "hours",
                                 "notes": "Failure-finding on a hidden function: the interval comes from the "
                                          "failure-finding analysis (99.8 % availability of the cut-off at the "
                                          "relay's failure rate).",
                                 "evidence": {"type": "strategy_analysis", "id": UAV_BMS_ANALYSIS}}},
               ]},
              {"text": "Cells drift more than 30 mV apart",
               "standard": "Cells within 30 mV of each other at the end of charge",
               "modes": [
                   {"text": "Balancing circuit stops working",
                    "cause": "A balance resistor fails open",
                    "effect_local": "One cell is never bled down on charge",
                    "effect_next": "The high cell reaches 4.25 V first; the charge stops early; capacity falls",
                    "effects": "Shorter flights; a cell over-charged if the cut-off also fails.",
                    "detection_method": "The charger reports the cell spread at the end of every charge",
                    "severity": 6, "occurrence": 3, "detection": 2,  # RPN 36, AP L
                    "action": "Cell spread on the charging record", "action_owner": "Operations",
                    "action_due": "2026-11-12", "action_status": "done",
                    "failure_rate": 5e-5, "mode_ratio": 0.4, "loss_probability": 0.1, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "task": "Review the charger's cell-spread report",
                                 "interval": 10, "interval_unit": "cycles",
                                 "notes": "P-F interval: a dead balance resistor shows as a spread growing by a few "
                                          "millivolts a cycle; a look every 10 cycles finds it long before the 30 "
                                          "mV limit."}},
               ]},
              {"text": "Reports more charge than the pack has",
               "standard": "State of charge within 5 % of a measured discharge",
               "modes": [
                   {"text": "State-of-charge estimate drifts as the pack ages",
                    "cause": "The coulomb counter isn't re-learned as the capacity fades",
                    "effect_local": "The reported charge runs ahead of the real charge",
                    "effect_next": "The low-battery failsafe acts late",
                    "effects": "The pack reaches cut-off in the air: uncontrolled descent.",
                    "detection_method": "Hidden: only a measured discharge shows the error",
                    "severity": 10, "occurrence": 3, "detection": 8,  # RPN 240, AP H
                    "action": "Re-learn the capacity on a full discharge every 50 cycles",
                    "action_owner": "Electronics lead", "action_due": "2026-12-15", "action_status": "open",
                    "failure_rate": 5e-5, "mode_ratio": 0.2, "loss_probability": 0.5, "severity_class": "I",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding",
                                 "task": "Compare the reported state of charge with a measured discharge",
                                 "interval": 50, "interval_unit": "cycles",
                                 "notes": "Failure-finding on a hidden function: the error can't be seen in flight. "
                                          "The measured discharge every 50 cycles both finds the error and re-learns "
                                          "the capacity."}},
               ]},
          ]},
         {"text": "Pass up to 80 A to the aircraft without interruption",
          "standards": [{"text": "Carries 80 A continuously, and 120 A for 5 s", "parameter": "Continuous current",
                         "comparator": ">=", "value": 80, "unit": "A"}],
          "failures": [
              {"text": "Cuts off in flight without cause", "standard": "Carries 80 A continuously, and 120 A for 5 s",
               "modes": [
                   {"text": "Current sense trips on the motors' start-up spike",
                    "cause": "The trip set too fast for the spike when all four motors spool up",
                    "effect_local": "The relay opens for 50 ms",
                    "effect_next": "The flight controller browns out",
                    "effects": "Power lost in flight: uncontrolled descent.",
                    "detection_method": "The relay logs a trip; the arming spool-up would show it on the ground",
                    "severity": 10, "occurrence": 2, "detection": 6,  # RPN 120, AP M
                    "action": "Lengthen the trip's time constant in the board's firmware",
                    "action_owner": "Electronics lead", "action_due": "2026-12-20", "action_status": "in_progress",
                    "failure_rate": 5e-5, "mode_ratio": 0.2, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "redesign",
                                 "notes": "No task can prevent a spurious trip in flight: the trip's time constant "
                                          "is a firmware change, now in test."}},
               ]},
          ]},
     ]},
    {"position": "Power",
     "context": "One 6S 10 Ah lithium-polymer pack with its management board in the battery bay; 25 minutes a "
                "sortie with 20 % left; about 400 cycles a year across the operator's packs.",
     "functions": [
         {"text": "Power every system for the planned flight",
          "standards": [{"text": "25 minutes' flight per pack with 15 % charge left at landing",
                         "parameter": "Flight time per pack", "comparator": ">=", "value": 25, "unit": "min"}],
          "failures": [
              {"text": "Power lost in flight",
               "caused_by": [("Battery pack", "Power lost in flight"),
                             ("Battery pack", "The pack slides or falls out in flight"),
                             ("Battery management (BMS)", "Cuts off in flight without cause")]},
              {"text": "Flight shorter than planned",
               "standard": "25 minutes' flight per pack with 15 % charge left at landing",
               "caused_by": [("Battery pack", "Flight time on a full charge under 25 minutes")]},
          ]},
     ]},
    # ---- payload: the camera head and its gimbal ------------------------------------
    {"position": "Camera",
     "context": "A 4K camera and a 640×512 thermal imager in one head on the gimbal; records to a microSD card; "
                "10 mm per pixel at 30 m.",
     "functions": [
         {"text": "Record 4K video and a thermal picture of the conductors",
          "standards": [
              {"text": "Ground resolution of 10 mm per pixel or better at 30 m", "parameter": "Ground resolution",
               "comparator": "<=", "value": 10, "unit": "mm/pixel"},
              {"text": "Resolves a 5 °C hot spot at 30 m", "parameter": "Hot-spot contrast resolved", "comparator": "<=",
               "value": 5, "unit": "°C"},
              {"text": "Records the whole sortie without a gap", "parameter": "Recording gap", "comparator": "=",
               "value": 0, "unit": "s"},
          ],
          "failures": [
              {"text": "Image unusable", "standard": "Ground resolution of 10 mm per pixel or better at 30 m",
               "modes": [
                   {"text": "Lens fogs after a cold start",
                    "cause": "Condensation inside the housing when a cold camera meets warm, humid air",
                    "effect_local": "A soft, hazy picture for the first minutes",
                    "effect_next": "The first span's footage is unusable", "effects": "A span flown again.",
                    "detection_method": "The observer sees the haze in the live picture before take-off",
                    "severity": 4, "occurrence": 4, "detection": 2,  # RPN 32, AP L
                    "action": "Keep the camera in the warm vehicle until the pre-flight", "action_owner": "Operations",
                    "action_due": "2026-11-10", "action_status": "done",
                    "failure_rate": 8e-5, "mode_ratio": 0.3, "loss_probability": 0.05, "severity_class": "IV",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Camera: the live picture sharp and clear before take-off",
                                 "notes": "The pre-flight look at the live picture catches it; a fogged lens clears "
                                          "in minutes."}},
               ]},
              {"text": "Thermal picture drifts or is lost", "standard": "Resolves a 5 °C hot spot at 30 m",
               "modes": [
                   {"text": "Flat-field (shutter) calibration fails; the thermal image drifts",
                    "cause": "The shutter mechanism sticks",
                    "effect_local": "Fixed-pattern noise and a drifting temperature scale",
                    "effect_next": "Hot spots under 5 °C disappear into the noise",
                    "effects": "A hot connector missed: the inspection's main finding.",
                    "detection_method": "A thermal check against a hand at the pre-flight; the camera reports a "
                                        "shutter fault",
                    "severity": 6, "occurrence": 3, "detection": 3,  # RPN 54, AP L
                    "action": "Shutter cycled in the pre-flight thermal check", "action_owner": "Payload",
                    "action_due": "2026-11-15", "action_status": "done",
                    "failure_rate": 8e-5, "mode_ratio": 0.3, "loss_probability": 0.2, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Thermal: a hand in front of the imager shows as a clear hot shape and the "
                                          "shutter clicks",
                                 "notes": "A sticking shutter gets worse over days; the pre-flight check finds it "
                                          "before the sortie."}},
               ]},
              {"text": "No image recorded", "standard": "Records the whole sortie without a gap",
               "modes": [
                   {"text": "Memory card wears out and drops frames",
                    "cause": "Flash wear after hundreds of hours of 4K writes",
                    "effect_local": "Dropped frames, then write failures",
                    "effect_next": "Gaps in the recording",
                    "effects": "Spans re-flown; a gap found only at the review.",
                    "detection_method": "The camera reports dropped frames; the card's age",
                    "severity": 5, "occurrence": 4, "detection": 4,  # RPN 80, AP L
                    "action": "Replace the card every year", "action_owner": "Operations",
                    "action_due": "2026-11-10", "action_status": "done",
                    "failure_rate": 8e-5, "mode_ratio": 0.4, "loss_probability": 0.1, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "fixed_interval", "programme": "annual",
                                 "check": "Camera memory card: replace with a new approved card, formatted in the "
                                          "camera",
                                 "notes": "Scheduled discard: write endurance runs out with use and the first sign "
                                          "is dropped frames; a year's flying is well under the card's rating."}},
               ]},
          ]},
     ]},
    {"position": "Payload gimbal",
     "context": "Two-axis brushless gimbal under the centre body on four rubber damper balls; carries the camera "
                "head (4K and thermal, 240 g); holds the picture on the conductors in a 10 m/s wind.",
     "functions": [
         {"text": "Hold the camera steady on the target",
          "standards": [
              {"text": "Pointing held within 0.1° in a 10 m/s wind", "parameter": "Pointing error", "comparator": "<=",
               "value": 0.1, "unit": "°"},
              {"text": "Horizon level within 0.5°", "parameter": "Horizon tilt", "comparator": "<=", "value": 0.5,
               "unit": "°"},
          ],
          "failures": [
              {"text": "Camera not held on the target", "standard": "Pointing held within 0.1° in a 10 m/s wind",
               "modes": [
                   {"text": "Gimbal motor stalls on a snagged cable",
                    "cause": "Cable routing without a service loop", "effect_local": "The gimbal locks",
                    "effect_next": "Footage unusable", "effects": "The span is flown again.",
                    "detection_method": "Gimbal sweep before flight",
                    "severity": 3, "occurrence": 4, "detection": 2,  # RPN 24, AP L
                    "action": "Re-route the cable with a service loop", "action_owner": "Payload",
                    "action_due": "2026-11-05", "action_status": "done",
                    "failure_rate": 1e-4, "mode_ratio": 0.5, "loss_probability": 0.02, "severity_class": "IV",
                    "consequence": "non_operational",
                    "decision": {"outcome": "rtf", "rtf_basis": "uneconomic",
                                 "task": "Free the cable and fly the span again",
                                 "notes": "A stall costs a repeat flight, less than any task would; the cable now "
                                          "has a service loop. The replacement analysis finds no interval worth "
                                          "having: the gimbal motor's failures are random.",
                                 "evidence": {"type": "strategy_analysis", "id": UAV_GIMBAL_ANALYSIS}}},
                   {"text": "Damper balls perish and go hard",
                    "cause": "The rubber hardens with sun and age",
                    "effect_local": "Motor vibration reaches the camera",
                    "effect_next": "Rolling-shutter 'jello' in the video",
                    "effects": "Footage unusable; the span flown again.",
                    "detection_method": "Jello in the footage review; the balls hard to the touch",
                    "severity": 4, "occurrence": 5, "detection": 3,  # RPN 60, AP L
                    "action": "Replace the four damper balls every year", "action_owner": "Payload",
                    "action_due": "2026-11-30", "action_status": "open",
                    "failure_rate": 1e-4, "mode_ratio": 0.3, "loss_probability": 0.05, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "fixed_interval", "programme": "annual",
                                 "check": "Gimbal damper balls: replace all four",
                                 "notes": "Scheduled discard: the balls harden with age rather than use, so the "
                                          "annual inspection replaces them; cheaper than the re-flights."}},
               ]},
              {"text": "Horizon tilted more than 0.5°", "standard": "Horizon level within 0.5°",
               "modes": [
                   {"text": "Gimbal IMU calibration drifts",
                    "cause": "Temperature, and a knock in transport",
                    "effect_local": "The gimbal's level reference is off",
                    "effect_next": "Every frame tilted; distances misread",
                    "effects": "A tilted survey; the span measured again.",
                    "detection_method": "A tilted horizon in the live picture before take-off",
                    "severity": 3, "occurrence": 4, "detection": 2,  # RPN 24, AP L
                    "action": "Gimbal calibration at the 25-hour inspection", "action_owner": "Payload",
                    "action_due": "2026-11-15", "action_status": "done",
                    "failure_rate": 1e-4, "mode_ratio": 0.2, "loss_probability": 0.05, "severity_class": "IV",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "25h",
                                 "check": "Gimbal: level the horizon against a reference; recalibrate the gimbal IMU "
                                          "if off by more than 0.5°",
                                 "notes": "P-F interval: the drift is slow (a degree over months); the 25-hour check "
                                          "keeps it inside 0.5°."}},
               ]},
          ]},
         {"text": "Deliver a usable picture of the target",
          "failures": [
              {"text": "No usable picture of the target",
               "caused_by": [("Camera", "Image unusable"), ("Camera", "Thermal picture drifts or is lost"),
                             ("Camera", "No image recorded")]},
          ]},
     ]},
    # ---- comms ------------------------------------------------------------------------
    {"position": "Comms link",
     "context": "A 2.4 GHz control and telemetry radio and a 5.8 GHz video transmitter in the centre body, "
                "antennas under the arms; 2 km range in line of sight; the ground station shows the link quality.",
     "functions": [
         {"text": "Carry control and telemetry between the aircraft and the ground station",
          "standards": [
              {"text": "Range of at least 2 km in line of sight", "parameter": "Range", "comparator": ">=", "value": 2,
               "unit": "km"},
              {"text": "Packet loss under 1 % at 2 km", "parameter": "Packet loss", "comparator": "<=", "value": 1,
               "unit": "%"},
          ],
          "failures": [
              {"text": "Link lost inside 2 km", "standard": "Range of at least 2 km in line of sight",
               "modes": [
                   {"text": "Link lost behind terrain or to interference",
                    "cause": "Flying out of line of sight", "effect_local": "No control input",
                    "effect_next": "Failsafe return-to-home",
                    "effects": "Mission aborted; a safe landing if return-to-home works.",
                    "detection_method": "Signal strength shown on the ground station",
                    "severity": 6, "occurrence": 5, "detection": 2,  # RPN 60, AP L
                    "action": "Geofence on signal strength; pilot training", "action_owner": "Operations",
                    "action_due": "2026-11-08", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.5, "loss_probability": 0.1, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "redesign",
                                 "notes": "A geofence on signal strength in the firmware, and pilots trained to keep "
                                          "line of sight: no maintenance task helps."}},
                   {"text": "Antenna cable chafes through where it passes the arm root",
                    "cause": "The cable rubs on the arm clamp as the arm folds",
                    "effect_local": "Signal strength drops; then no link",
                    "effect_next": "Return-to-home on link loss",
                    "effects": "A sortie aborted; a fly-away if return-to-home also fails.",
                    "detection_method": "Signal strength in the log falls over weeks; the cable is inspected at 25 "
                                        "hours",
                    "severity": 6, "occurrence": 3, "detection": 3,  # RPN 54, AP L
                    "action": "A cable sleeve at the arm root", "action_owner": "Electronics lead",
                    "action_due": "2026-11-25", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.1, "loss_probability": 0.1, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "25h",
                                 "check": "Antenna cables at the arm roots: no chafe through the sleeve; connectors "
                                          "tight",
                                 "notes": "P-F interval: the sleeve wears through over tens of hours before the braid "
                                          "does; 25 hours catches it."}},
                   {"text": "Radio module fails (electronic)",
                    "cause": "Random component failure", "effect_local": "No link",
                    "effect_next": "Return-to-home", "effects": "A sortie aborted.",
                    "detection_method": "Link quality on the ground station",
                    "severity": 6, "occurrence": 2, "detection": 2,  # RPN 24, AP L
                    "action": "None: a spare radio in the field kit", "action_owner": "Operations",
                    "action_due": "2026-11-10", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.2, "loss_probability": 0.1, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "rtf", "rtf_basis": "random", "task": "Replace the radio when it fails",
                                 "notes": "Run to failure: the avionics boards' failures fit an exponential, so no "
                                          "age-based task helps; return-to-home covers the flight and a spare "
                                          "covers the day.",
                                 "evidence": {"type": "model", "id": UAV_AVIONICS_MODEL}}},
               ]},
              {"text": "Packets dropped above 1 %", "standard": "Packet loss under 1 % at 2 km",
               "modes": [
                   {"text": "Radio overheats in the sun while the aircraft waits on the pad",
                    "cause": "A black centre body in 40 °C sun; the radio derates above 70 °C",
                    "effect_local": "Packet loss climbs; range drops",
                    "effect_next": "Jerky control; a return-to-home if it worsens",
                    "effects": "A sortie delayed or aborted.",
                    "detection_method": "Link quality on the ground station before take-off",
                    "severity": 5, "occurrence": 4, "detection": 2,  # RPN 40, AP L
                    "action": "Shade the aircraft between sorties (field procedure)", "action_owner": "Operations",
                    "action_due": "2026-11-08", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.1, "loss_probability": 0.05, "severity_class": "IV",
                    "consequence": "operational",
                    "decision": {"outcome": "accept",
                                 "notes": "Accepted: a field rule (shade between sorties) and the link-quality check "
                                          "before take-off cover it; there is nothing to maintain."}},
               ]},
          ]},
         {"text": "Send the live picture to the observer",
          "standards": [{"text": "Live picture latency under 300 ms at 2 km", "parameter": "Latency", "comparator": "<=",
                         "value": 300, "unit": "ms"}],
          "failures": [
              {"text": "No live picture, or it freezes", "standard": "Live picture latency under 300 ms at 2 km",
               "modes": [
                   {"text": "Video transmitter drops to its low rate on interference",
                    "cause": "Other 5.8 GHz users near a town",
                    "effect_local": "The picture freezes or pixelates",
                    "effect_next": "The observer can't see the line; the pilot pauses",
                    "effects": "A slower sortie; the recording on the camera is unaffected.",
                    "detection_method": "The observer sees it at once",
                    "severity": 3, "occurrence": 5, "detection": 1,  # RPN 15, AP L
                    "action": "A channel scan before each day's flying", "action_owner": "Operations",
                    "action_due": "2026-11-08", "action_status": "done",
                    "failure_rate": 2e-4, "mode_ratio": 0.1, "loss_probability": 0.02, "severity_class": "IV",
                    "consequence": "operational",
                    "decision": {"outcome": "accept",
                                 "notes": "Accepted: the recording isn't affected and the observer calls a pause; "
                                          "the channel scan is a field rule."}},
               ]},
          ]},
     ]},
    # ---- flight control: GPS, compass, the IMUs and the controller ------------------
    {"position": "GPS receiver",
     "context": "Multi-constellation receiver on a mast above the centre body; position hold needs 12 satellites, "
                "and the arming check refuses take-off with fewer.",
     "functions": [
         {"text": "Give the aircraft's position",
          "standards": [
              {"text": "Horizontal position within 2 m", "parameter": "Horizontal error", "comparator": "<=", "value": 2,
               "unit": "m"},
              {"text": "A fix with at least 12 satellites before take-off", "parameter": "Satellites in the fix",
               "comparator": ">=", "value": 12},
          ],
          "failures": [
              {"text": "Position error over 2 m, or no fix", "standard": "Horizontal position within 2 m",
               "modes": [
                   {"text": "Antenna connector works loose",
                    "cause": "Vibration", "effect_local": "The position fix is lost",
                    "effect_next": "Position hold fails; the aircraft drifts in wind",
                    "effects": "Fly-away risk; a geofence breach.",
                    "detection_method": "Satellite count in the pre-flight check",
                    "severity": 8, "occurrence": 3, "detection": 2,  # RPN 48, AP L
                    "action": "Locking connector; satellite count on the pre-flight checklist", "action_owner": "Production",
                    "action_due": "2026-11-12", "action_status": "done",
                    "failure_rate": 5e-5, "mode_ratio": 0.5, "loss_probability": 0.4, "severity_class": "II",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "GPS: at least 12 satellites and a 3D fix before take-off",
                                 "notes": "A loosening connector drops satellites for flights before the fix goes; "
                                          "the count before each flight is the warning."}},
               ]},
              {"text": "Fewer than 12 satellites at arming",
               "standard": "A fix with at least 12 satellites before take-off",
               "modes": [
                   {"text": "Too few satellites in the fix near steel structures (multipath)",
                    "cause": "Reflections from a steel pole or a substation beside the pad",
                    "effect_local": "Satellites drop in and out; the fix is poor",
                    "effect_next": "The arming check refuses take-off; the crew waits or moves the pad",
                    "effects": "A delayed sortie.", "detection_method": "The arming check",
                    "severity": 3, "occurrence": 5, "detection": 1,  # RPN 15, AP L
                    "action": "Pads chosen 20 m clear of steel in the site survey", "action_owner": "Operations",
                    "action_due": "2026-11-10", "action_status": "done",
                    "failure_rate": 5e-5, "mode_ratio": 0.5, "loss_probability": 0.02, "severity_class": "IV",
                    "consequence": "operational",
                    "decision": {"outcome": "accept",
                                 "notes": "Accepted: the arming check already refuses a poor fix, the cost is a "
                                          "wait, and no maintenance task changes where the satellites are. The site "
                                          "survey keeps the pad clear of steel."}},
               ]},
          ]},
     ]},
    {"position": "Compass",
     "context": "A magnetometer in the GPS mast, away from the power leads; calibrated after any change to the "
                "aircraft's metal or current paths.",
     "functions": [
         {"text": "Give the aircraft's heading",
          "standards": [{"text": "Heading within 5° of true", "parameter": "Heading error", "comparator": "<=", "value": 5,
                         "unit": "°"}],
          "failures": [
              {"text": "Heading error over 5°", "standard": "Heading within 5° of true",
               "modes": [
                   {"text": "Magnetometer disturbed by the field around the conductors",
                    "cause": "The magnetic field of the line current, strongest close to the conductors",
                    "effect_local": "Heading swings as the aircraft nears the line",
                    "effect_next": "Position hold circles; the track wanders",
                    "effects": "A sortie flown off line; a strike in the worst case.",
                    "detection_method": "The flight controller flags a compass–GPS heading disagreement",
                    "severity": 7, "occurrence": 3, "detection": 4,  # RPN 84, AP L
                    "action": "Firmware falls back to GPS heading on a disagreement; keep 30 m above the conductors",
                    "action_owner": "Software lead", "action_due": "2026-12-20", "action_status": "in_progress",
                    "failure_rate": 3e-5, "mode_ratio": 0.6, "loss_probability": 0.3, "severity_class": "II",
                    "consequence": "operational",
                    "decision": {"outcome": "redesign",
                                 "notes": "No task helps: the field is the line's. The fix is the firmware's "
                                          "fallback to GPS heading when the compass disagrees, and the 30 m "
                                          "standoff in the operating context."}},
                   {"text": "Calibration lost after a motor, arm or payload change",
                    "cause": "Any change to the aircraft's metal or current paths shifts the compass offsets",
                    "effect_local": "A heading offset of 10° or more",
                    "effect_next": "Position hold drifts; the arming check may refuse",
                    "effects": "A delayed sortie, or one flown off line.",
                    "detection_method": "Compass health in the arming check",
                    "severity": 6, "occurrence": 4, "detection": 2,  # RPN 48, AP L
                    "action": "Compass calibration written into every change procedure", "action_owner": "Production",
                    "action_due": "2026-11-15", "action_status": "done",
                    "failure_rate": 3e-5, "mode_ratio": 0.4, "loss_probability": 0.2, "severity_class": "III",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Compass: health passes at arming; calibrate after any motor, arm or "
                                          "payload change",
                                 "notes": "The arming check catches a bad calibration before the sortie; the "
                                          "calibration itself is part of the change procedure, not a scheduled "
                                          "task."}},
               ]},
          ]},
     ]},
    {"position": "IMU",
     "context": "One of two inertial units on the flight controller board; the controller flies on the better one "
                "and compares them at arming.",
     "functions": [
         {"text": "Measure angular rate and acceleration",
          "standards": [{"text": "Gyro bias under 0.5 °/s after a 2-minute warm-up", "parameter": "Gyro bias",
                         "comparator": "<=", "value": 0.5, "unit": "°/s"}],
          "failures": [
              {"text": "Readings drift or freeze", "standard": "Gyro bias under 0.5 °/s after a 2-minute warm-up",
               "modes": [
                   {"text": "Gyro bias drifts with temperature",
                    "cause": "No temperature compensation after a sensor change",
                    "effect_local": "The attitude estimate drifts", "effect_next": "The controller fights a false tilt",
                    "effects": "Oscillation and a hard landing.",
                    "detection_method": "Gyro calibration in the arming check, after warm-up",
                    "severity": 7, "occurrence": 4, "detection": 3,  # RPN 84, AP M
                    "action": "Temperature calibration in the production test", "action_owner": "Production",
                    "action_due": "2026-12-12", "action_status": "open",
                    "failure_rate": 4e-5, "mode_ratio": 0.6, "loss_probability": 0.3, "severity_class": "II",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Gyros: the arming check's calibration passes after a 2-minute warm-up",
                                 "notes": "The arming check measures the bias every time; a drifting gyro fails it "
                                          "before the sortie."}},
               ]},
              {"text": "No usable reading",
               "modes": [
                   {"text": "Fails silently while the other IMU carries on",
                    "cause": "A solder joint cracks from vibration", "effect_local": "This IMU's readings stop",
                    "effect_next": "The flight controller uses the other IMU; nothing tells the pilot",
                    "effects": "No backup left: the next IMU failure loses attitude control.",
                    "detection_method": "None in flight (hidden); the arming self-test compares both IMUs",
                    "severity": 8, "occurrence": 3, "detection": 8,  # RPN 192, AP M
                    "action": "Show an IMU disagreement in the arming checks", "action_owner": "Software lead",
                    "action_due": "2026-12-12", "action_status": "open",
                    "failure_rate": 4e-5, "mode_ratio": 0.4, "loss_probability": 0.5, "severity_class": "II",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding", "task": "Compare both IMUs in the arming self-test log",
                                 "interval": 10, "interval_unit": "hours",
                                 "notes": "Failure-finding: the arming self-test writes both IMUs' readings to the "
                                          "log, and the 10-hour review compares them, so a dead IMU is found within "
                                          "a week of flying rather than at the next failure."}},
               ]},
          ]},
     ]},
    {"position": "Flight controller",
     "context": "Runs the 400 Hz attitude loop, the position controller and the failsafes (return-to-home, "
                "low-battery land, the geofence and the height limit); barometer behind a foam port; logs at 10 Hz "
                "to a microSD card; configuration loaded from the mission planner before each day's flying.",
     "functions": [
         {"text": "Hold the commanded attitude and position",
          "standards": [
              {"text": "Attitude within 2° of the command in a 10 m/s wind", "parameter": "Attitude error",
               "comparator": "<=", "value": 2, "unit": "°"},
              {"text": "Height held within 0.5 m over a 25-minute sortie", "parameter": "Height drift",
               "comparator": "<=", "value": 0.5, "unit": "m"},
          ],
          "failures": [
              {"text": "Loses attitude control", "standard": "Attitude within 2° of the command in a 10 m/s wind",
               "modes": [
                   {"text": "Firmware lock-up (watchdog reset in flight)",
                    "cause": "A software fault under a high logging load",
                    "effect_local": "The control loop stops for about a second", "effect_next": "Attitude diverges",
                    "effects": "Uncontrolled descent.", "detection_method": "Log review for watchdog events",
                    "severity": 10, "occurrence": 2, "detection": 6,  # RPN 120, AP M
                    "action": "Reduce the log rate; add watchdog events to the log review",
                    "action_owner": "Software lead", "action_due": "2026-11-18", "action_status": "in_progress",
                    "failure_rate": 1e-5, "mode_ratio": 0.3, "loss_probability": 0.9, "severity_class": "I",
                    "consequence": "safety",
                    "decision": {"outcome": "redesign", "notes": "A software change; no maintenance task helps."}},
               ]},
              {"text": "Height drifts more than 0.5 m", "standard": "Height held within 0.5 m over a 25-minute sortie",
               "modes": [
                   {"text": "Barometer port blocked by dust, or the foam cover missing",
                    "cause": "Dust from gravel pads; the foam cover left off after a board change",
                    "effect_local": "The pressure reading is noisy and wind-affected",
                    "effect_next": "Height hold wanders in gusts; the aircraft sinks toward the conductors",
                    "effects": "A sortie flown off height; a strike on the line in the worst case.",
                    "detection_method": "Pre-flight hover at 2 m: the height holds within 0.2 m; the arming check "
                                        "reports barometer noise",
                    "severity": 8, "occurrence": 3, "detection": 3,  # RPN 72, AP L
                    "action": "Add the foam cover to the board-change checklist",
                    "action_owner": "Software lead", "action_due": "2026-11-25", "action_status": "done",
                    "failure_rate": 1e-5, "mode_ratio": 0.2, "loss_probability": 0.3, "severity_class": "II",
                    "consequence": "operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Hover at 2 m before the sortie: the height holds within 0.2 m; no "
                                          "barometer warning at arming",
                                 "notes": "Dust builds up over days, not minutes: the pre-flight hover shows it as a "
                                          "wandering height before the sortie."}},
               ]},
          ]},
         {"text": "Return home and land when the link is lost or the pack is low",
          "standards": [
              {"text": "Return-to-home starts within 3 s of losing the link", "parameter": "Time to return-to-home",
               "comparator": "<=", "value": 3, "unit": "s"},
              {"text": "Lands with at least 15 % charge left in the pack", "parameter": "Charge at landing",
               "comparator": ">=", "value": 15, "unit": "%"},
          ],
          "failures": [
              {"text": "Does not return home when the link is lost",
               "standard": "Return-to-home starts within 3 s of losing the link",
               "modes": [
                   {"text": "Link-loss failsafe left at 'continue' after a firmware update",
                    "cause": "A firmware update resets the failsafe to its default and nobody checks",
                    "effect_local": "No action on link loss",
                    "effect_next": "The aircraft flies on, out of control range",
                    "effects": "A fly-away: the aircraft is lost, and may come down on people or the line.",
                    "detection_method": "None in normal flying (hidden): only a deliberate link-loss test shows it",
                    "severity": 10, "occurrence": 2, "detection": 9,  # RPN 180, AP H
                    "action": "Failsafe test after every firmware update and every month",
                    "action_owner": "Software lead", "action_due": "2026-11-15", "action_status": "done",
                    "failure_rate": 1e-5, "mode_ratio": 0.15, "loss_probability": 0.8, "severity_class": "I",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding", "programme": "failsafe",
                                 "check": "Link loss: switch the transmitter off in a hover at 3 m over the pad; "
                                          "the aircraft returns and lands within 3 s of the loss",
                                 "notes": "Failure-finding on a hidden function, tested every month (about 12 "
                                          "flight hours) and after any firmware change. By the calendar, not flight "
                                          "hours: a configuration change defeats it, not flying."}},
               ]},
              {"text": "Does not land before the pack runs out",
               "standard": "Lands with at least 15 % charge left in the pack",
               "modes": [
                   {"text": "Low-battery threshold set below the pack's safe voltage",
                    "cause": "Threshold left at the default (3.3 V a cell) instead of the 20 % charge the mission needs",
                    "effect_local": "The low-battery action comes too late",
                    "effect_next": "The pack reaches cut-off in the air",
                    "effects": "Power lost in flight: uncontrolled descent.",
                    "detection_method": "None in normal flying (hidden); the configuration check and the bench test "
                                        "show it",
                    "severity": 10, "occurrence": 2, "detection": 8,  # RPN 160, AP H
                    "action": "Lock the threshold in the operator's configuration file",
                    "action_owner": "Software lead", "action_due": "2026-12-05", "action_status": "in_progress",
                    "failure_rate": 1e-5, "mode_ratio": 0.1, "loss_probability": 1.0, "severity_class": "I",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding", "programme": "failsafe",
                                 "check": "Low battery: on the bench supply, bring the pack voltage down to the 20 % "
                                          "point; the land warning and the landing come within 3 s",
                                 "notes": "Failure-finding on a hidden function; done with the link-loss test "
                                          "every month."}},
               ]},
          ]},
         {"text": "Hold the aircraft inside the geofence and under the height limit",
          "standards": [
              {"text": "Stops at the corridor boundary", "parameter": "Distance outside the geofence", "comparator": "=",
               "value": 0, "unit": "m"},
              {"text": "Never above 120 m above ground", "parameter": "Height above ground", "comparator": "<=",
               "value": 120, "unit": "m"},
          ],
          "failures": [
              {"text": "Flies through the corridor boundary", "standard": "Stops at the corridor boundary",
               "modes": [
                   {"text": "Geofence not loaded for the day's corridor",
                    "cause": "The corridor polygon export skipped in the mission planner; the aircraft flies with "
                             "last month's fence, or none",
                    "effect_local": "No fence, or the wrong one",
                    "effect_next": "A pilot's error isn't caught",
                    "effects": "A flight outside the permitted corridor: a breach of the operator's permission.",
                    "detection_method": "Hidden until the aircraft reaches the boundary; the fence test shows it",
                    "severity": 8, "occurrence": 3, "detection": 8,  # RPN 192, AP M
                    "action": "The planner refuses to arm without today's fence (software change requested)",
                    "action_owner": "Operations", "action_due": "2027-01-15", "action_status": "open",
                    "failure_rate": 1e-5, "mode_ratio": 0.1, "loss_probability": 0.2, "severity_class": "II",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding", "programme": "failsafe",
                                 "check": "Geofence: fly at the boundary at 10 m; the aircraft stops and holds at "
                                          "the fence",
                                 "notes": "Failure-finding on a hidden function. The fence is also confirmed on the "
                                          "planner's screen each morning, but only the flight test proves it is "
                                          "loaded in the aircraft."}},
               ]},
              {"text": "Climbs above 120 m", "standard": "Never above 120 m above ground",
               "modes": [
                   {"text": "Height limit referenced to sea level, not the ground",
                    "cause": "The limit entered as 'above mean sea level' on a site 150 m above the sea",
                    "effect_local": "The limit never acts",
                    "effect_next": "A climb to clear a tall structure can pass 120 m above ground",
                    "effects": "A breach of the height permission; conflict with low-flying aircraft.",
                    "detection_method": "Hidden; the climb test shows it",
                    "severity": 8, "occurrence": 2, "detection": 8,  # RPN 128, AP M
                    "action": "Reference fixed to 'above take-off' in the operator's configuration",
                    "action_owner": "Software lead", "action_due": "2026-11-30", "action_status": "done",
                    "failure_rate": 1e-5, "mode_ratio": 0.1, "loss_probability": 0.2, "severity_class": "II",
                    "consequence": "safety", "hidden": True,
                    "decision": {"outcome": "failure_finding", "programme": "failsafe",
                                 "check": "Height limit: climb over the pad; the aircraft stops at 120 m above "
                                          "take-off",
                                 "notes": "Failure-finding, with the other failsafe tests every month."}},
               ]},
          ]},
         {"text": "Record every flight for the log review",
          "standards": [{"text": "Every flight logged at 10 Hz from arming to disarming", "parameter": "Log rate",
                         "comparator": ">=", "value": 10, "unit": "Hz"}],
          "failures": [
              {"text": "No flight log recorded", "standard": "Every flight logged at 10 Hz from arming to disarming",
               "modes": [
                   {"text": "Log card full or corrupted",
                    "cause": "The microSD card fills, or a write fails on a cheap card",
                    "effect_local": "No log, or one that won't open",
                    "effect_next": "The 10-hour review has nothing to read; a watchdog event or dropout goes unseen",
                    "effects": "A fault found later than it should be; no evidence after an incident.",
                    "detection_method": "The arming check reports the card's free space; the last log opens on the "
                                        "planner",
                    "severity": 5, "occurrence": 4, "detection": 2,  # RPN 40, AP L
                    "action": "Use the approved card; replace it yearly", "action_owner": "Operations",
                    "action_due": "2026-11-10", "action_status": "done",
                    "failure_rate": 1e-5, "mode_ratio": 0.15, "loss_probability": 0.05, "severity_class": "IV",
                    "consequence": "non_operational",
                    "decision": {"outcome": "on_condition", "programme": "pre_flight",
                                 "check": "Flight log: the card has space for the day; the last flight's log opens "
                                          "on the planner",
                                 "notes": "A full card shows at arming; the look before each flight costs nothing."}},
               ]},
          ]},
     ]},
    {"position": "Flight control",
     "context": "A flight controller running the 400 Hz attitude loop and the position controller, two IMUs it "
                "compares at arming, a GPS receiver and a compass; the failsafes run in the controller.",
     "functions": [
         {"text": "Keep the aircraft stable and on its planned path",
          "standards": [
              {"text": "Attitude within 2° of the command in a 10 m/s wind", "parameter": "Attitude error",
               "comparator": "<=", "value": 2, "unit": "°"},
              {"text": "Position within 1.5 m of the planned track", "parameter": "Track error", "comparator": "<=",
               "value": 1.5, "unit": "m"},
          ],
          "failures": [
              {"text": "Loses control of attitude or position",
               "standard": "Attitude within 2° of the command in a 10 m/s wind",
               "caused_by": [("Flight controller", "Loses attitude control"), ("IMU", "Readings drift or freeze")]},
              {"text": "Height or position held outside its limits",
               "standard": "Position within 1.5 m of the planned track",
               "caused_by": [("Flight controller", "Height drifts more than 0.5 m"),
                             ("GPS receiver", "Position error over 2 m, or no fix"), ("Compass", "Heading error over 5°")]},
          ]},
         {"text": "Act for the pilot when the link, the pack or the boundary demands it",
          "standards": [{"text": "Each failsafe acts within 3 s of its trigger", "parameter": "Failsafe response time",
                         "comparator": "<=", "value": 3, "unit": "s"}],
          "failures": [
              {"text": "A failsafe does not act when it should",
               "standard": "Each failsafe acts within 3 s of its trigger",
               "caused_by": [("Flight controller", "Does not return home when the link is lost"),
                             ("Flight controller", "Does not land before the pack runs out"),
                             ("Flight controller", "Flies through the corridor boundary"),
                             ("Flight controller", "Climbs above 120 m")]},
          ]},
     ]},
    # ---- the aircraft: the mission's functions, explained by everything below --------
    {"position": "", "context": SAMPLE_PRODUCT_CONTEXT,
     "functions": [
         {"text": "Fly the planned inspection sortie and land back on the pad",
          "standards": [
              {"text": "A sortie of up to 25 minutes on one battery pack", "parameter": "Sortie length", "comparator": ">=",
               "value": 25, "unit": "min"},
              {"text": "Holds 30 m above the conductors, within 5 m, at 5 m/s", "parameter": "Height above the conductors",
               "comparator": "between", "value": "25-35", "unit": "m"},
          ],
          "failures": [
              {"text": "Aircraft lost or crashes",
               "caused_by": [("Airframe", "A structural member cracks or separates in flight"),
                             ("Propulsion", "Thrust lost or reduced on an arm"),
                             ("Flight control", "Loses control of attitude or position"),
                             ("Power", "Power lost in flight")]},
              {"text": "Aircraft damaged on landing",
               "caused_by": [("Airframe", "The aircraft tips over or is damaged on landing")]},
              {"text": "Sortie cut short", "standard": "A sortie of up to 25 minutes on one battery pack",
               "caused_by": [("Power", "Flight shorter than planned"), ("Comms link", "Link lost inside 2 km")]},
              {"text": "Off the corridor height or line",
               "standard": "Holds 30 m above the conductors, within 5 m, at 5 m/s",
               "caused_by": [("Flight control", "Height or position held outside its limits")]},
          ]},
         {"text": "Record usable imagery of every span, pole and fitting on the feeder",
          "standards": [
              {"text": "Ground resolution of 10 mm per pixel or better at 30 m", "parameter": "Ground resolution",
               "comparator": "<=", "value": 10, "unit": "mm/pixel"},
              {"text": "A 5 °C hot spot on a connector resolved at 30 m", "parameter": "Hot-spot contrast resolved",
               "comparator": "<=", "value": 5, "unit": "°C"},
              {"text": "The 12 km feeder covered in no more than 8 sorties", "parameter": "Sorties per inspection",
               "comparator": "<=", "value": 8, "unit": "sorties"},
          ],
          "failures": [
              {"text": "Imagery unusable or missing for part of the feeder",
               "standard": "Ground resolution of 10 mm per pixel or better at 30 m",
               "caused_by": [("Payload gimbal", "No usable picture of the target"),
                             ("Payload gimbal", "Camera not held on the target")]},
              {"text": "Hot spots missed", "standard": "A 5 °C hot spot on a connector resolved at 30 m",
               "caused_by": [("Camera", "Thermal picture drifts or is lost")]},
              {"text": "More than 8 sorties to cover the feeder",
               "standard": "The 12 km feeder covered in no more than 8 sorties",
               "caused_by": [("Power", "Flight shorter than planned"),
                             ("Payload gimbal", "No usable picture of the target")]},
          ]},
         {"text": "Keep clear of people, property and the line",
          "standards": [
              {"text": "Inside the geofence and under 120 m above ground at all times", "parameter": "Height above ground",
               "comparator": "<=", "value": 120, "unit": "m"},
              {"text": "Return-to-home within 3 s of losing the link or reaching 20 % charge",
               "parameter": "Time to return-to-home", "comparator": "<=", "value": 3, "unit": "s"},
          ],
          "failures": [
              {"text": "Flies outside the geofence or above 120 m",
               "standard": "Inside the geofence and under 120 m above ground at all times",
               "caused_by": [("Flight control", "A failsafe does not act when it should")]},
              {"text": "Does not return home when the link is lost or the pack is low",
               "standard": "Return-to-home within 3 s of losing the link or reaching 20 % charge",
               "caused_by": [("Flight control", "A failsafe does not act when it should"),
                             ("Battery management (BMS)", "Reports more charge than the pack has")]},
          ]},
     ]},
]


def sample_uav_rcm() -> list[dict]:
    """The sample quadcopter's RCM, a fresh copy each time (callers may change it)."""
    return copy.deepcopy(SAMPLE_UAV_RCM)


def _decision_for(decision: dict, programme: dict[str, str]) -> tuple[dict, str | None]:
    """A template mode's decision as the service takes it, and the shared task it
    joins (its id), if any: a decision naming a programme task carries that task's
    name and interval, so the task stays one act for every mode it serves."""
    if not decision.get("programme"):
        return decision, None
    spec = SAMPLE_UAV_PROGRAMME[decision["programme"]]
    given = {k: v for k, v in decision.items() if k not in ("programme", "check")}
    given |= {"task": spec["name"], "interval": spec["interval"], "interval_unit": spec["unit"]}
    return given, programme[decision["programme"]]


def _add_uav_rcm(m, at_of: dict[str, list[str]], counts: dict) -> dict[str, str]:
    """The sample quadcopter's RCM on every position a template name maps to (at_of:
    name -> position ids; "" is the product itself): the maintenance programme's
    shared tasks on the product, then, position by position, its operating context,
    each function with its performance standards, its functional failures (breaching
    a standard where the template says so, linked to the lower failures that cause
    them), and each failure mode scored, with its consequence, decision and notes. A
    decision that names a programme task joins it and adds its line to the task's
    checklist."""
    pid = at_of[""][0]
    programme: dict[str, str] = {}
    checks: dict[str, list[str]] = {}
    for key, spec in SAMPLE_UAV_PROGRAMME.items():
        task = m.create_task(pid, spec["name"], spec["interval"], unit=spec["unit"], outcome=spec["outcome"],
                             instructions=spec["instructions"])
        programme[key], checks[key] = task["id"], []
        counts["tasks"] += 1
    ffs: dict[tuple[str, str], str] = {}
    for entry in sample_uav_rcm():
        for at in at_of[entry["position"]]:
            if entry.get("context"):
                m.update_position(at, operating_context=entry["context"])
            for fn in entry["functions"]:
                function = m.add_function(at, fn["text"])
                counts["functions"] += 1
                standards = {st["text"]: m.add_standard(function["id"], **st)["id"] for st in fn.get("standards") or []}
                counts["standards"] += len(standards)
                for failure in fn["failures"]:
                    breach = failure.get("standard")
                    ff = m.add_functional_failure(function["id"], failure["text"],
                                                  standard_id=standards[breach] if breach else None)
                    ffs[(at, failure["text"])] = ff["id"]
                    counts["functional_failures"] += 1
                    for below, text in failure.get("caused_by") or []:
                        for cause_at in at_of[below]:
                            m.link_cause(ff["id"], ffs[(cause_at, text)])
                            counts["causes_linked"] += 1
                    for mode in failure.get("modes") or []:
                        fm = m.add_failure_mode(at, mode["text"], functional_failure_id=ff["id"])
                        counts["failure_modes"] += 1
                        if mode.get("effects") or mode.get("notes"):
                            m.update_failure_mode(fm["id"], effects=mode.get("effects"), notes=mode.get("notes"))
                        m.score_failure_mode(fm["id"], _scores(mode, SAMPLE_UAV_BASIS))
                        counts["scored"] += 1
                        if not mode.get("decision"):
                            m.decide_failure_mode(fm["id"], consequence=mode.get("consequence"),
                                                  hidden=mode.get("hidden", ...))
                            continue
                        decision, task_id = _decision_for(mode["decision"], programme)
                        # strict=False: one sample keeps a legacy decision the diagram now refuses, to show
                        # the evidence check and the advice that flags it.
                        m.decide_failure_mode(fm["id"], consequence=mode.get("consequence"), decision=decision,
                                              task_id=task_id, hidden=mode.get("hidden", ...), strict=False)
                        counts["decisions"] += 1
                        if task_id:
                            check = mode["decision"]["check"]
                            if check not in checks[mode["decision"]["programme"]]:
                                checks[mode["decision"]["programme"]].append(check)
                        elif decision["outcome"] in ("on_condition", "fixed_interval", "failure_finding") \
                                and decision.get("interval"):
                            counts["tasks"] += 1
    # Each programme task's checklist is what its failure modes ask for, in the order
    # the RCM reads; its kind is the programme's, whatever mode joined it first.
    for key, tid in programme.items():
        m.update_task(tid, checklist=checks[key], outcome=SAMPLE_UAV_PROGRAMME[key]["outcome"])
    return programme


def _add_uav_lsa(m, programme: dict[str, str], counts: dict) -> None:
    """Each programme task's LSA record (task.resources_set), its spares named by part
    number taken from the parts register."""
    for key, record in SAMPLE_UAV_LSA.items():
        given = dict(record)
        if record.get("spares"):
            given["spares"] = [{"part_id": _part(m, line["part_number"], "")["id"], "qty": line["qty"]}
                               if line.get("part_number") else line for line in record["spares"]]
        m.set_task_resources(programme[key], given)
        counts["lsa_records"] += 1


def _add_uav_models(m, at_of: dict[str, list[str]], counts: dict) -> None:
    """The life models on the design's positions, each for the failure mode it describes."""
    for name, model_id, model_name, mode_text, note in SAMPLE_PRODUCT_MODELS:
        for at in at_of[name]:
            modes = [fm["id"] for fm in m._modes_on(at) if fm.get("text") == mode_text]
            m.link_position_model(at, "model", model_id, failure_mode_ids=modes, name=model_name, note=note)
            counts["models_linked"] += 1


def _add_uav_package(m, top_id: str) -> dict:
    """The calendar tasks on a built item, packaged into one monthly visit."""
    spec = SAMPLE_UAV_PACKAGE
    tasks = {t["name"]: t["id"] for t in m.s.inn(m.org, top_id, "ON")
             if t.get("label") == "Task" and not t.get("retired")}
    members = []
    for key, nth in spec["tasks"]:
        tid = tasks[SAMPLE_UAV_PROGRAMME[key]["name"]]
        members.append({"task_id": tid, "visit_rule": "nth", "every_nth": nth} if nth else {"task_id": tid})
    pkg = m.create_package(spec["name"], position_id=top_id, timing="fixed", every=spec["every"], unit=spec["unit"],
                           weekday=spec["weekday"], nth=spec["nth"], tolerance=spec["tolerance"],
                           tolerance_unit="days", trade=spec["trade"], notes=spec["notes"], tasks=members)
    return {"id": pkg["id"], "name": pkg["name"]}


# ---- the sample product: a quadcopter design and three items built from it ---------
# Entirely invented: no real product, company, operator or partner. The design carries
# the RCM above on every position it belongs to (four arms, motors, speed controllers
# and propellers, two IMUs), so its RCM and FME(C)A tabs are full.

SAMPLE_PRODUCT_NAME = "Survey quadcopter (sample)"
SAMPLE_PRODUCT_PART = "SQ-4"
SAMPLE_PRODUCT_REV = "C"
_PRODUCT_COPY_NAME = products.SAMPLE_NAME

ARMS = 4
# The design tree: (name, position class, children); the classes pool like positions' life data.
SAMPLE_PRODUCT_TREE: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("Airframe", "", [("Centre frame", "")] + [(f"Arm {i}", "Airframe arm") for i in range(1, ARMS + 1)]
     + [("Landing gear", "Landing gear")]),
    ("Propulsion", "", [(f"Motor {i}", "Brushless motor") for i in range(1, ARMS + 1)]
     + [(f"ESC {i}", "Speed controller (ESC)") for i in range(1, ARMS + 1)]
     + [(f"Propeller {i}", "Propeller") for i in range(1, ARMS + 1)]),
    ("Flight control", "", [("Flight controller", "Flight controller"), ("IMU 1", "IMU"), ("IMU 2", "IMU"),
                            ("GPS", "GPS module"), ("Compass", "Compass")]),
    ("Power", "", [("Battery pack", "Battery pack"), ("BMS", "Battery management (BMS)")]),
    ("Comms", "", []),
    ("Payload gimbal", "", [("Camera", "Camera")]),
]
# The design's physical layout (its design locations): (name, inside, the positions placed
# there). Every item built from it carries a copy, its positions placed the same way.
_ARM_NAMES = ["Forward left arm", "Forward right arm", "Rear left arm", "Rear right arm"]
SAMPLE_PRODUCT_LAYOUT: list[tuple[str, str | None, list[str]]] = [
    *[(arm, None, [f"Arm {i}", f"Motor {i}", f"ESC {i}", f"Propeller {i}"]) for i, arm in enumerate(_ARM_NAMES, 1)],
    ("Centre body", None, ["Centre frame", "Landing gear", "Flight controller", "IMU 1", "IMU 2", "GPS", "Compass",
                           "Comms"]),
    ("Battery bay", "Centre body", ["Battery pack", "BMS"]),
    ("Payload bay", None, ["Payload gimbal", "Camera"]),
]
# Where each of SAMPLE_UAV_RCM's positions sits in the product's design ("" is the product).
SAMPLE_PRODUCT_MODES_AT = {
    "": [""], "Airframe": ["Airframe"], "Centre frame": ["Centre frame"], "Arm": [f"Arm {i}" for i in range(1, ARMS + 1)],
    "Landing gear": ["Landing gear"],
    "Propulsion": ["Propulsion"], "Motor": [f"Motor {i}" for i in range(1, ARMS + 1)],
    "Speed controller (ESC)": [f"ESC {i}" for i in range(1, ARMS + 1)],
    "Propeller": [f"Propeller {i}" for i in range(1, ARMS + 1)],
    "Flight control": ["Flight control"], "Flight controller": ["Flight controller"], "IMU": ["IMU 1", "IMU 2"],
    "GPS receiver": ["GPS"], "Compass": ["Compass"],
    "Power": ["Power"], "Battery pack": ["Battery pack"], "Battery management (BMS)": ["BMS"],
    "Comms link": ["Comms"], "Payload gimbal": ["Payload gimbal"], "Camera": ["Camera"],
}
# The bill of materials: (part number, name, quantity in one quadcopter, indenture level).
# The airframe kit is the centre frame, the arms and the landing gear; the camera head
# comes with its gimbal; the compass is in the GPS module.
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
# Where a parts-count prediction of the sample starts (position_models.py). Sample values,
# invented like the rest: nothing here is a real design's figure.
# Its environment: MIL-HDBK-217F's "Airborne, rotary winged" (ARW), the handbook's environment for
# equipment on a rotorcraft, which a quadcopter is. The handbook's uninhabited environments (AUC,
# AUF) are the uncrewed bays of fixed-wing transports and fighters. The sample prediction on the
# Predictions page (backend/services/samples.py) uses ARW too.
SAMPLE_PRODUCT_ENVIRONMENT = "ARW"
SAMPLE_MOTOR_PART = "SQ-M2210"


def is_sample_product(node: dict | None) -> bool:
    """A design's top that is a copy of the sample product, made the user's own or not."""
    return bool(node and node.get("design") and (products.is_sample(node)
                                                 or node.get("from_sample") == products.SAMPLE_KEY))


def sample_part_conditions(reference: str, record_id: str) -> dict | None:
    """The conditions a part of the sample starts from when a prediction gives it this handbook
    model (None: the sample has none for it). The motors on NSWC-11's electric motor: the sample
    prediction's conditions for a 2210 brushless motor (sample values, not measured)."""
    from backend.services import samples

    if (reference or "").upper() == SAMPLE_MOTOR_PART and record_id == samples.SAMPLE_MOTOR_MODEL:
        return dict(samples.SAMPLE_MOTOR_CONDITIONS)
    return None


# The items built: serial, revision, flight hours and sorties flown, read now.
SAMPLE_PRODUCT_ITEMS = [("0007", "C", 212.0, 553), ("0008", "C", 31.0, 81), ("0009", "B", 640.0, 1670)]
# The flight-critical RBD's blocks: a guessed constant failure rate per flight hour each
# (placeholder=true on every block: no real data).
SAMPLE_RBD_RATES = {"Battery pack": 1e-4, "BMS": 5e-5, "Flight controller": 2e-5, "IMU": 1e-4, "GPS": 5e-5,
                    "ESC": 3e-5, "Motor": 4e-5, "Propeller": 2e-5}

# Each programme task's LSA record (task.resources_set): who does it and for how long, the
# tools, the spares and consumables to bring, access and downtime, and the method. The task
# names say what is done; this says how. Invented, like the rest of the sample: the times
# are a plausible plan for a small drone, not measured. A spare with a part_number is the
# catalogue part of the bill of materials; the items built from the design copy the lot.
SAMPLE_UAV_LSA = {
    "pre_flight": {
        "labour": [{"trade": "Pilot", "people": 1, "hours": 0.25}, {"trade": "Observer", "people": 1, "hours": 0.25}],
        "tools": [{"name": "Propeller go/no-go gauge"}, {"name": "Hex driver set, 1.5 to 3 mm"},
                  {"name": "Ground station tablet"}],
        "spares": [{"part_number": "SQ-P1045", "qty": 4}],
        "consumables": [{"name": "Lens cleaning wipes", "qty": 2, "unit": "wipes"}],
        "access": {"downtime_hours": 0.25, "access_equipment": "Marked take-off pad, clear of people"},
        "method": "On the pad before each sortie: the observer reads the checklist aloud and the pilot does each "
                  "item; then power up, wait for the arming checks and hover at 2 m.",
        "duration_hours": 0.25,
    },
    "log_review": {
        "labour": [{"trade": "Technician", "people": 1, "hours": 0.5}],
        "tools": [{"name": "Laptop with the flight log viewer"}],
        "method": "Download the logs since the last review; plot each motor's temperature, each speed controller's "
                  "temperature rise, RPM and watchdog events against their limits, and note the trend.",
        "duration_hours": 0.5,
    },
    "25h": {
        "labour": [{"trade": "Technician", "people": 1, "hours": 1.5}],
        "tools": [{"name": "Torque driver, 0.5 to 3 N·m"}, {"name": "Magnifier, 10×"},
                  {"name": "Gimbal levelling reference"}],
        "consumables": [{"name": "Isopropyl alcohol", "qty": 0.05, "unit": "L"},
                        {"name": "Cable sleeve", "qty": 0.2, "unit": "m"}],
        "access": {"downtime_hours": 2, "isolation": "Battery pack out and propellers off before any work"},
        "method": "On the bench: clean each arm root and motor mount and look at it under the magnifier; check the "
                  "antenna cables where they pass the arm roots; then level the gimbal against the reference.",
        "duration_hours": 1.5,
    },
    "100h": {
        "labour": [{"trade": "Technician", "people": 1, "hours": 3}],
        "tools": [{"name": "Torque driver, 0.5 to 3 N·m"}, {"name": "Magnifier, 10×"},
                  {"name": "Hex driver set, 1.5 to 3 mm"}],
        "consumables": [{"name": "Torque seal", "qty": 2, "unit": "g"},
                        {"name": "Isopropyl alcohol", "qty": 0.05, "unit": "L"}],
        "access": {"downtime_hours": 4, "isolation": "Battery pack out and propellers off before any work"},
        "method": "The 25-hour items first; then take the arms off and look at every arm bolt hole in the centre "
                  "plates under the magnifier; refit the arms, torque the clamp bolts to 2.5 N·m in a cross "
                  "pattern and renew the stripes.",
        "duration_hours": 3,
    },
    "annual": {
        "labour": [{"trade": "Service centre technician", "people": 1, "hours": 6}],
        "tools": [{"name": "Torque driver, 0.5 to 3 N·m"}, {"name": "Magnifier, 10×"},
                  {"name": "Motor and speed controller run-up bench"}],
        "spares": [{"name": "Memory card, 128 GB (approved type)", "qty": 1}, {"name": "Gimbal damper ball", "qty": 4}],
        "consumables": [{"name": "Isopropyl alcohol", "qty": 0.1, "unit": "L"}],
        "access": {"downtime_hours": 120, "access_equipment": "Shipping case to and from the maker's service centre"},
        "method": "At the maker's service centre: the 100-hour items, then the memory card and the four damper "
                  "balls replaced, the age-limited parts replaced, and the year's logs reviewed.",
        "duration_hours": 6,
    },
    "failsafe": {
        "labour": [{"trade": "Pilot", "people": 1, "hours": 1}, {"trade": "Observer", "people": 1, "hours": 1}],
        "tools": [{"name": "Bench power supply, 0 to 30 V, 10 A"}, {"name": "Ground station tablet"},
                  {"name": "Radio transmitter"}],
        "access": {"downtime_hours": 1, "access_equipment": "Marked take-off pad, clear of people, inside the "
                                                            "geofence"},
        "method": "Over the pad, with the observer watching the airspace: the link-loss test in a 3 m hover, the "
                  "geofence at 10 m and the height-limit climb; then, with the propellers off, the low-battery "
                  "test on the bench supply.",
        "duration_hours": 1,
    },
    "battery": {
        "labour": [{"trade": "Technician", "people": 1, "hours": 0.5}],
        "tools": [{"name": "Battery analyser (cell voltages and internal resistance)"},
                  {"name": "Charger with a storage mode"}],
        "access": {"isolation": "Packs handled and charged in a fire-resistant bag"},
        "method": "Read every pack's cell voltages and internal resistance on the analyser and log them against the "
                  "pack's serial; bring a pack outside 3.75 to 3.85 V a cell to storage charge; set aside a pack "
                  "below 3.6 V a cell.",
        "duration_hours": 0.5,
    },
}

# The calendar tasks, packaged into one monthly visit on the first item built (a design's
# tasks are never due; the items' copies are): the failsafe tests on every visit, the
# battery storage check on every third and the annual inspection on every twelfth.
SAMPLE_UAV_PACKAGE = {
    "name": "Monthly maintenance visit", "every": 1, "unit": "months", "weekday": "Monday", "nth": 1,
    "tolerance": 3, "trade": "Technician",
    "notes": "The calendar tasks in one visit on the first Monday of the month, before the month's survey "
             "flying: the failsafe tests every visit, the battery storage check every third visit and the annual "
             "inspection every twelfth.",
    "tasks": [("failsafe", None), ("battery", 3), ("annual", 12)],
}

# Life models on the design's positions (copied to the items built from it): (template
# position, saved model id, its name, the failure mode it describes). Shared samples every
# account can read, in flight hours, invented like the rest (backend/services/samples.py).
UAV_PROPELLER_MODEL = "sample-model-quad-propeller-weibull"
UAV_BATTERY_MODEL = "sample-model-quad-battery-weibull"
SAMPLE_PRODUCT_MODELS = [
    ("Motor", UAV_BEARING_MODEL, "Bearing life — Weibull (sample)", "Bearing seizure",
     "Sample values, not field data: a Weibull fitted to invented bench-test bearing lives, in hours."),
    ("Propeller", UAV_PROPELLER_MODEL, "Quadcopter propeller — Weibull (sample)", "Blade fatigue crack at the hub",
     "Sample values, not field data: an invented Weibull in flight hours (scale 400, shape 3), the same as the "
     "propeller replacement analysis."),
    ("Battery pack", UAV_BATTERY_MODEL, "Quadcopter battery pack — Weibull (sample)", "Cell capacity fade",
     "Sample values, not field data: an invented Weibull in flight hours (scale 600, shape 3), the same as the "
     "battery retirement analysis."),
    ("Comms link", UAV_AVIONICS_MODEL, "Quadcopter avionics — Exponential (sample)",
     "Radio module fails (electronic)",
     "Sample values, not field data: an exponential fitted to invented avionics board lives, in hours."),
]


def sample_products(m) -> list[dict]:
    """Copies of the sample product in this workspace (live product designs with its name)."""
    return [p for p in _copies(m, _PRODUCT_COPY_NAME) if p.get("design")]


def own_sample_products(m) -> list[dict]:
    """Copies of the sample product the user has made their own (products.clear_sample):
    live product designs keeping the sample's key, whatever they're called now."""
    return sorted((p for p in m.s.nodes(m.org, "Position") if p.get("from_sample") == products.SAMPLE_KEY
                   and p.get("design") and not p.get("retired")), key=lambda p: p["name"])


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


def _sample_maintainability(m, db, product: dict) -> dict:
    """The sample product's maintainability prediction, in the workspace's saved
    predictions and attached to the product (its inputs' product_id): the shared
    sample's lines (backend/services/samples.py), so the numbers are the same. Made
    only when the workspace has none for this product, so asking twice adds one. A
    saved document like the RBD, not an event: it stays if the product is retired."""
    from backend.services import maintainability, samples

    have = db[maintainability.COLLECTION].find_one({"owner_id": m.org, "inputs.product_id": product["id"]})
    if have is not None:
        return {"id": have["_id"], "name": have["name"], "added": False}
    inputs = samples.sample_maintainability_inputs({"id": product["id"], "name": product["name"]})
    doc = maintainability.save_prediction(db, f"{product['name']} — maintainability", inputs, m.org)
    return {"id": doc.id, "name": doc.name, "added": True}


def add_sample_product(m, db, again: bool = False) -> dict:
    """Add the sample product to ``m``'s workspace: a quadcopter's design tree with the
    sample RCM on it (its mission as the operating context, every failure mode scored,
    the decisions' tasks as its maintenance programme), its physical layout (design
    locations, the positions placed on them), its part with a small bill of materials,
    three items built from it (each with flight-hours and flights counters), a replaced
    motor on one, two failure reports, a flight-critical RBD in the RBDs
    (placeholder failure rates, said so in its name) and a maintainability prediction
    attached to the product. Once only, unless ``again``. A copy of the sample that is
    there already and has no maintainability prediction (one added before the sample
    had one) is given it here; one the user made their own is left as it is."""
    existing = sample_products(m)
    # One made the user's own counts too: the sample is never added again beside it unless asked.
    owned = [] if existing else own_sample_products(m)
    if (existing or owned) and not again:
        have = (existing or owned)[0]
        predictions = {p["id"]: _sample_maintainability(m, db, p) for p in existing}
        mine = predictions.get(have["id"])
        topped_up = (f" Added its maintainability prediction, “{mine['name']}”: invented repair times and failure "
                     "rates, the same as the shared sample's.") if mine and mine["added"] else ""
        return {
            "added": False,
            "product": {"id": have["id"], "name": have["name"]},
            "position": {"id": have["id"], "name": have["name"]},
            **({"maintainability": mine} if mine else {}),
            "message": (f"The sample product is already in your workspace as “{have['name']}”. "
                        f"Ask again to add another copy.{topped_up}") if existing else
                       (f"You made the sample product your own as “{have['name']}”. Ask again to add a fresh copy "
                        "of the sample beside it."),
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

    at: dict[str, str] = {"": pid}
    counts = {"positions": 1, "functions": 0, "standards": 0, "functional_failures": 0, "failure_modes": 0,
              "scored": 0, "decisions": 0, "causes_linked": 0, "tasks": 0, "locations": 0, "lsa_records": 0,
              "models_linked": 0}
    # Its physical layout first, so each position is made where it sits.
    places: dict[str, str] = {}
    placed_at: dict[str, str] = {}
    for place, inside, positions in SAMPLE_PRODUCT_LAYOUT:
        places[place] = m.create_location(place, parent_id=places.get(inside) if inside else None,
                                          design_of=None if inside else pid)["id"]
        counts["locations"] += 1
        placed_at |= {name: places[place] for name in positions}
    for group, cls, children in SAMPLE_PRODUCT_TREE:
        at[group] = m.create_position(group, parent_id=pid, position_class=cls,
                                      location_id=placed_at.get(group))["id"]
        counts["positions"] += 1
        for child, child_cls in children:
            at[child] = m.create_position(child, parent_id=at[group], position_class=child_cls,
                                          location_id=placed_at.get(child))["id"]
            counts["positions"] += 1
    at_of = {k: [at[n] for n in names] for k, names in SAMPLE_PRODUCT_MODES_AT.items()}
    programme = _add_uav_rcm(m, at_of, counts)
    # Before any item is built, so each item's copies carry them.
    _add_uav_lsa(m, programme, counts)
    _add_uav_models(m, at_of, counts)

    today = date.fromisoformat(m.today())

    def ago(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()

    motor = next(pt for pt in m.s.nodes(m.org, "Part") if pt["part_number"] == "SQ-M2210")
    gps = next(pt for pt in m.s.nodes(m.org, "Part") if pt["part_number"] == "SQ-GPS8")
    items = []
    for serial, rev, hours, flights in SAMPLE_PRODUCT_ITEMS:
        built = m.build_item(pid, serial, rev=rev, dry_run=False)
        tree = {row["path"].split(" › ")[-1]: row["id"] for row in built["positions"]}
        point = m.add_point(None, "Flight hours", kind="counter", unit="hours", item_id=built["item"]["id"])
        m.record_reading(point["id"], hours)
        sorties = m.add_point(None, "Flights", kind="counter", unit="flights", item_id=built["item"]["id"])
        m.record_reading(sorties["id"], flights)
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
    package = _add_uav_package(m, first["top_position_id"])
    rbd = _save_sample_rbd(m, db, f"{name}: flight-critical RBD (placeholder failure rates)")
    prediction = _sample_maintainability(m, db, {"id": pid, "name": name})
    undecided = counts["failure_modes"] - counts["decisions"]
    return {
        "added": True,
        "product": {"id": pid, "name": name},
        "position": {"id": pid, "name": name},
        "items": [{k: it[k] for k in ("serial", "rev", "item_id", "top_position_id")} for it in items],
        "reports": [{"id": r["id"], "label": r.get("label") or r["title"]} for r in reports],
        "rbd": rbd,
        "maintainability": prediction,
        "package": package,
        **counts,
        "message": (f"Added “{name}”: a design of {_n(counts['positions'], 'position')} with a complete RCM study "
                    f"for its inspection mission ({_n(counts['functions'], 'function')} with "
                    f"{_n(counts['standards'], 'performance standard')}, "
                    f"{_n(counts['functional_failures'], 'functional failure')} and "
                    f"{_n(counts['failure_modes'], 'failure mode')}, each scored as an FME(C)A and all but "
                    f"{undecided} decided) and the maintenance programme those decisions make "
                    f"({_n(counts['tasks'], 'task')}: the pre-flight check, the flight log review, the 25-hour, "
                    "100-hour and annual inspections, the monthly failsafe function tests, the three-monthly "
                    "battery storage check, and the propeller and battery limits; each programme task with its "
                    "LSA record). The evidence check shows "
                    "each case: the motor bearings' legacy run-to-failure "
                    "decision is contradicted on purpose (their life model shows wear-out), the battery retirement "
                    "can't be checked until its units agree, and the rest with evidence are supported. Its physical "
                    f"layout ({_n(counts['locations'], 'design location')}: four arms, the centre body with its "
                    f"battery bay, and the payload bay), its part with a bill of materials, {_n(len(items), 'item')} "
                    f"built from it (serials {', '.join(it['serial'] for it in items)}), the work package "
                    f"“{package['name']}” on {items[0]['serial']} for the calendar tasks, a replaced motor and two "
                    f"failure reports. Life models on {_n(counts['models_linked'], 'position')} (motors, propellers, "
                    f"battery pack and radio) are shared samples, not field data. The RBD “{rbd['name']}” is in your RBDs: its failure rates are placeholders, "
                    "not data. Each arm's ESC, motor and propeller are in series there: the design has one ESC per "
                    f"motor. The maintainability prediction “{prediction['name']}” is in your maintainability "
                    "predictions, attached to the product: its repair times and failure rates are invented."),
    }
