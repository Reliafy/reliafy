"""Chapter 6, Valve assemblies (Revision E): the poppet assembly (Eq. 6-6), the
sliding action valve (Eq. 6-14), the housing (Eq. 6-15) and the valve assemblies
that add up their parts (Eqs. 6-1 and 6-2).

Checked against the rendered pages 6-3 to 6-32:
- C_P (Figure 6.6, p. 6-20): ((P1 − P2)/3000)², given "for P1 − P2 > 50 psi" with no
  formula below; the model uses the same formula and warns below 50 psi.
- C_Q (Figure 6.7, p. 6-21): as Chapter 3 (4.2 − 79·Q_f up to 0.03 in³/min,
  0.055/Q_f above).
- C_F (Figure 6.8, p. 6-22): f^1.65/353, f in μin (no lower branch, unlike Chapter
  3's static seal); the figure covers 5 to 125 μin.
- C_S (Eq. 6-12, Figure 6.9, p. 6-23): 0.26 · (9000/S_S)^1.5.
- C_DT (Figure 6.10, p. 6-24): 1.1·D_S + 0.32; the extracted text reads "0.3 ... 2"
  but the page reads 0.32 (the line passes 1.0 at 0.62 in).
- C_SW (Figure 6.11, p. 6-25): 3.55 − 24.52·L_W + 72.99·L_W² − 85.75·L_W³ up to
  0.34 in, 0.25 above (the cubic gives 0.28 at 0.34: a small step, as printed).
- C_B (Figure 6.12, p. 6-26): 0.42 below 500 μin, B²/(6×10⁵) above (0.417 at 500).
- C_DS (Figure 6.13, p. 6-27): 0.615·D_SP. C_W (Figure 6.14, p. 6-28): 1 + F_L².
- C_μ (Table 6-7, p. 6-32): "the actual friction coefficient is used" (p. 6-19):
  C_μ is the coefficient itself; the table gives typical values.
- C_ν (Table 6-6, p. 6-31): the same table as Chapter 3's Table 3-3 except carbon
  dioxide, which Table 6-6 prints as 0.7 to 0.9. Carbon dioxide's viscosity
  (about 0.015 cP) gives ν_o/ν ≈ 550, matching Table 3-3's 599.9 to 352.1, so the
  model uses Table 3-3's row (and, as there, leaves out MIL-H-83282 above 250 °F).
  Section 6.4.4 says to divide a kinematic viscosity by the density; Section 6.3.4
  (and 3.2.3.5) say multiply, which is right (dynamic = kinematic × density).
- C_N (Table 6-5, p. 6-30): as Chapter 3's Table 3-4.
- The poppet's base rate (1.40) and the sliding valve's (1.25) are per million
  operations; the housing's 0.01 is per million hours (p. 6-19).
- Eqs. 6-1 and 6-2 (p. 6-3) add the valve's parts and state every term, and the
  total, in failures per million operations, though the seal, spring and solenoid
  models of Chapters 3 to 5 and the housing give failures per million hours. The
  handbook's own rule for mixed parts (pp. 12-10, 12-16) and its only worked
  combination (Chapter 1's valve, Table 1-1 and Figure 1.3, p. 1-12/1-13) put
  every part on one time basis first: the poppet or spool (per operation) times
  the valve's operations an hour, then add the per-hour parts. The assembly
  records do that and are per million hours, with the operations an hour asked
  for once (it also sets the spring's cycle rate and the solenoid's use rate).
  The conditions the poppet (or spool) and the seals share (pressures, fluid,
  temperature, contamination and flow) are entered once on the assembly.
- Chapter 1's worked poppet (Table 1-1, p. 1-12, λ_P = 0.35) uses the leakage form
  of p. 1-7 (Eq. 6-4 inside Eq. 6-3) and multiplies by 0.5 operations an hour; the
  tests show it and what Eq. 6-6 gives for the same poppet.
- Left out: Eq. 6-5 (only "a function of" Z, α, n, Q, d, T, no formula).
"""

