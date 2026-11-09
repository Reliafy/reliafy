"""Chapter 15, Accumulators (Revision B): the accumulator as the sum of its parts,
Eq. 15-1 (p. 15-5), and its cylinder wall, Eq. 15-10 (thin wall, p. 15-10) and
Eq. 15-14 (thick wall, p. 15-11), each stress's rate from the stress-strength
interference of Section 15.6 (Eq. 15-15 to 15-17, pp. 15-11 to 15-13).

Checked against the rendered pages 15-5 to 15-13:
- Eq. 15-1: λ_A = λ_SE + λ_SP + λ_PC + λ_VA + λ_CW, failures per million hours.
- Thin wall (t/r_i < 0.1): σ_c = P r_i / (t η_c) (15-6); σ_l = P r_i / (2 t η_l)
  (15-7); joint efficiencies from Table 15-2 (p. 15-9).
- Thick wall (t/r_i > 0.1): σ_l = P r_i² / (r_o² − r_i²) (15-11);
  σ_c = P r_i² (r_o² + r²) / (r² (r_o² − r_i²)) (15-12);
  σ_r = P r_i² (r_o² − r²) / (r² (r_o² − r_i²)) (15-13), r the average radius.
- λ_CW = λ_CW,B + λ_c + λ_l (15-10), + λ_r for a thick wall (15-14);
  λ_CW,B = 0.001 failures per million hours.
- z = (μ_S − μ_s) / √(σ_S² + σ_s²) (15-17), μ_S the mean yield strength F_y;
  "converted to reliability and failure rate using cumulative standard normal
  distribution tables and assuming R = e^(−λt)" (p. 15-13).

Readings chosen where the handbook is silent or loose (each in the report):
- Time t in R = e^(−λt): the handbook names no period. It's an input here (the
  period the stress-strength reliability applies over), so
  λ_x = −ln(Φ(z_x)) / t × 10⁶ per million hours.
- The stress's standard deviation σ_s: the handbook gives none. Every wall
  stress is proportional to the pressure for a fixed geometry, so here each
  stress's coefficient of variation is the pressure's (σ_s = σ_x · s_P / P).
- Φ: the expression language has no normal distribution, so the upper tail is
  computed with the Chebyshev-fitted erfc of Press et al. (Numerical Recipes,
  "erfcc"), fractional error under 1.2×10⁻⁷ everywhere: good in the far tail,
  where an R near 1 matters.
- Eq. 15-13 is printed positive; the radial stress is compressive. Its size is
  what enters z, so the sign doesn't change λ_r.
- The thick-wall equations carry no joint efficiency (the thin-wall ones do):
  the joints are not used for a thick wall, and the model warns if any were set.
- t/r_i exactly 0.1 is between the two sections' "< 0.1" and "> 0.1": treated as
  thick.
- p. 15-10 calls λ_c the rate "considering compressive stress"; Eq. 15-14's
  list (p. 15-11) calls it circumferential, as the equations use it.
- The hemispherical ends' stress (Eq. 15-9) isn't in Eq. 15-10 or 15-14: left
  out (the handbook notes the ends are twice as strong for the same thickness).
- Eq. 15-1 has a spring term; a gas-charged piston accumulator has no spring
  (p. 15-2), so it has its own record without λ_SP. Bladder and diaphragm
  types have no piston and no model in the handbook: not covered.
- λ_PC: Chapter 9 has two actuator records (side load, axial load); the
  accumulator uses the side-load one, since p. 15-5 names the piston's side
  load (from tilting) as what drives its wear.
- Units: Eq. 15-1 adds Chapter 9's actuator rate (per million cycles) and
  Chapter 6's valve assembly rate (per million operations) to per-hour rates,
  as written (said in each mode's note).
"""

from backend.scripts.nswc11.common import (
    base, check, choice, derived, mode, num, positive, record, refuse, uses,
)

_FAILURE_MODES = [
    "Seal leakage: embrittlement, wear, distortion, incompatible fluid",
    "Worn cylinder bore or piston: contaminants, reaction with the fluid",
    "Loss of spring tension: corrosion, fracture, misalignment",
    "Piston stiction: surface wear, corrosion",
    "Loss of pressure: ruptured gas bag, external leakage",
    "Charge gas leaking into the fluid: leakage past the piston or bag, sudden discharge",
    "Inoperative accumulator: jammed output valve",
]

