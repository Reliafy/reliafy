"""A block linked to a saved model takes the model's current fit, never the copy stored on the
block when the model was picked: a revised model reaches every diagram that uses it, on every
route (the diagram as read, the Calculator's posted graph, the saved diagram's analysis, the
downloads)."""

import math

import mongomock
import pytest

from backend.schema import Model
from backend.db import to_doc
from backend.services import rbd_live_models, rbds

UID = "user-live-models"
USER = {"uid": UID, "email": "live@example.com", "name": "Live", "email_verified": True}

# The block was built from the seal's first fit; the seal model was then revised.
OLD = (2588.0, 1.53)
NEW = (2200.0, 1.6)


def _sf(alpha, beta, t):
    return math.exp(-((t / alpha) ** beta))


def _seal_model(db):
    doc = Model(id="seal-model", name="Mechanical seal", owner_id=UID, kind="distribution",
                distribution_id="weibull",
                results={"distribution": "Weibull", "distribution_id": "weibull", "unit": "hours",
                         "params": [{"name": "alpha", "value": NEW[0]}, {"name": "beta", "value": NEW[1]}]})
    db.models.insert_one(to_doc(doc))
    return doc


def _graph():
    stale = {"source": "saved", "kind": "distribution", "modelId": "seal-model", "name": "Mechanical seal",
             "distribution": "Weibull", "distribution_id": "weibull", "unit": "hours",
             "params": [{"name": "alpha", "value": OLD[0]}, {"name": "beta", "value": OLD[1]}]}
    return {"unit": "hours", "nodes": [
        {"id": "input", "type": "input", "data": {"label": "Input"}},
        {"id": "seal", "type": "component", "data": {"label": "Seal", "model": stale}},
        {"id": "output", "type": "output", "data": {"label": "Output"}}],
        "edges": [{"id": "e1", "source": "input", "target": "seal"}, {"id": "e2", "source": "seal", "target": "output"}]}


def test_the_numbers_this_fixes():
    # One seal at 500 h: the stale copy says 0.9223, the revised model 0.9108. (In the reported
    # pump diagram, with its other blocks, the system figure went from 0.9333 to 0.9314.)
    assert round(_sf(*OLD, 500.0), 4) == 0.9223
    assert round(_sf(*NEW, 500.0), 4) == 0.9108


def test_refresh_puts_a_linked_block_on_its_models_current_fit():
    db = mongomock.MongoClient()["live_models"]
    _seal_model(db)
    graph = _graph()
    out = rbd_live_models.refresh(db, graph, [UID])
    model = out["nodes"][1]["data"]["model"]
    assert [p["value"] for p in model["params"]] == list(NEW)
    assert model["modelId"] == "seal-model" and model["source"] == "saved"
    assert graph["nodes"][1]["data"]["model"]["params"][0]["value"] == OLD[0]  # input untouched


def test_an_unreadable_model_keeps_the_blocks_copy():
    db = mongomock.MongoClient()["live_models_gone"]
    graph = _graph()
    assert rbd_live_models.refresh(db, graph, [UID]) is graph
    other = mongomock.MongoClient()["live_models_other"]
    _seal_model(other)
    assert rbd_live_models.refresh(other, graph, ["someone-else"]) is graph  # not in the reader's scope


def test_a_standby_units_own_model_is_refreshed_too():
    db = mongomock.MongoClient()["live_models_standby"]
    _seal_model(db)
    stale = _graph()["nodes"][1]["data"]["model"]
    graph = {"nodes": [{"id": "sb", "type": "standby", "data": {"label": "Pumps", "spareModels": [stale]}}]}
    out = rbd_live_models.refresh(db, graph, [UID])
    assert out["nodes"][0]["data"]["spareModels"][0]["params"][0]["value"] == NEW[0]


def test_saved_reads_and_posted_graphs_both_use_the_revised_model():
    db = mongomock.MongoClient()["live_models_service"]
    _seal_model(db)
    rbd = rbds.save_rbd(db, "Pump end", _graph(), UID)
    # The diagram as read (the builder, the saved diagram's routes, sub-systems).
    read = rbds.get_rbd(db, rbd.id, UID)
    assert read.graph["nodes"][1]["data"]["model"]["params"][0]["value"] == NEW[0]
    # A posted graph still holding the stale copy (an editor opened before the revision).
    out = rbds.analyze_graph(db, _graph(), UID, at_times=[500.0])
    assert out["at"]["sf"][0] == pytest.approx(_sf(*NEW, 500.0), rel=1e-6)
    # The Python download writes the revised parameters.
    _, source = rbds.export_python(db, "Pump end", _graph(), UID)
    assert "2200" in source and "2588" not in source


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_live_models"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    test_db.users.update_one({"_id": UID}, {"$set": {"email": USER["email"], "email_lc": USER["email"],
                                                     "name": USER["name"], "email_verified": True}}, upsert=True)
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_every_rbd_route_reads_the_revised_model(client):
    _seal_model(client.db)
    rbd = rbds.save_rbd(client.db, "Pump end", _graph(), UID)
    got = client.get(f"/api/rbds/{rbd.id}").json()
    assert got["graph"]["nodes"][1]["data"]["model"]["params"][0]["value"] == NEW[0]
    saved = client.get(f"/api/rbds/{rbd.id}/analyze").json()
    posted = client.post("/api/rbds/analyze", json={"graph": _graph()}).json()
    mttf = NEW[0] * math.gamma(1 + 1 / NEW[1])  # 1,972 h (the stale copy: 2,328 h)
    for out in (saved, posted):
        assert out["mttf"] == pytest.approx(mttf, rel=1e-3)
