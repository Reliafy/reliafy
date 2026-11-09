"""NSWC-11 Chapter 15, accumulators: the cylinder wall's stress-strength model
and the accumulator's sum of parts, against the handbook's equations (pages
cited). The chapter has no worked example."""

import importlib
import math

import pytest

from backend.library import covariate
from backend.library import service as library
from backend.scripts import build_nswc11

ch15 = importlib.import_module("backend.scripts.nswc11.ch15_accumulators")
OWN = {r["id"]: r for r in (build_nswc11._record(x) for x in ch15.RECORDS)}

STUBS = {"nswc-11:seal-dynamic": ("per_million_hours", 1.0), "nswc-11:spring-compression": ("per_million_hours", 2.0),
         "nswc-11:actuator-side-load": ("per_million_cycles", 4.0),
         "nswc-11:valve-assembly": ("per_million_operations", 8.0)}


def _stub(rid, unit, rate):
    return {"id": rid, "name": rid, "kind": covariate.KIND, "covariate_model": {
        "rate_unit": unit, "inputs": [], "derived": [], "checks": [],
        "modes": [{"key": "part", "name": "part", "base": {"value": rate, "page": "x"}, "factors": []}]}}


def resolve(rid):
    """Chapter 15's own records straight from the module, other chapters' parts as fixed rates (some of
    those chapters are written separately), so these tests check Chapter 15's own sum."""
    if rid in OWN:
        return OWN[rid]
    if rid in STUBS:
        return _stub(rid, *STUBS[rid])
    return library.get(rid)


def lam(slug, **values):
    return covariate.evaluate(resolve(f"nswc-11:{slug}"), values, resolve)


THIN = dict(P=3000, s_P=300, r_i=2.0, t=0.15, F_y=60000, s_Fy=4000, t_op=87600)


def q(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def rate(z, t_op):
    return -math.log1p(-q(z)) / t_op * 1e6


def d(out):
    return {x["name"]: x["value"] for x in out["derived"]}


def test_thin_wall_stresses_with_joint_efficiency():
    # Eq. 15-6 and 15-7 (p. 15-8), Table 15-2 (p. 15-9): welded double butt joint, 0.85.
    out = lam("accumulator-cylinder-wall", joint_c="welded_butt_double", joint_l="riveted_lap_single", **THIN)
    v = d(out)
    assert v["thick"] == 0
    assert v["sigma_c"] == pytest.approx(3000 * 2 / (0.15 * 0.85))
    assert v["sigma_l"] == pytest.approx(3000 * 2 / (2 * 0.15 * 0.55))
    assert v["sigma_r"] == 0
    z_c = (60000 - v["sigma_c"]) / math.sqrt(4000 ** 2 + (v["sigma_c"] * 0.1) ** 2)  # Eq. 15-17
    assert v["z_c"] == pytest.approx(z_c)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates["base"] == 0.001
    assert rates["circumferential"] == pytest.approx(rate(z_c, 87600), rel=1e-6)
    assert rates["radial"] == 0
    assert out["total"] == pytest.approx(sum(rates.values()))


def test_thick_wall_lame_stresses():
    # Eq. 15-11 to 15-13 (pp. 15-10, 15-11), r the average radius; t/r_i = 0.5 is thick.
    out = lam("accumulator-cylinder-wall", **{**THIN, "r_i": 1.0, "t": 0.5, "P": 10000, "s_P": 500})
    v = d(out)
    ri, ro, r, P = 1.0, 1.5, 1.25, 10000
    assert v["thick"] == 1
    assert v["sigma_l"] == pytest.approx(P * ri ** 2 / (ro ** 2 - ri ** 2))
    assert v["sigma_c"] == pytest.approx(P * ri ** 2 * (ro ** 2 + r ** 2) / (r ** 2 * (ro ** 2 - ri ** 2)))
    assert v["sigma_r"] == pytest.approx(P * ri ** 2 * (ro ** 2 - r ** 2) / (r ** 2 * (ro ** 2 - ri ** 2)))
    assert {m["key"]: m["rate"] for m in out["modes"]}["radial"] > 0


@pytest.mark.parametrize("z", [-2.0, -0.5, 0.0, 0.7, 1.5, 3.0, 5.0, 8.0])
def test_normal_tail_fit_matches_erfc(z):
    # Q = 1 - Phi(z) by the Numerical Recipes erfcc fit (fractional error under 1.2e-7): pick P so z_l = z.
    s_fy, f_y = 1000.0, 50000.0
    sigma = f_y - z * s_fy  # s_P = 0 gives sigma_s = 0, so z = (F_y - sigma)/s_Fy
    P = sigma * 2 * 0.15 / 2.0  # thin wall, no joint: sigma_l = P r_i / (2 t)
    out = lam("accumulator-cylinder-wall", **{**THIN, "P": P, "s_P": 0, "F_y": f_y, "s_Fy": s_fy})
    v = d(out)
    assert v["z_l"] == pytest.approx(z, abs=1e-9)
    assert v["Q_l"] == pytest.approx(q(z), rel=2e-7)
    assert v["lam_l"] == pytest.approx(-math.log(q(-z)) / 87600 * 1e6, rel=1e-6)
    # The hoop stress is twice the longitudinal, far past the strength: R is a tail too small for a float
    # (Q(|z|) underflows), yet −ln R stays finite, matching the tail's asymptote z²/2 + ln(|z|·√(2π)).
    zc = v["z_c"]
    assert zc < -30 and q(-zc) < 1e-200
    assert v["lam_c"] == pytest.approx((zc ** 2 / 2 + math.log(-zc * math.sqrt(2 * math.pi))) / 87600 * 1e6,
                                       rel=1e-3)


def test_checks_warn_on_yield_and_unused_joints():
    words = " ".join(lam("accumulator-cylinder-wall", **{**THIN, "P": 6000})["warnings"])
    assert "expected to yield" in words
    words = " ".join(lam("accumulator-cylinder-wall", joint_c="welded_butt_single",
                         **{**THIN, "t": 0.5})["warnings"])
    assert "joints given aren't used" in words
    with pytest.raises(covariate.CovariateError):
        lam("accumulator-cylinder-wall", **{**THIN, "s_Fy": 0})


def test_accumulators_sum_their_parts_as_written():
    # Eq. 15-1 (p. 15-5): seals + springs + piston/cylinder + valve + wall, rates added as the handbook writes them.
    wall = lam("accumulator-cylinder-wall", **THIN)["total"]
    wall_values = {f"wall.{k}": v for k, v in THIN.items()}
    out = lam("accumulator-spring-loaded", n_SE=2, n_SP=1, **wall_values)
    assert out["total"] == pytest.approx(2 * 1.0 + 2.0 + 4.0 + 8.0 + wall)
    gas = lam("accumulator-gas-charged", n_SE=2, **wall_values)
    assert gas["total"] == pytest.approx(2 * 1.0 + 4.0 + 8.0 + wall)
    assert "springs" not in {m["key"] for m in gas["modes"]}
    for rid in ("nswc-11:accumulator-spring-loaded", "nswc-11:accumulator-gas-charged"):
        assert covariate.problems(OWN[rid], resolve) == []
