"""The quick spares forecast (Decisions › Forecasts › Spares forecast; Derryn, 23 Nov 2026): a model
picked or typed, units at an age, a use rate and a replacement policy, worked out by the saved-fleet
engine and never stored; and what it takes from a position or task in the Explorer."""

import pytest

from backend.services import fleet as fleet_service
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

EXP = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.001}], "unit": "hours"}
WEIBULL = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}],
           "unit": "hours"}


def test_a_constant_rate_forecast_is_exact():
    """Ten units at 0.001 a hour, 100 h a month for 12 months, run to failure: 10 × 1,200 h / 1,000 h = 12."""
    out = fleet_service.scratch_forecast({**EXP, "units": 10, "ages": 500, "rate": 100, "periods": 12})
    assert out["status"] == "ok" and out["saved"] is False
    assert out["expected"] == pytest.approx(12.0)
    assert out["per_period"] == pytest.approx([1.0] * 12)
    assert out["per_item"][0]["count"] == 10 and out["interval_level"] == 0.9


def test_one_age_each_and_the_same_as_a_saved_fleet():
    ages = [100, 900, 1500]
    out = fleet_service.scratch_forecast({**WEIBULL, "ages": ages, "rate": 200, "periods": 6})
    assert [r["id"] for r in out["per_item"]] == [it["id"] for it in out["items"]]
    assert [it["current_use"] for it in out["items"]] == ages
    # The oldest unit expects the most failures.
    exp = [r["expected"] for r in out["per_item"]]
    assert exp[2] > exp[0]


def test_planned_replacement_and_the_spares_answer():
    out = fleet_service.scratch_forecast({**WEIBULL, "units": 20, "ages": 400, "rate": 150, "periods": 12,
                                          "strategy": "age", "replace_at": 800, "failure_cost": 5000,
                                          "planned_cost": 800, "spares": {"lead_time": 2}})
    assert out["strategy"]["kind"] == "age" and out["planned"]["expected"] > 0
    assert out["spares"]["status"] == "ok" and out["spares"]["hold"] >= 1


@pytest.mark.parametrize("body, words", [
    ({"units": 2, "ages": 10}, "Pick a saved model"),
    ({**EXP, "units": 2}, "age now"),
    ({**EXP, "units": 2, "ages": -1}, "negative"),
    ({**EXP, "units": 0, "ages": 1}, "at least 1"),
    ({**EXP, "units": 2, "ages": 1, "strategy": "age"}, "replace at"),
])
def test_refusals_say_what_to_do(body, words):
    with pytest.raises(fleet_service.FleetValidationError, match=words):
        fleet_service.scratch_forecast({"rate": 10, **body})


def test_over_rest_nothing_saved(api):  # noqa: F811
    from backend import db

    r = api.post("/api/fleet/scratch-forecast", json={**EXP, "units": 4, "ages": 0, "rate": 250, "periods": 12})
    assert r.status_code == 200, r.text
    assert r.json()["expected"] == pytest.approx(12.0)
    assert db.get_db().fleets.count_documents({"name": {"$regex": "Typed"}}) == 0
    bad = api.post("/api/fleet/scratch-forecast", json={**EXP, "units": 4, "rate": 250})
    assert bad.status_code == 422 and "age" in bad.json()["detail"]


def test_the_start_from_a_position_takes_only_what_is_recorded(api):  # noqa: F811
    pump = api.post("/api/maintenance/positions", json={"name": "Pump P-1"}).json()
    task = api.post(f"/api/maintenance/positions/{pump['id']}/tasks",
                    json={"name": "Replace the seal", "interval": 6, "unit": "months"})
    assert task.status_code == 200, task.text
    r = api.get(f"/api/maintenance/positions/{pump['id']}/spares-forecast-start", params={"task_id": task.json()["id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    # No model, no duty: nothing made up; the notes say what to enter.
    assert out["model"] is None and out["hours_per_day"] is None and out["replace_at"] is None
    assert out["task"]["name"] == "Replace the seal"
    assert any("hours a unit runs a day" in n for n in out["notes"])
    missing = api.get("/api/maintenance/positions/nope/spares-forecast-start")
    assert missing.status_code == 404
