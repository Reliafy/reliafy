"""Chapter 9, Actuators (Revision C): the piston/cylinder actuator, Eq. 9-1, with
the base rate from the constant-wear life under a side load (Eq. 9-4) or an
axial load (Eq. 9-6), Eq. 9-14.

Checked against the rendered pages 9-5 to 9-17:
- Eq. 9-1 (p. 9-5): λ_AC = λ_AC,B · C_CP · C_T, failures per million cycles.
- Eq. 9-14 (p. 9-11): λ_AC,B = 10⁶ / N_O.
- Eq. 9-4 (p. 9-7), side load: N_O = k1 · [γ F_Y / ((W_S/L)·(D1−D2)/(D1·D2) /
  ((1−η1²)/E1 + (1−η2²)/E2))^½]⁹ with k1 = 15.4 × 10³. Eq. 9-3's 0.8 is not in
  Eq. 9-4: the page says k1 "includes a lubrication constant" (2000 / 0.8⁹ is
  about 14.9 × 10³, near but not 15.4 × 10³). The model follows Eq. 9-4 as
  printed and shows S_C (Eq. 9-3, with its 0.8) only as a derived value.
- Eq. 9-6 (pp. 9-7, 9-8), axial load: N_O = k2 · [γ F_Y / (W_A·((D1−D2)/(D1·D2))² /
  ((1−η1²)/E1 + (1−η2²)/E2)²)^⅓]⁹ with k2 = 17.7 × 10³; S_C (Eq. 9-5) has 0.9.
- γ (p. 9-6): 0.20 for materials prone to adhesive wear, 0.54 for little transfer.
- C_CP (Eq. 9-19, p. 9-14) = C_H · C_S · C_N. Ambiguity: the text defines
  C_H = H_P/H_C (piston ÷ cylinder hardness), but Table 9-1's caption (p. 9-16)
  says "use ratio of hardest particle/piston hardness for C_H", and the text
  above (p. 9-14) says wear rises with particle hardness over surface hardness,
  "normally the piston", negligible below 1. The model takes C_H as the hardest
  particle's hardness ÷ the piston's (the table caption and the physics), as one
  ratio input defaulting to 1.
- C_S = filter size (micron) / 10; C_N about 1.0, approaching 2.0 in severe
  conditions (p. 9-14).
- C_T (Eq. 9-22, p. 9-15) = exp[(θ/T_a)(1 − T_a/T)]. Ambiguity: the page gives
  T_a = 25.2 °C and T in °C, but this is an Arrhenius term (Eq. 9-20 has T in
  K), and Eq. 9-23's θ/T_a = 4 with θ = 1200 K only holds with T_a in kelvin
  (1200 / 298.35 = 4.02). The model uses absolute temperatures: T_a = 298.35 K
  (25.2 °C) and T = T_O + 273.15. In °C the factor would blow up below 25 °C and
  divide by zero at 0 °C. θ is an input (1200 K, the handbook's usual value;
  1200 to 6000 K, θ/T_a 4 to 20).
- The severe-wear phase (Eqs. 9-7 to 9-13) and the contaminant pitting check
  (Eq. 9-15) are not part of the rate: the handbook takes N_O as the life
  (p. 9-8). No worked example in the chapter.
"""

from backend.scripts.nswc11.common import (
    base, choice, derived, factor, mode, num, positive, record, refuse, warn,
)

_FAILURE_MODES = [
    "Internal leakage: lost or reduced output force (side loading, piston wear, contaminants past the rod seal)",
    "External leakage (seal leakage, piston and cylinder wear)",
    "Damaged rod seal lets contaminants in (excessive side loading)",
    "Spurious position change (stiction, binding)",
    "Jamming or seizure (excessive loading)",
    "Aeration: air drawn past the rod seals",
    "Bearing or lead nut failure (axial or side load on the thrust bearing over its rating)",
]

T_A_K = 298.35  # 25.2 °C, p. 9-15


