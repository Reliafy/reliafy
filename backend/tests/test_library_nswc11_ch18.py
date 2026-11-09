"""NSWC-11 Chapter 18, slider crank mechanisms: Eq. 18-1's sum of parts (p. 18-3).
The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library

STUBS = {"nswc-11:bearing-rolling-load-rating": ("per_million_hours", 2.0),
         "nswc-11:seal-static": ("per_million_hours", 0.5),
         "nswc-11:seal-dynamic": ("per_million_hours", 3.0),
         "nswc-11:actuator-side-load": ("per_million_cycles", 7.0)}


def _stub(rid, unit, rate):
    return {"id": rid, "name": rid, "kind": covariate.KIND, "covariate_model": {
        "rate_unit": unit, "inputs": [], "derived": [], "checks": [],
        "modes": [{"key": "part", "name": "part", "base": {"value": rate, "page": "x"}, "factors": []}]}}


def resolve(rid):
    return _stub(rid, *STUBS[rid]) if rid in STUBS else library.get(rid)


def test_slider_crank_sums_its_parts_per_hour():
    # Eq. 18-1: λ_SC = λ_BE + λ_RD + λ_SE + λ_RI + λ_SM, every term per million hours: the slider's wear
    # (Chapter 9, per million cycles) × the crank's operations an hour (pp. 12-10, 12-16); the bearings, seals
    # and the rod's 0.001 each (p. 18-9) are per million hours already.
    rec = library.get("nswc-11:slider-crank")
    out = covariate.evaluate(rec, {"ops_per_hour": 120, "n_BE": 3, "n_RD": 1, "n_SE": 2, "n_RI": 4}, resolve)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates == pytest.approx({"bearings": 6.0, "rods": 0.001, "seals": 1.0, "rings": 12.0, "slider": 7.0 * 120})
    assert out["total"] == pytest.approx(19.001 + 840.0)
    assert out["unit"] == "per_million_hours"
    assert all(m.get("note") for m in rec["covariate_model"]["modes"])


def test_slider_crank_at_1800_rpm_with_the_real_parts():
    # 1,800 rpm = 108,000 operations an hour, which also sets the bearings' speed. Before the fix the record
    # summed the per-hour bearings and seals into a total "per million operations" that a prediction then
    # multiplied by 108,000: the bearings' 110.7 per million hours became about 1.2 × 10⁷.
    be = {"L_S": 5000, "F_R": 500}
    rings = {"P1": 100, "Q_f": 0.06, "D_SL": 2, "n": 0, "V_lin": 300, "M": 500, "C": 910, "f": 15, "T_R": 250,
             "T_O": 100, "source": "piston_pump", "FR": 10}
    slider = {"W_S": 50, "L": 2, "D1": 3.0, "D2": 2.998, "eta1": 0.3, "eta2": 0.3, "E1": 30e6, "E2": 30e6,
              "F_Y": 50000, "wear": "gouging"}
    values = {"ops_per_hour": 108000, "n_BE": 2, "n_RD": 1, "n_SE": 0, "n_RI": 2,
              **{f"bearings.{k}": v for k, v in be.items()}, **{f"rings.{k}": v for k, v in rings.items()},
              **{f"slider.{k}": v for k, v in slider.items()}}
    out = covariate.evaluate(library.get("nswc-11:slider-crank"), values, library.get)
    bearing = covariate.evaluate(library.get("nswc-11:bearing-rolling-load-rating"), {**be, "n": 1800},
                                 library.get)["total"]
    ring = covariate.evaluate(library.get("nswc-11:seal-dynamic"), rings, library.get)["total"]
    wear = covariate.evaluate(library.get("nswc-11:actuator-side-load"), slider, library.get)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates["bearings"] == pytest.approx(2 * bearing) and round(2 * bearing, 1) == 110.7
    assert rates["rings"] == pytest.approx(2 * ring)
    assert rates["slider"] == pytest.approx(wear["total"] * 108000)
    assert out["total"] == pytest.approx(2 * bearing + 0.001 + 2 * ring + wear["total"] * 108000)
    assert round(out["total"], 1) == 111.7
    # The actuator's own warning (its 9th-power life is far outside the handbook's test lives) comes through.
    assert any("p. 9-11" in w for w in out["warnings"])


def test_slider_crank_reads_the_canonical_part_records():
    rec = library.get("nswc-11:slider-crank")
    used = {m["uses"] for m in rec["covariate_model"]["modes"] if m.get("uses")}
    assert used == set(STUBS)
    assert covariate.problems(rec, library.get) == []
    with pytest.raises(covariate.CovariateError, match="needed"):
        covariate.evaluate(rec, {"ops_per_hour": 60, "n_BE": 3}, resolve)
