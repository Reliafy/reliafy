"""Chapter 12, Brakes and clutches (Revision C): the brake friction material
(Eq. 12-6), the clutch friction material (Eq. 12-16), and the brake (Eq. 12-1)
and clutch (Eq. 12-11) assemblies.

Checked against the rendered pages 12-9 to 12-20:
- Eq. 12-6 (p. 12-11): λ_FR = λ_FR,B · C_BT · C_RD · C_T; Eq. 12-16 (p. 12-18):
  λ_CF = λ_CF,B · C_NP · C_T. Both in failures per million hours.
- The base rate (Eq. 12-5, p. 12-11; Eq. 12-15, p. 12-18) is 1/Life = W_p/d =
  k_o·P·v_s·t / (d·A): failures per application, not per hour. The pages say the
  model comes from "normalizing" it to historical failure rate data but give no
  normalisation. Reading chosen: per application × applications per hour × 10⁶,
  the conversion the chapter itself gives for per-cycle rates (pp. 12-10, 12-16).
  A maker's base rate can be used instead (the *-known-rate records); the page
  warns a maker's rate may be per brake actuation (p. 12-11): convert it the
  same way.
- Section 12.4.5.1 refers to "Equation (12-13)" for the clutch base rate and
  calls it λ_FR,B; the procedure is Eq. 12-15 (λ_CF,B). Read as Eq. 12-15.
- Table 12-8 (p. 12-20): wear coefficients. Carbon-carbon prints as "2..24 × 10⁻¹¹",
  read as 2.24 × 10⁻¹¹.
- C_BT (p. 12-12): drum 1.25, slotted annular disk 1.25, pad disk 1.00,
  annulus disk 0.90.
- C_RD (Table 12-6, p. 12-12) applies to operation with high amounts of dust; the
  model applies it only when the user says the brake works in heavy dust.
- C_T (Eqs. 12-7 to 12-10, p. 12-13; 12-17 to 12-20, p. 12-19): quadratics in
  X = 590 + T (T ambient, °F). The brake page prints 0.00759 in the carbon-carbon
  equation (12-9) and the clutch page 0.00758 (12-19); each record uses its own
  page's figure. The handbook gives no temperature range; every quadratic stays
  positive for any temperature, and each is about 1 at 70 °F.
- C_NP (p. 12-19) = the number of disks. Ambiguity: the text above it (p. 12-18)
  says multiple plates "increase the reliability", yet the factor multiplies the
  rate by the number of disks. The model follows the printed factor and says so.
- Assemblies (Eq. 12-1, p. 12-9; Eq. 12-11, p. 12-15): the parts' rates are added
  in failures per million hours; a part rated per million cycles is multiplied
  by its cycles per hour (pp. 12-10, 12-16). The actuator is taken as axially
  loaded (it pushes the friction parts together), Eq. 9-6; the seals as dynamic
  seals, the springs as compression springs and the bearings from their load
  rating. Brake housing: 3.0 failures per million hours (p. 12-9).
- No worked example in the chapter.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, factor, mode, non_negative, num, positive, record, refuse, table, uses,
)

_LINING_FAILURE_MODES = [
    "Heat spotting: heavy gouging and rapid lining wear (rubbing against a heat-spotted metal part)",
    "Crazing: random cracks and a high wear rate (overheating)",
    "Scoring: grooves that shorten its life (the metal part needs regrinding)",
    "Fade: temporary loss of performance (overheating from excessive braking)",
    "Metal pick-up (an unsuitable pair of materials)",
    "Grab, strip braking and misalignment (lining radius, distorted path, poor fitting)",
    "Worn through (maintenance neglected)",
]
_BRAKE_FAILURE_MODES = [
    "Sticking piston or leaking cylinder (contamination): low output pressure",
    "Broken or weak spring (fatigue)",
    "Sticking bleeder valve (contamination)",
    "Deteriorated lining (age, heat): metal-on-metal contact",
    "Worn bearing (lack of lubrication)",
    "Worn seals (age): external leakage",
    "Cracked housing (vibration, fatigue)",
]
_CLUTCH_FAILURE_MODES = [
    "Dishing, waviness or buckling of the plates (lack of conformability, uneven heating)",
    "Banding or crushing of the friction material",
    "Material transfer to the opposing plate (overheating, unsuitable material)",
    "Bond failure (poor bonding, overheating)",
    "Burst failure of the facing at high speed",
    "Grooving, reduced friction from oil or grease, distortion",
    "Loss of fluid pressure in hydraulic clutches (seal leakage)",
]

#: Table 12-8 (p. 12-20): wear coefficient k_o, psi⁻¹, against cast iron or steel.
_MATERIALS = [
    ("asbestos_1", "Asbestos type I composite", 6.46e-11),
    ("asbestos_2", "Asbestos type II composite", 8.09e-11),
    ("carbon_carbon", "Carbon-carbon composite", 2.24e-11),
    ("sintered_bronze_dry", "Sintered bronze (dry)", 2.42e-10),
    ("non_asbestos_dry", "Non-asbestos composite (dry)", 9.90e-10),
    ("sintered_bronze_wet", "Sintered bronze (wet)", 5.02e-13),
    ("sintered_bronze_composite", "Sintered bronze composite", 9.31e-11),
    ("sintered_resin_composite", "Sintered resin composite", 3.03e-11),
]
K_O = {c: k for c, _, k in _MATERIALS}

#: C_T quadratics (a, b, c in a − b·X + c·X²), brake page 12-13 and clutch page 12-19.
_CT_BRAKE = {
    "sintered_metallic": (1.42, 0.00154, 0.00000138),
    "resin_asbestos": (2.79, 0.0109, 0.0000124),
    "carbon_carbon": (3.80, 0.00759, 0.00000507),
    "resin_asbestos_truck": (17.59, 0.0603, 0.0000534),
}
_CT_CLUTCH = {**_CT_BRAKE, "carbon_carbon": (3.80, 0.00758, 0.00000507)}


def _select(name: str, values: dict) -> str:
    """An expression picking ``values[name]`` by a choice's code (a chain of ``a if … else``)."""
    items = list(values.items())
    out = repr(items[-1][1])
    for code, v in reversed(items[:-1]):
        out = f"{v!r} if {name} == {code!r} else {out}"
    return f"({out})"


