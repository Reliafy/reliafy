"""NSWC-11 Chapter 4, springs: the models against the handbook's own tables,
figures and Chapter 1's worked example (pages cited)."""

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


# Table 1-1, p. 1-12: the example valve's poppet return spring (0.5 operations an hour).
TABLE_1_1 = dict(G_M=11.5e6, D_W=0.085, D_C=0.58, N_a=14, T_S=245e3, L1=3.35, L2=2.28, cycle_rate=0.5 / 60)


def test_table_1_1_spring():
    # The printed λ_SP = 1.04 is Eq. 4-5 (p. 4-12; p. 1-10): 23.8 · (S_G/T_S)³ with S_G = 86,200 psi.
    p_l = 11.5e6 * 0.085 ** 4 * (3.35 - 2.28) / (8 * 0.58 ** 3 * 14)  # Eq. 4-1/1-9: 29.4 lb
    r = 0.58 / 0.085
    k_w = (4 * r - 1) / (4 * r - 4) + 0.615 / r  # 1.219
    s_g = 8 * p_l * 0.58 * k_w / (math.pi * 0.085 ** 3)
    assert round(p_l, 1) == 29.4 and round(k_w, 3) == 1.219 and round(s_g / 1e3, 1) == 86.2
    assert round(23.8 * (s_g / 245e3) ** 3, 2) == 1.04
    # The library's model is the generalised Eq. 4-6. Table 1-1's spring is the reference spring of every
    # size factor (each is 1), so only C_Y = (190/245)³ and C_CS = 0.1 (under 30 cycles/min) are left:
    # 23.8 × 0.4664 × 0.1 = 1.11, not 1.04. Eq. 4-6's normalisation (C_Y referred to 190 ksi, C_CS = 0.1 for a
    # slow spring) doesn't reproduce Eq. 4-5 exactly; the gap is the handbook's two forms, not the model.
    out = lam("spring-compression", **TABLE_1_1)
    f = factors(out)
    for s in ("C_G", "C_DW", "C_DC", "C_N", "C_L", "C_K", "C_R", "C_M"):
        assert f[s] == pytest.approx(1.0, abs=2e-3), s
    assert f["C_CS"] == 0.1
    assert round(out["total"], 2) == 1.11


@pytest.mark.parametrize("g, printed", [(11.8, 1.08), (11.5, 1.00), (11.2, 0.92), (10.8, 0.83), (10.5, 0.76),
                                        (11.0, 0.88), (11.4, 0.97), (5.0, 0.08), (6.0, 0.14), (7.0, 0.23),
                                        (9.5, 0.56), (10.0, 0.67)])
def test_rigidity_factor_reproduces_table_4_2(g, printed):
    # Table 4-2, p. 4-39: C_G = (G_M / 11.5e6)³.
    c_g = factors(lam("spring-compression", **{**TABLE_1_1, "G_M": g * 1e6}))["C_G"]
    if g == 10.0:
        # Stainless 302/304/316: the table prints 0.67, its formula gives 0.658 (0.66). The model uses the formula.
        assert round(c_g, 3) == 0.658
    else:
        assert round(c_g, 2) == printed


@pytest.mark.parametrize("e, printed", [(29.0, 1.05), (28.5, 1.00), (15.0, 0.15), (17.0, 0.21), (26.0, 0.76),
                                        (28.0, 0.98), (29.5, 1.04), (31.0, 1.09)])
def test_elasticity_factor_against_table_4_2(e, printed):
    # Table 4-2, p. 4-39: C_E = (E_M / 28.5e6)³. Three rows don't match their own formula: stainless 302 (28.0:
    # printed 0.98, formula 0.95), 17-7 PH (29.5: printed 1.04, formula 1.11; stainless 431 at the same 29.5 is
    # printed 1.11) and Inconel (31.0: printed 1.09, formula 1.29). The model uses the formula.
    c_e = factors(lam("spring-torsion", E_M=e * 1e6, D_W=0.085, D_C=0.58, N_a=14, T_S=190e3, theta=0.667,
                      cycle_rate=300))["C_E"]
    formula = {28.0: 0.95, 29.5: 1.11, 31.0: 1.29}
    assert round(c_e, 2) == formula.get(e, printed)