# Table 15-2 (p. 15-9): approximate joint efficiencies, the same for η_c and η_l.
_JOINTS = [
    ("none", "No joint (seamless): η = 1 by its definition (p. 15-8)", 1.0),
    ("riveted_lap_single", "Riveted lap joint, single row", 0.55),
    ("riveted_lap_double", "Riveted lap joint, double row", 0.65),
    ("riveted_lap_triple", "Riveted lap joint, triple row", 0.75),
    ("riveted_butt_single", "Riveted butt joint, single row", 0.65),
    ("riveted_butt_double", "Riveted butt joint, double row", 0.75),
    ("riveted_butt_triple", "Riveted butt joint, triple row", 0.85),
    ("riveted_butt_quadruple", "Riveted butt joint, quadruple row", 0.90),
    ("welded_butt_single", "Welded butt joint, single", 0.75),
    ("welded_butt_double", "Welded butt joint, double", 0.85),
]


def _eta(name: str) -> str:
    expr = "1.0"
    for code, _label, value in reversed(_JOINTS):
        expr = f"{value} if {name} == '{code}' else ({expr})"
    return expr


def _joint(name: str, label: str, symbol: str) -> dict:
    return choice(name, label, [(c, lab) for c, lab, _v in _JOINTS], default="none", default_basis="neutral",
                  symbol=symbol, page="15-9",
                  help="Table 15-2; used for a thin wall only (the thick-wall equations have no joint efficiency).")


def _tail(x: str) -> list[dict]:
    """Derived values for stress x (c, l or r): its standard deviation, z (Eq. 15-17), the upper tail
    Q = 1 − Φ(z) through the Numerical Recipes erfcc fit, and the rate per million hours."""
    poly = ("1.00002368 + k * (0.37409196 + k * (0.09678418 + k * (-0.18628806 + k * (0.27886807 + "
            "k * (-1.13520398 + k * (1.48851587 + k * (-0.82215223 + k * 0.17087277)))))))")
    u, k, e = f"u_{x}", f"k_{x}", f"e_{x}"
    return [
        derived(f"sd_{x}", f"Standard deviation of σ_{x}", f"sigma_{x} * s_P / P", "psi", f"σ_s,{x}", "15-13"),
        derived(f"z_{x}", f"Safety margin z for σ_{x}", f"(F_y - sigma_{x}) / sqrt(s_Fy ** 2 + sd_{x} ** 2)", "",
                f"z_{x}", "15-13", "15-17"),
        derived(u, f"z_{x} ÷ √2", f"z_{x} / sqrt(2)", ""),
        derived(k, f"erfc fit term for z_{x}", f"1 / (1 + 0.5 * abs({u}))", ""),
        derived(f"ln{e}", f"ln erfc(|z_{x}| ÷ √2)",
                f"ln({k}) - {u} * {u} - 1.26551223 + {k} * ({poly.replace('k', k)})", ""),
        derived(e, f"erfc(|z_{x}| ÷ √2)", f"exp(ln{e})", ""),
        derived(f"Q_{x}", f"Chance σ_{x} exceeds the strength (1 − R)",
                f"0.5 * ({e} if {u} >= 0 else 2 - {e})", "", f"1 − R_{x}", "15-13", "15-15"),
        # −ln R: for z ≥ 0 from Q (≈ Q in the far tail, where 1 − Q rounds to 1); for z < 0, R is itself the
        # small tail 0.5·erfc(|z|/√2), so −ln R comes from its logarithm and never underflows.
        derived(f"lam_{x}", f"Rate from σ_{x}",
                f"1e6 * ((Q_{x} if Q_{x} < 1e-9 else -ln(1 - Q_{x})) if {u} >= 0 else -(ln(0.5) + ln{e})) / t_op",
                "failures per million hours", f"λ_{x}", "15-13"),
    ]


