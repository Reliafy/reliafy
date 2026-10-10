"""MCP is part of Reliafy Pro; Free gets a small monthly allowance; the
retired Agent plan is grandfathered.

A Free OAuth user connects, lists the tools and has 20 tool calls a month
(every tool except fitting, fleets and simulation); past them each call says
when they reset, and ``upgrade_link`` (never counted) offers only Pro. Pro (and operators, and self-hosted installs) has every tool with no
quota. ``rlf_`` API tokens stay Pro-only. A subscriber to the retired Agent
plan (US$2/month, MCP only) keeps what they had until the subscription ends:
the tools except fitting and fleets, a daily tool-call quota and the Agent
storage caps. On the Stripe side the Agent plan can't be bought any more,
while an existing Agent subscription's webhook events still work.

MCP calls go through the real ``/mcp`` mount (as in test_mcp.py); Stripe is a
fake module swapped in for ``routers.billing._stripe`` — nothing leaves the
process.
"""

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import mongomock
import pytest
import surpyval
from fastapi.testclient import TestClient

from backend.tests.test_mcp import REPAIRABLE_STAGES, _err, _ok, _run

BASE = "https://reliafy.com"
FREE, AGENT, PRO = "free-user", "agent-user", "pro-user"
USERS = {
    FREE: {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
    AGENT: {"_id": AGENT, "email": "agent@example.org", "name": "Agent", "plan": "agent", "email_verified": True},
    PRO: {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro", "email_verified": True},
}
UPGRADE = "upgrade to Reliafy Pro (US$19/month)"
WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
N_TOOLS = 55


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import oauth as oauth_service
    from backend.services import rbd_analysis, tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", BASE)
    monkeypatch.setattr(rbd_analysis, "_AVAIL_SIMS", 20)  # keep the suite quick
    test_db = mongomock.MongoClient()["reliafy_mcp_plans_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    for u in USERS.values():
        test_db.users.insert_one(dict(u))

    # Count real availability simulations (not the exact, simulate=False, analyses).
    sims = {"n": 0}
    real = rbd_analysis.analyze_availability

    def spy(*args, **kwargs):
        if kwargs.get("simulate", True):
            sims["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rbd_analysis, "analyze_availability", spy)

    def oauth_token(uid):
        """An access token as Claude's connector would hold after sign-in."""
        now = datetime.now(timezone.utc)
        return oauth_service._issue(
            test_db, family_id=f"fam-{uid}", uid=uid, client_id="https://claude.ai/test", client_name="Claude",
            scopes=["mcp"], res=oauth_service.resource(), grant_created_at=now)["access_token"]

    class Env:
        db = test_db
        oauth = {uid: oauth_token(uid) for uid in USERS}
        api = {uid: tokens.create_token(test_db, uid, "mcp")["token"] for uid in USERS}
        simulations = sims

    return Env


def _call(token, name, args=None):
    async def fn(client):
        return await client.call_tool(name, args or {})

    return _run(token, fn)


def _calls_today(db, uid):
    from backend.services import billing

    return billing.mcp_calls_today(db, uid)


def _calls_used(db, uid, plan="free"):
    from backend.services import billing

    return billing.mcp_calls_used(db, uid, plan)


def _post_mcp(token):
    """A raw tools/list POST to /mcp, with the session manager running."""
    from backend.tests.test_mcp_oauth import _post_mcp as post

    return post(None, token)


# ---- Free: a small monthly allowance to try it --------------------------------------------

FIT_ARGS = {"data": [120, 340, 510, 700, 980]}
FREE_PRO_ONLY = "part of Reliafy Pro (US$19/month)"


def test_free_user_tries_every_tool_but_the_pro_only_ones_within_the_allowance(env):
    from backend import config
    from backend.services import billing

    assert config.MCP_FREE_MONTHLY_CALLS == 20
    assert billing.mcp_quota("free") == (20, "month") and billing.mcp_quota("pro") == (None, None)
    token = env.oauth[FREE]
    assert _post_mcp(token).status_code == 200  # connecting works
    tools = {t.name for t in _run(token, lambda c: c.list_tools()).tools}
    assert len(tools) == N_TOOLS and {"upgrade_link", "list_models", "save_model"} <= tools

    assert "life_models" in _ok(_call(token, "list_models"))
    assert _ok(_call(token, "save_model", {"name": "Bearing", "distribution": "weibull", "params": WEIBULL}))["saved"]
    assert _ok(_call(token, "optimal_replacement", {
        "distribution_id": "weibull", "params": WEIBULL, "planned_cost": 100, "unplanned_cost": 1000}))
    assert _ok(_call(token, "upload_dataset", {"name": "d", "csv": "t,c\n1,0\n2,0\n"}))["id"]
    assert _ok(_call(token, "plan_demonstration_test", {"reliability": 0.95}))["units"] == 59
    assert _calls_used(env.db, FREE) == 5

    # Fitting and fleets are Pro-only: refused, and refusals aren't counted.
    for name, args in [("fit_distribution", FIT_ARGS),
                       ("fit_and_save_model", {"name": "x", **FIT_ARGS}),
                       ("fit_alt_model", {"name": "x", "data": [120, 340], "stresses": [[350], [400]]}),
                       ("list_fleets", {}),
                       ("create_fleet_alert", {"fleet_id": "nope", "kind": "above", "threshold": 1})]:
        msg = _err(_call(token, name, args))
        assert FREE_PRO_ONLY in msg and f"{BASE}/billing" in msg and "upgrade_link" in msg, name
    assert "SurPyval" in _err(_call(token, "fit_distribution", FIT_ARGS))
    assert _calls_used(env.db, FREE) == 5
    assert env.db.models.count_documents({"owner_id": FREE, "dataset_id": {"$ne": ""}}) == 0


def test_free_user_gets_the_exact_figures_but_no_simulations(env):
    rid = _repairable(env, FREE, "Pumps")
    assert _calls_used(env.db, FREE) == 1
    out = _ok(_call(env.oauth[FREE], "analyze_rbd", {"rbd_id": rid}))
    # The exact figures (#154) on the Free plan, within the allowance...
    assert out["available"] is True and out["has_simulation"] is False
    exact = out["exact"]
    assert exact["status"] == "ok" and exact["method"]["mission_availability"] in ("exact", "numerical")
    assert 0 < exact["mission_availability"] <= 1 and exact["expected_failures"] > 0
    assert len(exact["curve"]) == 21 and exact["routes"]["availability"]["route"] == "simulated"
    # ...the simulation refused, with the way forward.
    sim = out["simulation"]
    assert sim["available"] is False and sim["code"] == "pro_required"
    assert "isn't included on the Free plan" in sim["message"] and "export_rbd_python" in sim["message"]
    assert env.simulations["n"] == 0
    assert _calls_used(env.db, FREE) == 2  # an answer, so it counts


def test_free_user_simulation_only_diagram_is_refused_and_not_counted(env):
    """No exact figures at all (one repair crew for wear-out lives): as before #154."""
    rid = _repairable(env, FREE, "Pumps")
    doc = env.db.rbds.find_one({"_id": rid})
    graph = doc["graph"]
    graph["repair_crews"] = {"crews": 1}
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": graph}})
    out = _ok(_call(env.oauth[FREE], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is False and out["code"] == "pro_required"
    assert "isn't included on the Free plan" in out["message"]
    assert env.simulations["n"] == 0
    assert _calls_used(env.db, FREE) == 1


def test_free_user_current_state(env):
    rid = _repairable(env, FREE, "Pumps")
    graph = env.db.rbds.find_one({"_id": rid})["graph"]
    ids = [n["id"] for n in graph["nodes"] if n["type"] == "component"]
    new = _ok(_call(env.oauth[FREE], "analyze_rbd", {"rbd_id": rid, "t_max": 100}))["exact"]
    now = _ok(_call(env.oauth[FREE], "analyze_rbd", {
        "rbd_id": rid, "t_max": 100, "current_state": {ids[0]: {"down": True, "since": 0.5}}}))
    assert now["current_state"] == {ids[0]: {"down": True, "since": 0.5}}
    assert now["exact"]["from"] == "now" and new["from"] == "new"
    assert now["exact"]["mission_availability"] < new["mission_availability"]
    msg = _err(_call(env.oauth[FREE], "analyze_rbd", {
        "rbd_id": rid, "current_state": {"nope": {"age": 3}}}))
    assert "isn't a component block" in msg
    assert "availability_cache" not in env.db.rbds.find_one({"_id": rid})


def test_free_user_shares_a_protected_link_within_the_allowance(env):
    """Share links (#125) are on every plan and count like any other call."""
    token = env.oauth[FREE]
    rbd = _ok(_call(token, "create_rbd", {"name": "Skid", "stages": REPAIRABLE_STAGES}))
    before = _calls_used(env.db, FREE)
    out = _ok(_call(token, "share_link", {"kind": "rbd", "id": rbd["id"], "password": True,
                                          "expires_in_days": 30}))
    assert out["url"].startswith(f"{BASE}/p/") and out["passphrase"] and out["protected"] is True
    assert _ok(_call(token, "list_share_links", {}))["count"] == 1
    _ok(_call(token, "revoke_share_link", {"token": out["token"]}))
    assert _calls_used(env.db, FREE) == before + 3


def test_free_allowance_is_per_calendar_month(env, monkeypatch):
    from backend.services import billing

    now = {"t": datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(billing, "_now", lambda: now["t"])
    token = env.oauth[FREE]
    for _ in range(20):
        _ok(_call(token, "list_rbds"))
    msg = _err(_call(token, "list_rbds"))  # the 21st
    assert ("You've used this month's 20 free Reliafy tool calls. They reset on 1 November "
            "(UTC) — in 29 days. ") in msg
    assert ("Using Reliafy from AI agents without a limit is part of Reliafy Pro (US$19/month) — upgrade at "
            f"{BASE}/billing, or call upgrade_link for a payment link.") in msg
    assert _calls_used(env.db, FREE) == 20  # the refused call isn't counted
    doc = env.db.mcp_usage.find_one({"uid": FREE})
    assert doc["_id"].endswith(":2026-10")
    assert doc["expires_at"].replace(tzinfo=timezone.utc) == datetime(2026, 11, 2, tzinfo=timezone.utc)

    # No reset at a day boundary...
    now["t"] = datetime(2026, 10, 4, 0, 5, tzinfo=timezone.utc)
    assert "this month's 20 free" in _err(_call(token, "list_rbds"))
    now["t"] = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
    assert "— in 30 min." in _err(_call(token, "list_rbds"))
    # ...but on the first of the next month.
    now["t"] = datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc)
    _ok(_call(token, "list_rbds"))
    assert _calls_used(env.db, FREE) == 1


def test_next_month_start_rolls_the_year():
    from backend.services import billing

    assert billing.next_month_start(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)) == datetime(
        2027, 1, 1, tzinfo=timezone.utc)
    assert billing.next_month_start(datetime(2026, 1, 31, tzinfo=timezone.utc)) == datetime(
        2026, 2, 1, tzinfo=timezone.utc)


def test_a_lapsed_agent_plan_is_free_again(env):
    from backend.services import billing

    past = datetime.now(timezone.utc) - timedelta(days=1)
    env.db.users.update_one({"_id": AGENT}, {"$set": {"plan_until": past}})
    _ok(_call(env.oauth[AGENT], "list_models"))
    assert billing.mcp_calls_used(env.db, AGENT, "free") == 1 and _calls_today(env.db, AGENT) == 0
    assert FREE_PRO_ONLY in _err(_call(env.oauth[AGENT], "fit_distribution", FIT_ARGS))


@pytest.mark.parametrize("uid", [FREE, AGENT])
def test_api_tokens_stay_pro_only(env, uid):
    r = _post_mcp(env.api[uid])
    assert r.status_code == 403 and "API token is part of Reliafy Pro" in r.json()["detail"]
    assert "Agent" not in r.json()["detail"] and "Free" not in r.json()["detail"]


def test_rest_api_stays_pro_only_for_agent(env):
    from backend.services import billing

    assert billing.api_access_allowed(env.db, {"uid": AGENT, "email": "agent@example.org", "email_verified": True}) is False
    assert billing.api_access_allowed(env.db, {"uid": PRO, "email": "pro@example.org", "email_verified": True}) is True


def test_mcp_plan_follows_the_api_entitlement(env, monkeypatch):
    from backend import config
    from backend.services import billing

    def plan(uid):
        return billing.mcp_plan(env.db, {"uid": uid, "email": USERS[uid]["email"], "email_verified": True})

    assert (plan(FREE), plan(AGENT), plan(PRO)) == ("free", "agent", "pro")
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"free@example.org"})
    assert plan(FREE) == "pro"
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    assert plan(FREE) == "pro" and plan(AGENT) == "pro"


# ---- Pro: everything, no quota ------------------------------------------------------------

@pytest.mark.parametrize("via", ["oauth", "api"])
def test_pro_has_every_tool_without_quota(env, monkeypatch, via):
    from backend import config

    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 0)
    token = getattr(env, via)[PRO]
    assert len(_run(token, lambda c: c.list_tools()).tools) == N_TOOLS
    assert _ok(_call(token, "fit_distribution", {"data": [120, 340, 510, 700, 980]}))["params"]
    assert _ok(_call(token, "fit_and_save_model", {"name": "x", "data": [120, 340, 510, 700, 980]}))["saved"]
    assert "fleets" in _ok(_call(token, "list_fleets"))
    alerts = _call(token, "create_fleet_alert", {"fleet_id": "nope", "kind": "above", "threshold": 1})
    assert "not found" in _err(alerts).lower()  # past the gate, into the tool
    assert _ok(_call(token, "save_model", {"name": "Bearing", "distribution": "weibull", "params": WEIBULL}))
    for _ in range(3):
        _ok(_call(token, "list_models"))
    assert env.db.mcp_usage.count_documents({}) == 0


def test_self_hosted_and_operators_have_full_access(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "ADMIN_EMAILS", {"free@example.org"})
    _ok(_call(env.oauth[FREE], "list_models"))
    _ok(_call(env.oauth[FREE], "fit_distribution", {"data": [120, 340, 510, 700, 980]}))
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    for _ in range(2):
        _ok(_call(env.oauth[FREE], "list_models"))
    assert _post_mcp(env.api[FREE]).status_code == 200
    assert env.db.mcp_usage.count_documents({}) == 0


# ---- Grandfathered Agent: what they had, until it ends --------------------------------------

def test_grandfathered_agent_keeps_tools_except_fitting_and_fleets(env):
    token = env.oauth[AGENT]
    assert "life_models" in _ok(_call(token, "list_models"))
    assert _ok(_call(token, "optimal_replacement", {
        "distribution_id": "weibull", "params": WEIBULL, "planned_cost": 100, "unplanned_cost": 1000}))
    assert _ok(_call(token, "save_model", {"name": "Bearing", "distribution": "weibull", "params": WEIBULL}))["saved"]

    for name, args in [("fit_distribution", {"data": [120, 340, 510, 700, 980]}),
                       ("fit_and_save_model", {"name": "x", "data": [120, 340, 510, 700, 980]})]:
        msg = _err(_call(token, name, args))
        assert "part of Reliafy Pro (US$19/month)" in msg
        assert "SurPyval" in msg and "save_model" in msg and f"{BASE}/billing" in msg
    for name, args in [("list_fleets", {}),
                       ("create_fleet_alert", {"fleet_id": "nope", "kind": "above", "threshold": 1})]:
        msg = _err(_call(token, name, args))
        assert "Fleet forecasts and fleet alerts are part of Reliafy Pro" in msg and f"{BASE}/billing" in msg
    assert env.db.models.count_documents({"owner_id": AGENT, "dataset_id": {"$ne": ""}}) == 0


def test_grandfathered_agent_keeps_the_daily_quota(env, monkeypatch):
    from backend import config
    from backend.services import billing

    assert billing.mcp_daily_quota("agent") == config.MCP_AGENT_DAILY_CALLS == 2000
    assert billing.mcp_daily_quota("free") is None and billing.mcp_daily_quota("pro") is None

    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 2)
    token = env.oauth[AGENT]
    # A refused Pro-only call doesn't use the quota; tools/list never does.
    _err(_call(token, "fit_distribution", {"data": [1, 2, 3]}))
    _run(token, lambda c: c.list_tools())
    assert _calls_today(env.db, AGENT) == 0

    for _ in range(2):
        _ok(_call(token, "list_rbds"))
    msg = _err(_call(token, "list_rbds"))
    assert "2 Reliafy tool calls included per day on the Agent plan" in msg and "resets at 00:00 UTC" in msg
    assert UPGRADE in msg and "upgrade_link" in msg and "US$2" not in msg
    assert _calls_today(env.db, AGENT) == 2  # a refused call isn't counted
    assert len(_run(token, lambda c: c.list_tools()).tools) == N_TOOLS  # listing still works

    # Next UTC day: a fresh quota.
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    monkeypatch.setattr(billing, "_now", lambda: tomorrow)
    _ok(_call(token, "list_rbds"))
    assert _calls_today(env.db, AGENT) == 1


# ---- availability simulation: Pro or purchased credits ---------------------------------------

def _repairable(env, uid, name):
    return _ok(_call(env.oauth[uid], "create_rbd", {"name": name, "repairable": True, "stages": REPAIRABLE_STAGES}))["id"]


def test_grandfathered_agent_gets_no_simulations(env):
    rid = _repairable(env, AGENT, "Pumps")
    out = _ok(_call(env.oauth[AGENT], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is True and out["exact"]["status"] == "ok"
    assert out["simulation"]["available"] is False and out["simulation"]["code"] == "pro_required"
    msg = out["simulation"]["message"]
    assert "needs Reliafy Pro (US$19/month" in msg and f"{BASE}/billing" in msg
    assert "export_rbd_python" in msg and "Download as Python" in msg and "RePyability" in msg
    assert env.simulations["n"] == 0

    # The way forward it names works on the plan.
    script = _ok(_call(env.oauth[AGENT], "export_rbd_python", {"rbd_id": rid}))
    assert "repyability" in script["script"].lower()
    compile(script["script"], script["filename"], "exec")


def test_pro_and_purchased_credits_simulate_and_the_saved_result_is_served_after(env):
    from backend.services import billing

    rid = _repairable(env, PRO, "Pumps")
    # Every figure is exact: no simulation unless asked (#262)...
    out = _ok(_call(env.oauth[PRO], "analyze_rbd", {"rbd_id": rid}))
    assert out["has_simulation"] is False and out["simulation"]["on_request"] is True
    assert "simulate=true" in out["simulation"]["message"] and env.simulations["n"] == 0
    # ...and asked, it runs.
    out = _ok(_call(env.oauth[PRO], "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    assert out["available"] and out["cached"] is False and env.simulations["n"] == 1
    assert out["has_simulation"] is True and out["simulation"]["available"] is True
    assert out["exact"]["status"] == "ok" and out["precision"]
    # simulate=false: the exact figures only (the saved simulation still served).
    fast = _ok(_call(env.oauth[PRO], "analyze_rbd", {"rbd_id": rid, "simulate": False, "t_max": 500}))
    assert fast["has_simulation"] is False and fast["exact"]["window"] == 500
    assert env.simulations["n"] == 1

    # An Agent user who bought credits is entitled, as in the app...
    billing.grant_credits(env.db, AGENT, 500, "purchase")
    rid = _repairable(env, AGENT, "Compressors")
    out = _ok(_call(env.oauth[AGENT], "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    assert out["available"] and out["cached"] is False and env.simulations["n"] == 2
    # ...and without the entitlement still gets the saved result, never a re-run.
    env.db.credit_ledger.delete_many({"uid": AGENT, "reason": "purchase"})
    out = _ok(_call(env.oauth[AGENT], "analyze_rbd", {"rbd_id": rid, "recompute": True}))
    assert out["available"] and out["cached"] is True and out["can_recompute"] is False
    assert env.simulations["n"] == 2


# ---- plan-aware storage caps ----------------------------------------------------------------

def test_caps_are_plan_aware(env, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 2)
    monkeypatch.setattr(config, "AGENT_MAX_DATASETS", 3)
    assert billing.cap_for("datasets") == 2
    assert billing.cap_for("datasets", "agent") == 3 and billing.cap_for("datasets", "pro") is None
    assert billing.plan_caps("pro") is None
    assert billing.plan_caps("agent")["fleets"] == config.AGENT_MAX_FLEETS

    for uid in (FREE, AGENT, PRO):
        env.db.datasets.insert_many([{"_id": f"{uid}-d{i}", "owner_id": uid} for i in range(2)])
    assert billing.would_exceed_cap(env.db, FREE, "datasets") is True
    assert billing.would_exceed_cap(env.db, AGENT, "datasets") is False
    env.db.datasets.insert_one({"_id": "agent-d3", "owner_id": AGENT})
    assert billing.would_exceed_cap(env.db, AGENT, "datasets") is True
    env.db.datasets.insert_many([{"_id": f"pro-x{i}", "owner_id": PRO} for i in range(5)])
    assert billing.would_exceed_cap(env.db, PRO, "datasets") is False

    # A lapsed Agent plan falls back to the free caps.
    past = datetime.now(timezone.utc) - timedelta(days=1)
    env.db.users.update_one({"_id": AGENT}, {"$set": {"plan_until": past}})
    assert billing.account(env.db, AGENT)["active_plan"] == "free"
    env.db.datasets.delete_one({"_id": "agent-d3"})
    assert billing.would_exceed_cap(env.db, AGENT, "datasets") is True


def test_agent_mcp_cap_message_says_the_limit_and_upgrade(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "AGENT_MAX_DATASETS", 1)
    csv = "hours,failed\n1,0\n2,0\n3,1\n"
    _ok(_call(env.oauth[AGENT], "upload_dataset", {"name": "a", "csv": csv}))
    msg = _err(_call(env.oauth[AGENT], "upload_dataset", {"name": "b", "csv": csv}))
    assert "Agent plan's limit of 1 saved datasets" in msg and "doesn't reset" in msg
    assert UPGRADE in msg and "US$2" not in msg


def test_web_app_cap_message_uses_the_users_own_plan(env, monkeypatch):
    """A grandfathered Agent user who reaches a cap in the web app is told the
    Agent limit, not the free one."""
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "FREE_MAX_RBDS", 1)
    monkeypatch.setattr(config, "AGENT_MAX_RBDS", 25)
    assert billing.cap_message(env.db, FREE, "rbds") == (
        "You've reached the free-plan limit of 1 saved RBD. Upgrade to Pro for unlimited RBDs."
    )
    assert billing.cap_message(env.db, AGENT, "rbds") == (
        "You've reached the Agent plan limit of 25 saved RBDs. Upgrade to Pro for unlimited RBDs."
    )


# ---- save_model ---------------------------------------------------------------------------

def test_save_model_from_parameters(env):
    token = env.oauth[PRO]
    ds = _ok(_call(token, "upload_dataset", {"name": "Bearings", "csv": "hours,failed\n900,0\n1200,0\n1500,1\n"}))
    # Parameter order doesn't matter; names do.
    saved = _ok(_call(token, "save_model", {
        "name": "Bearing life", "distribution": "Weibull", "unit": "hours",
        "params": [{"name": "beta", "value": 2.5}, {"name": "alpha", "value": 1200}],
        "dataset_id": ds["id"], "notes": "surpyval.Weibull.fit, MLE"}))
    mid = saved["model_id"]
    assert saved["distribution_id"] == "weibull" and saved["unit"] == "Hours"
    assert saved["params"] == [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
    assert saved["url"].endswith(f"/modelling/m/{mid}") and saved["dataset_id"] == ds["id"]
    ref = surpyval.Weibull.from_params([1200, 2.5])
    assert saved["metrics"]["mttf"] == pytest.approx(float(ref.mean()))

    doc = env.db.models.find_one({"_id": mid})
    assert doc["owner_id"] == PRO and doc["spec"]["params_only"] is True
    assert doc["spec"]["notes"] == "surpyval.Weibull.fit, MLE" and doc["spec"]["source_dataset_id"] == ds["id"]
    assert doc["dataset_id"] == ""  # a reference only: never refitted from that dataset

    # Usable like any fitted model.
    rel = _ok(_call(token, "reliability_at", {"model_id": mid, "times": [600]}))
    assert rel["points"][0]["reliability"] == pytest.approx(float(ref.sf(600)), rel=1e-3)
    assert _ok(_call(token, "optimal_replacement", {"model_id": mid, "planned_cost": 100, "unplanned_cost": 1000}))
    assert mid in [m["id"] for m in _ok(_call(token, "list_models", {"kind": "life"}))["life_models"]]


def test_save_model_with_an_offset(env):
    saved = _ok(_call(env.oauth[AGENT], "save_model", {
        "name": "Offset", "distribution": "weibull",
        "params": [*WEIBULL, {"name": "gamma", "value": 100}]}))
    assert {"name": "gamma (offset)", "value": 100.0} in saved["extra_params"]
    ref = surpyval.Weibull.from_params([1200, 2.5], gamma=100)
    assert saved["metrics"]["mttf"] == pytest.approx(float(ref.mean()))


@pytest.mark.parametrize("args,expect", [
    ({"distribution": "nope", "params": WEIBULL}, "isn't a supported"),
    ({"distribution": "weibull", "params": [{"name": "alpha", "value": 1}]}, "missing: beta"),
    ({"distribution": "weibull", "params": [*WEIBULL, {"name": "mu", "value": 1}]}, "unknown: mu"),
    ({"distribution": "weibull", "params": [*WEIBULL, {"name": "beta", "value": 3}]}, "given twice"),
    ({"distribution": "normal", "params": [{"name": "mu", "value": 5}, {"name": "sigma", "value": 1},
                                           {"name": "gamma", "value": 1}]}, "doesn't take an offset"),
    ({"distribution": "weibull", "params": WEIBULL, "dataset_id": "missing"}, "Dataset not found"),
])
def test_save_model_validates(env, args, expect):
    msg = _err(_call(env.oauth[PRO], "save_model", {"name": "Bad", **args}))
    assert expect in msg
    assert env.db.models.count_documents({"owner_id": PRO}) == 0


def test_save_model_dataset_must_be_the_callers(env):
    ds = _ok(_call(env.oauth[PRO], "upload_dataset", {"name": "Mine", "csv": "t,c\n1,0\n2,0\n"}))
    msg = _err(_call(env.oauth[AGENT], "save_model", {
        "name": "Sneaky", "distribution": "weibull", "params": WEIBULL, "dataset_id": ds["id"]}))
    assert "Dataset not found" in msg


# ---- Stripe: subscribe, webhook, monthly credit ---------------------------------------------

class FakePrices:
    """Stripe's Price API, enough for stripe_prices: list by lookup key. Any
    create is a bug now that the Agent plan isn't sold."""

    def __init__(self, existing=None):
        self.prices = list(existing or [])
        self.listed = []

    def list(self, lookup_keys, limit, **kw):
        self.listed.append(kw)
        return {"data": [p for p in self.prices if p["lookup_key"] in lookup_keys][:limit]}

    def create(self, **kw):
        raise AssertionError("The retired Agent plan's Price must never be created.")


class FakeStripe:
    """Just the stripe-python surface routers/billing.py touches."""

    def __init__(self):
        self.calls = []
        self.Price = FakePrices()
        fake = self

        class Customer:
            @staticmethod
            def create(**kw):
                fake.calls.append(("customer", kw))
                return SimpleNamespace(id="cus_new")

        class Session:
            @staticmethod
            def create(**kw):
                fake.calls.append(("checkout", kw))
                return SimpleNamespace(url="https://checkout.stripe.test/cs_1")

        class Subscription:
            @staticmethod
            def retrieve(sub_id):
                fake.calls.append(("retrieve", sub_id))
                return {"id": sub_id, "items": {"data": [{"id": "si_1", "price": {"id": "price_agent"}}]}}

            @staticmethod
            def modify(sub_id, **kw):
                fake.calls.append(("modify", sub_id, kw))
                return {"id": sub_id}

        self.Customer = Customer
        self.checkout = SimpleNamespace(Session=Session)
        self.Subscription = Subscription


@pytest.fixture()
def stripe_client(env, monkeypatch):
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import billing as billing_router

    fake = FakeStripe()
    monkeypatch.setattr(config, "STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setattr(config, "STRIPE_PRO_PRICE_ID", "price_pro")
    monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", "price_agent")
    monkeypatch.setattr(billing_router, "_stripe", lambda: fake)
    who = {"uid": FREE}
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": who["uid"], "email": USERS[who["uid"]]["email"], "name": "T"}
    try:
        yield SimpleNamespace(client=TestClient(app), fake=fake, who=who, db=env.db, oauth=env.oauth)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("configured", [True, False])
def test_subscribe_plan_agent_is_refused(stripe_client, monkeypatch, configured):
    from backend import config
    from backend.services import stripe_prices

    s = stripe_client
    if not configured:  # the provisioned-by-lookup-key setup: still nothing is created
        monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", None)
        stripe_prices.reset_cache()
    try:
        r = s.client.post("/api/billing/subscribe", json={"plan": "agent"})
        assert r.status_code == 410
        assert r.json()["detail"] == "The Agent plan has been retired; MCP is now part of Pro."
        assert s.fake.calls == []  # no customer, no checkout
    finally:
        stripe_prices.reset_cache()

    # No body still means Pro, as the existing button sends.
    r = s.client.post("/api/billing/subscribe")
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.test/")
    kind, kw = s.fake.calls[-1]
    assert kind == "checkout" and kw["mode"] == "subscription"
    assert kw["line_items"] == [{"price": "price_pro", "quantity": 1}]
    assert kw["metadata"] == {"uid": FREE, "kind": "pro"}

    assert s.client.post("/api/billing/subscribe", json={"plan": "platinum"}).status_code == 400
    body = s.client.get("/api/billing").json()
    assert "agent_available" not in body and body["pro_available"] is True


def test_grandfathered_agent_upgrades_to_pro_on_the_same_subscription(stripe_client):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    s = stripe_client
    s.who["uid"] = FREE
    # An Agent checkout opened before the plan was retired completes afterwards.
    _handle_event(s.db, {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "customer": "cus_f", "subscription": "sub_1", "metadata": {"uid": FREE, "kind": "agent"}}}})
    assert billing.account(s.db, FREE)["active_plan"] == "agent"
    assert s.client.post("/api/billing/subscribe", json={"plan": "agent"}).status_code == 410

    r = s.client.post("/api/billing/subscribe", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["switched"] is True
    assert not [c for c in s.fake.calls if c[0] == "checkout"]  # no second subscription
    _, sub_id, kw = s.fake.calls[-1]
    assert sub_id == "sub_1" and kw["items"] == [{"id": "si_1", "price": "price_pro"}]
    assert billing.account(s.db, FREE)["active_plan"] == "pro"

    # A pre-existing subscriber without a recorded subscription id goes to the portal.
    s.who["uid"] = AGENT
    r = s.client.post("/api/billing/subscribe", json={"plan": "pro"})
    assert r.status_code == 409 and "Manage subscription" in r.json()["detail"]


def test_webhook_handles_an_existing_agent_subscription_to_its_end(stripe_client):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    s = stripe_client
    billing.set_plan(s.db, FREE, "agent", customer_id="cus_f", subscription_id="sub_1")
    assert _ok(_call(s.oauth[FREE], "list_models"))  # MCP while it lasts

    # A renewal (still the Agent price) keeps the plan.
    _handle_event(s.db, {"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_f", "status": "active",
        "items": {"data": [{"id": "si_1", "price": {"id": "price_agent"}}]}}}})
    acct = billing.account(s.db, FREE)
    assert acct["active_plan"] == "agent" and acct["is_agent"] is True and acct["is_pro"] is False
    assert s.client.get("/api/me").json()["plan"] == "agent"

    # Some other (old) subscription ending leaves the current plan alone...
    _handle_event(s.db, {"type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_old", "customer": "cus_f"}}})
    assert billing.account(s.db, FREE)["active_plan"] == "agent"
    # ...while cancelling the current one downgrades — and with it goes MCP.
    _handle_event(s.db, {"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_f", "status": "canceled",
        "items": {"data": [{"id": "si_1", "price": {"id": "price_agent"}}]}}}})
    acct = billing.account(s.db, FREE)
    assert acct["active_plan"] == "free" and acct["stripe_subscription_id"] is None
    _ok(_call(s.oauth[FREE], "list_models"))  # back on Free's allowance...
    assert _calls_used(s.db, FREE) == 1
    assert FREE_PRO_ONLY in _err(_call(s.oauth[FREE], "fit_distribution", FIT_ARGS))  # ...without fitting

    # customer.subscription.deleted ends one too.
    billing.set_plan(s.db, AGENT, "agent", customer_id="cus_a", subscription_id="sub_a")
    _handle_event(s.db, {"type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_a", "customer": "cus_a"}}})
    assert billing.account(s.db, AGENT)["active_plan"] == "free"


