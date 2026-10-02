"""MCP: get_account (#133), confidence bounds in reliability_at (#134), and
get_dataset / update_model / update_dataset (#135).

Through the real /mcp mount, as test_mcp.py: ``env`` there is a self-hosted
install (billing off); ``plans`` below turns billing on with Free, Agent and
Pro users signed in over OAuth, as Claude's connector is.
"""

import matplotlib

matplotlib.use("Agg")

import re
from datetime import datetime, timezone

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval

from backend.tests.test_mcp import A, B, FLAGS, TIMES, _call, _err, _ok, env  # noqa: F401 - env is a fixture

BEARINGS = "sample-model-bearings-weibull"
SEAL_PH = "sample-model-seal-weibull-ph"
SAMPLE_DS = "sample-ds-bearings"
SAMPLE_REC = "sample-rec-compressors"
WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]

FREE, AGENT, PRO = "free-user", "agent-user", "pro-user"
PLAN_USERS = {
    FREE: {"_id": FREE, "email": "free@example.org", "name": "Free"},
    AGENT: {"_id": AGENT, "email": "agent@example.org", "name": "Agent", "plan": "agent"},
    PRO: {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro"},
}


@pytest.fixture()
def samples(env):
    from backend.services import samples as samples_service

    samples_service.seed_samples(env.db)
    return env


@pytest.fixture()
def plans(monkeypatch):
    """Billing on; Free / Agent / Pro users with OAuth access tokens."""
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import oauth as oauth_service

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://reliafy.com")
    test_db = mongomock.MongoClient()["reliafy_mcp_account_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    for u in PLAN_USERS.values():
        test_db.users.insert_one(dict(u))
    now = datetime.now(timezone.utc)

    class Env:
        db = test_db
        oauth = {uid: oauth_service._issue(
            test_db, family_id=f"fam-{uid}", uid=uid, client_id="https://claude.ai/test", client_name="Claude",
            scopes=["mcp"], res=oauth_service.resource(), grant_created_at=now)["access_token"] for uid in PLAN_USERS}

    return Env


def _calls_today(db, uid):
    from backend.services import billing

    return billing.mcp_calls_today(db, uid)


# ---- get_account (#133) ----------------------------------------------------------------------

def test_get_account_is_ungated_and_on_every_plan():
    from backend.mcp_server import PRO_ONLY_TOOLS, UNGATED_TOOLS

    assert "get_account" in UNGATED_TOOLS and "get_account" not in PRO_ONLY_TOOLS


def test_free_account_reports_calls_left_and_works_past_the_quota(plans, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "MCP_FREE_DAILY_CALLS", 3)
    token = plans.oauth[FREE]
    _ok(_call(token, "save_model", {"name": "Bearing", "distribution": "weibull", "params": WEIBULL}))
    _ok(_call(token, "list_models"))

    out = _ok(_call(token, "get_account"))
    assert _calls_today(plans.db, FREE) == 2  # get_account isn't counted
    assert out["plan"] == "free" and out["plan_name"] == "Free" and out["operator"] is False
    calls = out["tool_calls"]
    assert calls["used_today"] == 2 and calls["daily_limit"] == 3 and calls["left_today"] == 1
    assert calls["resets_at"] == billing.next_day_start().isoformat()
    assert re.fullmatch(r"(\d+ h )?\d+ min", calls["resets_in"])
    assert out["storage"]["models"] == {"used": 1, "limit": config.FREE_MAX_MODELS}
    assert out["storage"]["datasets"] == {"used": 0, "limit": config.FREE_MAX_DATASETS}
    assert set(out["storage"]) == set(billing.CAPPED_KINDS)
    assert out["simulation_available"] is False
    assert "Reliafy Agent (US$2/month, MCP) or Pro (US$19/month)" in out["upgrade"]
    assert "upgrade_link" in out["upgrade"]

    _ok(_call(token, "list_models"))
    assert "You've used all 3" in _err(_call(token, "list_models"))
    out = _ok(_call(token, "get_account"))  # still answers once the limit is hit
    assert out["tool_calls"]["used_today"] == 3 and out["tool_calls"]["left_today"] == 0
    assert _calls_today(plans.db, FREE) == 3


def test_agent_account_points_at_pro_and_counts_purchased_credits(plans):
    from backend import config
    from backend.services import billing

    out = _ok(_call(plans.oauth[AGENT], "get_account"))
    assert out["plan"] == "agent" and out["tool_calls"]["daily_limit"] == config.MCP_AGENT_DAILY_CALLS
    assert out["storage"]["rbds"]["limit"] == config.AGENT_MAX_RBDS
    assert "Reliafy Pro (US$19/month)" in out["upgrade"] and "Reliafy Agent (US$2" not in out["upgrade"]
    assert out["simulation_available"] is False
    billing.grant_credits(plans.db, AGENT, 500, "purchase")
    assert _ok(_call(plans.oauth[AGENT], "get_account"))["simulation_available"] is True


def test_pro_and_operator_accounts_are_unlimited(plans, monkeypatch):
    from backend import config

    out = _ok(_call(plans.oauth[PRO], "get_account"))
    assert out["plan"] == "pro" and out["upgrade"] is None and out["simulation_available"] is True
    assert out["tool_calls"] == {"used_today": None, "daily_limit": None, "left_today": None,
                                 "resets_at": None, "resets_in": None}
    assert all(v["limit"] is None for v in out["storage"].values())

    monkeypatch.setattr(config, "ADMIN_EMAILS", {"free@example.org"})
    out = _ok(_call(plans.oauth[FREE], "get_account"))
    assert out["operator"] is True and out["upgrade"] is None and out["tool_calls"]["daily_limit"] is None
    assert all(v["limit"] is None for v in out["storage"].values()) and "Operator" in out["note"]


def test_self_hosted_account_has_no_limits(env):
    out = _ok(_call(env.token[A], "get_account"))
    assert out["tool_calls"]["daily_limit"] is None and out["upgrade"] is None
    assert all(v["limit"] is None for v in out["storage"].values()) and "Self-hosted" in out["note"]


# ---- reliability_at confidence bounds (#134) ---------------------------------------------------

def _saved_weibull(env):
    return _ok(_call(env.token[A], "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "distribution": "weibull", "name": "Pumps", "unit": "hours"}))


def test_bounds_match_surpyval_exactly_at_the_requested_times(env):
    saved = _saved_weibull(env)
    times = [300.0, 1000.0, 2500.0, 1e5]  # 1e5 is far past the plot grid: still exact
    out = _ok(_call(env.token[A], "reliability_at", {"model_id": saved["model_id"], "times": times,
                                                     "confidence": 0.9}))
    ref = surpyval.Weibull.fit(x=TIMES, c=FLAGS)
    r_ref = ref.cb(np.array(times), on="sf", alpha_ci=0.1, bound="two-sided")
    f_ref = ref.cb(np.array(times), on="ff", alpha_ci=0.1, bound="two-sided")
    assert out["confidence"] == 0.9 and "Fisher-matrix" in out["bounds_note"]
    for i, p in enumerate(out["points"]):
        lo, hi = p["reliability_bounds"]
        assert lo == pytest.approx(r_ref[i][0], rel=1e-6, abs=1e-12)
        assert hi == pytest.approx(r_ref[i][1], rel=1e-6, abs=1e-12)
        assert p["failure_bounds"] == pytest.approx(list(f_ref[i]), rel=1e-6, abs=1e-12)
        assert lo <= p["reliability"] <= hi
        flo, fhi = p["failure_bounds"]
        assert flo <= p["failure"] <= fhi
        assert flo == pytest.approx(1 - hi, abs=1e-12) and fhi == pytest.approx(1 - lo, abs=1e-12)


def test_bounds_agree_with_the_apps_confidence_band(env):
    """The app's band endpoint and the MCP give the same numbers at the same times."""
    from backend.services import models as models_service

    saved = _saved_weibull(env)
    band = models_service.confidence(env.db, saved["model_id"], {"on": "sf", "alpha_ci": 0.05}, [A],
                                     x_min=250.0, x_max=2000.0)
    ends = [band["x"][0], band["x"][-1]]
    out = _ok(_call(env.token[A], "reliability_at", {"model_id": saved["model_id"], "times": ends,
                                                     "confidence": 0.95}))
    for i, j in ((0, 0), (1, -1)):
        assert out["points"][i]["reliability_bounds"] == pytest.approx(
            [band["lower"][j], band["upper"][j]], rel=1e-9)


def test_sample_model_with_data_has_bounds_and_no_confidence_means_no_bounds(samples):
    out = _ok(_call(samples.token[A], "reliability_at", {"model_id": BEARINGS, "times": [250],
                                                         "confidence": 0.95}))
    lo, hi = out["points"][0]["reliability_bounds"]
    assert 0 < lo < out["points"][0]["reliability"] < hi < 1

    plain = _ok(_call(samples.token[A], "reliability_at", {"model_id": BEARINGS, "times": [250]}))
    assert "reliability_bounds" not in plain["points"][0] and "bounds_note" not in plain


def test_ph_bounds_are_surpyvals_at_the_covariates_used(samples):
    from backend.services import models as models_service

    out = _ok(_call(samples.token[A], "reliability_at", {"model_id": SEAL_PH, "times": [1000, 5000],
                                                         "confidence": 0.9}))
    live = models_service.get_live_model(samples.db, SEAL_PH, None)["model"]
    Z = pd.DataFrame({k: [v] for k, v in out["covariates_used"].items()})
    ref = live.cb(np.array([1000.0, 5000.0]), Z, on="sf", alpha_ci=0.1, bound="two-sided")
    for i, p in enumerate(out["points"]):
        assert p["reliability_bounds"] == pytest.approx(list(ref[i]), rel=1e-9)
    assert "covariate values used" in out["bounds_note"]


def test_no_bounds_without_a_covariance_and_the_note_says_why(env):
    token = env.token[A]
    km = _ok(_call(token, "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "distribution": "kaplan_meier", "name": "KM"}))
    params_only = _ok(_call(token, "save_model", {"name": "From SurPyval", "distribution": "weibull",
                                                  "params": WEIBULL}))
    for model_id, why in ((km["model_id"], "non-parametric"), (params_only["model_id"], "parameters alone")):
        out = _ok(_call(token, "reliability_at", {"model_id": model_id, "times": [500, 900], "confidence": 0.95}))
        assert all(p["reliability_bounds"] is None and p["failure_bounds"] is None for p in out["points"])
        assert why in out["bounds_note"] and out["bounds_note"].startswith("No 95% bounds")
        assert out["points"][0]["reliability"] is not None  # the point values are still there


def test_mixture_has_no_bounds(env):
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    rng = np.random.default_rng(3)
    x = np.concatenate([rng.weibull(1.2, 40) * 100, rng.weibull(4.0, 40) * 1000])
    ds = datasets_service.create_dataset(env.db, "two modes", pd.DataFrame({"x": x}).to_csv(index=False).encode(), A)
    m = models_service.save_model(env.db, "Mixture", ds, "mixture", {"x": "x"}, [], None, "hours", A,
                                  options={"mixture": 2, "mixture_distribution": "weibull"})
    out = _ok(_call(env.token[A], "reliability_at", {"model_id": m.id, "times": [100], "confidence": 0.9}))
    assert out["points"][0]["reliability_bounds"] is None and "mixture" in out["bounds_note"]


def test_bounds_fail_closed_when_surpyval_cant_compute_them(env, monkeypatch):
    saved = _saved_weibull(env)

    def boom(*args, **kwargs):
        raise ValueError("Only MLE has confidence bounds")

    monkeypatch.setattr(surpyval.Weibull.fit(x=TIMES, c=FLAGS).__class__, "cb", boom)
    out = _ok(_call(env.token[A], "reliability_at", {"model_id": saved["model_id"], "times": [500],
                                                     "confidence": 0.9}))
    assert out["points"][0]["reliability_bounds"] is None
    assert "Only MLE has confidence bounds" in out["bounds_note"]


@pytest.mark.parametrize("bad", [0, 1, 1.5, -0.2])
def test_confidence_must_be_between_0_and_1(samples, bad):
    _err(_call(samples.token[A], "reliability_at", {"model_id": BEARINGS, "times": [250], "confidence": bad}))
