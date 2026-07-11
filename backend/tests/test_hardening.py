"""Phase-1 hardening: fail-hard DB, upload cap, emails, telemetry, admin stats."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

A = "user-a"
B = "user-b"

USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "A"},
    B: {"uid": B, "email": "b@x.com", "name": "B"},
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)

    tc = TestClient(app)

    def act_as(uid):
        app.dependency_overrides[get_current_user] = lambda: USERS[uid]
        email = USERS[uid]["email"]
        test_db.users.update_one(
            {"_id": uid},
            {"$set": {"email": email, "email_lc": email, "name": USERS[uid]["name"]}},
            upsert=True,
        )

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def sent(monkeypatch):
    """Capture outbound emails instead of touching SMTP."""
    from backend.services import email as email_service

    captured = []
    monkeypatch.setattr(email_service, "send", lambda to, subject, body: captured.append(
        {"to": to, "subject": subject, "body": body}
    ))
    return captured


def _csv() -> bytes:
    rng = np.random.default_rng(3)
    x = np.round(rng.weibull(3.0, 40) * 100, 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


# ---- Fail-hard DB ----------------------------------------------------------------

def test_db_refuses_simulator_when_uri_configured(monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "MONGODB_URI", "mongodb://127.0.0.1:9/down")
    monkeypatch.setattr(config, "MONGODB_TIMEOUT_MS", 200)
    monkeypatch.setattr(db, "_db", None)
    monkeypatch.setattr(db, "_simulated", False)
    with pytest.raises(RuntimeError, match="unreachable"):
        db._connect()


def test_db_simulator_without_uri(monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "MONGODB_URI", None)
    monkeypatch.setattr(db, "_db", None)
    monkeypatch.setattr(db, "_simulated", False)
    handle = db._connect()
    assert handle is not None and db.is_simulated()


# ---- Upload cap -------------------------------------------------------------------

def test_upload_size_cap(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    client.act_as(A)
    big = b"t\n" + b"1.0\n" * 2000
    r = client.post("/api/datasets", files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 422 and "too large" in r.json()["detail"]
    # Under the cap is fine.
    r = client.post("/api/datasets", files={"file": ("ok.csv", b"t\n1\n2\n", "text/csv")})
    assert r.status_code == 200


# ---- Email notifications ----------------------------------------------------------

def test_team_invite_emails(client, sent):
    client.act_as(B)
    client.act_as(A)
    tid = client.post("/api/teams", json={"name": "Crew"}).json()["id"]

    # Registered user -> "added" email.
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})
    assert sent[-1]["to"] == "b@x.com" and "added" in sent[-1]["subject"].lower()
    assert "Crew" in sent[-1]["subject"]

    # Unregistered -> pending-invite email with a signup nudge.
    client.post(f"/api/teams/{tid}/members", json={"email": "new@x.com"})
    assert sent[-1]["to"] == "new@x.com" and "invited" in sent[-1]["subject"].lower()
    assert "account" in sent[-1]["body"].lower()


def test_share_email(client, sent):
    client.act_as(B)
    client.act_as(A)
    r = client.post(
        "/api/models",
        data={"name": "M", "distribution": "weibull", "x": "t"},
        files={"file": ("d.csv", _csv(), "text/csv")},
    )
    mid = r.json()["id"]
    client.post("/api/shares", json={"collection": "models", "artifact_id": mid, "email": "b@x.com"})
    assert sent[-1]["to"] == "b@x.com"
    assert "shared" in sent[-1]["subject"].lower()
    assert f"/modelling/m/{mid}" in sent[-1]["body"]
    # Duplicate share doesn't re-send.
    n = len(sent)
    client.post("/api/shares", json={"collection": "models", "artifact_id": mid, "email": "b@x.com"})
    assert len(sent) == n


def test_email_noop_when_unconfigured():
    from backend.services import email as email_service

    assert not email_service.enabled()
    email_service.send("x@y.com", "s", "b")  # must not raise


# ---- Telemetry + admin stats -------------------------------------------------------

def test_telemetry_endpoints(client):
    assert client.post("/api/client-error", json={"message": "boom", "stack": "x", "path": "/rcm"}).status_code == 200
    assert client.post("/api/metrics/event", json={"name": "pageview", "path": "/"}).status_code == 200


def test_admin_stats_gated(client, monkeypatch):
    from backend import config

    client.act_as(A)
    assert client.get("/api/admin/stats").status_code == 403
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"a@x.com"})
    data = client.get("/api/admin/stats").json()
    assert data["users_total"] >= 1
    assert set(data["artifacts"]) == {
        "datasets", "models", "rbds", "degradation_models",
        "tracked_items", "strategy_analyses", "rcm_studies",
    }


# ---- Optimistic locking + attribution ----------------------------------------------

def test_rcm_tree_conflict_409(client):
    client.act_as(A)
    sid = client.post("/api/rcm/studies", json={"name": "S"}).json()["id"]
    tree = {"functions": [{"text": "Fn", "failures": []}]}
    first = client.put(f"/api/rcm/studies/{sid}/tree", json=tree)
    assert first.status_code == 200
    loaded_at = first.json()["updated_at"]

    # A save carrying the current stamp succeeds and bumps updated_at.
    r = client.put(f"/api/rcm/studies/{sid}/tree",
                   json={**tree, "expected_updated_at": loaded_at})
    assert r.status_code == 200
    # Reusing the stale stamp now conflicts.
    r = client.put(f"/api/rcm/studies/{sid}/tree",
                   json={**tree, "expected_updated_at": loaded_at})
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    # Without the precondition it's last-write-wins (backwards compatible).
    assert client.put(f"/api/rcm/studies/{sid}/tree", json=tree).status_code == 200


def test_rbd_conflict_and_attribution(client):
    client.act_as(A)
    graph = {"nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"}],
             "edges": [{"source": "input", "target": "output"}]}
    saved = client.post("/api/rbds", json={"name": "D", "graph": graph}).json()
    assert saved["updated_by"] == "A"
    loaded_at = saved["updated_at"]

    ok = client.post("/api/rbds", json={"name": "D2", "graph": graph, "id": saved["id"],
                                        "expected_updated_at": loaded_at})
    assert ok.status_code == 200
    stale = client.post("/api/rbds", json={"name": "D3", "graph": graph, "id": saved["id"],
                                           "expected_updated_at": loaded_at})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"