def _geometry() -> list[dict]:
    return [
        num("D1", "Cylinder bore diameter", "in", [positive("a diameter is more than zero")], symbol="D1", page="9-6"),
        num("D2", "Piston diameter", "in", [positive("a diameter is more than zero")], symbol="D2", page="9-6"),
        num("eta1", "Poisson's ratio, cylinder", "", [refuse(min=0, max=0.5, why="Poisson's ratio of a solid is 0 to 0.5")],
            symbol="η1", page="9-6", help="About 0.3 for steels."),
        num("eta2", "Poisson's ratio, piston", "", [refuse(min=0, max=0.5, why="Poisson's ratio of a solid is 0 to 0.5")],
            symbol="η2", page="9-6"),
        num("E1", "Modulus of elasticity, cylinder", "psi", [positive("a modulus is more than zero")], symbol="E1",
            page="9-6", help="About 30 × 10⁶ psi for steel."),
        num("E2", "Modulus of elasticity, piston", "psi", [positive("a modulus is more than zero")], symbol="E2",
            page="9-7"),
        num("F_Y", "Yield strength of the softer material", "psi", [
            positive("a strength is more than zero"),
            warn(min=5000, max=120000, why="Table 9-3 covers 5 to 120 ksi", page="9-17"),
        ], symbol="F_Y", page="9-6"),
        choice("wear", "Wear behaviour of the materials (wear factor γ)", [
            ("adhesive", "High susceptibility to adhesive wear, material transfers (γ = 0.20)"),
            ("gouging", "Little transfer, micro-gouging by asperities (γ = 0.54)")],
            symbol="γ", page="9-6"),
    ]


def _conditions() -> list[dict]:
    return [
        num("C_H", "Hardest particle's hardness ÷ piston hardness", "", [
            positive("a ratio of hardnesses is more than zero")], default=1.0, default_basis="neutral", symbol="C_H",
            page="9-14", help="Hardnesses from Table 9-1 (p. 9-16). Below 1 the handbook expects negligible wear."),
        num("filter_micron", "Filter rating", "micron", [positive("a filter size is more than zero")], default=10,
            default_basis="neutral", symbol="C_S × 10", page="9-14", help="C_S = filter size ÷ 10, so 1 at 10 micron."),
        num("C_N", "Particle size and number factor", "", [
            positive("the factor is more than zero"),
            warn(min=1.0, max=2.0, why="about 1.0 for most applications, approaching 2.0 in severe contamination",
                 page="9-14")], default=1.0, default_basis="handbook", symbol="C_N", page="9-14"),
        num("T_O", "Operating temperature", "°C", [refuse(min=-273.15, exclusive=True, why="above absolute zero")],
            default=25.2, default_basis="neutral", symbol="T", page="9-15",
            help="At the ambient 25.2 °C the factor is 1."),
        num("theta", "Activation energy constant", "K", [
            positive("the constant is more than zero"),
            warn(min=1200, max=6000, why="θ lies between 1200 K and 6000 K", page="9-15")],
            default=1200, default_basis="handbook", symbol="θ", page="9-15",
            help="The handbook: 1200 K for most situations (Eq. 9-23)."),
    ]


def _factors() -> list[dict]:
    return [
        factor("C_H", "Particle hardness", "9-14", expr="C_H", equation="9-19", source="Table 9-1",
               words="particles harder than the piston"),
        factor("C_S", "Filtration", "9-14", expr="filter_micron / 10", equation="9-19",
               words="a coarser filter"),
        factor("C_N", "Particle size and number", "9-14", expr="C_N", equation="9-19",
               words="more and larger particles"),
        factor("C_T", "Temperature", "9-15", expr=f"exp(theta / {T_A_K} * (1 - {T_A_K} / (T_O + 273.15)))",
               equation="9-22", words="a hotter actuator"),
    ]


_GAMMA = derived("gamma", "Wear factor", "0.20 if wear == 'adhesive' else 0.54", "", "γ", "9-6")
_ELASTIC = derived("k_E", "Elastic term (1−η1²)/E1 + (1−η2²)/E2", "(1 - eta1 ** 2) / E1 + (1 - eta2 ** 2) / E2",
                   "1/psi", page="9-6")
_CLEARANCE = derived("clearance", "Diametral clearance D1 − D2", "D1 - D2", "in", page="9-6", limits=[
    refuse(min=0, exclusive=True, why="the cylinder bore D1 must be larger than the piston D2", page="9-6")])
