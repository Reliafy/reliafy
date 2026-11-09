"""NSWC-11 Chapter 19, sensors and transducers: Eq. 19-1 and Table 19-4 (pages
cited). The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library
from backend.scripts.nswc11.ch19_sensors import ELEMENTS


def lam(**values):
    return covariate.evaluate(library.get("nswc-11:sensor"), values, library.get)


def test_table_19_4_has_every_printed_row():
    # pp. 19-16 and 19-17: 43 rows, spot-checked against the page.
    assert len(ELEMENTS) == 43 and len({c for c, *_ in ELEMENTS}) == 43
    rates = {c: v for c, *_, v in ELEMENTS}
    assert rates["thermal_rtd"] == 1.50 and rates["presence_proximity"] == 15.38
    assert rates["optical_photodetector"] == 0.03 and rates["env_altitude"] == 3.39
    assert rates["env_humidity_capacitive"] == 20.44 and rates["fluid_flow"] == 14.30


def test_sensing_element_alone():
    out = lam(element="thermal_thermocouple")
    assert out["total"] == pytest.approx(5.0) and out["unit"] == "per_million_hours"


def test_eq_19_1_sums_the_network():
    # Eq. 19-1, p. 19-14: λ_TD = λ_TD,B + λ_S + λ_T + λ_C + λ_P + λ_X
    out = lam(element="position_lvdt", lam_TDB=0.5, lam_T=0.2, lam_C=1.1, lam_P=2.0, lam_X=0.4)
    assert out["total"] == pytest.approx(0.5 + 7.5 + 0.2 + 1.1 + 2.0 + 0.4)
    assert [m["key"] for m in out["modes"]] == ["base", "element", "line", "computer", "power", "other"]


def test_element_is_needed_and_rates_cant_be_negative():
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam()
    with pytest.raises(covariate.CovariateError):
        lam(element="thermal_rtd", lam_T=-1)
