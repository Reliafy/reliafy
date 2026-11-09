"""NSWC-11 Chapter 22, fluid conductors: pipe, tubing and hose against Eqs. 22-4 to
22-6, Tables 22-2, 22-4 and 22-6 and Figure 22.1 (pages cited). The chapter has no
worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library


def lam(slug, **values):
    return covariate.evaluate(library.get(f"nswc-11:{slug}"), values, library.get)


@pytest.mark.parametrize("env, printed", [("normal", 1.0), ("heavy", 1.2), ("severe", 1.4)])
def test_pipe_eq_22_4_and_table_22_2(env, printed):
    assert lam("pipe-assembly", environment=env)["total"] == pytest.approx(0.47 * printed)


@pytest.mark.parametrize("env, printed", [("normal", 1.0), ("heavy", 1.2), ("severe", 1.4)])
def test_tubing_eq_22_5_and_table_22_4(env, printed):
    assert lam("tubing-assembly", environment=env)["total"] == pytest.approx(1.33 * printed)


def test_rate_is_per_connection():
    # pp. 22-5, 22-8: the base rate is per connection; the count defaults to 1 (the equation as printed).
    assert lam("pipe-assembly", n_conn=6, environment="heavy")["total"] == pytest.approx(6 * 0.47 * 1.2)
    with pytest.raises(covariate.CovariateError):
        lam("tubing-assembly", n_conn=0)


@pytest.mark.parametrize("dT, read", [(60, 0.21), (40, 0.21), (18, 0.5), (0, 1.0), (-20, 2.2), (-36, 4.0),
                                      (-50, 6.9)])
def test_hose_temperature_factor_follows_figure_22_1(dT, read):
    # Figure 22.1, p. 22-13: 1/2^((T_R - T_O)/18), 0.21 above 40 °F; points read from the curve.
    out = lam("hose-assembly", T_R=200, T_O=200 - dT)
    c_t = out["modes"][0]["factors"][0]["value"]
    assert c_t == pytest.approx(read, rel=0.05)


def test_hose_eq_22_6_and_table_22_6():
    out = lam("hose-assembly", T_R=200, T_O=182, environment="severe")
    assert out["total"] == pytest.approx(1.85 * 0.5 * 1.5)  # severe hose duty is 1.5, not pipe's 1.4


def test_hose_over_its_rating_warns():
    out = lam("hose-assembly", T_R=150, T_O=210)
    words = " ".join(out["warnings"])
    assert "p. 22-13" in words and "p. 22-9" in words
