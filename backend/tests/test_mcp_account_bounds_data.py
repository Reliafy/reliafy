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


def _calls_used(db, uid, plan="free"):
    from backend.services import billing

    return billing.mcp_calls_used(db, uid, plan)


# ---- get_account (#133) ----------------------------------------------------------------------

def test_get_account_is_ungated_and_on_every_plan():
    from backend.mcp_server import PRO_ONLY_TOOLS, UNGATED_TOOLS

    assert "get_account" in UNGATED_TOOLS and "get_account" not in PRO_ONLY_TOOLS
    # The new data tools are ordinary: every plan, counted against the quota.
    assert not {"get_dataset", "update_model", "update_dataset"} & (PRO_ONLY_TOOLS | UNGATED_TOOLS)


def test_free_account_reports_calls_left_this_month_and_works_past_the_allowance(plans, monkeypatch):
    from backend import config
    from backend.services import billing

    now = {"t": datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(billing, "_now", lambda: now["t"])
    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 3)
    token = plans.oauth[FREE]
    _ok(_call(token, "save_model", {"name": "Bearing", "distribution": "weibull", "params": WEIBULL}))
    _ok(_call(token, "list_models"))

    out = _ok(_call(token, "get_account"))
    assert _calls_used(plans.db, FREE) == 2  # get_account isn't counted
    assert out["plan"] == "free" and out["plan_name"] == "Free" and out["operator"] is False
    assert out["grandfathered"] is False
    calls = out["tool_calls"]
    assert calls["unlimited"] is False and calls["period"] == "month"
    assert calls["used"] == 2 and calls["limit"] == 3 and calls["left"] == 1
    assert calls["resets_at"] == datetime(2026, 11, 1, tzinfo=timezone.utc).isoformat()
    assert calls["resets_on"] == "1 November 2026 (UTC)" and calls["resets_in"] == "29 days"
    assert out["storage"]["models"] == {"used": 1, "limit": config.FREE_MAX_MODELS}
    assert out["storage"]["datasets"] == {"used": 0, "limit": config.FREE_MAX_DATASETS}
    assert set(out["storage"]) == set(billing.CAPPED_KINDS)
    assert out["simulation_available"] is False
    assert "Reliafy Pro (US$19/month)" in out["upgrade"] and "Agent" not in out["upgrade"]
    assert "upgrade_link" in out["upgrade"] and "3 tool calls a month" in out["note"]

    _ok(_call(token, "list_models"))
    assert "this month's 3 free Reliafy tool calls" in _err(_call(token, "list_models"))
    out = _ok(_call(token, "get_account"))  # still answers once the allowance is used up
    assert out["tool_calls"]["used"] == 3 and out["tool_calls"]["left"] == 0
    assert _calls_used(plans.db, FREE) == 3

    # Next month: a fresh allowance.
    now["t"] = datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc)
    calls = _ok(_call(token, "get_account"))["tool_calls"]
    assert calls["used"] == 0 and calls["left"] == 3 and calls["resets_on"] == "1 December 2026 (UTC)"


def test_get_account_is_never_counted_and_is_logged_as_answered(plans, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 1)
    monkeypatch.setattr(config, "USAGE_LOGGING", True)
    token = plans.oauth[FREE]
    _ok(_call(token, "list_models"))
    for _ in range(3):
        _ok(_call(token, "get_account"))
    assert "upgrade_link" in _err(_call(token, "list_models"))  # the allowance is used up...
    assert _ok(_call(token, "get_account"))["tool_calls"]["left"] == 0  # ...and get_account still answers
    assert _calls_used(plans.db, FREE) == 1
    assert _calls_used(plans.db, FREE) == 1
    events = list(plans.db.usage_events.find({"uid": FREE, "channel": "mcp", "feature": "get_account"}))
    assert len(events) == 4 and {e["outcome"] for e in events} == {"ok"} and {e["plan"] for e in events} == {"free"}


def test_grandfathered_agent_account_shows_its_daily_quota_and_points_at_pro(plans):
    from backend import config
    from backend.services import billing

    out = _ok(_call(plans.oauth[AGENT], "get_account"))
    assert out["plan"] == "agent" and out["grandfathered"] is True
    calls = out["tool_calls"]
    assert calls["period"] == "day" and calls["limit"] == config.MCP_AGENT_DAILY_CALLS
    assert calls["resets_at"] == billing.next_day_start().isoformat() and "resets_on" not in calls
    assert re.fullmatch(r"(\d+ h )?\d+ min", calls["resets_in"])
    assert out["storage"]["rbds"]["limit"] == config.AGENT_MAX_RBDS
    assert "Reliafy Pro (US$19/month)" in out["upgrade"] and "Reliafy Agent (US$2" not in out["upgrade"]
    assert "retired" in out["note"]
    assert out["simulation_available"] is False
    billing.grant_credits(plans.db, AGENT, 500, "purchase")
    assert _ok(_call(plans.oauth[AGENT], "get_account"))["simulation_available"] is True