_WALL = record(
    "accumulator-cylinder-wall", "Accumulator cylinder wall", "vessel_tank", 15,
    "15.4 Thin wall cylinders; 15.5 Thick wall cylinders", "15-10, 15-14", "15-10",
    "λ_CW = λ_CW,B + λ_c + λ_l (+ λ_r for a thick wall), each λ_x = −ln Φ(z_x) / t with "
    "z_x = (F_y − σ_x) / √(σ_S² + σ_s²)",
    "A pressure cylinder's wall fails when a stress from the fluid pressure beats the metal's yield strength. Its "
    "failure rate is a small base rate plus a rate for each stress (around the wall, along it, and through a thick "
    "wall), from how far the mean stress sits below the mean strength given how much each varies, spread over "
    "the period you give.",
    inputs=[
        num("P", "Internal pressure (mean)", "psi", [positive("the cylinder must hold a pressure")], symbol="P",
            page="15-7"),
        num("s_P", "Standard deviation of the internal pressure", "psi",
            [refuse(min=0, why="a standard deviation can't be negative")], symbol="σ_P", page="15-13",
            help="The handbook gives no stress spread; here every stress varies as the pressure does."),
        num("r_i", "Internal radius", "in", [positive("a radius is more than zero")], symbol="r_i", page="15-7"),
        num("t", "Wall thickness", "in", [positive("a wall is more than zero thick")], symbol="t", page="15-7"),
        _joint("joint_c", "Joint efficiency for the circumferential stress (longitudinal seam)", "η_c"),
        _joint("joint_l", "Joint efficiency for the longitudinal stress (circumferential seam)", "η_l"),
        num("F_y", "Material yield strength (mean)", "psi", [positive("a strength is more than zero")],
            symbol="μ_S (F_y)", page="15-12"),
        num("s_Fy", "Standard deviation of the yield strength", "psi",
            [positive("a strength always varies a little: give its standard deviation")], symbol="σ_S",
            page="15-13", help="The handbook: yield strengths of steels are normally distributed (p. 15-12)."),
        num("t_op", "Period the reliability applies over", "hours", [positive("a period is more than zero")],
            symbol="t", page="15-13",
            help="R = e^(−λt) (p. 15-13): the handbook names no period; give the time the pressure loading's "
                 "reliability covers, e.g. the design life."),
    ],
    derived=[
        derived("thick", "Thick wall (1) or thin (0)", "1 if t / r_i >= 0.1 else 0", "", page="15-6"),
        derived("r_o", "External radius", "r_i + t", "in", "r_o", "15-10"),
        derived("r", "Average radius", "(r_i + r_o) / 2", "in", "r", "15-11"),
        derived("eta_c", "Circumferential joint efficiency", _eta("joint_c"), "", "η_c", "15-9"),
        derived("eta_l", "Longitudinal joint efficiency", _eta("joint_l"), "", "η_l", "15-9"),
        derived("sigma_c", "Circumferential (hoop) stress",
                "P * r_i ** 2 * (r_o ** 2 + r ** 2) / (r ** 2 * (r_o ** 2 - r_i ** 2)) if thick == 1 "
                "else P * r_i / (t * eta_c)", "psi", "σ_c", "15-8", "15-6, 15-12"),
        derived("sigma_l", "Longitudinal stress",
                "P * r_i ** 2 / (r_o ** 2 - r_i ** 2) if thick == 1 else P * r_i / (2 * t * eta_l)", "psi", "σ_l",
                "15-8", "15-7, 15-11"),
        derived("sigma_r", "Radial stress (size; 0 for a thin wall)",
                "P * r_i ** 2 * (r_o ** 2 - r ** 2) / (r ** 2 * (r_o ** 2 - r_i ** 2)) if thick == 1 else 0",
                "psi", "σ_r", "15-11", "15-13"),
        *_tail("c"), *_tail("l"), *_tail("r"),
    ],
    checks=[
        check("z_c > 0 and z_l > 0", "The mean wall stress is above the mean yield strength: the wall is expected "
              "to yield", "15-12"),
        check("thick == 0 or (joint_c == 'none' and joint_l == 'none')",
              "The wall is thick (t/r_i of 0.1 or more): the thick-wall equations have no joint efficiency, so "
              "the joints given aren't used", "15-10"),
    ],
    modes=[
        mode("base", "Cylinder wall base", base("λ_CW,B", "Cylinder base failure rate", "15-10", value=0.001),
             symbol="λ_CW,B"),
        mode("circumferential", "Circumferential (hoop) stress",
             base("λ_c", "Rate from the circumferential stress", "15-13", expr="lam_c", equation="15-17"),
             symbol="λ_c"),
        mode("longitudinal", "Longitudinal stress",
             base("λ_l", "Rate from the longitudinal stress", "15-13", expr="lam_l", equation="15-17"),
             symbol="λ_l"),
        mode("radial", "Radial stress (thick wall only)",
             base("λ_r", "Rate from the radial stress (0 for a thin wall)", "15-13",
                  expr="lam_r if thick == 1 else 0", equation="15-17"), symbol="λ_r"),
    ],
    notes=("Thin wall (t/r_i under 0.1) by Eq. 15-6, 15-7 and 15-10; thick wall by Eq. 15-11 to 15-14. The period "
           "t and the stress spread (here the pressure's) are inputs the handbook leaves open; hemispherical ends "
           "(Eq. 15-9) aren't in its sum."),
    failure_modes=["Wall yield or rupture: a pressure stress beyond the material's strength"],
)

