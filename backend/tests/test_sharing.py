"""Direct sharing: view-only grants, hiding, revocation, transitive references."""

import matplotlib

matplotlib.use("Agg")

import io

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
    rng = np.random.default_rng(11)
    x = np.round(rng.weibull(3.0, 60) * 100, 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


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
        # Simulate the /api/me profile upsert so email lookups work.
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


def _save_model(client, name="M"):
    r = client.post(
        "/api/models",
        data={"name": name, "distribution": "weibull", "x": "t"},
        files={"file": ("d.csv", _csv(), "text/csv")},
    )
    assert r.status_code == 200, r.json()
    return r.json()


def _share(client, collection, artifact_id, email):
    return client.post("/api/shares", json={
        "collection": collection, "artifact_id": artifact_id, "email": email,
    })


# ---- Happy path + errors -----------------------------------------------------

def test_share_model_happy_path(client):
    client.act_as(B)  # register B's email
    client.act_as(A)
    model = _save_model(client)
    r = _share(client, "models", model["id"], "B@X.com")
    assert r.status_code == 200

    # Recipient sees it inline: tagged, read-only; get-by-id works.
    client.act_as(B)
    rows = client.get("/api/models").json()["models"]
    mine = next(m for m in rows if m["id"] == model["id"])
    assert mine["read_only"] is True and mine["shared_by"] == "a@x.com"
    assert client.get(f"/api/models/{model['id']}").status_code == 200
    # Evaluate reaches the compute layer (a plain distribution has no covariate
    # functions, so 422 with that message — NOT a 404 — proves access + refit).
    r = client.post(f"/api/models/{model['id']}/evaluate", json={})
    assert r.status_code == 422 and "no covariate functions" in r.json()["detail"]

    # Recipient mutations are blocked.
    assert client.patch(f"/api/models/{model['id']}", json={"name": "x"}).status_code == 403

    # A third user sees nothing.
    client.act_as(C)
    assert client.get(f"/api/models/{model['id']}").status_code == 404


def test_share_errors(client):
    client.act_as(B)
    client.act_as(A)
    model = _save_model(client)
    # Unknown email -> 404 with a clear message.
    r = _share(client, "models", model["id"], "ghost@nowhere.com")
    assert r.status_code == 404 and "No Reliafy account" in r.json()["detail"]
    # Self-share -> 400; sample -> 400; unknown collection -> 400.
    assert _share(client, "models", model["id"], "a@x.com").status_code == 400
    sample = client.db.models.find_one({"owner_id": "__samples__"})
    if sample:
        assert _share(client, "models", sample["_id"], "b@x.com").status_code == 400
    assert _share(client, "nonsense", model["id"], "b@x.com").status_code == 400
    # Someone else's artifact -> 404.
    client.act_as(B)
    assert _share(client, "models", model["id"], "c@x.com").status_code == 404
    # Duplicate share is idempotent.
    client.act_as(A)
    assert _share(client, "models", model["id"], "b@x.com").status_code == 200
    assert _share(client, "models", model["id"], "b@x.com").status_code == 200
    assert client.db.shares.count_documents({"artifact_id": model["id"]}) == 1


def test_hide_revoke_and_reshare(client):
    client.act_as(B)
    client.act_as(A)
    model = _save_model(client)
    _share(client, "models", model["id"], "b@x.com")

    # Recipient "deletes" -> hidden for them only.
    client.act_as(B)
    assert client.delete(f"/api/models/{model['id']}").status_code == 200
    assert model["id"] not in [m["id"] for m in client.get("/api/models").json()["models"]]
    client.act_as(A)
    assert client.get(f"/api/models/{model['id']}").status_code == 200
    assert len(client.get(f"/api/shares?collection=models&artifact_id={model['id']}").json()["shares"]) == 1

    # Re-sharing un-hides.
    _share(client, "models", model["id"], "b@x.com")
    client.act_as(B)
    assert model["id"] in [m["id"] for m in client.get("/api/models").json()["models"]]

    # Revoke -> recipient loses access.
    client.act_as(A)
    share_id = client.get(f"/api/shares?collection=models&artifact_id={model['id']}").json()["shares"][0]["id"]
    assert client.delete(f"/api/shares/{share_id}").status_code == 200
    client.act_as(B)
    assert client.get(f"/api/models/{model['id']}").status_code == 404


# ---- Transitive references ----------------------------------------------------

def test_shared_rcm_study_resolves_and_links_open(client):
    client.act_as(B)
    client.act_as(A)
    model = _save_model(client)
    sid = client.post("/api/rcm/studies", json={"name": "S"}).json()["id"]
    r = client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": [
        {"text": "Fn", "failures": [{"text": "FF", "modes": [
            {"text": "M", "consequence": "operational",
             "decision": {"outcome": "rtf", "rtf_basis": "random",
                          "evidence": {"type": "model", "id": model["id"]}}}]}]},
    ]})
    author_status = r.json()["functions"][0]["failures"][0]["modes"][0]["decision"]["status"]
    _share(client, "rcm_studies", sid, "b@x.com")

    client.act_as(B)
    # The study resolves with the author's evidence statuses.
    study = client.get(f"/api/rcm/studies/{sid}").json()
    decision = study["functions"][0]["failures"][0]["modes"][0]["decision"]
    assert decision["status"] == author_status
    assert study["read_only"] is True
    # Evidence link opens transitively (model + its dataset).
    assert client.get(f"/api/models/{model['id']}").status_code == 200
    assert client.get(f"/api/datasets/{model['dataset_id']}").status_code == 200
    # Edits are blocked.
    assert client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": []}).status_code == 403

    # Liveness: the author re-links to new evidence; the recipient sees it.
    client.act_as(A)
    model2 = _save_model(client, name="M2")
    client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": [
        {"text": "Fn", "failures": [{"text": "FF", "modes": [
            {"text": "M", "consequence": "operational",
             "decision": {"outcome": "rtf", "rtf_basis": "random",
                          "evidence": {"type": "model", "id": model2["id"]}}}]}]},
    ]})
    client.act_as(B)
    assert client.get(f"/api/models/{model2['id']}").status_code == 200

    # No leak: embedding someone's artifact id in your OWN study doesn't grant access.
    client.act_as(C)
    sid_c = client.post("/api/rcm/studies", json={"name": "steal"}).json()["id"]
    client.put(f"/api/rcm/studies/{sid_c}/tree", json={"functions": [
        {"text": "Fn", "failures": [{"text": "FF", "modes": [
            {"text": "M", "consequence": "operational",
             "decision": {"outcome": "rtf", "rtf_basis": "random",
                          "evidence": {"type": "model", "id": model["id"]}}}]}]},
    ]})
    study_c = client.get(f"/api/rcm/studies/{sid_c}").json()
    assert study_c["functions"][0]["failures"][0]["modes"][0]["decision"]["status"] == "stale"
    assert client.get(f"/api/models/{model['id']}").status_code == 404