def _ct(coeffs: dict) -> str:
    """C_T = a − b·X + c·X², a, b, c by lining type."""
    out = None
    for code, (a, b, c) in reversed(list(coeffs.items())):
        term = f"({a} - {b} * X + {c} * X ** 2)"
        out = term if out is None else f"{term} if lining_type == '{code}' else {out}"
    return f"1.0 if lining_type == 'other' else {out}"


def _lining_type(page: str, clutch: bool) -> dict:
    return choice("lining_type", "Lining type (for the temperature factor)", [
        ("sintered_metallic", "Sintered metallic" + ("" if clutch else " (truck linings)")),
        ("resin_asbestos", "Resin-asbestos (automotive, moderate-duty industrial)"),
        ("carbon_carbon", "Carbon-carbon"),
        ("resin_asbestos_truck", "Resin-asbestos (truck linings)"),
        ("other", "Another lining (no curve: C_T = 1)")], page=page,
        help="The handbook's four temperature curves (they aren't tied to the wear coefficient's material): pick "
             "the one that matches the lining, or 'another lining' for none of them.")


def _temperature(page: str) -> dict:
    return num("T", "Ambient temperature", "°F", [refuse(min=-459.67, exclusive=True, why="above absolute zero")],
               default=70, default_basis="typical", symbol="T", page=page,
               help="The factor is about 1 at 70 °F.")


def _material(page: str) -> dict:
    return choice("material", "Lining (pad) material (wear coefficient)", [(c, lab) for c, lab, _ in _MATERIALS],
                  symbol="k_o", page=page, help="Table 12-8: against cast iron or steel.")


def _wear_inputs(time_name: str, time_symbol: str, time_label: str, page: str, what: str) -> list[dict]:
    return [
        _material("12-20"),
        num("P", "Applied load", "lbf", [positive("the load is more than zero")], symbol="P", page=page),
        num("v_s", "Sliding velocity", "in/s", [positive("the velocity is more than zero")], symbol="v_s", page=page),
        num(time_name, time_label, "s", [positive("the time is more than zero")], symbol=time_symbol, page=page),
        num("d", "Lining thickness (effective)", "in", [positive("a thickness is more than zero")], symbol="d",
            page=page),
        num("A", f"{what} lining area", "in²", [positive("an area is more than zero")], symbol="A", page=page),
        num("n_per_hour", f"{what} applications per hour", "per hour", [positive("it must be applied")],
            symbol="n", page="12-10" if what == "Brake" else "12-16",
            help="Converts the wear rate per application into a rate per hour."),
    ]


