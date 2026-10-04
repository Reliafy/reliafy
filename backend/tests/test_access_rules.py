"""Access rules: shared references stay inside the sharer's data, references
are checked on save, email-based trust needs a verified address, API token
scopes, session revocation, OAuth registration limits and refresh replays,
and team / invite email content."""

import matplotlib

matplotlib.use("Agg")

import io
import logging
from datetime import datetime, timedelta, timezone

import mongomock
import numpy as np
import pandas as pd
import pytest

A, B, C, D = "user-a", "user-b", "user-c", "user-d"

USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True},
    B: {"uid": B, "email": "b@x.com", "name": "B", "email_verified": True},
    C: {"uid": C, "email": "c@x.com", "name": "C", "email_verified": True},
    # Signed up with email/password and hasn't followed the link yet.
    D: {"uid": D, "email": "d@x.com", "name": "D", "email_verified": False},
}


def _csv(seed=11) -> bytes:
    rng = np.random.default_rng(seed)
    x = np.round(rng.weibull(3.0, 40) * 100, 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import ingest as ingest_router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["reliafy_access_rules"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()

    tc = TestClient(app)

    def act_as(uid):
        user = USERS[uid]
        app.dependency_overrides[get_current_user] = lambda: dict(user)
        test_db.users.update_one(
            {"_id": uid},
            {"$set": {"email": user["email"], "email_lc": user["email"], "name": user["name"],
                      "email_verified": user["email_verified"]}},
            upsert=True,
        )

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _save_model(client, name="M", seed=11):
    r = client.post(
        "/api/models",
        data={"name": name, "distribution": "weibull", "x": "t"},
        files={"file": ("d.csv", _csv(seed), "text/csv")},
    )
    assert r.status_code == 200, r.json()
    return r.json()


def _graph(model_id=None, sub_rbd_id=None):
    """A minimal diagram whose block uses a saved model and/or a sub-system."""
    nodes = [{"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {}}]
    edges = []
    last = "input"
    if model_id:
        nodes.append({"id": "c1", "type": "component", "position": {"x": 100, "y": 0}, "data": {
            "label": "Pump", "model": {"source": "saved", "kind": "distribution", "modelId": model_id,
                                       "distribution_id": "weibull",
                                       "params": [{"name": "alpha", "value": 90}, {"name": "beta", "value": 3}]}}})
        edges.append({"id": "e1", "source": last, "target": "c1"})
        last = "c1"
    if sub_rbd_id:
        nodes.append({"id": "s1", "type": "subsystem", "position": {"x": 200, "y": 0},
                      "data": {"label": "Sub", "rbd": {"id": sub_rbd_id, "name": "Sub"}}})
        edges.append({"id": "e2", "source": last, "target": "s1"})
        last = "s1"
    nodes.append({"id": "output", "type": "output", "position": {"x": 300, "y": 0}, "data": {}})
    edges.append({"id": "e3", "source": last, "target": "output"})
    return {"nodes": nodes, "edges": edges}


def _save_rbd(client, graph, name="R", rbd_id=None):
    body = {"name": name, "graph": graph}
    if rbd_id:
        body["id"] = rbd_id
    return client.post("/api/rbds", json=body)


def _share(client, collection, artifact_id, email):
    return client.post("/api/shares", json={"collection": collection, "artifact_id": artifact_id, "email": email})


def _tree(evidence_id, etype="model"):
    return [{"text": "Fn", "failures": [{"text": "FF", "modes": [
        {"text": "M", "consequence": "operational",
         "decision": {"outcome": "rtf", "rtf_basis": "random",
                      "evidence": {"type": etype, "id": evidence_id}}}]}]}]


def _register_all(client):
    for uid in (C, B, A):
        client.act_as(uid)


# ---- 1. Shared references stay within the sharer's own data ---------------------

def test_shared_rbd_opens_only_the_sharers_own_references(client):
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    a_rbd = _save_rbd(client, _graph(model_id=a_model["id"]), "A's diagram").json()

    client.act_as(B)
    b_model = _save_model(client, "B's model", seed=12)
    b_sub = _save_rbd(client, _graph(model_id=b_model["id"]), "B's sub").json()
    rbd = _save_rbd(client, _graph(model_id=b_model["id"], sub_rbd_id=b_sub["id"]), "B's diagram")
    assert rbd.status_code == 200, rbd.json()
    rbd_id = rbd.json()["id"]
    # A document saved before references were checked: B's diagram also
    # points at A's model and A's diagram.
    graph = client.db.rbds.find_one({"_id": rbd_id})["graph"]
    graph["nodes"].insert(1, _graph(model_id=a_model["id"])["nodes"][1] | {"id": "c-foreign"})
    graph["nodes"].insert(1, _graph(sub_rbd_id=a_rbd["id"])["nodes"][1] | {"id": "s-foreign"})
    client.db.rbds.update_one({"_id": rbd_id}, {"$set": {"graph": graph}})
    assert _share(client, "rbds", rbd_id, "c@x.com").status_code == 200

    client.act_as(C)
    assert client.get(f"/api/rbds/{rbd_id}").status_code == 200
    # B's own chain resolves: the model, its dataset and the nested diagram.
    assert client.get(f"/api/models/{b_model['id']}").status_code == 200
    assert client.get(f"/api/datasets/{b_model['dataset_id']}").status_code == 200
    assert client.get(f"/api/rbds/{b_sub['id']}").status_code == 200
    # A's artifacts stay closed.
    assert client.get(f"/api/models/{a_model['id']}").status_code in (403, 404)
    assert client.get(f"/api/datasets/{a_model['dataset_id']}").status_code in (403, 404)
    assert client.get(f"/api/rbds/{a_rbd['id']}").status_code in (403, 404)


def test_shared_study_evidence_from_another_owner_stays_closed(client):
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")

    client.act_as(B)
    b_model = _save_model(client, "B's model", seed=12)
    sid = client.post("/api/rcm/studies", json={"name": "S"}).json()["id"]
    assert client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": _tree(b_model["id"])}).status_code == 200
    # Pre-existing evidence link to A's model, written straight to the DB.
    tree = client.db.rcm_studies.find_one({"_id": sid})["functions"]
    tree[0]["failures"][0]["modes"].append(
        {**tree[0]["failures"][0]["modes"][0], "id": "m-foreign",
         "decision": {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": a_model["id"]}}})
    client.db.rcm_studies.update_one({"_id": sid}, {"$set": {"functions": tree}})
    _share(client, "rcm_studies", sid, "c@x.com")

    client.act_as(C)
    assert client.get(f"/api/rcm/studies/{sid}").status_code == 200
    assert client.get(f"/api/models/{b_model['id']}").status_code == 200
    assert client.get(f"/api/models/{a_model['id']}").status_code in (403, 404)
    assert client.get(f"/api/datasets/{a_model['dataset_id']}").status_code in (403, 404)


def test_reshared_reference_does_not_extend_a_share(client):
    """A shares a model with B; B's diagram uses it and B shares the diagram
    with C: C gets B's diagram, not A's model."""
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    _share(client, "models", a_model["id"], "b@x.com")

    client.act_as(B)
    rbd = _save_rbd(client, _graph(model_id=a_model["id"]))
    assert rbd.status_code == 200, rbd.json()  # B can open A's model through the share
    _share(client, "rbds", rbd.json()["id"], "c@x.com")

    client.act_as(C)
    assert client.get(f"/api/rbds/{rbd.json()['id']}").status_code == 200
    assert client.get(f"/api/models/{a_model['id']}").status_code in (403, 404)


def test_share_from_team_artifact_reference_stays_with_members(client):
    """A personal diagram referencing a team model: a non-member recipient
    can't open the team model; a member still reads it as a member."""
    from backend.services import access

    _register_all(client)
    client.act_as(B)
    team = client.db.teams.insert_one({
        "_id": "t1", "name": "Crew", "owner_uid": B,
        "members": [{"uid": B, "role": "owner"}, {"uid": A, "role": "member"}], "invites": [],
        "created_at": datetime.now(timezone.utc),
    })
    assert team.inserted_id == "t1"
    r = client.post("/api/models", data={"name": "team model", "distribution": "weibull", "x": "t"},
                    files={"file": ("d.csv", _csv(), "text/csv")}, headers={"X-Workspace-Id": "t1"})
    assert r.status_code == 200, r.json()
    team_model = r.json()
    assert team_model["id"]
    assert client.db.models.find_one({"_id": team_model["id"]})["owner_id"] == access.team_principal("t1")
    rbd = _save_rbd(client, _graph(model_id=team_model["id"]))
    assert rbd.status_code == 200
    _share(client, "rbds", rbd.json()["id"], "c@x.com")
    _share(client, "rbds", rbd.json()["id"], "a@x.com")

    client.act_as(C)
    assert client.get(f"/api/models/{team_model['id']}").status_code in (403, 404)
    client.act_as(A)
    assert client.get(f"/api/models/{team_model['id']}").status_code == 200


def test_public_link_context_reads_only_the_grantors_data(client):
    from backend.schema import Model
    from backend.services import access, public_links

    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    _share(client, "models", a_model["id"], "b@x.com")
    client.act_as(B)
    b_model = _save_model(client, "B's model", seed=12)

    guest = public_links.guest_ctx(B, B)
    assert access.fetch_readable(client.db, "models", Model, b_model["id"], guest)[0] is not None
    # Shared *to* the grantor: not part of what the grantor's public link shows.
    assert access.fetch_readable(client.db, "models", Model, a_model["id"], guest)[0] is None
    # A context whose owner isn't the grantor reads nothing but samples.
    assert access.fetch_readable(client.db, "models", Model, b_model["id"],
                                 public_links.guest_ctx(A, B))[0] is None


def test_public_link_gone_when_artifact_owner_differs(client):
    _register_all(client)
    client.act_as(B)
    b_model = _save_model(client, "B's model")
    link = client.post("/api/public-links", json={"collection": "models", "artifact_id": b_model["id"]}).json()
    assert client.get(f"/api/public/{link['token']}").status_code == 200
    client.db.models.update_one({"_id": b_model["id"]}, {"$set": {"owner_id": A}})
    assert client.get(f"/api/public/{link['token']}").status_code == 404


# ---- 1b. References are checked on save ----------------------------------------

def test_rbd_save_checks_model_and_subsystem_references(client):
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    a_rbd = _save_rbd(client, _graph(model_id=a_model["id"])).json()

    client.act_as(B)
    b_model = _save_model(client, "B's model", seed=12)
    r = _save_rbd(client, _graph(model_id=a_model["id"]))
    assert r.status_code == 422 and r.json()["code"] == "unreadable_reference"
    assert a_model["id"] in r.json()["detail"]
    r = _save_rbd(client, _graph(sub_rbd_id=a_rbd["id"]))
    assert r.status_code == 422 and r.json()["code"] == "unreadable_reference"
    # A spare's model is checked too.
    g = _graph(model_id=b_model["id"])
    g["nodes"][1]["data"]["standbyModel"] = {"modelId": a_model["id"]}
    assert _save_rbd(client, g).status_code == 422
    assert client.db.rbds.count_documents({"owner_id": B}) == 0

    # Own models, samples and stale (deleted) ids are fine.
    assert _save_rbd(client, _graph(model_id=b_model["id"])).status_code == 200
    assert _save_rbd(client, _graph(model_id="0" * 32)).status_code == 200
    sample = client.db.models.find_one({"owner_id": "__samples__"})
    if sample:
        assert _save_rbd(client, _graph(model_id=sample["_id"])).status_code == 200


def test_rbd_update_keeps_existing_references(client):
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    client.act_as(B)
    b_model = _save_model(client, "B's model", seed=12)
    rid = _save_rbd(client, _graph(model_id=b_model["id"])).json()["id"]
    # Saved before the check existed.
    client.db.rbds.update_one({"_id": rid}, {"$set": {"graph": _graph(model_id=a_model["id"])}})
    # Renaming / re-saving the same graph still works...
    assert _save_rbd(client, _graph(model_id=a_model["id"]), "renamed", rbd_id=rid).status_code == 200
    # ...but a new link to someone else's diagram doesn't.
    a_rbd = client.db.rbds.insert_one({"_id": "a-rbd", "owner_id": A, "name": "x", "graph": {}}).inserted_id
    r = _save_rbd(client, _graph(model_id=a_model["id"], sub_rbd_id=a_rbd), rbd_id=rid)
    assert r.status_code == 422


def test_rcm_tree_save_checks_evidence(client):
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    a_analysis = client.db.strategy_analyses.insert_one(
        {"_id": "a-analysis", "owner_id": A, "name": "x", "kind": "replacement"}).inserted_id

    client.act_as(B)
    sid = client.post("/api/rcm/studies", json={"name": "S"}).json()["id"]
    r = client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": _tree(a_model["id"])})
    assert r.status_code == 422 and r.json()["code"] == "unreadable_reference"
    r = client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": _tree(a_analysis, "strategy_analysis")})
    assert r.status_code == 422
    assert client.db.rcm_studies.find_one({"_id": sid}).get("functions") in (None, [])
    b_model = _save_model(client, "B's model", seed=12)
    assert client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": _tree(b_model["id"])}).status_code == 200


def test_fleet_and_model_saves_check_references(client):
    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    client.act_as(B)
    r = client.post("/api/fleet/fleets", json={"name": "F", "model_id": a_model["id"]})
    assert r.status_code == 422
    r = client.post("/api/models", data={"name": "M", "distribution": "weibull", "x": "t",
                                         "dataset_id": a_model["dataset_id"]})
    assert r.status_code == 404
    assert client.db.fleets.count_documents({"owner_id": B}) == 0


def test_mcp_writes_check_references(client):
    from backend.services import tokens
    from backend.tests.test_mcp import _call, _err, _ok

    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    a_rbd = _save_rbd(client, _graph(model_id=a_model["id"])).json()
    client.act_as(B)
    b_rbd = _save_rbd(client, _graph()).json()
    token = tokens.create_token(client.db, B, "mcp")["token"]

    nodes = [{"id": "input", "type": "input"},
             {"id": "s", "type": "subsystem", "label": "Sub", "subsystem_rbd_id": a_rbd["id"]},
             {"id": "output", "type": "output"}]
    edges = [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]
    msg = _err(_call(token, "create_rbd", {"name": "x", "nodes": nodes, "edges": edges}))
    assert "can't open" in msg or "not found" in msg
    msg = _err(_call(token, "edit_rbd", {"rbd_id": b_rbd["id"], "ops": [
        {"op": "add_node", "node": {"id": "s", "type": "subsystem", "label": "Sub",
                                    "subsystem_rbd_id": a_rbd["id"]}, "after": "input"}]}))
    assert "can't open" in msg or "not found" in msg
    assert client.db.rbds.count_documents({"owner_id": B}) == 1
    # A model by id the caller can't read is refused as before.
    _err(_call(token, "create_rbd", {"name": "y", "nodes": [
        {"id": "input", "type": "input"},
        {"id": "c", "type": "component", "label": "P", "model": {"saved_model_id": a_model["id"]}},
        {"id": "output", "type": "output"}],
        "edges": [{"source": "input", "target": "c"}, {"source": "c", "target": "output"}]}))
    # Copying a diagram saved before the check carries no foreign link along.
    client.db.rbds.update_one({"_id": b_rbd["id"]}, {"$set": {"graph": _graph(sub_rbd_id=a_rbd["id"])}})
    assert "can't open" in _err(_call(token, "clone_rbd", {"rbd_id": b_rbd["id"]}))
    assert client.db.rbds.count_documents({"owner_id": B}) == 1
    _ok(_call(token, "list_rbds"))


def test_check_references_helper(client):
    from backend.services import access

    _register_all(client)
    client.act_as(A)
    a_model = _save_model(client, "A's model")
    ctx = access.AccessCtx(user=USERS[B], uid=B, workspace="personal", write_owner=B,
                           read_owners=[B, "__samples__"], list_owners=B)
    refs = [("models", a_model["id"])]
    with pytest.raises(access.UnreadableReference):
        access.check_references(client.db, ctx, refs)
    access.check_references(client.db, ctx, refs, keep=refs)
    access.check_references(client.db, ctx, [("models", "gone")])
    assert access.graph_refs(_graph(model_id="m1", sub_rbd_id="r1")) == [("models", "m1"), ("rbds", "r1")]
    # Malformed graphs yield no references rather than failing.
    assert access.graph_refs({"nodes": ["x", {"data": "y"}, {"data": {"model": {"modelId": {"$ne": ""}}}}]}) == []


# ---- 2. Email trust needs a verified address -------------------------------------

def test_unverified_account_gets_no_email_share(client):
    _register_all(client)
    client.act_as(D)
    client.act_as(A)
    model = _save_model(client)
    r = _share(client, "models", model["id"], "d@x.com")
    assert r.status_code == 409 and "verified" in r.json()["detail"]
    assert client.db.shares.count_documents({}) == 0
    client.act_as(D)
    assert client.get(f"/api/models/{model['id']}").status_code == 404


def test_unverified_account_gets_no_invite(client):
    _register_all(client)
    client.act_as(D)
    client.act_as(A)
    tid = client.post("/api/teams", json={"name": "Crew"}).json()["id"]
    # Not added directly: staged as a pending invite instead.
    r = client.post(f"/api/teams/{tid}/members", json={"email": "d@x.com"})
    assert r.status_code == 200 and r.json()["status"] == "invited"
    # Signing in unverified doesn't activate it.
    client.act_as(D)
    assert client.get("/api/me").json()["teams"] == []
    team = client.db.teams.find_one({"_id": tid})
    assert [m["uid"] for m in team["members"]] == [A]
    # Once verified, the next sign-in joins the team.
    USERS[D]["email_verified"] = True
    try:
        client.act_as(D)
        assert [t["id"] for t in client.get("/api/me").json()["teams"]] == [tid]
    finally:
        USERS[D]["email_verified"] = False


def test_unverified_operator_email_is_not_admin(client, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "ADMIN_EMAILS", {"d@x.com", "a@x.com"})
    assert billing.is_admin_user({"email": "d@x.com", "email_verified": False}) is False
    assert billing.is_admin_user({"email": "d@x.com"}) is False
    assert billing.is_admin_user({"email": "a@x.com", "email_verified": True}) is True
    client.act_as(D)
    assert client.get("/api/me").json()["admin"] is False
    client.act_as(A)
    assert client.get("/api/me").json()["admin"] is True
    # Single-user installs (sign-in off) are unaffected.
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    assert billing.is_admin_user({"email": "d@x.com"}) is True


def test_profile_records_email_verification(client):
    client.act_as(D)
    me = client.get("/api/me").json()
    assert me["email_verified"] is False
    assert client.db.users.find_one({"_id": D})["email_verified"] is False


# ---- 3. Revoked sessions ----------------------------------------------------------

def test_revoked_session_is_401(monkeypatch):
    from fastapi import HTTPException
    from firebase_admin import auth as fb_auth

    from backend import auth, config

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(auth, "_initialized", True)
    auth._verified_cache.clear()
    calls = []

    def revoked(token, check_revoked=False):
        calls.append(check_revoked)
        raise fb_auth.RevokedIdTokenError("revoked")

    monkeypatch.setattr(fb_auth, "verify_id_token", revoked)
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user("Bearer some-token")
    assert exc.value.status_code == 401 and calls == [True]

    def ok(token, check_revoked=False):
        calls.append(check_revoked)
        return {"uid": "u1", "email": "u@x.com", "email_verified": True,
                "exp": datetime.now(timezone.utc).timestamp() + 3600}

    monkeypatch.setattr(fb_auth, "verify_id_token", ok)
    user = auth.get_current_user("Bearer other-token")
    assert user["uid"] == "u1" and user["email_verified"] is True
    auth._verified_cache.clear()


# ---- 4. API token scopes ----------------------------------------------------------

def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_token_scopes_on_rest_endpoints(client):
    from backend.services import tokens

    client.act_as(B)
    _save_model(client)
    db = client.db
    ingest = tokens.create_token(db, B, "i", ["ingest"])["token"]
    read = tokens.create_token(db, B, "r", ["read"])["token"]
    write = tokens.create_token(db, B, "w", ["write"])["token"]
    from backend.main import app

    app.dependency_overrides.clear()  # tokens, not the session override

    assert client.get("/api/v1/models", headers=_bearer(ingest)).status_code == 403
    assert client.get("/api/v1/models", headers=_bearer(read)).status_code == 200
    assert client.get("/api/v1/models", headers=_bearer(write)).status_code == 403
    body = {"name": "d", "data": {"t": [1, 2, 3]}}
    assert client.post("/api/v1/datasets", json=body, headers=_bearer(read)).status_code == 403
    assert client.post("/api/v1/datasets", json=body, headers=_bearer(write)).status_code == 200
    assert client.post("/api/v1/strategy/optimal-replacement", json={}, headers=_bearer(ingest)).status_code == 403
    # Ingest endpoints need the ingest scope (anything but 401/403 = past the check).
    assert client.post("/api/ingest/fleets/nope/usage", json={}, headers=_bearer(read)).status_code == 403
    assert client.post("/api/ingest/fleets/nope/usage", json={}, headers=_bearer(ingest)).status_code not in (401, 403)


def test_token_without_scopes_keeps_every_scope(client):
    from backend.main import app
    from backend.services import tokens

    client.act_as(B)
    raw = tokens.create_token(client.db, B, "old")["token"]
    client.db.api_tokens.update_many({}, {"$unset": {"scopes": ""}})
    assert tokens.list_tokens(client.db, B)[0]["scopes"] == ["ingest", "read", "write"]
    app.dependency_overrides.clear()
    assert client.get("/api/v1/models", headers=_bearer(raw)).status_code == 200
    assert client.post("/api/v1/datasets", json={"name": "d", "data": {"t": [1, 2]}},
                       headers=_bearer(raw)).status_code == 200
    assert client.post("/api/ingest/fleets/nope/usage", json={}, headers=_bearer(raw)).status_code not in (401, 403)


def test_token_creation_with_scopes(client):
    client.act_as(B)
    r = client.post("/api/tokens", json={"name": "cmms", "scopes": ["ingest"]})
    assert r.status_code == 200 and r.json()["scopes"] == ["ingest"]
    assert client.get("/api/tokens").json()["tokens"][0]["scopes"] == ["ingest"]
    assert client.post("/api/tokens", json={"name": "x", "scopes": ["admin"]}).status_code == 422
    assert client.post("/api/tokens", json={"name": "x", "scopes": []}).status_code == 422
    # No scopes given: every scope, as before.
    assert client.post("/api/tokens", json={"name": "all"}).json()["scopes"] == ["ingest", "read", "write"]


def test_token_scopes_on_mcp_tools(client):
    from backend.services import tokens
    from backend.tests.test_mcp import GRAPH, _call, _err, _ok, _post_mcp

    client.act_as(B)
    db = client.db
    ingest = tokens.create_token(db, B, "i", ["ingest"])["token"]
    read = tokens.create_token(db, B, "r", ["read"])["token"]
    write = tokens.create_token(db, B, "rw", ["read", "write"])["token"]

    r = _post_mcp({"Authorization": f"Bearer {ingest}"})
    assert r.status_code == 403 and "ingest" in r.json()["detail"]

    _ok(_call(read, "list_models"))
    _ok(_call(read, "get_account"))
    assert "write" in _err(_call(read, "create_rbd", {"name": "x", **GRAPH}))
    assert client.db.rbds.count_documents({"owner_id": B}) == 0
    assert "write" in _err(_call(read, "delete_model", {"model_id": "nope"}))
    assert "write" in _err(_call(read, "share_link", {"kind": "model", "id": "nope"}))
    # Read + write reaches the tool itself.
    assert "scope" not in _err(_call(write, "delete_model", {"model_id": "nope"}))


def test_mcp_imports_check_the_token_scope_then_the_import_guard(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from backend.services import import_guard, tokens
    from backend.tests.test_mcp import _call, _err, _ok

    monkeypatch.setattr(import_guard, "WAIT_SECONDS", 0.0)
    client.act_as(B)
    db = client.db
    read = tokens.create_token(db, B, "r", ["read"])["token"]
    write = tokens.create_token(db, B, "rw", ["read", "write"])["token"]
    dft = 'toplevel "S";\n"S" or "A" "B";\n"A" lambda=1e-3;\n"B" lambda=2e-3;\n'
    args = {"content": dft, "format": "galileo", "save": False}

    assert "write" in _err(_call(read, "import_rbd", args))
    _ok(_call(write, "import_rbd", args))
    db.import_locks.insert_one({"_id": B, "nonce": "busy",
                                "until": datetime.now(timezone.utc) + timedelta(minutes=1)})
    assert "Another import" in _err(_call(write, "import_rbd", args))


def test_tool_scope_follows_annotations():
    from backend import mcp_server

    assert mcp_server._tool_scope(mcp_server._READ) == "read"
    assert mcp_server._tool_scope(mcp_server._LINK) == "read"
    assert mcp_server._tool_scope(mcp_server._WRITE) == "write"


# ---- 5. OAuth ----------------------------------------------------------------------

def test_client_registration_is_rate_limited_per_ip(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app
    from backend.routers import oauth as oauth_router

    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://reliafy.com")
    test_db = mongomock.MongoClient()["reliafy_register_limit"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(oauth_router, "REGISTER_PER_IP", 3)
    tc = TestClient(app)
    body = {"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"], "client_name": "x"}
    for _ in range(3):
        assert tc.post("/oauth/register", json=body, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 201
    r = tc.post("/oauth/register", json=body, headers={"X-Forwarded-For": "203.0.113.5"})
    assert r.status_code == 429 and r.headers.get("retry-after")
    assert test_db.oauth_clients.count_documents({}) == 3


def test_refresh_replay_in_grace_returns_same_pair():
    from backend.services import oauth

    db = mongomock.MongoClient()["reliafy_refresh_replay"]
    client = {"client_id": "c1"}
    first = oauth._issue(db, family_id="f1", uid="u1", client_id="c1", client_name="App",
                         scopes=["mcp"], res="https://reliafy.com/mcp",
                         grant_created_at=datetime.now(timezone.utc))
    original = oauth.check_resource
    oauth.check_resource = lambda value: None
    try:
        second = oauth.refresh(db, client, {"refresh_token": first["refresh_token"]})
        again = oauth.refresh(db, client, {"refresh_token": first["refresh_token"]})
        assert again == second
        assert db.oauth_tokens.count_documents({"family_id": "f1"}) == 2
        # The successor pair isn't stored readable.
        rotated = db.oauth_tokens.find_one({"rotated": True})
        assert second["refresh_token"] not in str(rotated) and second["access_token"] not in str(rotated)
        # A different (forged) token can't open it, and after the window a
        # replay revokes the grant.
        assert oauth._unseal("rlfr_other", rotated["successor"]) is None
        db.oauth_tokens.update_many({"rotated": True}, {"$set": {
            "rotated_at": datetime.now(timezone.utc) - oauth.REFRESH_REUSE_GRACE - timedelta(seconds=1)}})
        with pytest.raises(oauth.OAuthError):
            oauth.refresh(db, client, {"refresh_token": first["refresh_token"]})
        assert db.oauth_tokens.count_documents({"family_id": "f1", "revoked": False}) == 0
    finally:
        oauth.check_resource = original


# ---- 6. Team and invite email content ---------------------------------------------

def test_team_names_are_cleaned_and_capped(client):
    client.act_as(A)
    r = client.post("/api/teams", json={"name": "Reliability\r\nBcc: x@y.com\tteam"})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert client.db.teams.find_one({"_id": tid})["name"] == "Reliability Bcc: x@y.com team"
    assert client.post("/api/teams", json={"name": "x" * 81}).status_code == 422
    assert client.post("/api/teams", json={"name": "\n\t"}).status_code == 422
    assert client.patch(f"/api/teams/{tid}", json={"name": "y" * 81}).status_code == 422
    assert client.patch(f"/api/teams/{tid}", json={"name": "New\nname"}).json()["name"] == "New name"
    assert client.db.teams.find_one({"_id": tid})["name"] == "New name"


def test_invite_email_handles_names_with_line_breaks(monkeypatch):
    from backend.services import email as email_service

    built = []
    monkeypatch.setattr(email_service, "enabled", lambda: True)

    class NoThread:
        def __init__(self, target, args, daemon):
            built.append(args[0])

        def start(self):
            pass

    monkeypatch.setattr(email_service.threading, "Thread", NoThread)
    email_service.team_invite_pending("x@y.com", "Sam\r\nBcc: z@z.com", "Crew\nTeam " + "x" * 200)
    email_service.team_member_added("x@y.com", "Name\x00", "Crew")
    subject = built[0]["Subject"]
    assert "\n" not in subject and "\r" not in subject and len(subject) <= 200
    assert built[0]["Bcc"] is None


def test_invites_are_rate_limited(client, monkeypatch):
    from backend.services import teams

    monkeypatch.setattr(teams, "INVITES_PER_TEAM", 2)
    client.act_as(A)
    tid = client.post("/api/teams", json={"name": "Crew"}).json()["id"]
    assert client.post(f"/api/teams/{tid}/members", json={"email": "n1@x.com"}).status_code == 200
    assert client.post(f"/api/teams/{tid}/members", json={"email": "n2@x.com"}).status_code == 200
    r = client.post(f"/api/teams/{tid}/members", json={"email": "n3@x.com"})
    assert r.status_code == 429
    assert [i["email"] for i in client.db.teams.find_one({"_id": tid})["invites"]] == ["n1@x.com", "n2@x.com"]

    monkeypatch.setattr(teams, "INVITES_PER_TEAM", 100)
    monkeypatch.setattr(teams, "INVITES_PER_USER", 3)
    tid2 = client.post("/api/teams", json={"name": "Crew 2"}).json()["id"]
    assert client.post(f"/api/teams/{tid2}/members", json={"email": "n4@x.com"}).status_code == 429


def test_logged_recipients_are_masked(caplog, monkeypatch):
    from backend import config
    from backend.services import email as email_service

    monkeypatch.setattr(config, "SMTP_HOST", None)
    with caplog.at_level(logging.INFO, logger="backend.services.email"):
        email_service.send("derryn@gmail.com", "Hello", "Body")
    assert "derryn@gmail.com" not in caplog.text
    assert "d***@gmail.com" in caplog.text
    assert email_service.mask_address("a@b.co, longer@c.org") == "a***@b.co, l***@c.org"


# ---- Verification status looked up when not stored --------------------------------

@pytest.fixture()
def lookup(monkeypatch):
    """Stand in for Firebase Admin: ``answers[uid]`` is True / False, or an
    exception to raise."""
    from backend.services import email_trust

    answers, calls = {}, []

    def fake(uid):
        calls.append(uid)
        answer = answers[uid]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(email_trust, "_firebase_ready", lambda: True)
    monkeypatch.setattr(email_trust, "_lookup", fake)
    return answers, calls


def _unknown(client, uid):
    """An account that hasn't signed in since verification was recorded."""
    client.db.users.update_one({"_id": uid}, {"$unset": {"email_verified": ""}})


def test_share_to_unknown_status_uses_verified_lookup(client, lookup):
    answers, calls = lookup
    _register_all(client)
    _unknown(client, C)
    answers[C] = True
    client.act_as(A)
    model = _save_model(client)
    assert _share(client, "models", model["id"], "c@x.com").status_code == 200
    assert calls == [C]
    # The answer is stored on the profile, so later checks needn't ask.
    assert client.db.users.find_one({"_id": C})["email_verified"] is True


def test_share_to_unknown_status_refused_when_lookup_says_unverified(client, lookup):
    answers, _ = lookup
    _register_all(client)
    _unknown(client, C)
    answers[C] = False
    client.act_as(A)
    model = _save_model(client)
    r = _share(client, "models", model["id"], "c@x.com")
    assert r.status_code == 409 and "hasn't verified" in r.json()["detail"]
    assert client.db.shares.count_documents({}) == 0
    assert client.db.users.find_one({"_id": C})["email_verified"] is False


def test_share_to_unknown_status_refused_when_lookup_fails(client, lookup):
    answers, calls = lookup
    _register_all(client)
    _unknown(client, C)
    answers[C] = RuntimeError("firebase unavailable")
    client.act_as(A)
    model = _save_model(client)
    r = _share(client, "models", model["id"], "c@x.com")
    assert r.status_code == 409 and "couldn't confirm" in r.json()["detail"]
    assert client.db.shares.count_documents({}) == 0
    assert "email_verified" not in client.db.users.find_one({"_id": C})
    # Cached briefly: an immediate retry doesn't ask again.
    _share(client, "models", model["id"], "c@x.com")
    assert calls == [C]


def test_invite_to_unknown_status_uses_lookup(client, lookup):
    answers, _ = lookup
    _register_all(client)
    _unknown(client, B)
    _unknown(client, C)
    answers[B] = True
    answers[C] = RuntimeError("firebase unavailable")
    client.act_as(A)
    tid = client.post("/api/teams", json={"name": "Crew"}).json()["id"]
    assert client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"}).json()["status"] == "added"
    r = client.post(f"/api/teams/{tid}/members", json={"email": "c@x.com"}).json()
    assert r["status"] == "invited" and "couldn't confirm" in r["note"]


def test_invite_activation_with_unknown_status_uses_lookup(lookup, monkeypatch):
    from backend import config
    from backend.services import teams

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    answers, _ = lookup
    db = mongomock.MongoClient()["reliafy_invite_lookup"]
    db.teams.insert_one({"_id": "t1", "name": "Crew", "owner_uid": A, "members": [{"uid": A}],
                         "invites": [{"email": "c@x.com"}, {"email": "d@x.com"}]})
    answers[C], answers[D] = True, RuntimeError("down")
    teams.activate_invites(db, {"uid": C, "email": "c@x.com", "name": "C"})
    teams.activate_invites(db, {"uid": D, "email": "d@x.com", "name": "D"})
    team = db.teams.find_one({"_id": "t1"})
    assert [m["uid"] for m in team["members"]] == [A, C]
    assert [i["email"] for i in team["invites"]] == ["d@x.com"]


def test_token_user_with_unknown_status_uses_lookup(lookup, monkeypatch):
    from backend import config
    from backend.services import billing, tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"c@x.com", "d@x.com"})
    answers, _ = lookup
    db = mongomock.MongoClient()["reliafy_token_lookup"]
    db.users.insert_many([{"_id": C, "email": "c@x.com"}, {"_id": D, "email": "d@x.com"}])
    answers[C], answers[D] = True, RuntimeError("down")
    c = tokens.verify(db, tokens.create_token(db, C, "t")["token"])
    d = tokens.verify(db, tokens.create_token(db, D, "t")["token"])
    assert billing.is_admin_user(c) is True
    assert billing.is_admin_user(d) is False


def test_alert_email_only_to_verified_address(client, lookup, monkeypatch):
    from backend.schema import Fleet
    from backend.services import email as email_service
    from backend.services import fleet_alerts

    answers, _ = lookup
    sent = []
    monkeypatch.setattr(email_service, "enabled", lambda: True)
    monkeypatch.setattr(email_service, "send_now", lambda to, *a, **k: sent.append(to))
    monkeypatch.setattr(fleet_alerts, "render", lambda *a, **k: {"subject": "s", "text": "t", "html": "h"})
    fleet = Fleet(id="f1", name="F", owner_id=B, model_id="m1", settings={}, items=[])
    rule = {"_id": "r1", "owner_uid": B, "kind": "above", "threshold": 1}
    now = datetime.now(timezone.utc)

    client.act_as(B)  # verified
    fleet_alerts._fire(client.db, fleet, rule, 0, None, 2.0, now, "test")
    assert sent == ["b@x.com"]

    client.act_as(D)  # stored unverified, and the lookup agrees
    answers[D] = False
    fleet_alerts._fire(client.db, fleet, {**rule, "_id": "r2", "owner_uid": D}, 0, None, 2.0, now, "test")
    client.act_as(C)
    _unknown(client, C)  # unknown, and the lookup fails
    answers[C] = RuntimeError("down")
    fleet_alerts._fire(client.db, fleet, {**rule, "_id": "r3", "owner_uid": C}, 0, None, 2.0, now, "test")
    assert sent == ["b@x.com"]
    errors = {e["alert_id"]: e["error"] for e in client.db.fleet_alert_events.find()}
    assert errors["r1"] is None
    assert "isn't verified" in errors["r2"] and "Couldn't confirm" in errors["r3"]


def test_no_lookup_without_firebase_or_with_sign_in_off(client, monkeypatch):
    from backend import config
    from backend.services import email_trust

    def unexpected(uid):
        raise AssertionError("no lookup expected")

    monkeypatch.setattr(email_trust, "_lookup", unexpected)
    monkeypatch.setattr(email_trust, "_firebase_ready", lambda: False)
    client.act_as(C)
    _unknown(client, C)
    assert email_trust.status(client.db, C) == email_trust.UNVERIFIED
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    assert email_trust.status(client.db, C) == email_trust.VERIFIED
