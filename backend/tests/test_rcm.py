"""RCM studies: worksheet CRUD, caps, and live evidence-status resolution."""

import matplotlib

matplotlib.use("Agg")

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


def _csv(kind: str) -> bytes:
    rng = np.random.default_rng(7)
    if kind == "wear":
        x = np.round(rng.weibull(3.0, 80) * 100, 2)
    else:  # random
        x = np.round(rng.exponential(100, 80), 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _make_model(session, owner, kind, distribution="weibull"):
    from backend.services import datasets as ds
    from backend.services import models as ms

    dataset = ds.create_dataset(session, f"{kind}.csv", _csv(kind), owner)
    return ms.save_model(session, f"{kind} model", dataset, distribution, {"x": "t"}, [], None, owner_id=owner)


def _make_replacement(session, owner, beneficial: bool):
    """Save an optimal-replacement analysis; wear-out params + high failure cost
    -> beneficial, exponential -> not beneficial."""
    from backend.services import strategy_store

    if beneficial:
        inputs = {"distribution_id": "weibull",
                  "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}],
                  "planned_cost": 100.0, "unplanned_cost": 2000.0, "unit": "hours"}
    else:
        inputs = {"distribution_id": "exponential",
                  "params": [{"name": "failure_rate", "value": 0.001}],
                  "planned_cost": 100.0, "unplanned_cost": 2000.0, "unit": "hours"}
    return strategy_store.save_analysis(session, "repl", "optimal_replacement", inputs, owner)


def _mode(decision, mid="m1"):
    return [{
        "id": "f1", "text": "Function",
        "failures": [{"id": "ff1", "text": "Failure", "modes": [
            {"id": mid, "text": "Mode", "consequence": "operational", "decision": decision},
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
        rcm.replace_tree(session, study.id, _mode(None) and [{
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


# ---- Evidence-status rules ------------------------------------------------------

def test_rtf_random_statuses(session):
    wear = _make_model(session, A, "wear")             # beta ~ 3 -> wear_out
    random_m = _make_model(session, A, "random")       # beta ~ 1 -> random
    expo = _make_model(session, A, "random", "exponential")

    d = {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": random_m.id}}
    assert _status(session, A, d)["status"] == "supported"

    d["evidence"]["id"] = wear.id
    r = _status(session, A, d)
    assert r["status"] == "contradicted"
    assert "wear-out" in r["summary"]

    d["evidence"]["id"] = expo.id
    assert _status(session, A, d)["status"] == "supported"

    # Old model without CI info -> inconclusive with a re-save hint.
    from backend import db as db_module
    session.models.update_one({"_id": wear.id}, {"$unset": {"results.randomness": ""}})
    session.models.update_one({"_id": wear.id}, {"$set": {"results.params": [
        {"name": "alpha", "value": 100.0}, {"name": "beta", "value": 3.0}]}})
    d["evidence"]["id"] = wear.id
    r = _status(session, A, d)
    assert r["status"] == "inconclusive" and "re-save" in r["reason"]


def test_replacement_statuses(session):
    good = _make_replacement(session, A, beneficial=True)
    bad = _make_replacement(session, A, beneficial=False)

    fixed = {"outcome": "fixed_interval", "evidence": {"type": "strategy_analysis", "id": good.id}}
    r = _status(session, A, fixed)
    assert r["status"] == "supported" and "Optimal interval" in r["summary"]

    fixed["evidence"]["id"] = bad.id
    assert _status(session, A, fixed)["status"] == "contradicted"

    rtf_u = {"outcome": "rtf", "rtf_basis": "uneconomic",
             "evidence": {"type": "strategy_analysis", "id": bad.id}}
    assert _status(session, A, rtf_u)["status"] == "supported"
    rtf_u["evidence"]["id"] = good.id
    assert _status(session, A, rtf_u)["status"] == "contradicted"


def test_on_condition_ffi_mismatch_unevidenced_stale(session):
    from backend.services import datasets as ds
    from backend.services import degradation as deg
    from backend.services import strategy_store

    # Degradation model for on_condition.
    rows = []
    rng = np.random.default_rng(0)
    for u in range(4):
        for t in np.arange(1, 7) * 50.0:
            rows.append({"i": f"u{u}", "t": t, "y": 1 + (0.02 + 0.003 * u) * t + rng.normal(0, 0.05)})
    buf = io.StringIO(); pd.DataFrame(rows).to_csv(buf, index=False)
    dataset = ds.create_dataset(session, "deg.csv", buf.getvalue().encode(), A)
    dmodel = deg.save_model(session, "Deg", dataset,
                            {"mapping": {"i": "i", "x": "t", "y": "y"}, "threshold": 8.0,
                             "path": "linear", "distribution_id": "weibull",
                             "population_method": "moments", "unit": "h", "measurement_unit": "mm"}, A)
    oc = {"outcome": "on_condition", "evidence": {"type": "degradation_model", "id": dmodel.id}}
    assert _status(session, A, oc)["status"] == "supported"

    # Failure finding.
    ffi = strategy_store.save_analysis(session, "ffi", "failure_finding",
        {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.001}],
         "target_availability": 0.99, "unit": "h"}, A)
    ff = {"outcome": "failure_finding", "evidence": {"type": "strategy_analysis", "id": ffi.id}}
    r = _status(session, A, ff)
    assert r["status"] == "supported" and "Check every" in r["summary"]

    # Type mismatch -> inconclusive.
    mm = {"outcome": "on_condition", "evidence": {"type": "strategy_analysis", "id": ffi.id}}
    assert _status(session, A, mm)["status"] == "inconclusive"

    # Unevidenced.
    assert _status(session, A, {"outcome": "fixed_interval", "evidence": None})["status"] == "unevidenced"

    # Redesign / accept -> no status.
    assert _status(session, A, {"outcome": "redesign"})["status"] is None

    # Stale: delete the artifact.
    deg.delete_model(session, dmodel.id, A)
    assert _status(session, A, oc)["status"] == "stale"


# ---- API: caps + isolation -----------------------------------------------------

def test_api_caps_and_isolation(monkeypatch):
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
    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        r = client.post("/api/rcm/studies", json={"name": "S1"})
        assert r.status_code == 200
        sid = r.json()["id"]
        r2 = client.post("/api/rcm/studies", json={"name": "S2"})
        assert r2.status_code == 402 and r2.json()["code"] == "cap"

        # Admin bypasses the cap.
        monkeypatch.setattr(config, "ADMIN_EMAILS", {"a@x.com"})
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

        # usage_summary carries the new key.
        assert client.get("/api/billing").json()["caps"]["rcm_studies"] == 1

        # Isolation.
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b@x.com", "name": "B"}
        assert client.get(f"/api/rcm/studies/{sid}").status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---- Sample study ---------------------------------------------------------------

def test_sample_study_seeds_with_contradicted_demo(session, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    samples.seed_samples(session)
    samples.seed_samples(session)  # idempotent
    assert session.rcm_studies.count_documents({}) == 1

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        study = client.get("/api/rcm/studies/sample-rcm-truck").json()
        assert study["is_sample"] is True
        assert study["rollup"]["supported"] == 3
        assert study["rollup"]["contradicted"] == 1  # the legacy RTF demo

        # Read-only: PUT and rename refused; delete hides per-user.
        assert client.put("/api/rcm/studies/sample-rcm-truck/tree", json={"functions": []}).status_code == 403
        assert client.patch("/api/rcm/studies/sample-rcm-truck", json={"name": "x"}).status_code == 403
        assert client.delete("/api/rcm/studies/sample-rcm-truck").json()["ok"] is True
        assert client.get("/api/rcm/studies/sample-rcm-truck").status_code == 404
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b@x.com", "name": "B"}
        assert client.get("/api/rcm/studies/sample-rcm-truck").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_unit_mismatch_blocks_support(session):
    """A task interval in a different unit than its evidence resolves
    inconclusive — units are free text, so only definite disagreement trips."""
    analysis = _make_replacement(session, A, beneficial=True)  # unit: hours

    def status_for(interval_unit):
        return _status(session, A, {
            "outcome": "fixed_interval", "task": "replace", "interval": 500,
            "interval_unit": interval_unit,
            "evidence": {"type": "strategy_analysis", "id": analysis.id},
        })

    # Definite mismatch -> inconclusive with a unit-specific reason.
    bad = status_for("km")
    assert bad["status"] == "inconclusive" and "Unit mismatch" in bad["reason"]
    # Aliases of the same unit agree.
    assert status_for("hrs")["status"] == "supported"
    assert status_for("hours")["status"] == "supported"
    # Missing unit on the decision passes (can't prove a contradiction).
    ok = _status(session, A, {
        "outcome": "fixed_interval", "task": "replace",
        "evidence": {"type": "strategy_analysis", "id": analysis.id},
    })
    assert ok["status"] == "supported"
