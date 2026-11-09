"""Chapter 8, Gears and splines (Revision A): gears, Eq. 8-2 (base rate from a
design life, or a known base rate), and splines, Eq. 8-13.

Checked against the rendered pages 8-8 to 8-19:
- λ_G,B (footnote, p. 8-9): "(RPM × 60) × 1 / design life (revolutions)",
  one failure in 10⁸ revolutions when no design life is known. That is per
  hour; ×10⁶ gives the stated unit (failures per million hours). Ambiguous: the
  footnote's RPM isn't said to be the design or the operating speed. The model
  uses the design speed V_d: the base rate is "at a specified speed, load,
  lubricant and temperature", and C_GS then scales for the operating speed (the
  operating speed in both would count speed twice).
- C_GS (Eq. 8-3, Figure 8.6, p. 8-9 and 8-14): k + (V_o / V_d)^0.7 with k = 1.0.
  The factor is 2.0 (not 1) at the design speed; the handbook's figure shows
  this (its axis starts at 1.0 for V_o = 0). Followed literally.
- C_GP (Eq. 8-6, Figure 8.7, p. 8-10 and 8-15): ((L_O / L_D) / k)^4.69 with
  k = 0.50: 1 at half the design load, 2^4.69 ≈ 25.8 at the design load.
  Followed literally.
- C_GA (Eq. 8-7, p. 8-10): (A_E / 0.006)^2.36 with A_E in radians; Figure 8.8
  (p. 8-16) writes it as 12.44 · A_E^2.36 with A_E in degrees, the same curve
  (0.006 rad = 0.344°; tested). Perfect alignment would make the factor, and
  the gear's rate, zero, so a misalignment of zero is refused.
- C_GL (Eq. 8-8): (ν_O / ν_L)^0.54. C_GT (Eq. 8-9): (460 + T_AT) / 620 above
  160 °F, else 1.0.
- C_GV (Eq. 8-10): the AGMA service factor, "Table 8-1" on p. 8-19. The
  chapter numbers two tables 8-1 (the failure modes on p. 8-7 and the service
  factors); the service factor table is the one meant.
- Spline (Eq. 8-11, 8-12, 8-13, p. 8-12 and 8-13): λ_GS,B = 10⁶ / θ per million
  revolutions (a revolution is one cycle, so the rate unit is per million
  cycles), θ = 7.08×10⁻¹⁰ (φ G_L / G_D)^4.56 · A_E^-2.36, φ = 4.85×10³ G_B G_D³ /
  G_T. G_B is printed as "tooth hardness (Brinell), lbs/in²"; a Brinell number
  isn't in lb/in², so the model takes the Brinell hardness number as usually
  quoted (HB, e.g. 300) and says so on the input.
- The figures' axes give the warn ranges: Figure 8.6 V_o/V_d 0 to 1.4, Figure 8.7
  L_O/L_D 0 to 1.3, Figure 8.8 0 to 2.2°, Figure 8.9 ν_O/ν_L 0 to 2.0, Figure 8.10
  −50 to 700 °F. The spline life equation has no stated range.
"""

from backend.scripts.nswc11.common import (
    base, choice, derived, factor, mode, num, positive, record, refuse, table, warn,
)

_FAILURE_MODES = [
    "Pitting: cyclic contact stress through the lubricant film damages the tooth surface",
    "Root fillet or tooth end cracking: tooth bending fatigue",
    "Tooth shear: fracture",
    "Scuffing: lubrication breakdown, then wear and tooth failure",
    "Plastic deformation: heavy load yields the surface, giving vibration and noise",
    "Spalling: fatigue deteriorates the mating surfaces",
    "Tooth bending and contact fatigue",
    "Thermal fatigue: incorrect heat treatment",
    "Abrasive wear: contaminants in the mesh or lubricant score the teeth",
]

_DEG = 0.017453292519943295  # radians in one degree


def _speed_inputs() -> list[dict]:
    return [
        num("V_o", "Operating speed", "rpm", [positive("the gear must turn")], symbol="V_o", page="8-9"),
        num("V_d", "Design speed", "rpm", [positive("a design speed is more than zero")], symbol="V_d", page="8-9"),
    ]