UNLIMITED_CALLS = {"unlimited": True, "period": None, "used": None, "limit": None, "left": None,
                   "resets_at": None, "resets_in": None}


def test_pro_and_operator_accounts_are_unlimited(plans, monkeypatch):
    from backend import config

    out = _ok(_call(plans.oauth[PRO], "get_account"))
    assert out["plan"] == "pro" and out["upgrade"] is None and out["simulation_available"] is True
    assert out["tool_calls"] == UNLIMITED_CALLS
    assert all(v["limit"] is None for v in out["storage"].values())

    monkeypatch.setattr(config, "ADMIN_EMAILS", {"free@example.org"})
    out = _ok(_call(plans.oauth[FREE], "get_account"))
    assert out["operator"] is True and out["upgrade"] is None and out["tool_calls"] == UNLIMITED_CALLS
    assert all(v["limit"] is None for v in out["storage"].values()) and "Operator" in out["note"]


def test_self_hosted_account_has_no_limits(env):
    out = _ok(_call(env.token[A], "get_account"))
    assert out["tool_calls"] == UNLIMITED_CALLS and out["upgrade"] is None
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


# ---- get_dataset (#135) ------------------------------------------------------------------------

def _upload(token, n=120, name="Run hours"):
    rows = "\n".join(f"{100 + i},{i % 2},{'' if i == 3 else 'site-' + str(i % 3)}" for i in range(n))
    return _ok(_call(token, "upload_dataset", {"name": name, "csv": f"hours,failed,site\n{rows}"}))


def test_get_dataset_pages_rows_with_typed_columns(env):
    ds = _upload(env.token[A])
    out = _ok(_call(env.token[A], "get_dataset", {"dataset_id": ds["id"]}))
    assert out["name"] == "Run hours" and out["row_count"] == 120 and out["is_sample"] is False
    assert out["columns"][:2] == [{"name": "hours", "dtype": "int64"}, {"name": "failed", "dtype": "int64"}]
    assert out["columns"][2]["name"] == "site" and out["columns"][2]["dtype"] in ("object", "str")  # pandas 2 / 3
    assert len(out["rows"]) == 50 and out["offset"] == 0 and out["next_offset"] == 50
    assert out["rows"][0] == [100, 0, "site-0"]
    assert out["rows"][3] == [103, 1, None]  # a blank cell is null

    last = _ok(_call(env.token[A], "get_dataset", {"dataset_id": ds["id"], "offset": 100, "limit": 50}))
    assert len(last["rows"]) == 20 and last["next_offset"] is None and last["rows"][-1][0] == 219

    big = _ok(_call(env.token[A], "get_dataset", {"dataset_id": ds["id"], "limit": 500}))
    assert len(big["rows"]) == 120 and big["next_offset"] is None

    past = _ok(_call(env.token[A], "get_dataset", {"dataset_id": ds["id"], "offset": 500}))
    assert past["rows"] == [] and "past the last row" in past["note"]


@pytest.mark.parametrize("args", [{"limit": 501}, {"limit": 0}, {"offset": -1}])
def test_get_dataset_limits(env, args):
    ds = _upload(env.token[A], n=5)
    _err(_call(env.token[A], "get_dataset", {"dataset_id": ds["id"], **args}))


def test_get_dataset_reads_samples_but_not_other_users_data(samples):
    out = _ok(_call(samples.token[A], "get_dataset", {"dataset_id": SAMPLE_DS, "limit": 5}))
    assert out["is_sample"] is True and len(out["rows"]) == 5 and out["row_count"] >= 5

    theirs = _upload(samples.token[B], n=5, name="B's data")
    assert _err(_call(samples.token[A], "get_dataset", {"dataset_id": theirs["id"]})).endswith("Dataset not found.")


# ---- update_model / update_dataset (#135) ------------------------------------------------------

