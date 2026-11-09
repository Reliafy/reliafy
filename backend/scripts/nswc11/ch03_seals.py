"""Chapter 3, Seals and gaskets (Revision G): gaskets and static seals (Eq. 3-7),
dynamic seals (Eq. 3-14) and mechanical seals (Eq. 3-16).

Checked against the rendered pages 3-8 to 3-39:
- C_P (Figure 3.10, p. 3-29): 0.25 up to 1500 psi, (P_S/3000)² above; the two meet
  at 1500 psi. P_S = P1 − P2.
- C_Q (Figure 3.11, p. 3-30): 4.2 − 79·Q_f up to 0.03 in³/min, 0.055/Q_f above
  (they meet at 1.83).
- C_DL: Figure 3.12 (p. 3-31) 1.1·D_SL + 0.32 for seals; Figure 3.13 (p. 3-32)
  0.45·(L/w) + 0.32 for gaskets.
- C_H (Figure 3.14, p. 3-33): the exponent prints as "43" with the decimal point
  lost; the text gives 4.3, and the curve (about 13 at M/C = 1.0, 55 at 1.4) agrees
  with (M/C ÷ 0.55)^4.3. Read as 4.3.
- C_F: Figure 3.15 (p. 3-34, static seals) 0.25 up to 15 μin, f^1.65/353 above;
  Figure 3.17 (p. 3-36, dynamic and mechanical seals) 1.0 up to 10 μin,
  1/2^((10 − f)/38) above. The model takes f in μin RMS as the figures do (the
  equations on pp. 3-6 to 3-8 use inches).
- C_T (Eq. 3-11, p. 3-16, Figure 3.16 p. 3-35): 1/2^t with t = (T_R − T_O)/18 for
  T_R − T_O ≤ 40 °F, 0.21 above (1/2^(40/18) = 0.214, so they meet). Figure 3.16
  says T_R is in "Table 3-6"; the rated temperatures are in Table 3-5 (Table 3-6
  is friction coefficients).
- C_ν (Table 3-3, p. 3-37): ν_o/ν with ν_o = 2×10⁻⁸ lbf·min/in². The table's
  values are that ratio at 50 °F steps; between steps the model interpolates
  linearly (an assumption: the handbook gives only the steps). Where the table
  prints "---" (unreliable) the model refuses and asks for the fluid's viscosity.
  The MIL-H-83282 entries at 300 and 350 °F (0.6114, 0.7766) break the column's
  rising trend (4.063 at 250 °F) and look like decimal slips for 6.114 and 7.766;
  the model doesn't use them (it refuses above 250 °F for that fluid and asks for
  the viscosity). For "another fluid" the viscosity is taken in centipoise (the
  unit of Figure 3.6) and converted: 1 lbf·min/in² = 4.1369×10⁸ cP, so
  ν_o = 8.274 cP. Water at 100 °F (0.68 cP) gives 12.2 against the table's 12.15.
- C_N (Table 3-4, p. 3-38): (C_o/C_10)³ · FR · N10 with C_10 = 10 μm and N10 the
  particles per hour per rated gpm of the upstream component.
- C_PV (Eq. 3-15, p. 3-24): PV_OP/PV_DS, with PV from Eq. 3-13 (p. 3-21):
  π/12 · DP · d · V · k, V in rpm. The page repeats the same formula for V in
  ft/min, which would count π/12 twice; the model uses the rpm form for a
  rotating seal and DP · V · k for a sliding (reciprocating) speed in ft/min.
- Eq. 3-14's speed split (p. 3-22): C_P, C_DL and C_H apply below 800 rpm and
  600 ft/min and are 1.0 at or above; C_PV applies at or above and is 1.0 below.
  Section 3.3.3.3 (p. 3-23) also says C_PV applies to seals reciprocating faster
  than 5 in/s; the model follows the equation's own definitions (p. 3-22/3-23).
- Mechanical seals (Eq. 3-16, p. 3-28): base 22.8 per million hours, balanced
  seal assumed (k = 0.4 by default).
- Chapter 1's worked seal (Table 1-1, p. 1-12, λ_SE = 1.20) uses the earlier
  leakage form, Eq. 3-5 with K1 = 3.27×10⁻⁴ (given only in Chapter 1), not
  Eq. 3-7; the tests show both.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, num, non_negative, positive, record, refuse, warn,
)

# ---- fluid viscosity (Table 3-3, p. 3-37) ----------------------------------------------------

_T_STEPS = [-50, 0, 50, 100, 150, 200, 250, 300, 350]
#: code, label, C_ν at each step (None where the table prints "---").
_FLUIDS = [
    ("air", "Air", [554.0, 503.4, 462.9, 430.1, 402.6, 379.4, 359.5, None, None]),
    ("oxygen", "Oxygen", [504.6, 457.8, 420.6, 390.2, 365.9, 343.6, 325.3, None, None]),
    ("nitrogen", "Nitrogen", [580.0, 528.0, 486.5, 452.6, 424.3, 400.0, 379.6, None, None]),
    ("co2", "Carbon dioxide", [None, 599.9, 510.7, 449.7, 395.9, 352.1, None, None, None]),
    ("water", "Water", [None, None, 6.309, 12.15, 19.43, 27.30, None, None, None]),
    ("sae10", "SAE 10 oil", [None, None, 0.060, 0.250, 0.750, 1.690, 2.650, None, None]),
    ("sae20", "SAE 20 oil", [None, None, 0.0314, 0.167, 0.492, 1.183, 2.213, 2.861, 5.204]),
    ("sae30", "SAE 30 oil", [None, None, 0.0297, 0.1129, 0.3519, 0.8511, 1.768, 2.861, 4.309]),
    ("sae40", "SAE 40 oil", [None, None, 0.0122, 0.0534, 0.2462, 0.6718, 1.325, 2.221, 3.387]),
    ("sae50", "SAE 50 oil", [None, None, 0.0037, 0.0326, 0.1251, 0.3986, 0.8509, 1.657, 2.654]),
    ("sae90", "SAE 90 oil", [None, None, 0.0012, 0.0189, 0.0973, 0.3322, 0.7855, 1.515, 2.591]),
    ("diesel", "Diesel fuel", [0.1617, 0.7492, 2.089, 3.847, 6.228, 9.169, 12.78, 16.31, None]),
    # 300 and 350 °F (0.6114, 0.7766) left out: they break the column's trend (see the module note).
    ("mil_h_83282", "Hydraulic fluid MIL-H-83282", [0.0031, 0.0432, 0.2137, 0.6643, 1.421, 2.585, 4.063, None, None]),
    ("mil_h_5606", "Hydraulic fluid MIL-H-5606", [0.0188, 0.0951, 0.2829, 0.6228, 1.108, 1.783, 2.719, 3.628, 4.880]),
]
#: ν_o = 2e-8 lbf·min/in² in centipoise (1 lbf·min/in² = 6894.757 Pa × 60 s = 4.136854e8 cP).
NU_O_CP = 2e-8 * 6894.757 * 60 * 1000


def _fluid_points(vals):
    pts = [(t, v) for t, v in zip(_T_STEPS, vals) if v is not None]
    return [p[0] for p in pts], [p[1] for p in pts]


def _nu_table_expr() -> str:
    expr = "0"
    for code, _, vals in reversed(_FLUIDS):
        xs, ys = _fluid_points(vals)
        expr = f"interp(T_O, {xs}, {ys}) if fluid == '{code}' else ({expr})"
    return expr


def _nu_range_expr() -> str:
    parts = ["fluid == 'other'"]
    for code, _, vals in _FLUIDS:
        xs, _ = _fluid_points(vals)
        parts.append(f"(fluid == '{code}' and {xs[0]} <= T_O <= {xs[-1]})")
    return " or ".join(parts)


_FLUID = choice("fluid", "Fluid sealed", [*[(c, lab) for c, lab, _ in _FLUIDS],
                                          ("other", "Another fluid (give its viscosity)")],
                default="other", default_basis="neutral", page="3-37",
                help="Table 3-3's fluids, read at the operating temperature. 'Another fluid' uses the viscosity "
                     "below (its default, 8.27 cP, is the handbook's reference viscosity: factor 1).")
_NU = num("nu_cP", "Dynamic viscosity of the fluid at its operating temperature (another fluid only)", "cP",
          [positive("a viscosity is more than zero")], default=NU_O_CP, default_basis="neutral",
          symbol="ν", page="3-37",
          help="Only used for 'another fluid'. The handbook works in lbf·min/in²; 1 lbf·min/in² = 4.137×10⁸ cP. "
               "For a kinematic viscosity, multiply by the density (p. 3-14).")

_SOURCES = [("piston_pump", "Piston pump (steel)", 0.017), ("gear_pump", "Gear pump (steel)", 0.019),
            ("vane_pump", "Vane pump (steel)", 0.006), ("cylinder", "Cylinder (steel)", 0.008),
            ("sliding_valve", "Sliding action valve (steel)", 0.0004), ("hose", "Hose (rubber)", 0.0013)]


def _n10_expr() -> str:
    expr = "0"
    for code, _, v in reversed(_SOURCES):
        expr = f"{v} if source == '{code}' else ({expr})"
    return expr


def _pressure() -> list[dict]:
    return [
        num("P1", "System (upstream) pressure", "psi", [non_negative("a pressure can't be negative")],
            symbol="P1", page="3-14"),
        num("P2", "Downstream pressure (atmospheric if it leaks to air)", "psi",
            [non_negative("a pressure can't be negative")], default=14.7, default_basis="handbook",
            symbol="P2", page="3-14", help="The handbook: standard atmospheric pressure or the downstream pressure."),
    ]


def _leakage() -> dict:
    return num("Q_f", "Allowable leakage", "in³/min", [
        positive("an allowable leakage is more than zero"),
        warn(min=0.01, max=0.15, why="Figure 3.11 covers 0.01 to 0.15 in³/min", page="3-30"),
    ], symbol="Q_f", page="3-10", help="From the component's specification: the leakage that counts as a failure.")


def _hardness() -> list[dict]:
    return [
        num("M", "Meyer hardness of the softer material (Young's modulus for rubber)", "psi",
            [positive("a hardness is more than zero")], symbol="M", page="3-33",
            help="For rubber, Young's modulus from its Shore A hardness (Figure 3.4, p. 3-12)."),
        num("C", "Contact stress at the seal", "psi", [positive("the seal needs a contact stress")], symbol="C",
            page="3-13", help="Force compressing the seal ÷ its contact area (Eq. 3-9)."),
    ]


def _temperature() -> list[dict]:
    return [
        num("T_R", "Maximum rated temperature of the seal material", "°F",
            [refuse(min=-459.67, why="below absolute zero")], symbol="T_R", page="3-16",
            help="From the maker; Table 3-5 (p. 3-38) gives typical values: natural rubber 160, nitrile, neoprene, "
                 "butyl and ethylene propylene 250, polyacrylate 300, silicone and fluorosilicone 450, "
                 "fluorocarbon 475, fluoroelastomers and fluoroplastics 500, urethane 210, leather 200 °F."),
        num("T_O", "Operating temperature (of the fluid at the seal)", "°F",
            [refuse(min=-459.67, why="below absolute zero")], symbol="T_O", page="3-16"),
    ]


def _contamination() -> list[dict]:
    return [
        choice("source", "Upstream component producing contaminants", [(c, lab) for c, lab, _ in _SOURCES],
               symbol="N10", page="3-38",
               help="Table 3-4: particles under 10 μm per hour per rated gpm (piston pump 0.017, gear pump 0.019, "
                    "vane pump 0.006, cylinder 0.008, sliding valve 0.0004, hose 0.0013)."),
        num("C_o", "System filter size", "μm", [positive("a filter size is more than zero")], default=10,
            default_basis="handbook", symbol="C_o", page="3-38",
            help="10 μm is the handbook's standard system filter (factor (C_o/10)³ = 1)."),
        num("FR", "Rated flow rate", "gpm", [positive("the flow rate is more than zero")], symbol="FR", page="3-38"),
    ]


def _shared_derived() -> list[dict]:
    return [
        derived("P_S", "Pressure across the seal (P1 − P2)", "P1 - P2", "psi", "P_S", "3-29"),
        derived("dT", "Rated minus operating temperature", "T_R - T_O", "°F", "T_R − T_O", "3-35",
                limits=[warn(min=-50, why="Figure 3.16 covers T_R − T_O down to −50 °F", page="3-35")]),
        derived("C_nu_table", "C_ν read from Table 3-3", _nu_table_expr(), "", "C_ν", "3-37"),
        derived("N10", "Particles under 10 μm per hour per rated gpm", _n10_expr(), "", "N10", "3-38"),
    ]


def _shared_checks() -> list[dict]:
    return [
        check("P1 >= P2", "The upstream pressure P1 should be at least the downstream pressure P2", "3-29",
              severity="refuse"),
        check(_nu_range_expr(), "Table 3-3 has no reliable value for this fluid at this temperature (it prints "
              "'---'; for MIL-H-83282 above 250 °F its values look misprinted): choose 'another fluid' and give its "
              "viscosity", "3-37", severity="refuse"),
    ]


def _cq() -> dict:
    return factor("C_Q", "Allowable leakage", "3-30", expr="4.2 - 79 * Q_f if Q_f <= 0.03 else 0.055 / Q_f",
                  source="Figure 3.11", words="a tighter allowable leakage")


def _cnu() -> dict:
    return factor("C_ν", "Fluid viscosity", "3-37", expr=f"{NU_O_CP!r} / nu_cP if fluid == 'other' else C_nu_table",
                  source="Table 3-3", words="a thinner fluid (gases most of all)")


def _ct() -> dict:
    return factor("C_T", "Temperature", "3-35", expr="0.21 if dT > 40 else 1 / 2 ** (dT / 18)", equation="3-11",
                  source="Figure 3.16", words="running near or above its rated temperature")


def _cn() -> dict:
    return factor("C_N", "Contaminants", "3-38", expr="(C_o / 10) ** 3 * FR * N10", source="Table 3-4",
                  words="a coarser filter, more flow, a dirtier upstream component")


def _cp() -> dict:
    return factor("C_P", "Fluid pressure", "3-29", expr="0.25 if P_S <= 1500 else (P_S / 3000) ** 2",
                  source="Figure 3.10", words="higher pressure across it")


def _ch() -> dict:
    return factor("C_H", "Hardness ÷ contact stress", "3-33", expr="(M_C / 0.55) ** 4.3", source="Figure 3.14",
                  words="a hard material for its contact stress")


def _cf_dynamic() -> dict:
    return factor("C_F", "Surface finish", "3-36", expr="1.0 if f <= 10 else 1 / 2 ** ((10 - f) / 38)",
                  source="Figure 3.17", words="a rougher surface")


_M_C = derived("M_C", "Meyer hardness ÷ contact stress", "M / C", "", "M/C", "3-33",
               limits=[warn(min=0.2, max=1.4, why="Figure 3.14 covers M/C from 0.2 to 1.4", page="3-33")])


def _balance() -> dict:
    return choice("balance", "Seal balance", [("balanced", "Balanced (k = 0.4)"), ("unbalanced", "Unbalanced (k = 1.0)")],
               default="balanced", default_basis="handbook", symbol="k", page="3-21",
               help="The mechanical seal model assumes a balanced seal (p. 3-27).")


#: Why the library's seal, spring and poppet differ from Chapter 1's worked valve (Table 1-1, p. 1-12).
TABLE_1_1_NOTE = (
    "The handbook's Table 1-1 example (p. 1-12: seal 1.20, spring 1.04, poppet 0.35 per million hours) uses "
    "Chapter 1's physical equations (the leakage form, Eq. 3-5 here, with K1 = 3.27×10⁻⁴); this record uses the "
    "chapter's factor model, Eq. 3-7, normalised to field failure data, which isn't algebraically the same: for "
    "Table 1-1's seal it gives about 1.5 before C_T and C_N, which Table 1-1 doesn't have. Table 1-1 was also last "
    "revised before this chapter (p. vii).")
CN_NOTE = (
    "The contaminant factor C_N = (C_o/10)³ · FR · N10 (Table 3-4) is usually well below 1 (0.17 for a 10 gpm "
    "piston pump and a 10 µm filter, 0.004 for a sliding valve) and is the largest lever in the model; Table 1-1's "
    "worked example leaves it out.")

_STATIC_MODES = [
    "Leakage from wear: contaminants, misalignment, vibration, poor surface finish",
    "Leakage from distortion: extreme temperature, eccentricity, extrusion, compression set, over-torqued bolts",
    "Leakage from embrittlement: poor lubrication, fluid or thermal degradation, idle periods, ozone",
    "Leakage from creep: pressure surges, material degradation, thermal cycling",
    "Leakage from compression set: excessive squeeze, incomplete vulcanisation, hardening at high temperature",
    "Leakage from installation damage: no lead-in chamfer, sharp corners, unprotected spares",
    "Rupture from gas expansion: gas absorbed under high pressure",
]

_DYNAMIC_MODES = [
    "Wear: misalignment, shaft out of round, end play, poor finish, contaminants, poor lubrication, rubbing speed",
    "Dynamic instability: shaft misalignment",
    "Embrittlement: contaminants, fluid incompatibility, thermal degradation, idle periods",
    "Spring failure (see the spring models)",
    "Fracture, edge chipping, shear: stress-corrosion cracking, excessive PV, pressure, torque, shaft whip",
    "Compression set: extreme temperature",
    "Seepage and face distortion: too little squeeze, debris on the faces, excessive PV, poor lubrication",
    "Slow response from friction: excessive squeeze, seal swell, extrusion, metal-to-metal contact",
]

_MECHANICAL_MODES = [
    "Leakage before the face wears out: heat from pressure and speed, thermal distortion of the faces",
    "Face wear and damage: abrasive particles, lost fluid film, too much face contact",
    "Fracture and distortion of face materials, extruded elastomers",
    "Jammed seal face or a damaged spring (contact, heat, corrosion)",
]

RECORDS = [
    record(
        "seal-static", "Gasket or static seal", "seal", 3, "3.2.3 Failure rate model for gaskets and static seals",
        "3-7", "3-8",
        "λ_SE = λ_SE,B · C_P · C_Q · C_DL · C_H · C_F · C_ν · C_T · C_N",
        "A gasket or static seal's failure rate starts at 2.4 failures per million hours and is scaled by the "
        "pressure across it, how little leakage is allowed, its size, its hardness against the contact stress, the "
        "finish of the surface it seals on, the fluid's viscosity, how close it runs to its rated temperature and "
        "the dirt upstream components put in the fluid.",
        inputs=[
            choice("shape", "Seal shape", [("circular", "Circular seal (O-ring or ring seal)"),
                                           ("gasket", "Flat gasket (non-circular)")],
                   default="circular", default_basis="typical", page="3-10",
                   help="Sets the size factor: the inner diameter for a seal (Figure 3.12), length ÷ width for a "
                        "gasket (Figure 3.13)."),
            *_pressure(),
            _leakage(),
            num("D_SL", "Inner diameter of the seal (circular seals)", "in", [positive("a seal has a diameter")],
                symbol="D_SL", page="3-31", help="Circular seals only.", when="shape == 'circular'"),
            num("L", "Total linear length of the gasket (gaskets)", "in", [positive("a gasket has a length")],
                symbol="L", page="3-32", help="Gaskets only.", when="shape == 'gasket'"),
            num("w", "Minimum width of the gasket (gaskets)", "in", [positive("a gasket has a width")],
                symbol="w", page="3-32", help="Gaskets only.", when="shape == 'gasket'"),
            *_hardness(),
            num("f", "Surface finish of the seat (the harder surface)", "μin RMS", [
                non_negative("a surface finish can't be negative"),
                warn(max=125, why="Figure 3.15 covers 0 to 125 μin", page="3-34"),
            ], symbol="f", page="3-34",
                help="About 32 μin for elastomer seals, 16 for plastic and 8 for metal (p. 3-12); it worsens with time "
                     "in service."),
            *_temperature(),
            _FLUID, _NU,
            *_contamination(),
        ],
        derived=[
            *_shared_derived(), _M_C,
            derived("L_w", "Gasket length ÷ width", "L / w if w > 0 else 0", "", "L/w", "3-32"),
        ],
        checks=[
            *_shared_checks(),
            check("D_SL > 0", "A circular seal needs its inner diameter D_SL", "3-31", severity="refuse",
                  when="shape == 'circular'"),
            check("L > 0 and w > 0", "A gasket needs its length L and minimum width w", "3-32", severity="refuse",
                  when="shape == 'gasket'"),
            check("0.5 <= D_SL <= 10", "Figure 3.12 covers seal inner diameters from 0.5 to 10 in", "3-31",
                  when="shape == 'circular' and D_SL > 0"),
            check("2 <= L_w <= 24", "Figure 3.13 covers gasket L/w from 2 to 24", "3-32",
                  when="shape == 'gasket' and L_w > 0"),
            check("P_S <= 10000", "Figure 3.10 covers pressures up to 10,000 psi", "3-29"),
        ],
        modes=[mode("seal", "Seal or gasket (leakage)",
                    base("λ_SE,B", "Base failure rate of a seal", "3-8", value=2.4),
                    [
                        _cp(), _cq(),
                        factor("C_DL", "Seal size", "3-31", expr="1.1 * D_SL + 0.32 if shape == 'circular' "
                               "else 0.45 * L_w + 0.32", source="Figures 3.12 and 3.13",
                               words="a bigger seal, a longer and narrower gasket"),
                        _ch(),
                        factor("C_F", "Seat surface finish", "3-34", expr="0.25 if f <= 15 else f ** 1.65 / 353",
                               source="Figure 3.15", words="a rougher seat"),
                        _cnu(), _ct(), _cn(),
                    ], symbol="λ_SE")],
        notes=("Surface finish and hardness change with time in service (p. 3-7): evaluate at several ages for a "
               "rate over the product's life. Between Table 3-3's 50 °F steps C_ν is interpolated linearly. "
               + TABLE_1_1_NOTE + " " + CN_NOTE),
        failure_modes=_STATIC_MODES,
    ),
    record(
        "seal-dynamic", "Dynamic seal (rotary, reciprocating or oscillating)", "seal", 3,
        "3.3.3 Failure rate model for dynamic seals", "3-14", "3-22",
        "λ_SE = λ_SE,B · C_P · C_Q · C_DL · C_H · C_F · C_ν · C_T · C_N · C_PV "
        "(C_P, C_DL, C_H = 1 at or above 800 rpm or 600 ft/min; C_PV = 1 below)",
        "A dynamic seal's failure rate starts at 22.8 failures per million hours and is scaled by how little "
        "leakage is allowed, the finish of the surface it runs on, the fluid's viscosity, how close it runs to its "
        "rated temperature and the dirt in the fluid. A slow seal is also scaled by the pressure across it, its "
        "size and its hardness against the contact stress; a fast one (800 rpm or 600 ft/min and up) by its "
        "pressure × speed against its design value.",
        inputs=[
            *_pressure(),
            _leakage(),
            num("D_SL", "Seal diameter (inner)", "in", [positive("a seal has a diameter")], symbol="D_SL", page="3-31",
                help="Used for the size factor (slow seals) and in PV (fast seals)."),
            num("n", "Shaft speed (rotating seals)", "rpm", [non_negative("a speed can't be negative")], symbol="V",
                page="3-21", help="0 for a seal that only slides (reciprocating)."),
            num("V_lin", "Sliding speed (reciprocating seals)", "ft/min", [non_negative("a speed can't be negative")],
                symbol="V", page="3-21", help="0 for a rotating seal (its surface speed comes from the shaft speed)."),
            *_hardness(),
            num("f", "Surface finish of the surface the seal runs on", "μin RMS", [
                non_negative("a surface finish can't be negative"),
                warn(max=100, why="Figure 3.17 covers 0 to 100 μin", page="3-36"),
            ], symbol="f", page="3-36", help="Usually 10 to 20 μin for a gland surface (p. 3-23)."),
            *_temperature(),
            _FLUID, _NU,
            *_contamination(),
            _balance(),
            num("PV_DS", "Design PV of the seal (from its maker; fast seals)", "psi·ft/min",
                [non_negative("a PV can't be negative")], default=0, default_basis="neutral", symbol="PV_DS",
                page="3-24", help="Used at or above 800 rpm or 600 ft/min when the maker gives one; 0 when there's "
                                  "none (C_PV is then left out, p. 3-23)."),
        ],
        derived=[
            *_shared_derived(), _M_C,
            derived("V_s", "Sliding speed at the seal", "pi() * D_SL * n / 12 + V_lin", "ft/min", "V", "3-21"),
            derived("fast", "1 at or above 800 rpm or 600 ft/min, else 0",
                    "1 if n >= 800 or V_s >= 600 else 0", "", None, "3-22"),
            derived("k", "Degree of seal unbalance", "0.4 if balance == 'balanced' else 1.0", "", "k", "3-21"),
            derived("PV_OP", "Operating pressure × velocity", "P_S * V_s * k", "psi·ft/min", "PV_OP", "3-21", "3-13"),
        ],
        checks=[
            *_shared_checks(),
            check("PV_DS > 0", "No design PV from the maker: the PV factor C_PV is left out (1.0), as the handbook "
                  "applies it only \"where a PV design factor is available from the manufacturer\"", "3-23",
                  when="fast == 1"),
            check("0.5 <= D_SL <= 10", "Figure 3.12 covers seal inner diameters from 0.5 to 10 in", "3-31",
                  when="fast == 0"),
            check("P_S <= 10000", "Figure 3.10 covers pressures up to 10,000 psi", "3-29", when="fast == 0"),
        ],
        modes=[mode("seal", "Dynamic seal (leakage, wear)",
                    base("λ_SE,B", "Base failure rate of a dynamic seal", "3-22", value=22.8),
                    [
                        {**_cp(), "when": "fast == 0"}, _cq(),
                        factor("C_DL", "Seal size", "3-31", expr="1.1 * D_SL + 0.32", source="Figure 3.12",
                               when="fast == 0", words="a bigger seal"),
                        {**_ch(), "when": "fast == 0"},
                        _cf_dynamic(), _cnu(), _ct(), _cn(),
                        factor("C_PV", "Pressure × velocity", "3-24", expr="PV_OP / PV_DS", equation="3-15",
                               when="fast == 1 and PV_DS > 0", words="running above its design PV"),
                    ], symbol="λ_SE")],
        notes=("One diameter serves both the size factor (Figure 3.12's inner diameter) and Eq. 3-13's seal "
               "diameter. Between Table 3-3's 50 °F steps C_ν is interpolated linearly. Without a design PV from "
               "the maker, a fast seal's C_PV is left out (p. 3-23). " + CN_NOTE),
        failure_modes=_DYNAMIC_MODES,
    ),
    record(
        "seal-mechanical", "Mechanical seal (rotating face seal)", "seal", 3,
        "3.4.2 Failure rate model for mechanical seals", "3-16", "3-28",
        "λ_SE = λ_SE,B · C_Q · C_F · C_ν · C_T · C_N · C_PV",
        "A mechanical seal's failure rate starts at 22.8 failures per million hours and is scaled by how little "
        "leakage is allowed, the finish of its faces, the fluid's viscosity, how close its faces run to their rated "
        "temperature, the dirt in the fluid and its pressure × speed against its design value. It assumes a "
        "balanced seal.",
        inputs=[
            *_pressure(),
            _leakage(),
            num("d", "Seal diameter", "in", [positive("a seal has a diameter")], symbol="d", page="3-21"),
            num("n", "Shaft speed", "rpm", [positive("a mechanical seal turns")], symbol="V", page="3-21"),
            num("f", "Surface finish of the seal faces", "μin RMS", [
                non_negative("a surface finish can't be negative"),
                warn(max=100, why="Figure 3.17 covers 0 to 100 μin", page="3-36"),
            ], symbol="f", page="3-36"),
            *_temperature(),
            _FLUID, _NU,
            *_contamination(),
            _balance(),
            num("PV_DS", "Design PV of the seal faces (from the maker)", "psi·ft/min",
                [positive("a design PV is more than zero")], symbol="PV_DS", page="3-24",
                help="Table 3-7 (p. 3-39) gives typical limits: carbon against hard-faced stainless steel or ceramic "
                     "543,000; leaded bronze 992,000; nickel iron 1,142,000; tungsten carbide 2,570,000."),
        ],
        derived=[
            *_shared_derived(),
            derived("V_s", "Face sliding speed", "pi() * d * n / 12", "ft/min", "V", "3-21"),
            derived("k", "Degree of seal unbalance", "0.4 if balance == 'balanced' else 1.0", "", "k", "3-21"),
            derived("PV_OP", "Operating pressure × velocity", "P_S * V_s * k", "psi·ft/min", "PV_OP", "3-21", "3-13"),
        ],
        checks=[
            *_shared_checks(),
            check("n >= 800 or V_s >= 600", "The handbook treats a seal as mechanical above 800 rpm or 600 ft/min; "
                  "a slower seal is a dynamic seal", "3-2"),
        ],
        modes=[mode("seal", "Mechanical seal (leakage before the face wears out)",
                    base("λ_SE,B", "Base failure rate of a mechanical seal", "3-28", value=22.8),
                    [_cq(), _cf_dynamic(), _cnu(), _ct(), _cn(),
                     factor("C_PV", "Pressure × velocity", "3-24", expr="PV_OP / PV_DS", equation="3-15",
                            words="running above its design PV")],
                    symbol="λ_SE")],
        notes="Between Table 3-3's 50 °F steps C_ν is interpolated linearly. " + CN_NOTE,
        failure_modes=_MECHANICAL_MODES,
    ),
]