def _condition_inputs() -> list[dict]:
    """Lubricant, temperature and service: the inputs gears and splines share."""
    return [
        num("nu_ratio", "Viscosity of the specified lubricant ÷ viscosity of the one used", "", [
            positive("a ratio of viscosities is more than zero"),
            warn(max=2.0, why="Figure 8.9 covers νO/νL up to 2.0", page="8-17"),
        ], default=1.0, default_basis="neutral", symbol="νO/νL", page="8-11",
            help="1 when the gear runs on the lubricant it was specified for (factor 1)."),
        num("T_AT", "Operating temperature", "°F", [
            refuse(min=-459.67, why="below absolute zero"),
            warn(min=-50, max=700, why="Figure 8.10 covers −50 to 700 °F", page="8-18"),
        ], default=160, default_basis="neutral", symbol="T_AT", page="8-11",
            help="Up to 160 °F the factor is 1."),
        choice("prime_mover", "Prime mover", [
            ("uniform", "Uniform"), ("medium_shock", "Medium shock"), ("heavy_shock", "Heavy shock"),
        ], default="uniform", default_basis="neutral", page="8-19"),
        choice("driven_load", "Character of the load on the driven member", [
            ("uniform", "Uniform"), ("medium_shock", "Medium shock"), ("heavy_shock", "Heavy shock"),
        ], default="uniform", default_basis="neutral", page="8-19"),
    ]


_SPEED_RATIO = derived("speed_ratio", "Operating speed ÷ design speed", "V_o / V_d", "", "V_o/V_d", "8-9",
                       limits=[warn(max=1.4, why="Figure 8.6 covers V_o/V_d up to 1.4", page="8-14")])

_C_GS = factor("C_GS", "Speed against design", "8-9", expr="1.0 + speed_ratio ** 0.7", equation="8-3",
               source="Figure 8.6", words="running faster than its design speed")
_C_GL = factor("C_GL", "Lubricant viscosity", "8-11", expr="nu_ratio ** 0.54", equation="8-8", source="Figure 8.9",
               words="a thinner lubricant than specified")
_C_GT = factor("C_GT", "Operating temperature", "8-11", expr="(460 + T_AT) / 620 if T_AT > 160 else 1.0",
               equation="8-9", source="Figure 8.10", words="running above 160 °F")
_C_GV = factor("C_GV", "AGMA service factor (shock)", "8-19", table=table(["prime_mover", "driven_load"], {
    "uniform": {"uniform": 1.00, "medium_shock": 1.25, "heavy_shock": 1.75},
    "medium_shock": {"uniform": 1.25, "medium_shock": 1.50, "heavy_shock": 2.00},
    "heavy_shock": {"uniform": 1.50, "medium_shock": 1.75, "heavy_shock": 2.25},
}), equation="8-10", source="Table 8-1 (AGMA service factor)", words="shock from the prime mover or the load")


def _gear_inputs() -> list[dict]:
    return [
        *_speed_inputs(),
        num("L_O", "Operating load", "lb", [positive("the gear carries a load")], symbol="L_O", page="8-10"),
        num("L_D", "Design load", "lb", [positive("a design load is more than zero")], symbol="L_D", page="8-10"),
        num("A_E", "Misalignment angle", "rad", [
            positive("the handbook's misalignment factor is zero at perfect alignment, which would make the "
                     "gear's failure rate zero; enter the real misalignment (0.006 rad gives a factor of 1)"),
            warn(max=2.2 * _DEG, why="Figure 8.8 covers 0 to 2.2° (0.0384 rad)", page="8-16"),
        ], default=0.006, default_basis="neutral", symbol="A_E", page="8-10",
            help="In radians (degrees × 0.01745). 0.006 rad (0.34°) gives a factor of 1."),
        *_condition_inputs(),
    ]


def _gear_derived() -> list[dict]:
    return [
        _SPEED_RATIO,
        derived("load_ratio", "Operating load ÷ design load", "L_O / L_D", "", "L_O/L_D", "8-10",
                limits=[warn(max=1.3, why="Figure 8.7 covers L_O/L_D up to 1.3", page="8-15")]),
    ]


def _gear_factors() -> list[dict]:
    return [
        _C_GS,
        factor("C_GP", "Load against design", "8-10", expr="(load_ratio / 0.50) ** 4.69", equation="8-6",
               source="Figure 8.7", words="a heavier load than designed for"),
        factor("C_GA", "Misalignment", "8-10", expr="(A_E / 0.006) ** 2.36", equation="8-7", source="Figure 8.8",
               words="misalignment of gears, shafts and bearings"),
        _C_GL, _C_GT, _C_GV,
    ]


_GEAR_FORMULA = "λ_G = λ_G,B · C_GS · C_GP · C_GA · C_GL · C_GT · C_GV"
_GEAR_WORDS_TAIL = ("scaled by its speed and load against the design, misalignment, its lubricant's viscosity, its "
                    "temperature and the shock from the prime mover and the load (the AGMA service factor). The "
                    "handbook's speed and load factors aren't 1 at the design point: 2.0 at the design speed and "
                    "1 at half the design load.")

