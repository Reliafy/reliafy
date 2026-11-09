"""Chapter 11, Fluid filters (Revision B): the filter assembly, Eq. 11-1.

Checked against the rendered pages 11-8 to 11-12:
- Eq. 11-1 (p. 11-8): λ_F = λ_F,B · C_DP · C_V · C_CS · C_CF.
- λ_F,B (Eq. 11-2, p. 11-9): 2.53 failures per million hours, or 10⁶ / θ from a
  maker's life expectancy θ in hours (the page writes λ = 1/θ; the 10⁶ gives the
  stated unit, as for bearings in Chapter 7).
- C_DP (Eq. 11-3, p. 11-10): 1.25 · P_O / P_R. The handbook gives no range; the
  factor is 1 at P_O = 0.8 P_R.
- C_V (p. 11-10): 1.25 for aircraft and mobile systems, 1.00 otherwise.
- C_CS (Eq. 11-4, p. 11-10): (ν_cold start / ν_normal)^x, x from Table 11-3
  (p. 11-12). Ambiguity: the page gives the viscosities in lb-min/in² while
  Table 11-3 is in centistokes; only their ratio enters, so the model takes the
  ratio (any one unit for both). Table 11-3's viscosities are not used to look
  the ratio up (the user reads them from the table or the fluid's data sheet);
  only its exponent x is, by fluid. The text (p. 11-11) says x runs "from 0.20
  for light viscous fluids such as kerosene to 1.1"; the table agrees.
- C_CF (Table 11-2, p. 11-11): by pore size and surge frequency (0 to 0.1 Hz,
  0.1 to 0.5 Hz). The table stops at 0.5 Hz; faster surges aren't covered.
- No worked example in the chapter.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, factor, mode, num, positive, record, table, warn,
)

_FAILURE_MODES = [
    "Channelling: pores enlarge and unfiltered fluid passes (high differential pressure, cyclic flow)",
    "Fatigue cracks in the media at pleat roots (cyclic flow)",
    "Media migration: fibres released downstream (vibration, cyclic flow, cold starts)",
    "Disintegration of the element (embrittlement, cold starts, very high differential pressure)",
    "Plugging: rising differential pressure (moisture, saturated oil, oxidation products, coolant, wear debris)",
]

#: Table 11-3 (p. 11-12): the exponent x by fluid.
_FLUIDS = [
    ("water", "Water", 0.2),
    ("sea_water", "Sea water", 0.2),
    ("gasoline", "Gasoline (0.68 s.g.)", 0.3),
    ("kerosene", "Kerosene (0.81 s.g.)", 0.2),
    ("light_lube_oil", "Light lubricating oil (0.91 s.g.)", 0.2),
    ("heavy_lube_oil", "Heavy lubricating oil (0.91 s.g.)", 0.7),
    ("sae_10", "SAE 10 oil", 0.5),
    ("sae_20", "SAE 20 oil", 0.6),
    ("sae_30", "SAE 30 oil", 0.7),
    ("sae_40", "SAE 40 oil", 0.8),
    ("sae_50", "SAE 50 oil", 0.9),
    ("sae_60", "SAE 60 oil", 1.0),
    ("sae_70", "SAE 70 oil", 1.1),
]
FLUID_X = {code: x for code, _, x in _FLUIDS}


def _select(name: str, values: dict) -> str:
    """An expression picking ``values[name]`` by a choice's code (a chain of ``a if … else``)."""
    items = list(values.items())
    out = repr(items[-1][1])
    for code, v in reversed(items[:-1]):
        out = f"{v!r} if {name} == {code!r} else {out}"
    return f"({out})"

