"""NSWC-11 Chapter 13, compressors: the models against the handbook's
equations, tables and figures (pages cited). The chapter has no worked
example. The assembly is tested with stand-in parts (a constant rate each)."""

import math

import pytest

from backend.library import covariate
from backend.scripts.build_nswc11 import _record
from backend.scripts.nswc11 import ch13_compressors as ch13

RECORDS = {f"nswc-11:{r['slug']}": _record(r) for r in ch13.RECORDS}
DIAPHRAGM = dict(F=20, a=2.0, b=0.8, h=0.1, IRHD="50")


def stub(rid, rate, unit="per_million_hours"):
    return {"id": rid, "kind": covariate.KIND, "name": rid, "covariate_model": {
        "rate_unit": unit, "inputs": [], "modes": [{"key": "m", "name": "m", "base": {"value": rate, "page": "x"}}]}}


STUBS = {"nswc-11:bearing-rolling-load-rating": stub("b", 2.0), "nswc-11:valve-assembly": stub("v", 0.5,
         "per_million_operations"), "nswc-11:seal-mechanical": stub("s", 3.0),
         "nswc-11:shaft": stub("sh", 1e-4, "per_million_cycles")}
RESOLVE = {**RECORDS, **STUBS}.__getitem__
PARTS = dict(n_BE=2, VA_ops_per_hour=4, n_SE=1, SH_cycles_per_hour=60 * 1800)


def lam(slug, **values):
    return covariate.evaluate(RECORDS[f"nswc-11:{slug}"], values, RESOLVE)


def factors(out, key=None):
    mode = next(m for m in out["modes"] if key is None or m["key"] == key)
    return {f["symbol"]: f["value"] for f in mode["factors"]}


def test_records_have_no_problems():
    for rid, rec in RECORDS.items():
        assert covariate.problems(rec, RESOLVE) == [], rid


@pytest.mark.parametrize("driver, printed", [("radial", 12.0), ("axial", 12.0), ("piston_single", 14.0),
                                             ("piston_double", 16.5), ("labyrinth", 16.5),
                                             ("diaphragm_rubber", 22.8), ("diaphragm_metal", 28.5), ("vane", 12.0),
                                             ("screw", 12.0), ("lobe", 12.0), ("liquid_ring", 12.0)])
def test_fluid_driver_table_13_4_and_assembly_sum(driver, printed):
    out = lam("compressor", driver=driver, **PARTS)
    # Eq. 13-1: λ_FD·C_SF + casing 0.010 + bearings + valves (per operation × ops/h) + seals + shaft (× cycles/h).
    assert out["total"] == pytest.approx(printed + 0.010 + 2 * 2.0 + 0.5 * 4 + 3.0 + 1e-4 * 108000)
    assert out["unit"] == "per_million_hours"


def test_service_factors_table_13_5_multiply():
    out = lam("compressor", driver="piston_single", high_duty="yes", vibration_shock="yes", **PARTS)
    f = factors(out, "fluid_driver")
    assert (f["C_SF,duty"], f["C_SF,vib"], f["C_SF,temp"]) == (1.4, 1.3, 1.0)
    assert out["modes"][0]["rate"] == pytest.approx(14.0 * 1.4 * 1.3)
    expected = {"centrifugal": (1.2, 1.1, 1.1, 1.2, 1.1), "rotary": (1.2, 1.1, 1.2, 1.4, 1.4),
                "reciprocating": (1.4, 1.4, 1.1, 1.3, 1.1), "diaphragm": (1.2, 1.4, 1.2, 1.5, 1.3)}
    for driver, family in [("axial", "centrifugal"), ("screw", "rotary"), ("labyrinth", "reciprocating"),
                           ("diaphragm_metal", "diaphragm")]:
        f = factors(lam("compressor", driver=driver, **PARTS, **{name: "yes" for name, *_ in ch13.SERVICE}),
                    "fluid_driver")
        assert tuple(f[sym] for _, _, sym, _ in ch13.SERVICE) == expected[family]


def _stress(F, a, b, h, eta=0.5):
    c = a / b
    # Eq. 13-4 with its "ln c²" read as (ln c)² (p. 13-15; read as ln(c²) it is negative for c < 3.5).
    k_f = 3 * (1 - eta ** 2) / math.pi * ((c * c - 1) / (4 * c * c) - math.log(c) ** 2 / (c * c - 1))
    b_f = 2 / (1 - eta ** 2) * c * c * (2 * c * c * math.log(c) - c * c + 1) / (
        (c * c - 1) ** 2 - 4 * c * c * math.log(c) ** 2)  # Eq. 13-7
    return F * k_f * b_f / (2 * math.pi * h * h)  # Eq. 13-6


def test_diaphragm_strain_from_eq_13_6_and_table_13_2():
    out = lam("compressor-diaphragm", **DIAPHRAGM)
    d = {x["name"]: x["value"] for x in out["derived"]}
    assert d["sigma_r"] == pytest.approx(_stress(20, 2.0, 0.8, 0.1))
    assert d["E"] == 310  # Table 13-2, 50 IRHD
    s = 100 * d["sigma_r"] / 310
    assert d["S"] == pytest.approx(s)
    f = factors(out)
    assert f["C_P"] == pytest.approx(1.0 if s <= 75 else (s / 75) ** 1.8)
    assert f["C_AC"] == pytest.approx((s / 10) ** 1.1)
    assert out["total"] == pytest.approx(0.58 * f["C_P"] * f["C_AC"])


def test_eq_13_4_read_literally_would_be_negative():
    # Documents the reading: ln(c²) gives a negative bending stiffness at c = a/b = 2.5.
    c = 2.5
    assert (c * c - 1) / (4 * c * c) - math.log(c * c) / (c * c - 1) < 0
    assert (c * c - 1) / (4 * c * c) - math.log(c) ** 2 / (c * c - 1) > 0


def test_figures_13_6_and_13_7_ends():
    # Figure 13.6 (p. 13-22): C_P = 1 at 75 %, about 70 at 800 % (read from the figure's top right).
    assert (800 / 75) ** 1.8 == pytest.approx(70.8, abs=0.1)
    # Figure 13.7 (p. 13-23): at 100 % strain about 12.6 (0.3 pphm) and 100 (7.5 pphm).
    assert (100 / 10) ** 1.1 == pytest.approx(12.59, abs=0.01) and (100 / 10) ** 2 == 100


def test_ozone_coating_and_temperature():
    base = lam("compressor-diaphragm", **DIAPHRAGM)
    s = next(x["value"] for x in base["derived"] if x["name"] == "S")
    f = factors(lam("compressor-diaphragm", ozone="high", coating="yes", T=250, C_LC=0.3, **DIAPHRAGM))
    assert f["C_AC"] == pytest.approx((s / 10) ** 2 / 3)
    assert (f["C_T"], f["C_LC"]) == (6.7, 0.3)
    assert factors(lam("compressor-diaphragm", T=212, **DIAPHRAGM))["C_T"] == 1.0


def test_limits():
    with pytest.raises(covariate.CovariateError, match="smaller than the diaphragm"):
        lam("compressor-diaphragm", **{**DIAPHRAGM, "b": 2.5})
    words = " ".join(lam("compressor-diaphragm", **{**DIAPHRAGM, "b": 0.05, "h": 0.5, "F": 2000})["warnings"])
    assert "p. 13-15" in words
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("compressor", driver="screw")
