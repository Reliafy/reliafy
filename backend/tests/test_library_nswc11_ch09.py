"""NSWC-11 Chapter 9, actuators: the models against the handbook's equations
(pages cited). The chapter has no worked example."""

import math

import pytest

from backend.library import covariate
from backend.scripts.build_nswc11 import _record
from backend.scripts.nswc11 import ch09_actuators

RECORDS = {f"nswc-11:{r['slug']}": _record(r) for r in ch09_actuators.RECORDS}
STEEL = dict(D1=2.0, D2=1.998, eta1=0.3, eta2=0.3, E1=30e6, E2=30e6, F_Y=40000, wear="adhesive")


def lam(slug, **values):
    return covariate.evaluate(RECORDS[f"nswc-11:{slug}"], values, RECORDS.__getitem__)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


def test_records_have_no_problems():
    for rec in RECORDS.values():
        assert covariate.problems(rec, RECORDS.__getitem__) == []


def test_side_load_base_rate_is_eq_9_4_and_9_14():
    out = lam("actuator-side-load", W_S=200, L=1.5, **STEEL)
    k_e = 2 * (1 - 0.3 ** 2) / 30e6
    stress = math.sqrt(200 / 1.5 * (0.002 / (2.0 * 1.998)) / k_e)
    n_o = 15.4e3 * (0.20 * 40000 / stress) ** 9
    assert out["unit"] == "per_million_cycles"
    assert out["total"] == pytest.approx(1e6 / n_o)  # all factors 1 at the defaults
    d = {x["name"]: x["value"] for x in out["derived"]}
    assert d["S_C"] == pytest.approx(0.8 * stress)  # Eq. 9-3


def test_axial_load_base_rate_is_eq_9_6():
    out = lam("actuator-axial-load", W_A=500, **{**STEEL, "wear": "gouging"})
    k_e = 2 * (1 - 0.3 ** 2) / 30e6
    stress = (500 * (0.002 / (2.0 * 1.998)) ** 2 / k_e ** 2) ** (1 / 3)
    assert out["total"] == pytest.approx(1e6 / (17.7e3 * (0.54 * 40000 / stress) ** 9))


def test_k1_is_not_quite_eq_9_2_over_0_8_to_the_9th():
    # Documents the gap noted on p. 9-7: k1 = 15.4e3 "includes a lubrication constant"; 2000/0.8^9 is 14.9e3.
    assert 2000 / 0.8 ** 9 == pytest.approx(14901, abs=1)


def test_contaminant_factor_is_eq_9_19():
    f = factors(lam("actuator-side-load", W_S=200, L=1.5, C_H=2, filter_micron=25, C_N=1.5, **STEEL))
    assert (f["C_H"], f["C_S"], f["C_N"]) == (2, 2.5, 1.5)


def test_temperature_factor_eq_9_22_in_kelvin():
    # 1 at the 25.2 °C ambient; with θ = 1200 K it is close to Eq. 9-23's e^(4[1 − T_a/T]).
    assert factors(lam("actuator-side-load", W_S=200, L=1.5, **STEEL))["C_T"] == pytest.approx(1.0)
    c_t = factors(lam("actuator-side-load", W_S=200, L=1.5, T_O=100, **STEEL))["C_T"]
    assert c_t == pytest.approx(math.exp(1200 / 298.35 * (1 - 298.35 / 373.15)))
    assert c_t == pytest.approx(math.exp(4 * (1 - 298.35 / 373.15)), rel=0.01)


def test_limits():
    with pytest.raises(covariate.CovariateError, match="larger than the piston"):
        lam("actuator-side-load", W_S=200, L=1.5, **{**STEEL, "D2": 2.0})
    words = " ".join(lam("actuator-side-load", W_S=200, L=1.5, theta=8000, C_N=3,
                         **{**STEEL, "F_Y": 150000})["warnings"])
    assert "p. 9-17" in words and "p. 9-15" in words and "p. 9-14" in words
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("actuator-side-load", W_S=200, L=1.5, **{k: v for k, v in STEEL.items() if k != "wear"})
