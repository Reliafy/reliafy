"""Mixture fits — several failure modes muddled into one dataset.

The load-bearing test here is the AIC one. SurPyval's ``MixtureModel.loglike``
is the EM objective, not the observed-data log-likelihood; deriving AIC from it
makes a mixture beat a single distribution even on single-mode data, which would
push every user toward a mixture they don't need. ``_mixture_log_likelihood``
computes the real thing, and the discrimination test below is what pins it.
"""

import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting
from backend.fitting import FitError


def _aic(result):
    return next(g["value"] for g in result["gof"] if str(g.get("label")) == "AIC")


def _two_mode(n=200, seed=0):
    rng = np.random.default_rng(seed)  # noqa: F841 - surpyval draws internally
    x = np.concatenate([sp.Weibull.random(n, 300, 4.0), sp.Weibull.random(n, 1500, 1.2)])
    return pd.DataFrame({"hours": np.round(np.abs(x), 3)})


def _one_mode(n=400):
    return pd.DataFrame({"hours": np.round(np.abs(sp.Weibull.random(n, 800, 1.7)), 3)})


def test_mixture_recovers_two_modes():
    r = fitting.fit("mixture", _two_mode(), {"x": "hours"})
    assert r["mixture"] == 2
    assert "mixture (2 components)" in r["distribution"]
    by = {p["name"]: p["value"] for p in r["params"]}
    assert set(by) == {"alpha1", "beta1", "weight1", "alpha2", "beta2", "weight2"}
    assert by["weight1"] + by["weight2"] == pytest.approx(1.0, abs=1e-6)
    # One short-life high-beta mode and one long-life low-beta mode, either order.
    alphas = sorted([by["alpha1"], by["alpha2"]])
    assert alphas[0] < 700 < alphas[1]


def test_aic_prefers_a_mixture_only_when_the_data_has_two_modes():
    """Both directions. If this passes with the EM objective substituted in, the
    test is not doing its job — the single-mode case is the one that catches it."""
    two = _two_mode()
    assert _aic(fitting.fit("mixture", two, {"x": "hours"})) \
        < _aic(fitting.fit("weibull", two, {"x": "hours"}))

    one = _one_mode()
    assert _aic(fitting.fit("mixture", one, {"x": "hours"})) \
        > _aic(fitting.fit("weibull", one, {"x": "hours"}))


def test_log_likelihood_is_the_observed_data_one_not_the_em_objective():
    df = _two_mode()
    r = fitting.fit("mixture", df, {"x": "hours"})
    ll = next(g["value"] for g in r["gof"] if "likelihood" in str(g.get("label")).lower())
    # Computed independently here: sum log sum_j w_j f_j(x).
    by = {p["name"]: p["value"] for p in r["params"]}
    x = df["hours"].to_numpy(float)
    dens = sum(by[f"weight{j}"] * np.ravel(sp.Weibull.df(x, by[f"alpha{j}"], by[f"beta{j}"]))
               for j in (1, 2))
    assert ll == pytest.approx(float(np.sum(np.log(dens))), rel=1e-6)


def test_curves_and_plot_survive_the_missing_pieces():
    """A mixture has no qf, no hf and no covariance. B-life must still work
    (numeric inversion), the hazard must still plot (f/R), and the probability
    plot must render without a confidence band rather than failing."""
    r = fitting.fit("mixture", _two_mode(), {"x": "hours"}, unit="hours")
    curves = r["functions"]["curves"]
    sf = [v for v in curves["sf"] if v is not None]
    assert sf and all(a >= b - 1e-9 for a, b in zip(sf, sf[1:]))   # monotone
    assert max(sf) <= 1.0 + 1e-9 and min(sf) >= -1e-9
    assert any(v is not None for v in curves["hf"])                 # derived f/R
    assert r["plot"]["bounds"] is None                              # no covariance
    assert len(r["plot"]["scatter"]["x"]) > 0


def test_censoring_is_carried_into_the_likelihood():
    df = _two_mode()
    df["cens"] = 0
    df.loc[df.index[-60:], "cens"] = 1
    r = fitting.fit("mixture", df, {"x": "hours", "c": "cens"})
    assert r["mixture"] == 2 and r["n"] == len(df)
    # Censored observations contribute survival, not density, so the likelihood
    # differs from treating them all as failures.
    plain = fitting.fit("mixture", df, {"x": "hours"})
    lab = "Log-likelihood"
    assert next(g["value"] for g in r["gof"] if g["label"] == lab) != \
        pytest.approx(next(g["value"] for g in plain["gof"] if g["label"] == lab))


def test_saved_spec_round_trips():
    """save_model persists result["options"]; without the echo a reopened
    mixture would silently refit as a single distribution."""
    df = _two_mode()
    r = fitting.fit("mixture", df, {"x": "hours"}, options={"mixture": 3})
    assert r["options"] == {"mixture": 3, "mixture_distribution": "weibull"}
    again = fitting.fit(r["distribution_id"], df, {"x": "hours"}, options=r["options"])
    assert again["mixture"] == 3


def test_rejected_combinations():
    df = _two_mode()
    for opts, expect in (
        ({"offset": True}, "can't be combined"),
        ({"lfp": True}, "can't be combined"),
        ({"fixed": {"beta": 2}}, "can't be combined"),
        ({"mixture": 99}, "At most"),
        ({"mixture": "two"}, "whole number"),
    ):
        with pytest.raises(FitError) as e:
            fitting.fit("mixture", df, {"x": "hours"}, options=opts)
        assert expect in str(e.value)

    # Mixture settings are meaningless without the Mixture model selected.
    with pytest.raises(FitError, match="only apply to the Mixture model"):
        fitting.fit("weibull", df, {"x": "hours"}, options={"mixture": 2})
    with pytest.raises(FitError, match="only apply to the Mixture model"):
        fitting.fit("best", df, {"x": "hours"}, options={"mixture_distribution": "weibull"})
    with pytest.raises(FitError, match="can't be mixed"):
        fitting.fit("mixture", df, {"x": "hours"},
                    options={"mixture_distribution": "kaplan_meier"})


def test_defaults_are_two_weibull_components():
    df = _two_mode()
    assert fitting.normalize_options(fitting.MIXTURE_ID, None) == {
        "mixture": 2, "mixture_distribution": "weibull"}
    r = fitting.fit(fitting.MIXTURE_ID, df, {"x": "hours"})
    assert r["mixture"] == 2 and r["base_distribution_id"] == "weibull"


def test_the_picker_offers_every_mixable_distribution():
    """One Mixture entry lists which distributions can be mixed, so that list
    and the fitting registry must agree."""
    from backend.main import distributions_endpoint

    entry = next(d for d in distributions_endpoint()["distributions"] if d.get("mixture"))
    assert entry["id"] == fitting.MIXTURE_ID
    assert {d["id"] for d in entry["mixture_distributions"]} == set(fitting.DISTRIBUTIONS)


@pytest.mark.parametrize("dist", ["weibull", "lognormal", "normal", "gamma"])
def test_mixtures_work_across_the_paper_transforms(dist):
    """Each distribution draws on its own probability paper; the transform must
    tolerate a mixture's longer parameter vector."""
    r = fitting.fit("mixture", _two_mode(n=120), {"x": "hours"},
                    options={"mixture_distribution": dist})
    assert r["mixture"] == 2
    assert len(r["plot"]["scatter"]["x"]) > 0