def test_webhook_follows_an_agent_subscriber_to_pro(stripe_client):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    s = stripe_client
    billing.set_plan(s.db, FREE, "agent", customer_id="cus_f", subscription_id="sub_1")
    # Switched to Pro (here or in Stripe's portal): the subscription's price says so.
    _handle_event(s.db, {"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_f", "status": "active",
        "items": {"data": [{"id": "si_1", "price": {"id": "price_pro"}}]}}}})
    assert billing.account(s.db, FREE)["active_plan"] == "pro"


def test_agent_price_is_found_by_lookup_key_never_created(monkeypatch):
    from backend import config
    from backend.routers import billing as billing_router
    from backend.services import stripe_prices

    monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", None)
    monkeypatch.setattr(config, "STRIPE_PRO_PRICE_ID", "price_pro")
    stripe_prices.reset_cache()
    try:
        # Never provisioned: nothing to find, and nothing is created.
        stripe = SimpleNamespace(Price=FakePrices())
        assert stripe_prices.agent_price_id(stripe) is None
        assert stripe_prices.agent_price_id(None) is None

        # Provisioned back when it was sold (and maybe archived since): found
        # by its lookup key, archived or not.
        prices = FakePrices([{"id": "price_auto_1", "lookup_key": stripe_prices.AGENT_LOOKUP_KEY,
                              "active": False}])
        stripe = SimpleNamespace(Price=prices)
        monkeypatch.setattr(billing_router, "_stripe", lambda: stripe)
        assert billing_router._plan_for_prices({"price_auto_1"}) == "agent"
        assert billing_router._plan_for_prices({"price_other"}) is None
        assert billing_router._plan_for_prices({"price_pro", "price_auto_1"}) == "pro"
        assert prices.listed and all("active" not in kw for kw in prices.listed)

        # A configured id always wins.
        monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", "price_configured")
        assert stripe_prices.agent_price_id(stripe) == "price_configured"
    finally:
        stripe_prices.reset_cache()


