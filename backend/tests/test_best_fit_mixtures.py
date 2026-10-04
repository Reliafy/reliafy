"""Best fit with two-mode mixtures competing (#236).

A mixture is ranked beside the single distributions only when its numbers
are on the same footing: the real observed-data log-likelihood on every kind
of row (``_mixture_log_likelihood``, held to SurPyval 0.23's own), and the
same BIC sample size (observed failures) as every other model. These tests
check both against the library, then the ranking against SurPyval's own
``fit_best(include=[..., MixtureModel(Weibull, 2)])``.
"""

import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting
from backend.fitting import FitError
from backend.tests.test_mcp import env  # noqa: F401 - a fixture


def _two_mode(seed=0, n_early=60, n_late=140):
    rng = np.random.default_rng(seed)
    x = np.concatenate([sp.Weibull.random(n_early, 100, 0.8, random_state=rng),
                        sp.Weibull.random(n_late, 1500, 3.5, random_state=rng)])
    return pd.DataFrame({"h": np.round(x, 3)})


def _one_mode(seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"h": np.round(sp.Weibull.random(300, 800, 1.7, random_state=rng), 3)})


def _rows(seed=0):
    rng = np.random.default_rng(seed)
    x = np.round(np.abs(np.concatenate([sp.Weibull.random(200, 300, 4.0, random_state=rng),
                                        sp.Weibull.random(200, 1500, 1.2, random_state=rng)])), 3)
    return x[x > 30]


@pytest.mark.parametrize("dist", [sp.Weibull, sp.LogNormal])
@pytest.mark.parametrize("kind", ["censored", "left_truncated", "right_truncated", "interval", "recast"])
def test_the_mixture_log_likelihood_is_surpyvals_on_every_kind_of_row(dist, kind):
    """The workaround agrees with SurPyval 0.23's ``log_likelihood`` on
    censored, truncated and interval data too, not just exact times (before
    #236 it read only exact / right / left rows and ignored truncation)."""
    x = _rows()
    c = np.where(x > 1800, 1, 0)
    c[:5] = -1
    data = {
        "censored": dict(x=np.minimum(x, 1800), c=c),
        "left_truncated": dict(x=x[x > 100], tl=100),
        "right_truncated": dict(x=x[x < 2000], tr=2000),
        "interval": dict(xl=np.floor(x / 100) * 100, xr=np.floor(x / 100) * 100 + 100),
        # A censored row with a finite truncation bound on its censored side
        # is an interval up to that bound (SurPyval #310).
        "recast": dict(x=np.minimum(x, 1800), c=c, tl=20, tr=5000),
    }[kind]
    raw = sp.MixtureModel(dist=dist, m=2)
    raw.fit(**data)
    assert fitting._mixture_log_likelihood(raw) == pytest.approx(raw.log_likelihood, rel=1e-9)


def test_a_mixture_fit_reports_surpyvals_criteria_on_censored_data():
    """BIC and AICc count the observed failures, as SurPyval does for every
    model — so a mixture's BIC is comparable with a single fit's."""
    x = _rows()
    c = np.where(x > 1500, 1, 0)
    df = pd.DataFrame({"h": np.minimum(x, 1500), "c": c})
    r = fitting.fit("mixture", df, {"x": "h", "c": "c"})
    raw = sp.MixtureModel(dist=sp.Weibull, m=2)
    raw.fit(x=np.minimum(x, 1500), c=c)
    gof = {g["id"]: g["value"] for g in r["gof"]}
    assert gof["log_likelihood"] == pytest.approx(raw.log_likelihood, rel=1e-6)
    assert gof["aic"] == pytest.approx(raw.aic(), rel=1e-6)
    assert gof["aic_c"] == pytest.approx(raw.aic_c(), rel=1e-6)
    assert gof["bic"] == pytest.approx(raw.bic(), rel=1e-6)


