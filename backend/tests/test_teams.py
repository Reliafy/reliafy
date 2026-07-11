"""Teams: shared workspaces — membership, scoping, caps, freezing, cascade."""

import matplotlib

matplotlib.use("Agg")

import io
from datetime import datetime, timedelta, timezone

import mongomock
import numpy as np
import pandas as pd
import pytest

A = "user-a"
B = "user-b"
C = "user-c"

USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "A"},
    B: {"uid": B, "email": "b@x.com", "name": "B"},
    C: {"uid": C, "email": "c@x.com", "name": "C"},
}


def _csv() -> bytes:
    rng = np.random.default_rng(7)
    x = np.round(rng.weibull(3.0, 60) * 100, 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


@pytest.fixture()
def client(monkeypatch):
    """TestClient against mongomock with billing ON and switchable users."""
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)

    tc = TestClient(app)

    def act_as(uid):
        app.dependency_overrides[get_current_user] = lambda: USERS[uid]

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _make_pro(db, uid):
    db.users.update_one({"_id": uid}, {"$set": {"plan": "pro", "email": USERS[uid]["email"], "email_lc": USERS[uid]["email"]}}, upsert=True)


def _register(db, uid):
    """Simulate a prior login so email lookups can find the user."""
    email = USERS[uid]["email"]
    db.users.update_one(
        {"_id": uid},
        {"$set": {"email": email, "email_lc": email, "name": USERS[uid]["name"]}},
        upsert=True,
    )


def _create_team(client, name="Crew"):
    r = client.post("/api/teams", json={"name": name})
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def _save_model(client, tid=None, name="M"):
    headers = {"X-Workspace-Id": tid} if tid else {}
    return client.post(
        "/api/models",
        data={"name": name, "distribution": "weibull", "x": "t"},
        files={"file": ("d.csv", _csv(), "text/csv")},
        headers=headers,
    )


# ---- Creation gate ---------------------------------------------------------------

def test_create_requires_pro(client, monkeypatch):
    from backend import config

    client.act_as(A)
    r = client.post("/api/teams", json={"name": "Crew"})
    assert r.status_code == 402 and r.json()["code"] == "pro_required"

    _make_pro(client.db, A)
    tid = _create_team(client)
    me = client.get("/api/me").json()
    assert [t["id"] for t in me["teams"]] == [tid]
    assert me["teams"][0]["role"] == "owner"

    # Admins bypass the Pro gate.
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"b@x.com"})
    client.act_as(B)
    assert client.post("/api/teams", json={"name": "Ops"}).status_code == 200


# ---- Membership ------------------------------------------------------------------

def test_membership_and_invites(client):
    _make_pro(client.db, A)
    _register(client.db, B)
    client.act_as(A)
    tid = _create_team(client)

    # Registered email -> member immediately.
    r = client.post(f"/api/teams/{tid}/members", json={"email": "B@X.com"})
    assert r.status_code == 200 and r.json()["status"] == "added"
    # Duplicate -> 409; self -> 400.
    assert client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"}).status_code == 409
    assert client.post(f"/api/teams/{tid}/members", json={"email": "a@x.com"}).status_code == 400

    # Unregistered email -> pending invite, activates on the invitee's /api/me.
    r = client.post(f"/api/teams/{tid}/members", json={"email": "c@x.com"})
    assert r.status_code == 200 and r.json()["status"] == "invited"
    assert client.post(f"/api/teams/{tid}/members", json={"email": "c@x.com"}).status_code == 409
    client.act_as(C)
    me = client.get("/api/me").json()
    assert [t["id"] for t in me["teams"]] == [tid]
    detail = client.get(f"/api/teams/{tid}").json()
    assert detail["invites"] == [] and len(detail["members"]) == 3

    # Member can't manage; owner can remove; owner can't leave or be removed.
    client.act_as(B)
    assert client.post(f"/api/teams/{tid}/members", json={"email": "d@x.com"}).status_code == 403
    assert client.post(f"/api/teams/{tid}/leave").status_code == 200
    client.act_as(A)
    assert client.delete(f"/api/teams/{tid}/members/{C}").status_code == 200
    assert client.delete(f"/api/teams/{tid}/members/{A}").status_code == 400
    assert client.post(f"/api/teams/{tid}/leave").status_code == 400