from backend.scripts.nswc11.ch03_seals import NU_O_CP, _FLUIDS, _SOURCES, _n10_expr, _nu_range_expr, _nu_table_expr
from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, num, non_negative, positive, record, refuse, uses, warn,
)

_VALVE_MODES = [
    "Seal leakage: embrittlement, installation damage, wear, distortion, dynamic instability",
    "Worn or damaged poppet seat: contaminants (internal leakage, poor pressure control)",
    "Damaged valve stem: vibration, shock (slow response, fails to open or close)",
    "Worn or damaged spool: contaminants, misalignment (internal leakage)",
    "Sticking piston or spool: contaminants, lost lubrication, trapped air, high temperature",
    "Broken spring or damaged spring ends: fatigue",
    "Inoperative solenoid: open coil, misalignment with the spool or stem",
    "Cracked fitting or housing: fatigue, shock, vibration (external leakage)",
]
_POPPET_MODES = [
    "Internal leakage: worn poppet and seat from contaminants",
    "Poor response: sticking or jammed poppet (side loading, wrong spring force, contaminants)",
    "External leakage: worn poppet stem from contaminants",
]
_SLIDING_MODES = [
    "Internal leakage: worn spool and sleeve (contaminants, side loading)",
    "Poor response: sticking sleeve (side loading, wrong spring force, contaminants, silting)",
    "External leakage: worn gasket or seal",
    "Port fails to open: jammed sleeve (excessive side loading, contaminants)",
]


def _pressure() -> list[dict]:
    return [
        num("P1", "Upstream pressure", "psi", [non_negative("a pressure can't be negative")], symbol="P1", page="6-10"),
        num("P2", "Downstream pressure", "psi", [non_negative("a pressure can't be negative")], default=14.7,
            default_basis="handbook", symbol="P2", page="6-10",
            help="Atmospheric for a valve venting to air (the handbook: upstream minus downstream pressure)."),
    ]


def _fluid_inputs() -> list[dict]:
    return [
        num("T_O", "Fluid temperature", "°F", [refuse(min=-459.67, why="below absolute zero")], symbol="T", page="6-31"),
        choice("fluid", "Fluid", [*[(c, lab) for c, lab, _ in _FLUIDS], ("other", "Another fluid (give its viscosity)")],
               default="other", default_basis="neutral", page="6-31",
               help="Table 6-6's fluids at the fluid temperature. 'Another fluid' uses the viscosity below (its "
                    "default, 8.27 cP, is the handbook's reference viscosity: factor 1)."),
        num("nu_cP", "Dynamic viscosity of the fluid at its temperature (another fluid only)", "cP",
            [positive("a viscosity is more than zero")], default=NU_O_CP, default_basis="neutral", symbol="ν",
            page="6-31", help="Only used for 'another fluid'. 1 lbf·min/in² = 4.137×10⁸ cP."),
        choice("source", "Upstream component producing contaminants", [(c, lab) for c, lab, _ in _SOURCES],
               symbol="N10", page="6-30",
               help="Table 6-5: particles under 10 μm per hour per rated gpm (piston pump 0.017, gear pump 0.019, "
                    "vane pump 0.006, cylinder 0.008, sliding valve 0.0004, hose 0.0013)."),
        num("C_o", "System filter size", "μm", [positive("a filter size is more than zero")], default=10,
            default_basis="handbook", symbol="C_o", page="6-30",
            help="10 μm is the handbook's standard system filter (factor (C_o/10)³ = 1)."),
        num("FR", "Rated flow rate", "gpm", [positive("the flow rate is more than zero")], symbol="FR", page="6-30"),
        num("F_L", "Actual flow rate ÷ the maker's rated flow", "", [
            non_negative("a flow ratio can't be negative"),
            warn(min=0.1, max=1.4, why="Figure 6.14 covers 0.1 to 1.4", page="6-28"),
        ], symbol="F_L", page="6-28"),
    ]


