"""Product-usage logging: MCP tool calls and app requests become usage
events (90-day TTL), rolled up into identifier-free daily totals, reported
on the operator dashboard.

MCP calls go through the real ``/mcp`` mount with the fixtures of
test_mcp_plans.py (Free, Agent and Pro users; OAuth tokens from a client
registered as "Claude").
"""

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.tests.test_mcp import _err, _ok, _run
from backend.tests.test_mcp_plans import AGENT, FREE, PRO, WEIBULL, _call, _post_mcp, env  # noqa: F401

FIT = {"data": [120, 340, 510, 700, 980]}


def _events(db, **query):
    return list(db.usage_events.find({"channel": "mcp", **query}, {"_id": 0}))


# ---- MCP: every tool call, every outcome ---------------------------------------------------

def test_mcp_logs_each_outcome_with_plan_client_and_duration(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 1)
    _ok(_call(env.oauth[PRO], "list_models"))  # ok
    _err(_call(env.oauth[PRO], "get_model", {"model_id": "nope"}))  # error
    _ok(_call(env.oauth[FREE], "list_rbds"))  # ok (the allowance)
    _err(_call(env.oauth[FREE], "list_rbds"))  # limit
    _err(_call(env.oauth[FREE], "fit_distribution", FIT))  # pro_only (Free)
    _err(_call(env.oauth[AGENT], "fit_distribution", FIT))  # pro_only (grandfathered Agent)
    assert _post_mcp(env.api[FREE]).status_code == 403  # locked: a non-Pro API token

    got = {(e["uid"], e["feature"], e["outcome"], e["plan"]) for e in _events(env.db)
           if e["feature"] not in ("initialize", "tools/list")}
    assert got == {
        (PRO, "list_models", "ok", "pro"),
        (PRO, "get_model", "error", "pro"),
        (FREE, "list_rbds", "ok", "free"),
        (FREE, "list_rbds", "limit", "free"),
        (FREE, "fit_distribution", "pro_only", "free"),
        (AGENT, "fit_distribution", "pro_only", "agent"),
        (FREE, "connect", "locked", "free"),
    }
    calls = _events(env.db, feature="list_models")
    assert calls[0]["client"] == "Claude" and calls[0]["ms"] >= 0 and calls[0]["day"]
    assert _events(env.db, feature="connect")[0]["client"] == "API token"
    # Nothing about what was analysed, and no network identifiers.
    for e in env.db.usage_events.find({}, {"_id": 0}):
        assert set(e) == {"ts", "day", "uid", "channel", "feature", "outcome", "plan", "client", "ms"}


def test_mcp_logs_connections_and_upgrade_link(env, monkeypatch):
    from backend.routers import billing as billing_router

    _run(env.oauth[FREE], lambda c: c.list_tools())
    features = [e["feature"] for e in _events(env.db, uid=FREE)]
    assert "initialize" in features and "tools/list" in features

    # upgrade_link is logged like any tool (here Stripe isn't configured: an error).
    monkeypatch.setattr(billing_router, "_stripe", lambda: None)
    _call(env.oauth[FREE], "upgrade_link")
    assert _events(env.db, uid=FREE, feature="upgrade_link")


def test_simulation_refusal_is_logged_pro_only(env):
    from backend.tests.test_mcp import REPAIRABLE_STAGES

    rid = _ok(_call(env.oauth[FREE], "create_rbd", {
        "name": "Pumps", "repairable": True, "stages": REPAIRABLE_STAGES}))["id"]
    # The exact figures are an answer (#154)...
    assert _ok(_call(env.oauth[FREE], "analyze_rbd", {"rbd_id": rid}))["available"] is True
    assert _events(env.db, feature="analyze_rbd")[0]["outcome"] == "ok"
    # ...a simulation-only diagram (one repair crew for wear-out lives) is the refusal.
    graph = env.db.rbds.find_one({"_id": rid})["graph"]
    graph["repair_crews"] = {"crews": 1}
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": graph}})
    assert _ok(_call(env.oauth[FREE], "analyze_rbd", {"rbd_id": rid}))["available"] is False
    assert {e["outcome"] for e in _events(env.db, feature="analyze_rbd")} == {"ok", "pro_only"}