_BRAKE_FACTOR_INPUTS = [
    choice("brake_type", "Brake type", [
        ("drum", "Drum brake"), ("slotted_annular", "Slotted annular disk brake"), ("pad", "Pad disk brake"),
        ("annulus", "Annulus disk brake")], default="pad", default_basis="neutral", symbol="C_BT", page="12-12"),
    choice("dust", "Dust", [("normal", "Normal conditions"), ("heavy", "High amounts of dust")],
           default="normal", default_basis="neutral", page="12-12"),
    choice("binder", "Binder resin of the friction material", [
        ("phenolic", "Phenolic"), ("oil_modified_phenolic", "Oil-modified phenolic"),
        ("rubber_phenolic", "Rubber phenolic"), ("cashew", "Cashew"), ("oil_phenolic", "Oil-phenolic")],
        default="phenolic", default_basis="typical", symbol="C_RD", page="12-12",
        help="Only matters in heavy dust."),
    _lining_type("12-13", clutch=False),
    _temperature("12-13"),
]


def _brake_factors() -> list[dict]:
    return [
        factor("C_BT", "Brake type", "12-12", table=table("brake_type", {
            "drum": 1.25, "slotted_annular": 1.25, "pad": 1.00, "annulus": 0.90}),
            words="drum and slotted brakes (heat dissipation)"),
        factor("C_RD", "Dust contaminants", "12-12", table=table("binder", {
            "phenolic": 3.5, "oil_modified_phenolic": 1.2, "rubber_phenolic": 1.1, "cashew": 1.1,
            "oil_phenolic": 1.1}), source="Table 12-6", when="dust == 'heavy'", words="heavy dust"),
        factor("C_T", "Ambient temperature", "12-13", expr=_ct(_CT_BRAKE), equation="12-7 to 12-10",
               words="ambient temperature away from about 70 °F"),
    ]


_CLUTCH_FACTOR_INPUTS = [
    num("N_P", "Number of disks in the clutch", "", [refuse(min=1, why="a clutch has at least one disk")],
        default=1, default_basis="neutral", symbol="C_NP", page="12-19"),
    _lining_type("12-19", clutch=True),
    _temperature("12-19"),
]


def _clutch_factors() -> list[dict]:
    return [
        factor("C_NP", "Number of plates", "12-19", expr="N_P", words="more disks (as the factor is printed)"),
        factor("C_T", "Ambient temperature", "12-19", expr=_ct(_CT_CLUTCH), equation="12-17 to 12-20",
               words="ambient temperature away from about 70 °F"),
    ]


_X = derived("X", "590 + ambient temperature", "590 + T", "", "X", "12-13")
_CNP_CHECK = check("N_P == 1", "C_NP multiplies the rate by the number of disks, as printed (p. 12-19), though p. 12-18 "
                   "says multiple plates increase the reliability; with a maker's rate for the whole disk pack, set "
                   "the number of disks to 1", "12-19")
_T_CHECK = check("-40 <= T <= 200", "The temperature curves have no stated range; outside about −40 to 200 °F they're "
                 "extrapolated", "12-13")
_KO = derived("k_o", "Wear coefficient", _select("material", K_O), "1/psi", "k_o", "12-20")

_KNOWN_RATE_HELP = ("From the lining's maker. If it's per application, multiply by the applications per hour "
                    "(and by 10⁶ for per million).")


def _known(name: str) -> dict:
    return num("lambda_B", "Base failure rate from the maker", "failures per million hours",
               [positive("a failure rate is more than zero")], symbol=name, page="12-11", help=_KNOWN_RATE_HELP)


