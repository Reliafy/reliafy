"""RCM studies: the stand-alone worksheet's create, read, save and delete, the
Free plan's limit, the sample study, and that a study saved before opens and
saves as it is."""

import io

import mongomock
import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


A = "user-a"
B = "user-b"


def _user(uid, email):
    return lambda: {"uid": uid, "email": email, "name": uid, "email_verified": True}


def _csv(kind: str) -> bytes:
    rng = np.random.default_rng(7)
    x = np.round(rng.weibull(3.0, 80) * 100, 2) if kind == "wear" else np.round(rng.exponential(100, 80), 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _make_model(session, owner, kind):
    from backend.services import datasets as ds
    from backend.services import models as ms

    dataset = ds.create_dataset(session, f"{kind}.csv", _csv(kind), owner)
    return ms.save_model(session, f"{kind} model", dataset, "weibull", {"x": "t"}, [], None, owner_id=owner)


def _mode(decision, mid="m1", consequence="operational"):
    return [{
        "id": "f1", "text": "Function",
        "failures": [{"id": "ff1", "text": "Failure", "modes": [
            {"id": mid, "text": "Mode", "consequence": consequence, "decision": decision},
        ]}],
    }]


def _status(session, owner, decision):
    from backend.services import rcm

    study = rcm.create_study(session, "S", "", "", owner)
    rcm.replace_tree(session, study.id, _mode(decision), owner)
    study = rcm.get_study(session, study.id, owner)
    resolved = rcm.resolve(session, study, owner)
    return resolved["functions"][0]["failures"][0]["modes"][0]["decision"]


# ---- CRUD + validation --------------------------------------------------------

def test_study_crud_and_tree_validation(session):
    from backend.services import rcm

    study = rcm.create_study(session, "Pumps", "Pump station", "", A)
    assert rcm.get_study(session, study.id, A) is not None
    assert rcm.get_study(session, study.id, B) is None  # isolation

    # Valid tree round trip; ids preserved, missing ids generated.
    tree = [{"text": "Fn", "failures": [{"id": "keep", "text": "FF", "modes": []}]}]
    updated = rcm.replace_tree(session, study.id, tree, A)
    assert updated.functions[0]["id"]  # generated
    assert updated.functions[0]["failures"][0]["id"] == "keep"

    with pytest.raises(rcm.RcmValidationError):  # empty text
        rcm.replace_tree(session, study.id, [{"text": " ", "failures": []}], A)
    with pytest.raises(rcm.RcmValidationError):  # bad consequence
        rcm.replace_tree(session, study.id, [{
            "text": "Fn", "failures": [{"text": "FF", "modes": [{"text": "M", "consequence": "bogus"}]}]}], A)
    with pytest.raises(rcm.RcmValidationError):  # rtf without basis
        rcm.replace_tree(session, study.id, _mode({"outcome": "rtf"}), A)
    with pytest.raises(rcm.RcmValidationError):  # bad interval
        rcm.replace_tree(session, study.id, _mode({"outcome": "fixed_interval", "interval": -5}), A)
    with pytest.raises(rcm.StudyNotFound):  # B can't write A's tree
        rcm.replace_tree(session, study.id, tree, B)

    rcm.rename_study(session, study.id, "Pumps v2", A)
    rcm.delete_study(session, study.id, A)
    assert rcm.get_study(session, study.id, A) is None


def test_a_study_keeps_hidden_as_its_own_consequence(session):
    """A study saved before stores "hidden" as a fifth consequence: it opens
    and saves with it, whatever the asset tree's RCM does with the word."""
    from backend.services import rcm

    study = rcm.create_study(session, "S", "", "", A)
    tree = _mode({"outcome": "failure_finding", "task": "Test it", "interval": 6, "interval_unit": "months"},
                 consequence="hidden")
    saved = rcm.replace_tree(session, study.id, tree, A)
    mode = saved.functions[0]["failures"][0]["modes"][0]
    assert mode["consequence"] == "hidden"
    assert set(mode) == {"id", "text", "consequence", "decision"}  # nothing added to the stored shape
    resolved = rcm.resolve(session, rcm.get_study(session, study.id, A), A)
    assert resolved["functions"][0]["failures"][0]["modes"][0]["consequence"] == "hidden"


def test_a_stored_study_opens_and_saves_unchanged(session):
    """A document written before (with fields this code no longer sets) reads
    back as stored, and a save of what was read changes only the stamp."""
    from datetime import datetime, timezone

    from backend.services import rcm
    from backend.services.rcm_sample import sample_truck_functions

    stamp = datetime(2026, 9, 1, tzinfo=timezone.utc)
    functions = rcm.clean_tree(sample_truck_functions())  # the shape a save has always stored
    session.rcm_studies.insert_one({
        "_id": "old-study", "id": "old-study", "name": "Old", "system": "Truck", "description": "", "owner_id": A,
        "updated_by": None, "created_at": stamp, "updated_at": stamp, "functions": functions,
        "migrated_to": "pos-1",
    })
    study = rcm.get_study(session, "old-study", A)
    assert study.functions == functions
    resolved = rcm.resolve(session, study, A)
    assert resolved["rollup"]["modes"] == 5 and resolved["rollup"]["decided"] == 5

    rcm.replace_tree(session, "old-study", study.functions, A)
    stored = session.rcm_studies.find_one({"_id": "old-study"})
    assert stored["functions"] == functions
    assert stored["migrated_to"] == "pos-1"  # kept as stored, not used


def test_rtf_random_statuses(session):
    wear = _make_model(session, A, "wear")
    rnd = _make_model(session, A, "random")
    d = {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": wear.id}}
    assert _status(session, A, d)["status"] == "contradicted"
    d["evidence"]["id"] = rnd.id
    assert _status(session, A, d)["status"] == "supported"
    assert _status(session, A, {"outcome": "rtf", "rtf_basis": "random"})["status"] == "unevidenced"
    d["evidence"]["id"] = "gone"
    assert _status(session, A, d)["status"] == "stale"


# ---- API: options, caps, isolation ---------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "FREE_MAX_RCM_STUDIES", 1)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    c = TestClient(app)
    c.db = test_db
    c.act_as = lambda uid: app.dependency_overrides.__setitem__(get_current_user, _user(uid, f"{uid}@x.com"))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def test_options_are_the_studys_own(client):
    client.act_as(A)
    options = client.get("/api/rcm/options").json()
    assert [c["id"] for c in options["consequences"]] == [
        "safety", "environmental", "operational", "non_operational", "hidden"]
    assert {o["id"] for o in options["outcomes"]} == {
        "on_condition", "fixed_interval", "rtf", "failure_finding", "redesign", "accept"}
    assert [b["id"] for b in options["rtf_bases"]] == ["random", "uneconomic"]


def test_api_caps_and_isolation(client, monkeypatch):
    from backend import config

    client.act_as(A)
    r = client.post("/api/rcm/studies", json={"name": "S1"})
    assert r.status_code == 200
    sid = r.json()["id"]
    r2 = client.post("/api/rcm/studies", json={"name": "S2"})
    assert r2.status_code == 402 and r2.json()["code"] == "cap"
    assert "RCM stud" in r2.json()["detail"]

    # Admin bypasses the cap.
    monkeypatch.setattr(config, "ADMIN_EMAILS", {f"{A}@x.com"})
    assert client.post("/api/rcm/studies", json={"name": "S3"}).status_code == 200
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())

    # PUT tree via API + resolved response shape.
    r = client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": [
        {"text": "Fn", "failures": [{"text": "FF", "modes": [
            {"text": "M", "consequence": "operational",
             "decision": {"outcome": "accept", "notes": "cheap part"}}]}]},
    ]})
    assert r.status_code == 200
    assert r.json()["rollup"]["modes"] == 1
    listed = client.get("/api/rcm/studies").json()["studies"]
    assert {s["id"] for s in listed} >= {sid} and listed[0]["rollup"]["modes"] in (0, 1)

    # The plan page counts studies.
    assert client.get("/api/billing").json()["caps"]["rcm_studies"] == 1

    # Rename, then isolation.
    assert client.patch(f"/api/rcm/studies/{sid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    client.act_as(B)
    assert client.get(f"/api/rcm/studies/{sid}").status_code == 404
    assert client.put(f"/api/rcm/studies/{sid}/tree", json={"functions": []}).status_code == 404
    assert client.delete(f"/api/rcm/studies/{sid}").status_code == 404
    client.act_as(A)
    assert client.delete(f"/api/rcm/studies/{sid}").json() == {"ok": True}
    assert client.get(f"/api/rcm/studies/{sid}").status_code == 404


def test_study_routes_removed_with_other_features_stay_gone(client):
    client.act_as(A)
    sid = client.post("/api/rcm/studies", json={"name": "S1"}).json()["id"]
    assert client.get(f"/api/rcm/studies/{sid}/maintenance-tasks").status_code in (404, 405)
    assert client.post("/api/rcm/import/preview").status_code in (404, 405)
    assert client.post("/api/rcm/import").status_code in (404, 405)


# ---- Sample study ---------------------------------------------------------------

def test_sample_study_seeds_with_contradicted_demo(client):
    from backend.services import samples

    samples.seed_samples(client.db)
    before = client.db.rcm_studies.find_one({"_id": "sample-rcm-truck"})
    samples.seed_samples(client.db)  # idempotent: a study already there is left as it is
    assert client.db.rcm_studies.count_documents({}) == 1
    assert client.db.rcm_studies.find_one({"_id": "sample-rcm-truck"}) == before

    client.act_as(A)
    study = client.get("/api/rcm/studies/sample-rcm-truck").json()
    assert study["is_sample"] is True and study["read_only"] is True
    assert study["rollup"]["supported"] == 3
    assert study["rollup"]["contradicted"] == 1  # the legacy RTF demo
    assert "sample-rcm-truck" in {s["id"] for s in client.get("/api/rcm/studies").json()["studies"]}

    # Read-only: PUT and rename refused; delete hides per-user.
    assert client.put("/api/rcm/studies/sample-rcm-truck/tree", json={"functions": []}).status_code == 403
    assert client.patch("/api/rcm/studies/sample-rcm-truck", json={"name": "x"}).status_code == 403
    assert client.delete("/api/rcm/studies/sample-rcm-truck").json()["ok"] is True
    assert client.get("/api/rcm/studies/sample-rcm-truck").status_code == 404
    client.act_as(B)
    assert client.get("/api/rcm/studies/sample-rcm-truck").status_code == 200
