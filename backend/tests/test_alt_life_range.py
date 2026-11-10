"""The range on the life at the use stress of an accelerated life model: the
most extrapolated number on the page, so it carries its interval.

Wald: the delta method on the log of the life, from the fit's covariance of
the life-stress coefficients. Here it is checked against the same variance
written out by hand for two life-stress models whose log life is linear in
the coefficients, and the other two methods against SurPyval's own bound on
the quantile that is the characteristic life.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest
import surpyval as sp
from scipy.stats import norm

from backend import alt

USE = [323.0]
Z95 = float(norm.ppf(0.975))


def _thermal(seed=1, n_per=24, cutoff=5000.0):
    """Units at three temperatures (K), Arrhenius-Weibull, stopped at
    ``cutoff`` hours."""
    rng = np.random.default_rng(seed)
    T = np.repeat([350.0, 375.0, 400.0], n_per)
    x = np.exp(-12 + 7000 / T) * rng.weibull(2.5, T.size)
    return pd.DataFrame({"hours": np.minimum(x, cutoff), "tempK": T, "cens": (x > cutoff).astype(int)})


def _voltage(seed=3, n_per=15):
    """Units at three voltages, inverse power law, exponential lives."""
    rng = np.random.default_rng(seed)
    V = np.repeat([30.0, 36.0, 42.0], n_per)
    return pd.DataFrame({"minutes": rng.exponential(1.0 / (2e-12 * V ** 6.0)), "kV": V})


def _fit(df=None, distribution="weibull", life_model="arrhenius"):
    df = _thermal() if df is None else df
    mapping = {"x": "hours", "c": "cens"} if "hours" in df else {"x": "minutes"}
    _, cid = alt.fit(df, mapping, ["tempK" if "tempK" in df else "kV"], distribution, life_model)
    return alt.get_live(cid)


def _coefficient_cov(model, *names):
    idx = [list(model.parameter_names).index(n) for n in names]
    return np.asarray(model.covariance(), dtype=float)[np.ix_(idx, idx)]


def _value(model, name):
    return float(np.asarray(model.params, dtype=float)[list(model.parameter_names).index(name)])


def test_wald_range_is_the_delta_method_written_by_hand_arrhenius():
    # Arrhenius: life = b·exp(a / T), so ln(life) = ln b + a / T: linear in
    # (a, ln b). Its gradient in (a, b) is (1 / T, 1 / b).
    m = _fit()
    b = alt.use_level_bounds(m, USE, "arrhenius")
    life = _value(m, "b") * math.exp(_value(m, "a") / USE[0])
    assert b["characteristic_life"]["value"] == pytest.approx(life, rel=1e-9)
    g = np.array([1.0 / USE[0], 1.0 / _value(m, "b")])
    se = math.sqrt(float(g @ _coefficient_cov(m, "a", "b") @ g))
    by_hand = [life * math.exp(-Z95 * se), life * math.exp(Z95 * se)]
    assert b["characteristic_life"]["ci"] == pytest.approx(by_hand, rel=1e-6)
    assert b["confidence"] == 0.95 and b["method"] == "wald"
    assert "note" not in b["characteristic_life"]


def test_wald_range_is_the_delta_method_written_by_hand_inverse_power():
    # Inverse power law: life = 1 / (a·V^n), so ln(life) = -ln a - n·ln V.
    # Its gradient in (a, n) is (-1 / a, -ln V). Exponential lives: the life
    # is the mean time to failure.
    m = _fit(_voltage(), "exponential", "inverse_power")
    use = [20.0]
    b = alt.use_level_bounds(m, use, "inverse_power", confidence=0.9)
    life = 1.0 / (_value(m, "a") * use[0] ** _value(m, "n"))
    assert b["characteristic_life"]["value"] == pytest.approx(life, rel=1e-9)
    g = np.array([-1.0 / _value(m, "a"), -math.log(use[0])])
    se = math.sqrt(float(g @ _coefficient_cov(m, "a", "n") @ g))
    z = float(norm.ppf(0.95))
    by_hand = [life * math.exp(-z * se), life * math.exp(z * se)]
    assert b["characteristic_life"]["ci"] == pytest.approx(by_hand, rel=1e-6)


@pytest.mark.parametrize("distribution", list(alt.ALT_DISTRIBUTIONS))
@pytest.mark.parametrize("life_model", ["arrhenius", "eyring", "inverse_power", "linear"])
def test_range_holds_the_estimate_and_stays_positive(distribution, life_model):
    m = _fit(distribution=distribution, life_model=life_model)
    ev = alt.evaluate(m, [340.0], life_model)
    json.dumps(ev)
    row = ev["bounds"]["characteristic_life"]
    life = ev["metrics"]["characteristic_life"]
    assert row["value"] == life
    lower, upper = row["ci"]
    assert 0 < lower < life < upper and math.isfinite(upper)
    # On the log scale: the estimate is the geometric middle of the range.
    assert math.sqrt(lower * upper) == pytest.approx(life, rel=1e-9)


def test_range_narrows_with_more_data_and_with_less_confidence():
    def width(n_per, confidence=0.95):
        lower, upper = alt.use_level_bounds(_fit(_thermal(n_per=n_per)), USE, "arrhenius",
                                            confidence=confidence)["characteristic_life"]["ci"]
        return upper / lower

    small, large = width(12), width(96)
    assert 1 < large < small
    # Eight times the units: the log-width shrinks by about sqrt(8).
    assert math.log(small) / math.log(large) == pytest.approx(math.sqrt(8), rel=0.35)
    assert width(24, 0.8) < width(24, 0.95)


def test_range_widens_the_further_the_use_stress_is_from_the_test():
    m = _fit()
    widths = []
    for use in (350.0, 323.0, 298.0):
        lower, upper = alt.use_level_bounds(m, [use], "arrhenius")["characteristic_life"]["ci"]
        widths.append(upper / lower)
    assert widths[0] < widths[1] < widths[2]


@pytest.mark.parametrize("distribution, name, p", [("weibull", "Weibull", 1 - math.exp(-1)),
                                                    ("lognormal", "LogNormal", 0.5)])
def test_likelihood_ratio_range_is_surpyvals_bound_on_that_quantile(distribution, name, p):
    m = _fit(distribution=distribution)
    assert m.distribution.name == name
    b = alt.use_level_bounds(m, USE, "arrhenius", method="lr", confidence=0.9)
    row = b["characteristic_life"]
    # The quantile at p is the characteristic life itself ...
    assert float(np.ravel(m.qf(p, [USE]))[0]) == pytest.approx(row["value"], rel=1e-9)
    # ... so its two-sided bound is the life's.
    ref = np.ravel(m.quantile_cb([p], [USE], alpha_ci=0.1, bound="two-sided", method="lr"))
    assert row["ci"] == pytest.approx(ref.tolist(), rel=1e-6)
    assert row["ci"][0] < row["value"] < row["ci"][1]
    # The two methods agree roughly with this much data (71 failures).
    wald = alt.use_level_bounds(m, USE, "arrhenius", confidence=0.9)["characteristic_life"]["ci"]
    assert row["ci"] == pytest.approx(wald, rel=0.1)


def test_bootstrap_range_shares_the_seeded_refits():
    m = _fit()
    b = alt.use_level_bounds(m, USE, "arrhenius", method="bootstrap", n_boot=100, seed=7)
    ref = np.ravel(m.quantile_cb([1 - math.exp(-1)], [USE], bound="two-sided", method="bootstrap",
                                 n_boot=100, random_state=7))
    assert b["characteristic_life"]["ci"] == pytest.approx(ref.tolist(), rel=1e-9)
    # The B-lives are what they were without it.
    q = m.quantile_cb([0.1, 0.01], [USE], bound="lower", method="bootstrap", n_boot=100, random_state=7)
    assert [b["b_lives"]["b10"]["lower"], b["b_lives"]["b1"]["lower"]] == pytest.approx(q.tolist(), rel=1e-9)


def test_no_range_is_null_with_the_reason_never_invented(monkeypatch):
    # A gamma's characteristic life is no fixed quantile: Wald only.
    gamma = _fit(distribution="gamma")
    row = alt.use_level_bounds(gamma, USE, "arrhenius", method="lr")["characteristic_life"]
    assert row["ci"] is None and row["value"] > 0
    assert row["note"] == ("No range on the life at the use stress: the likelihood-ratio method has none for "
                           "this distribution. The Wald method gives one.")
    assert alt.use_level_bounds(gamma, USE, "arrhenius")["characteristic_life"]["ci"] is not None

    # A straight-line life model run on to where the life isn't positive.
    linear = _fit(distribution="normal", life_model="linear")
    row = alt.use_level_bounds(linear, [600.0], "linear")["characteristic_life"]
    assert row["value"] < 0 and row["ci"] is None and "isn't a positive number" in row["note"]

    # No covariance (or one that isn't finite): no range, the estimate as it was.
    m = _fit()
    before = alt.use_level_bounds(m, USE, "arrhenius")["characteristic_life"]
    for broken in (lambda: (_ for _ in ()).throw(RuntimeError("no covariance")),
                   lambda: np.full((4, 4), np.nan)):
        monkeypatch.setattr(m, "covariance", broken)
        ci, note = alt.life_at_use_interval(m, np.array([USE]), before["value"], 0.95)
        assert ci is None and "no usable covariance" in note
    monkeypatch.undo()
    ci, note = alt.life_at_use_interval(m, np.array([USE]), float("nan"), 0.95)
    assert ci is None and note


def test_a_saved_model_gives_the_same_range_and_no_other_number_moves():
    df = _thermal()
    _, cid = alt.fit(df, {"x": "hours", "c": "cens"}, ["tempK"], "weibull", "arrhenius", "hours")
    live = alt.get_live(cid)
    ev = alt.evaluate(live, USE, "arrhenius", ref_stress=[400.0], mission_time=2000.0)
    # A model opened again from its saved form keeps no data, only its covariance.
    restored = alt.get_live(alt.restore_live(alt.serialize_live(cid)))
    again = alt.evaluate(restored, USE, "arrhenius", ref_stress=[400.0], mission_time=2000.0)
    assert again["bounds"]["characteristic_life"]["ci"] == pytest.approx(
        ev["bounds"]["characteristic_life"]["ci"], rel=1e-6)

    # The estimates and the other bounds are SurPyval's, as before.
    direct = sp.AcceleratedLife(sp.Weibull, alt._LM["Exponential"]).fit(
        x=df["hours"].to_numpy(float), Z=df[["tempK"]].to_numpy(float), c=df["cens"].to_numpy(int))
    Z = np.array([USE])
    assert ev["metrics"]["characteristic_life"] == pytest.approx(float(np.ravel(direct.phi(Z))[0]), rel=1e-9)
    assert ev["metrics"]["b10"] == pytest.approx(float(np.ravel(direct.qf(0.1, Z))[0]), rel=1e-9)
    b = ev["bounds"]
    assert set(b) == {"method", "method_name", "confidence", "use_stress", "band", "b_lives", "mission",
                      "coefficients", "characteristic_life", "warnings", "note"}
    q = direct.quantile_cb([0.1, 0.01], Z, bound="lower")
    assert [b["b_lives"]["b10"]["lower"], b["b_lives"]["b1"]["lower"]] == pytest.approx(q.tolist(), rel=1e-6)
    band = direct.cb(np.asarray(b["band"]["x"]), Z, on="sf")
    np.testing.assert_allclose(b["band"]["lower"], band[:, 0], rtol=1e-6)
    assert b["mission"]["lower"] == pytest.approx(
        float(np.ravel(direct.cb([2000.0], Z, on="sf", bound="lower"))[0]), rel=1e-6)
    assert set(ev["metrics"]) == {"characteristic_life", "mean_life", "b50", "b10", "b1", "mission_time",
                                  "mission_reliability"}