_BASE = base("λ_AC,B", "Base failure rate (10⁶ ÷ cycles in the constant wear phase)", "9-11", expr="1e6 / N_O",
             equation="9-14")
_WORDS_TAIL = ("That is scaled by how hard the particles are against the piston, the filter's rating, how many and "
               "how large the particles are, and its temperature.")

RECORDS = [
    record(
        "actuator-side-load", "Actuator, piston and cylinder (side load)", "actuator", 9,
        "9.3 Failure rate model for actuator", "9-1", "9-5",
        "λ_AC = λ_AC,B · C_CP · C_T, with λ_AC,B = 10⁶ / N_O, "
        "N_O = k1 · [γ F_Y / ((W_S/L)·(D1−D2)/(D1·D2) / ((1−η1²)/E1 + (1−η2²)/E2))^½]⁹ and C_CP = C_H · C_S · C_N",
        "A piston actuator wears out its piston and cylinder. Its failure rate per million cycles starts at one over "
        "the cycles it takes to wear through the constant-wear phase, which falls steeply (to the 9th power) as the "
        "contact stress from the side load rises against the softer material's yield strength. " + _WORDS_TAIL,
        inputs=[
            num("W_S", "Side load on the actuator", "lbf", [positive("the side load is more than zero")], symbol="W_S",
                page="9-6"),
            num("L", "Total contact length between piston and cylinder", "in", [positive("a length is more than zero")],
                symbol="L", page="9-6"),
            *_geometry(), *_conditions(),
        ],
        derived=[
            _CLEARANCE, _GAMMA, _ELASTIC,
            derived("stress", "Contact stress term (Eq. 9-3 without its 0.8)",
                    "sqrt(W_S / L * (D1 - D2) / (D1 * D2) / k_E)", "psi", page="9-7", equation="9-4"),
            derived("S_C", "Compressive stress between piston and cylinder", "0.8 * stress", "psi", "S_C", "9-6",
                    "9-3"),
            derived("N_O", "Cycles in the constant wear phase", "15.4e3 * (gamma * F_Y / stress) ** 9", "cycles",
                    "N_O", "9-7", "9-4"),
        ],
        modes=[mode("actuator", "Actuator (piston and cylinder wear)", _BASE, _factors(), symbol="λ_AC")],
        rate_unit="per_million_cycles",
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "actuator-axial-load", "Actuator, piston and cylinder (axial load)", "actuator", 9,
        "9.3 Failure rate model for actuator", "9-1", "9-5",
        "λ_AC = λ_AC,B · C_CP · C_T, with λ_AC,B = 10⁶ / N_O, "
        "N_O = k2 · [γ F_Y / (W_A·((D1−D2)/(D1·D2))² / ((1−η1²)/E1 + (1−η2²)/E2)²)^⅓]⁹ and C_CP = C_H · C_S · C_N",
        "A piston actuator wears out its piston and cylinder. Its failure rate per million cycles starts at one over "
        "the cycles it takes to wear through the constant-wear phase, which falls steeply (to the 9th power) as the "
        "contact stress from the axial load rises against the softer material's yield strength. " + _WORDS_TAIL,
        inputs=[
            num("W_A", "Axial load on the actuator", "lbf", [positive("the axial load is more than zero")], symbol="W_A",
                page="9-7"),
            *_geometry(), *_conditions(),
        ],
        derived=[
            _CLEARANCE, _GAMMA, _ELASTIC,
            derived("stress", "Contact stress term (Eq. 9-5 without its 0.9)",
                    "(W_A * ((D1 - D2) / (D1 * D2)) ** 2 / k_E ** 2) ** (1 / 3)", "psi", page="9-7", equation="9-6"),
            derived("S_C", "Compressive stress between piston and cylinder", "0.9 * stress", "psi", "S_C", "9-7",
                    "9-5"),
            derived("N_O", "Cycles in the constant wear phase", "17.7e3 * (gamma * F_Y / stress) ** 9", "cycles",
                    "N_O", "9-8", "9-6"),
        ],
        modes=[mode("actuator", "Actuator (piston and cylinder wear)", _BASE, _factors(), symbol="λ_AC")],
        rate_unit="per_million_cycles",
        failure_modes=_FAILURE_MODES,
    ),
]