def _parts(friction_slug: str, friction_name: str) -> list[dict]:
    sym = "λ_FR" if "brake" in friction_slug else "λ_CF"
    return [
        uses("actuators", "Actuators", "actuator-axial-load", symbol="λ_AC", scale="AC_cycles_per_hour",
             scale_label="actuator cycles an hour (all actuators)",
             note="Chapter 9 gives actuators in failures per million cycles; the handbook multiplies by cycles per "
                  "hour (pp. 12-10, 12-16), so this part is its rate × the actuator cycles per hour (all actuators "
                  "together)."),
        uses("springs", "Springs", "spring-compression", symbol="λ_SP", count="n_SP"),
        uses("friction", friction_name + " (from its wear)", friction_slug, symbol=sym, when="lining == 'wear'"),
        uses("friction_maker", friction_name + " (from the maker's rate)", friction_slug + "-known-rate", symbol=sym,
             when="lining == 'maker'"),
        uses("bearings", "Bearings", "bearing-rolling-load-rating", symbol="λ_BE", count="n_BE"),
        uses("seals", "Seals", "seal-dynamic", symbol="λ_SE", count="n_SE"),
    ]


def _lining(brake: bool) -> dict:
    choices = [("wear", "From its wear (the lining's wear coefficient, load and speed)"),
               ("maker", "From the maker's base failure rate")]
    if brake:
        choices.append(("none", "None: a magnetic particle, hysteresis or eddy-current brake (no friction lining)"))
    return choice("lining", "Friction material rated", choices, default="wear", default_basis="typical",
                  page="12-7" if brake else "12-16",
                  help="Which friction material model the assembly adds" + (
                      "; magnetic particle, hysteresis and eddy-current brakes brake without friction (p. 12-7)."
                      if brake else "."))


def _counts() -> list[dict]:
    return [
        num("AC_cycles_per_hour", "Actuator cycles per hour (all actuators together)", "per hour",
            [non_negative()], symbol="cycles/h", page="12-10",
            help="Turns the actuators' rate per million cycles into one per million hours."),
        num("n_SP", "Number of springs", "", [non_negative()], symbol="n_SP", page="12-9"),
        num("n_BE", "Number of bearings", "", [non_negative()], symbol="n_BE", page="12-9"),
        num("n_SE", "Number of seals", "", [non_negative()], symbol="n_SE", page="12-9"),
    ]