def test_best_fit_picks_a_mixture_for_two_modes_as_surpyval_does():
    df = _two_mode()
    r = fitting.fit("best", df, {"x": "h"}, unit="hours", options={"include_mixtures": True})
    sel = r["selection"]
    assert sel["criterion"] == "aic" and sel["mixture_criterion"] == "bic" and sel["include_mixtures"] is True
    assert r["distribution_id"] == "mixture" and r["mixture"] == 2
    assert r["base_distribution_id"] == "weibull"
    ids = [c["id"] for c in sel["candidates"]]
    assert ids[0] == "mixture:weibull" and "mixture:lognormal" in ids and "weibull" in ids
    # The winning mixture leads; the singles follow in their own (AIC) order, unchanged; then the
    # other mixture.
    off = [c["id"] for c in fitting.fit("best", df, {"x": "h"})["selection"]["candidates"]]
    assert ids == ["mixture:weibull", *off, "mixture:lognormal"]
    # BIC decided it: the mixture's beats the best single's.
    d = sel["decision"]
    best_single = sel["candidates"][1]
    assert d["mixture_wins"] is True and d["criterion"] == "bic"
    assert d["mixture"] == "mixture:weibull" and d["single"] == best_single["id"] == off[0]
    assert d["margin"] == pytest.approx(best_single["bic"] - sel["candidates"][0]["bic"]) and d["margin"] > 0
    # SurPyval's own fit_best, given the same candidates, agrees.
    theirs = sp.fit_best(df["h"].to_numpy(), metric="bic",
                         include=["Weibull", "LogNormal", sp.MixtureModel(sp.Weibull, 2)])
    assert isinstance(theirs, sp.MixtureModel)
    assert sel["candidates"][0]["bic"] == pytest.approx(theirs.bic(), rel=1e-6)
    single = next(c for c in sel["candidates"] if c["id"] == "weibull")
    assert single["bic"] == pytest.approx(sp.Weibull.fit(df["h"].to_numpy()).bic(), rel=1e-6)
    # In plain words, with the unit: about 30% early failures, the rest wear-out.
    words = r["mixture_summary"]
    assert words.startswith("Two failure modes: about 3")
    assert "early failures with β ≈ 0." in words and "the rest wear-out with β ≈ 3." in words
    assert "hours" in words and "split the data by failure mode" in words
    # The saved spec refits the mixture, not "best".
    assert r["options"] == {"mixture": 2, "mixture_distribution": "weibull"}


def test_best_fit_keeps_a_single_distribution_for_one_mode():
    r = fitting.fit("best", _one_mode(), {"x": "h"}, options={"include_mixtures": True})
    assert r["distribution_id"] != "mixture" and "mixture_summary" not in r
    assert r["selection"]["criterion"] == "aic" and r["selection"]["decision"]["mixture_wins"] is False
    assert any(c["id"] == "mixture:weibull" for c in r["selection"]["candidates"])