def test_daily_totals_carry_no_account_ids(env):
    from backend.services import usage

    _ok(_call(env.oauth[PRO], "list_models"))
    _err(_call(env.oauth[FREE], "fit_distribution", FIT))
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1, hours=1)
    assert usage.rollup(env.db, now=tomorrow)["days"]
    docs = list(env.db.usage_daily.find({}))
    assert docs
    blob = repr(docs)
    for uid in (FREE, AGENT, PRO):
        assert uid not in blob
    for doc in docs:
        assert "uid" not in doc
    tool = next(d for d in docs if d.get("feature") == "list_models")
    assert tool["client"] == "Claude" and tool["plan"] == "pro" and tool["count"] == 1
    walls = [d for d in docs if d.get("segment") == "wall_pro_only"]
    assert walls and walls[0]["accounts"] == 1 and walls[0]["plan"] == "free"


def test_usage_events_expire_after_90_days():
    from backend.services import usage

    db = mongomock.MongoClient()["usage_ttl"]
    usage.ensure_indexes(db)
    ttl = [i for i in db.usage_events.index_information().values() if "expireAfterSeconds" in i]
    assert len(ttl) == 1
    assert ttl[0]["key"] == [("ts", 1)] and ttl[0]["expireAfterSeconds"] == 90 * 24 * 3600
    # Nothing else carries account ids or expires.
    assert not any("expireAfterSeconds" in i for i in db.usage_daily.index_information().values())


def test_init_db_creates_the_usage_indexes(monkeypatch):
    from backend import db as db_module

    test_db = mongomock.MongoClient()["usage_init"]
    monkeypatch.setattr(db_module, "_db", test_db)
    db_module.init_db()
    assert any(i.get("expireAfterSeconds") == 90 * 24 * 3600
               for i in test_db.usage_events.index_information().values())


# ---- the app (REST) channel -----------------------------------------------------------------

@pytest.mark.parametrize("method,path,feature", [
    ("POST", "/api/fit/weibull", "fit"),
    ("POST", "/api/rbds/analyze", "rbd_analyze"),
    ("GET", "/api/rbds/abc/analyze", "rbd_analyze"),
    ("POST", "/api/rbds", "rbd_save"),
    ("GET", "/api/rbds/abc/export.py", "export_python"),
    ("GET", "/api/rbds/abc/export.json", "export_json"),
    ("POST", "/api/strategy/optimal-replacement", "strategy_replacement"),
    ("POST", "/api/strategy/failure-finding", "strategy_failure_finding"),
    ("POST", "/api/recurrent/models/m1/overhaul", "strategy_overhaul"),
    ("POST", "/api/rcm/studies", "rcm_create"),
    ("PUT", "/api/rcm/studies/s1/tree", "rcm_edit"),
    ("PATCH", "/api/rcm/studies/s1", "rcm_update"),
    ("POST", "/api/fleet/fleets", "fleet_create"),
    ("PUT", "/api/fleet/fleets/f1/items", "fleet_items"),
    ("DELETE", "/api/fleet/tracked/t1", "fleet_delete"),
    ("POST", "/api/datasets", "dataset_upload"),
    ("POST", "/api/datasets/paste", "dataset_upload"),
    ("POST", "/api/assistant/stream", "assistant"),
    ("POST", "/api/public-links", "share_link"),
    ("PATCH", "/api/public-links/tok1", "share_link_edit"),
    ("DELETE", "/api/public-links/tok1", "share_link_revoke"),
    ("POST", "/api/billing/subscribe", "billing_subscribe"),
    ("DELETE", "/api/me/oauth-grants/g1", "mcp_disconnect"),
    ("POST", "/api/v1/fit", "fit"),
    ("GET", "/api/v1/models", "model_list"),
    ("POST", "/api/ingest/fleets/f1/usage", "fleet_ingest"),
    ("PATCH", "/api/models/m1", "model_update"),
    ("DELETE", "/api/rbds/r1", "rbd_delete"),
    # Not logged: list/item reads, operator, telemetry, previews, webhooks.
    ("GET", "/api/models", None),
    ("GET", "/api/rbds/r1", None),
    ("GET", "/api/me", None),
    ("GET", "/api/billing", None),
    ("GET", "/api/admin/usage", None),
    ("POST", "/api/metrics/event", None),
    ("POST", "/api/client-error", None),
    ("POST", "/api/columns", None),
    ("POST", "/api/rbds/validate", None),
    ("POST", "/api/stripe/webhook", None),
    ("GET", "/assets/index.js", None),
    ("POST", "/mcp", None),
])
def test_app_feature_mapping(method, path, feature):
    from backend.services.usage import app_feature

    assert app_feature(method, path) == feature


