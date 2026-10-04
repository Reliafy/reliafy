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
    assert sel["criterion"] == "bic" and sel["include_mixtures"] is True
    assert r["distribution_id"] == "mixture" and r["mixture"] == 2
    assert r["base_distribution_id"] == "weibull"
    ids = [c["id"] for c in sel["candidates"]]
    assert ids[0] == "mixture:weibull" and "mixture:lognormal" in ids and "weibull" in ids
    assert [c["bic"] for c in sel["candidates"]] == sorted(c["bic"] for c in sel["candidates"])
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
    assert r["selection"]["criterion"] == "bic"
    assert any(c["id"] == "mixture:weibull" for c in r["selection"]["candidates"])


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
    assert out["distribution_id"] == "mixture" and out["selection"]["criterion"] == "bic"
    assert out["mixture_summary"].startswith("Two failure modes")
    assert "only" in _err(_call(env.token[A], "fit_distribution", {"distribution": "weibull", "data": data,
                                                                  "include_mixtures": True}))

