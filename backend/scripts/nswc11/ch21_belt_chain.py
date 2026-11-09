"""Chapter 21, Belt and chain drives (Revision B): belt drive, Eq. 21-7, and chain
drive, Eq. 21-11.

Checked against the rendered pages 21-11 to 21-28:
- Eq. 21-7 (p. 21-11): λ_BD = λ_BD,B · C_BL · C_t · C_PD · C_BT · C_BV · C_SV + λ_P,
  λ_BD,B = 40 failures per million hours; λ_P (p. 21-12) = 0.8 for flat pulleys and 1.5
  for grooved pulleys, "for driver and driven pulleys": read as the rate of the pair.
- C_BL (Figure 21.6, p. 21-12): 0.3 + ((hp_O/hp_D)/1.1)^4.2; the axis covers 0.70 to
  2.00. The formula gives 0.97 at a ratio of 1 where the curve reads 1.0: the model
  uses the printed formula.
- C_t (Figure 21.7, p. 21-13): 1/2^t with t = 0 from −20 to 40 °F and t = (40 − T_O)/55
  above 40 °F (so C_t = 2^((T_O − 40)/55), 7.5 at 200 °F as the curve shows). The axis
  covers −20 to 200 °F; standard belts are limited to −20 to 140 °F (pp. 21-3, 21-11).
  The handbook gives no value below −20 °F; the model holds 1.0 there and warns.
- C_PD (Figure 21.8, p. 21-14): 2 · (4.5/PD)², PD the driven pulley's diameter in
  inches; the curve covers 2.5 to 8.5 in.
- C_BT (Table 21-2, p. 21-15) covers ten V-belt sections only (SPZ to SPC, Y to D):
  the handbook gives no C_BT for flat, round or synchronous (timing) belts, so the model
  can't be evaluated for them.
- C_BV (Table 21-3, p. 21-15) is a three-way table (driver torque × service × driven
  load). Every cell is 1.0 + 0.1 for normal service (0.2 continuous) + 0.1 for a high
  torque driver + 0.1 for the second load row, so the model writes it as that sum; the
  tests check all twelve printed cells.
- C_SV (Table 21-4, p. 21-16): driven-machinery shock × source of power.
- Left out: Figure 21.5 (peak tension against failure rate, p. 21-10) is a set of
  curves with no equation and isn't a factor of Eq. 21-7. Equations 21-1 to 21-6 (belt
  speed and tensions) are design checks, not factors.
- Eq. 21-11 (p. 21-23): λ_CD = λ_CD,B · C_CV · C_CS · C_CT · C_CI · C_ST + λ_CS,
  λ_CD,B = 15, λ_CS = 0.8 failures per million hours (driver and driven sprockets).
- C_CS (Table 21-8, p. 21-26): < 50 ft/min 1.0, 50 to 100 ft/min 1.2, over 100 to
  160 ft/min 1.4. The table stops at 160 ft/min although Figure 21.14 rates chains
  to 1,700 rpm (far faster chains): above 160 ft/min the model holds 1.4 and warns.
  Chain speed comes from Eq. 21-8, S = P·N·n/12, with the smaller sprocket's teeth and
  speed (the same sprocket C_ST uses).
- C_CT (Table 21-9, p. 21-27) is in °C (the belt's temperature is in °F, as printed):
  up to 170 °C 1.0, to 200 °C 1.5, to 260 °C 2.0; above 260 °C the table stops (warns).
- C_ST (Figure 21.16, p. 21-28): 19/ST, the curve covering 15 to 25 teeth.
- Table 21-6 (multiple strand factor) adjusts a horsepower rating, not the failure rate,
  so it isn't in the model.
"""

from backend.scripts.nswc11.common import (
    base, choice, derived, factor, mode, num, positive, record, refuse, table, warn,
)

_BELT_FAILURE_MODES = [
    "Belt failure from the wrong operating tension (installation error)",
    "Sidewall cracking from pulley or sheave misalignment",
    "Slippage and rapid wear on a worn pulley or sheave",
    "Hardening and short life from temperature extremes",
    "Wear from chemical contamination or foreign objects in the drive",
    "Heat and wear from belt slip (too little tension)",
    "Broken belt from fatigue (too much tension)",
    "Premature failure from large starting and stopping forces",
    "Normal wear from repeated stressing",
    "Rapid deterioration from heat build-up (poor ventilation)",
    "Sidewall cracking from a pulley loose on its shaft",
]

