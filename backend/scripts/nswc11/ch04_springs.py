"""Chapter 4, Springs (Revision E): helical compression (Eq. 4-6), extension
(Section 4.4.2), helical torsion (Eq. 4-12), curved washer (Eq. 4-14), wave washer
(Eq. 4-16), Belleville washer (Eq. 4-18), cantilever (Eq. 4-20) and beam (Eq. 4-22).

Checked against the rendered pages 4-10 to 4-40:
- Every size and stress factor is (value ÷ reference)^n, the reference being where
  the factor is 1: C_G = (G_M/11.5×10⁶)³, C_E = (E_M/28.5×10⁶)³ (Table 4-2, p. 4-39),
  C_Y = (190×10³/T_S)³ (Table 4-3, p. 4-40), C_DW = (D_W/0.085)³ (Figure 4.10),
  C_N = (14/N_a)³ (Figure 4.12), C_L = ((L1 − L2)/1.07)³ (Figure 4.13),
  C_K = (K_W/1.219)³ (Figure 4.14), torsion C_L = (θ/0.667)³ (Figure 4.15),
  C_t = (t/0.025)³ (Figure 4.16), C_D = (1.20/OD)⁶ (Figure 4.17),
  C_f = (f/0.055)³ (Figure 4.18), torsion C_DC = (0.58/D_C)³ (Figure 4.21),
  cantilever and beam C_L = (1.20/L)⁶ (Figure 4.22), C_NW = (5/N)² (Table 4-4).
- C_DC for compression springs (Figure 4.11, p. 4-27): the printed formula is
  (0.58/D_C)⁶ but the plotted curve is (0.58/D_C)³ (0.2 at 1 in, 7 at 0.3 in; the
  same curve as Figure 4.21 for torsion springs). The model uses the formula's
  6th power: Eq. 4-3 with Eq. 4-1 makes the stress go as 1/D_C², so (S/T_S)³ goes
  as D_C⁻⁶, and the other factors follow the same cube-of-stress rule.
- K_W: Eq. 4-4 (p. 4-12) has 0.615/r, Figure 4.14 (p. 4-30) 0.616/r. The model uses
  Eq. 4-4's 0.615 (the Wahl factor); at r = 0.58/0.085 it gives the reference 1.219.
- Torsion springs: Eq. 4-12's list (p. 4-15) points C_L at Figure 4.13 (the
  compression spring's deflection in inches); a torsion spring's deflection is in
  revolutions, and Figure 4.15 (p. 4-31) is "Deflection of a Torsion Spring". The
  model uses Figure 4.15.
- C_S (Figure 4.19, p. 4-35): (6/(π ln R))³ · ((R − 1)/ln R − 1) · ((R − 1)/2) ·
  ((R − 1)²/R²), R = OD/ID; it gives 1.16 at R = 2 and 0.31 at R = 1.2, as plotted.
- C_CS (Figure 4.20, p. 4-36): 0.1 up to 30 cycles/min, CR/300 to 300, (CR/300)³
  above; the pieces meet at 300 (and nearly at 30: 0.1).
- C_R and C_M (Sections 4.3.10, 4.3.11, p. 4-9/4-10): 1.0 with corrosion protection
  and known quality control; higher by experience. They're inputs.
- Tables 4-2 and 4-3 are the formulas' values for typical materials; the tests
  check them, and the few rows that don't match their own formula are noted there.
- Chapter 1's worked spring (Table 1-1, p. 1-12, λ_SP = 1.04) uses Eq. 4-5
  (λ_SP,B · (S_G/T_S)³) directly, not Eq. 4-6; the tests show both.
"""

from backend.scripts.nswc11.common import (
    base, check, derived, factor, mode, num, positive, record, warn,
)

_FAILURE_MODES = [
    "Static springs: load loss, creep, set, yielding (hydrogen embrittlement, parameter change)",
    "Cyclic springs: fracture, damaged ends, fatigue, buckling, surging (excessive mean stress, flaws, heat, "
    "tooling marks, sharp end bends, corrosion, misalignment, stress range, vibration)",
    "Dynamic loading: fracture, fatigue (load ratio exceeded, shock, surface defects, resonance surging)",
]


