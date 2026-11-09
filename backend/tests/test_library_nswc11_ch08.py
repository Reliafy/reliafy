"""NSWC-11 Chapter 8, gears and splines: the models against the handbook's
equations, figures and tables (pages cited). The chapter has no worked example."""

import math

import pytest

from backend.library import covariate
from backend.library import service as library


def rec(slug):
    return library.get(f"nswc-11:{slug}")


def lam(slug, **values):
    return covariate.evaluate(rec(slug), values, library.get)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


GEAR = dict(V_o=1800, V_d=1800, L_O=500, L_D=1000)


def test_gear_base_rate_is_one_failure_per_design_life_at_design_speed():
    # p. 8-9: λ_G,B = (RPM × 60) / design life, 10^8 revolutions by default; ×10^6 for per million hours.
    out = lam("gear", **GEAR)
    assert out["modes"][0]["base"]["value"] == pytest.approx(1800 * 60 / 1e8 * 1e6)  # 1080
    f = factors(out)
    # At the design speed C_GS = 1 + 1 = 2 (Eq. 8-3); at half the design load C_GP = 1 (Eq. 8-6);
    # misalignment 0.006 rad, specified lubricant, 160 °F, uniform service: all 1.
    assert f == pytest.approx({"C_GS": 2.0, "C_GP": 1.0, "C_GA": 1.0, "C_GL": 1.0, "C_GT": 1.0, "C_GV": 1.0})
    # 1800 rpm is 108,000 revolutions an hour: 10^8 revolutions last 926 h, so 1,080 per million hours.
    assert out["total"] == pytest.approx(2160.0)
    assert out["unit"] == "per_million_hours"


def test_gear_factors_follow_equations_8_3_to_8_9():
    out = lam("gear", V_o=900, V_d=1800, L_O=1000, L_D=1000, A_E=0.012, nu_ratio=1.5, T_AT=300)
    f = factors(out)
    assert f["C_GS"] == pytest.approx(1 + 0.5 ** 0.7)
    assert f["C_GP"] == pytest.approx(2 ** 4.69)  # 25.8 at the design load
    assert f["C_GA"] == pytest.approx(2 ** 2.36)
    assert f["C_GL"] == pytest.approx(1.5 ** 0.54)
    assert f["C_GT"] == pytest.approx(760 / 620)


@pytest.mark.parametrize("degrees", [0.2, 0.5, 1.0, 2.0])
def test_misalignment_in_radians_matches_figure_8_8_in_degrees(degrees):
    # Eq. 8-7 (radians, p. 8-10) and Figure 8.8's 12.44·A_E^2.36 (degrees, p. 8-16) are one curve.
    f = factors(lam("gear", A_E=math.radians(degrees), **GEAR))
    assert f["C_GA"] == pytest.approx(12.44 * degrees ** 2.36, rel=2e-3)


@pytest.mark.parametrize("prime, driven, printed", [
    ("uniform", "uniform", 1.00), ("uniform", "heavy_shock", 1.75), ("medium_shock", "medium_shock", 1.50),
    ("heavy_shock", "uniform", 1.50), ("heavy_shock", "heavy_shock", 2.25),
])
def test_agma_service_factor_table(prime, driven, printed):
    # Table 8-1 (AGMA service factor), p. 8-19.
    assert factors(lam("gear", prime_mover=prime, driven_load=driven, **GEAR))["C_GV"] == printed


def test_known_rate_gear_takes_the_makers_rate():
    out = lam("gear-known-rate", lambda_GB=3.0, **GEAR)
    assert out["total"] == pytest.approx(6.0)


def test_gear_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError, match="Misalignment angle"):
        lam("gear", A_E=0, **GEAR)
    out = lam("gear", V_o=3000, V_d=1800, L_O=1500, L_D=1000, A_E=0.05, T_AT=800)
    words = " ".join(out["warnings"])
    for page in ("8-14", "8-15", "8-16", "8-18"):
        assert f"p. {page}" in words


def test_spline_life_and_rate_follow_equations_8_11_to_8_13():
    vals = dict(G_L=2.0, G_D=2.0, G_T=10000, G_B=300, A_E=0.006, V_o=1800, V_d=1800)
    out = lam("spline", **vals)
    phi = 4.85e3 * 300 * 2.0 ** 3 / 10000
    theta = 7.08e-10 * (phi * 2.0 / 2.0) ** 4.56 * 0.006 ** -2.36
    assert out["modes"][0]["base"]["value"] == pytest.approx(1e6 / theta)
    assert out["total"] == pytest.approx(1e6 / theta * 2.0)  # C_GS = 2 at the design speed; others 1
    assert out["unit"] == "per_million_cycles"
    f = factors(out)
    assert set(f) == {"C_GS", "C_GL", "C_GT", "C_GV"}


def test_spline_needs_a_misalignment():
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("spline", G_L=2.0, G_D=2.0, G_T=10000, G_B=300, V_o=1800, V_d=1800)
