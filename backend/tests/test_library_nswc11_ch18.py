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


def test_slider_crank_sums_its_parts_as_written():
    # Eq. 18-1: λ_SC = λ_BE + λ_RD + λ_SE + λ_RI + λ_SM; the rod is 0.001 each (p. 18-9).
    rec = library.get("nswc-11:slider-crank")
    out = covariate.evaluate(rec, {"n_BE": 3, "n_RD": 1, "n_SE": 2, "n_RI": 4}, resolve)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates == pytest.approx({"bearings": 6.0, "rods": 0.001, "seals": 1.0, "rings": 12.0, "slider": 7.0})
    assert out["total"] == pytest.approx(26.001)
    assert out["unit"] == "per_million_operations"
    # Every part's own unit differs from Eq. 18-1's: each mode says how the handbook adds them.
    assert all(m.get("note") for m in rec["covariate_model"]["modes"])


def test_slider_crank_reads_the_canonical_part_records():
    rec = library.get("nswc-11:slider-crank")
    used = {m["uses"] for m in rec["covariate_model"]["modes"] if m.get("uses")}
    assert used == set(STUBS)
    assert covariate.problems(rec, library.get) == []
    with pytest.raises(covariate.CovariateError, match="needed"):
        covariate.evaluate(rec, {"n_BE": 3}, resolve)
