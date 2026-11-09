"""NSWC-11 Chapter 11, fluid filters: the model against the handbook's equations
and tables (pages cited). The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.scripts.build_nswc11 import _record
from backend.scripts.nswc11 import ch11_filters

RECORDS = {f"nswc-11:{r['slug']}": _record(r) for r in ch11_filters.RECORDS}


def lam(slug, **values):
    return covariate.evaluate(RECORDS[f"nswc-11:{slug}"], values, RECORDS.__getitem__)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


def test_record_has_no_problems():
    for rec in RECORDS.values():
        assert covariate.problems(rec, RECORDS.__getitem__) == []


def test_base_rate_and_pressure_factor():
    # Eq. 11-2 (p. 11-9): 2.53 per million hours; Eq. 11-3 (p. 11-10): C_DP = 1.25 P_O / P_R, 1 at P_O = 0.8 P_R.
    out = lam("filter-fluid", P_O=80, P_R=100)
    assert out["total"] == pytest.approx(2.53)
    assert out["unit"] == "per_million_hours"
    assert factors(lam("filter-fluid", P_O=100, P_R=100))["C_DP"] == pytest.approx(1.25)
    assert lam("filter-fluid", P_O=50, P_R=100, lambda_FB=1e6 / 200000)["total"] == pytest.approx(5 * 0.625)


@pytest.mark.parametrize("pore, surge, printed", [("uniform", "low", 1.0), ("uniform", "high", 1.2),
                                                  ("non_uniform", "low", 1.2), ("non_uniform", "high", 1.5)])
def test_cyclic_flow_reproduces_table_11_2(pore, surge, printed):
    assert factors(lam("filter-fluid", P_O=80, P_R=100, pore=pore, surge=surge))["C_CF"] == printed


def test_vibration_factor():
    # p. 11-10: 1.25 for aircraft and mobile systems, 1.00 otherwise.
    assert factors(lam("filter-fluid", P_O=80, P_R=100, mobile="aircraft_mobile"))["C_V"] == 1.25
    assert factors(lam("filter-fluid", P_O=80, P_R=100))["C_V"] == 1.0


@pytest.mark.parametrize("fluid, x", [("water", 0.2), ("sea_water", 0.2), ("gasoline", 0.3), ("kerosene", 0.2),
                                      ("light_lube_oil", 0.2), ("heavy_lube_oil", 0.7), ("sae_10", 0.5),
                                      ("sae_20", 0.6), ("sae_30", 0.7), ("sae_40", 0.8), ("sae_50", 0.9),
                                      ("sae_60", 1.0), ("sae_70", 1.1)])
def test_cold_start_exponent_from_table_11_3(fluid, x):
    # Eq. 11-4 (p. 11-10): C_CS = (ν_cold / ν_normal)^x; e.g. SAE 30 from 0 °C to 60 °C: 2282/33 cSt.
    out = lam("filter-fluid", P_O=80, P_R=100, fluid=fluid, nu_ratio=2282 / 33)
    assert factors(out)["C_CS"] == pytest.approx((2282 / 33) ** x)


def test_limits():
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("filter-fluid", P_O=80)
    with pytest.raises(covariate.CovariateError, match="Rated filter pressure"):
        lam("filter-fluid", P_O=80, P_R=0)
    words = " ".join(lam("filter-fluid", P_O=120, P_R=100, nu_ratio=0.5)["warnings"])
    assert "p. 11-9" in words and "p. 11-10" in words