_UNIT_NOTE_PC = ("Chapter 9's side-load actuator model (p. 15-5: tilting the accumulator changes the piston's side "
                 "load) is per million cycles: × the accumulator's charge and discharge cycles an hour, so it adds "
                 "to Eq. 15-1's per-hour rates (the handbook's rule, pp. 12-10, 12-16).")
_UNIT_NOTE_VA = ("Chapter 6's valve assembly, per million hours (its poppet converted by its operations an hour, "
                 "one operation per accumulator cycle).")


def _parts(spring: bool) -> list[dict]:
    out = [uses("seals", "Piston seals (each)", "seal-dynamic", symbol="λ_SE", count="n_SE",
                note="Chapter 3's dynamic seal model, one per piston seal.")]
    if spring:
        out.append(uses("springs", "Springs (each)", "spring-compression", symbol="λ_SP", count="n_SP",
                        bind={"cycle_rate": "cycles_per_hour / 60"},
                        note="Chapter 4's compression spring model (p. 15-5: the static spring equations suit "
                             "most accumulators), cycling once per accumulator cycle."))
    out += [
        uses("piston_cylinder", "Piston and cylinder interface", "actuator-side-load", symbol="λ_PC",
             scale="cycles_per_hour", scale_label="cycles an hour", note=_UNIT_NOTE_PC),
        uses("valve", "Valves (each)", "valve-assembly", symbol="λ_VA", count="n_VA",
             bind={"ops_per_hour": "cycles_per_hour"}, note=_UNIT_NOTE_VA),
        uses("wall", "Cylinder wall", "accumulator-cylinder-wall", symbol="λ_CW"),
    ]
    return out


def _counts(spring: bool) -> list[dict]:
    out = [num("cycles_per_hour", "Charge and discharge cycles per hour", "per hour",
               [positive("an accumulator that never cycles isn't rated by this model")], symbol="cycles/h",
               page="15-5", help="Converts the piston's wear (per million cycles) to per hour, and sets the valves' "
                                 "operations and the springs' cycle rate (one each per cycle)."),
           num("n_SE", "Number of piston seals", "", [refuse(min=0, why="a count can't be negative")],
               symbol="n", page="15-5"),
           num("n_VA", "Number of valves", "", [refuse(min=0, why="a count can't be negative")], default=1,
               default_basis="handbook", symbol="n", page="15-5",
               help="Eq. 15-1 has one λ_VA; p. 15-1 describes an inlet (one-way) and an outlet valve: enter 2 for "
                    "both. For a check valve with no solenoid, set the valve's solenoids to 0.")]
    if spring:
        out.append(num("n_SP", "Number of springs", "", [refuse(min=0, why="a count can't be negative")],
                       symbol="n", page="15-2", help="A spring-loaded accumulator has one spring or several."))
    return out


RECORDS = [
    _WALL,
    record(
        "accumulator-spring-loaded", "Accumulator, spring-loaded piston", "vessel_tank", 15,
        "15.3 Failure rate model", "15-1", "15-5", "λ_A = λ_SE + λ_SP + λ_PC + λ_VA + λ_CW",
        "A spring-loaded accumulator's failure rate is the sum of its parts: its piston seals, its springs, the "
        "wear between piston and cylinder, its control valve and its pressure-holding cylinder wall.",
        inputs=_counts(True), modes=_parts(True),
        notes=("Eq. 15-1 in full. Seals from Chapter 3 (dynamic), springs from Chapter 4, piston and cylinder from "
               "Chapter 9, the valve from Chapter 6 and the wall from Sections 15.4 to 15.6."),
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "accumulator-gas-charged", "Accumulator, gas-charged piston", "vessel_tank", 15,
        "15.3 Failure rate model", "15-1", "15-5", "λ_A = λ_SE + λ_PC + λ_VA + λ_CW (Eq. 15-1 with no spring)",
        "A gas-charged piston accumulator's failure rate is the sum of its parts: its piston seals, the wear "
        "between piston and cylinder, its control valve and its pressure-holding cylinder wall. It has no spring.",
        inputs=_counts(False), modes=_parts(False),
        notes=("Eq. 15-1 without λ_SP: a gas-loaded accumulator holds its pressure with gas, not a spring "
               "(p. 15-2). For a piston type; bladder and diaphragm types have no model in the handbook."),
        failure_modes=[f for f in _FAILURE_MODES if not f.startswith("Loss of spring")],
    ),
]