RECORDS = [
    record(
        "gear", "Gear (from its design life)", "gear", 8, "8.4 Gear reliability prediction", "8-2", "8-8",
        _GEAR_FORMULA + ", with λ_G,B = 10⁶ · 60 · V_d / design life (revolutions)",
        "A gear's failure rate starts at one failure per design life (10⁸ revolutions unless the maker says "
        "otherwise), turned into hours at its design speed. That is " + _GEAR_WORDS_TAIL,
        inputs=[
            *_gear_inputs(),
            num("life_rev", "Design life", "revolutions", [positive("a life is more than zero")], default=1e8,
                default_basis="handbook", symbol="design life", page="8-9",
                help="The handbook: a gear is usually designed for 10⁸ revolutions."),
        ],
        derived=_gear_derived(),
        modes=[mode("gear", "Gear (wear, fatigue, breakage)",
                    base("λ_G,B", "Base failure rate (design speed × 60 ÷ design life, × 10⁶)", "8-9",
                         expr="1e6 * 60 * V_d / life_rev"),
                    _gear_factors(), symbol="λ_G")],
        failure_modes=_FAILURE_MODES,
        notes="The footnote's RPM in the base rate is taken as the design speed; C_GS scales for the operating "
              "speed (p. 8-9).",
    ),
    record(
        "gear-known-rate", "Gear (from a known base failure rate)", "gear", 8, "8.4 Gear reliability prediction",
        "8-2", "8-8", _GEAR_FORMULA,
        "When the maker (or data for similar gears) gives the gear's failure rate at its specified speed, load, "
        "lubricant and temperature, that rate is " + _GEAR_WORDS_TAIL,
        inputs=[
            num("lambda_GB", "Base failure rate at the design conditions", "failures per million hours",
                [positive("a failure rate is more than zero")], symbol="λ_G,B", page="8-8",
                help="From the maker or failure data for similar gears, in failures per million hours."),
            *_gear_inputs(),
        ],
        derived=_gear_derived(),
        modes=[mode("gear", "Gear (wear, fatigue, breakage)",
                    base("λ_G,B", "Base failure rate (from the maker)", "8-8", expr="lambda_GB"),
                    _gear_factors(), symbol="λ_G")],
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "spline", "Spline", "gear", 8, "8.5 Spline reliability prediction", "8-13", "8-12",
        "λ_GS = λ_GS,B · C_GS · C_GL · C_GT · C_GV, with λ_GS,B = 10⁶ / θ, "
        "θ = 7.08×10⁻¹⁰ (φ G_L / G_D)^4.56 · A_E^−2.36 and φ = 4.85×10³ G_B G_D³ / G_T",
        "A spline's failure rate per million revolutions starts at one over its life in revolutions, which grows "
        "steeply with its length, diameter and tooth hardness and falls with the torque and the misalignment. "
        "That is scaled by its speed against the design, its lubricant's viscosity, its temperature and the "
        "shock from the prime mover and the load.",
        inputs=[
            num("G_L", "Spline length", "in", [positive("a length is more than zero")], symbol="G_L", page="8-12"),
            num("G_D", "Spline diameter", "in", [positive("a diameter is more than zero")], symbol="G_D", page="8-12"),
            num("G_T", "Torque", "in·lb", [positive("the spline carries a torque")], symbol="G_T", page="8-12"),
            num("G_B", "Tooth hardness (Brinell hardness number)", "HB", [positive("a hardness is more than zero")],
                symbol="G_B", page="8-13",
                help="The Brinell number as usually quoted (e.g. 300). The handbook labels it lb/in², which a "
                     "Brinell number isn't; the number is used as given."),
            num("A_E", "Misalignment angle", "rad", [
                positive("the life equation has no value at perfect alignment (the life would be infinite)"),
            ], symbol="A_E", page="8-12", help="In radians (degrees × 0.01745)."),
            *_speed_inputs(),
            *_condition_inputs(),
        ],
        derived=[
            _SPEED_RATIO,
            derived("phi", "Load factor", "4.85e3 * G_B * G_D ** 3 / G_T", "", "φ", "8-12"),
            derived("theta", "Spline life", "7.08e-10 * (phi * G_L / G_D) ** 4.56 * A_E ** -2.36", "revolutions",
                    "θ", "8-12", "8-12"),
        ],
        modes=[mode("spline", "Spline (wear, fretting, tooth failure)",
                    base("λ_GS,B", "Base failure rate (10⁶ ÷ the life in revolutions)", "8-12", expr="1e6 / theta",
                         equation="8-11"),
                    [_C_GS, _C_GL, _C_GT, _C_GV], symbol="λ_GS")],
        rate_unit="per_million_cycles",
        failure_modes=[
            "Wear from fretting, especially in loose splines",
            "Tooth bending and contact fatigue",
            "Tooth shear: fracture",
            "Abrasive wear: contaminants in the lubricant",
        ],
        notes="Per million revolutions (one revolution is one cycle). G_B is taken as the Brinell hardness number "
              "though the handbook labels it lb/in² (p. 8-13).",
    ),
]