def test_shared_degradation_model_with_items(client):
    client.act_as(B)
    client.act_as(A)
    rows = []
    rng = np.random.default_rng(5)
    for i in range(6):
        slope = 0.004 + rng.normal(0, 0.0005)
        for t in (200, 800, 1400, 2000):
            rows.append({"i": f"u{i}", "x": t, "y": round(slope * t + rng.normal(0, 0.05), 3)})
    buf = io.StringIO(); pd.DataFrame(rows).to_csv(buf, index=False)
    dm = client.post("/api/degradation/models", data={
        "name": "D", "i": "i", "x": "x", "y": "y", "threshold": "8",
    }, files={"file": ("d.csv", buf.getvalue().encode(), "text/csv")}).json()
    item = client.post(f"/api/degradation/models/{dm['id']}/items",
                       json={"name": "unit-1", "measurements": [{"t": 100, "y": 1.0}, {"t": 500, "y": 2.5}]}).json()
    _share(client, "degradation_models", dm["id"], "b@x.com")

    client.act_as(B)
    detail = client.get(f"/api/degradation/models/{dm['id']}").json()
    assert detail["read_only"] is True
    # The owner's tracked items ride along, read-only.
    assert [it["id"] for it in detail["items"]] == [item["id"]]
    assert detail["items"][0]["read_only"] is True
    r = client.post(f"/api/degradation/models/{dm['id']}/items/{item['id']}/measurements",
                    json={"t": 900, "y": 4.0})
    assert r.status_code in (403, 404)
    # Registering their own item on a shared model is NOT allowed (not writable).
    # (create_item scopes the model lookup to the write owner.)
    r = client.post(f"/api/degradation/models/{dm['id']}/items",
                    json={"name": "mine", "measurements": [{"t": 1, "y": 0.1}]})
    assert r.status_code == 404


def test_shares_do_not_count_against_caps(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "FREE_MAX_MODELS", 1)
    client.act_as(B)
    client.act_as(A)
    model = _save_model(client)
    _share(client, "models", model["id"], "b@x.com")
    client.act_as(B)
    # The shared model doesn't consume B's only free slot.
    assert _save_model(client, name="own")  # 200 asserted inside