_CHAIN_FAILURE_MODES = [
    "Turned or galled pins (poor lubrication)",
    "Enlarged holes, broken pins or link plates (overload)",
    "Worn link plate contours (chain rubbing its guide)",
    "Cracked link plates: fatigue or stress corrosion",
    "Broken, cracked or deformed rollers (excessive speed, riding high on the teeth)",
    "Chain climbing the sprocket teeth (slack chain, overload)",
    "Wear from foreign objects in the drive",
    "Excessive noise (interference, loose casing, slack, poor lubrication)",
    "Bushing or roller fatigue",
    "Elongation from link-pin joint wear, then skipping teeth",
    "Sudden failure from tensile fatigue of the side plates",
]

_TORQUE = choice("torque", "Driver (source of power)", [
    ("normal", "Low or normal torque (small AC motors, shunt-wound DC motors, small engines)"),
    ("high", "High or non-uniform torque (single-phase AC motors, series-wound DC motors, large engines)"),
], page="21-15", help="Used by both the operating service factor C_BV and the shock factor C_SV.")

BELT_TYPES = [
    ("SPZ", "Narrow (wedge) SPZ", 0.8), ("SPA", "Narrow (wedge) SPA", 0.48), ("SPB", "Narrow (wedge) SPB", 0.33),
    ("SPC", "Narrow (wedge) SPC", 0.18), ("Y", "Classical Y", 9.09), ("Z", "Classical Z", 4.16),
    ("A", "Classical A", 0.93), ("B", "Classical B", 0.54), ("C", "Classical C", 0.30), ("D", "Classical D", 0.14),
]

CHAIN_LOAD = {"smooth": (1.0, 1.1, 1.3), "some_impact": (1.4, 1.5, 1.7), "large_impact": (1.8, 1.9, 2.1)}
CHAIN_DRIVER = ("smooth", "slight_shock", "moderate_shock")

