"""Saved reliability and maintainability predictions count toward the Free
plan's storage limits (as many as RBDs and fault trees), in the web app, over
MCP and over REST; shared samples never count."""

from __future__ import annotations

import mongomock
import pytest

from backend.tests.test_mcp import _call, _err, _ok
from backend.tests.test_mcp_plans import FREE, PRO, UPGRADE, env  # noqa: F401
from backend.tests.test_reliability_prediction import LINES as RP_LINES

# MCP switched on (on the cloud it is off by default).
pytestmark = pytest.mark.usefixtures("mcp_on")

MT_LINES = [{"name": "A", "failure_rate": 10, "elements": {"replace": 1}},
            {"name": "B", "failure_rate": 30, "elements": {"isolation": 1, "replace": 2}}]

# kind -> (web save route, web body, MCP save action, MCP arguments, noun in the message)
KINDS = {
    "reliability_predictions": (
        "/api/predictions", {"name": "Box", "inputs": {"lines": RP_LINES, "environment": "GF"}},
        "prediction_save", {"name": "Box", "lines": RP_LINES, "environment": "GF"},
        "reliability prediction"),
    "maintainability_predictions": (
        "/api/maintainability/predictions", {"name": "Box", "inputs": {"unit": "hours", "lines": MT_LINES}},
        "maintainability_save", {"name": "Box", "lines": MT_LINES},
        "maintainability prediction"),
}


def test_both_kinds_are_capped_like_rbds_and_fault_trees():
    from backend import config
    from backend.services import billing

    caps = billing.plan_caps("free")
    assert caps["reliability_predictions"] == caps["maintainability_predictions"] == caps["rbds"] \
        == caps["fault_trees"] == config.FREE_MAX_RBDS
    assert billing.plan_caps("pro") is None


@pytest.fixture()
def web(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["prediction_caps"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)  # a sample of each kind, which must not count
    test_db.users.insert_many([
        {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
        {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro", "email_verified": True},
    ])
    who = {"uid": FREE}
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": who["uid"], "email": f"{who['uid']}@example.org", "name": "U", "email_verified": True}
    tc = TestClient(app)
    tc.who = who
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("kind", KINDS)
def test_the_web_save_refuses_past_the_free_cap(web, kind):
    route, body, *_, noun = KINDS[kind]
    assert web.db[kind].count_documents({}) >= 1  # the sample is there and is not the user's

    first = web.post(route, json=body)
    assert first.status_code == 200, first.text
    over = web.post(route, json={**body, "name": "Second"})
    assert over.status_code == 402
    assert over.json() == {
        "detail": f"You've reached the free-plan limit of 1 saved {noun}. "
                  f"Upgrade to Pro for unlimited {noun}s.",
        "code": "cap", "upgrade": True}
    assert web.db[kind].count_documents({"owner_id": FREE}) == 1
    # Editing the one you have is still allowed.
    assert web.patch(f"{route}/{first.json()['id']}", json={"name": "Renamed"}).status_code == 200

    # The Billing page counts the user's own, not the sample.
    usage = web.get("/api/billing").json()
    assert usage["usage"][kind] == 1 and usage["caps"][kind] == 1

    # Pro has no cap.
    web.who["uid"] = PRO
    for i in range(3):
        assert web.post(route, json={**body, "name": f"P{i}"}).status_code == 200
    assert web.get("/api/billing").json()["usage"][kind] == 3


@pytest.mark.parametrize("kind", KINDS)
def test_the_mcp_save_refuses_past_the_free_cap(env, kind):  # noqa: F811
    from backend.services import samples

    samples.seed_samples(env.db)
    *_, action, args, noun = KINDS[kind]
    free = env.oauth[FREE]
    assert _ok(_call(free, "change", {"action": action, **args}))["saved"]
    msg = _err(_call(free, "change", {"action": action, **args, "name": "Second"}))
    assert f"Free plan's limit of 1 saved {noun}s" in msg and "doesn't reset" in msg and UPGRADE in msg
    assert env.db[kind].count_documents({"owner_id": FREE}) == 1
    storage = _ok(_call(free, "get", {"kind": "account"}))["storage"][kind]
    assert storage == {"used": 1, "limit": 1}

    pro = env.oauth[PRO]
    for i in range(3):
        assert _ok(_call(pro, "change", {"action": action, **args, "name": f"P{i}"}))["saved"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_rest_save_refuses_past_the_free_cap(env, kind, monkeypatch):  # noqa: F811
    """REST is the MCP action: the same refusal (a Free user given API access
    for the test, as REST is otherwise Pro)."""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import billing, tokens

    monkeypatch.setattr(billing, "api_access_allowed", lambda db, user: True)
    *_, action, args, noun = KINDS[kind]
    token = tokens.create_token(env.db, FREE, "api")["token"]
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(f"/api/v1/change/{action}", json=args, headers=headers).status_code == 200
    r = client.post(f"/api/v1/change/{action}", json={**args, "name": "Second"}, headers=headers)
    assert r.status_code >= 400 and f"limit of 1 saved {noun}s" in r.text
