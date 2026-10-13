"""Workspace boundaries: preview fits store nothing, diagram-owner scope only
for the diagram as saved, public dataset links, share requests, What changed,
run history after access ends, and team deletion."""

import io
from datetime import datetime, timedelta, timezone

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest

OWNER, MEMBER, OTHER = "user-owner", "user-member", "user-other"

USERS = {
    OWNER: {"uid": OWNER, "email": "owner@x.com", "name": "Owner", "email_verified": True},
    MEMBER: {"uid": MEMBER, "email": "member@x.com", "name": "Member", "email_verified": True},
    OTHER: {"uid": OTHER, "email": "other@x.com", "name": "Other", "email_verified": True},
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["reliafy_boundaries"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    for uid, user in USERS.items():
        test_db.users.update_one({"_id": uid}, {"$set": {
            "email": user["email"], "email_lc": user["email"], "email_verified": True, "name": user["name"]}},
            upsert=True)
    test_db.users.update_one({"_id": OWNER}, {"$set": {"plan": "pro"}})

    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: dict(USERS[uid])

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _team_with_member(client, member=MEMBER):
    client.act_as(OWNER)
    tid = client.post("/api/teams", json={"name": "Crew"}).json()["id"]
    assert client.post(f"/api/teams/{tid}/members", json={"email": USERS[member]["email"]}).status_code == 200
    client.act_as(member)
    assert client.post(f"/api/teams/invites/{tid}/accept").status_code == 200
    return tid


def _csv(df) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def _degradation_csv(seed=0) -> bytes:
    rows = [{"unit": f"u{u}", "t": t, "y": 0.1 * t * (1 + u / 10) + seed / 1000}
            for u in range(4) for t in range(1, 6)]
    return _csv(pd.DataFrame(rows))


def _recurrent_csv() -> bytes:
    rows = [{"system": s, "time": t, "obs_end": 100} for s in ("A", "B", "C") for t in (10, 30, 55, 70, 90)]
    return _csv(pd.DataFrame(rows))


def _alt_csv() -> bytes:
    rng = np.random.default_rng(4)
    rows = []
    for temp in (320.0, 350.0, 380.0):
        scale = 1000 * np.exp(4000 * (1 / temp - 1 / 350))
        for x in rng.weibull(2.0, 10) * scale:
            rows.append({"t": round(float(x), 3), "temp": temp})
    return _csv(pd.DataFrame(rows))


PREVIEWS = [
    ("/api/degradation/fit", "/api/degradation/models",
     {"i": "unit", "x": "t", "y": "y", "threshold": "5"}, _degradation_csv),
    ("/api/recurrent/fit", "/api/recurrent/models",
     {"i": "system", "x": "time", "t": "obs_end", "model": "crow_amsaa"}, _recurrent_csv),
    ("/api/alt/fit", "/api/alt/models", {"x": "t", "s1": "temp"}, _alt_csv),
]


# ---- Preview fits store nothing ------------------------------------------------------

@pytest.mark.parametrize("preview, save, form, data", PREVIEWS)
def test_preview_fit_parses_the_upload_without_storing_it(client, preview, save, form, data):
    client.act_as(OWNER)
    r = client.post(preview, data=form, files={"file": ("d.csv", data(), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["dataset_id"] is None and r.json()["results"]
    assert client.db.datasets.count_documents({}) == 0
    # The save stores the upload, as the app sends it after a preview.
    r = client.post(save, data={**form, "name": "Saved"}, files={"file": ("d.csv", data(), "text/csv")})
    assert r.status_code == 200, r.text
    assert client.db.datasets.count_documents({"owner_id": OWNER}) == 1


def test_preview_fit_of_a_saved_dataset_returns_its_id(client):
    from backend.services import datasets as datasets_service

    ds = datasets_service.create_dataset(client.db, "wear", _degradation_csv(), OWNER)
    client.act_as(OWNER)
    r = client.post("/api/degradation/fit", data={**PREVIEWS[0][2], "dataset_id": ds.id})
    assert r.status_code == 200 and r.json()["dataset_id"] == ds.id


@pytest.mark.parametrize("preview, save, form, data", PREVIEWS)
def test_view_only_member_can_preview_but_not_store_in_the_team(client, preview, save, form, data):
    tid = _team_with_member(client)
    h = {"X-Workspace-Id": tid}
    client.act_as(MEMBER)  # free: views the team, can't edit it
    r = client.post(preview, data=form, files={"file": ("d.csv", data(), "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post(save, data={**form, "name": "x"}, files={"file": ("d.csv", data(), "text/csv")}, headers=h)
    assert r.status_code == 402 and r.json()["code"] == "member_pro_required"
    assert client.db.datasets.count_documents({}) == 0


def test_frozen_team_stores_no_upload(client):
    tid = _team_with_member(client)
    client.db.users.update_one({"_id": OWNER}, {"$unset": {"plan": ""}})
    client.act_as(OWNER)
    preview, save, form, data = PREVIEWS[1]
    r = client.post(save, data={**form, "name": "x"}, files={"file": ("d.csv", data(), "text/csv")},
                    headers={"X-Workspace-Id": tid})
    assert r.status_code == 402 and r.json()["code"] == "team_frozen"
    assert client.db.datasets.count_documents({}) == 0


def test_save_with_upload_keeps_the_dataset_cap(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 1)
    client.act_as(MEMBER)
    preview, save, form, data = PREVIEWS[1]
    r = client.post(save, data={**form, "name": "a"}, files={"file": ("d.csv", data(), "text/csv")})
    assert r.status_code == 200, r.text
    # Data it already holds re-uses its dataset; new data is over the cap.
    r = client.post(save, data={**form, "name": "b"}, files={"file": ("d.csv", data(), "text/csv")})
    assert r.status_code == 200, r.text
    other = _recurrent_csv().replace(b"90,100", b"95,100")
    r = client.post(save, data={**form, "name": "c"}, files={"file": ("e.csv", other, "text/csv")})
    assert r.status_code == 402 and r.json()["code"] == "cap"
    # Previews still work past the cap: they store nothing.
    for _ in range(3):
        assert client.post(preview, data=form, files={"file": ("e.csv", other, "text/csv")}).status_code == 200
    assert client.db.datasets.count_documents({"owner_id": MEMBER}) == 1


# ---- Saved models in a posted graph: the diagram owner's only for the saved graph ----

def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _series(*nodes):
    ids = ["input", *(n["id"] for n in nodes), "output"]
    return {"repairable": True, "unit": "hours",
            "nodes": [{"id": "input", "type": "input", "data": {"label": "in"}},
                      {"id": "output", "type": "output", "data": {"label": "out"}}, *nodes],
            "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(zip(ids, ids[1:]))]}


def _node(nid, model, repair):
    return {"id": nid, "type": "component", "position": {"x": 0, "y": 0},
            "data": {"label": nid, "model": model, "repair": repair}}


def test_graph_owners_widen_only_for_the_saved_graph():
    from backend.schema import Rbd
    from backend.services import rbds as rbds_service

    saved = _series(_node("p", _exp(1e-3), _exp(0.1)))
    rbd = Rbd(id="r1", name="R", owner_id="grantor", graph=saved)
    moved = {**saved, "nodes": [{**n, "position": {"x": 50, "y": 9}} for n in saved["nodes"]]}
    assert rbds_service.graph_owners(["me"], rbd, moved) == ["me", "grantor"]  # layout aside
    assert rbds_service.graph_owners(["me"], {"owner_id": "grantor", "graph": saved}, saved) == ["me", "grantor"]
    edited = _series(_node("p", _exp(2e-3), _exp(0.1)))
    assert rbds_service.graph_owners(["me"], rbd, edited) == ["me"]
    assert rbds_service.graph_owners(["me"], None, saved) == ["me"]


def _shared_diagram_and_private_model(client):
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    rng = np.random.default_rng(3)
    load = rng.uniform(0.5, 1.5, 120)
    x = rng.weibull(2.0, 120) * 1000 * np.exp(-0.8 * (load - 1))
    data = _csv(pd.DataFrame({"t": np.round(x, 3), "c": 0, "load": np.round(load, 3)}))
    ds = datasets_service.create_dataset(client.db, "reg", data, OWNER)
    model = models_service.save_model(client.db, "private PH", ds, "weibull_ph", {"x": "t", "c": "c"}, [], "load",
                                      owner_id=OWNER)
    rbd = rbds_service.save_rbd(client.db, "Shared pump", _series(_node("p", _exp(1e-3), _exp(0.1))), OWNER)
    client.db.shares.insert_one({"_id": "s1", "collection": "rbds", "artifact_id": rbd.id, "grantor_uid": OWNER,
                                 "recipient_uid": OTHER, "recipient_email": "other@x.com",
                                 "created_at": datetime.now(timezone.utc)})
    return rbd, model


@pytest.mark.parametrize("path, extra", [
    ("/api/rbds/sensitivity", {}),
    ("/api/rbds/measures", {"measure": "rate"}),
])
def test_shared_diagram_id_doesnt_open_its_owners_other_models(client, path, extra):
    rbd, model = _shared_diagram_and_private_model(client)
    ph = {"source": "saved", "kind": "regression", "modelId": model.id, "distribution": "Weibull PH",
          "distribution_id": "weibull_ph", "covariates": [{"name": "load", "type": "number", "default": 1.0}]}
    graph = _series(_node("x", _exp(1e-3), ph))
    client.act_as(OTHER)
    assert client.get(f"/api/models/{model.id}").status_code == 404
    r = client.post(path, json={"graph": graph, "rbd_id": rbd.id, **extra})
    assert r.status_code == 422 and "saved model not found" in r.json()["detail"]


@pytest.mark.parametrize("path, module, name", [
    ("/api/rbds/sensitivity", "rbd_sensitivity", "sensitivity_payload"),
    ("/api/rbds/measures", "rbd_measures", "measures_payload"),
    ("/api/rbds/intervals", "rbd_intervals", "intervals_payload"),
])
def test_routers_pass_the_owner_only_for_the_saved_graph(client, monkeypatch, path, module, name):
    import importlib

    rbd, _ = _shared_diagram_and_private_model(client)
    seen = []

    def capture(session, ctx, graph, rbd, owners, **kwargs):
        seen.append(list(owners))
        return 200, {}

    monkeypatch.setattr(importlib.import_module(f"backend.routers.{module}"), name, capture)
    extra = {"measure": "rate"} if module == "rbd_measures" else {}
    client.act_as(OTHER)
    client.post(path, json={"graph": rbd.graph, "rbd_id": rbd.id, **extra})
    client.post(path, json={"graph": _series(_node("p", _exp(5e-3), _exp(0.1))), "rbd_id": rbd.id, **extra})
    assert seen == [[OTHER, "__samples__", OWNER], [OTHER, "__samples__"]]


def test_rerun_passes_the_owner_only_for_the_saved_graph(client, monkeypatch):
    from backend.routers import rbds as rbds_router

    rbd, _ = _shared_diagram_and_private_model(client)
    seen = []

    def capture(session, ctx, graph, t_max, rbd, force, owners, **kwargs):
        seen.append(list(owners))
        return 422, {"detail": "stop"}

    monkeypatch.setattr(rbds_router, "availability_payload", capture)
    when = datetime.now(timezone.utc)
    for jid, graph in (("same", rbd.graph), ("other", _series(_node("p", _exp(5e-3), _exp(0.1))))):
        client.db.rbd_jobs.insert_one({"_id": jid, "kind": "availability", "status": "done", "uid": OTHER,
                                       "rbd_id": rbd.id, "created_at": when, "finished_at": when,
                                       "request": {"graph": graph, "options": {}}, "result": {}})
    client.act_as(OTHER)
    client.post("/api/rbd-runs/same/rerun")
    client.post("/api/rbd-runs/other/rerun")
    assert seen == [[OTHER, "__samples__", OWNER], [OTHER, "__samples__"]]


def test_payload_scope_drops_the_owner_for_another_graph(client):
    """The shared payload builders narrow the scope themselves, whoever calls."""
    from backend.routers import rbd_measures as measures_router
    from backend.services import access

    rbd, model = _shared_diagram_and_private_model(client)
    ph = {"source": "saved", "kind": "regression", "modelId": model.id, "distribution": "Weibull PH",
          "distribution_id": "weibull_ph", "covariates": [{"name": "load", "type": "number", "default": 1.0}]}
    ctx = access.AccessCtx(user=USERS[OTHER], uid=OTHER, workspace="personal", write_owner=OTHER,
                           read_owners=[OTHER], list_owners=OTHER)
    from backend.services.rbd_analysis import AnalysisError
    with pytest.raises(AnalysisError, match="saved model not found"):
        measures_router.measures_payload(client.db, ctx, _series(_node("x", _exp(1e-3), ph)), rbd,
                                         [OTHER, OWNER], measure="rate")


# ---- Public dataset links --------------------------------------------------------------

def test_public_dataset_link_lists_no_models_of_the_grantor(client):
    client.act_as(OWNER)
    rng = np.random.default_rng(1)
    data = _csv(pd.DataFrame({"t": np.round(rng.weibull(2.0, 30) * 100, 2)}))
    r = client.post("/api/models", data={"name": "Customer warranty model", "distribution": "weibull", "x": "t"},
                    files={"file": ("d.csv", data, "text/csv")})
    assert r.status_code == 200, r.text
    dataset_id = r.json()["dataset_id"]
    assert client.get(f"/api/datasets/{dataset_id}").json()["models"]  # the owner sees them
    token = client.post("/api/public-links", json={"collection": "datasets", "artifact_id": dataset_id}).json()["token"]
    client.act_as(None)
    art = client.get(f"/api/public/{token}").json()["artifact"]
    assert art["models"] == [] and art["other_models"] == [] and art["n_models"] == 0
    assert "Customer warranty model" not in str(art)


# ---- Share requests ----------------------------------------------------------------------

def _owner_model(client):
    client.act_as(OWNER)
    rng = np.random.default_rng(2)
    data = _csv(pd.DataFrame({"t": np.round(rng.weibull(2.0, 30) * 100, 2)}))
    r = client.post("/api/models", data={"name": "M", "distribution": "weibull", "x": "t"},
                    files={"file": ("d.csv", data, "text/csv")})
    return r.json()["id"]


def test_share_answer_is_the_same_with_or_without_an_account(client):
    mid = _owner_model(client)
    client.db.users.update_one({"_id": OTHER}, {"$set": {"email_verified": False}})
    answers = {}
    for email in ("member@x.com", "other@x.com", "nobody@x.com"):
        r = client.post("/api/shares", json={"collection": "models", "artifact_id": mid, "email": email})
        answers[email] = (r.status_code, sorted(r.json()), r.json()["email"])
    assert answers == {e: (200, ["created_at", "email", "id"], e) for e in answers}
    listed = client.get("/api/shares", params={"collection": "models", "artifact_id": mid}).json()["shares"]
    assert sorted(s["email"] for s in listed) == ["member@x.com", "nobody@x.com", "other@x.com"]
    # The verified account has it now.
    client.act_as(MEMBER)
    assert client.get(f"/api/models/{mid}").status_code == 200


def test_share_to_an_address_reaches_the_account_made_for_it_later(client):
    mid = _owner_model(client)
    r = client.post("/api/shares", json={"collection": "models", "artifact_id": mid, "email": "New@X.com"})
    assert r.status_code == 200 and r.json()["email"] == "new@x.com"
    USERS["user-new"] = {"uid": "user-new", "email": "new@x.com", "name": "New", "email_verified": True}
    try:
        client.act_as("user-new")
        assert client.get(f"/api/models/{mid}").status_code == 404
        client.get("/api/me")
        assert client.get(f"/api/models/{mid}").status_code == 200
        assert client.db.shares.count_documents({"recipient_uid": {"$regex": "^pending:"}}) == 0
        # Revoking still works on the claimed share.
        client.act_as(OWNER)
        [share] = client.get("/api/shares", params={"collection": "models", "artifact_id": mid}).json()["shares"]
        assert client.delete(f"/api/shares/{share['id']}").status_code == 200
        client.act_as("user-new")
        assert client.get(f"/api/models/{mid}").status_code == 404
    finally:
        USERS.pop("user-new")


def test_share_requests_are_rate_limited(client, monkeypatch):
    from backend.services import shares

    monkeypatch.setattr(shares, "SHARES_PER_HOUR", 3)
    mid = _owner_model(client)
    codes = [client.post("/api/shares", json={"collection": "models", "artifact_id": mid,
                                              "email": f"p{i}@x.com"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_share_email_caps_and_cleans_the_sharers_text(client, monkeypatch):
    from backend.services import email as email_service

    sent = []
    monkeypatch.setattr(email_service, "send", lambda to, subject, body, **k: sent.append((to, subject, body)))
    client.db.users.update_one({"_id": OWNER}, {"$set": {"name": "x"}})
    mid = _owner_model(client)
    client.db.models.update_one({"_id": mid}, {"$set": {"name": "Urgent\r\nBcc: z@z.com " + "y" * 300}})
    USERS[OWNER]["name"] = "Support team\n" + "n" * 300
    try:
        client.post("/api/shares", json={"collection": "models", "artifact_id": mid, "email": "member@x.com"})
    finally:
        USERS[OWNER]["name"] = "Owner"
    [(to, subject, body)] = sent
    assert to == "member@x.com" and "\n" not in subject and "\r" not in subject and len(subject) < 200
    assert "(owner@x.com)" in body and "y" * 100 not in body and "n" * 100 not in body


# ---- What changed counts the workspace's own runs -----------------------------------------

def test_changes_ignore_runs_by_people_a_diagram_is_shared_with(client):
    from backend.services import rbds as rbds_service

    rbd = rbds_service.save_rbd(client.db, "Plant A", _series(_node("p", _exp(1e-3), _exp(0.1))), OWNER)
    now = datetime.now(timezone.utc)

    def job(jid, uid, when, availability):
        client.db.rbd_jobs.insert_one({"_id": jid, "kind": "availability", "status": "done", "uid": uid,
                                       "rbd_id": rbd.id, "created_at": when, "finished_at": when,
                                       "result": {"precision": {"window_availability": availability}}})

    job("own-old", OWNER, now - timedelta(days=60), 0.99)
    job("shared-new", OTHER, now - timedelta(days=1), 0.60)
    client.act_as(OWNER)
    assert client.get("/api/changes", params={"days": 30}).json()["simulations"] == []
    job("own-new", OWNER, now - timedelta(hours=1), 0.98)
    [row] = client.get("/api/changes", params={"days": 30}).json()["simulations"]
    assert row["run_id"] == "own-new" and row["runs"] == 1


def test_team_changes_count_every_members_runs(client):
    from backend.services import rbds as rbds_service

    tid = _team_with_member(client)
    rbd = rbds_service.save_rbd(client.db, "Team plant", _series(_node("p", _exp(1e-3), _exp(0.1))), f"team:{tid}")
    when = datetime.now(timezone.utc) - timedelta(hours=1)
    client.db.rbd_jobs.insert_one({"_id": "m1", "kind": "availability", "status": "done", "uid": MEMBER,
                                   "rbd_id": rbd.id, "created_at": when, "finished_at": when,
                                   "result": {"precision": {"window_availability": 0.9}}})
    client.act_as(OWNER)
    rows = client.get("/api/changes", params={"days": 30}, headers={"X-Workspace-Id": tid}).json()["simulations"]
    assert [r["run_id"] for r in rows] == ["m1"]


# ---- Run history after access ends --------------------------------------------------------

def test_runs_hide_the_diagram_once_access_ends(client):
    from backend.services import rbds as rbds_service

    graph = _series(_node("p", _exp(1e-3), _exp(0.1)))
    rbd = rbds_service.save_rbd(client.db, "Plant B", graph, OWNER)
    client.db.shares.insert_one({"_id": "s2", "collection": "rbds", "artifact_id": rbd.id, "grantor_uid": OWNER,
                                 "recipient_uid": OTHER, "recipient_email": "other@x.com",
                                 "created_at": datetime.now(timezone.utc)})
    when = datetime.now(timezone.utc)
    client.db.rbd_jobs.insert_one({"_id": "run1", "kind": "availability", "status": "done", "uid": OTHER,
                                   "rbd_id": rbd.id, "created_at": when, "finished_at": when,
                                   "request": {"graph": graph, "options": {}}, "result": {}})
    client.act_as(OTHER)
    assert client.get("/api/rbd-runs/run1").json()["rbd_name"] == "Plant B"
    assert client.get("/api/rbd-runs/run1").json()["inputs"]["diagram_changed_since"] is False

    client.db.shares.delete_one({"_id": "s2"})
    client.db.rbds.update_one({"_id": rbd.id}, {"$set": {"name": "Plant B (renamed)"}})
    detail = client.get("/api/rbd-runs/run1").json()
    assert detail["rbd_name"] is None and detail["inputs"]["diagram_changed_since"] is None
    assert client.get("/api/rbd-runs").json()["runs"][0]["rbd_name"] is None
    assert client.get("/api/rbd-runs/diagrams").json()["diagrams"] == [
        {"rbd_id": rbd.id, "name": "Diagram no longer available"}]
    exported = client.get("/api/rbd-runs/run1/export", params={"format": "json"}).json()
    assert exported["inputs"]["graph"] is None
    assert "renamed" not in str(client.get("/api/rbd-runs/run1").json())


# ---- Team deletion -------------------------------------------------------------------------

def test_deleting_a_team_removes_all_its_data(client):
    tid = _team_with_member(client)
    principal = f"team:{tid}"
    db = client.db
    db.alt_models.insert_one({"_id": "alt1", "owner_id": principal, "name": "ALT"})
    db.rbds.insert_one({"_id": "rbd1", "owner_id": principal, "name": "R", "graph": {}})
    db.rbd_jobs.insert_one({"_id": "job1", "rbd_id": "rbd1", "uid": MEMBER, "kind": "availability"})
    db.fleets.insert_one({"_id": "f1", "owner_id": principal, "name": "F"})
    db.fleet_alerts.insert_one({"_id": "fa1", "fleet_id": "f1"})
    db.fleet_forecasts.insert_one({"_id": "ff1", "fleet_id": "f1"})
    db.fleet_alert_events.insert_one({"_id": "fe1", "fleet_id": "f1"})
    db.model_refits.insert_one({"_id": "mr1", "owner_id": principal, "model_id": "m1"})
    # Someone else's records stay.
    db.alt_models.insert_one({"_id": "alt2", "owner_id": OWNER, "name": "Mine"})
    db.rbd_jobs.insert_one({"_id": "job2", "rbd_id": "rbd-mine", "uid": OWNER, "kind": "availability"})

    client.act_as(OWNER)
    assert client.delete(f"/api/teams/{tid}").status_code == 200
    for coll in ("alt_models", "rbds", "rbd_jobs", "fleets", "fleet_alerts", "fleet_forecasts",
                 "fleet_alert_events", "model_refits"):
        assert db[coll].count_documents({"_id": {"$nin": ["alt2", "job2"]}}) == 0, coll
    assert db.alt_models.count_documents({"_id": "alt2"}) == 1 and db.rbd_jobs.count_documents({"_id": "job2"}) == 1


# ---- Ids from request bodies are strings ------------------------------------------------

def test_non_string_ids_match_nothing(client):
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    datasets_service.create_dataset(client.db, "d", _degradation_csv(), OWNER)
    assert datasets_service.get_dataset(client.db, {"$ne": ""}, owner_id=OWNER) is None
    assert models_service.get_model(client.db, {"$ne": ""}, owner_id=OWNER) is None