RECORDS = [
    record(
        "belt-drive", "Belt drive (V-belt)", "belt_chain", 21, "21.5 Failure rate model for belt drive", "21-7",
        "21-11",
        "λ_BD = λ_BD,B · C_BL · C_t · C_PD · C_BT · C_BV · C_SV + λ_P",
        "A belt drive's failure rate starts at 40 failures per million hours for the belt, scaled by how hard it "
        "is loaded against its rating, its temperature, the driven pulley's size, the belt's section, the service "
        "it runs in and the shock it sees; the two pulleys add their own small rate.",
        inputs=[
            num("hp_O", "Power the belt transmits in service", "hp", [positive("the belt must carry a load")],
                symbol="hp_O", page="21-12",
                help="Any unit, the same as the rated power: only the ratio counts (the handbook writes ft·lb/min)."),
            num("hp_D", "Belt's rated (design) power", "hp", [positive("a rating is more than zero")],
                symbol="hp_D", page="21-12", help="The maker's horsepower rating at the belt speed (section 21.4.4)."),
            num("T_O", "Belt operating temperature", "°F", [
                refuse(min=-459.67, why="below absolute zero"),
                warn(min=-20, max=200, why="Figure 21.7 covers −20 to 200 °F", page="21-13"),
                warn(min=-20, max=140, why="standard belts work from −20 to 140 °F; outside it the belt needs "
                                           "special materials", page="21-11"),
            ], default=40, default_basis="neutral", symbol="T_O", page="21-13",
                help="Up to 40 °F the factor is 1. Include heat from slip, tight bends and poor ventilation."),
            num("PD", "Driven pulley pitch diameter", "in", [
                positive("a pulley has a diameter"),
                warn(min=2.5, max=8.5, why="Figure 21.8 covers 2.5 to 8.5 in", page="21-14"),
            ], symbol="PD", page="21-14"),
            choice("belt_type", "Belt section", [(c, lab) for c, lab, _ in BELT_TYPES], symbol="C_BT",
                   page="21-15", help="Table 21-2 gives V-belt sections only; flat, round and timing belts have no "
                                      "value in the handbook."),
            _TORQUE,
            choice("service", "Hours of service", [
                ("intermittent", "Intermittent service"), ("normal", "Normal service"),
                ("continuous", "Continuous service"),
            ], page="21-15"),
            choice("driven_load", "Driven load", [
                ("light", "Blowers, small fans, centrifugal pumps, compressors"),
                ("heavier", "Generators, machine tools, rotary pumps"),
            ], page="21-15"),
            choice("shock", "Shock from the driven machinery", [
                ("none", "No shock"), ("light", "Light shock"), ("medium", "Medium shock"), ("heavy", "Heavy shock"),
            ], symbol="C_SV", page="21-16"),
            choice("pulley_type", "Pulleys", [("flat", "Flat pulleys"), ("grooved", "Grooved pulleys (sheaves)")],
                   symbol="λ_P", page="21-12"),
        ],
        derived=[
            derived("hp_ratio", "Power in service ÷ rated power", "hp_O / hp_D", "", "hp_O/hp_D", "21-12",
                    limits=[warn(min=0.7, max=2.0, why="Figure 21.6 covers 0.70 to 2.00", page="21-12")]),
        ],
        modes=[
            mode("belt", "Belt", base("λ_BD,B", "Base failure rate of the belt", "21-11", value=40.0,
                                      equation="21-7"), [
                factor("C_BL", "Belt loading", "21-12", expr="0.3 + (hp_ratio / 1.1) ** 4.2", source="Figure 21.6",
                       words="power carried against its rating"),
                factor("C_t", "Belt temperature", "21-13", expr="1.0 if T_O <= 40 else 2 ** ((T_O - 40) / 55)",
                       source="Figure 21.7", words="a hotter belt"),
                factor("C_PD", "Pulley diameter", "21-14", expr="2 * (4.5 / PD) ** 2", source="Figure 21.8",
                       words="a smaller driven pulley"),
                factor("C_BT", "Belt type", "21-15", table=table("belt_type", {c: v for c, _, v in BELT_TYPES}),
                       source="Table 21-2", words="its section"),
                factor("C_BV", "Operating service", "21-15",
                       expr="(1.0 if service == 'intermittent' else 1.1 if service == 'normal' else 1.2)"
                            " + (0.1 if torque == 'high' else 0.0) + (0.1 if driven_load == 'heavier' else 0.0)",
                       source="Table 21-3", words="longer hours, a rougher driver and a heavier load"),
                factor("C_SV", "Shock environment", "21-16", table=table(["shock", "torque"], {
                    "none": {"normal": 1.1, "high": 1.2},
                    "light": {"normal": 1.2, "high": 1.3},
                    "medium": {"normal": 1.3, "high": 1.5},
                    "heavy": {"normal": 1.4, "high": 1.7},
                }), source="Table 21-4", words="shock from the driven machine"),
            ], symbol="λ_BD,B·C"),
            mode("pulleys", "Driver and driven pulleys",
                 base("λ_P", "Failure rate of the driver and driven pulleys", "21-12",
                      table=table("pulley_type", {"flat": 0.8, "grooved": 1.5}), equation="21-7"),
                 symbol="λ_P"),
        ],
        failure_modes=_BELT_FAILURE_MODES,
        notes=("Table 21-2 gives belt type factors for V-belt sections only, so flat, round and synchronous belts "
               "can't be evaluated. Figure 21.5 (peak tension) has no equation and isn't part of Eq. 21-7."),
    ),
    record(
        "chain-drive", "Chain drive (roller chain)", "belt_chain", 21, "21.9 Failure rate model for chain drive",
        "21-11", "21-23",
        "λ_CD = λ_CD,B · C_CV · C_CS · C_CT · C_CI · C_ST + λ_CS, with chain speed S = P·N·n/12",
        "A chain drive's failure rate starts at 15 failures per million hours for the chain, scaled by the shock "
        "from its driver and load, the chain's speed, its temperature, how it's lubricated and the teeth on the "
        "smaller sprocket; the sprockets add 0.8.",
        inputs=[
            num("P", "Chain pitch", "in", [positive("a chain has a pitch")], symbol="P", page="21-21"),
            num("n", "Speed of the smaller sprocket", "rpm", [positive("the drive must turn")], symbol="n",
                page="21-21"),
            num("ST", "Teeth on the smaller sprocket", "teeth", [
                positive("a sprocket has teeth"),
                warn(min=15, max=25, why="Figure 21.16 covers 15 to 25 teeth", page="21-28"),
            ], default=19, default_basis="neutral", symbol="ST", page="21-28", help="19 teeth gives a factor of 1."),
            num("T_C", "Chain operating temperature", "°C", [
                refuse(min=-273.15, why="below absolute zero"),
                warn(max=260, why="Table 21-9 covers up to 260 °C", page="21-27"),
            ], default=20, default_basis="neutral", symbol="T", page="21-27",
                help="Up to 170 °C the factor is 1."),
            choice("driver", "Driver sprocket's power source", [
                ("smooth", "Smooth running (electric motors, turbines)"),
                ("slight_shock", "Slight shock (motors with frequent starts, engines with hydraulic couplings)"),
                ("moderate_shock", "Moderate shocks (engines with mechanical couplings)"),
            ], default="smooth", default_basis="neutral", symbol="C_CV", page="21-26"),
            choice("load", "Type of driven load", [
                ("smooth", "Smooth (conveyors with small load changes, centrifugal blowers)"),
                ("some_impact", "Some impact (conveyors with some load changes, centrifugal compressors, marine "
                                "engines)"),
                ("large_impact", "Large impact (machines with reversing or large impact loads)"),
            ], default="smooth", default_basis="neutral", symbol="C_CV", page="21-26"),
            choice("lubrication", "Lubrication", [
                ("manual", "Manual (oiler or brush)"), ("drip", "Drip"), ("bath", "Oil bath"),
                ("stream", "Oil stream (forced)"),
            ], default="drip", default_basis="neutral", symbol="C_CI", page="21-27"),
        ],
        derived=[
            derived("S", "Chain speed", "P * ST * n / 12", "ft/min", "S", "21-21", "21-8",
                    limits=[warn(max=160, why="Table 21-8 covers chain speeds up to 160 ft/min", page="21-26")]),
        ],
        modes=[
            mode("chain", "Chain", base("λ_CD,B", "Base failure rate of the chain", "21-23", value=15.0,
                                        equation="21-11"), [
                factor("C_CV", "Operating service", "21-26", table=table(["load", "driver"], {
                    ld: dict(zip(CHAIN_DRIVER, vals)) for ld, vals in CHAIN_LOAD.items()}),
                    source="Table 21-7", words="shock from the driver and the load"),
                factor("C_CS", "Chain speed", "21-26", expr="1.0 if S < 50 else 1.2 if S <= 100 else 1.4",
                       source="Table 21-8", words="a faster chain"),
                factor("C_CT", "Chain temperature", "21-27", expr="1.0 if T_C <= 170 else 1.5 if T_C <= 200 else 2.0",
                       source="Table 21-9", words="a hotter chain"),
                factor("C_CI", "Lubrication method", "21-27", table=table("lubrication", {
                    "manual": 1.5, "drip": 1.0, "bath": 0.8, "stream": 0.7}),
                    source="Table 21-10", words="poorer lubrication"),
                factor("C_ST", "Sprocket teeth", "21-28", expr="19 / ST", source="Figure 21.16",
                       words="fewer teeth on the smaller sprocket"),
            ], symbol="λ_CD,B·C"),
            mode("sprockets", "Driver and driven sprockets",
                 base("λ_CS", "Failure rate of the driver and driven sprockets", "21-23", value=0.8,
                      equation="21-11"), symbol="λ_CS"),
        ],
        failure_modes=_CHAIN_FAILURE_MODES,
        notes=("Table 21-8 (chain speed) stops at 160 ft/min, far below the speeds the handbook's horsepower charts "
               "cover: above it the factor is held at 1.4 with a warning."),
    ),
]
