"""The Calculator on a model made from parameters alone (no data, no fit) — planning #418.

Such a model has no dataset to refit and no saved fit to restore, so every
calculator request that needed the live model answered "Model not found": the
time at a reliability, re-drawing the curves over a wider axis, and the life
figures over the API. The model is its parameters, so the live model is
rebuilt from them: point answers everywhere, and no bounds, with a plain note
saying why (there's no fit to base them on).
"""
import math

import mongomock
import pytest

pytestmark = pytest.mark.usefixtures("mcp_on")

WEIBULL = [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2.5}]
EXPONENTIAL = [{"name": "failure_rate", "value": 0.001}]


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app
    from backend.services import models as models_service

    monkeypatch.setattr(config, "AUTH_DISABLED", True)  # single-user: /api/v1 needs no token
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_calc_params"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    models_service._LIVE.clear()
    tc = TestClient(app)
    tc.db = test_db
    return tc


def _make(client, distribution, params, name="Handbook"):
    r = client.post("/api/models/from-params",
                    json={"name": name, "distribution": distribution, "unit": "hours", "params": params})
    assert r.status_code == 200, r.text
    return r.json()


def _weibull_time(r, alpha=1000.0, beta=2.5):
    return alpha * (-math.log(r)) ** (1 / beta)


def test_the_calculator_is_given_paths_to_answer_from_but_no_bounds(client):
    fns = _make(client, "weibull", WEIBULL)["results"]["functions"]
    assert fns["evaluate_path"].endswith("/evaluate")
    assert fns["life_path"].endswith("/life")
    assert "confidence_path" not in fns  # nothing to base bounds on
    assert "entered from parameters" in fns["bands_note"]


def test_time_at_reliability_is_exact_with_a_plain_note_on_bounds(client):
    m = _make(client, "weibull", WEIBULL)
    r = client.post(f"/api/models/{m['id']}/life",
                    json={"reliability": [0.9, 0.005], "confidence": 0.9, "bound": "lower"})
    assert r.status_code == 200, r.text
    body = r.json()
    b10, far = body["points"]
    assert b10["time"] == pytest.approx(_weibull_time(0.9), rel=1e-9)  # 406.5 hours
    # Past the 99% the stored curve stops at: still answered, from the model.
    assert far["time"] == pytest.approx(_weibull_time(0.005), rel=1e-9)
    assert b10["lower"] is None and b10["upper"] is None
    assert "entered from parameters" in body["bounds_note"]


def test_b_lives_and_mttf_of_an_exponential(client):
    m = _make(client, "exponential", EXPONENTIAL)
    body = client.post(f"/api/models/{m['id']}/life", json={"confidence": 0.9}).json()
    b50 = next(b for b in body["b_lives"] if b["label"] == "B50")
    assert b50["value"] == pytest.approx(math.log(2) / 0.001)
    assert body["mttf"]["value"] == pytest.approx(1000.0)
    assert b50["lower"] is None


def test_the_curves_are_redrawn_over_a_wider_axis(client):
    m = _make(client, "weibull", WEIBULL)
    stored_end = m["results"]["functions"]["curves"]["x"][-1]
    r = client.post(f"/api/models/{m['id']}/evaluate?x_max=3000", json={})
    assert r.status_code == 200, r.text
    curves = r.json()["curves"]
    assert curves["x"][-1] == pytest.approx(3000) and stored_end < 3000
    assert curves["sf"][-1] == pytest.approx(math.exp(-((3000 / 1000) ** 2.5)), rel=1e-6)


def test_bounds_asked_for_are_refused_in_plain_words(client):
    m = _make(client, "weibull", WEIBULL)
    r = client.post(f"/api/models/{m['id']}/confidence", json={"on": "sf", "alpha_ci": 0.1})
    assert r.status_code == 422
    assert "entered from parameters" in r.json()["detail"]


def test_edited_parameters_are_the_ones_answered_from(client):
    m = _make(client, "exponential", EXPONENTIAL)
    client.post(f"/api/models/{m['id']}/life", json={"reliability": [0.5]})  # the live model is cached
    r = client.put(f"/api/models/{m['id']}/params", json={
        "distribution": "exponential", "unit": "hours", "params": [{"name": "failure_rate", "value": 0.002}]})
    assert r.status_code == 200, r.text
    t = client.post(f"/api/models/{m['id']}/life", json={"reliability": [0.5]}).json()["points"][0]["time"]
    assert t == pytest.approx(math.log(2) / 0.002)


def test_a_life_requirement_over_the_api_gets_an_estimate(client):
    m = _make(client, "weibull", WEIBULL)
    r = client.post("/api/v1/analyse/check_life_requirement",
                    json={"model_id": m["id"], "b_life": 10, "life": 300, "confidence": 0.9})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["verdict"] == "unknown" and out["estimate_meets"] is True
    assert float(str(out["estimate"]).replace(",", "")) == pytest.approx(406.5, rel=1e-3)


def test_a_bare_list_of_numbers_is_taken_in_order(client):
    r = client.post("/api/models/from-params",
                    json={"name": "Shorthand", "distribution": "weibull", "params": [1000, 2.5]})
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["results"]["params"]] == [1000, 2.5]


def test_a_library_rate_model_keeps_its_spread_and_no_bounds_note(client):
    """A model made from a library record's rate has a spread across plants to show instead."""
    m = _make(client, "exponential", EXPONENTIAL, name="Pump (library)")
    doc = client.db.models.find_one({"_id": m["id"]})
    doc["results"]["method"] = "library"
    doc["results"]["rate_uncertainty"] = {"distribution": "gamma", "alpha": 2.0, "beta": 2000.0}
    client.db.models.replace_one({"_id": m["id"]}, doc)
    fns = client.get(f"/api/models/{m['id']}").json()["results"]["functions"]
    assert fns["life_path"].endswith("/life") and "confidence_path" not in fns
    assert "bands_note" not in fns
