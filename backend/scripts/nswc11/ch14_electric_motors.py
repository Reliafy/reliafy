"""Chapter 14, Electric motors (Revision B): the motor as the sum of its parts,
Eq. 14-1 (p. 14-7), and the windings, Eq. 14-2 to 14-8 (pp. 14-8 to 14-13).

Checked against the rendered pages 14-7 to 14-18:
- Eq. 14-1: λ_M = (λ_M,B · C_SF) + λ_WI + λ_BS + λ_ST + λ_AS + λ_BE + λ_GR + λ_C,
  all in failures per million hours. λ_BS is 3.2 per million hours *per brush*
  (so a count of brushes); λ_ST is 0.001.
- Eq. 14-3: λ_WI,B = 10⁶ / L_I; with no maker's life, L_I = 25,000 h (40.0).
- Eq. 14-5: C_T = 2^((T_O − 40)/10) (the text extraction scrambles it).
- Eq. 14-6: C_V = 2^(10 · V_D/V_R) for single-phase motors.
- Eq. 14-7: C_V = 1 + (0.40 · V_U)^2.5 for three-phase motors, V_U in % from
  0 to 3 % (p. 14-13).
- Eq. 14-8: C_alt = 1.00 + 8×10⁻⁵ (a − 3300 ft) above 3,300 ft, else 1.0.
- Tables 14-3 (λ_M,B) and 14-4 (C_SF) on p. 14-18.
- Figure axes: 14.1 covers T_O 0 to 80 °C; 14.2 covers V_D/V_R 0 to 0.40;
  14.3 covers V_U 0 to 4 % (the text's range is 0 to 3 %); 14.4 covers 0 to
  18,000 ft.

Readings chosen where the handbook is silent or loose (each in the report):
- The handbook gives C_V only for single-phase (Eq. 14-6) and three-phase
  (Eq. 14-7) motors. Table 14-3 lists DC and polyphase motors too: here a
  polyphase motor takes Eq. 14-7 (voltage unbalance) and a DC motor takes
  Eq. 14-6 (the same rated-versus-actual voltage differential), said on the
  factor.
- λ_C, the capacitor, is from MIL-HDBK-217 (an electronic part, outside this
  handbook): a rate the user gives, 0 when there's no capacitor.
- λ_AS uses the Chapter 20 shaft model: per million hours by Reliafy's reading
  (readings.SHAFT_PER_HOUR; p. 14-7 lists λ_AS per million hours), added as it
  is; with the switch off it is per million cycles × the motor's revolutions an
  hour. One motor speed is entered and passed to the bearings.
- Insulation class (Table 14-2, p. 14-9) and Note 1 (p. 14-11): with the class
  and a measured winding rise (Eq. 14-4 from hot and cold resistances), T_O is
  lowered by the class's allowable rise minus the measured one.
- Gears are only in geared motors, so there are two motor records: without
  gears and with (λ_GR from Chapter 8, a count of gears).
- p. 14-11 says a Class F motor in a Class B environment "can be expected to
  last four times as long"; the classes are 25 °C apart, which Eq. 14-5 makes
  2^2.5 ≈ 5.7 times (four times is 20 °C). The model follows Eq. 14-5.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, num, refuse, record, table, uses, warn,
)
from backend.scripts.nswc11 import readings

#: Table 14-2 (p. 14-9): allowable temperature rise by insulation class, °C.
_RISE = {"A": 60, "B": 85, "F": 110, "H": 135}

_FAILURE_MODES = [
    "Open or shorted winding: insulation breakdown (heat, altitude, overload, frequent starts, dirt on cooling fins, "
    "vibration, shock)",
    "Worn bearing: spalling, creeping or spin (static load, belt misalignment, lubrication, contamination, heat)",
    "Cracked housing: fatigue, external shock, vibration",
    "Sheared armature shaft or cracked rotor laminations: fatigue, misalignment, bearing failure",
    "Worn brushes, failing open: poor maintenance, contamination, heat, wrong contact pressure",
    "Noisy running: worn or bent shaft, misalignment, vibration, distorted base plate, broken mounts",
    "Overheating: frequent starts, wrong supply voltage, hot surroundings, phase unbalance over 1 %, overload, "
    "blocked ventilation",
    "Overload tripping: wrong supply voltage, excessive load speed",
]

_MOTOR_TYPE = choice("motor_type", "Type of motor", [
    ("dc", "DC (brushed)"),
    ("dc_brushless", "DC brushless"),
    ("ac_single", "AC single phase"),
    ("ac_polyphase", "AC polyphase (three phase)"),
], symbol="λ_M,B", page="14-18",
    help="Sets the motor's base rate (Table 14-3) and which supply-voltage factor applies.")

_LOAD = choice("load", "Type of load (service factor)", [
    ("uniform", "Uniform: one way, continuous, little load change, no shock or vibration"),
    ("light_impact", "Light impact: frequent starts and stops, stepping, little shock or vibration"),
    ("medium_impact", "Medium impact: frequent reversing, moderate load impact, shock and vibration"),
    ("heavy_impact", "Heavy impact: heavy vibration, shock loads, heavy load changes"),
], default="uniform", default_basis="neutral", symbol="C_SF", page="14-18")


def _winding_inputs() -> list[dict]:
    return [
        num("L_I", "Expected winding life (maker's figure)", "hours", [positive_life()], default=25000,
            default_basis="handbook", symbol="L_I", page="14-8",
            help="With no maker's figure the handbook expects 25,000 hours (40.0 failures per million hours)."),
        num("T_O", "Ambient temperature around the running motor at full load", "°C", [
            refuse(min=-273.15, why="below absolute zero"),
            warn(min=0, max=80, why="Figure 14.1 covers 0 to 80 °C", page="14-14"),
        ], default=40, default_basis="neutral", symbol="T_O", page="14-11",
            help="40 °C is the rating's assumed ambient (factor 1). If hot and cold resistance readings show the "
                 "winding's rise is below its class's (Table 14-2), lower T_O by the difference (p. 14-11, note 1); "
                 "allow for an enclosed cabinet or nearby hot equipment (note 2)."),
        num("VD_VR", "Supply voltage difference ÷ rated voltage", "", [
            refuse(min=0, why="a difference in size can't be negative"),
            warn(max=0.40, why="Figure 14.2 covers V_D/V_R from 0 to 0.40", page="14-15"),
        ], default=0, default_basis="neutral", symbol="V_D/V_R", page="14-12",
            help="|rated − actual voltage| ÷ rated voltage, above or below (single-phase and DC motors)."),
        num("V_U", "Phase voltage unbalance", "%", [
            refuse(min=0, max=100, why="a percentage unbalance is 0 to 100"),
            warn(max=1, why="the industry standard recommends at most 1 % (the handbook's range is 0 to 3 %)",
                 page="14-12"),
            warn(max=3, why="the handbook's range for V_U is 0 to 3 %; never run a motor above 3 %",
                 page="14-13"),
        ], default=0, default_basis="neutral", symbol="V_U", page="14-12",
            help="100 × (greatest difference from the average phase voltage) ÷ the average (three-phase motors)."),
        choice("ins_class", "Insulation class (to adjust T_O from a measured winding rise)", [
            ("unknown", "Not used (no measured rise)"), ("A", "Class A (allowable rise 60 °C)"),
            ("B", "Class B (85 °C)"), ("F", "Class F (110 °C)"), ("H", "Class H (135 °C)")],
            default="unknown", default_basis="neutral", symbol="Table 14-2", page="14-9",
            help="With a measured rise, T_O is lowered by the class's allowable rise minus the measured rise "
                 "(p. 14-11, note 1): a Class F motor running a Class B rise gets 25 °C off, 2^2.5 = 5.7 × longer."),
        num("rise", "Measured winding temperature rise at full load", "°C", [
            refuse(min=0, why="a rise can't be negative")], symbol="T_rise", page="14-10", when="ins_class != 'unknown'",
            help="Eq. 14-4: (R_H − R_C) / R_C × (234.5 + T_C), from the hot and cold winding resistances and the "
                 "cold temperature."),
        num("a", "Operating altitude", "ft", [
            refuse(min=-1500, why="no land is more than about 1,400 ft below sea level"),
            warn(min=0, max=18000, why="Figure 14.4 covers 0 to 18,000 ft", page="14-17"),
        ], default=0, default_basis="neutral", symbol="a", page="14-13",
            help="Up to 3,300 ft counts as sea level (factor 1)."),
    ]


def positive_life() -> dict:
    return refuse(min=0, exclusive=True, why="a life is more than zero")


def _winding_factors(polyphase: str) -> list[dict]:
    """C_T, C_V (Eq. 14-6 unless ``polyphase`` is true, then Eq. 14-7) and C_alt."""
    return [
        factor("C_T", "Ambient temperature", "14-11", expr="2 ** ((T_eff - 40) / 10)", equation="14-5",
               source="Figure 14.1", words="a hotter surrounding"),
        factor("C_V", "Supply voltage differential (single phase; DC by the same differential)", "14-12",
               expr="2 ** (10 * VD_VR)", equation="14-6", source="Figure 14.2", when=f"not ({polyphase})",
               words="a supply voltage away from the rating"),
        factor("C_V", "Phase voltage unbalance (three phase)", "14-12", expr="1 + (0.40 * V_U) ** 2.5",
               equation="14-7", source="Figure 14.3", when=polyphase, words="unbalanced phase voltages"),
        factor("C_alt", "Altitude", "14-13", expr="1.0 if a <= 3300 else 1.00 + 8e-5 * (a - 3300)",
               equation="14-8", source="Figure 14.4", words="thin air at altitude"),
    ]


def _winding_mode(polyphase: str) -> dict:
    return mode("windings", "Windings (insulation breakdown)",
                base("λ_WI,B", "Winding base failure rate (10⁶ ÷ the expected winding life in hours)", "14-8",
                     expr="1e6 / L_I", equation="14-3"),
                _winding_factors(polyphase), symbol="λ_WI")


_SHAFT_NOTE = ("Reliafy's reading (p. 14-7 against p. 20-5): Eq. 14-1 lists the armature shaft per million hours "
               "while Chapter 20 gives it per million cycles; it is taken per million hours and added as it is."
               if readings.SHAFT_PER_HOUR else
               "Chapter 20's shaft model is per million cycles: × the motor's revolutions an hour (60 × rpm).")
_RISE_EXPR = " else ".join(f"{v} if ins_class == '{k}'" for k, v in _RISE.items()) + " else 0"
_T_EFF = derived("T_eff", "Ambient temperature for C_T (less any spare rise, Table 14-2 note 1)",
                 f"T_O if ins_class == 'unknown' else T_O - (({_RISE_EXPR}) - rise)", "°C", "T_O", "14-11")


def _motor_inputs(geared: bool) -> list[dict]:
    out = [
        _MOTOR_TYPE, _LOAD,
        num("n", "Motor speed", "rpm", [refuse(min=0, exclusive=True, why="the motor must turn")], symbol="n",
            page="14-7", help="Passed to the bearings (one speed for the motor)."),
        *_winding_inputs(),
        num("n_BS", "Number of brushes", "", [refuse(min=0, why="a count can't be negative")], default=0,
            default_basis="typical", symbol="n", page="14-7",
            help="3.2 failures per million hours per brush (p. 14-7). 0 for a motor without brushes."),
        num("n_BE", "Number of rolling bearings", "", [refuse(min=0, why="a count can't be negative")],
            symbol="n", page="14-7", help="Eq. 14-1 takes the total for all the motor's bearings."),
        num("lambda_C", "Capacitor failure rate (from MIL-HDBK-217), if it has one", "failures per million hours",
            [refuse(min=0, why="a failure rate can't be negative")], default=0, default_basis="typical",
            symbol="λ_C", page="14-7",
            help="The handbook takes it from MIL-HDBK-217 (an electronic part). 0 when there's no capacitor."),
    ]
    if geared:
        out.append(num("n_GR", "Number of gears", "", [refuse(min=0, why="a count can't be negative")],
                       symbol="n", page="14-7", help="Eq. 14-1 takes the total for all the motor's gears."))
    return out


def _motor_modes(geared: bool) -> list[dict]:
    out = [
        mode("motor", "Motor base (loaded as in service)",
             base("λ_M,B", "Motor base failure rate", "14-18", table=table("motor_type", {
                 "dc": 2.17, "dc_brushless": 1.75, "ac_single": 6.90, "ac_polyphase": 10.00,
             }), source="Table 14-3"),
             [factor("C_SF", "Motor load service factor", "14-18", table=table("load", {
                 "uniform": 1.00, "light_impact": 1.50, "medium_impact": 2.00, "heavy_impact": 3.00,
             }), source="Table 14-4", words="shock, vibration and frequent starts in its load")],
             symbol="λ_M,B·C_SF"),
        _winding_mode("motor_type == 'ac_polyphase'"),
        mode("brushes", "Brushes (each)", base("λ_BS", "Brush failure rate, per brush", "14-7", value=3.2),
             symbol="λ_BS", count="n_BS"),
        mode("stator", "Stator housing", base("λ_ST", "Stator housing failure rate", "14-7", value=0.001),
             symbol="λ_ST"),
        uses("shaft", "Armature shaft", "shaft", symbol="λ_AS", note=_SHAFT_NOTE,
             **({} if readings.SHAFT_PER_HOUR else {"scale": "60 * n", "scale_label": "revolutions an hour"})),
        uses("bearings", "Bearings (each)", "bearing-rolling-load-rating", symbol="λ_BE", count="n_BE",
             bind={"n": "n"}),
    ]
    if geared:
        out.append(uses("gears", "Gears (each)", "gear", symbol="λ_GR", count="n_GR"))
    out.append(mode("capacitor", "Capacitor (if fitted)",
                    base("λ_C", "Capacitor failure rate (MIL-HDBK-217)", "14-7", expr="lambda_C"), symbol="λ_C"))
    return out


_MOTOR_CHECKS = [
    check("not (motor_type == 'dc' and n_BS == 0)", "A brushed DC motor has brushes: give how many", "14-7"),
    check("not (motor_type == 'dc_brushless' and n_BS > 0)", "A brushless DC motor has no brushes", "14-18"),
]

_WORDS = ("A motor's failure rate is the sum of its parts. The motor's own base rate (by type) is scaled by how "
          "rough its load is; its windings start at one over their expected life and are scaled by the "
          "surrounding temperature, the supply voltage and altitude; then come its brushes, stator housing, "
          "armature shaft and bearings{gears}, and a capacitor if it has one.")

_FORMULA = ("λ_M = (λ_M,B · C_SF) + λ_WI + λ_BS + λ_ST + λ_AS + λ_BE{gr} + λ_C, with "
            "λ_WI = λ_WI,B · C_T · C_V · C_alt")

RECORDS = [
    record(
        "electric-motor", "Electric motor (no gearbox)", "electric_motor", 14, "14.4 Model development", "14-1",
        "14-7", _FORMULA.format(gr=""), _WORDS.format(gears=""),
        inputs=_motor_inputs(False), modes=_motor_modes(False), checks=_MOTOR_CHECKS, derived=[_T_EFF],
        notes=("Eq. 14-1 without λ_GR, for a motor with no gears. Bearings use the Chapter 7 load-rating model "
               "and the armature shaft the Chapter 20 shaft model. The handbook gives the supply-voltage factor "
               "for single- and three-phase motors only: a DC motor here takes the single-phase voltage "
               "differential (Eq. 14-6)."),
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "electric-motor-geared", "Electric motor with gears", "electric_motor", 14, "14.4 Model development",
        "14-1", "14-7", _FORMULA.format(gr=" + λ_GR"), _WORDS.format(gears=" and gears"),
        inputs=_motor_inputs(True), modes=_motor_modes(True), checks=_MOTOR_CHECKS, derived=[_T_EFF],
        notes=("Eq. 14-1 in full, for a motor with gears (Chapter 8's gear model, one per gear). Bearings use the "
               "Chapter 7 load-rating model and the armature shaft the Chapter 20 shaft model. A DC motor takes "
               "the single-phase voltage differential (Eq. 14-6)."),
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "electric-motor-winding", "Electric motor winding", "electric_motor", 14,
        "14.5 Failure rate model for motor windings", "14-2", "14-8",
        "λ_WI = λ_WI,B · C_T · C_V · C_alt, with λ_WI,B = 10⁶ / L_I",
        "A motor winding's failure rate starts at one over its expected life (25,000 hours if the maker gives "
        "none) and is scaled by the temperature around the running motor (doubling every 10 °C above 40 °C), a "
        "supply voltage away from its rating or unbalanced between phases, and altitude above 3,300 ft.",
        inputs=[
            choice("supply", "Supply", [
                ("single_phase", "Single phase (or DC: rated-versus-actual voltage, Eq. 14-6)"),
                ("three_phase", "Three phase (voltage unbalance, Eq. 14-7)"),
            ], symbol="C_V", page="14-12"),
            *_winding_inputs(),
        ],
        modes=[_winding_mode("supply == 'three_phase'")], derived=[_T_EFF],
        notes="The windings term λ_WI of Eq. 14-1 on its own. DC motors take Eq. 14-6 (the handbook names only "
              "single- and three-phase motors).",
        failure_modes=_FAILURE_MODES[:1],
    ),
]