def test_update_model_renames_and_annotates_without_touching_the_fit(env):
    token = env.token[A]
    saved = _saved_weibull(env)
    mid = saved["model_id"]
    before = _ok(_call(token, "get_model", {"model_id": mid}))

    out = _ok(_call(token, "update_model", {"model_id": mid, "name": "  Feed pumps  ",
                                             "notes": "Site B only; 2019-2024."}))
    assert out["updated"] == ["name", "notes"] and out["name"] == "Feed pumps" and out["kind"] == "life"
    after = _ok(_call(token, "get_model", {"model_id": mid}))
    assert after["name"] == "Feed pumps" and after["notes"] == "Site B only; 2019-2024."
    assert after["params"] == before["params"] and after["gof"] == before["gof"]

    out = _ok(_call(token, "update_model", {"model_id": mid, "notes": ""}))  # "" clears
    assert out["updated"] == ["notes"] and out["notes"] is None and out["name"] == "Feed pumps"
    assert "notes" not in _ok(_call(token, "get_model", {"model_id": mid}))


def test_update_model_handles_recurrent_models(samples):
    doc = samples.db.recurrent_models.find_one({"_id": SAMPLE_REC})
    samples.db.recurrent_models.insert_one({**doc, "_id": "rec-a", "id": "rec-a", "owner_id": A})
    out = _ok(_call(samples.token[A], "update_model", {"model_id": "rec-a", "name": "Compressors (mine)",
                                                        "notes": "copied"}))
    assert out["kind"] == "recurrent" and out["name"] == "Compressors (mine)"
    got = _ok(_call(samples.token[A], "get_model", {"model_id": "rec-a"}))
    assert got["name"] == "Compressors (mine)" and got["notes"] == "copied"


def test_update_refuses_samples_other_users_and_empty_changes(samples):
    a = samples.token[A]
    assert "shared sample model" in _err(_call(a, "update_model", {"model_id": BEARINGS, "name": "Mine"}))
    assert "shared sample model" in _err(_call(a, "update_model", {"model_id": SAMPLE_REC, "notes": "x"}))
    assert "shared sample dataset" in _err(_call(a, "update_dataset", {"dataset_id": SAMPLE_DS, "name": "Mine"}))
    assert samples.db.models.find_one({"_id": BEARINGS})["name"] != "Mine"

    theirs = _ok(_call(samples.token[B], "save_model", {"name": "B's", "distribution": "weibull", "params": WEIBULL}))
    their_ds = _upload(samples.token[B], n=5, name="B's data")
    assert _err(_call(a, "update_model", {"model_id": theirs["model_id"], "name": "x"})).endswith("Model not found.")
    assert _err(_call(a, "update_dataset", {"dataset_id": their_ds["id"], "name": "x"})).endswith("Dataset not found.")
    assert samples.db.models.find_one({"_id": theirs["model_id"]})["name"] == "B's"
    assert samples.db.datasets.find_one({"_id": their_ds["id"]})["name"] == "B's data"

    mine = _upload(a, n=5)
    assert "Nothing to change" in _err(_call(a, "update_dataset", {"dataset_id": mine["id"]}))
    assert "blank" in _err(_call(a, "update_dataset", {"dataset_id": mine["id"], "name": "   "}))
    _err(_call(a, "update_dataset", {"dataset_id": mine["id"], "notes": "x" * 5001}))


def test_update_dataset_renames_and_annotates_without_touching_the_data(env):
    token = env.token[A]
    ds = _upload(token, n=5)
    before = env.db.datasets.find_one({"_id": ds["id"]})
    out = _ok(_call(token, "update_dataset", {"dataset_id": ds["id"], "name": "Hours v2", "notes": "Cleaned."}))
    assert out["updated"] == ["name", "notes"] and out["dataset_id"] == ds["id"]
    assert out["name"] == "Hours v2" and out["notes"] == "Cleaned." and out["url"].endswith(f"/datasets/d/{ds['id']}")
    after = env.db.datasets.find_one({"_id": ds["id"]})
    assert after["data"] == before["data"] and after["checksum"] == before["checksum"]
    got = _ok(_call(token, "get_dataset", {"dataset_id": ds["id"]}))
    assert got["name"] == "Hours v2" and got["notes"] == "Cleaned."
    assert any(d["name"] == "Hours v2" for d in _ok(_call(token, "list_datasets"))["datasets"])

    _ok(_call(token, "update_dataset", {"dataset_id": ds["id"], "notes": ""}))
    assert "notes" not in _ok(_call(token, "get_dataset", {"dataset_id": ds["id"]}))


def test_data_tools_count_against_the_free_allowance(plans, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 3)
    token = plans.oauth[FREE]
    ds = _upload(token, n=5)
    _ok(_call(token, "get_dataset", {"dataset_id": ds["id"]}))
    _ok(_call(token, "update_dataset", {"dataset_id": ds["id"], "name": "Renamed"}))
    assert _calls_used(plans.db, FREE) == 3
    assert "this month's 3 free Reliafy tool calls" in _err(_call(token, "get_dataset", {"dataset_id": ds["id"]}))
