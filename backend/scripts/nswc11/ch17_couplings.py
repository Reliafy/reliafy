"""Chapter 17, Mechanical couplings (Revision B): from the maker's cycles to
failure (Eq. 17-1), a gear coupling as the sum of its parts (Eq. 17-2), and a
universal joint (Eq. 17-3).

Checked against the rendered pages 17-6 to 17-9:
- Eq. 17-1 (p. 17-6) is printed as "λ_CP = 1 / N, failures/million cycles";
  1/N is per cycle, so the model uses 10⁶ / N for the stated unit (as
  Chapters 7 and 20). Eq. 17-1 has no factor, but Table 17-3 (p. 17-8) is given
  "to modify the expected failure rate of a coupling for the expected operating
  environment", and Eq. 17-2 applies it to the base rate λ_CP,B; the
  endurance record applies it too (reading chosen, said in its notes).
- Eq. 17-2: λ_CP = λ_CP,B · C_SF + λ_GR + λ_SE + λ_H. λ_CP,B isn't defined
  further; the model takes it as an input with no default: the 5.0 failures per
  million cycles of p. 17-7 is the handbook's typical rate for a whole coupling
  (its symbol is λ_CP, the total), so using it as the base would count the parts
  twice.
- λ_H = 0.001 failures per million cycles (Section 17.6, p. 17-9).
- The handbook writes the gear, seal, bearing and fastener rates as failures
  per million cycles, but their own chapters (8, 3, 7, 16) give them per million
  hours. The assemblies are per million hours: the per-cycle terms (λ_CP,B · C_SF
  and λ_H) are multiplied by the coupling's cycles an hour (the handbook's rule,
  pp. 12-10, 12-16) and the per-hour parts added as they are. What one "cycle"
  is the chapter doesn't say; it is whatever the maker's cycles to failure count.
- The seals of a coupling turn with the shaft: the Chapter 3 dynamic seal model.
"""

from backend.scripts.nswc11.common import base, choice, factor, mode, num, positive, record, table, uses

_CYCLES = num("cycles_per_hour", "Coupling cycles per hour", "per hour", [positive("a coupling that never cycles "
              "isn't rated by this model")], symbol="cycles/h", page="17-6",
              help="Turns the per-cycle terms into per hour. The handbook doesn't say what a coupling cycle is: use "
                   "the same cycle the maker's cycles to failure count (a load or start-stop cycle, or a revolution). "
                   "At 1,800 rpm a revolution is 108,000 an hour, and 5 failures per million revolutions would be "
                   "540,000 per million hours.")
_SCALE_NOTE = ("Per million cycles × the coupling's cycles an hour, so it adds to the per-hour parts (pp. 12-10, "
               "12-16).")

_FAILURE_MODES = [
    "Worn flexing element or shaft bushings: excessive misalignment",
    "Ruptured elastomer, sheared hub pins or teeth: torsional shock overload",
    "Fatigue of the flexing element, hub pins or discs: frequent starts and stops, torsional vibration",
    "Shaft bearing failure: lubricant failure, misalignment, temperature extremes",
    "Loose hubs on the shaft: torsional shock, high peak-to-peak torque",
    "Worn gear teeth: lubrication failure, high peak-to-peak torque",
    "Hammering or clacking: misalignment, loose hubs or bolts, lubricant failure",
    "Swollen, distorted or cracked elastomer, hub corrosion: chemical attack, heat",
]

_SERVICE_INPUTS = [
    choice("driven", "Driven machinery", [
        ("uniform", "Uniform"), ("light_shock", "Light shock"), ("medium_shock", "Medium shock"),
        ("heavy_shock", "Heavy shock"),
    ], default="uniform", default_basis="typical", symbol="C_SF", page="17-8"),
    choice("torque", "Torque characteristic", [
        ("normal", "Normal torque"), ("high", "High or non-uniform torque"),
    ], default="normal", default_basis="typical", symbol="C_SF", page="17-8"),
]

_C_SF = factor("C_SF", "Service factor", "17-8", table=table(["driven", "torque"], {
    "uniform": {"normal": 1.1, "high": 1.2},
    "light_shock": {"normal": 1.2, "high": 1.3},
    "medium_shock": {"normal": 1.3, "high": 1.4},
    "heavy_shock": {"normal": 1.4, "high": 1.5},
}), source="Table 17-3", words="shock in the driven machinery and uneven torque")

_HOUSING = mode("housing", "Housing (with hubs)", base("λ_H", "Housing failure rate (per million cycles)", "17-9",
                                                    value=0.001),
                symbol="λ_H", scale="cycles_per_hour", scale_label="cycles an hour", note=_SCALE_NOTE)

_MIXED = ("Its own chapter gives it per million hours, so it adds as it is (Eq. {eq} writes it per million "
          "cycles; the per-cycle terms are the ones converted).")

