"""Chapter 22, Fluid conductors (Revision A): pipe assembly, Eq. 22-4; tubing
assembly, Eq. 22-5; hose assembly, Eq. 22-6.

Checked against the rendered pages 22-5, 22-8 and 22-12 to 22-14:
- Eq. 22-4 (p. 22-5): λ_P = λ_P,B · C_E, λ_P,B = 0.47 failures per million hours "per
  connection" (the text), C_E from Table 22-2 (1.0, 1.2, 1.4).
- Eq. 22-5 (p. 22-8): λ_T = λ_T,B · C_E, λ_T,B = 1.33 per million hours per connection,
  C_E from Table 22-4 (1.0, 1.2, 1.4).
- Ambiguity (pp. 22-5, 22-8): the base rate is said to be per connection, yet the
  equation for "the total failure rate of the assembly" has no count of connections.
  The model multiplies by the number of connections (a count input); its default, 1,
  is the equation exactly as printed.
- Eq. 22-6 (p. 22-12): λ_H = λ_H,B · C_T · C_E, base 1.85 per million hours. The
  where-list names the base "λ_T,B" (a slip: the equation's symbol is λ_H,B).
- C_T (Figure 22.1, p. 22-13): 1/2^t with t = (T_R − T_O)/18 for T_R − T_O ≤ 40 °F, and
  C_T = 0.21 above 40 °F (the two meet: 2^(−40/18) = 0.214). The axis covers
  T_R − T_O from 60 down to −50 °F (running 50 °F over the rating).
- C_E for hose (Table 22-6, p. 22-14): severe duty is 1.5 (pipe and tubing: 1.4).
- The handbook points to Chapter 3 for the seals in pipe and tube connectors: add them
  as their own parts. Equations 22-1 to 22-3 (stress, burst and working pressure) are
  design checks, not factors, so they aren't in the models.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, num, positive, record, refuse, table, warn,
)

_PIPE_FAILURE_MODES = [
    "Damaged connector: corrosion, wrong torque on a fitting, gasket failure (growing leakage)",
    "Burst from a rapidly applied load or pressure transients",
    "Buckling from too few pipe supports",
    "Bending failure from a bend radius below the allowable",
    "Cracks in rigid pipe from external stress",
    "Leakage from chemical incompatibility, the wrong thread sealant or ultraviolet damage",
    "Fatigue from water hammer",
]

_TUBE_FAILURE_MODES = [
    "Stress cracks from misalignment or poor deburring and flaring",
    "Metal fatigue from vibration",
    "Compressed-air line leaks (misalignment, vibration, over-torqued compression fittings)",
    "Damaged connector from the wrong torque or an impact",
    "Burst from pressure transients or a suddenly applied load",
    "Leakage from chemical incompatibility or the wrong thread sealant",
    "Buckling when a tube support fails",
]

_HOSE_FAILURE_MODES = [
    "Fatigue of metal hose (high flow velocity, flexing corrugations)",
    "Circumferential cracks from twisting the hose when installed",
    "Irregular cracks in metal hose from vibration",
    "Inner tube deterioration from heat or contaminants",
    "Premature failure from excessive fluid temperature",
    "Fracture from too small a bend radius or a bend right behind the coupling",
    "Leakage from long exposure to heat or chemical attack",
    "Inner tube failure from fluid incompatibility",
]


def _connections(page: str) -> dict:
    return num("n_conn", "Number of connections", "", [
        positive("an assembly has at least one connection"),
    ], default=1, default_basis="neutral", page=page,
        help="The handbook's base rate is per connection; 1 is its equation exactly as printed.")


def _environment(page: str, severe: str) -> dict:
    return choice("environment", "Operating environment", [
        ("normal", "Normal duty, ambient conditions, no vibration or shock"),
        ("heavy", "Heavy duty, random fluid pulsations" if severe != "pipe" else
         "Heavy duty, flexible pipe under random pulsations"),
        ("severe", "Severe duty, vibration and shock"),
    ], default="normal", default_basis="neutral", symbol="C_E", page=page)


RECORDS = [
    record(
        "pipe-assembly", "Pipe assembly", "pipe", 22, "22.2.2 Reliability prediction of pipe assembly", "22-4",
        "22-5", "λ_P = λ_P,B · C_E (per connection)",
        "A pipe assembly fails mostly at its joints: each connection has a base rate of 0.47 failures per million "
        "hours, scaled by how rough its duty is (pulsations, vibration and shock).",
        inputs=[_connections("22-5"), _environment("22-5", "pipe")],
        modes=[mode("connections", "Pipe connections",
                    base("λ_P,B", "Base failure rate per connection", "22-5", value=0.47, equation="22-4"), [
                        factor("C_E", "Environment", "22-5", table=table("environment", {
                            "normal": 1.0, "heavy": 1.2, "severe": 1.4}), source="Table 22-2",
                            words="pulsations, vibration and shock"),
                    ], symbol="λ_P", count="n_conn")],
        failure_modes=_PIPE_FAILURE_MODES,
        notes=("The base rate is per connection though Eq. 22-4 shows no count: the model multiplies by the number "
               "of connections (1 by default, the equation as printed). Seals in the connectors are separate parts "
               "(Chapter 3)."),
    ),
    record(
        "tubing-assembly", "Tubing assembly", "pipe", 22, "22.3.2 Reliability prediction of tubing assembly", "22-5",
        "22-8", "λ_T = λ_T,B · C_E (per connection)",
        "A tubing assembly fails mostly at its joints: each connection has a base rate of 1.33 failures per million "
        "hours, scaled by how rough its duty is (pulsations, vibration and shock).",
        inputs=[_connections("22-8"), _environment("22-8", "tube")],
        modes=[mode("connections", "Tubing connections",
                    base("λ_T,B", "Base failure rate per connection", "22-8", value=1.33, equation="22-5"), [
                        factor("C_E", "Environment", "22-8", table=table("environment", {
                            "normal": 1.0, "heavy": 1.2, "severe": 1.4}), source="Table 22-4",
                            words="pulsations, vibration and shock"),
                    ], symbol="λ_T", count="n_conn")],
        failure_modes=_TUBE_FAILURE_MODES,
        notes=("The base rate is per connection though Eq. 22-5 shows no count: the model multiplies by the number "
               "of connections (1 by default, the equation as printed). Seals in the connections are separate "
               "parts (Chapter 3)."),
    ),
    record(
        "hose-assembly", "Hose assembly", "pipe", 22, "22.4.2 Reliability prediction of hose assembly", "22-6",
        "22-12", "λ_H = λ_H,B · C_T · C_E, with C_T = 1/2^((T_R − T_O)/18), or 0.21 when T_R − T_O > 40 °F",
        "A hose assembly's failure rate starts at 1.85 failures per million hours and is scaled by how close it "
        "runs to its rated temperature (it doubles for every 18 °F hotter) and how rough its duty is.",
        inputs=[
            num("T_R", "Hose's rated temperature", "°F", [refuse(min=-459.67, why="below absolute zero")],
                symbol="T_R", page="22-13"),
            num("T_O", "Hose's operating temperature", "°F", [refuse(min=-459.67, why="below absolute zero")],
                symbol="T_O", page="22-13"),
            choice("environment", "Operating environment", [
                ("normal", "Normal duty, ambient conditions, no vibration or shock"),
                ("heavy", "Heavy duty, random fluid pulsations"),
                ("severe", "Severe duty, vibration and shock"),
            ], default="normal", default_basis="neutral", symbol="C_E", page="22-14"),
        ],
        derived=[
            derived("dT", "Rated temperature less operating temperature", "T_R - T_O", "°F", "T_R − T_O", "22-13",
                    limits=[warn(min=-50, max=60, why="Figure 22.1 covers T_R − T_O from −50 to 60 °F",
                                 page="22-13")]),
        ],
        checks=[check("T_O <= T_R", "The hose runs above its rated temperature; the handbook warns this "
                                    "deteriorates the hose and loosens its fittings", "22-9")],
        modes=[mode("hose", "Hose assembly",
                    base("λ_H,B", "Base failure rate of the hose assembly", "22-12", value=1.85, equation="22-6"), [
                        factor("C_T", "Temperature", "22-13", expr="0.21 if dT > 40 else 2 ** (-dT / 18)",
                               source="Figure 22.1", words="running near or over its rated temperature"),
                        factor("C_E", "Environment", "22-14", table=table("environment", {
                            "normal": 1.0, "heavy": 1.2, "severe": 1.5}), source="Table 22-6",
                            words="pulsations, vibration and shock"),
                    ], symbol="λ_H")],
        failure_modes=_HOSE_FAILURE_MODES,
        notes="The handbook's where-list calls the base rate λ_T,B; the equation's symbol, λ_H,B, is used here.",
    ),
]