def test_invoice_paid_grants_monthly_credit_to_pro_only(env, monkeypatch):
    from backend import config
    from backend.routers.billing import _handle_event
    from backend.services import billing

    monkeypatch.setattr(config, "PRO_MONTHLY_CREDIT_CENTS", 1000)
    monkeypatch.setattr(config, "STRIPE_PRO_PRICE_ID", "price_pro")
    monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", "price_agent")
    billing.set_plan(env.db, AGENT, "agent", customer_id="cus_agent")
    before = billing.account(env.db, AGENT)["credit_cents"]

    # A grandfathered Agent invoice — with or without line prices — grants nothing.
    _handle_event(env.db, {"type": "invoice.paid", "data": {"object": {"id": "in_a1", "customer": "cus_agent"}}})
    _handle_event(env.db, {"type": "invoice.paid", "data": {"object": {
        "id": "in_a2", "customer": "cus_agent", "lines": {"data": [{"price": {"id": "price_agent"}}]}}}})
    assert billing.account(env.db, AGENT)["credit_cents"] == before
    assert env.db.credit_ledger.count_documents({"uid": AGENT, "reason": "pro-monthly"}) == 0

    # A Pro invoice arriving before checkout.session.completed set the plan
    # still grants: the invoice's own price decides (newer API line shape).
    billing.set_customer(env.db, FREE, "cus_new_pro")
    _handle_event(env.db, {"type": "invoice.paid", "data": {"object": {
        "id": "in_p1", "customer": "cus_new_pro",
        "lines": {"data": [{"pricing": {"price_details": {"price": "price_pro"}}}]}}}})
    assert env.db.credit_ledger.count_documents({"uid": FREE, "reason": "pro-monthly"}) == 1


