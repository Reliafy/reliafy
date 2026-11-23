"""The slimmer reads a large workspace's Home and Forecasts use give exactly the numbers
of the full reads: the overview without its tree, the RCM rollup alone, the linked
evidence read in one query per kind, and every class's forecast in one request."""

import mongomock
import pytest

from backend.maintenance import forecast
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_forecast import _model, _pumps
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - a fixture

M = "/api/maintenance"


def _ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def _rcm_workspace(api):
    """Two pumps under a plant, with decisions linking a sample model, a model that
    exists nowhere, and none."""
    plant = _ok(api.post(f"{M}/positions", json={"name": "Plant"}))
    modes = []
    for name in ("Pump A", "Pump B"):
        pump = _ok(api.post(f"{M}/positions", json={"name": name, "parent_id": plant["id"]}))
        for text in ("Bearing seizes", "Seal leaks", "Impeller wears"):
            modes.append(_ok(api.post(f"{M}/positions/{pump['id']}/failure-modes", json={"text": text})))
    evidence = ["sample-model-bearings-weibull", "not-a-model", None, "sample-model-bearings-weibull"]
    for mode, eid in zip(modes, evidence):
        decision = {"outcome": "rtf", "rtf_basis": "random"}
        if eid:
            decision["evidence"] = {"type": "model", "id": eid}
        _ok(api.put(f"{M}/failure-modes/{mode['id']}/decision",
                    json={"consequence": "operational", "decision": decision}))
    return plant


def test_rollup_only_is_the_full_reads_rollup(api):
    plant = _rcm_workspace(api)
    full = _ok(api.get(f"{M}/rcm"))
    assert full["rollup"]["modes"] == 6 and full["rollup"]["decided"] == 4
    assert full["rollup"]["contradicted"] == 2 and full["rollup"]["stale"] == 1
    assert _ok(api.get(f"{M}/rcm", params={"rollup_only": "true"})) == {"rollup": full["rollup"]}
    within = _ok(api.get(f"{M}/rcm", params={"within": plant["id"]}))
    assert _ok(api.get(f"{M}/rcm", params={"within": plant["id"], "rollup_only": "true"})) == \
        {"rollup": within["rollup"]}


def test_linked_evidence_is_read_once_per_kind(api, monkeypatch):
    from backend.services import models as models_service

    _rcm_workspace(api)
    before = _ok(api.get(f"{M}/rcm"))
    singles = []
    real = models_service.get_model
    monkeypatch.setattr(models_service, "get_model",
                        lambda db, mid, owner=None: singles.append(mid) or real(db, mid, owner))
    again = _ok(api.get(f"{M}/rcm"))
    assert again == before
    # The evidence check reads none one at a time now (a position's own failure rate still may).
    assert "not-a-model" not in singles


def test_prefetch_gives_what_fetching_each_gives(api):
    from backend import db
    from backend.maintenance import rcm_decisions

    session = db.get_db()
    refs = [("model", "sample-model-bearings-weibull"), ("model", "not-a-model"), ("strategy_analysis", "nope"),
            ("degradation_model", "nope"), ("report", "nope"), ("model", "repairable:nope")]
    one = rcm_decisions.evidence_fetcher(session, "user-r")
    batched = rcm_decisions.evidence_fetcher(session, "user-r")
    batched.prefetch(refs)
    for etype, eid in refs:
        assert batched(etype, eid) == one(etype, eid)
    assert batched("model", "sample-model-bearings-weibull") is not None
    # Scoped to the reader as each fetch is: someone else's model isn't handed over.
    session.models.insert_one({**session.models.find_one({"_id": "sample-model-bearings-weibull"}),
                               "_id": "theirs", "owner_id": "someone-else"})
    hidden = rcm_decisions.evidence_fetcher(session, "user-r")
    hidden.prefetch([("model", "theirs")])
    assert hidden("model", "theirs") is None
    shown = rcm_decisions.evidence_fetcher(session, "user-r", frozenset({"sample-model-bearings-weibull"}))
    shown.prefetch([("model", "sample-model-bearings-weibull")])
    assert shown("model", "sample-model-bearings-weibull") is None  # hidden from this reader


def test_overview_without_its_tree_is_the_rest_unchanged(api):
    _rcm_workspace(api)
    full = _ok(api.get(f"{M}/overview"))
    slim = _ok(api.get(f"{M}/overview", params={"tree": "false"}))
    assert "tree" in full and "tree" not in slim
    assert slim == {k: v for k, v in full.items() if k != "tree"}


@pytest.fixture()
def fapi(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_forecasts"])
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": "user-f", "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        yield TestClient(app), Maintenance(store, "user-f", "user-f")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_every_class_forecast_in_one_request(fapi):
    client, m = fapi
    _pumps(m, name="Pool pump")
    _pumps(m, n=2, name="Fan")
    _model(m, "Pool pump")
    _model(m, "Fan", "weibull", [{"name": "alpha", "value": 400.0}, {"name": "beta", "value": 2.0}])
    _pumps(m, n=1, name="Valve")  # no model: can't be worked out
    forecast._CACHE.clear()
    names = ["Pool pump", "Fan", "Valve", "Nope"]
    batch = _ok(client.get(f"{M}/classes/forecasts", params={"position_class": names}))["forecasts"]
    assert list(batch) == names
    for name in ("Pool pump", "Fan"):
        one = _ok(client.get(f"{M}/classes/forecast", params={"position_class": name}))
        assert batch[name] == one and one["expected"] > 0
    assert batch["Valve"]["error"] is True and batch["Valve"]["detail"]
    assert batch["Nope"] == {"error": True, "detail": "Not found."}
    assert _ok(client.get(f"{M}/classes/forecasts"))["forecasts"] == {}
    too_many = client.get(f"{M}/classes/forecasts", params={"position_class": [f"c{i}" for i in range(201)]})
    assert too_many.status_code == 422