# ---- inputs ------------------------------------------------------------------------------------

def _modulus_g() -> dict:
    return num("G_M", "Modulus of rigidity of the spring material", "psi", [
        positive("a modulus is more than zero"),
    ], symbol="G_M", page="4-39",
        help="Table 4-2: music wire 11.8×10⁶, hard-drawn steel 11.5×10⁶ (factor 1), chrome steel 11.2×10⁶, "
             "stainless 302/304/316 10.0×10⁶, phosphor bronze 6.0×10⁶, beryllium copper 7.0×10⁶.")


def _modulus_e() -> dict:
    return num("E_M", "Modulus of elasticity of the spring material", "psi", [
        positive("a modulus is more than zero"),
    ], symbol="E_M", page="4-39",
        help="Table 4-2: hard-drawn steel 28.5×10⁶ (factor 1), music wire and chrome steel 29.0×10⁶, "
             "stainless 302/304/316 28.0×10⁶, phosphor bronze 15.0×10⁶, beryllium copper 17.0×10⁶.")


def _tensile() -> dict:
    return num("T_S", "Tensile strength of the spring material", "psi", [
        positive("a tensile strength is more than zero"),
        warn(min=110e3, max=295e3, why="Table 4-3 covers 110,000 to 295,000 psi", page="4-40"),
    ], symbol="T_S", page="4-40",
        help="Table 4-3 (for 0.1 in wire): brass 110,000, phosphor bronze 125,000, copper-beryllium 190,000 "
             "(factor 1), hard-drawn steel 216,000, spring temper steel 245,000, music wire 295,000 psi.")


def _cycle_rate() -> dict:
    return num("cycle_rate", "Spring cycle rate", "cycles/min", [
        {"min": 0, "severity": "refuse", "why": "a cycle rate can't be negative"},
        warn(max=500, why="Figure 4.20 covers 0 to 500 cycles/min", page="4-36"),
    ], symbol="CR", page="4-36", help="Up to 30 cycles a minute the factor is 0.1 (a spring that rarely cycles).")


def _experience() -> list[dict]:
    return [
        num("C_R", "Corrosion factor (from experience)", "", [
            positive("a factor is more than zero"),
            warn(min=1.0, why="the handbook uses 1.0 with corrosion protection and higher values from experience",
                 page="4-9"),
        ], default=1.0, default_basis="handbook", symbol="C_R", page="4-9",
            help="1.0 when the spring is protected against corrosion; more than 1 from your experience of the "
                 "spring in its environment."),
        num("C_M", "Manufacturing quality factor (from experience)", "", [
            positive("a factor is more than zero"),
            warn(min=1.0, why="the handbook uses 1.0 for known acceptable quality control, higher otherwise",
                 page="4-10"),
        ], default=1.0, default_basis="handbook", symbol="C_M", page="4-10",
            help="1.0 for known acceptable quality control; more than 1 from experience with the maker."),
    ]


def _wire() -> dict:
    return num("D_W", "Wire diameter", "in", [
        positive("a wire has a diameter"),
        warn(min=0.01, max=0.17, why="Figure 4.10 covers 0.01 to 0.17 in", page="4-26"),
    ], symbol="D_W", page="4-26")


def _coils(help: str) -> dict:
    return num("N_a", "Number of active coils", "", [
        positive("a spring has active coils"),
        warn(min=5, max=25, why="Figure 4.12 covers 5 to 25 active coils", page="4-28"),
    ], symbol="N_a", page="4-9", help=help)


def _thickness() -> dict:
    return num("t", "Material thickness", "in", [
        positive("a thickness is more than zero"),
        warn(min=0.01, max=0.08, why="Figure 4.16 covers 0.01 to 0.08 in", page="4-32"),
    ], symbol="t", page="4-32")