def test_billing_status_shows_the_agent_quota_only_to_agent_subscribers(stripe_client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 2000)
    s = stripe_client
    _ok(_call(s.oauth[AGENT], "list_models"))
    _ok(_call(s.oauth[AGENT], "list_rbds"))

    s.who["uid"] = AGENT
    body = s.client.get("/api/billing").json()
    assert body["plan"] == "agent" and body["pro_available"] is True
    assert body["plan_caps"]["datasets"] == config.AGENT_MAX_DATASETS
    assert body["caps"]["datasets"] == config.FREE_MAX_DATASETS
    assert body["mcp"]["calls_today"] == 2 and body["mcp"]["daily_quota"] == 2000
    for retired in ("agent_available", "agent_caps", "mcp_free_daily_calls", "mcp_agent_daily_calls"):
        assert retired not in body
    assert not any("simulation" in key for key in [*body, *body["mcp"]])

    s.who["uid"] = FREE
    _ok(_call(s.oauth[FREE], "list_models"))
    body = s.client.get("/api/billing").json()
    assert body["plan"] == "free" and body["mcp"]["daily_quota"] is None and body["mcp"]["calls_today"] == 0
    assert body["mcp"]["quota"] == 20 and body["mcp"]["period"] == "month" and body["mcp"]["calls_used"] == 1

    s.who["uid"] = PRO
    body = s.client.get("/api/billing").json()
    assert body["plan"] == "pro" and body["plan_caps"] is None and body["mcp"]["daily_quota"] is None
    assert body["mcp"]["quota"] is None and body["mcp"]["period"] is None


