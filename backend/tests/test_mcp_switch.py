"""The MCP connector's on/off switch (backend/services/mcp_switch.py): its
default (off on the cloud, on self-hosted), the MCP_ENABLED override, the
refusals at /mcp and the connector-only OAuth endpoints (fast, before any
authentication), the REST API left alone, the first Pro checkout turning it
on, and the Admin API."""

import logging

import mongomock
import pytest
from fastapi.testclient import TestClient

U = "pro-to-be"
ADMIN = {"uid": "op-1", "email": "op@example.com", "name": "Op", "email_verified": True}
NOT_ADMIN = {"uid": "u-2", "email": "u2@example.com", "name": "U2", "email_verified": True}

OAUTH_PATHS = [
    ("POST", "/oauth/register"),
    ("GET", "/oauth/authorize"),
    ("GET", "/oauth/authorize/request"),
    ("POST", "/oauth/authorize/decision"),
    ("POST", "/oauth/token"),
]


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import ingest as ingest_router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)  # the cloud
    monkeypatch.setattr(config, "ADMIN_EMAILS", {ADMIN["email"]})
    test_db = mongomock.MongoClient()["reliafy_switch_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()

    pushes = []
    from backend.services import push

    monkeypatch.setattr(push, "send", lambda title, message, **kw: pushes.append((title, message)) or True)

    class Env:
        db = test_db
        client = TestClient(app, follow_redirects=False)
        pushed = pushes

        @staticmethod
        def act_as(user):
            if user is None:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = lambda: user

    try:
        yield Env
    finally:
        app.dependency_overrides.clear()


def _checkout_pro(uid=U, cs="cs_1"):
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": cs, "customer": f"cus_{uid}", "subscription": f"sub_{uid}",
                                "metadata": {"uid": uid, "kind": "pro"}}}}


# ---- default and override -----------------------------------------------------------

def test_off_by_default_on_the_cloud(env):
    from backend.services import mcp_switch

    assert mcp_switch.enabled(env.db) is False
    assert env.client.get("/api/config").json()["mcp"] is False


def test_on_by_default_self_hosted(env, monkeypatch):
    from backend import config
    from backend.services import mcp_switch

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    assert mcp_switch.enabled(env.db) is True
    assert env.client.get("/api/config").json()["mcp"] is True


def test_stored_switch_wins_over_the_default(env, monkeypatch):
    from backend import config
    from backend.services import mcp_switch

    mcp_switch.set_enabled(env.db, True, "op@example.com", "test")
    assert mcp_switch.enabled(env.db) is True
    # Self-hosted, turned off by its operator: stays off.
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    mcp_switch.set_enabled(env.db, False, "op@example.com", "test")
    assert mcp_switch.enabled(env.db) is False


@pytest.mark.parametrize("forced", [True, False])
def test_env_override_both_ways(env, monkeypatch, forced):
    from backend import config
    from backend.services import mcp_switch

    mcp_switch.set_enabled(env.db, not forced, "op@example.com", "test")
    monkeypatch.setattr(config, "MCP_ENABLED", forced)
    assert mcp_switch.enabled(env.db) is forced
    state = mcp_switch.state(env.db)
    assert state["enabled"] is forced and state["override"] is forced and state["stored"] is (not forced)


def test_env_override_parsing():
    from backend.config import _tristate

    for raw, want in [("true", True), ("ON", True), ("1", True), ("yes", True), ("false", False),
                      ("off", False), ("0", False), ("", None), (None, None), ("maybe", None)]:
        assert _tristate(raw) is want, raw


def test_reads_are_cached_and_a_local_change_clears_the_cache(env):
    from backend.services import mcp_switch

    assert mcp_switch.enabled(env.db) is False
    # Another instance turns it on: this one keeps its cached answer...
    env.db.app_settings.update_one({"_id": "mcp"}, {"$set": {"enabled": True}}, upsert=True)
    assert mcp_switch.enabled(env.db) is False
    # ...until the cache lapses.
    mcp_switch._cache = (mcp_switch._cache[0] - mcp_switch.CACHE_SECONDS - 1, False)
    assert mcp_switch.enabled(env.db) is True
    # A change made here is seen at once.
    mcp_switch.set_enabled(env.db, False, "op@example.com", "test")
    assert mcp_switch.enabled(env.db) is False


# ---- refusals while off ---------------------------------------------------------------

def test_mcp_refuses_fast_before_auth(env, caplog):
    caplog.set_level(logging.INFO, logger="backend.services.mcp_switch")
    for headers in ({}, {"Authorization": "Bearer rlf_secret-token-value"}):
        r = env.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers)
        assert r.status_code == 503
        assert "isn't switched on" in r.json()["detail"] and "hello@reliafy.com" in r.json()["detail"]
        assert "www-authenticate" not in r.headers  # no OAuth sign-in starts
    assert env.client.get("/mcp").status_code == 503
    refusals = [rec for rec in caplog.records if "refused" in rec.getMessage()]
    assert len(refusals) == 3 and all(rec.levelno == logging.INFO for rec in refusals)
    assert not any("rlf_" in rec.getMessage() for rec in caplog.records)


@pytest.mark.parametrize("method,path", OAUTH_PATHS)
def test_oauth_connector_endpoints_refuse_when_off(env, method, path):
    r = env.client.request(method, path)  # no auth, no body
    assert r.status_code == 403
    assert "switched on" in r.text and "hello@reliafy.com" in r.text and "try again" not in r.text
    assert r.headers["cache-control"] == "no-store"


def test_oauth_refusals_keep_open_cors(env):
    r = env.client.post("/oauth/token", headers={"Origin": "https://inspector.example"})
    assert r.status_code == 403 and r.headers["access-control-allow-origin"] == "*"
    assert r.json()["error"] == "access_denied"