def _leakage() -> dict:
    return num("Q_f", "Leakage that counts as a valve failure", "in³/min", [
        positive("an allowable leakage is more than zero"),
        warn(min=0.01, max=0.14, why="Figure 6.7 covers 0.01 to 0.14 in³/min", page="6-21"),
    ], symbol="Q_f", page="6-10")


def _shared_derived() -> list[dict]:
    return [
        derived("dP", "Pressure across the valve (P1 − P2)", "P1 - P2", "psi", "P1 − P2", "6-20",
                limits=[warn(min=50, max=10000, why="Figure 6.6's formula is given for 50 to 10,000 psi",
                             page="6-20")]),
        derived("C_nu_table", "C_ν read from Table 6-6", _nu_table_expr(), "", "C_ν", "6-31"),
        derived("N10", "Particles under 10 μm per hour per rated gpm", _n10_expr(), "", "N10", "6-30"),
    ]


def _shared_checks() -> list[dict]:
    return [
        check("P1 >= P2", "The upstream pressure P1 should be at least the downstream pressure P2", "6-20",
              severity="refuse"),
        check(_nu_range_expr(), "Table 6-6 has no reliable value for this fluid at this temperature (it prints "
              "'---'; for MIL-H-83282 above 250 °F its values look misprinted): choose 'another fluid' and give its "
              "viscosity", "6-31", severity="refuse"),
    ]


def _shared_factors() -> list[dict]:
    return [
        factor("C_P", "Fluid pressure", "6-20", expr="(dP / 3000) ** 2", source="Figure 6.6",
               words="more pressure across the valve"),
        factor("C_Q", "Allowable leakage", "6-21", expr="4.2 - 79 * Q_f if Q_f <= 0.03 else 0.055 / Q_f",
               source="Figure 6.7", words="a tighter allowable leakage"),
    ]


def _cnu_cn_cw() -> list[dict]:
    return [
        factor("C_ν", "Fluid viscosity and temperature", "6-31",
               expr=f"{NU_O_CP!r} / nu_cP if fluid == 'other' else C_nu_table", source="Table 6-6, Figure 6.15",
               words="a thinner fluid (gases most of all)"),
        factor("C_N", "Contaminants", "6-30", expr="(C_o / 10) ** 3 * FR * N10", source="Table 6-5",
               words="a coarser filter, more flow, a dirtier upstream component"),
        factor("C_W", "Flow rate", "6-28", expr="1.0 + F_L ** 2", source="Figure 6.14",
               words="more flow for its rating"),
    ]


_ASSEMBLY_NOTE = ("{where} gives this part in failures per million hours; it is added as it is (Eq. {eq}, p. 6-3, "
                  "with every part on one time basis as Chapter 1's worked valve does, p. 1-12).")
_OPS_SCALE_NOTE = ("Per million operations × the valve's operations an hour, so it adds to the per-hour parts (the "
                   "handbook's rule, pp. 12-10 and 12-16; Chapter 1's worked valve converts its poppet the same way, "
                   "Table 1-1, p. 1-12).")

#: The conditions the moving part and the seals share, entered once on the assembly.
_SHARED = ("P1", "P2", "T_O", "fluid", "nu_cP", "source", "C_o", "FR")


def _assembly_inputs() -> list[dict]:
    ops = num("ops_per_hour", "Valve operations per hour", "per hour", [
        positive("a valve that never operates isn't rated by this model"),
    ], symbol="ops/h", page="6-3",
        help="How often the valve opens and closes. It turns the poppet's (or spool's) rate per million operations "
             "into one per hour, and sets the return spring's cycle rate and the solenoid's use rate (one cycle "
             "per operation).")
    shared = [i for i in (*_pressure(), *_fluid_inputs()) if i["name"] in _SHARED]
    return [
        ops, *shared,
        num("n_seals", "Number of seals", "", [non_negative("a count can't be negative")], default=1,
            default_basis="typical", page="6-3", help="Seals rated with the gasket and static seal model."),
        num("n_springs", "Number of springs", "", [non_negative("a count can't be negative")], default=1,
            default_basis="typical", page="6-3"),
        num("n_solenoids", "Number of solenoids", "", [non_negative("a count can't be negative")], default=1,
            default_basis="typical", page="6-3", help="0 for a valve worked by hand or by pressure (or a check valve)."),
    ]