# ---- upgrade_link: Pro only ---------------------------------------------------------------

def test_upgrade_link_offers_only_pro_and_works_past_the_free_allowance(stripe_client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 1)
    s = stripe_client
    tools = _run(s.oauth[FREE], lambda c: c.list_tools()).tools
    schema = next(t for t in tools if t.name == "upgrade_link").input_schema["properties"]["plan"]
    assert schema.get("enum", [schema.get("const")]) == ["pro"] and schema["default"] == "pro"

    _ok(_call(s.oauth[FREE], "list_models"))
    assert "this month's 1 free" in _err(_call(s.oauth[FREE], "list_models"))  # allowance used...
    out = _ok(_call(s.oauth[FREE], "upgrade_link"))  # ...but the way to Pro works
    assert out["plan"] == "pro" and out["price"] == "US$19/month"
    assert out["url"].startswith("https://checkout.stripe.test/")
    assert "nothing is charged until the checkout is completed" in out["note"]
    kind, kw = s.fake.calls[-1]
    assert kind == "checkout" and kw["line_items"] == [{"price": "price_pro", "quantity": 1}]
    assert kw["metadata"] == {"uid": FREE, "kind": "pro"}

    # Asking for the retired plan isn't possible.
    assert _call(s.oauth[FREE], "upgrade_link", {"plan": "agent"}).is_error
    assert not any(kw.get("metadata", {}).get("kind") == "agent" for _, kw in
                   [c for c in s.fake.calls if c[0] == "checkout"])
    assert _calls_used(s.db, FREE) == 1  # upgrade_link isn't counted


def test_upgrade_link_past_the_agent_quota_and_never_switching_a_subscriber(stripe_client, monkeypatch):
    from backend import config

    s = stripe_client
    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 1)
    _ok(_call(s.oauth[AGENT], "list_models"))
    assert "upgrade_link" in _err(_call(s.oauth[AGENT], "list_models"))  # quota used up

    out = _ok(_call(s.oauth[AGENT], "upgrade_link"))
    assert out["url"].endswith("/billing") and "billing page" in out["note"] and out["plan"] == "pro"
    assert not any(c[0] in ("modify", "checkout") for c in s.fake.calls)
    assert _calls_today(s.db, AGENT) == 1  # upgrade_link isn't counted
