"""NSWC-11 Chapter 5, solenoids and contactors: the models against the handbook's
own tables and figures (pages cited). The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library


def rec(slug):
    return library.get(f"nswc-11:{slug}")


def lam(slug, **values):
    return covariate.evaluate(rec(slug), values, library.get)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


def test_solenoid_temperature_factor_follows_figure_5_2():
    # Eq. 5-2, p. 5-6: (1/1.5^t)³, t = ((T_R − T_O) − 20)/10: 1 at 20 °C margin, 1.5^6 at 0.
    assert factors(lam("solenoid", T_R=130, T_O=110, ops_per_min=1))["C_T"] == pytest.approx(1.0)
    assert factors(lam("solenoid", T_R=130, T_O=130, ops_per_min=1))["C_T"] == pytest.approx(1.5 ** 6)
    assert factors(lam("solenoid", T_R=130, T_O=70, ops_per_min=1))["C_T"] == pytest.approx(1.5 ** -12)


def test_solenoid_rate_is_per_operation_times_operations_an_hour():
    # Eq. 5-1, p. 5-5: 2.77 per million operations × C_T × C_K × operations/min × 60.
    out = lam("solenoid", T_R=155, T_O=135, ops_per_min=2, environment="heavy_shock", duty="high_ext")
    assert out["unit"] == "per_million_hours"
    assert out["total"] == pytest.approx(2.77 * 1.0 * 1.7 * 120)


@pytest.mark.parametrize("env, row", [("uniform", [1.1, 1.3, 1.2, 1.4]), ("light_shock", [1.2, 1.4, 1.3, 1.5]),
                                      ("medium_shock", [1.3, 1.5, 1.4, 1.6]), ("heavy_shock", [1.4, 1.6, 1.5, 1.7])])
def test_service_factor_table_5_2(env, row):
    for duty, printed in zip(["normal_min", "normal_ext", "high_min", "high_ext"], row):
        assert factors(lam("solenoid", T_R=130, T_O=110, ops_per_min=1, environment=env, duty=duty))["C_K"] == printed


def test_contactor_by_load_type():
    # Eqs. 5-6 to 5-8, p. 5-9, with Figures 5.3 to 5.7 (pp. 5-11 to 5-15).
    common = dict(V_o=100, V_r=200, I_o=5, I_r=10)
    ac = lam("contactor", load="ac_resistive", **common)
    assert ac["unit"] == "per_million_operations"
    assert ac["total"] == pytest.approx(1.10 * 0.5 ** 0.75 * 3.50 * 0.5 ** 1.14)
    ind = lam("contactor", load="ac_inductive", PF=0.5, **common)
    assert factors(ind)["C_PF"] == pytest.approx(1.0)
    assert ind["total"] == pytest.approx(3.60 * 0.5 ** 0.75 * 3.50 * 0.5 ** 1.14)
    dc = lam("contactor", load="dc", **common)
    assert "C_PF" not in factors(dc)
    assert dc["total"] == pytest.approx(2.5 * 0.5 ** 1.33 * 4.20 * 0.5 ** 1.30)
    # At rating the AC current factor is 3.50 and the DC one 4.20, as plotted.
    assert factors(lam("contactor", load="dc", V_o=1, V_r=1, I_o=1, I_r=1))["C_I"] == pytest.approx(4.20)


def test_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError, match="power factor"):
        lam("contactor", load="ac_inductive", V_o=100, V_r=200, I_o=5, I_r=10)
    with pytest.raises(covariate.CovariateError, match="Power factor"):
        lam("contactor", load="ac_inductive", V_o=100, V_r=200, I_o=5, I_r=10, PF=1.2)
    out = lam("contactor", load="dc", V_o=150, V_r=100, I_o=0.5, I_r=10)
    words = " ".join(out["warnings"])
    assert "p. 5-14" in words and "p. 5-15" in words
    assert "p. 5-10" in " ".join(lam("solenoid", T_R=105, T_O=200, ops_per_min=1)["warnings"])
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("solenoid", T_R=105)
