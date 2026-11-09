"""Chapter 16, Threaded fasteners (Revision B): Eq. 16-6 (p. 16-13).

Checked against the rendered pages 16-13 to 16-21:
- Eq. 16-6: λ_F = λ_F,B · C_SZ · C_L · C_T · C_I · C_K, failures per million
  hours (p. 16-14 prints λ_F,B's unit as "failures/failures/million hours", a
  slip for failures per million hours, as Table 16-5's heading says).
- Eq. 16-7: C_SZ = (0.370 d / 0.3)^−0.1133 for bending or torsion, d the major
  diameter, 2 in or less; 1.0 for axial loading (Eq. 16-8); and 1.0 whenever
  Table 16-5's standard grades give the base rate (p. 16-14).
- Eq. 16-9: C_T = (460 + T_O) / 620 above 160 °F (steel), else 1.0 (p. 16-15).
- Tables 16-5 (λ_F,B), 16-6 (C_L), 16-7 (C_I) and 16-8 (C_K) on pp. 16-19 to
  16-21.

Two records: from Table 16-5's standard grades (C_SZ = 1, as p. 16-14 says), and
from a base rate the user has from fastener test data (16.3.5), where Eq. 16-7
adjusts for size under bending or torsion.

Readings chosen (each in the report):
- Table 16-6 gives axial loading 1.09 (ultimate strength up to 220 kpsi) or
  1.00 (over 220 kpsi), though p. 16-15 says Table 16-5 already assumes axial
  loading. The model applies Table 16-6 as printed.
- Table 16-8 gives C_K only by SAE grade band (0-2, 4-8). The user picks the
  band; for an SAE grade it must match the grade (a refusing check). For ISO and
  ASTM grades the band is the user's call (help text suggests the SAE grade of
  similar proof load from Table 16-5).
- C_T is stated "for steel"; the record says so and doesn't model other metals.
- Temperature limits: the chapter's material data (Tables 16-2 and 16-4) cover
  −325 to 800 °F; outside that the model warns.
- Section 16.3's preload and stress-relaxation equations (16-1 to 16-5) are
  design checks, not part of Eq. 16-6: left out.
"""

from backend.scripts.nswc11.common import (
    base, check, choice, factor, mode, num, positive, record, refuse, table, warn,
)

_FAILURE_MODES = [
    "Male thread fracture: poor material, corrosion, fatigue",
    "Broken shank: poor material, over-torquing",
    "Self loosening: under-torquing, vibration",
    "Fractured bolt head or cracked nut: excessive preload",
    "Thread stripping: production variation, material strength variation, nut displacement, excessive tension",
    "Joint loosening over time: load beyond preload, too little preload, poor washers",
    "Reduced fatigue life: bolt too tight or too loose",
    "Galling during assembly or removal: too fine a thread, wrong material pair",
    "Surface bearing deformation or crushed gasket: bolt too tight",
]

# Table 16-5 (p. 16-19): grade / class and diameter range → base failure rate, failures per million hours.
_GRADES = [
    ("sae_1", "SAE 1, 1/4 to 1 1/2 in (proof 33 kpsi)", 0.260, "low"),
    ("sae_2_small", "SAE 2, 1/4 to 3/4 in (proof 55 kpsi)", 0.156, "low"),
    ("sae_2_large", "SAE 2, 3/4 to 1 1/2 in (proof 33 kpsi)", 0.260, "low"),
    ("sae_4", "SAE 4, 1/4 to 1 1/2 in (proof 65 kpsi)", 0.132, "high"),
    ("sae_5_small", "SAE 5, 1/4 to 1 in (proof 85 kpsi)", 0.101, "high"),
    ("sae_5_mid", "SAE 5, 1 to 1 1/2 in (proof 74 kpsi)", 0.116, "high"),
    ("sae_5_large", "SAE 5, 1 1/2 to 3 in (proof 55 kpsi)", 0.156, "high"),
    ("sae_7", "SAE 7, 1/4 to 1 1/2 in (proof 105 kpsi)", 0.082, "high"),
    ("sae_8", "SAE 8, 1/4 to 1 1/2 in (proof 120 kpsi)", 0.072, "high"),
    ("iso_4_6", "ISO 4.6, up to 1 1/2 in (proof 33 kpsi)", 0.260, None),
    ("iso_5_8", "ISO 5.8, up to 1 1/2 in (proof 55 kpsi)", 0.156, None),
    ("iso_8_8", "ISO 8.8, up to 1 1/2 in (proof 85 kpsi)", 0.101, None),
    ("iso_10_9", "ISO 10.9, up to 1 1/2 in (proof 120 kpsi)", 0.072, None),
    ("a325_small", "ASTM A325, 1/2 to 1 in (proof 85 kpsi)", 0.101, None),
    ("a325_large", "ASTM A325, 1 1/8 to 1 1/2 in (proof 74 kpsi)", 0.116, None),
    ("a354_bb_small", "ASTM A354 BB, 1/4 to 2 1/2 in (proof 80 kpsi)", 0.107, None),
    ("a354_bb_large", "ASTM A354 BB, 2 3/4 to 4 in (proof 75 kpsi)", 0.114, None),
    ("a354_bc_small", "ASTM A354 BC, 1/4 to 2 1/2 in (proof 105 kpsi)", 0.082, None),
    ("a354_bc_large", "ASTM A354 BC, 2 3/4 to 4 in (proof 95 kpsi)", 0.090, None),
    ("a354_bd", "ASTM A354 BD, 1/4 to 1 1/2 in (proof 120 kpsi)", 0.072, None),
    ("a490", "ASTM A490, 1/2 to 1 1/2 in (proof 120 kpsi)", 0.072, None),
]

