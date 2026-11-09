"""Chapter 13, Compressors (Revision B): the compressor assembly (Eq. 13-1) and
the rubber diaphragm of a diaphragm compressor (Eq. 13-2).

Checked against the rendered pages 13-10 to 13-25:
- Eq. 13-1 (p. 13-10): λ_C = λ_FD · C_SF + λ_CA + λ_BE + λ_VA + λ_SE + λ_SH, every
  term in failures per million hours. The where-list (p. 13-11) prints λ_SE twice;
  the second is the shaft, λ_SH. The handbook calls it an "example equation"
  to adapt to the design (timing gears, belts, couplings, sensors, filters,
  clutches may be added); the record is the printed equation.
- λ_FD: Table 13-4 (p. 13-24), by fluid driver type. λ_CA = 0.010 (p. 13-11).
- C_SF: Table 13-5 (p. 13-25) gives a factor per condition (high duty cycle,
  extreme temperatures, non-scheduled lubrication checks, high vibration or
  shock, poor inlet air) by compressor family. Ambiguity: it doesn't say how to
  combine several conditions. Reading chosen: multiply the factors of every
  condition that applies (1.0 when none does, the table's "normal" row).
- Valve assemblies (Chapter 6) are per million hours (their poppet or spool
  converted by the valve's own operations an hour), so they add as they are,
  one per control valve. The shaft follows readings.SHAFT_PER_HOUR: per million
  hours by default (added as it is, as p. 13-11 lists it); with that switch off
  it's per million cycles × the shaft's cycles an hour. The seals are
  taken as mechanical seals (the shaft seal every compressor type has); the
  bearings from their load rating.
- Multi-stage compressors: each stage is a compressor of its own and the rates
  add (p. 13-11, note to Table 13-4): use one record per stage.
- Eq. 13-2 (p. 13-13): λ_DI = λ_BFD · C_P · C_AC · C_LC · C_T, λ_BFD = 0.58.
  The stress is Eq. 13-6 (p. 13-16), σ_r = F·K_F·B_F / (2π h²), with K_F (Eq. 13-4,
  p. 13-15) and B_F (Eq. 13-7, p. 13-16), c = a/b. Ambiguity: Eq. 13-4 prints
  "ln c²" in its second term. Read literally as ln(c²) the bending stiffness
  comes out negative for every c below about 3.5 (b/a above 0.29), which can't
  be; read as (ln c)², the rigid-centre diaphragm's standard form and the
  notation Eq. 13-7 uses ("ln² c"), it is positive for every c > 1. The model
  uses (ln c)². Eq. 13-8 gives the push-rod
  force from shaft power, F = 396,000·hp / (L·ω); the record takes F. Two strains,
  as the handbook says: for C_P "the value for strain obtained from Figure 13.3"
  (p. 13-17), rubber's non-linear stress-strain curves for four hardnesses (33,
  47, 59 and 73 IRHD), which can't be read reliably enough to digitise between
  curves, so the record takes that strain as an input the user reads off Figure
  13.3 at the stress σ_r it shows; and for C_AC the strain σ_r / E with E from
  Table 13-2 (p. 13-19) by hardness (p. 13-18).
- C_P (Figure 13.6, p. 13-22): 1.0 up to 75 % strain, (S/75)^1.8 above; the
  figure runs to 800 %. C_AC (Figure 13.7, p. 13-23): (S/10)^1.1 at 0.3 pphm
  ozone, (S/10)² at 7.5 pphm; the figure covers 15 to 100 % strain, and C_AC is
  held at its 100 % value beyond (with a warning) rather than extrapolated; × 1/3
  with an anti-ozonant coating (p. 13-18). Only the two printed ozone levels are
  offered; outdoor air is "a few pphm" (p. 13-18), nearer the 7.5 curve.
- C_LC: only a nomograph (Figure 13.5, p. 13-21) from the penetration rate
  (Figure 13.4, a curve, adjusted by Table 13-3) and the thickness, with no
  equation, and its scales can't be read reliably from the page. The model
  takes C_LC as a number the user reads from the nomograph (its scale runs
  0.01 to 100), 1 by default.
- C_T (p. 13-20): 1.0 for −32 °F < T ≤ 212 °F, 6.7 above 212 °F.
- No worked example in the chapter.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, non_negative, num, positive, record, refuse, table, uses, warn,
)
from backend.scripts.nswc11 import readings

_FAILURE_MODES = [
    "Seal, bearing, gear, belt or shaft failure (see their chapters)",
    "Clogged filter or suction strainer (contaminants)",
    "Corrosion, water hammer or freeze damage (moisture in the compressor)",
    "Pressure pulsations and loss of output (wear, erosion of close-clearance parts, casing or seal leaks)",
    "Increased friction and wear (contaminants, poor lubrication, running outside its limits)",
    "Reciprocating: valves that stick or leak, worn piston or packing rings, liquid in a cylinder",
    "Rotary: rotor wear from contaminants or lost lubricant film, slippage, clogged discharge port",
    "Diaphragm: embrittlement, corrosion, cracking or rupture of the diaphragm",
]

#: Table 13-4 (p. 13-24): fluid driver, base rate per million hours, and its Table 13-5 family.
_DRIVERS = [
    ("radial", "Centrifugal, radial flow", 12.0, "centrifugal"),
    ("axial", "Centrifugal, axial flow", 12.0, "centrifugal"),
    ("piston_single", "Reciprocating, single piston", 14.0, "reciprocating"),
    ("piston_double", "Reciprocating, double-acting piston", 16.5, "reciprocating"),
    ("labyrinth", "Reciprocating, labyrinth", 16.5, "reciprocating"),
    ("diaphragm_rubber", "Reciprocating, rubber diaphragm", 22.8, "diaphragm"),
    ("diaphragm_metal", "Reciprocating, metal diaphragm", 28.5, "diaphragm"),
    ("vane", "Rotary, vane", 12.0, "rotary"),
    ("screw", "Rotary, screw", 12.0, "rotary"),
    ("lobe", "Rotary, lobe", 12.0, "rotary"),
    ("liquid_ring", "Rotary, liquid ring", 12.0, "rotary"),
]
LAMBDA_FD = {c: lam for c, _, lam, _ in _DRIVERS}
FAMILY = {c: fam for c, _, _, fam in _DRIVERS}

#: Table 13-5 (p. 13-25): (input, label, symbol, {family: factor}).
SERVICE = [
    ("high_duty", "High duty cycle (more than 5 cycles an hour)", "C_SF,duty",
     {"centrifugal": 1.2, "rotary": 1.2, "reciprocating": 1.4, "diaphragm": 1.2}),
    ("extreme_temperature", "Extreme operating temperatures", "C_SF,temp",
     {"centrifugal": 1.1, "rotary": 1.1, "reciprocating": 1.4, "diaphragm": 1.4}),
    ("unscheduled_lubrication", "Non-scheduled lubrication checks", "C_SF,lube",
     {"centrifugal": 1.1, "rotary": 1.2, "reciprocating": 1.1, "diaphragm": 1.2}),
    ("vibration_shock", "High vibration and/or heavy shock loading", "C_SF,vib",
     {"centrifugal": 1.2, "rotary": 1.4, "reciprocating": 1.3, "diaphragm": 1.5}),
    ("poor_inlet_air", "Poor inlet air quality", "C_SF,air",
     {"centrifugal": 1.1, "rotary": 1.4, "reciprocating": 1.1, "diaphragm": 1.3}),
]

#: Table 13-2 (p. 13-19): Young's modulus (psi) by hardness (IRHD).
YOUNG = {30: 130, 35: 168, 40: 213, 45: 256, 50: 310, 55: 460, 60: 630, 65: 830, 70: 1040, 75: 1340}


def _select(name: str, values: dict) -> str:
    """An expression picking ``values[name]`` by a choice's code (a chain of ``a if … else``)."""
    items = list(values.items())
    out = repr(items[-1][1])
    for code, v in reversed(items[:-1]):
        out = f"{v!r} if {name} == {code!r} else {out}"
    return f"({out})"