def test_discovery_and_revocation_still_work_when_off(env):
    assert env.client.get("/.well-known/oauth-authorization-server").status_code == 200
    assert env.client.get("/.well-known/oauth-protected-resource/mcp").status_code == 200
    # Revocation answers as ever (an unknown client is refused by OAuth, not the switch).
    r = env.client.post("/oauth/revoke", data={"token": "x", "client_id": "nobody"})
    assert r.status_code != 403 and "isn't switched on" not in r.text


def test_oauth_endpoints_proceed_when_on(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_ENABLED", True)
    r = env.client.post("/oauth/token", data={"grant_type": "password"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
    r = env.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401 and "www-authenticate" in r.headers


def test_rest_api_unaffected_when_off(env):
    from backend.services import billing, mcp_switch

    user = {"uid": U, "email": "pro@example.org", "name": "P", "email_verified": True}
    env.db.users.insert_one({"_id": U, "email": user["email"]})
    billing.set_plan(env.db, U, "pro")
    env.act_as(user)
    raw = env.client.post("/api/tokens", json={"name": "cron", "scopes": ["read"]}).json()["token"]
    env.act_as(None)
    assert mcp_switch.enabled(env.db) is False
    auth = {"Authorization": f"Bearer {raw}"}
    r = env.client.get("/api/v1/models", headers=auth)
    assert r.status_code == 200, r.text
    # The same token at /mcp is switched off.
    assert env.client.post("/mcp", json={}, headers=auth).status_code == 503


# ---- turning on by itself -------------------------------------------------------------

def test_first_pro_checkout_turns_it_on_once(env):
    from backend.routers.billing import _handle_event
    from backend.services import mcp_switch

    _handle_event(env.db, _checkout_pro())
    assert mcp_switch.enabled(env.db) is True
    doc = env.db.app_settings.find_one({"_id": "mcp"})
    assert doc["enabled"] is True and doc["changed_by"] == U and doc["reason"] == "first Pro subscriber"
    assert env.pushed == [("MCP connector switched on", "MCP connector switched on: a new Pro subscriber")]
    assert not any("@" in title + message for title, message in env.pushed)

    # A replayed webhook, a renewal and a second subscriber do nothing more.
    _handle_event(env.db, _checkout_pro())
    _handle_event(env.db, {"type": "customer.subscription.updated",
                           "data": {"object": {"id": f"sub_{U}", "customer": f"cus_{U}", "status": "active",
                                               "items": {"data": []}}}})
    _handle_event(env.db, _checkout_pro("second", "cs_2"))
    assert len(env.pushed) == 1
    assert env.db.app_settings.find_one({"_id": "mcp"})["changed_by"] == U


def test_replay_after_switching_off_leaves_it_off(env):
    from backend.routers.billing import _handle_event
    from backend.services import mcp_switch

    _handle_event(env.db, _checkout_pro())
    mcp_switch.set_enabled(env.db, False, "op@example.com", "off again")
    _handle_event(env.db, _checkout_pro())  # the user is Pro already
    assert mcp_switch.enabled(env.db) is False and len(env.pushed) == 1


def test_pro_checkout_never_overrides_env_off(env, monkeypatch):
    from backend import config
    from backend.routers.billing import _handle_event

    monkeypatch.setattr(config, "MCP_ENABLED", False)
    _handle_event(env.db, _checkout_pro())
    assert env.db.app_settings.find_one({"_id": "mcp"}) is None and env.pushed == []


def test_already_on_does_nothing(env):
    from backend.routers.billing import _handle_event
    from backend.services import mcp_switch

    mcp_switch.set_enabled(env.db, True, "op@example.com", "a free user asked")
    _handle_event(env.db, _checkout_pro())
    assert env.db.app_settings.find_one({"_id": "mcp"})["reason"] == "a free user asked"
    assert env.pushed == []


def test_credit_pack_does_not_turn_it_on(env):
    from backend.routers.billing import _handle_event
    from backend.services import mcp_switch

    _handle_event(env.db, {"type": "checkout.session.completed",
                           "data": {"object": {"id": "cs_p", "metadata": {"uid": U, "kind": "pack",
                                                                           "grant_cents": "500"}}}})
    assert mcp_switch.enabled(env.db) is False and env.pushed == []


# ---- admin API ---------------------------------------------------------------------

def test_admin_api_reads_and_sets_the_switch(env):
    env.act_as(ADMIN)
    state = env.client.get("/api/admin/mcp").json()
    assert state["enabled"] is False and state["stored"] is None and state["default"] is False
    assert state["override"] is None and state["changed_at"] is None

    r = env.client.post("/api/admin/mcp", json={"enabled": True, "reason": "a free user asked"})
    assert r.status_code == 200
    state = r.json()
    assert state["enabled"] is True and state["changed_by"] == ADMIN["email"]
    assert state["reason"] == "a free user asked" and state["changed_at"]
    # Takes effect at once on this process.
    env.act_as(None)
    assert env.client.post("/mcp", json={}).status_code == 401

    env.act_as(ADMIN)
    state = env.client.post("/api/admin/mcp", json={"enabled": False}).json()
    assert state["enabled"] is False and state["reason"] == "set on the Admin page"


def test_admin_api_is_operator_only(env):
    env.act_as(NOT_ADMIN)
    assert env.client.get("/api/admin/mcp").status_code == 403
    assert env.client.post("/api/admin/mcp", json={"enabled": True}).status_code == 403
    assert env.db.app_settings.find_one({"_id": "mcp"}) is None
    env.act_as(None)
    assert env.client.get("/api/admin/mcp").status_code == 401