_LOAD = choice("load", "Type of load applied", [
    ("axial_low", "Axial, ultimate tensile strength 220 kpsi or less"),
    ("axial_high", "Axial, ultimate tensile strength over 220 kpsi"),
    ("bending", "Bending"),
    ("torsion_shear", "Torsion and shear"),
], symbol="C_L", page="16-20",
    help="Table 16-6. Table 16-5's base rates assume axial loading (p. 16-15).")

_IMPACT = choice("impact", "Impact category (the machine the joint is on)", [
    ("light", "Light: rotating machinery (motors, turbines, centrifugal pumps)"),
    ("medium", "Medium: rotary and reciprocating machines (compressors, pumps)"),
    ("heavy", "Heavy: presses for tools and dies, shears"),
    ("very_heavy", "Very heavy: hammers, rolling mills, crushers"),
], default="light", default_basis="neutral", symbol="C_I", page="16-20")

_VIBRATION = choice("vibration", "Vibration", [
    ("normal", "Normal vibration"), ("high", "Continuous high vibration"),
], default="normal", default_basis="neutral", symbol="C_I", page="16-20")

_BAND = choice("thread_band", "Bolt strength band for the thread factor", [
    ("low", "SAE grade 0 to 2 (or a similar lower-strength bolt)"),
    ("high", "SAE grade 4 to 8 (or a similar higher-strength bolt)"),
], symbol="C_K", page="16-21",
    help="Table 16-8 gives the thread factor by SAE grade only. For an ISO or ASTM grade, pick the band of the "
         "SAE grade with a similar proof load (Table 16-5).")

_FORM = choice("thread_form", "How the threads were made", [("rolled", "Rolled threads"), ("cut", "Cut threads")],
               symbol="C_K", page="16-21")

_T_O = num("T_O", "Fastener operating temperature", "°F", [
    refuse(min=-459.67, why="below absolute zero"),
    warn(min=-325, max=800, why="the chapter's material data (Tables 16-2 and 16-4) cover −325 to 800 °F",
         page="16-16"),
], default=70, default_basis="neutral", symbol="T_O", page="16-15",
    help="Up to 160 °F the factor is 1. Eq. 16-9 is for steel fasteners.")


def _common_factors() -> list[dict]:
    return [
        factor("C_L", "Type of load", "16-20", table=table("load", {
            "axial_low": 1.09, "axial_high": 1.00, "bending": 1.00, "torsion_shear": 1.72,
        }), source="Table 16-6", words="torsion and shear"),
        factor("C_T", "Temperature (steel)", "16-15", expr="1.0 if T_O <= 160 else (460 + T_O) / 620",
               equation="16-9", words="heat above 160 °F"),
        factor("C_I", "Cyclic shock and impact", "16-20", table=table(["impact", "vibration"], {
            "light": {"normal": 1.00, "high": 1.50},
            "medium": {"normal": 1.25, "high": 1.88},
            "heavy": {"normal": 1.67, "high": 2.50},
            "very_heavy": {"normal": 2.50, "high": 3.75},
        }), source="Table 16-7", words="impact and vibration in the machine"),
        factor("C_K", "Thread stress concentration", "16-21", table=table(["thread_band", "thread_form"], {
            "low": {"rolled": 2.2, "cut": 2.8},
            "high": {"rolled": 3.0, "cut": 3.8},
        }), source="Table 16-8", words="cut rather than rolled threads, higher-strength bolts"),
    ]


