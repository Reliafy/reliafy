"""NSWC-11 Chapter 3, seals and gaskets: the models against the handbook's own
figures, tables and Chapter 1's worked example (pages cited)."""

import math

import pytest

from backend.library import covariate
from backend.library import service as library
from backend.scripts.nswc11.ch03_seals import NU_O_CP


def rec(slug):
    return library.get(f"nswc-11:{slug}")


def lam(slug, **values):
    return covariate.evaluate(rec(slug), values, library.get)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


STATIC = dict(P1=3000, P2=15, Q_f=0.06, D_SL=0.34, M=500, C=910, f=35, T_R=250, T_O=250, source="cylinder",
              C_o=10, FR=10)


def test_table_1_1_seal_comes_from_eq_3_5_not_eq_3_7():
    # Table 1-1, p. 1-12 prints λ_SE = 1.20 from the leakage form (Eq. 3-5, p. 3-8; p. 1-10) with
    # K1 = 3.27e-4, P1 = 3000, P2 = 15, H = 1.02e-4, Q_f = 0.06, ν_a = 2e-8, r_i = 0.17, r_o = 0.35:
    eq_3_5 = 2.4 * (3.27e-4 * (3000 ** 2 - 15 ** 2) * 1.02e-4 ** 3) / (0.06 * 2e-8 * 15) * (0.35 + 0.17) / (0.35 - 0.17)
    assert round(eq_3_5, 2) == 1.20
    # The library's model is the normalised Eq. 3-7 (p. 3-8), whose factors the same seal sets to:
    # C_P = (2985/3000)² , C_Q = 0.055/0.06, C_DL = 1.1·0.34 + 0.32, C_H = (0.549/0.55)^4.3, C_F = 35^1.65/353,
    # C_ν = 1 (ν_a = ν_o). Table 1-1 gives no temperature or contamination, so C_T and C_N are left out of
    # the comparison: the rest gives 1.50, not 1.20. The gap is the two forms, not a slip in the model.
    out = lam("seal-static", **STATIC)
    f = factors(out)
    assert f["C_T"] == 1.0 and f["C_ν"] == pytest.approx(1.0)
    without_t_n = out["total"] / (f["C_T"] * f["C_N"])
    expected = 2.4 * (2985 / 3000) ** 2 * (0.055 / 0.06) * (1.1 * 0.34 + 0.32) * ((500 / 910) / 0.55) ** 4.3 \
        * 35 ** 1.65 / 353
    assert without_t_n == pytest.approx(expected)
    assert round(without_t_n, 2) == 1.50


def test_figure_formulas_meet_at_their_breaks():
    # Figures 3.10, 3.11, 3.15, 3.16 (pp. 3-29, 3-30, 3-34, 3-35): each piecewise curve is continuous.
    f = factors(lam("seal-static", **{**STATIC, "P1": 1514.7, "P2": 14.7, "Q_f": 0.03, "f": 15, "T_O": 210}))
    assert f["C_P"] == pytest.approx(0.25)
    assert f["C_Q"] == pytest.approx(0.055 / 0.03, abs=0.005)
    assert f["C_F"] == pytest.approx(0.25, abs=0.01)
    assert f["C_T"] == pytest.approx(0.21, abs=0.005)
    hot = factors(lam("seal-static", **{**STATIC, "T_O": 286}))  # 36 °F over rating: t = -2
    assert hot["C_T"] == pytest.approx(4.0)