# ---- Workspace scoping + isolation ------------------------------------------------

def test_team_workspace_scoping(client):
    _make_pro(client.db, A)
    _make_pro(client.db, B)
    client.act_as(A)
    tid = _create_team(client)
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})

    r = _save_model(client, tid)
    assert r.status_code == 200
    mid = r.json()["id"]
    doc = client.db.models.find_one({"_id": mid})
    assert doc["owner_id"] == f"team:{tid}"

    # Both members list it in the team workspace; it's writable there.
    for uid in (A, B):
        client.act_as(uid)
        listed = client.get("/api/models", headers={"X-Workspace-Id": tid}).json()["models"]
        assert [m["id"] for m in listed] == [mid]
        assert listed[0]["read_only"] is False

    # Member (not just owner) can rename team artifacts.
    client.act_as(B)
    assert client.patch(f"/api/models/{mid}", json={"name": "renamed"},
                        headers={"X-Workspace-Id": tid}).status_code == 200

    # Absent from personal lists; samples absent from team lists.
    personal = client.get("/api/models").json()["models"]
    assert mid not in [m["id"] for m in personal]
    team_list = client.get("/api/models", headers={"X-Workspace-Id": tid}).json()["models"]
    assert all(not m["is_sample"] for m in team_list)

    # Deep link from the personal workspace: readable but read-only.
    detail = client.get(f"/api/models/{mid}").json()
    assert detail["read_only"] is True
    assert client.patch(f"/api/models/{mid}", json={"name": "x"}).status_code == 403

    # Non-members: 403 on the header, 404 by id, 404 on the team.
    client.act_as(C)
    assert client.get("/api/models", headers={"X-Workspace-Id": tid}).status_code == 403
    assert client.get(f"/api/models/{mid}").status_code == 404
    assert client.get(f"/api/teams/{tid}").status_code == 404


# ---- Caps -------------------------------------------------------------------------

def test_team_workspace_is_uncapped(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "FREE_MAX_MODELS", 1)
    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 10)
    _make_pro(client.db, A)
    _make_pro(client.db, B)
    client.act_as(A)
    tid = _create_team(client)
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})

    # A member saves without limits in the team workspace...
    client.act_as(B)
    assert _save_model(client, tid, name="t1").status_code == 200
    assert _save_model(client, tid, name="t2").status_code == 200
    # ...and team artifacts don't count against their personal caps (Pro
    # accounts are uncapped anyway; the owner_id scoping is what matters).
    assert client.db.models.count_documents({"owner_id": B}) == 0


# ---- Frozen team ------------------------------------------------------------------

def test_frozen_team_is_read_only(client):
    _make_pro(client.db, A)
    _register(client.db, B)
    client.act_as(A)
    tid = _create_team(client)
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})
    assert _save_model(client, tid).status_code == 200
    mid = client.get("/api/models", headers={"X-Workspace-Id": tid}).json()["models"][0]["id"]

    # Owner's Pro lapses.
    client.db.users.update_one(
        {"_id": A},
        {"$set": {"plan_until": datetime.now(timezone.utc) - timedelta(days=1)}},
    )

    client.act_as(B)
    # Reads still work, flagged frozen + read-only.
    assert client.get("/api/teams").json()["teams"][0]["frozen"] is True
    listed = client.get("/api/models", headers={"X-Workspace-Id": tid}).json()["models"]
    assert listed[0]["read_only"] is True
    # Writes are blocked with the dedicated code.
    r = _save_model(client, tid, name="nope")
    assert r.status_code == 402 and r.json()["code"] == "team_frozen"
    r = client.patch(f"/api/models/{mid}", json={"name": "x"}, headers={"X-Workspace-Id": tid})
    assert r.status_code == 402 and r.json()["code"] == "team_frozen"


# ---- Team artifacts compose -------------------------------------------------------