def _deflection(what: str) -> dict:
    return num("f", f"{what} deflection", "in", [
        {"min": 0, "severity": "refuse", "why": "a deflection can't be negative"},
        warn(min=0.01, max=0.15, why="Figure 4.18 covers 0.01 to 0.15 in", page="4-34"),
    ], symbol="f", page="4-34")


def _washer_od() -> dict:
    return num("OD", "Outside diameter of the washer", "in", [
        positive("a washer has a diameter"),
        warn(min=0.6, max=3.5, why="Figure 4.17 covers 0.6 to 3.5 in", page="4-33"),
    ], symbol="OD", page="4-33")


# ---- factors -----------------------------------------------------------------------------------

def _cg() -> dict:
    return factor("C_G", "Modulus of rigidity", "4-39", expr="(G_M / 11.5e6) ** 3", source="Table 4-2",
                  words="a stiffer material in shear")


def _ce() -> dict:
    return factor("C_E", "Modulus of elasticity", "4-39", expr="(E_M / 28.5e6) ** 3", source="Table 4-2",
                  words="a stiffer material")


def _cy() -> dict:
    return factor("C_Y", "Tensile strength", "4-40", expr="(190e3 / T_S) ** 3", source="Table 4-3",
                  words="a weaker material")


def _cdw() -> dict:
    return factor("C_DW", "Wire diameter", "4-26", expr="(D_W / 0.085) ** 3", source="Figure 4.10",
                  words="thicker wire (more stress for the deflection)")


def _cn() -> dict:
    return factor("C_N", "Number of active coils", "4-28", expr="(14 / N_a) ** 3", source="Figure 4.12",
                  words="fewer active coils")


def _ccs() -> dict:
    return factor("C_CS", "Cycle rate", "4-36",
                  expr="0.1 if cycle_rate <= 30 else (cycle_rate / 300 if cycle_rate <= 300 else (cycle_rate / 300) ** 3)",
                  source="Figure 4.20", words="cycling faster")


def _cr_cm() -> list[dict]:
    return [factor("C_R", "Corrosive environment", "4-9", expr="C_R", words="a corrosive environment"),
            factor("C_M", "Manufacturing process", "4-10", expr="C_M", words="unproven quality control")]


def _ct() -> dict:
    return factor("C_t", "Material thickness", "4-32", expr="(t / 0.025) ** 3", source="Figure 4.16",
                  words="thicker material")


def _cd() -> dict:
    return factor("C_D", "Washer size", "4-33", expr="(1.20 / OD) ** 6", source="Figure 4.17",
                  words="a smaller washer")


def _cf() -> dict:
    return factor("C_f", "Deflection", "4-34", expr="(f / 0.055) ** 3", source="Figure 4.18",
                  words="more deflection")


def _cl_length() -> dict:
    return factor("C_L", "Spring length", "4-38", expr="(1.20 / L) ** 6", source="Figure 4.22",
                  words="a shorter spring")