def _assembly_modes(moving: dict, eq: str) -> list[dict]:
    shared = {n: n for n in _SHARED}
    return [
        moving,
        uses("seal", "Seals", "seal-static", symbol="λ_SE", count="n_seals", bind=shared,
             note=_ASSEMBLY_NOTE.format(eq=eq, where="Chapter 3")),
        uses("spring", "Return spring" if eq == "6-1" else "Springs", "spring-compression", symbol="λ_SP",
             count="n_springs", bind={"cycle_rate": "ops_per_hour / 60"},
             note=_ASSEMBLY_NOTE.format(eq=eq, where="Chapter 4")),
        uses("solenoid", "Solenoid", "solenoid", symbol="λ_SO", count="n_solenoids",
             bind={"ops_per_min": "ops_per_hour / 60"}, note=_ASSEMBLY_NOTE.format(eq=eq, where="Chapter 5")),
        uses("housing", "Housing", "valve-housing", symbol="λ_HO", note=_ASSEMBLY_NOTE.format(eq=eq, where="Section 6.5")),
    ]

RECORDS = [
    record(
        "valve-poppet", "Valve poppet assembly", "valve", 6, "6.3 Failure rate model for poppet assembly", "6-6",
        "6-9", "λ_PO = λ_PO,B · C_P · C_Q · C_F · C_ν · C_N · C_S · C_DT · C_SW · C_W",
        "A poppet and seat's failure rate starts at 1.40 failures per million operations and is scaled by the "
        "pressure across it, how little leakage is allowed, the finish of its seat, the fluid's viscosity, the "
        "dirt in the fluid, how hard the poppet presses on its seat, the seat's diameter and land width, and the "
        "flow against its rating.",
        inputs=[
            *_pressure(), _leakage(),
            num("f", "Mean surface finish of the poppet and seat", "μin", [
                non_negative("a surface finish can't be negative"),
                warn(min=5, max=125, why="Figure 6.8 covers 5 to 125 μin", page="6-22"),
            ], symbol="f", page="6-22",
                help="Table 6-4 (p. 6-30): lapping 2–16, polishing 4–16, honing 4–32, grinding 4–64, turning "
                     "16–250 μin. It worsens in service (35 to 55 μin in a year in Chapter 1's example)."),
            num("S_S", "Contact pressure of the poppet on its seat", "psi", [
                positive("the poppet must press on its seat"),
                warn(min=500, max=14000, why="Figure 6.9 covers 500 to 14,000 psi", page="6-23"),
            ], symbol="S_S", page="6-13",
                help="Eq. 6-11: (P1 − P2) × seat area ÷ seat land area. At least about three times the fluid "
                     "pressure to prevent leakage."),
            num("D_S", "Seat diameter (mean)", "in", [
                positive("a seat has a diameter"),
                warn(min=0.1, max=2.2, why="Figure 6.10 covers 0.1 to 2.2 in", page="6-24"),
            ], symbol="D_S", page="6-24"),
            num("L_W", "Radial seat land width", "in", [
                positive("a seat land has a width"),
                warn(min=0.02, max=0.40, why="Figure 6.11 covers 0.02 to 0.40 in", page="6-25"),
            ], symbol="L_W", page="6-25"),
            *_fluid_inputs(),
        ],
        derived=_shared_derived(),
        checks=_shared_checks(),
        modes=[mode("poppet", "Poppet and seat (wear by contaminants, leakage)",
                    base("λ_PO,B", "Base failure rate of a poppet assembly (per million operations)", "6-9",
                         value=1.40),
                    [
                        *_shared_factors(),
                        factor("C_F", "Surface finish", "6-22", expr="f ** 1.65 / 353", source="Figure 6.8",
                               words="a rougher seat"),
                        factor("C_S", "Seat contact pressure", "6-23", expr="0.26 * (9000 / S_S) ** 1.5",
                               equation="6-12", source="Figure 6.9", words="a lightly loaded seat"),
                        factor("C_DT", "Seat diameter", "6-24", expr="1.1 * D_S + 0.32", source="Figure 6.10",
                               words="a bigger seat"),
                        factor("C_SW", "Seat land width", "6-25",
                               expr="3.55 - 24.52 * L_W + 72.99 * L_W ** 2 - 85.75 * L_W ** 3 if L_W <= 0.34 else 0.25",
                               source="Figure 6.11", words="a narrower seat land"),
                        *_cnu_cn_cw(),
                    ], symbol="λ_PO")],
        rate_unit="per_million_operations",
        notes=("Between Table 6-6's 50 °F steps C_ν is interpolated linearly. The handbook's Table 1-1 example "
               "(p. 1-12: seal 1.20, spring 1.04, poppet 0.35 per million hours) uses Chapter 1's physical "
               "equations (for the poppet, the leakage form of p. 1-7: 0.70 per million operations × 0.5 operations "
               "an hour); this record uses the chapter's factor model, Eq. 6-6, normalised to field failure data, "
               "which isn't algebraically the same: for Table 1-1's poppet it gives 0.597 per million operations "
               "(0.30 an hour at 0.5 operations an hour) before C_N and C_W, which Table 1-1 doesn't have. The "
               "contaminant factor C_N = (C_o/10)³ · FR · N10 (Table 6-5) is usually well below 1 (0.17 for a 10 gpm "
               "piston pump and a 10 µm filter, 0.004 for a sliding valve) and Table 1-1 omits it."),
        failure_modes=_POPPET_MODES,
    ),
    record(
        "valve-sliding", "Sliding action valve (spool and sleeve)", "valve", 6,
        "6.4 Failure rate model for sliding action valves", "6-14", "6-17",
        "λ_SV = λ_SV,B · C_P · C_Q · C_ν · C_N · C_B · C_DS · C_μ · C_W",
        "A spool valve's failure rate starts at 1.25 failures per million operations and is scaled by the "
        "pressure across it, how little leakage is allowed, the fluid's viscosity, the dirt in the fluid, the "
        "spool's clearance and diameter, the friction between spool and sleeve, and the flow against its rating.",
        inputs=[
            *_pressure(), _leakage(),
            num("B", "Diametrical spool-to-sleeve clearance", "μin", [
                positive("a spool needs a clearance"),
                warn(min=200, max=1500, why="Figure 6.12 covers 200 to 1,500 μin", page="6-26"),
            ], symbol="B", page="6-19", help="About 50 μin is common (p. 6-15); from the assembly drawing."),
            num("D_SP", "Spool diameter", "in", [
                positive("a spool has a diameter"),
                warn(min=0.4, max=3.6, why="Figure 6.13 covers 0.4 to 3.6 in", page="6-27"),
            ], symbol="D_SP", page="6-27"),
            num("mu", "Static friction coefficient, spool on sleeve", "", [positive("a friction coefficient is more than zero")],
                symbol="μ", page="6-32",
                help="Table 6-7 (dry / lubricated): steel on steel 0.8 / 0.5, aluminium on steel 0.6 / 0.5, brass on "
                     "steel 0.5 / 0.4, Teflon on Teflon 0.05 / 0.04, hard carbon on carbon 0.2 / 0.1."),
            *_fluid_inputs(),
        ],
        derived=_shared_derived(),
        checks=_shared_checks(),
        modes=[mode("spool", "Spool and sleeve (wear, sticking, leakage)",
                    base("λ_SV,B", "Base failure rate of a sliding action valve (per million operations)", "6-17",
                         value=1.25),
                    [
                        *_shared_factors(),
                        *_cnu_cn_cw()[:2],
                        factor("C_B", "Spool clearance", "6-26", expr="0.42 if B < 500 else B ** 2 / 6e5",
                               source="Figure 6.12", words="a bigger clearance"),
                        factor("C_DS", "Spool diameter", "6-27", expr="0.615 * D_SP", source="Figure 6.13",
                               words="a bigger spool"),
                        factor("C_μ", "Friction coefficient", "6-32", expr="mu", source="Table 6-7",
                               words="more friction (dry, like metals)"),
                        _cnu_cn_cw()[2],
                    ], symbol="λ_SV")],
        rate_unit="per_million_operations",
        notes=("The model assumes the spool is protected from the environment (p. 6-19). Between Table 6-6's 50 °F "
               "steps C_ν is interpolated linearly."),
        failure_modes=_SLIDING_MODES,
    ),
    record(
        "valve-housing", "Valve housing", "valve", 6, "6.5 Failure rate estimate for housing assembly", "6-15",
        "6-19", "λ_HO = λ_HO,B",
        "A valve housing (with its connectors) rarely fails: the handbook gives a constant 0.01 failures per "
        "million hours, best replaced by field experience; for critical safety uses, review its stress analysis.",
        inputs=[],
        modes=[mode("housing", "Housing (fatigue cracking)",
                    base("λ_HO,B", "Base failure rate of a valve housing", "6-19", value=0.01), [], symbol="λ_HO")],
        failure_modes=["Cracked fitting or housing: fatigue, external shock, vibration (external leakage)"],
    ),
    record(
        "valve-assembly", "Valve assembly, poppet type", "valve", 6, "6.1 Introduction (valve assembly)", "6-1",
        "6-3", "λ_VA = λ_PO · ops/h + λ_SE + λ_SP + λ_SO + λ_HO",
        "A poppet valve's failure rate per hour is the sum of its parts': the poppet and seat (its rate per "
        "operation times the operations an hour), its seals, its return spring, the solenoid that drives it and "
        "its housing, each from its own model. The pressures, fluid and dirt the poppet and seals share are "
        "entered once.",
        inputs=_assembly_inputs(),
        modes=_assembly_modes(
            uses("poppet", "Poppet and seat", "valve-poppet", symbol="λ_PO", bind={n: n for n in _SHARED},
                 scale="ops_per_hour", scale_label="operations an hour", note=_OPS_SCALE_NOTE), "6-1"),
        notes=("Per million hours: the poppet's per-operation rate is multiplied by the operations an hour before "
               "the parts are added, as Chapter 1's worked valve does (p. 1-12); Eq. 6-1 itself labels every term "
               "per million operations. The seals use the gasket and static seal model, as Chapter 1's worked valve "
               "does (p. 1-10); rate a seal that slides with the dynamic seal model instead. A count of 0 leaves a "
               "part out and its inputs aren't needed."),
        failure_modes=_VALVE_MODES,
    ),
    record(
        "valve-assembly-sliding", "Valve assembly, sliding action (spool) type", "valve", 6,
        "6.1 Introduction (valve assembly)", "6-2", "6-3", "λ_VA = λ_SV · ops/h + λ_SE + λ_SP + λ_SO + λ_HO",
        "A spool valve's failure rate per hour is the sum of its parts': the spool and sleeve (its rate per "
        "operation times the operations an hour), its seals, its springs, the solenoid that drives it and its "
        "housing, each from its own model. The pressures, fluid and dirt the spool and seals share are entered once.",
        inputs=_assembly_inputs(),
        modes=_assembly_modes(
            uses("spool", "Spool and sleeve", "valve-sliding", symbol="λ_SV", bind={n: n for n in _SHARED},
                 scale="ops_per_hour", scale_label="operations an hour", note=_OPS_SCALE_NOTE), "6-2"),
        notes=("Per million hours: the spool's per-operation rate is multiplied by the operations an hour before "
               "the parts are added (pp. 12-10, 12-16; p. 1-12). The seals use the gasket and static seal model; "
               "rate a seal that slides with the dynamic seal model instead. A count of 0 leaves a part out and "
               "its inputs aren't needed."),
        failure_modes=_VALVE_MODES,
    ),
]
