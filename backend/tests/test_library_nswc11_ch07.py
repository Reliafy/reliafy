"""NSWC-11 Chapter 7, bearings: the models against the handbook's own tables and
equations (pages cited)."""

import math

import pytest

from backend.library import covariate
from backend.library import service as library


def rec(slug):
    return library.get(f"nswc-11:{slug}")


def lam(slug, **values):
    return covariate.evaluate(rec(slug), values, library.get)


@pytest.mark.parametrize("R, printed", [(90, 1.00), (95, 1.62), (96, 1.88), (97, 2.29), (98, 3.01), (99, 4.79),
                                        (50, 0.29)])
def test_reliability_factor_reproduces_table_7_2(R, printed):
    # Table 7-2, p. 7-18: C_R = 0.223 / ln(100/R)^(2/3), printed to 2 decimals.
    out = lam("bearing-rolling-known-l10", L10h=10000, L_A=500, L_S=1000, R=R)
    c_r = next(f["value"] for f in out["modes"][0]["factors"] if f["symbol"] == "C_R")
    if R == 50:
        # The table prints 0.29 for L50, but its own footnote formula gives 0.2847 (0.28 to two
        # places). The model uses the formula; the table's L50 entry is a rounding slip.
        assert c_r == pytest.approx(0.2847, abs=5e-5) and abs(c_r - printed) < 0.01
    else:
        assert round(c_r, 2) == printed


def test_load_rating_model_is_one_over_l10_life_scaled():
    # Eq. 7-2 and 7-4: L10h = 10^6/(60 n) (L_S/L_A)^y; all factors 1 at R = 90 %, clean, cool, uniform.
    out = lam("bearing-rolling-load-rating", L_S=5000, F_R=1000, n=1800, R=90, contamination="extreme_clean")
    l10h = 1e6 / (60 * 1800) * 5 ** 3
    c_r = 0.223 / math.log(100 / 90) ** (2 / 3)  # 0.9997, not quite 1
    assert out["total"] == pytest.approx(1e6 / l10h * c_r)
    assert out["unit"] == "per_million_hours"


def test_roller_exponent_and_service_table():
    out = lam("bearing-rolling-load-rating", L_S=5000, F_R=1000, n=1800, R=90, contamination="extreme_clean",
              bearing_type="roller", service="vee_belt")
    assert out["total"] == pytest.approx(60 * 1800 * 0.2 ** 3.3 * 1.8 * 0.223 / math.log(100 / 90) ** (2 / 3))


def test_water_and_temperature_factors_follow_figures_7_4_and_7_5():
    base = dict(L10h=10000, L_A=1000, L_S=1000, R=90, contamination="extreme_clean")
    f = {x["symbol"]: x["value"] for x in lam("bearing-rolling-known-l10", CW=0.8, T_O=200, **base)["modes"][0]["factors"]}
    assert f["C_CW"] == pytest.approx(11.0)  # the two pieces of Eq. 7-7 meet at 0.8 %
    assert f["C_t"] == pytest.approx((200 / 183) ** 3)
    f = {x["symbol"]: x["value"] for x in lam("bearing-rolling-known-l10", CW=0.9, T_O=150, **base)["modes"][0]["factors"]}
    assert f["C_CW"] == 11.0 and f["C_t"] == 1.0


def test_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError) as err:
        lam("bearing-rolling-load-rating", L_S=5000, F_R=1000, n=0)
    assert "Operating speed" in str(err.value)
    out = lam("bearing-rolling-load-rating", L_S=1000, F_R=2000, n=100, T_O=300)
    words = " ".join(out["warnings"])
    assert "p. 7-17" in words and "p. 7-14" in words
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("bearing-rolling-load-rating", F_R=1000, n=100)


def test_service_factor_the_handbook_leaves_blank_is_refused():
    with pytest.raises(covariate.CovariateError, match="no value for this combination"):
        lam("bearing-rolling-load-rating", L_S=5000, F_R=1000, n=1800, bearing_type="roller",
            service="precision_gearing")
    assert math.isfinite(lam("bearing-rolling-load-rating", L_S=5000, F_R=1000, n=1800)["total"])