RECORDS = [
    record(
        "brake-friction-material", "Brake friction material (lining or pad, from its wear)", "brake_clutch", 12,
        "12.3.5 Disk / brake lining reliability model", "12-6", "12-11",
        "λ_FR = λ_FR,B · C_BT · C_RD · C_T, with λ_FR,B = 10⁶ · n · k_o·P·v_s·t_b / (d·A) "
        "(Eq. 12-5 per application × applications per hour) and C_T = a − b·X + c·X², X = 590 + T",
        "A brake lining fails when it wears through. Its base rate is the share of the lining worn away by each "
        "application (from the wear coefficient, the load, the sliding speed and time, over its thickness and area), "
        "times the applications an hour. That is scaled by the brake type, heavy dust and the ambient temperature.",
        inputs=[*_wear_inputs("t_b", "t_b", "Braking time per application", "12-10", "Brake"),
                *_BRAKE_FACTOR_INPUTS],
        checks=[_T_CHECK],
        derived=[_KO, _X,
                 derived("W_p", "Lining wear per application", "k_o * P * v_s * t_b / A", "in", "W_p", "12-11",
                         "12-4"),
                 derived("life", "Applications until the lining is worn through", "d / W_p", "applications", "Life",
                         "12-10", "12-3")],
        modes=[mode("lining", "Friction material (wear)",
                    base("λ_FR,B", "Base failure rate (lining worn per application × applications per hour)",
                         "12-11", expr="1e6 * n_per_hour / life", equation="12-5"),
                    _brake_factors(), symbol="λ_FR")],
        failure_modes=_LINING_FAILURE_MODES,
    ),
    record(
        "brake-friction-material-known-rate", "Brake friction material (from the maker's rate)", "brake_clutch", 12,
        "12.3.5 Disk / brake lining reliability model", "12-6", "12-11",
        "λ_FR = λ_FR,B · C_BT · C_RD · C_T, with C_T = a − b·X + c·X², X = 590 + T",
        "When the lining's maker gives its base failure rate, a brake lining's rate is that, scaled by the brake "
        "type, heavy dust and the ambient temperature.",
        inputs=[_known("λ_FR,B"), *_BRAKE_FACTOR_INPUTS],
        checks=[_T_CHECK],
        derived=[_X],
        modes=[mode("lining", "Friction material (wear)",
                    base("λ_FR,B", "Base failure rate (from the maker)", "12-11", expr="lambda_B"),
                    _brake_factors(), symbol="λ_FR")],
        failure_modes=_LINING_FAILURE_MODES,
    ),
    record(
        "clutch-friction-material", "Clutch friction material (from its wear)", "brake_clutch", 12,
        "12.4.5 Clutch friction material reliability model", "12-16", "12-18",
        "λ_CF = λ_CF,B · C_NP · C_T, with λ_CF,B = 10⁶ · n · k_o·P·v_s·t_a / (d·A) "
        "(Eq. 12-15 per application × applications per hour) and C_T = a − b·X + c·X², X = 590 + T",
        "A clutch lining fails when it wears through. Its base rate is the share of the lining worn away by each "
        "engagement (from the wear coefficient, the load, the sliding speed and time, over its thickness and area), "
        "times the engagements an hour. That is scaled by the number of disks and the ambient temperature.",
        inputs=[*_wear_inputs("t_a", "t_a", "Clutch actuation (slip) time per engagement", "12-17", "Clutch"),
                *_CLUTCH_FACTOR_INPUTS],
        checks=[_CNP_CHECK, _T_CHECK],
        derived=[_KO, _X,
                 derived("W_p", "Lining wear per engagement", "k_o * P * v_s * t_a / A", "in", "W_p", "12-18",
                         "12-14"),
                 derived("life", "Engagements until the lining is worn through", "d / W_p", "applications", "Life",
                         "12-17", "12-13")],
        modes=[mode("lining", "Friction material (wear)",
                    base("λ_CF,B", "Base failure rate (lining worn per engagement × engagements per hour)",
                         "12-18", expr="1e6 * n_per_hour / life", equation="12-15"),
                    _clutch_factors(), symbol="λ_CF")],
        failure_modes=_CLUTCH_FAILURE_MODES,
    ),
    record(
        "clutch-friction-material-known-rate", "Clutch friction material (from the maker's rate)", "brake_clutch", 12,
        "12.4.5 Clutch friction material reliability model", "12-16", "12-18",
        "λ_CF = λ_CF,B · C_NP · C_T, with C_T = a − b·X + c·X², X = 590 + T",
        "When the clutch's maker gives its friction material's base failure rate, the rate is that, scaled by the "
        "number of disks and the ambient temperature.",
        inputs=[_known("λ_CF,B"), *_CLUTCH_FACTOR_INPUTS],
        checks=[_CNP_CHECK, _T_CHECK],
        derived=[_X],
        modes=[mode("lining", "Friction material (wear)",
                    base("λ_CF,B", "Base failure rate (from the maker)", "12-18", expr="lambda_B"),
                    _clutch_factors(), symbol="λ_CF")],
        failure_modes=_CLUTCH_FAILURE_MODES,
    ),
    record(
        "brake-assembly", "Brake assembly", "brake_clutch", 12, "12.3.4 Brake failure rate model", "12-1", "12-9",
        "λ_BR = λ_AC + λ_SP + λ_FR + λ_BE + λ_SE + λ_HO, λ_HO = 3.0",
        "A brake's failure rate is the sum of its parts: actuators, springs, the friction lining, bearings, seals and "
        "the housing (3.0 failures per million hours).",
        inputs=[_lining(True), *_counts()],
        modes=[*_parts("brake-friction-material", "Friction lining"),
               mode("housing", "Housing", base("λ_HO", "Brake housing failure rate", "12-9", value=3.0),
                    symbol="λ_HO")],
        failure_modes=_BRAKE_FAILURE_MODES,
    ),
    record(
        "clutch-assembly", "Clutch assembly", "brake_clutch", 12, "12.4.4 Clutch failure rate model", "12-11",
        "12-15",
        "λ_CL = λ_AC + λ_BE + λ_CF + λ_SE + λ_SP",
        "A clutch's failure rate is the sum of its parts: actuators, bearings, the friction material, seals and "
        "springs.",
        inputs=[_lining(False), *[{**c, "page": "12-15"} if c["name"] != "AC_cycles_per_hour" else {**c, "page": "12-16"}
                                  for c in _counts()]],
        modes=_parts("clutch-friction-material", "Friction material"),
        failure_modes=_CLUTCH_FAILURE_MODES,
    ),
]