@pytest.mark.parametrize("ts, printed", [(110, 5.15), (125, 3.51), (145, 2.25), (158, 1.74), (175, 1.28),
                                         (190, 1.00), (210, 0.74), (216, 0.68), (227, 0.59), (245, 0.47),
                                         (268, 0.36), (295, 0.27)])
def test_tensile_factor_reproduces_table_4_3(ts, printed):
    c_y = factors(lam("spring-compression", **{**TABLE_1_1, "T_S": ts * 1e3}))["C_Y"]
    assert round(c_y, 2) == printed


@pytest.mark.parametrize("n, printed", [(3, 2.78), (4, 1.56), (5, 1.00), (6, 0.69), (7, 0.51), (8, 0.39)])
def test_wave_factor_reproduces_table_4_4(n, printed):
    out = lam("spring-wave-washer", E_M=28.5e6, t=0.025, OD=1.2, f=0.055, N=n, T_S=190e3, cycle_rate=300)
    f = factors(out)
    assert round(f["C_NW"], 2) == printed
    assert out["total"] == pytest.approx(1.9 * f["C_NW"])  # every other factor is at its reference


def test_belleville_stress_factor_follows_figure_4_19():
    def c_s(R):
        return factors(lam("spring-belleville", E_M=28.5e6, t=0.025, OD=1.2, ID=1.2 / R, f=0.055, T_S=190e3,
                           cycle_rate=300))["C_S"]
    assert c_s(2.0) == pytest.approx(1.157, abs=1e-3)  # read about 1.15 on the curve
    assert c_s(1.2) == pytest.approx(0.31, abs=0.01)
    assert c_s(4.7) == pytest.approx(3.0, abs=0.05)
    with pytest.raises(covariate.CovariateError, match="outside diameter must be more"):
        lam("spring-belleville", E_M=28.5e6, t=0.025, OD=1.0, ID=1.0, f=0.055, T_S=190e3, cycle_rate=300)


def test_cycle_rate_factor_figure_4_20():
    rates = {10: 0.1, 30: 0.1, 150: 0.5, 300: 1.0, 450: 1.5 ** 3}
    for cr, printed in rates.items():
        assert factors(lam("spring-compression", **{**TABLE_1_1, "cycle_rate": cr}))["C_CS"] == pytest.approx(printed)


def test_reference_springs_give_their_base_rates():
    # Each flat spring at its factors' reference values (and 300 cycles/min) returns its base rate.
    common = dict(E_M=28.5e6, t=0.025, f=0.055, T_S=190e3, cycle_rate=300)
    assert lam("spring-curved-washer", OD=1.2, **common)["total"] == pytest.approx(1.1)
    assert lam("spring-cantilever", L=1.2, **common)["total"] == pytest.approx(1.1)
    assert lam("spring-beam", L=1.2, **common)["total"] == pytest.approx(4.4)
    torsion = lam("spring-torsion", E_M=28.5e6, D_W=0.085, D_C=0.58, N_a=14, T_S=190e3, theta=0.667,
                  cycle_rate=300)
    assert torsion["total"] == pytest.approx(14.3)
    ext = lam("spring-extension", **{**TABLE_1_1, "T_S": 190e3, "cycle_rate": 300, "L1": 2.0, "L2": 3.07})
    assert ext["total"] == pytest.approx(23.8, rel=2e-3)  # extension: same model, the deflection's sign ignored


def test_coil_diameter_uses_the_printed_sixth_power():
    # Figure 4.11, p. 4-27: the formula is (0.58/D_C)^6; the plotted curve is the cube (see the module note).
    f = factors(lam("spring-compression", **{**TABLE_1_1, "D_C": 1.16, "D_W": 0.17}))
    assert f["C_DC"] == pytest.approx(0.5 ** 6)


def test_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError, match="Wire diameter"):
        lam("spring-compression", **{**TABLE_1_1, "D_W": 0})
    with pytest.raises(covariate.CovariateError, match="coil diameter must be more"):
        lam("spring-compression", **{**TABLE_1_1, "D_W": 0.6})
    out = lam("spring-compression", **{**TABLE_1_1, "T_S": 400e3, "N_a": 3, "cycle_rate": 900})
    words = " ".join(out["warnings"])
    assert "p. 4-40" in words and "p. 4-28" in words and "p. 4-36" in words
