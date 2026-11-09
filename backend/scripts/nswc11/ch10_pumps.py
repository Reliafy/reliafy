"""Chapter 10, Pumps (Revision C): the fluid driver, Eq. 10-3, and the pump
assembly, Eq. 10-2.

Checked against the rendered pages 10-10 to 10-19:
- Eq. 10-2 (p. 10-10): λ_P = λ_SE + λ_SH + λ_BE + λ_CA + λ_FD, every term in
  failures per million operating hours. The shaft's own model (Chapter 20) is
  per million cycles; the handbook adds it here as is, and so does the model
  (said in the mode's note).
- λ_SE (Section 10.4) is "all pump seals": O-rings and gaskets (Chapter 3) and
  the mechanical seals. The assembly includes the mechanical seals (× their
  number); static seals and gaskets, each with its own conditions, are left to
  be added as their own Chapter 3 records (said in the record's notes).
- λ_CA = 0.01 failures per million hours (p. 10-13).
- C_PF (Table 10-3, p. 10-18; Figure 10.4, p. 10-16). The table heads itself
  "Equations for Figure 10.5" but they are Figure 10.4's. For the ordinary
  volute from 0.1 to 1.0 the page prints the last term as 1.77 (Q/Q_r)², the
  same power as the term before; read from Figure 10.4 at Q/Q_r = 0.5, 0.6 and
  0.7 the curve is at about 7.25, 6.2 and 5.05, which the cube gives (7.21,
  6.18, 5.02) and the square doesn't (7.43, 6.44, 5.28). The model uses the
  cube. Between 1.0 and 1.1 the table gives 1.0, though the figure's curve dips
  to about 0.6 there; the model follows the table. The range is 0.1 to 1.7
  (the table's and the figure's).
- C_PS (Eq. 10-4, p. 10-15): k (V_O / V_D)^1.3, k = 5.00, so 5 at the
  maximum allowable design speed; Figure 10.5 covers V_O/V_D 0.2 to 2.0.
- C_C (Eq. 10-5): 0.6 + 0.05 F_AC, F_AC the filter size in microns (1 at 8 µm).
- C_SF (Table 10-5, p. 10-19) and λ_FD,B (Table 10-4, p. 10-19), as printed.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, non_negative, num, positive, record, table, uses, warn,
)

_FAILURE_MODES = [
    "Cavitation: low suction head or NPSH erodes the impeller, rotor or casing, with noise and vibration",
    "Corrosion and erosion: the wrong fluid, or too much flow for it",
    "Shaft deflection and unbalance: radial thrust, impeller wear, torsional vibration",
    "External leakage: worn mechanical seal, scored shaft sleeve, badly packed stuffing box",
    "Air leaking through a gasket or stuffing box: loss of head",
    "Mechanical noise: debris, an unbalanced impeller, a bent shaft, a worn bearing, a loose foundation",
    "Suction or discharge head out of range: clogged pipes, part-open valves",
    "Worn or broken impeller, clogged suction line: contaminants, the wrong flow",
    "Thrust bearing failure: excessive axial load",
    "Pressure surges and fluid overheating (displacement pumps)",
]

_CENTRIFUGAL = ("centrifugal_axial", "centrifugal_mixed_radial", "centrifugal_peripheral")

_DRIVER = choice("driver", "Fluid driver (Table 10-4)", [
    ("centrifugal_axial", "Centrifugal: axial flow impeller (closed or open)"),
    ("centrifugal_mixed_radial", "Centrifugal: mixed or radial flow impeller (open, semi-open or closed)"),
    ("centrifugal_peripheral", "Centrifugal: peripheral (single or multi-stage)"),
    ("recip_piston", "Displacement, reciprocating: piston or plunger"),
    ("recip_diaphragm", "Displacement, reciprocating: diaphragm"),
    ("rotary_vane", "Displacement, rotary (single rotor): vane"),
    ("rotary_piston", "Displacement, rotary (single rotor): piston"),
    ("rotary_gear", "Displacement, rotary (multiple rotor): gear"),
    ("rotary_lobe", "Displacement, rotary (multiple rotor): lobe"),
    ("rotary_screw", "Displacement, rotary (multiple rotor): screw"),
], symbol="λ_FD,B", page="10-19")

_CASING = choice("casing", "Casing (for the flow factor)", [
    ("ordinary_volute", "Centrifugal, ordinary volute casing"),
    ("modified_volute", "Centrifugal, modified volute casing"),
    ("double_volute", "Centrifugal, double volute casing"),
    ("displacement", "Displacement pump"),
], symbol="C_PF", page="10-18")

_C_PF = (
    "(9.94 - 0.90 * q - 10.00 * q ** 2 + 1.77 * q ** 3 if q <= 1.0 else 1.0 if q < 1.1 else "
    "-30.60 + 36.00 * q - 4.50 * q ** 2 - 2.20 * q ** 3) if casing == 'ordinary_volute' else "
    "5.31 - 0.55 * q - 12.00 * q ** 2 + 12.60 * q ** 3 - 4.63 * q ** 4 + 0.68 * q ** 5 "
    "if casing == 'modified_volute' else "
    "1.03 - 0.30 * q + 0.04 * q ** 2 if casing == 'double_volute' else 0.80 + 1.1 * q"
)

RECORDS = [
    record(
        "pump-fluid-driver", "Pump fluid driver (impeller, rotor, piston or diaphragm)", "pump", 10,
        "10.8 Failure rate model for fluid driver", "10-3", "10-13",
        "λ_FD = λ_FD,B · C_PF · C_PS · C_C · C_SF",
        "A pump's fluid driver starts at a base rate for its type (impeller, vane, gear, lobe, screw, piston or "
        "diaphragm). That is scaled by how far its flow is from the pump's rated flow (worst for an ordinary volute "
        "casing), its speed against the maximum allowable, the filter size and the hours a day it runs under "
        "shock.",
        inputs=[
            _DRIVER, _CASING,
            num("Q", "Actual operating flow", "gpm", [positive("the pump moves fluid")], symbol="Q", page="10-18"),
            num("Q_r", "Maximum specified pump flow", "gpm", [positive("a rated flow is more than zero")],
                symbol="Q_r", page="10-18"),
            num("V_O", "Operating speed", "rpm", [positive("the pump must run")], symbol="V_O", page="10-15"),
            num("V_D", "Maximum allowable design speed", "rpm", [positive("a design speed is more than zero")],
                symbol="V_D", page="10-15"),
            num("F_AC", "Filter size", "µm", [non_negative("a filter size can't be negative")], default=8,
                default_basis="neutral", symbol="F_AC", page="10-15", help="8 µm gives a factor of 1."),
            choice("duty", "Duration of service", [
                ("occasional", "Occasional (half an hour a day)"), ("under_3h", "Less than three hours a day"),
                ("3_to_10h", "3 to 10 hours a day"), ("over_10h", "Over 10 hours a day"),
            ], default="3_to_10h", default_basis="neutral", symbol="C_SF", page="10-19"),
            choice("load", "Load", [
                ("uniform", "Uniform"), ("moderate_shock", "Moderate shock"), ("heavy_shock", "Heavy shock"),
                ("extreme_shock", "Extreme shock"),
            ], default="uniform", default_basis="neutral", symbol="C_SF", page="10-19"),
        ],
        derived=[
            derived("q", "Operating flow ÷ maximum specified flow", "Q / Q_r", "", "Q/Q_r", "10-18",
                    limits=[warn(min=0.1, max=1.7, why="Table 10-3 and Figure 10.4 cover Q/Q_r 0.1 to 1.7",
                                 page="10-18")]),
            derived("speed_ratio", "Operating speed ÷ maximum allowable speed", "V_O / V_D", "", "V_O/V_D", "10-15",
                    limits=[warn(min=0.2, max=2.0, why="Figure 10.5 covers V_O/V_D 0.2 to 2.0", page="10-17")]),
        ],
        checks=[check(" or ".join(f"driver == '{d}'" for d in _CENTRIFUGAL) + " or casing == 'displacement'",
                      "A displacement pump's driver takes the displacement flow curve (casing: displacement pump)",
                      "10-18"),
                check("not (" + " or ".join(f"driver == '{d}'" for d in _CENTRIFUGAL) + ") or casing != 'displacement'",
                      "A centrifugal pump's driver takes the curve for its volute casing, not the displacement one",
                      "10-18")],
        modes=[mode("fluid_driver", "Fluid driver (wear, erosion, cavitation damage)",
                    base("λ_FD,B", "Base failure rate for the driver type", "10-19", source="Table 10-4",
                         table=table("driver", {
                             "centrifugal_axial": 0.20, "centrifugal_mixed_radial": 0.12,
                             "centrifugal_peripheral": 0.20, "recip_piston": 1.18, "recip_diaphragm": 0.58,
                             "rotary_vane": 0.4, "rotary_piston": 1.05, "rotary_gear": 0.75, "rotary_lobe": 0.45,
                             "rotary_screw": 0.58})),
                    [
                        factor("C_PF", "Flow against rated flow", "10-18", expr=_C_PF, source="Table 10-3, Figure 10.4",
                               words="running away from its best flow"),
                        factor("C_PS", "Operating speed", "10-15", expr="5.00 * speed_ratio ** 1.3", equation="10-4",
                               source="Figure 10.5", words="running faster"),
                        factor("C_C", "Contaminants (filter size)", "10-15", expr="0.6 + 0.05 * F_AC",
                               equation="10-5", words="a coarser filter"),
                        factor("C_SF", "Service (hours a day and shock)", "10-19", table=table(["duty", "load"], {
                            "occasional": {"uniform": 1.00, "moderate_shock": 1.00, "heavy_shock": 1.00,
                                           "extreme_shock": 1.25},
                            "under_3h": {"uniform": 1.00, "moderate_shock": 1.00, "heavy_shock": 1.25,
                                         "extreme_shock": 1.50},
                            "3_to_10h": {"uniform": 1.00, "moderate_shock": 1.25, "heavy_shock": 1.50,
                                         "extreme_shock": 1.75},
                            "over_10h": {"uniform": 1.25, "moderate_shock": 1.50, "heavy_shock": 1.75,
                                         "extreme_shock": 2.00},
                        }), source="Table 10-5", words="long hours and shock loads"),
                    ], symbol="λ_FD")],
        failure_modes=_FAILURE_MODES,
        notes="Table 10-3's ordinary-volute curve below Q/Q_r = 1.0 uses (Q/Q_r)³ for its last term, read from "
              "Figure 10.4; the page prints a square (p. 10-18).",
    ),
    record(
        "pump", "Pump (assembly)", "pump", 10, "10.3 Model development", "10-2", "10-10",
        "λ_P = λ_SE + λ_SH + λ_BE + λ_CA + λ_FD",
        "A pump's failure rate is the sum of its parts: its mechanical seals, its shaft, its bearings, its casing "
        "(a small fixed rate) and its fluid driver, each from its own model.",
        inputs=[
            num("n_SE", "Number of mechanical seals", "", [positive("a pump has at least one seal")],
                symbol="n_SE", page="10-11"),
            num("n_BE", "Number of bearings", "", [positive("a pump has at least one bearing")], symbol="n_BE",
                page="10-12", help="All alike: the bearing model's rate × this number."),
        ],
        modes=[
            uses("seals", "Mechanical seals", "seal-mechanical", symbol="λ_SE", count="n_SE"),
            uses("shaft", "Shaft", "shaft", symbol="λ_SH",
                 note="The shaft's model (Chapter 20) is in failures per million cycles; Eq. 10-2 adds it to the "
                      "per-hour rates as it is, and so does this model."),
            uses("bearings", "Bearings", "bearing-rolling-load-rating", symbol="λ_BE", count="n_BE"),
            mode("casing", "Casing", base("λ_CA", "Casing failure rate", "10-13", value=0.01), symbol="λ_CA"),
            uses("fluid_driver", "Fluid driver", "pump-fluid-driver", symbol="λ_FD"),
        ],
        failure_modes=_FAILURE_MODES,
        notes="λ_SE here is the mechanical seals; the handbook's λ_SE also counts the pump's O-rings and gaskets "
              "(Chapter 3), which are added as their own records (p. 10-11). The shaft's per-cycle rate is added "
              "as the handbook does (p. 10-10).",
    ),
]