@pytest.mark.parametrize("status,outcome", [
    (200, "ok"), (201, "ok"), (304, "ok"), (402, "limit"), (429, "limit"), (403, "locked"),
    (400, "error"), (404, "error"), (422, "error"), (500, "error"), (503, "error"),
])
def test_app_outcome_from_status(status, outcome):
    from backend.services.usage import outcome_for_status

    assert outcome_for_status(status) == outcome


@pytest.fixture()
def app_env(monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["usage_app"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    from backend.main import app

    return TestClient(app), test_db


def test_app_requests_become_feature_events(app_env):
    from backend import config

    client, test_db = app_env
    assert client.post("/api/tokens", json={"name": "x"}).status_code == 402  # Pro-only
    assert client.post("/api/fit/weibull", data={}).status_code == 422
    assert client.get("/api/models").status_code == 200  # a list: not logged
    events = list(test_db.usage_events.find({}, {"_id": 0}))
    got = {(e["channel"], e["feature"], e["outcome"], e["plan"]) for e in events}
    assert got == {("app", "api_token_create", "limit", "free"), ("app", "fit", "error", "free")}
    assert all(e["uid"] == config.DEV_USER_ID and e["ms"] >= 0 for e in events)


def test_api_token_requests_are_the_api_channel(app_env):
    from backend.services import tokens

    client, test_db = app_env
    test_db.users.insert_one({"_id": "pro-1", "email": "p@example.org", "plan": "pro", "email_verified": True})
    token = tokens.create_token(test_db, "pro-1", "script")["token"]
    r = client.get("/api/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    e = test_db.usage_events.find_one({"uid": "pro-1"})
    assert (e["channel"], e["feature"], e["outcome"], e["plan"]) == ("api", "model_list", "ok", "pro")


def test_a_failing_insert_never_breaks_the_request(app_env, monkeypatch):
    from backend.services import usage

    client, test_db = app_env

    def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(test_db.usage_events, "insert_one", boom)
    assert client.post("/api/tokens", json={"name": "x"}).status_code == 402
    monkeypatch.setattr(usage, "record_for", boom)  # even past record()'s own guard
    assert client.post("/api/tokens", json={"name": "x"}).status_code == 402
    assert client.get("/api/models").status_code == 200


def test_middleware_sees_the_user_and_feature_from_worker_threads(monkeypatch):
    """Sync dependencies and endpoints run in a threadpool on a copy of the
    request context; the user and a re-labelled feature still reach the
    middleware. An exception escaping the app is logged as an error."""
    from backend import db as db_module
    from backend.services import usage

    test_db = mongomock.MongoClient()["usage_mw"]
    monkeypatch.setattr(db_module, "_db", test_db)
    monkeypatch.setattr(usage, "plan_of", lambda db, user: "pro")

    def who():
        usage.note_user({"uid": "u1"})
        return "u1"

    mini = FastAPI()
    mini.add_middleware(usage.UsageMiddleware)

    @mini.post("/api/rbds/analyze")
    def analyze(uid: str = Depends(who)):
        usage.set_feature("availability_sim")
        return {"ok": True}

    @mini.post("/api/strategy/optimal-replacement")
    def crash(uid: str = Depends(who)):
        raise RuntimeError("bug")

    @mini.post("/api/strategy/compare-two")
    def anonymous():
        return {}

    tc = TestClient(mini, raise_server_exceptions=False)
    assert tc.post("/api/rbds/analyze").status_code == 200
    assert tc.post("/api/strategy/optimal-replacement").status_code == 500
    assert tc.post("/api/strategy/compare-two").status_code == 200  # no user: not logged
    got = {(e["feature"], e["outcome"]) for e in test_db.usage_events.find({})}
    assert got == {("availability_sim", "ok"), ("strategy_replacement", "error")}


# ---- roll-up --------------------------------------------------------------------------------

DAY = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def _seed(db, monkeypatch, at=DAY):
    """Events on one day: two app accounts (one also on MCP), an operator."""
    from backend.services import usage

    monkeypatch.setattr(usage, "_now", lambda: at)
    for _ in range(3):
        usage.record(db, uid="a", channel="app", feature="fit", plan="free", ms=10)
    usage.record(db, uid="b", channel="app", feature="fit", plan="pro", ms=30)
    usage.record(db, uid="b", channel="mcp", feature="list_models", plan="pro", client="Claude", ms=5)
    usage.record(db, uid="b", channel="mcp", feature="initialize", plan="pro", client="Claude")
    usage.record(db, uid="c", channel="mcp", feature="fit_distribution", outcome="pro_only", plan="free",
                 client="Cursor")
    usage.record(db, uid="ops", channel="app", feature="fit", plan="admin")


def _daily(db):
    return sorted((d for d in db.usage_daily.find({}, {"_id": 0})), key=lambda d: repr(sorted(d.items())))


def test_rollup_is_idempotent_with_distinct_counts(monkeypatch):
    from backend.services import usage

    db = mongomock.MongoClient()["usage_rollup"]
    _seed(db, monkeypatch)
    # Not before the day (plus a short grace) is over.
    assert usage.rollup(db, now=DAY + timedelta(hours=14, minutes=58))["days"] == []
    later = DAY + timedelta(days=1)
    assert usage.rollup(db, now=later)["days"] == ["2026-10-05"]
    first = _daily(db)

    fit = [d for d in first if d.get("feature") == "fit" and d["plan"] == "free"]
    assert fit[0]["count"] == 3 and fit[0]["ms_sum"] == 30 and fit[0]["ms_n"] == 3
    acc = {(d["segment"], d["plan"]): d["accounts"] for d in first if d["kind"] == "accounts"}
    assert acc[("app", "free")] == 1 and acc[("app", "pro")] == 1 and acc[("app", "admin")] == 1
    assert acc[("mcp", "pro")] == 1 and acc[("mcp", "free")] == 1 and acc[("mcp_connect", "pro")] == 1
    assert acc[("wall_pro_only", "free")] == 1 and ("wall_pro_only", "pro") not in acc

    # Again (nothing to do), and forced (recomputed): the same documents.
    assert usage.rollup(db, now=later) == {"days": [], "weeks": []}
    assert _daily(db) == first
    usage.rollup(db, now=later, force=True)
    assert _daily(db) == first
    assert db.usage_rollups.count_documents({"kind": "day", "key": "2026-10-05"}) == 1


def test_weekly_rollup_counts_accounts_and_repeat_wall_hits(monkeypatch):
    from backend.services import usage

    db = mongomock.MongoClient()["usage_weekly"]
    monday = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)  # a Monday
    for offset, uid in [(0, "w1"), (2, "w1"), (1, "w2")]:
        monkeypatch.setattr(usage, "_now", lambda o=offset: monday + timedelta(days=o))
        usage.record(db, uid=uid, channel="mcp", feature="list_rbds", outcome="limit", plan="free")
    out = usage.rollup(db, now=monday + timedelta(days=8))
    assert "2026-10-05" in out["weeks"]
    segs = db.usage_weekly.find_one({"week": "2026-10-05"})["segments"]
    assert segs["wall_limit"] == 2 and segs["wall_any"] == 2 and segs["wall_repeat"] == 1 and segs["mcp"] == 2


# ---- conversions ----------------------------------------------------------------------------

def test_upgrade_after_an_mcp_wall_is_recorded_once(monkeypatch):
    from backend.services import billing, usage

    db = mongomock.MongoClient()["usage_conv"]
    db.users.insert_many([{"_id": "walled"}, {"_id": "plain"}])
    usage.record(db, uid="walled", channel="mcp", feature="list_rbds", outcome="limit", plan="free")
    billing.set_plan(db, "walled", "pro")
    billing.set_plan(db, "plain", "pro")
    billing.set_plan(db, "walled", "pro")  # a renewal / repeat webhook: no new conversion
    conv = {(e["uid"], e["feature"]) for e in db.usage_events.find({"channel": "billing"})}
    assert conv == {("walled", "pro_upgrade"), ("walled", "upgrade_after_mcp_lock"), ("plain", "pro_upgrade")}
    assert db.usage_events.count_documents({"channel": "billing"}) == 3

    rep = usage.report(db, days=30)
    assert rep["pro_wall"]["accounts"] == 1 and rep["pro_wall"]["limit_accounts"] == 1
    assert rep["pro_wall"]["upgraded_accounts"] == 1
    assert rep["pro_wall"]["pro_upgrades"] == 2 and rep["pro_wall"]["upgrades_after_wall"] == 1


# ---- the report and the admin endpoint ------------------------------------------------------

def test_report_shapes_and_operator_exclusion(monkeypatch):
    from backend.services import usage

    db = mongomock.MongoClient()["usage_report"]
    _seed(db, monkeypatch)
    today = DAY + timedelta(days=1, hours=3)
    _seed(db, monkeypatch, at=today)  # today: not rolled up, aggregated live
    rep = usage.report(db, days=30, now=today)

    assert rep["days"] == 30 and len(rep["daily"]) == 30 and rep["daily"][-1]["day"] == "2026-10-06"
    d5, d6 = rep["daily"][-2], rep["daily"][-1]
    for d in (d5, d6):  # rolled-up and live days agree
        assert (d["app"], d["mcp"], d["mcp_connects"]) == (4, 2, 1)
        assert (d["app_accounts"], d["mcp_accounts"], d["any_accounts"]) == (2, 2, 3)
    assert rep["totals"]["app"] == 8 and rep["totals"]["mcp"] == 4 and rep["totals"]["mcp_connects"] == 2
    tools = {t["key"]: t for t in rep["mcp_tools"]}
    assert tools["list_models"]["ok"] == 2 and tools["fit_distribution"]["pro_only"] == 2
    assert tools["list_models"]["avg_ms"] == 5
    assert rep["app_features"][0] == {"key": "fit", "count": 8, "ok": 8, "error": 0, "locked": 0,
                                      "limit": 0, "pro_only": 0}
    assert rep["mcp_outcomes"] == {"ok": 2, "error": 0, "locked": 0, "limit": 0, "pro_only": 2}
    assert {c["key"] for c in rep["mcp_clients"]} == {"Claude", "Cursor"}
    assert rep["share"]["mcp_share"] == pytest.approx(4 / 12, abs=1e-4)
    assert rep["share"]["mcp_accounts"] == 2 and rep["share"]["app_accounts"] == 2
    assert rep["share"]["mcp_and_app_accounts"] == 1 and rep["share"]["mcp_only_accounts"] == 1
    assert rep["pro_wall"]["pro_only_accounts"] == 1 and rep["pro_wall"]["repeat_accounts"] == 1
    assert rep["weekly"][-1]["week"] == "2026-10-05" and rep["weekly"][-1]["wall_pro_only"] == 1

    with_ops = usage.report(db, days=30, include_admin=True, now=today)
    assert with_ops["totals"]["app"] == 10 and with_ops["daily"][-1]["app_accounts"] == 3


def test_admin_usage_endpoint_is_operator_only(monkeypatch):
    from backend import config, db as db_module
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"ops@example.org"})
    test_db = mongomock.MongoClient()["usage_admin"]
    monkeypatch.setattr(db_module, "_db", test_db)
    tc = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": "u", "email": "u@example.org", "email_verified": True}
        assert tc.get("/api/admin/usage").status_code == 403
        app.dependency_overrides[get_current_user] = lambda: {"uid": "ops", "email": "ops@example.org", "email_verified": True}
        for days, expect in [(7, 7), (90, 90), (365, 365), (12, 30)]:
            body = tc.get(f"/api/admin/usage?days={days}").json()
            assert body["days"] == expect and len(body["daily"]) == expect
            assert set(body) >= {"totals", "daily", "weekly", "mcp_tools", "app_features", "api_features",
                                 "mcp_outcomes", "mcp_clients", "mcp_plans", "share", "pro_wall", "window_days"}
            assert body["window_days"] == min(expect, 90)
    finally:
        app.dependency_overrides.clear()