def test_fluid_viscosity_table_3_3_and_its_formula():
    # Table 3-3, p. 3-37: printed steps are returned exactly; C_ν = ν_o/ν with ν_o = 2e-8 lbf·min/in².
    for fluid, t, printed in [("water", 100, 12.15), ("sae30", 200, 0.8511), ("air", -50, 554.0),
                              ("mil_h_5606", 350, 4.880)]:
        f = factors(lam("seal-static", **{**STATIC, "fluid": fluid, "T_R": t, "T_O": t}))
        assert f["C_ν"] == pytest.approx(printed)
    # Water at 100 °F is about 0.68 cP: the formula gives 12.2 against the printed 12.15.
    f = factors(lam("seal-static", **{**STATIC, "fluid": "other", "nu_cP": 0.68}))
    assert round(f["C_ν"], 1) == 12.2
    assert NU_O_CP == pytest.approx(8.2737, abs=1e-4)
    # Where the table prints '---' (and MIL-H-83282 above 250 °F) the model refuses.
    with pytest.raises(covariate.CovariateError, match="Table 3-3 has no reliable value"):
        lam("seal-static", **{**STATIC, "fluid": "water", "T_O": 300, "T_R": 350})
    with pytest.raises(covariate.CovariateError, match="Table 3-3 has no reliable value"):
        lam("seal-static", **{**STATIC, "fluid": "mil_h_83282", "T_O": 300, "T_R": 350})


def test_contaminant_and_gasket_size_factors():
    # Table 3-4, p. 3-38: C_N = (C_o/10)³ · FR · N10; Figure 3.13, p. 3-32: C_DL = 0.45 L/w + 0.32.
    f = factors(lam("seal-static", **{**STATIC, "source": "gear_pump", "C_o": 20, "FR": 5}))
    assert f["C_N"] == pytest.approx(8 * 5 * 0.019)
    f = factors(lam("seal-static", **{**STATIC, "shape": "gasket", "D_SL": 0, "L": 40, "w": 4}))
    assert f["C_DL"] == pytest.approx(0.45 * 10 + 0.32)
    with pytest.raises(covariate.CovariateError, match="gasket needs"):
        lam("seal-static", **{**STATIC, "shape": "gasket"})


def test_dynamic_seal_switches_factors_at_800_rpm():
    common = dict(P1=1000, Q_f=0.05, D_SL=2, M=500, C=910, f=20, T_R=250, T_O=200, source="cylinder", FR=10)
    slow = lam("seal-dynamic", n=0, V_lin=100, **common)
    f = factors(slow)
    assert {"C_P", "C_DL", "C_H"} <= set(f) and "C_PV" not in f
    assert f["C_F"] == pytest.approx(2 ** (10 / 38))  # Figure 3.17, p. 3-36
    assert slow["modes"][0]["base"]["value"] == 22.8
    with pytest.raises(covariate.CovariateError, match="design PV"):
        lam("seal-dynamic", n=1800, V_lin=0, **common)
    fast = lam("seal-dynamic", n=1800, V_lin=0, PV_DS=200000, **common)
    f = factors(fast)
    assert not {"C_P", "C_DL", "C_H"} & set(f)
    pv = math.pi / 12 * (1000 - 14.7) * 2 * 1800 * 0.4  # Eq. 3-13, p. 3-21, balanced
    assert f["C_PV"] == pytest.approx(pv / 200000)


def test_mechanical_seal_model():
    out = lam("seal-mechanical", P1=500, Q_f=0.05, d=2, n=3600, f=8, T_R=400, T_O=300, source="piston_pump",
              FR=20, PV_DS=543000, balance="unbalanced")
    f = factors(out)
    assert list(f) == ["C_Q", "C_F", "C_ν", "C_T", "C_N", "C_PV"]
    assert f["C_PV"] == pytest.approx(math.pi / 12 * (500 - 14.7) * 2 * 3600 * 1.0 / 543000)
    assert f["C_T"] == 0.21 and f["C_F"] == 1.0
    assert out["total"] == pytest.approx(22.8 * math.prod(f.values()))
    assert out["unit"] == "per_million_hours"
    slow = lam("seal-mechanical", P1=500, Q_f=0.05, d=1, n=900, f=8, T_R=400, T_O=300, source="piston_pump",
               FR=20, PV_DS=543000)
    assert slow["warnings"] == []


def test_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError, match="Allowable leakage"):
        lam("seal-static", **{**STATIC, "Q_f": 0})
    out = lam("seal-static", **{**STATIC, "Q_f": 0.5, "M": 2000, "T_O": 320})
    words = " ".join(out["warnings"])
    assert "p. 3-30" in words and "p. 3-33" in words and "p. 3-35" in words
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("seal-static", P1=3000)
