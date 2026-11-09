"""NSWC-11 Chapter 17, mechanical couplings: Eq. 17-1 to 17-3 and Table 17-3
(pages cited). The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library


def stub(slug, rate):
    """A one-number record standing in for a part's own model (another chapter's)."""
    return {"id": f"nswc-11:{slug}", "kind": covariate.KIND, "name": slug, "covariate_model": {
        "rate_unit": "per_million_hours", "inputs": [],
        "modes": [{"key": "x", "name": slug, "base": {"value": rate, "page": "-"}}]}}


STUBS = {r["id"]: r for r in (stub("gear", 1.5), stub("seal-dynamic", 4.0), stub("bearing-rolling-load-rating", 2.0),
                              stub("fastener", 0.1))}


def resolve(rid):
    return STUBS.get(rid) or library.get(rid)


def lam(slug, values, resolver=library.get):
    return covariate.evaluate(library.get(f"nswc-11:{slug}"), values, resolver)


@pytest.mark.parametrize("driven, torque, printed", [("uniform", "normal", 1.1), ("light_shock", "high", 1.3),
                                                     ("medium_shock", "normal", 1.3), ("heavy_shock", "high", 1.5)])
def test_endurance_coupling_eq_17_1_with_table_17_3(driven, torque, printed):
    out = lam("coupling-endurance", {"N_cycles": 1e7, "driven": driven, "torque": torque})
    assert out["total"] == pytest.approx(1e6 / 1e7 * printed)
    assert out["unit"] == "per_million_cycles"


def test_gear_coupling_is_its_body_plus_its_parts():
    # Eq. 17-2 (p. 17-6): λ_CP,B·C_SF + λ_GR + λ_SE + λ_H, per million hours: the per-cycle body and housing
    # (λ_H 0.001, p. 17-9) × the coupling's cycles an hour (pp. 12-10, 12-16), the per-hour gears and seals as
    # they are. λ_CP,B has no default (p. 17-7's 5.0 is a whole coupling's rate).
    out = lam("coupling-gear", {"lambda_CP_B": 2.0, "cycles_per_hour": 10, "n_GR": 2, "n_SE": 2}, resolve)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates == pytest.approx({"coupling": 2.0 * 1.1 * 10, "gears": 3.0, "seals": 8.0, "housing": 0.001 * 10})
    assert out["total"] == pytest.approx(22.0 + 3.0 + 8.0 + 0.01)
    assert out["unit"] == "per_million_hours"
    with pytest.raises(covariate.CovariateError) as exc:
        lam("coupling-gear", {"cycles_per_hour": 10, "n_GR": 2, "n_SE": 2}, resolve)
    assert exc.value.missing == ["lambda_CP_B"]


def test_universal_joint_is_the_sum_of_its_parts():
    # Eq. 17-3 (p. 17-9): the per-hour bearings, seals and fasteners as they are, the housing × cycles an hour.
    out = lam("coupling-universal-joint", {"cycles_per_hour": 100, "n_BE": 4, "n_SE": 4, "n_F": 8}, resolve)
    assert out["total"] == pytest.approx(8.0 + 16.0 + 0.001 * 100 + 0.8)
    assert out["unit"] == "per_million_hours"


def test_records_build_against_the_real_parts():
    for slug in ("coupling-gear", "coupling-universal-joint"):
        rec = library.get(f"nswc-11:{slug}")
        assert covariate.problems(rec, library.get) == []
