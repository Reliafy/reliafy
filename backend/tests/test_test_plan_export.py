"""Download as Python for the Test planning calculators: the script works out
the same plan with SurPyval's test_planning, and every number it prints is
the calculator's."""

import mongomock
import pytest

from backend.tests.python_scripts import close, run

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _both(client, tmp_path, kind, body):
    url = "/api/strategy/demonstration-test" if kind == "demonstration" else f"/api/test-planning/{kind}"
    answer = client.post(url, json=body)
    assert answer.status_code == 200, answer.text
    script = client.post(f"/api/test-planning/{kind}/export.py", json=body)
    assert script.status_code == 200, script.text
    assert script.headers["content-type"].startswith("text/x-python")
    assert "requirements: surpyval==" in script.text
    return answer.json(), run(script.text, tmp_path)


# ---- Demonstration -------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"method": "attribute", "reliability": 0.9, "confidence": 0.9, "failures": 1, "mission_time": 500,
     "unit": "hours", "design_reliability": 0.97},
    {"method": "attribute", "reliability": 0.9, "confidence": 0.9, "test_multiple": 2, "shape": 1.8,
     "mission_time": 500},
    {"method": "attribute", "reliability": 0.95, "confidence": 0.9, "units": 20, "shape": 2, "failures": 0},
    {"method": "attribute", "reliability": 0.9, "confidence": 0.9, "design_reliability": 0.98,
     "producer_risk": 0.1},
])
def test_demonstration_attribute(client, tmp_path, body):
    api, out = _both(client, tmp_path, "demonstration", body)
    close(out["Units to test"]["value"], api["units"])
    close(out["Failures allowed"]["value"], api["failures"])
    close(out["Test length per unit (missions)"]["value"], api["test_multiple"])
    close(out["Reliability demonstrated"]["value"], api["demonstrated_reliability"])
    close(out["Chance a design at the target passes"]["value"], api["consumer_risk"])
    if api["pass_probability"] is not None:
        close(out["Chance the good design passes"]["value"], api["pass_probability"])
    if api["test_time_per_unit"] is not None:
        close(out["Test time per unit"]["value"], api["test_time_per_unit"])
        close(out["Total test time"]["value"], api["total_test_time"])


@pytest.mark.parametrize("body", [
    {"method": "mtbf", "mtbf": 1000, "confidence": 0.9, "failures": 2, "units": 5, "design_mtbf": 3000},
    {"method": "mtbf", "mtbf": 1000, "confidence": 0.8, "failures": 2, "failure_terminated": True},
    {"method": "mtbf", "mtbf": 1000, "confidence": 0.9, "design_mtbf": 3000, "producer_risk": 0.2},
])
def test_demonstration_mtbf(client, tmp_path, body):
    api, out = _both(client, tmp_path, "demonstration", body)
    close(out["Total test time"]["value"], api["total_test_time"])
    close(out["Failures allowed"]["value"], api["failures"])
    close(out["Chance a design at the target passes"]["value"], api["consumer_risk"])
    if api["test_time_per_unit"] is not None:
        close(out["Test time per unit"]["value"], api["test_time_per_unit"])
    if api["pass_probability"] is not None:
        close(out["Chance the good design passes"]["value"], api["pass_probability"])


# ---- Sequential ----------------------------------------------------------------------------

def test_sequential_mtbf(client, tmp_path):
    body = {"method": "mtbf", "mtbf": 500, "good_mtbf": 1000, "confidence": 0.9, "producer_risk": 0.1,
            "unit": "hours", "failures_seen": 2, "time_seen": 1500}
    api, out = _both(client, tmp_path, "sequential", body)
    close(out["Chance a design at the target passes"]["value"], api["consumer_risk"])
    close(out["Chance a good design fails"]["value"], api["producer_risk"])
    close(out["Average test time, good design"]["value"], api["expected"]["at_good"])
    close(out["Average test time, design at the target"]["value"], api["expected"]["at_target"])
    close(out["Fixed-length test time"]["value"], api["expected"]["fixed_length"])
    close(out["Fixed-length test failures"]["value"], api["expected"]["fixed_length_failures"])
    close(out["Longest it runs"]["value"], api["max_time"])
    close(out["Most failures"]["value"], api["max_failures"])
    assert f"Decision: {api['decision']['verdict']}" in out["_stdout"]


def test_sequential_attribute(client, tmp_path):
    body = {"method": "attribute", "reliability": 0.9, "good_reliability": 0.97, "confidence": 0.9,
            "producer_risk": 0.1, "failures_seen": 1, "units_seen": 10}
    api, out = _both(client, tmp_path, "sequential", body)
    close(out["Chance a design at the target passes"]["value"], api["consumer_risk"])
    close(out["Chance a good design fails"]["value"], api["producer_risk"])
    close(out["Average units tested, good design"]["value"], api["expected"]["at_good"])
    close(out["Average units tested, design at the target"]["value"], api["expected"]["at_target"])
    close(out["Fixed-length test units"]["value"], api["expected"]["fixed_length"])
    close(out["Most units"]["value"], api["max_units"])
    close(out["Most failures"]["value"], api["max_failures"])
    assert f"Decision: {api['decision']['verdict']}" in out["_stdout"]


