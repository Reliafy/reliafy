"""Chapter 7, Bearings (Revision D): rolling element bearings, Eq. 7-4 (from the
load rating) and Eq. 7-5 (from a known L10 life).

Checked against the rendered pages 7-9 to 7-19:
- λ_BE,B is printed as "1 / L10h, failures/million hours" (p. 7-11). L10h is in
  hours, so 1/L10h is per hour; the model uses 10⁶ / L10h to give the stated
  unit (failures per million hours).
- C_CW (Eq. 7-7, p. 7-12, Figure 7.4 p. 7-16): the extracted text is scrambled;
  the page reads C_CW = 1.0 + 25.50·CW − 16.25·CW² for CW ≤ 0.8 % and 11.00
  above, which meet at 0.8 % (1 + 20.4 − 10.4 = 11.0).
- C_t (Figure 7.5, p. 7-17): 1.0 below 183 °C, (T/183)³ from 183 °C.
- C_R (Table 7-2, p. 7-18): 0.223 / [ln(100/R)]^(2/3); the table's values are
  tested against the formula.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, num, positive, record, refuse, table, warn,
)

_FAILURE_MODES = [
    "Fatigue damage: spalling, brinelling, smearing (heavy or prolonged load, excessive speed, shock, vibration)",
    "Noisy bearing: surface fatigue, glazing, microspalling (loss of lubricant, housing out of round, corrosion)",
    "Seizure: cracked rings or rolling elements, skidding (poor heat removal, loss of lubricant, high temperature)",
    "Vibration: scuffing, fretting, pitting (misalignment, unbalanced or excessive load, poor housing support)",
    "Electric currents: pits on raceways and balls",
]

_TYPE = choice("bearing_type", "Bearing type", [("ball", "Ball bearing"), ("roller", "Roller bearing")],
               default="ball", default_basis="typical", page="7-9", help="Sets the load-life exponent y: 3.0 for ball, 3.3 for roller.")

_SERVICE = choice("service", "Type of application (service factor)", [
    ("uniform", "Uniform and steady load, free from shock"),
    ("light_shock", "Normal operation, light shock load"),
    ("moderate_shock", "Moderate shock load"),
    ("heavy_shock", "Heavy shock load"),
    ("extreme_shock", "Extreme and indeterminate shock load"),
    ("precision_gearing", "Precision gearing (ball bearings)"),
    ("commercial_gearing", "Commercial gearing (ball bearings)"),
    ("toothed_belt", "Toothed belts (roller bearings)"),
    ("vee_belt", "Vee belts (roller bearings)"),
    ("flat_belt", "Flat belts (roller bearings)"),
], default="uniform", default_basis="neutral", symbol="C_SF", page="7-18")

_CONTAMINATION = choice("contamination", "Lubricant cleanliness", [
    ("extreme_clean", "Extreme cleanliness: particles about the oil film thickness (laboratory)"),
    ("high_clean", "High cleanliness: oil through a fine filter (10 micron or finer)"),
    ("normal", "Normal cleanliness: slight contamination in the lubricant"),
    ("slight", "Slight contamination: hard particles over 10 micron"),
    ("severe", "Severe contamination: coarse filtering, no integral seals"),
], default="normal", default_basis="typical", symbol="C_C", page="7-19")

_DIAMETER = choice("diameter", "Bearing diameter", [("under_100mm", "Under 100 mm"), ("over_100mm", "Over 100 mm")],
                   default="under_100mm", default_basis="typical", page="7-19")


def _conditions() -> list[dict]:
    """The inputs both bearing models share: reliability, lubricant, water, temperature, service, cleanliness."""
    return [
        num("R", "Reliability the life is quoted at", "%", [
            refuse(min=0, max=100, exclusive=True, why="a reliability is between 0 and 100 %"),
            warn(min=50, max=99, why="Table 7-2 covers 50 % (L50) to 99 % (L1)", page="7-18"),
        ], default=50, default_basis="handbook", symbol="R", page="7-10",
            help="The handbook: use 50 % (the L50 life) to combine with other parts' MTBF-based rates."),
        num("nu_ratio", "Viscosity of the specified lubricant ÷ viscosity of the one used", "", [
            positive("a ratio of viscosities is more than zero"),
            warn(max=2.0, why="Figure 7.3 covers νO/νL up to 2.0", page="7-15"),
        ], default=1.0, default_basis="neutral", symbol="νO/νL", page="7-12",
            help="1 when the bearing runs on the lubricant it was specified for (factor 1)."),
        num("CW", "Water in the lubricant", "%", [
            refuse(min=0, max=100, why="a percentage of water is 0 to 100"),
            warn(max=1.0, why="Figure 7.4 covers 0 to 1 % water", page="7-16"),
        ], default=0, default_basis="neutral", symbol="CW", page="7-12",
            help="0 for a bearing designed for a water-based lubricant (the handbook: then C_CW = 1)."),
        num("T_O", "Bearing operating temperature", "°C", [
            refuse(min=-273.15, why="below absolute zero"),
            warn(min=60, max=260, why="Figure 7.5 covers 60 to 260 °C", page="7-17"),
        ], default=60, default_basis="neutral", symbol="T_O", page="7-13",
            help="Up to 183 °C the factor is 1."),
        _TYPE, _SERVICE, _CONTAMINATION, _DIAMETER,
    ]


def _factors() -> list[dict]:
    return [
        factor("C_R", "Reliability (life adjustment)", "7-18", expr="0.223 / ln(100 / R) ** (2 / 3)",
               source="Table 7-2", words="the reliability its life is quoted at"),
        factor("C_ν", "Lubricant viscosity", "7-12", expr="nu_ratio ** 0.54", equation="7-6", source="Figure 7.3",
               words="its lubricant's viscosity"),
        factor("C_CW", "Water in the lubricant", "7-12",
               expr="1.0 + 25.50 * CW - 16.25 * CW ** 2 if CW <= 0.8 else 11.0", equation="7-7",
               source="Figure 7.4", words="water in its lubricant"),
        factor("C_t", "Operating temperature", "7-17", expr="1.0 if T_O < 183 else (T_O / 183) ** 3",
               source="Figure 7.5", words="its temperature"),
        factor("C_SF", "Service (shock and load)", "7-18", table=table(["service", "bearing_type"], {
            "uniform": {"ball": 1.0, "roller": 1.0},
            "light_shock": {"ball": 1.5, "roller": 1.0},
            "moderate_shock": {"ball": 2.0, "roller": 1.3},
            "heavy_shock": {"ball": 2.5, "roller": 1.7},
            "extreme_shock": {"ball": 3.0, "roller": 2.0},
            "precision_gearing": {"ball": 1.2, "roller": None},
            "commercial_gearing": {"ball": 1.3, "roller": None},
            "toothed_belt": {"ball": None, "roller": 1.2},
            "vee_belt": {"ball": None, "roller": 1.8},
            "flat_belt": {"ball": None, "roller": 3.0},
        }), source="Table 7-3", words="shock in service"),
        factor("C_C", "Lubricant contamination", "7-19", table=table(["contamination", "diameter"], {
            "extreme_clean": {"under_100mm": 1.0, "over_100mm": 1.0},
            "high_clean": {"under_100mm": 1.4, "over_100mm": 1.2},
            "normal": {"under_100mm": 1.8, "over_100mm": 1.4},
            "slight": {"under_100mm": 2.5, "over_100mm": 2.0},
            "severe": {"under_100mm": 5.0, "over_100mm": 3.3},
        }), source="Table 7-4", words="dirt in its lubricant"),
    ]


_Y = derived("y", "Load-life exponent", "3.0 if bearing_type == 'ball' else 3.3", symbol="y", page="7-9",
             equation="7-1")

RECORDS = [
    record(
        "bearing-rolling-load-rating", "Bearing, rolling element (from its load rating)", "bearing", 7,
        "7.6 Bearing failure rate prediction", "7-4", "7-11",
        "λ_BE = λ_BE,B · C_R · C_ν · C_CW · C_t · C_SF · C_C, with λ_BE,B = 10⁶ / L10h and "
        "L10h = (10⁶ / 60n) · (L_S / L_A)^y",
        "A rolling bearing's failure rate starts at one over its L10 life, the hours 90 % of bearings last at the "
        "load and speed it runs at (from its catalogue load rating). That is scaled by the reliability its life is "
        "quoted at, its lubricant's viscosity, water in the lubricant, its temperature, shock in service and dirt "
        "in its lubricant.",
        inputs=[
            num("L_S", "Dynamic load rating (catalogue)", "lbf", [positive("a load rating is more than zero")],
                symbol="L_S", page="7-9"),
            num("F_R", "Radial load", "lbf", [positive("the bearing needs a radial load")], symbol="F_R", page="7-10"),
            num("F_A", "Axial (thrust) load", "lbf", [refuse(min=0, why="a load can't be negative")], default=0, default_basis="handbook",
                symbol="F_A", page="7-10", help="0 for a pure radial load: L_A is then the radial load."),
            num("X", "Radial factor (catalogue)", "", [positive("the radial factor is more than zero")], default=1.0, default_basis="handbook",
                symbol="X", page="7-10", help="1 for a pure radial load."),
            num("Y", "Thrust factor (catalogue)", "", [refuse(min=0, why="the thrust factor can't be negative")],
                default=0, default_basis="handbook", symbol="Y", page="7-10"),
            num("n", "Operating speed", "rpm", [positive("the bearing must turn")], symbol="n", page="7-9"),
            *_conditions(),
        ],
        derived=[
            _Y,
            derived("L_A", "Equivalent radial load", "X * F_R + Y * F_A", "lbf", "L_A", "7-10", "7-3"),
            derived("load_ratio", "Applied load ÷ load rating", "L_A / L_S", "", "L_A/L_S", "7-14",
                    limits=[warn(max=1.4, why="Figure 7.2 covers L_A/L_S up to 1.4", page="7-14")]),
            derived("L10h", "L10 life", "1e6 / (60 * n) * (L_S / L_A) ** y", "hours", "L10h", "7-9", "7-2"),
        ],
        checks=[check("F_A <= 0.3 * F_R", "The axial load F_A should not exceed 30 % of the radial load F_R", "7-10")],
        modes=[mode("bearing", "Bearing (fatigue, wear and what shortens its life)",
                    base("λ_BE,B", "Base failure rate (10⁶ ÷ the L10 life in hours)", "7-11", expr="1e6 / L10h",
                         equation="7-2"),
                    _factors(), symbol="λ_BE")],
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "bearing-rolling-known-l10", "Bearing, rolling element (from a known L10 life)", "bearing", 7,
        "7.6 Bearing failure rate prediction", "7-5", "7-11",
        "λ_BE = λ_BE,B · C_Y · C_R · C_ν · C_CW · C_t · C_SF · C_C, with λ_BE,B = 10⁶ / L10h and "
        "C_Y = (L_A / L_S)^y",
        "When the maker gives the bearing's rated L10 life (tested at its rated load, 90 % reliability), its "
        "failure rate starts at one over that life and is scaled by the load it really carries against its rating, "
        "then by the reliability its life is quoted at, its lubricant's viscosity, water in the lubricant, its "
        "temperature, shock in service and dirt in its lubricant.",
        inputs=[
            num("L10h", "Rated L10 life", "hours", [positive("a life is more than zero")], symbol="L10h", page="7-11"),
            num("L_A", "Equivalent radial load in service", "lbf", [positive("the bearing needs a load")],
                symbol="L_A", page="7-14"),
            num("L_S", "Dynamic load rating (catalogue)", "lbf", [positive("a load rating is more than zero")],
                symbol="L_S", page="7-14"),
            *_conditions(),
        ],
        derived=[
            _Y,
            derived("load_ratio", "Applied load ÷ load rating", "L_A / L_S", "", "L_A/L_S", "7-14",
                    limits=[warn(max=1.4, why="Figure 7.2 covers L_A/L_S up to 1.4", page="7-14")]),
        ],
        modes=[mode("bearing", "Bearing (fatigue, wear and what shortens its life)",
                    base("λ_BE,B", "Base failure rate (10⁶ ÷ the rated L10 life in hours)", "7-11", expr="1e6 / L10h"),
                    [factor("C_Y", "Applied load", "7-14", expr="load_ratio ** y", source="Figure 7.2",
                            words="the load it carries against its rating"), *_factors()],
                    symbol="λ_BE")],
        failure_modes=_FAILURE_MODES,
    ),
]