def _helical(slug: str, name: str, section: str, equation: str, page: str, words: str, coils_help: str,
             notes: str) -> dict:
    return record(
        slug, name, "spring", 4, section, equation, page,
        "λ_SP = λ_SP,B · C_G · C_DW · C_DC · C_N · C_Y · C_L · C_K · C_CS · C_R · C_M",
        words,
        inputs=[
            _modulus_g(), _wire(),
            num("D_C", "Mean coil diameter", "in", [
                positive("a coil has a diameter"),
                warn(min=0.2, max=3.0, why="Figure 4.11 covers 0.2 to 3.0 in", page="4-27"),
            ], symbol="D_C", page="4-27"),
            _coils(coils_help), _tensile(),
            num("L1", "Spring length at the start of the stroke", "in", [positive("a length is more than zero")],
                symbol="L1", page="4-11"),
            num("L2", "Spring length at the end of the stroke", "in", [positive("a length is more than zero")],
                symbol="L2", page="4-11"),
            _cycle_rate(), *_experience(),
        ],
        derived=[
            derived("deflection", "Deflection in service", "abs(L1 - L2)", "in", "L1 − L2", "4-29",
                    limits=[warn(max=6.0, why="Figure 4.13 covers deflections up to 6 in", page="4-29")]),
            derived("r", "Spring index (coil ÷ wire diameter)", "D_C / D_W", "", "r", "4-12",
                    limits=[warn(min=4, max=16, why="Figure 4.14 covers spring indices 4 to 16", page="4-30")]),
            derived("K_W", "Wahl stress concentration factor", "(4 * r - 1) / (4 * r - 4) + 0.615 / r", "", "K_W",
                    "4-12", "4-4"),
        ],
        checks=[
            check("r > 1", "The coil diameter must be more than the wire diameter", "4-12", severity="refuse"),
            check("deflection > 0", "With no deflection between L1 and L2 the model gives no failures", "4-29"),
        ],
        modes=[mode("spring", "Spring (fatigue, relaxation)",
                    base("λ_SP,B", "Base failure rate of a helical spring", "4-12", value=23.8),
                    [
                        _cg(), _cdw(),
                        factor("C_DC", "Coil diameter", "4-27", expr="(0.58 / D_C) ** 6", source="Figure 4.11",
                               words="a smaller coil"),
                        _cn(), _cy(),
                        factor("C_L", "Deflection", "4-29", expr="(deflection / 1.07) ** 3", source="Figure 4.13",
                               words="more deflection"),
                        factor("C_K", "Stress concentration", "4-30", expr="(K_W / 1.219) ** 3",
                               source="Figure 4.14", words="a tightly wound coil (low spring index)"),
                        _ccs(), *_cr_cm(),
                    ], symbol="λ_SP")],
        notes=notes,
        failure_modes=_FAILURE_MODES,
    )


def _flat(slug: str, name: str, section: str, equation: str, page: str, base_rate: float, base_page: str,
          formula: str, words: str, extra_inputs: list[dict], factors: list[dict], derived_values=(),
          checks=(), notes=None) -> dict:
    return record(
        slug, name, "spring", 4, section, equation, page, formula, words,
        inputs=[_modulus_e(), *extra_inputs, _tensile(), _cycle_rate(), *_experience()],
        derived=list(derived_values), checks=list(checks),
        modes=[mode("spring", "Spring (fatigue, relaxation)",
                    base("λ_SP,B", f"Base failure rate of a {name.lower()}", base_page, value=base_rate),
                    factors, symbol="λ_SP")],
        notes=notes, failure_modes=_FAILURE_MODES,
    )


_STRESS_WORDS = ("the stiffness of its material, {what}, the strength of its material, how fast it cycles, "
                 "corrosion and manufacturing quality")