def test_team_rcm_and_tracked_items(client):
    _make_pro(client.db, A)
    client.act_as(A)
    tid = _create_team(client)
    h = {"X-Workspace-Id": tid}

    # Team model -> team RCM study citing it as evidence resolves live.
    mid = _save_model(client, tid).json()["id"]
    sid = client.post("/api/rcm/studies", json={"name": "S"}, headers=h).json()["id"]
    r = client.put(f"/api/rcm/studies/{sid}/tree", headers=h, json={"functions": [
        {"text": "Fn", "failures": [{"text": "FF", "modes": [
            {"text": "M", "consequence": "operational",
             "decision": {"outcome": "rtf", "rtf_basis": "random",
                          "evidence": {"type": "model", "id": mid}}}]}]},
    ]})
    assert r.status_code == 200
    decision = r.json()["functions"][0]["failures"][0]["modes"][0]["decision"]
    assert decision["status"] in ("supported", "contradicted", "inconclusive")
    assert decision.get("artifact_name")  # the team model resolved

    # Tracked items created in the team workspace are team-owned and cascade.
    dm = client.post("/api/degradation/models", headers=h, data={
        "name": "D", "i": "i", "x": "x", "y": "y", "threshold": "8",
    }, files={"file": ("d.csv", _deg_csv(), "text/csv")})
    assert dm.status_code == 200, dm.json()
    dmid = dm.json()["id"]
    item = client.post(f"/api/degradation/models/{dmid}/items", headers=h,
                       json={"name": "unit-1", "measurements": [{"t": 100, "y": 1.0}, {"t": 500, "y": 2.5}]})
    assert item.status_code == 200, item.json()
    assert client.db.tracked_items.find_one({"_id": item.json()["id"]})["owner_id"] == f"team:{tid}"
    assert client.delete(f"/api/degradation/models/{dmid}", headers=h).status_code == 200
    assert client.db.tracked_items.count_documents({"model_id": dmid}) == 0


def _deg_csv() -> bytes:
    rows = []
    rng = np.random.default_rng(3)
    for i in range(6):
        slope = 0.004 + rng.normal(0, 0.0005)
        for t in (200, 800, 1400, 2000):
            rows.append({"i": f"u{i}", "x": t, "y": round(slope * t + rng.normal(0, 0.05), 3)})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


# ---- Delete cascade ---------------------------------------------------------------

def test_team_delete_cascades(client):
    _make_pro(client.db, A)
    client.act_as(A)
    tid = _create_team(client)
    h = {"X-Workspace-Id": tid}
    _save_model(client, tid)
    client.post("/api/rcm/studies", json={"name": "S"}, headers=h)
    principal = f"team:{tid}"
    assert client.db.models.count_documents({"owner_id": principal}) == 1
    assert client.db.datasets.count_documents({"owner_id": principal}) == 1

    assert client.delete(f"/api/teams/{tid}").status_code == 200
    for coll in ("models", "datasets", "rcm_studies"):
        assert client.db[coll].count_documents({"owner_id": principal}) == 0
    assert client.get("/api/teams").json()["teams"] == []
    # The workspace header is now invalid.
    assert client.get("/api/models", headers=h).status_code == 403


# ---- Pro-only editing --------------------------------------------------------------

def test_free_members_are_view_only(client):
    _make_pro(client.db, A)
    _register(client.db, B)  # B stays free
    client.act_as(A)
    tid = _create_team(client)
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})
    mid = _save_model(client, tid).json()["id"]

    client.act_as(B)
    h = {"X-Workspace-Id": tid}
    # Reads work, flagged view-only.
    listed = client.get("/api/models", headers=h).json()["models"]
    assert listed[0]["read_only"] is True
    assert client.get("/api/teams").json()["teams"][0]["can_edit"] is False
    # Writes are blocked with the upgrade nudge.
    r = _save_model(client, tid, name="nope")
    assert r.status_code == 402 and r.json()["code"] == "member_pro_required"
    r = client.patch(f"/api/models/{mid}", json={"name": "x"}, headers=h)
    assert r.status_code == 402 and r.json()["code"] == "member_pro_required"
    # Personal workspace is unaffected.
    assert _save_model(client, name="own").status_code == 200

    # Upgrading unlocks editing.
    _make_pro(client.db, B)
    assert client.patch(f"/api/models/{mid}", json={"name": "renamed"}, headers=h).status_code == 200


def test_free_members_edit_when_billing_disabled(client, monkeypatch):
    from backend import config

    _make_pro(client.db, A)
    _register(client.db, B)
    client.act_as(A)
    tid = _create_team(client)
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    client.act_as(B)
    assert _save_model(client, tid).status_code == 200