def _yes_no(name: str, label: str) -> dict:
    return choice(name, label, [("no", "No"), ("yes", "Yes")], default="no", default_basis="neutral", page="13-25")


def _service_factors() -> list[dict]:
    return [factor(sym, label, "13-25", table=table([name, "driver"], {
        "no": {c: 1.0 for c in LAMBDA_FD},
        "yes": {c: values[FAMILY[c]] for c in LAMBDA_FD},
    }), source="Table 13-5", words=label[0].lower() + label[1:]) for name, label, sym, values in SERVICE]


RECORDS = [
    record(
        "compressor", "Compressor (one stage)", "compressor", 13, "13.5 Failure rate model for compressor assembly",
        "13-1", "13-10",
        "λ_C = λ_FD · C_SF + λ_CA + λ_BE + λ_VA + λ_SE + λ_SH, with λ_CA = 0.010 and C_SF the product of "
        "Table 13-5's factors for the conditions that apply",
        "A compressor's failure rate is the sum of its parts. The fluid driver (the screw, piston, vanes, impeller or "
        "diaphragm) has a base rate by type, raised by a high duty cycle, extreme temperatures, unscheduled "
        "lubrication, vibration or shock, and poor inlet air. Then add the casing (0.010 per million hours), the "
        "bearings, the control valves, the seals and the shaft from their own models.",
        inputs=[
            choice("driver", "Fluid driver (compressor type)", [(c, lab) for c, lab, _, _ in _DRIVERS],
                   symbol="λ_FD", page="13-24"),
            *[_yes_no(name, label) for name, label, _, _ in SERVICE],
            num("n_BE", "Number of shaft bearings", "", [non_negative()], symbol="n_BE", page="13-10"),
            num("n_VA", "Number of control valves", "", [non_negative()], symbol="n_VA", page="13-11",
                help="0 when it has none (a rotary screw normally has no control valves, p. 13-11). Each valve's "
                     "operations an hour are among the valve's inputs."),
            num("n_SE", "Number of seals", "", [non_negative()], symbol="n_SE", page="13-11"),
            *([] if readings.SHAFT_PER_HOUR else [
                num("SH_cycles_per_hour", "Shaft cycles per hour", "per hour", [non_negative()], symbol="cycles/h",
                    page="13-11", help="Revolutions an hour (rpm × 60): turns the shaft's rate per million cycles "
                                       "(Chapter 20) into one per million hours.")]),
        ],
        checks=[
            check("n_BE > 0", "No shaft bearings counted: the bearings add nothing (every compressor shaft runs in "
                  "bearings)", "13-10"),
            check("n_SE > 0", "No seals counted: the seals add nothing (every compressor type has a shaft seal)",
                  "13-11"),
        ],
        modes=[
            mode("fluid_driver", "Fluid driver",
                 base("λ_FD", "Fluid driver failure rate", "13-24", table=table("driver", dict(LAMBDA_FD)),
                      source="Table 13-4"),
                 _service_factors(), symbol="λ_FD · C_SF"),
            mode("casing", "Casing", base("λ_CA", "Compressor casing failure rate", "13-11", value=0.010),
                 symbol="λ_CA"),
            uses("bearings", "Shaft bearings", "bearing-rolling-load-rating", symbol="λ_BE", count="n_BE"),
            uses("valves", "Control valve assemblies (each)", "valve-assembly", symbol="λ_VA", count="n_VA",
                 note="Chapter 6's valve assembly, per million hours (its poppet converted by its own operations an "
                      "hour), one per control valve."),
            uses("seals", "Seals", "seal-mechanical", symbol="λ_SE", count="n_SE"),
            uses("shaft", "Shaft", "shaft", symbol="λ_SH",
                 note="Reliafy's reading (p. 13-11 against p. 20-5): the shaft is taken per million hours, as Eq. "
                      "13-1 lists it, and added as it is.")
            if readings.SHAFT_PER_HOUR else
            uses("shaft", "Shaft", "shaft", symbol="λ_SH", scale="SH_cycles_per_hour", scale_label="cycles an hour",
                 note="Chapter 20 gives the shaft in failures per million cycles; Eq. 13-1 adds it per million "
                      "hours, so this part is the shaft rate × its cycles per hour."),
        ],
        notes=("The fluid driver is Table 13-4's rate by type; the detailed rubber-diaphragm model (Eq. 13-2, "
               "compressor-diaphragm, base 0.58) is a separate record: for a rubber-diaphragm compressor, compare "
               "it with Table 13-4's 22.8 (p. 13-13 sets λ_FD = λ_DI for that type). A reciprocating compressor's "
               "shaft sees reciprocating loads the shaft model doesn't cover (p. 20-5)."),
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "compressor-diaphragm", "Compressor diaphragm (rubber)", "compressor", 13,
        "13.8 Diaphragm failure rate model", "13-2", "13-13",
        "λ_DI = λ_BFD · C_P · C_AC · C_LC · C_T, λ_BFD = 0.58, with C_P from the strain read off Figure 13.3, "
        "C_AC from the strain S = σ_r / E (Table 13-2), σ_r = F·K_F·B_F / (2π h²)",
        "A rubber compressor diaphragm's failure rate starts at 0.58 failures per million hours and is scaled by how "
        "far it is strained (the push-rod force on a diaphragm of its size, thickness and hardness), ozone in the "
        "air, oil or solvent soaking into it, and temperatures over 212 °F.",
        inputs=[
            num("F", "Force on the diaphragm's rigid centre", "lbf", [positive("the force is more than zero")],
                symbol="F", page="13-15",
                help="From shaft power instead: F = 396,000 × hp ÷ (L × ω), L the eccentric's offset in inches and ω "
                     "the shaft speed in rpm (Eq. 13-8)."),
            num("a", "Diaphragm radius", "in", [positive("a radius is more than zero")], symbol="a", page="13-15"),
            num("b", "Radius of the rigid centre plate", "in", [positive("a radius is more than zero")], symbol="b",
                page="13-15"),
            num("h", "Diaphragm thickness", "in", [positive("a thickness is more than zero")], symbol="h",
                page="13-15"),
            choice("IRHD", "Rubber hardness (sets Young's modulus)",
                   [(str(k), f"{k} IRHD (E = {v} psi)") for k, v in YOUNG.items()], symbol="E", page="13-19"),
            num("eta", "Poisson's ratio", "", [refuse(min=0, max=0.5, why="Poisson's ratio of a solid is 0 to 0.5")],
                default=0.5, default_basis="handbook", symbol="η", page="13-17",
                help="The handbook: rubber is nearly incompressible, take 0.5."),
            num("S_fig", "Strain read from Figure 13.3 at the stress σ_r", "%", [
                refuse(min=0, why="a strain can't be negative"),
                warn(max=900, why="Figure 13.3's curves run to about 900 % strain", page="13-17")],
                symbol="S (Figure 13.3)", page="13-17",
                help="Read off Figure 13.3 (p. 13-17), natural rubber's stress against strain for 33, 47, 59 and 73 "
                     "IRHD, at the maximum radial stress σ_r this record works out (shown under its derived values). "
                     "Below 75 % the load factor C_P is 1. For example about 800 psi on the 47 IRHD curve is about 445 %."),
            choice("ozone", "Ozone in the air", [
                ("lab", "0.3 pphm (laboratory atmosphere)"), ("high", "7.5 pphm")],
                default="lab", default_basis="typical", page="13-23",
                help="Figure 13.7's two curves. Outdoor air at ground level is \"a few parts per hundred million\" "
                     "(p. 13-18): nearer 7.5 pphm than the laboratory's 0.3."),
            choice("coating", "Anti-ozonant coating", [("no", "No"), ("yes", "Yes (crack growth ÷ 3)")],
                   default="no", default_basis="neutral", page="13-18"),
            num("C_LC", "Liquid contaminant factor (read from Figure 13.5)", "", [
                positive("the factor is more than zero"),
                warn(min=0.01, max=100, why="Figure 13.5's scale runs 0.01 to 100", page="13-21")],
                default=1.0, default_basis="neutral", symbol="C_LC", page="13-21",
                help="From the nomograph: the penetration rate (Figure 13.4 by the liquid's viscosity, × Table "
                     "13-3's factor for the rubber) and the diaphragm thickness."),
            num("T", "Temperature", "°F", [
                refuse(min=-459.67, exclusive=True, why="above absolute zero"),
                warn(min=-32, exclusive=True, why="the factor is given above −32 °F", page="13-20")],
                default=70, default_basis="typical", symbol="T", page="13-20",
                help="Up to 212 °F the factor is 1."),
        ],
        derived=[
            derived("c", "Ratio of radii a/b", "a / b", "", "c", "13-15"),
            derived("K_F", "Stiffness coefficient (bending)",
                    "3 * (1 - eta ** 2) / pi() * ((c ** 2 - 1) / (4 * c ** 2) - ln(c) ** 2 / (c ** 2 - 1))",
                    "", "K_F", "13-15", "13-4"),
            derived("B_F", "Stiffness coefficient (tension)",
                    "2 / (1 - eta ** 2) * c ** 2 * (2 * c ** 2 * ln(c) - c ** 2 + 1) / "
                    "((c ** 2 - 1) ** 2 - 4 * c ** 2 * ln(c) ** 2)", "", "B_F", "13-16", "13-7"),
            derived("sigma_r", "Maximum radial stress", "F * K_F * B_F / (2 * pi() * h ** 2)", "psi", "σ_r",
                    "13-16", "13-6"),
            derived("E", "Young's modulus", _select("IRHD", {str(k): float(v) for k, v in YOUNG.items()}), "psi",
                    "E", "13-19"),
            derived("S", "Strain for the ozone factor (σ_r ÷ E)", "100 * sigma_r / E", "%", "S", "13-18",
                    limits=[warn(min=15, why="Figure 13.7 covers strains from 15 %", page="13-23")]),
            derived("S_AC", "Strain used for C_AC (held at Figure 13.7's 100 %)", "min(S, 100)", "%", "S", "13-23"),
        ],
        checks=[
            check("b > 0.05 * a", "Eq. 13-3 applies for b/a over 0.05", "13-15"),
            check("b < a", "The rigid centre must be smaller than the diaphragm", "13-15", severity="refuse"),
            check("h < 0.15 * a", "Shear stresses are neglected only for h/a under 0.15", "13-15"),
            check("S <= 100", "Figure 13.7 (ozone) covers strains up to 100 %: C_AC is held at its 100 % value",
                  "13-23"),
            check("S_fig <= 800", "Figure 13.6 covers strains up to 800 %", "13-22"),
        ],
        modes=[mode("diaphragm", "Diaphragm (cut growth, ozone cracking, swelling, heat)",
                    base("λ_BFD", "Compressor diaphragm base failure rate", "13-13", value=0.58, equation="13-2"),
                    [
                        factor("C_P", "Axial loading (strain from Figure 13.3)", "13-22",
                               expr="1.0 if S_fig <= 75 else (S_fig / 75) ** 1.8",
                               source="Figures 13.3 and 13.6", words="strain over 75 %"),
                        factor("C_AC", "Atmospheric contaminants (ozone)", "13-23",
                               expr="((S_AC / 10) ** 1.1 if ozone == 'lab' else (S_AC / 10) ** 2) * "
                                    "(1 / 3 if coating == 'yes' else 1.0)",
                               source="Figure 13.7", words="strain and ozone"),
                        factor("C_LC", "Liquid contaminants", "13-21", expr="C_LC", source="Figure 13.5",
                               words="oil or solvents soaking in"),
                        factor("C_T", "Temperature", "13-20", expr="1.0 if T <= 212 else 6.7",
                               words="over 212 °F"),
                    ], symbol="λ_DI")],
        failure_modes=[
            "Accelerated curing and embrittlement (extreme high or low temperature)",
            "Corrosion or cracking (contaminants, ozone)",
            "Rupture or crack (inadequate strength, local stresses at the seat, hardening)",
            "Mechanical-oxidative cut growth at high strain",
            "Swelling from absorbed oil or solvents",
        ],
    ),
]