RECORDS = [
    _helical(
        "spring-compression", "Spring, helical compression", "4.4.1 Compression spring", "4-6", "4-12",
        "A compression spring's failure rate starts at 23.8 failures per million hours and is scaled by its "
        "stress against its strength, through " + _STRESS_WORDS.format(
            what="its wire and coil diameters, its active coils, its deflection and its stress concentration"
        ) + ".",
        "Closed ends (ground or not): total coils minus two (p. 4-9).",
        "Section 4.3.7: a conical, barrel or hourglass spring is split into increments, each rated, and their "
        "rates added. With an S10 life from the maker, use that (times 4.55 for an average life) with these "
        "factors instead (p. 4-5); the library has no separate record for that route yet. "
        "The handbook's Table 1-1 example (p. 1-12: seal 1.20, spring 1.04, poppet 0.35 per million hours) uses "
        "Chapter 1's physical equations (for the spring, Eq. 4-5: 23.8 × (S_G/T_S)³ = 1.04); this record uses the "
        "chapter's factor model, Eq. 4-6, normalised to a 190,000 psi wire and a cycle rate, which isn't "
        "algebraically the same: for Table 1-1's spring it gives 1.11 (C_Y 0.466, C_CS 0.1, every geometry "
        "factor 1).",
    ),
    _helical(
        "spring-extension", "Spring, helical extension", "4.4.2 Extension spring", "4-6", "4-13",
        "An extension spring is rated like a compression spring (Section 4.4.2): its failure rate starts at 23.8 "
        "failures per million hours and is scaled by its stress against its strength, through " + _STRESS_WORDS.format(
            what="its wire and coil diameters, its coils (all active), its extension and its stress concentration"
        ) + ".",
        "All coils of an extension spring are active (p. 4-9).",
        "Section 4.4.2 rates extension springs with the compression spring's Eq. 4-6, all coils active. Most "
        "extension springs fail at their ends (p. 4-6): hooks need a bend radius of at least 1.5 wire diameters.",
    ),
    record(
        "spring-torsion", "Spring, helical torsion", "spring", 4, "4.4.3 Torsion spring", "4-12", "4-15",
        "λ_SP = λ_SP,B · C_E · C_DW · C_N · C_Y · C_L · C_CS · C_DC · C_R · C_M",
        "A torsion spring's failure rate starts at 14.3 failures per million hours and is scaled by its bending "
        "stress against its strength, through " + _STRESS_WORDS.format(
            what="its wire and coil diameters, its active coils and how far it turns") + ".",
        inputs=[
            _modulus_e(), _wire(),
            num("D_C", "Mean coil diameter", "in", [
                positive("a coil has a diameter"),
                warn(min=0.2, max=3.0, why="Figure 4.21 covers 0.2 to 3.0 in", page="4-37"),
            ], symbol="D_C", page="4-37", help="(OD + ID) / 2 (Eq. 4-7)."),
            _coils("Section 4.3.8."), _tensile(),
            num("theta", "Angular deflection from the free position", "revolutions", [
                {"min": 0, "severity": "refuse", "why": "a deflection can't be negative"},
                warn(min=0.05, max=1.4, why="Figure 4.15 covers 0.05 to 1.4 revolutions", page="4-31"),
            ], symbol="θ", page="4-31"),
            _cycle_rate(), *_experience(),
        ],
        modes=[mode("spring", "Spring (fatigue, relaxation)",
                    base("λ_SP,B", "Base failure rate of a torsion spring", "4-15", value=14.3),
                    [
                        _ce(), _cdw(), _cn(), _cy(),
                        factor("C_L", "Angular deflection", "4-31", expr="(theta / 0.667) ** 3", source="Figure 4.15",
                               words="turning it further"),
                        _ccs(),
                        factor("C_DC", "Coil diameter", "4-37", expr="(0.58 / D_C) ** 3", source="Figure 4.21",
                               words="a smaller coil"),
                        *_cr_cm(),
                    ], symbol="λ_SP")],
        notes=("Eq. 4-12 points C_L at Figure 4.13; the model uses Figure 4.15, the torsion spring's deflection in "
               "revolutions. Load a torsion spring so its coils close (p. 4-13)."),
        failure_modes=_FAILURE_MODES,
    ),
    _flat("spring-curved-washer", "Curved washer", "4.4.4 Curved washer", "4-14", "4-17", 1.1, "4-17",
          "λ_SP = λ_SP,B · C_E · C_t · C_D · C_Y · C_f · C_CS · C_R · C_M",
          "A curved washer's failure rate starts at 1.1 failures per million hours and is scaled by its stress "
          "against its strength, through " + _STRESS_WORDS.format(
              what="its thickness, its diameter and how far it flattens") + ".",
          [_thickness(), _washer_od(), _deflection("Washer")],
          [_ce(), _ct(), _cd(), _cy(), _cf(), _ccs(), *_cr_cm()]),
    _flat("spring-wave-washer", "Wave washer", "4.4.5 Wave washer", "4-16", "4-19", 1.9, "4-19",
          "λ_SP = λ_SP,B · C_E · C_t · C_D · C_Y · C_f · C_NW · C_CS · C_R · C_M",
          "A wave washer's failure rate starts at 1.9 failures per million hours and is scaled by its stress "
          "against its strength, through " + _STRESS_WORDS.format(
              what="its thickness, its diameter, how far it flattens and its number of waves") + ".",
          [_thickness(), _washer_od(), _deflection("Washer"),
           num("N", "Number of waves", "", [
               positive("a wave washer has waves"),
               warn(min=3, max=8, why="Table 4-4 covers 3 to 8 waves", page="4-40"),
           ], symbol="N", page="4-40")],
          [_ce(), _ct(), _cd(), _cy(), _cf(),
           factor("C_NW", "Number of waves", "4-40", expr="(5 / N) ** 2", source="Table 4-4", words="fewer waves"),
           _ccs(), *_cr_cm()]),
    _flat("spring-belleville", "Belleville washer", "4.4.6 Belleville washer", "4-18", "4-21", 2.6, "4-21",
          "λ_SP = λ_SP,B · C_E · C_t · C_D · C_f · C_Y · C_S · C_CS · C_R · C_M",
          "A Belleville washer's failure rate starts at 2.6 failures per million hours and is scaled by its "
          "stress against its strength, through " + _STRESS_WORDS.format(
              what="its thickness, its diameter, how far it flattens and its outside-to-inside diameter ratio") + ".",
          [_thickness(), _washer_od(), _deflection("Washer"),
           num("ID", "Inside diameter of the washer", "in", [positive("a washer has an inside diameter")],
               symbol="ID", page="4-35")],
          [_ce(), _ct(), _cd(), _cf(), _cy(),
           factor("C_S", "Compressive stress (diameter ratio)", "4-35",
                  expr="(6 / (pi() * ln(R))) ** 3 * ((R - 1) / ln(R) - 1) * ((R - 1) / 2) * ((R - 1) ** 2 / R ** 2)",
                  source="Figure 4.19", words="a wider washer for its hole"),
           _ccs(), *_cr_cm()],
          derived_values=[derived("R", "Outside ÷ inside diameter", "OD / ID", "", "R", "4-35",
                                  limits=[warn(min=1.2, max=5.0, why="Figure 4.19 covers R from 1.2 to 5.0",
                                               page="4-35")])],
          checks=[check("R > 1", "The outside diameter must be more than the inside diameter", "4-35",
                        severity="refuse")]),
    _flat("spring-cantilever", "Cantilever spring (flat strip)", "4.4.7 Cantilever spring", "4-20", "4-23", 1.1,
          "4-23",
          "λ_SP = λ_SP,B · C_E · C_t · C_L · C_f · C_Y · C_CS · C_R · C_M",
          "A cantilever spring's failure rate starts at 1.1 failures per million hours and is scaled by its "
          "bending stress against its strength, through " + _STRESS_WORDS.format(
              what="its thickness, its length and how far it deflects") + ".",
          [_thickness(),
           num("L", "Active length of the spring", "in", [
               positive("a spring has a length"),
               warn(min=0.6, max=3.5, why="Figure 4.22 covers 0.6 to 3.5 in", page="4-38"),
           ], symbol="L", page="4-38"),
           _deflection("Spring")],
          [_ce(), _ct(), _cl_length(), _cf(), _cy(), _ccs(), *_cr_cm()],
          notes="In a complex part only the portion that acts as a spring is rated (p. 4-22)."),
    _flat("spring-beam", "Beam spring (formed arc)", "4.4.8 Beam spring", "4-22", "4-25", 4.4, "4-25",
          "λ_SP = λ_SP,B · C_E · C_t · C_L · C_f · C_Y · C_CS · C_R · C_M",
          "A beam spring's failure rate starts at 4.4 failures per million hours and is scaled by its bending "
          "stress against its strength, through " + _STRESS_WORDS.format(
              what="its thickness, its length and how far it deflects") + ".",
          [_thickness(),
           num("L", "Active length of the spring", "in", [
               positive("a spring has a length"),
               warn(min=0.6, max=3.5, why="Figure 4.22 covers 0.6 to 3.5 in", page="4-38"),
           ], symbol="L", page="4-38"),
           _deflection("Spring")],
          [_ce(), _ct(), _cl_length(), _cf(), _cy(), _ccs(), *_cr_cm()],
          notes="Eq. 4-21's stress assumes the ends are free to expand sideways (p. 4-23)."),
]
