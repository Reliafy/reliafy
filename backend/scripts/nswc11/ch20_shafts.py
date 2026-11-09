"""Chapter 20, Shafts (Revision C): the shaft failure rate, Eq. 20-3.

Checked against the rendered pages 20-4 to 20-11:
- λ_SH,B (Eq. 20-4, p. 20-5) is printed as "1 / N, failures/million cycles",
  N the cycles to failure at the application stress (from the material's S-N
  curve). 1/N is per cycle, so the model uses 10⁶ / N for the stated unit (as
  Chapter 7 does with 1/L10h). N has to come from the material's S-N data: the
  handbook gives endurance limits (Table 20-2) but no way to get N from them.
- The unit: see readings.SHAFT_PER_HOUR (per million hours by default, the unit
  every assembly that uses the shaft lists it in).
- C_f (Table 20-3, p. 20-10): polynomials in the tensile strength T_S (kpsi).
  They are surface-finish (endurance) factors below 1 for rougher finishes, so
  multiplying the rate by them makes a rougher finish *lower* the predicted rate.
  See readings.SHAFT_FINISH_INVERTED (divided by default).
- C_T (Eq. 20-5, p. 20-6): (460 + T_AT) / 620 above 160 °F, else 1.0.
- C_DY (Eq. 20-8, p. 20-7): 0.0043 F / (E b) · [X³/I_X + L³/I_L + M³/I_M + N³/I_N],
  I = π d⁴ / 64 for each section (p. 20-7). The factor is the deflection against
  the allowable, so it is below 1 (lowering the rate) for a stiff shaft.
  Followed literally. Sections not present are entered with length 0.
  b defaults to 0.007 in (Table 20-6, note 1).
- C_SC (Eq. 20-9, 20-10, p. 20-8): printed as C_SC,R + C_SC,G, but the same page
  says C_SC,G = 1.0 with no grooves, and Table 20-4's smallest value is 1.00: the
  neutral values of a product, not a sum (a sum would add 1 to every plain
  shaft). Reliafy's reading: the product C_SC,R × C_SC,G.
  C_SC,R = (0.3 / (r/d))^0.2 · (D/d)^(1 − r/d).
  C_SC,G from Table 20-4 (h/D by h/r; the table's blank cells are left out of
  the choices), 1.0 with no grooves.
- The torque and shear stress (Eq. 20-1, 20-2) are design aids that feed no
  factor, so they aren't inputs here.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, non_negative, num, positive, record, refuse, warn,
)
from backend.scripts.nswc11 import readings

_FAILURE_MODES = [
    "Bent shaft: excessive load or torque, impact, a failed bearing",
    "Excessive deflection: dynamic or reversing loads, critical speed exceeded, unbalance",
    "Misalignment: poor assembly, worn bearings, excessive load",
    "Damaged surface finish: corrosion, contaminants, thermal expansion",
    "Fatigue or fracture: stress risers at fillets, keyways and diameter changes; bending fatigue; high torque",
    "Fretting corrosion: movement between tightly fitted parts",
]

# Table 20-4 (p. 20-10): C_SC,G by h/D (rows) and h/r (columns); "---" cells aren't offered.
_GROOVE_TABLE = {
    "0.05": {"0.1": 1.10, "0.5": 1.45, "1.0": 1.60, "2.0": 2.00, "4.0": 2.05},
    "0.10": {"0.1": 1.00, "0.5": 1.27, "1.0": 1.40, "2.0": 1.70, "4.0": 2.00, "6.0": 2.25},
    "0.20": {"0.1": 1.00, "0.5": 1.10, "1.0": 1.20, "2.0": 1.31, "4.0": 1.60, "6.0": 1.75, "8.0": 2.00},
    "0.30": {"0.1": 1.00, "0.5": 1.10, "1.0": 1.10, "2.0": 1.20, "4.0": 1.35, "6.0": 1.48, "8.0": 1.55},
}
_GROOVES = [("none", "No grooves")] + [
    (f"hD{hd}_hr{hr}", f"Groove depth ÷ diameter {hd}, depth ÷ radius {hr}")
    for hd, row in _GROOVE_TABLE.items() for hr in row
]
_GROOVE_VALUES = {"none": 1.0, **{f"hD{hd}_hr{hr}": v for hd, row in _GROOVE_TABLE.items() for hr, v in row.items()}}

_SECTIONS = ("X", "L", "M", "N")


def _section_inputs() -> list[dict]:
    out = []
    for s in _SECTIONS:
        # Section X always exists; L, M and N are absent (length 0) unless given (Figure 20.2).
        extra = {} if s == "X" else {"default": 0, "default_basis": "neutral"}
        out.append(num(f"len_{s}", f"Length of shaft section {s}", "in", [non_negative("a length can't be negative")],
                       symbol=s, page="20-7", help="0 when the shaft has no such section (Figure 20.2).", **extra))
        out.append(num(f"D_{s}", f"Diameter of shaft section {s}", "in", [non_negative("a diameter can't be negative")],
                       symbol=f"D_{s}", page="20-7", help="Only needed when the section has a length.",
                       when=f"len_{s} > 0"))
    return out


def _groove_expr() -> str:
    """Table 20-4 as an expression of the groove choice (a derived value, so C_SC can add it)."""
    *rest, last = _GROOVE_VALUES.items()
    return " else ".join(f"{v} if groove == '{k}'" for k, v in rest) + f" else {last[1]}"


def _section_term(s: str) -> str:
    return f"(len_{s} ** 3 / (pi() * D_{s} ** 4 / 64) if len_{s} > 0 else 0)"


_CF = ("1.0 if finish == 'polished' else 0.89 if finish == 'ground' else "
       "0.94 - 0.0046 * T_S + 8.37e-6 * T_S ** 2 if finish == 'hot_rolled' else "
       "1.07 - 0.0051 * T_S + 2.21e-5 * T_S ** 2 - 3.57e-8 * T_S ** 3 if finish == 'machined' "
       "else 0.75 - 4.06e-3 * T_S + 7.58e-6 * T_S ** 2")

UNIT_NOTE = (
    "Reliafy's reading (p. 20-5 against pp. 10-10, 13-11, 14-7): Chapter 20 prints the shaft per million cycles, but "
    "every assembly that uses it lists it per million hours, and converting by revolutions gives a life of hours "
    "(0.1 to 0.25 per million cycles × 108,000 revolutions an hour at 1,800 rpm). The rate is taken per million "
    "hours." if readings.SHAFT_PER_HOUR else
    "Per million cycles, as printed (p. 20-5): one cycle is one revolution (completely reversed bending); "
    "converted by revolutions an hour the rate can be implausibly high.")
FINISH_NOTE = (
    "Reliafy's reading (p. 20-10): Table 20-3's finish factors are endurance-strength factors (1 or below for a "
    "rougher finish); applied as printed they would lower the rate for a rougher finish, so the rate is divided by "
    "them (polished stays 1)." if readings.SHAFT_FINISH_INVERTED else
    "Table 20-3's finish factors are applied as printed: a rougher finish lowers the rate (p. 20-10), against "
    "Table 20-1 and Section 20.4.2.")
_FORMULA = ("λ_SH = λ_SH,B · " + ("(1 / C_f)" if readings.SHAFT_FINISH_INVERTED else "C_f") +
            " · C_T · C_DY · C_SC, with λ_SH,B = 10⁶ / N and C_SC = C_SC,R · C_SC,G")

RECORDS = [
    record(
        "shaft", "Shaft", "shaft", 20, "20.4 Failure rate model for shafts", "20-3", "20-4",
        _FORMULA,
        "A shaft's failure rate starts at one over the cycles its material lasts at the stress "
        "it works at (from the material's S-N curve). That is scaled by its surface finish, its temperature, how "
        "far it deflects against the allowable deflection, and the stress concentrations at its shoulders and "
        "grooves." + (" The rate is taken per million hours (Reliafy's reading: see the note)."
                      if readings.SHAFT_PER_HOUR else " The rate is per million cycles (revolutions)."),
        inputs=[
            num("N_cycles", "Cycles to failure at the application stress", "cycles",
                [positive("a life is more than zero")], symbol="N", page="20-5",
                help="From the material's S-N curve at the stress the shaft works at (Figure 20.1)."),
            choice("finish", "Surface finish", [
                ("polished", "Polished"), ("ground", "Ground"), ("hot_rolled", "Hot rolled"),
                ("machined", "Machined or cold drawn"), ("forged", "Forged"),
            ], default="polished", default_basis="neutral", symbol="C_f", page="20-10"),
            num("T_S", "Tensile strength of the material", "kpsi", [
                positive("a strength is more than zero"),
                warn(min=20, max=240, why="Table 20-5's shaft materials span 20 to 240 ksi", page="20-11"),
            ], symbol="T_S", page="20-10", when="finish != 'polished' and finish != 'ground'",
                help="Only needed for hot-rolled, machined and forged finishes (Table 20-3)."),
            num("T_AT", "Operating temperature", "°F", [refuse(min=-459.67, why="below absolute zero")],
                default=160, default_basis="neutral", symbol="T_AT", page="20-6",
                help="Up to 160 °F the factor is 1."),
            num("F", "Radial unbalance force or load weight", "lb",
                [positive("with no load the handbook's deflection factor, and so the shaft's rate, is zero")],
                symbol="F", page="20-7"),
            num("E", "Modulus of elasticity of the shaft material", "lb/in²", [
                positive("a modulus is more than zero"),
                warn(min=10.0e6, max=30.0e6, why="Table 20-5's shaft materials span 10 to 30 Mpsi", page="20-11"),
            ], symbol="E", page="20-7", help="Steels about 29 to 30 × 10⁶, aluminium about 10 × 10⁶ (Table 20-5)."),
            num("b", "Allowable shaft deflection", "in", [positive("an allowable deflection is more than zero")],
                default=0.007, default_basis="handbook", symbol="b", page="20-11",
                help="Table 20-6: actuator 0.007, compressor 0.025, motor 0.010, pump 0.007 in; 0.007 by default."),
            *_section_inputs(),
            num("r", "Fillet radius at the shoulder", "in", [positive("a radius is more than zero")], symbol="r",
                page="20-8"),
            num("D_big", "Shaft diameter before the shoulder", "in", [positive("a diameter is more than zero")],
                symbol="D", page="20-8"),
            num("d_small", "Shaft diameter after the shoulder", "in", [positive("a diameter is more than zero")],
                symbol="d", page="20-8"),
            choice("groove", "Shaft grooves (Table 20-4)", _GROOVES, default="none", default_basis="handbook",
                   symbol="C_SC,G", page="20-10", help="No grooves: the handbook's groove factor is 1.0."),
        ],
        derived=[
            derived("C_SC_R", "Shoulder stress concentration", "(0.3 / (r / d_small)) ** 0.2 * "
                    "(D_big / d_small) ** (1 - r / d_small)", "", "C_SC,R", "20-8", "20-10"),
            derived("C_SC_G", "Groove stress concentration (Table 20-4)", _groove_expr(), "", "C_SC,G", "20-10"),
        ],
        checks=[
            check("len_X > 0", "Shaft section X (the overhang to the load) needs a length", "20-7",
                  severity="refuse"),
            *[check(f"len_{s} == 0 or D_{s} > 0", f"Shaft section {s} has a length, so it needs its diameter",
                    "20-7", severity="refuse") for s in _SECTIONS],
            check("D_big >= d_small", "D is the larger diameter at the shoulder and d the smaller", "20-8"),
        ],
        modes=[mode("shaft", "Shaft (fatigue, deflection, fracture)",
                    base("λ_SH,B", "Base failure rate (10⁶ ÷ cycles to failure)", "20-5", expr="1e6 / N_cycles",
                         equation="20-4"),
                    [
                        factor("C_f", "Surface finish" + (" (rate ÷ Table 20-3's factor)"
                                                          if readings.SHAFT_FINISH_INVERTED else ""), "20-10",
                               expr=_CF if not readings.SHAFT_FINISH_INVERTED else f"1 / ({_CF})",
                               source="Table 20-3",
                               words="a rougher finish" if readings.SHAFT_FINISH_INVERTED else "its surface finish"),
                        factor("C_T", "Material temperature", "20-6", expr="(460 + T_AT) / 620 if T_AT > 160 else 1.0",
                               equation="20-5", words="running above 160 °F"),
                        factor("C_DY", "Shaft displacement", "20-7",
                               expr="0.0043 * F / (E * b) * (" + " + ".join(_section_term(s) for s in _SECTIONS) + ")",
                               equation="20-8", words="a heavier load or a longer, thinner shaft"),
                        factor("C_SC", "Stress concentration", "20-8",
                               expr="C_SC_R * C_SC_G",
                               equation="20-9", source="Table 20-4", words="sharp fillets and grooves"),
                    ], symbol="λ_SH")],
        rate_unit="per_million_hours" if readings.SHAFT_PER_HOUR else "per_million_cycles",
        failure_modes=_FAILURE_MODES,
        notes=" ".join([UNIT_NOTE, FINISH_NOTE,
                        "Reliafy's reading (p. 20-8): Eq. 20-9 prints C_SC = C_SC,R + C_SC,G, but the page says "
                        "C_SC,G = 1.0 with no grooves, which is the neutral value of a product; C_SC,R × C_SC,G is "
                        "used. C_DY's 0.0043 constant keeps it near 10⁻³ for an ordinary shaft, so the deflection "
                        "factor dominates (p. 20-7). The model assumes a constant torque and completely reversed "
                        "bending from rotation; for large reciprocating loads (piston engines, compressors) the "
                        "handbook says the rate must be analysed and adjusted (p. 20-5)."]),
    ),
]