def _weibull_shape_two(seed=5):
    """One mode, Weibull with β = 2: AIC puts Weibull first, BIC would put
    Rayleigh (Weibull with β fixed at 2) first."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"h": np.round(sp.Weibull.random(40, 800, 2.0, random_state=rng), 3)})


def test_mixtures_on_leave_the_single_ranking_as_it_is_off():
    """#236: turning mixtures on no longer re-ranks the singles by BIC (the
    Rayleigh-over-Weibull flip): their order is the toggle-off order, and
    the mixtures follow it, each with its BIC."""
    df = _weibull_shape_two()
    off = fitting.fit("best", df, {"x": "h"})
    on = fitting.fit("best", df, {"x": "h"}, options={"include_mixtures": True})
    off_ids = [c["id"] for c in off["selection"]["candidates"]]
    singles = [c for c in on["selection"]["candidates"] if not c.get("mixture")]
    mixes = [c for c in on["selection"]["candidates"] if c.get("mixture")]
    assert off_ids[0] == "weibull"
    # BIC alone would have flipped it: the case this guards against.
    assert min(off["selection"]["candidates"], key=lambda c: c["bic"])["id"] == "rayleigh"
    assert [c["id"] for c in singles] == off_ids
    assert [c["aic"] for c in singles] == pytest.approx([c["aic"] for c in off["selection"]["candidates"]])
    assert on["distribution_id"] == off["distribution_id"] == "weibull"
    # Mixtures come after every single, by BIC, each with its BIC shown.
    assert [c["id"] for c in on["selection"]["candidates"]] == off_ids + [c["id"] for c in mixes]
    assert mixes and all(np.isfinite(c["bic"]) for c in mixes)
    assert [c["bic"] for c in mixes] == sorted(c["bic"] for c in mixes)
    assert on["selection"]["decision"]["mixture_wins"] is False
    assert on["selection"]["decision"]["single"] == "weibull"


def test_the_plain_words_name_the_criterion():
    two = fitting.fit("best", _two_mode(), {"x": "h"}, options={"include_mixtures": True})
    words = two["selection"]["summary"]
    margin = two["selection"]["decision"]["margin"]
    assert words.startswith(f"A two-mode mixture beats the best single distribution by {margin:,.1f} on BIC")
    assert "ranked by AIC" in words
    one = fitting.fit("best", _weibull_shape_two(), {"x": "h"}, options={"include_mixtures": True})
    words = one["selection"]["summary"]
    assert words.startswith("No two-mode mixture beats the best single distribution on BIC: Weibull, BIC ")
    assert "ranked by AIC, as without mixtures" in words
    # Without mixtures there's no decision to explain.
    assert "summary" not in fitting.fit("best", _one_mode(), {"x": "h"})["selection"]


def test_the_decision_on_its_own():
    singles = [{"id": "weibull", "name": "Weibull", "aic": 10.0, "bic": 14.0},
               {"id": "rayleigh", "name": "Rayleigh", "aic": 11.0, "bic": 12.0}]
    mixes = [{"id": "mixture:weibull", "name": "Weibull mixture (2 components)", "aic": 5.0, "bic": 13.0}]
    # Compared with the best single by AIC (Weibull), not the lowest single BIC.
    d = fitting.mixture_decision(singles, mixes)
    assert d["mixture_wins"] is True and d["margin"] == pytest.approx(1.0) and d["single"] == "weibull"
    assert fitting.mixture_decision(singles, [])["mixture_wins"] is False
    assert "No two-mode mixture could be fitted" in fitting.mixture_decision(singles, [])["summary"]
    d = fitting.mixture_decision([], mixes)
    assert d["mixture_wins"] is True and "No single distribution could be fitted" in d["summary"]


def test_mixtures_are_opt_in_and_off_by_default():
    r = fitting.fit("best", _two_mode(), {"x": "h"})
    assert r["selection"]["criterion"] == "aic" and "include_mixtures" not in r["selection"]
    assert not any(c.get("mixture") for c in r["selection"]["candidates"])
    assert r["distribution_id"] != "mixture"


def test_mixture_option_refusals():
    df = _two_mode()
    with pytest.raises(FitError, match="only in Best fit"):
        fitting.fit("weibull", df, {"x": "h"}, options={"include_mixtures": True})
    for extra, what in (({"offset": True}, "an offset"), ({"lfp": True}, "limited failure"),
                        ({"how": "MPP"}, "MPP")):
        with pytest.raises(FitError, match=what):
            fitting.fit("best", df, {"x": "h"}, options={"include_mixtures": True, **extra})


def test_form_options_carry_the_flag():
    assert fitting.options_from_form(include_mixtures="true") == {
        "offset": False, "zi": False, "lfp": False, "include_mixtures": True}
    assert fitting.options_from_form(include_mixtures="") is None


def test_api_fit_and_save_with_mixtures(monkeypatch):
    import io

    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    user = {"uid": "user-a", "email": "a@x.com", "name": "A", "email_verified": True}
    app.dependency_overrides[get_current_user] = lambda: user
    test_db.users.update_one({"_id": "user-a"}, {"$set": {"email": "a@x.com", "plan": "pro"}}, upsert=True)
    buf = io.StringIO()
    _two_mode().to_csv(buf, index=False)
    csv = buf.getvalue().encode()
    try:
        tc = TestClient(app)
        r = tc.post("/api/fit/best", data={"x": "h", "include_mixtures": "true"},
                    files={"file": ("d.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["distribution_id"] == "mixture" and r.json()["mixture_summary"]
        r = tc.post("/api/models", data={"name": "M", "distribution": "best", "x": "h", "include_mixtures": "true"},
                    files={"file": ("d.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        saved = test_db.models.find_one({"_id": r.json()["id"]})
        assert saved["spec"]["distribution_id"] == "mixture"
        assert saved["spec"]["options"] == {"mixture": 2, "mixture_distribution": "weibull"}
    finally:
        app.dependency_overrides.clear()


def test_mcp_fit_distribution_takes_include_mixtures(env):
    from backend.tests.test_mcp import A, _call, _err, _ok

    data = _two_mode()["h"].tolist()
    out = _ok(_call(env.token[A], "fit_distribution", {"distribution": "best", "data": data,
                                                       "include_mixtures": True, "unit": "hours"}))
    assert out["distribution_id"] == "mixture" and out["selection"]["mixture_criterion"] == "bic"
    assert out["mixture_summary"].startswith("Two failure modes")
    assert out["selection_summary"].startswith("A two-mode mixture beats the best single distribution by ")
    # One mode: the same rule — the singles' ranking as without mixtures.
    one = _weibull_shape_two()["h"].tolist()
    on = _ok(_call(env.token[A], "fit_distribution", {"distribution": "best", "data": one,
                                                      "include_mixtures": True}))
    off = _ok(_call(env.token[A], "fit_distribution", {"distribution": "best", "data": one}))
    assert on["distribution_id"] == off["distribution_id"] == "weibull"
    ids = [c["id"] for c in on["selection"]["candidates"] if not c.get("mixture")]
    assert ids == [c["id"] for c in off["selection"]["candidates"]]
    assert "on BIC" in on["selection_summary"] and "selection_summary" not in off
    assert "only" in _err(_call(env.token[A], "fit_distribution", {"distribution": "weibull", "data": data,
                                                                  "include_mixtures": True}))