# ---- off switch -----------------------------------------------------------------------------

def test_usage_logging_off_records_nothing(env, monkeypatch):
    from backend import config
    from backend.services import billing, usage

    monkeypatch.setattr(config, "USAGE_LOGGING", False)
    _ok(_call(env.oauth[PRO], "list_models"))
    _run(env.oauth[FREE], lambda c: c.list_tools())
    assert _post_mcp(env.api[FREE]).status_code == 403
    billing.set_plan(env.db, FREE, "pro")
    assert usage.record(env.db, uid="x", channel="app", feature="fit") is False
    assert usage.rollup(env.db) == {"days": [], "weeks": []}
    assert env.db.usage_events.count_documents({}) == 0 and env.db.usage_daily.count_documents({}) == 0


def test_client_names_are_normalised():
    from backend.services.usage import normalise_client

    assert normalise_client("Claude") == "Claude"
    assert normalise_client("claude-code (reliafy)") == "Claude Code"
    assert normalise_client("Claude Code") == "Claude Code"
    assert normalise_client("Cursor") == "Cursor"
    assert normalise_client("Visual Studio Code") == "VS Code"
    assert normalise_client("") == "unknown"
    assert normalise_client("me@example.org's agent") == "other"
    assert normalise_client("My <b>Agent</b> " + "x" * 80) == "My b Agent b " + "x" * 19
