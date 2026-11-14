"""A saved Bayesian update in the Strategy calculators and the forecasts: each works with the
update's posterior predictive (the curve its page shows), not the distribution at its
parameters' middle values (which the stored ``params`` are)."""

import mongomock
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.services import bayes_life as bl
from backend.services import strategy

OWNER = "u1"


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    d = mongomock.MongoClient()["bayes_calculators"]
    monkeypatch.setattr(db, "_db", d)
    monkeypatch.setattr(db, "_simulated", True)
    return d


@pytest.fixture()
def client(session, monkeypatch):
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _update(session):
    # A Weibull baseline (5,000 h, shape 2) trusted only as a starting point, then two failures
    # and two survivors: the posterior is wide, so the middle values tell a tidier story.
    base = bl.baseline_from(session, [OWNER], set(), {"distribution": "weibull",
                                                       "params": {"alpha": 5000, "beta": 2}, "unit": "hours"})
    model, result, priors = bl.update(base, "start", bl.given_rows([900.0, 1500.0, 2000.0, 2500.0], [0, 0, 1, 1]))
    doc = bl.save(session, OWNER, model, result, priors, "Seal update")
    params = [{"name": p["name"], "value": p["value"], "ci": p.get("ci")} for p in doc.results["params"]]
    return doc, params, bl.predictive(bl.posterior_extras(doc)["posterior"])


def _sf(life, t):
    return float(np.ravel(life.sf(t))[0])


def test_the_calculators_life_is_the_updates_own_curve(session):
    doc, params, life = _update(session)
    got, _ = strategy._model_from_params("weibull", params, bl.posterior_extras(doc))
    model = bl.rebuild(doc.spec)
    for t in (500.0, 1000.0, 3000.0):
        assert _sf(got, t) == pytest.approx(_sf(model, t), rel=1e-9)
    mid, _ = strategy._model_from_params("weibull", params, None)
    assert abs(_sf(mid, 1000.0) - _sf(got, 1000.0)) > 5e-3


def test_optimal_replacement_uses_the_posterior_predictive(client, session):
    doc, params, life = _update(session)
    body = {"distribution_id": "weibull", "params": params, "planned_cost": 100, "unplanned_cost": 1000,
            "unit": "hours"}
    middle = client.post("/api/strategy/optimal-replacement", json=body).json()
    r = client.post("/api/strategy/optimal-replacement", json={**body, "model_id": doc.id})
    assert r.status_code == 200, r.text
    out = r.json()
    point = strategy._replacement_point(life, 100.0, 1000.0, False)
    assert out["optimal_time"] == pytest.approx(point["optimal_time"], rel=1e-9)
    assert out["mttf"] == pytest.approx(float(life.mean()), rel=1e-9)
    assert out["mttf"] > middle["mttf"] * 1.03  # the middle values' mean life was too short here
    assert abs(out["optimal_time"] - middle["optimal_time"]) > 20
    # No parameter-bounds range: the predictive already allows for how unsure they are.
    assert out["optimal_time_range"] is None and "Bayesian update" in out["optimal_time_range_note"]
    assert out["block"] is not None


def test_a_recipe_from_a_client_is_ignored(client, session):
    doc, params, _ = _update(session)
    body = {"distribution_id": "weibull", "params": params, "planned_cost": 100, "unplanned_cost": 1000,
            "unit": "hours"}
    plain = client.post("/api/strategy/optimal-replacement", json=body).json()
    sent = client.post("/api/strategy/optimal-replacement",
                       json={**body, "extras": bl.posterior_extras(doc)}).json()
    assert sent["optimal_time"] == pytest.approx(plain["optimal_time"], rel=1e-12)


def test_failure_finding_uses_the_posterior_predictive(client, session):
    doc, params, life = _update(session)
    body = {"distribution_id": "weibull", "params": params, "target_availability": 0.99, "unit": "hours"}
    middle = client.post("/api/strategy/failure-finding", json=body).json()
    r = client.post("/api/strategy/failure-finding", json={**body, "model_id": doc.id})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mttf"] == pytest.approx(float(life.mean()), rel=1e-9)
    assert out["interval"] != pytest.approx(middle["interval"], rel=1e-3)
    assert out["interval_bound"] is None


def test_calendar_replacement_and_next_use_the_posterior_predictive(client, session):
    from backend.services import strategy_calendar

    doc, params, _ = _update(session)
    body = {"distribution_id": "weibull", "params": params, "unit": "hours", "today": "2027-01-01",
            "opportunities": [{"name": "shut", "cost": 100, "every": 30, "every_unit": "days",
                               "start": "2027-01-01"}],
            "failure_cost": 1000}
    middle = client.post("/api/strategy/calendar-replacement", json=body).json()
    r = client.post("/api/strategy/calendar-replacement", json={**body, "model_id": doc.id})
    assert r.status_code == 200, r.text
    expected = strategy_calendar.calendar_replacement(
        "weibull", params, **{k: v for k, v in body.items() if k not in ("distribution_id", "params")},
        extras=bl.posterior_extras(doc))
    assert r.json()["cost_rate"] == pytest.approx(expected["cost_rate"], rel=1e-9)
    assert r.json()["cost_rate"] != pytest.approx(middle["cost_rate"], rel=1e-3)
    nxt = client.post("/api/strategy/calendar-next", json={**body, "model_id": doc.id, "age": 1500})
    assert nxt.status_code == 200, nxt.text


def test_compare_two_uses_the_posterior_predictive(client, session):
    doc, params, life = _update(session)
    side = {"distribution_id": "weibull", "params": params}
    r = client.post("/api/strategy/compare-two", json={"a": {**side, "model_id": doc.id}, "b": side,
                                                        "unit": "hours"})
    assert r.status_code == 200, r.text
    a, b = r.json()["a"]["metrics"], r.json()["b"]["metrics"]
    assert a["b10"] == pytest.approx(float(np.ravel(life.qf(0.1))[0]), rel=1e-6)
    assert a["b10"] < b["b10"] * 0.95  # the middle values' B10 was too long


def test_mcp_inputs_from_a_saved_update_carry_its_recipe(session):
    from backend import mcp_server

    doc, _, _ = _update(session)
    inputs = mcp_server._dist_inputs(session, OWNER, doc.id, None, None, None)
    assert strategy.is_posterior(inputs["extras"])
    assert mcp_server._weibull_beta_ci(session, OWNER, doc.id, inputs) is None


def test_the_rcm_calculators_start_from_the_updates_curve(session):
    from backend.services import rcm_intervals

    doc, _, life = _update(session)
    given = rcm_intervals.model_inputs(doc)
    assert strategy.is_posterior(given["extras"])
    got, _ = strategy._model_from_params(given["distribution_id"], given["params"], given["extras"])
    assert _sf(got, 1000.0) == pytest.approx(_sf(life, 1000.0), rel=1e-12)


def test_a_fleet_forecast_on_a_saved_update(session):
    from backend.services import fleet as fs

    doc, _, life = _update(session)
    fleet = fs.create_fleet(session, "Seals", doc.id, OWNER)
    items = [{"name": "S1", "current_use": 0}, {"name": "S2", "current_use": 1000}]
    fleet = fs.replace_items(session, fleet.id, {"periods": 3, "default_rate": 300, "method": "single"},
                             items, OWNER)
    out = fs.compute(session, fleet, [OWNER])
    assert out["status"] == "ok", out
    use = 900.0
    expected = sum(1 - _sf(life, a + use) / _sf(life, a) for a in (0.0, 1000.0))
    assert out["expected"] == pytest.approx(expected, rel=1e-6)