def _band_checks() -> list[dict]:
    out = []
    for code, label, _rate, band in _GRADES:
        if band:
            out.append(check(f"thread_band == '{band}'",
                             f"{label.split(',')[0]} is in Table 16-8's SAE grade "
                             f"{'0-2' if band == 'low' else '4-8'} band: pick that band for the thread factor",
                             "16-21", severity="refuse", when=f"grade == '{code}'"))
    return out


_WORDS_TABLE = ("A threaded fastener's failure rate starts at a base rate for its grade and size (lower for "
                "stronger grades) and is scaled by the type of load it carries, heat above 160 °F, impact and "
                "vibration in the machine, and the stress concentration of its threads.")
_WORDS_TEST = ("When test data for the fastener gives its base failure rate, that rate is scaled for a size "
               "different from the test specimen's (under bending or torsion), the type of load it carries, heat "
               "above 160 °F, impact and vibration in the machine, and the stress concentration of its threads.")
_FORMULA = "λ_F = λ_F,B · C_SZ · C_L · C_T · C_I · C_K"

RECORDS = [
    record(
        "fastener", "Threaded fastener (standard grade)", "fastener", 16, "16.4 Failure rate model", "16-6",
        "16-13", _FORMULA + " (C_SZ = 1 for Table 16-5's grades)", _WORDS_TABLE,
        inputs=[
            choice("grade", "Grade or class, and diameter", [(c, lab) for c, lab, _r, _b in _GRADES],
                   symbol="λ_F,B", page="16-19"),
            _LOAD, _T_O, _IMPACT, _VIBRATION, _BAND, _FORM,
        ],
        checks=_band_checks(),
        modes=[mode("fastener", "Fastener (fracture, loosening, stripping, fatigue)",
                    base("λ_F,B", "Base failure rate for the grade and size", "16-19",
                         table=table("grade", {c: r for c, _lab, r, _b in _GRADES}), source="Table 16-5"),
                    _common_factors(), symbol="λ_F")],
        notes=("Base rate from Table 16-5, so the size factor is 1 (p. 16-14). Table 16-6's axial factor is "
               "applied as printed, though p. 16-15 says Table 16-5 assumes axial loading."),
        failure_modes=_FAILURE_MODES,
    ),
    record(
        "fastener-test-data", "Threaded fastener (base rate from test data)", "fastener", 16,
        "16.4 Failure rate model", "16-6", "16-13", _FORMULA + ", C_SZ = (0.370 d / 0.3)^−0.1133 under bending "
        "or torsion", _WORDS_TEST,
        inputs=[
            num("lambda_FB", "Base failure rate from the fastener's test data", "failures per million hours",
                [positive("a failure rate from test data is more than zero")], symbol="λ_F,B", page="16-13",
                help="From maker's fatigue testing of this fastener (Section 16.3.5)."),
            num("d", "Major diameter of the fastener", "in", [
                positive("a diameter is more than zero"),
                warn(max=2, why="Eq. 16-7 is for a major diameter of 2 in or less", page="16-14"),
            ], symbol="d", page="16-14"),
            _LOAD, _T_O, _IMPACT, _VIBRATION, _BAND, _FORM,
        ],
        modes=[mode("fastener", "Fastener (fracture, loosening, stripping, fatigue)",
                    base("λ_F,B", "Base failure rate from test data", "16-13", expr="lambda_FB"),
                    [factor("C_SZ", "Size (bending or torsion)", "16-14", expr="(0.370 * d / 0.3) ** -0.1133",
                            equation="16-7", when="load == 'bending' or load == 'torsion_shear'",
                            words="a size different from the test specimen"),
                     *_common_factors()], symbol="λ_F")],
        notes="C_SZ is 1 for axial loading (Eq. 16-8) and follows Eq. 16-7 under bending or torsion, as printed. "
              "As printed it lowers the rate for a bigger fastener (0.88 at 2 in, 1.14 at 0.25 in), against p. "
              "16-14's text (\"the probability of failure is greater in larger parts\"): it is Shigley's strength "
              "size factor, which the chapter's other factors take as a reciprocal. Kept as printed; the effect is "
              "about ±14 % across the 0.25 to 2 in range.",
        failure_modes=_FAILURE_MODES,
    ),
]
