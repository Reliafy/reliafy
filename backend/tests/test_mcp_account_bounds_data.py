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
