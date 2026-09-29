"""The Agent plan (US$2/month, MCP only) and the free MCP tier.

Plan gating per MCP tool (OAuth vs ``rlf_`` API tokens), the daily tool-call
quota, availability simulation staying Pro / purchased credits, plan-aware
storage caps, the ``save_model`` tool, and the Stripe side: subscribing with
plan=agent, the webhook, and the Pro monthly credit staying Pro-only.

MCP calls go through the real ``/mcp`` mount (as in test_mcp.py); Stripe is a
fake module swapped in for ``routers.billing._stripe`` — nothing leaves the
process.
"""

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import mongomock
import numpy as np
import pytest
import surpyval
from fastapi.testclient import TestClient

from backend.tests.test_mcp import REPAIRABLE_STAGES, _err, _ok, _run

BASE = "https://reliafy.com"
FREE, AGENT, PRO = "free-user", "agent-user", "pro-user"
USERS = {
    FREE: {"_id": FREE, "email": "free@example.org", "name": "Free"},
    AGENT: {"_id": AGENT, "email": "agent@example.org", "name": "Agent", "plan": "agent"},
    PRO: {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro"},
}
UPGRADE = "Reliafy Agent (US$2/month, MCP) or Pro (US$19/month)"
WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]


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
    test_db = mongomock.MongoClient()["reliafy_agent_plan_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    for u in USERS.values():
        test_db.users.insert_one(dict(u))

    # Count real availability simulations.
    sims = {"n": 0}
    real = rbd_analysis.analyze_availability

    def spy(*args, **kwargs):
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


def _post_mcp(token):
    from backend.main import app

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    return TestClient(app).post("/mcp", json=body, headers={
        "Accept": "application/json, text/event-stream", "Authorization": f"Bearer {token}"})


# ---- plan gating per tool ---------------------------------------------------------------

@pytest.mark.parametrize("uid", [FREE, AGENT, PRO])
def test_oauth_tool_gating_by_plan(env, uid):
    token = env.oauth[uid]
    tools = {t.name for t in _run(token, lambda c: c.list_tools()).tools}
    assert {"save_model", "fit_distribution", "list_fleets"} <= tools  # every plan sees every tool

    assert "life_models" in _ok(_call(token, "list_models"))
    assert _ok(_call(token, "optimal_replacement", {
        "distribution_id": "weibull", "params": WEIBULL, "planned_cost": 100, "unplanned_cost": 1000}))
    saved = _ok(_call(token, "save_model", {"name": "Bearing", "distribution": "weibull", "params": WEIBULL}))
    assert saved["saved"] is True

    fit = _call(token, "fit_distribution", {"data": [120, 340, 510, 700, 980]})
    fit_saved = _call(token, "fit_and_save_model", {"name": "x", "data": [120, 340, 510, 700, 980]})
    fleets = _call(token, "list_fleets")
    alerts = _call(token, "create_fleet_alert", {"fleet_id": "nope", "kind": "above", "threshold": 1})
    if uid == PRO:
        assert _ok(fit)["params"] and _ok(fit_saved)["saved"] and "fleets" in _ok(fleets)
        assert "not found" in _err(alerts).lower()  # past the gate, into the tool
    else:
        for result in (fit, fit_saved):
            msg = _err(result)
            assert "part of Reliafy Pro (US$19/month)" in msg
            assert "SurPyval" in msg and "save_model" in msg and f"{BASE}/billing" in msg
        for result in (fleets, alerts):
            msg = _err(result)
            assert "Fleet forecasts and fleet alerts are part of Reliafy Pro" in msg and f"{BASE}/billing" in msg
        assert env.db.models.count_documents({"owner_id": uid, "dataset_id": {"$ne": ""}}) == 0


@pytest.mark.parametrize("uid", [FREE, AGENT])
def test_api_tokens_stay_pro_only(env, uid):
    r = _post_mcp(env.api[uid])
    assert r.status_code == 403 and "API token is part of Reliafy Pro" in r.json()["detail"]


def test_pro_api_token_has_every_tool_without_quota(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_DAILY_CALLS", 0)
    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 0)
    assert _ok(_call(env.api[PRO], "fit_distribution", {"data": [120, 340, 510, 700, 980]}))["params"]
    assert "fleets" in _ok(_call(env.api[PRO], "list_fleets"))
    assert env.db.mcp_usage.count_documents({}) == 0


def test_rest_api_stays_pro_only_for_agent(env):
    from backend.services import billing

    assert billing.api_access_allowed(env.db, {"uid": AGENT, "email": "agent@example.org"}) is False
    assert billing.api_access_allowed(env.db, {"uid": PRO, "email": "pro@example.org"}) is True


# ---- daily tool-call quota ----------------------------------------------------------------

def test_free_daily_quota_counts_tool_calls_only_and_resets(env, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "MCP_FREE_DAILY_CALLS", 3)
    token = env.oauth[FREE]

    # A refused Pro-only call doesn't use the quota; tools/list and initialize never do.
    _err(_call(token, "fit_distribution", {"data": [1, 2, 3]}))
    _run(token, lambda c: c.list_tools())
    assert _calls_today(env.db, FREE) == 0

    for _ in range(3):
        _ok(_call(token, "list_models"))
    assert _calls_today(env.db, FREE) == 3

    msg = _err(_call(token, "list_models"))
    assert "You've used all 3 Reliafy tool calls included per day on the Free plan" in msg
    assert "resets at 00:00 UTC" in msg and UPGRADE in msg and f"{BASE}/billing" in msg
    assert _calls_today(env.db, FREE) == 3  # a refused call isn't counted
    assert len(_run(token, lambda c: c.list_tools()).tools) == 20  # listing still works

    # Next UTC day: a fresh quota.
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    monkeypatch.setattr(billing, "_now", lambda: tomorrow)
    _ok(_call(token, "list_models"))
    assert _calls_today(env.db, FREE) == 1


def test_agent_quota_is_separate_and_pro_has_none(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_DAILY_CALLS", 1)
    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 2)
    for _ in range(2):
        _ok(_call(env.oauth[AGENT], "list_rbds"))
    msg = _err(_call(env.oauth[AGENT], "list_rbds"))
    assert "2 Reliafy tool calls included per day on the Agent plan" in msg
    # An Agent user is pointed at the plan above theirs, not at Agent again.
    assert "upgrade to Reliafy Pro (US$19/month)" in msg and "Reliafy Agent (US$2" not in msg

    for _ in range(3):
        _ok(_call(env.oauth[PRO], "list_rbds"))
    assert env.db.mcp_usage.count_documents({"uid": PRO}) == 0


def test_self_hosted_and_operators_have_no_quota(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_DAILY_CALLS", 1)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"free@example.org"})
    for _ in range(2):
        _ok(_call(env.oauth[FREE], "list_models"))
    _ok(_call(env.oauth[FREE], "fit_distribution", {"data": [120, 340, 510, 700, 980]}))
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    for _ in range(2):
        _ok(_call(env.oauth[FREE], "list_models"))
    assert env.db.mcp_usage.count_documents({}) == 0


# ---- availability simulation: Pro or purchased credits, on every plan ------------------------

def _repairable(env, uid, name):
    return _ok(_call(env.oauth[uid], "create_rbd", {"name": name, "repairable": True, "stages": REPAIRABLE_STAGES}))["id"]


@pytest.mark.parametrize("uid", [FREE, AGENT])
def test_free_and_agent_mcp_users_get_no_simulations(env, uid):
    rid = _repairable(env, uid, "Pumps")
    out = _ok(_call(env.oauth[uid], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is False and out["code"] == "pro_required"
    msg = out["message"]
    assert "needs Reliafy Pro (US$19/month" in msg and f"{BASE}/billing" in msg
    assert "export_rbd_python" in msg and "Download as Python" in msg and "RePyability" in msg
    assert env.simulations["n"] == 0

    # The way forward it names works on the plan.
    script = _ok(_call(env.oauth[uid], "export_rbd_python", {"rbd_id": rid}))
    assert "repyability" in script["script"].lower()
    compile(script["script"], script["filename"], "exec")


def test_pro_and_purchased_credits_simulate_and_the_saved_result_is_served_after(env):
    from backend.services import billing

    rid = _repairable(env, PRO, "Pumps")
    out = _ok(_call(env.oauth[PRO], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] and out["cached"] is False and env.simulations["n"] == 1

    # An Agent user who bought credits is entitled, as in the app...
    billing.grant_credits(env.db, AGENT, 500, "purchase")
    rid = _repairable(env, AGENT, "Compressors")
    out = _ok(_call(env.oauth[AGENT], "analyze_rbd", {"rbd_id": rid}))
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


def test_mcp_cap_message_says_the_limit_and_upgrade(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "AGENT_MAX_DATASETS", 1)
    monkeypatch.setattr(config, "FREE_MAX_MODELS", 1)
    csv = "hours,failed\n1,0\n2,0\n3,1\n"
    _ok(_call(env.oauth[AGENT], "upload_dataset", {"name": "a", "csv": csv}))
    msg = _err(_call(env.oauth[AGENT], "upload_dataset", {"name": "b", "csv": csv}))
    assert "Agent plan's limit of 1 saved datasets" in msg and "doesn't reset" in msg
    assert "upgrade to Reliafy Pro (US$19/month)" in msg

    _ok(_call(env.oauth[FREE], "save_model", {"name": "m1", "distribution": "weibull", "params": WEIBULL}))
    msg = _err(_call(env.oauth[FREE], "save_model", {"name": "m2", "distribution": "weibull", "params": WEIBULL}))
    assert "Free plan's limit of 1 saved models" in msg and UPGRADE in msg
    assert env.db.models.count_documents({"owner_id": FREE}) == 1



def test_web_app_cap_message_uses_the_users_own_plan(env, monkeypatch):
    """An Agent user who reaches a cap in the web app is told the Agent limit,
    not the free one."""
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
    token = env.oauth[AGENT]
    ds = _ok(_call(token, "upload_dataset", {"name": "Bearings", "csv": "hours,failed\n900,0\n1200,0\n1500,1\n"}))
    # Parameter order doesn't matter; names do.
    saved = _ok(_call(token, "save_model", {
        "name": "Bearing life", "distribution": "Weibull", "unit": "hours",
        "params": [{"name": "beta", "value": 2.5}, {"name": "alpha", "value": 1200}],
        "dataset_id": ds["id"], "notes": "surpyval.Weibull.fit, MLE"}))
    mid = saved["model_id"]
    assert saved["distribution_id"] == "weibull" and saved["unit"] == "hours"
    assert saved["params"] == [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
    assert saved["url"].endswith(f"/modelling/m/{mid}") and saved["dataset_id"] == ds["id"]
    ref = surpyval.Weibull.from_params([1200, 2.5])
    assert saved["metrics"]["mttf"] == pytest.approx(float(ref.mean()))

    doc = env.db.models.find_one({"_id": mid})
    assert doc["owner_id"] == AGENT and doc["spec"]["params_only"] is True
    assert doc["spec"]["notes"] == "surpyval.Weibull.fit, MLE" and doc["spec"]["source_dataset_id"] == ds["id"]
    assert doc["dataset_id"] == ""  # a reference only: never refitted from that dataset

    # Usable like any fitted model.
    rel = _ok(_call(token, "reliability_at", {"model_id": mid, "times": [600]}))
    assert rel["points"][0]["reliability"] == pytest.approx(float(ref.sf(600)), rel=1e-3)
    assert _ok(_call(token, "optimal_replacement", {"model_id": mid, "planned_cost": 100, "unplanned_cost": 1000}))
    assert mid in [m["id"] for m in _ok(_call(token, "list_models", {"kind": "life"}))["life_models"]]


def test_save_model_with_an_offset(env):
    saved = _ok(_call(env.oauth[FREE], "save_model", {
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
    msg = _err(_call(env.oauth[FREE], "save_model", {"name": "Bad", **args}))
    assert expect in msg
    assert env.db.models.count_documents({"owner_id": FREE}) == 0


def test_save_model_dataset_must_be_the_callers(env):
    ds = _ok(_call(env.oauth[PRO], "upload_dataset", {"name": "Mine", "csv": "t,c\n1,0\n2,0\n"}))
    msg = _err(_call(env.oauth[AGENT], "save_model", {
        "name": "Sneaky", "distribution": "weibull", "params": WEIBULL, "dataset_id": ds["id"]}))
    assert "Dataset not found" in msg


# ---- Stripe: subscribe, webhook, monthly credit ---------------------------------------------

class FakeStripe:
    """Just the stripe-python surface routers/billing.py touches."""

    def __init__(self):
        self.calls = []
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


def test_subscribe_with_plan_agent(stripe_client, monkeypatch):
    from backend import config

    s = stripe_client
    r = s.client.post("/api/billing/subscribe", json={"plan": "agent"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.test/")
    kind, kw = s.fake.calls[-1]
    assert kind == "checkout" and kw["mode"] == "subscription"
    assert kw["line_items"] == [{"price": "price_agent", "quantity": 1}]
    assert kw["metadata"] == {"uid": FREE, "kind": "agent"} and kw["customer"] == "cus_new"

    # No body still means Pro, as the existing button sends.
    r = s.client.post("/api/billing/subscribe")
    assert r.status_code == 200
    assert s.fake.calls[-1][1]["line_items"] == [{"price": "price_pro", "quantity": 1}]
    assert s.fake.calls[-1][1]["metadata"]["kind"] == "pro"

    assert s.client.post("/api/billing/subscribe", json={"plan": "platinum"}).status_code == 400
    monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", None)
    r = s.client.post("/api/billing/subscribe", json={"plan": "agent"})
    assert r.status_code == 503 and "Agent plan is not configured" in r.json()["detail"]
    assert s.client.get("/api/billing").json()["agent_available"] is False


def test_agent_upgrades_to_pro_on_the_same_subscription(stripe_client):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    s = stripe_client
    s.who["uid"] = FREE
    _handle_event(s.db, {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "customer": "cus_f", "subscription": "sub_1", "metadata": {"uid": FREE, "kind": "agent"}}}})
    assert s.client.post("/api/billing/subscribe", json={"plan": "agent"}).status_code == 409

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


def test_webhook_kind_agent_and_plan_changes(stripe_client):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    s = stripe_client
    _handle_event(s.db, {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "customer": "cus_f", "subscription": "sub_1", "metadata": {"uid": FREE, "kind": "agent"}}}})
    acct = billing.account(s.db, FREE)
    assert acct["active_plan"] == "agent" and acct["is_pro"] is False and acct["is_agent"] is True
    assert acct["stripe_subscription_id"] == "sub_1" and acct["stripe_customer_id"] == "cus_f"
    assert s.client.get("/api/me").json()["plan"] == "agent"

    # Switched to Pro (here or in Stripe's portal): the subscription's price says so.
    _handle_event(s.db, {"type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_f", "status": "active",
        "items": {"data": [{"id": "si_1", "price": {"id": "price_pro"}}]}}}})
    assert billing.account(s.db, FREE)["active_plan"] == "pro"

    # Some other (old) subscription ending leaves the current plan alone...
    _handle_event(s.db, {"type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_old", "customer": "cus_f"}}})
    assert billing.account(s.db, FREE)["active_plan"] == "pro"
    # ...while the current one ending downgrades.
    _handle_event(s.db, {"type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_1", "customer": "cus_f"}}})
    acct = billing.account(s.db, FREE)
    assert acct["active_plan"] == "free" and acct["stripe_subscription_id"] is None


def test_invoice_paid_grants_monthly_credit_to_pro_only(env, monkeypatch):
    from backend import config
    from backend.routers.billing import _handle_event
    from backend.services import billing

    monkeypatch.setattr(config, "PRO_MONTHLY_CREDIT_CENTS", 1000)
    monkeypatch.setattr(config, "STRIPE_PRO_PRICE_ID", "price_pro")
    monkeypatch.setattr(config, "STRIPE_AGENT_PRICE_ID", "price_agent")
    billing.set_plan(env.db, AGENT, "agent", customer_id="cus_agent")
    before = billing.account(env.db, AGENT)["credit_cents"]

    # An Agent invoice — with or without line prices — grants nothing.
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


def test_billing_status_exposes_agent_plan_and_mcp_usage(stripe_client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_AGENT_DAILY_CALLS", 2000)
    s = stripe_client
    _ok(_call(s.oauth[AGENT], "list_models"))
    _ok(_call(s.oauth[AGENT], "list_rbds"))

    s.who["uid"] = AGENT
    body = s.client.get("/api/billing").json()
    assert body["plan"] == "agent" and body["agent_available"] is True and body["pro_available"] is True
    assert body["plan_caps"] == body["agent_caps"] and body["agent_caps"]["datasets"] == config.AGENT_MAX_DATASETS
    assert body["caps"]["datasets"] == config.FREE_MAX_DATASETS
    assert body["mcp"]["calls_today"] == 2 and body["mcp"]["daily_quota"] == 2000
    assert body["mcp_agent_daily_calls"] == 2000 and body["mcp_free_daily_calls"] == config.MCP_FREE_DAILY_CALLS
    assert not any("simulation" in key for key in [*body, *body["mcp"]])  # not part of any MCP plan

    s.who["uid"] = FREE
    body = s.client.get("/api/billing").json()
    assert body["plan"] == "free" and body["mcp"]["daily_quota"] == config.MCP_FREE_DAILY_CALLS
    assert body["mcp"]["calls_today"] == 0

    s.who["uid"] = PRO
    body = s.client.get("/api/billing").json()
    assert body["plan"] == "pro" and body["plan_caps"] is None and body["mcp"]["daily_quota"] is None
