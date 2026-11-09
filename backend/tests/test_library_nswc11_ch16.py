"""NSWC-11 Chapter 16, threaded fasteners: the models against the handbook's
tables and equations (pages cited). The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library


def lam(slug, **values):
    return covariate.evaluate(library.get(f"nswc-11:{slug}"), values, library.get)


def fs(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


BASE = dict(load="axial_high", thread_band="high", thread_form="rolled")


@pytest.mark.parametrize("grade, rate", [("sae_1", 0.260), ("sae_5_small", 0.101), ("sae_8", 0.072),
                                         ("iso_8_8", 0.101), ("a354_bc_large", 0.090), ("a490", 0.072)])
def test_base_rate_from_table_16_5(grade, rate):
    band = "low" if grade == "sae_1" else "high"
    out = lam("fastener", grade=grade, load="axial_high", thread_band=band, thread_form="rolled")
    assert out["modes"][0]["base"]["value"] == rate
    # Axial over 220 kpsi, 70 °F, light/normal: only C_K (rolled: 2.2 or 3.0) is not 1.
    assert out["total"] == pytest.approx(rate * (2.2 if band == "low" else 3.0))
    assert out["unit"] == "per_million_hours"


def test_factors_from_tables_16_6_to_16_8():
    out = lam("fastener", grade="sae_8", load="torsion_shear", impact="heavy", vibration="high",
              thread_band="high", thread_form="cut")
    f = fs(out)
    assert (f["C_L"], f["C_I"], f["C_K"], f["C_T"]) == (1.72, 2.50, 3.8, 1.0)
    assert out["total"] == pytest.approx(0.072 * 1.72 * 2.50 * 3.8)
    assert fs(lam("fastener", grade="sae_2_small", load="axial_low", thread_band="low", thread_form="cut"))["C_L"] \
        == 1.09


@pytest.mark.parametrize("T_O, c_t", [(160, 1.0), (100, 1.0), (300, 760 / 620), (800, 1260 / 620)])
def test_temperature_factor_eq_16_9(T_O, c_t):
    assert fs(lam("fastener", grade="sae_5_small", T_O=T_O, **BASE))["C_T"] == pytest.approx(c_t)


def test_size_factor_only_with_test_data_and_bending_or_torsion():
    # Eq. 16-7 (p. 16-14): C_SZ = (0.370 d / 0.3)^-0.1133 for bending or torsion; 1 for axial (Eq. 16-8);
    # and 1 whenever Table 16-5's grades give the base rate.
    f = fs(lam("fastener-test-data", lambda_FB=0.1, d=0.5, load="bending", thread_band="high", thread_form="rolled"))
    assert f["C_SZ"] == pytest.approx((0.370 * 0.5 / 0.3) ** -0.1133)
    assert f["C_SZ"] > 1  # a 1/2 in bolt is under the 0.81 in where the factor is 1
    f = fs(lam("fastener-test-data", lambda_FB=0.1, d=0.5, **BASE))
    assert "C_SZ" not in f
    assert "C_SZ" not in fs(lam("fastener", grade="sae_5_small", **{**BASE, "load": "bending"}))


def test_thread_band_must_match_an_sae_grade_and_limits_warn():
    with pytest.raises(covariate.CovariateError, match="SAE 8 is in Table 16-8's SAE grade 4-8 band"):
        lam("fastener", grade="sae_8", load="bending", thread_band="low", thread_form="rolled")
    # ISO and ASTM grades: the band is the user's call.
    assert lam("fastener", grade="iso_10_9", load="bending", thread_band="low", thread_form="rolled")["total"] > 0
    words = " ".join(lam("fastener-test-data", lambda_FB=0.1, d=2.5, T_O=900, **BASE)["warnings"])
    assert "p. 16-14" in words and "p. 16-16" in words
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("fastener", grade="sae_8")