RECORDS = [
    record(
        "coupling-endurance", "Mechanical coupling (from the maker's cycles to failure)", "coupling", 17,
        "17.3 Failure rate model for mechanical coupling", "17-1", "17-6",
        "λ_CP = λ_CP,B · C_SF, with λ_CP,B = 10⁶ / N",
        "A coupling's failure rate per million cycles starts at one over the cycles it lasts at its working "
        "stress, from the maker's endurance data. That is scaled by a service factor for shock in the driven "
        "machinery and uneven torque.",
        inputs=[
            num("N_cycles", "Cycles to failure at the working stress", "cycles", [positive("a life is more than zero")],
                symbol="N", page="17-6", help="From the maker's stress against cycles curve (Figure 17.3)."),
            *_SERVICE_INPUTS,
        ],
        modes=[mode("coupling", "Coupling (wear, fatigue, overload)",
                    base("λ_CP,B", "Base failure rate (10⁶ ÷ cycles to failure)", "17-6", expr="1e6 / N_cycles",
                         equation="17-1"),
                    [_C_SF], symbol="λ_CP")],
        rate_unit="per_million_cycles",
        failure_modes=_FAILURE_MODES,
        notes="Eq. 17-1 alone has no factor; Table 17-3's service factor is applied as in Eq. 17-2 (p. 17-6, 17-8).",
    ),
    record(
        "coupling-gear", "Gear coupling (sum of its parts)", "coupling", 17,
        "17.3 Failure rate model for mechanical coupling", "17-2", "17-6",
        "λ_CP = λ_CP,B · C_SF + λ_GR + λ_SE + λ_H",
        "A gear coupling's failure rate is its base rate (5 failures per million cycles is typical) scaled by a "
        "service factor for shock and uneven torque, plus its gears, its seals and its housing.",
        inputs=[
            num("lambda_CP_B", "Base failure rate of the coupling body", "failures per million cycles",
                [positive("a failure rate is more than zero")], symbol="λ_CP,B", page="17-6",
                help="10⁶ ÷ the maker's cycles to failure (Eq. 17-1). The handbook's \"typical\" 5.0 per million "
                     "cycles (p. 17-7) is a whole coupling's rate, parts included: using it here counts the gears "
                     "and seals twice."),
            _CYCLES,
            *_SERVICE_INPUTS,
            num("n_GR", "Number of gear meshes", "", [positive("a gear coupling has gears")], symbol="n_GR",
                page="17-6", help="All alike: the gear model's rate × this number."),
            num("n_SE", "Number of seals", "", [positive("a gear coupling has seals")], symbol="n_SE", page="17-7"),
        ],
        modes=[
            mode("coupling", "Coupling body",
                 base("λ_CP,B", "Base failure rate (per million cycles)", "17-6", expr="lambda_CP_B"), [_C_SF],
                 symbol="λ_CP,B·C_SF", scale="cycles_per_hour", scale_label="cycles an hour", note=_SCALE_NOTE),
            uses("gears", "Gears", "gear", symbol="λ_GR", count="n_GR", note=_MIXED.format(eq="17-2")),
            uses("seals", "Seals", "seal-dynamic", symbol="λ_SE", count="n_SE", note=_MIXED.format(eq="17-2")),
            _HOUSING,
        ],
        failure_modes=_FAILURE_MODES,
        notes="Per million hours: the coupling body and housing (per million cycles) × the cycles an hour, plus "
              "the gear and seal models (per million hours) as they are (pp. 12-10, 12-16; Eq. 17-2 labels every "
              "term per million cycles).",
    ),
    record(
        "coupling-universal-joint", "Universal joint", "coupling", 17, "17.5 Failure rate model for universal joint",
        "17-3", "17-9", "λ_UJ = λ_BE + λ_SE + λ_H + λ_F",
        "A universal joint's failure rate is the sum of its parts: its bearings, its seals, its housing (a small "
        "fixed rate) and its fasteners, each from its own model.",
        inputs=[
            _CYCLES,
            num("n_BE", "Number of bearings", "", [positive("a universal joint has bearings")], symbol="n_BE",
                page="17-9", help="All alike: the bearing model's rate × this number."),
            num("n_SE", "Number of seals", "", [positive("a universal joint has seals")], symbol="n_SE", page="17-9"),
            num("n_F", "Number of fasteners", "", [positive("a universal joint has fasteners")], symbol="n_F",
                page="17-9"),
        ],
        modes=[
            uses("bearings", "Bearings", "bearing-rolling-load-rating", symbol="λ_BE", count="n_BE",
                 note=_MIXED.format(eq="17-3")),
            uses("seals", "Seals", "seal-dynamic", symbol="λ_SE", count="n_SE", note=_MIXED.format(eq="17-3")),
            _HOUSING,
            uses("fasteners", "Fasteners", "fastener", symbol="λ_F", count="n_F", note=_MIXED.format(eq="17-3")),
        ],
        failure_modes=_FAILURE_MODES,
        notes="Per million hours: the bearing, seal and fastener models (per million hours) as they are, plus the "
              "housing (per million cycles) × the cycles an hour (pp. 12-10, 12-16; Eq. 17-3 labels every term per "
              "million cycles).",
    ),
]
