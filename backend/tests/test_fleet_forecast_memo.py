"""A fleet forecast worked out once is handed back for exactly the same inputs, and only
for them: the same numbers as working it out again, and new numbers the moment a model,
a setting or an item changes."""

import mongomock
import pytest

from backend.tests.test_fleet import A, _fleet_with, _make_model


@pytest.fixture()
def session(monkeypatch):
    from backend import db
    from backend.services import fleet as fs

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    fs._LIFE_MEMO.clear()
    fs._REPAIRABLE_MEMO.clear()
    yield test_db


ITEMS = [{"id": f"i{k}", "name": f"Pump {k}", "current_use": 20.0 * k} for k in range(8)]


def _fresh(session, fleet):
    """The forecast worked out from nothing (no memo)."""
    from backend.services import fleet as fs

    fs._LIFE_MEMO.clear()
    fs._REPAIRABLE_MEMO.clear()
    return fs.compute(session, fleet, [A])


@pytest.mark.parametrize("method", ["renewals", "single"])
def test_a_hit_is_the_same_forecast(session, method):
    from backend.services import fleet as fs

    model = _make_model(session, A)
    fleet = _fleet_with(session, A, model, ITEMS, method=method, rate=2.0)
    first = _fresh(session, fleet)
    calls = []
    real = fs._compute_life
    fs._compute_life = lambda inputs: calls.append(1) or real(inputs)
    try:
        again = fs.compute(session, fleet, [A])
    finally:
        fs._compute_life = real
    assert calls == []  # handed back, not worked out
    assert again == first
    assert again["status"] == "ok" and again["expected"] > 0


def test_changing_the_answer_leaves_the_memo_alone(session):
    from backend.services import fleet as fs

    model = _make_model(session, A)
    fleet = _fleet_with(session, A, model, ITEMS, method="renewals", rate=2.0)
    first = fs.compute(session, fleet, [A])
    expected = first["expected"]
    first["expected"] = -1
    first["per_item"].clear()
    again = fs.compute(session, fleet, [A])
    assert again["expected"] == expected and again["per_item"]


def test_a_refit_model_is_forecast_again(session):
    from backend.services import fleet as fs
    from backend.services import models as ms

    model = _make_model(session, A)
    fleet = _fleet_with(session, A, model, ITEMS, method="renewals", rate=2.0)
    before = fs.compute(session, fleet, [A])
    # A refit stores new parameters (whatever its updated_at says).
    params = [dict(p) for p in model.results["params"]]
    for p in params:
        if p.get("name") == "alpha":
            p["value"] = p["value"] * 1.5
    session.models.update_one({"_id": model.id}, {"$set": {"results.params": params}})
    after = fs.compute(session, fleet, [A])
    assert after["expected"] < before["expected"]
    assert after == _fresh(session, fleet)
    assert ms.get_model(session, model.id, A).results["params"] == params


def test_changed_items_or_settings_are_forecast_again(session):
    from backend.services import fleet as fs

    model = _make_model(session, A)
    fleet = _fleet_with(session, A, model, ITEMS, method="single", rate=2.0)
    before = fs.compute(session, fleet, [A])
    older = [{**it, "current_use": it["current_use"] + 60} for it in ITEMS]
    moved = _fleet_with(session, A, model, older, method="single", rate=2.0)
    assert fs.compute(session, moved, [A])["expected"] != before["expected"]
    longer = _fleet_with(session, A, model, ITEMS, method="single", periods=24, rate=2.0)
    assert fs.compute(session, longer, [A])["expected"] > before["expected"]
    assert fs.compute(session, fleet, [A]) == before


def test_a_model_no_longer_readable_is_not_handed_back(session):
    from backend.services import fleet as fs

    model = _make_model(session, A)
    fleet = _fleet_with(session, A, model, ITEMS, method="renewals", rate=2.0)
    assert fs.compute(session, fleet, [A])["status"] == "ok"
    assert fs.compute(session, fleet, ["someone-else"])["status"] == "stale"
    session.models.delete_one({"_id": model.id})
    assert fs.compute(session, fleet, [A])["status"] == "stale"


def test_repairable_fleet_memo_follows_the_live_fit(session):
    from backend.services import fleet as fs
    from backend.services import recurrent as recurrent_service
    from backend.tests.test_repairable_fleets import _fleet

    fleet, model = _fleet(session, [{"id": "a", "name": "P1", "current_use": 100.0},
                                    {"id": "b", "name": "P2", "current_use": 400.0, "rate": 40.0}])
    first = _fresh(session, fleet)
    assert fs.compute(session, fleet, [A]) == first
    # A new live fit (the model fitted again) is a new object: worked out again from it.
    recurrent_service._LIVE.pop(model.id, None)
    assert fs.compute(session, fleet, [A]) == first
    assert len(fs._REPAIRABLE_MEMO._rows) == 2