# ---- Life ------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"solve_for": "precision", "params": {"alpha": 1000, "beta": 2}, "units": 20, "test_end": "time",
     "censor_time": 800, "unit": "hours"},
    {"solve_for": "precision", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}],
     "units": 20, "test_end": "failures", "failure_fraction": 0.5, "quantity": "mean"},
    {"solve_for": "units", "distribution": "lognormal", "params": {"mu": 7, "sigma": 0.8}, "precision": 50,
     "test_end": "time", "censor_time": 1500, "b_life": 5, "confidence": 0.95},
    {"solve_for": "units", "params": {"alpha": 1000, "beta": 2}, "precision": 60, "test_end": "all"},
    {"solve_for": "length", "params": {"alpha": 1000, "beta": 2}, "units": 30, "precision": 60,
     "test_end": "time"},
    {"solve_for": "length", "params": {"alpha": 1000, "beta": 2}, "units": 30, "precision": 60,
     "test_end": "failures"},
])
def test_life(client, tmp_path, body):
    api, out = _both(client, tmp_path, "life", body)
    close(out["Units on test"]["value"], api["n"])
    close(out["Test stops at"]["value"], api["censor_time"])
    close(out["Test stops at failure"]["value"], api["failures"])
    close(out["Expected failures"]["value"], api["expected_failures"])
    close(out[f"Estimate ({api['label'] if api['quantity'] != 'mean' else 'the mean life'})"]["value"],
          api["estimate"])
    close(out["Precision factor"]["value"], api["precision"])
    close(out["Interval from"]["value"], api["interval"][0])
    close(out["Interval to"]["value"], api["interval"][1])


# ---- Accelerated -----------------------------------------------------------------------------

ARRHENIUS = {"a": 6694, "b": 2e-5}


@pytest.mark.parametrize("body", [
    {"life_params": ARRHENIUS, "shape": 2, "use_stress": 323, "high_stress": 393, "units": 40, "censor_time": 1000,
     "unit": "hours", "stress_unit": "K"},
    {"life_params": ARRHENIUS, "shape": 2, "use_stress": 323, "high_stress": 393, "units": 40, "censor_time": 1000,
     "levels": 3, "allocation": [2, 1, 1]},
    {"mode": "check", "life_params": ARRHENIUS, "shape": 2, "use_stress": 323, "stresses": [353, 373, 393],
     "units_at": [20, 10, 10], "censor_time": 1000},
])
def test_accelerated(client, tmp_path, body):
    api, out = _both(client, tmp_path, "accelerated", body)
    for i, row in enumerate(api["rows"], start=1):
        close(out[f"Stress {i}"]["value"], row["stress"])
        close(out[f"Units at stress {i}"]["value"], row["units"])
        close(out[f"Expected failures at stress {i}"]["value"], row["expected_failures"])
    close(out["Expected failures in all"]["value"], api["total_expected_failures"])
    close(out[f"Estimate (B{api['b_life']:g} at the use stress)"]["value"], api["estimate"])
    close(out["Precision factor"]["value"], api["precision"])
    close(out["Interval from"]["value"], api["interval"][0])
    close(out["Interval to"]["value"], api["interval"][1])
    for other in api["alternatives"]:
        close(out[f"Precision factor with {other['levels']} stress levels"]["value"], other["precision"])


# ---- Comparison ------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"kind": "logrank", "solve_for": "sample_size", "hazard_ratio": 0.6, "event_probability": 0.5, "power": 0.8,
     "confidence": 0.9},
    {"kind": "logrank", "solve_for": "power", "hazard_ratio": 0.6, "event_probability": 0.5, "units_per_group": 80,
     "allocation_ratio": 2, "confidence": 0.9, "one_sided": True},
])
def test_logrank(client, tmp_path, body):
    api, out = _both(client, tmp_path, "comparison", body)
    close(out["Failures needed in all"]["value"], api["events"])
    close(out["New units"]["value"], api["units_new"])
    close(out["Old units"]["value"], api["units_old"])
    close(out["Power"]["value"], api["power"])


@pytest.mark.parametrize("body, key, label", [
    ({"kind": "rate_ratio", "solve_for": "exposure", "failures_before": 12, "exposure_before": 10000,
      "rate_ratio": 0.5, "power": 0.8, "confidence": 0.9, "unit": "hours"},
     "exposure_after", "Operating time needed after the change"),
    ({"kind": "rate_ratio", "solve_for": "detectable", "failures_before": 12, "exposure_before": 10000,
      "exposure_after": 8000, "power": 0.8}, "detectable_ratio", "Smallest detectable rate ratio"),
    ({"kind": "rate_ratio", "solve_for": "power", "failures_before": 12, "exposure_before": 10000,
      "exposure_after": 8000, "rate_ratio": 0.5}, "power", "Power"),
])
def test_rate_ratio(client, tmp_path, body, key, label):
    api, out = _both(client, tmp_path, "comparison", body)
    close(out["Failure rate before"]["value"], api["rate_before"])
    close(out[label]["value"], api[key])


# ---- Refusals --------------------------------------------------------------------------------

def test_bad_inputs_are_refused_in_the_calculators_words(client):
    body = {"method": "mtbf", "mtbf": 1000, "good_mtbf": 1100}
    calc = client.post("/api/test-planning/sequential", json=body)
    export = client.post("/api/test-planning/sequential/export.py", json=body)
    assert calc.status_code == export.status_code == 422
    assert export.json()["detail"] == calc.json()["detail"]
    assert client.post("/api/test-planning/life/export.py", json={"nonsense": 1}).status_code == 422
    assert client.post("/api/test-planning/nope/export.py", json={}).status_code == 404
    bad = client.post("/api/test-planning/demonstration/export.py", json={"method": "attribute"})
    assert bad.status_code == 422