RECORDS = [
    record(
        "filter-fluid", "Fluid filter assembly", "filter_strainer", 11, "11.4 Filter reliability model", "11-1",
        "11-8",
        "λ_F = λ_F,B · C_DP · C_V · C_CS · C_CF, with C_DP = 1.25 · P_O / P_R and "
        "C_CS = (ν_cold start / ν_normal)^x",
        "A fluid filter's failure rate starts at 2.53 failures per million hours (or one over the maker's life "
        "expectancy) and is scaled by its upstream pressure against its rated pressure, vibration (aircraft and "
        "mobile systems), how much thicker the fluid is at a cold start, and pressure surges through it.",
        inputs=[
            num("lambda_FB", "Base failure rate (2.53, or 10⁶ ÷ the maker's life in hours)", "failures per million hours",
                [positive("a failure rate is more than zero")], default=2.53, default_basis="handbook",
                symbol="λ_F,B", page="11-9",
                help="The handbook's typical value is 2.53; from a maker's multi-pass life θ hours, use 10⁶ ÷ θ."),
            num("P_O", "Operating pressure upstream of the filter", "psi", [positive("a pressure is more than zero")],
                symbol="P_O", page="11-10"),
            num("P_R", "Rated filter pressure", "psi", [positive("a rated pressure is more than zero")],
                symbol="P_R", page="11-10", help="In the same unit as the operating pressure."),
            choice("mobile", "System type (vibration)", [
                ("other", "Fixed (any other system)"), ("aircraft_mobile", "Aircraft or mobile system")],
                default="other", default_basis="neutral", symbol="C_V", page="11-10"),
            num("nu_ratio", "Viscosity at a cold start ÷ viscosity at normal operation", "", [
                positive("a ratio of viscosities is more than zero"),
                warn(min=1, why="a fluid is thicker at a cold start, so the ratio is normally 1 or more", page="11-10"),
            ], default=1.0, default_basis="neutral", symbol="ν_cold start/ν_normal", page="11-10",
                help="Both viscosities in the same unit (Table 11-3 gives centistokes from 0 to 150 °C). "
                     "1 when the system never starts cold."),
            choice("fluid", "Fluid (sets the cold-start exponent x)", [(c, lab) for c, lab, _ in _FLUIDS],
                   default="light_lube_oil", default_basis="typical", symbol="x", page="11-12",
                   help="Only matters when the viscosity ratio isn't 1."),
            choice("pore", "Filter medium", [
                ("uniform", "Uniform pore size (direct interception)"),
                ("non_uniform", "Non-uniform pore size (adsorption, thicker media)")],
                default="uniform", default_basis="neutral", page="11-11"),
            choice("surge", "Flow surge frequency", [
                ("low", "0 to 0.1 Hz (steady or slow surges)"), ("high", "0.1 to 0.5 Hz")],
                default="low", default_basis="neutral", page="11-11",
                help="Table 11-2 covers surges up to 0.5 Hz only."),
        ],
        checks=[check("P_O <= P_R", "The operating pressure is above the filter's rated pressure; the media's strength "
                      "against system pressure needs review", "11-9")],
        modes=[mode("filter", "Filter (leakage, channelling, media migration, plugging)",
                    base("λ_F,B", "Base failure rate", "11-9", expr="lambda_FB", equation="11-2"),
                    [
                        factor("C_DP", "Differential pressure", "11-10", expr="1.25 * P_O / P_R", equation="11-3",
                               words="its pressure against its rating"),
                        factor("C_V", "Vibration", "11-10",
                               table=table("mobile", {"other": 1.0, "aircraft_mobile": 1.25}),
                               words="vibration in aircraft and mobile systems"),
                        factor("C_CS", "Cold start", "11-10",
                               expr=f"nu_ratio ** ({_select('fluid', FLUID_X)})",
                               equation="11-4", source="Table 11-3", words="thicker fluid at a cold start"),
                        factor("C_CF", "Cyclic flow", "11-11", table=table(["pore", "surge"], {
                            "uniform": {"low": 1.0, "high": 1.2},
                            "non_uniform": {"low": 1.2, "high": 1.5},
                        }), source="Table 11-2", words="flow surges through a non-uniform medium"),
                    ], symbol="λ_F")],
        failure_modes=_FAILURE_MODES,
    ),
]
