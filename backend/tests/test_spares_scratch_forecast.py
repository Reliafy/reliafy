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
    r = api.get(f"/api/maintenance/positions/{pump['id']}/forecast-start")
    assert r.status_code == 200, r.text
    out = r.json()
    # No model, no duty: nothing made up; the notes say what to enter.
    assert out["model"] is None and out["hours_per_day"] is None and out["replace_at"] is None and out["ages"] == []
    assert out["from"]["path"] == "Pump P-1" and "/asset-register/explorer?" in out["from"]["link"]
    assert any("hours a unit runs a day" in n for n in out["notes"])
    alone = api.get(f"/api/maintenance/tasks/{task.json()['id']}/forecast-start").json()
    assert alone["from"]["kind"] == "task" and alone["task"]["name"] == "Replace the seal"
    assert api.get("/api/maintenance/positions/nope/forecast-start").status_code == 404


class _Doc:
    def __init__(self, id, name, unit):
        self.id, self.name, self.results = id, name, {"unit": unit}


def test_the_start_reads_the_model_ages_duty_and_task_below_a_position(monkeypatch):
    """A crusher with two liners: both on one saved model, each fitted with an item whose age comes
    from the calendar since it was fitted; a duty of 8 h a day; a 6-monthly liner change."""
    from datetime import datetime, timezone

    from backend.maintenance import forecast_start as fs
    from backend.maintenance.service import PROJECTORS, Maintenance
    from backend.maintenance.store import GraphStore
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime(2026, 12, 1, 8, tzinfo=timezone.utc))
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "org-start", "tester")
    m.today = lambda: "2026-12-01"
    crusher = m.create_position("Crusher C-1")["id"]
    m.set_operating_plan(crusher, {"background": {"kind": "rate", "amount": 8, "per": "day"}})
    a = m.create_position("Liner A", parent_id=crusher)["id"]
    b = m.create_position("Liner B", parent_id=crusher)["id"]
    m.fit(a, new_item={"name": "LN-1"}, on="2026-11-01")
    m.fit(b, new_item={"name": "LN-2"}, on="2026-11-21")
    for pid in (a, b):
        m.link_position_model(pid, "model", "mdl-1")
    m.create_task(a, "Change the liner", 6, "months", last_done="2026-11-01")
    docs = {"mdl-1": _Doc("mdl-1", "Liner life", "months")}
    out = fs.position_start(m, lambda kind, i: docs.get(i), crusher)
    assert out["model"] == {"id": "mdl-1", "name": "Liner life", "unit": "months"}
    assert out["units"] == 2 and len(out["ages"]) == 2
    assert sorted(round(x, 2) for x in out["ages"]) == [0.33, 0.99]
    assert out["hours_per_day"] == 8
    assert out["replace_at"] == 6 and out["task"]["name"] == "Change the liner"
    assert out["from"]["path"] == "Crusher C-1"


def test_one_call_gives_spares_hours_and_costs_from_the_same_runs():
    """Twenty units replaced at 800 h: each failure takes 6 h and costs $5,000; each planned
    replacement 2 h and $800; each spare $150. The hours and costs are those counts times the
    figures, period by period, with their own 90% ranges."""
    out = fleet_service.scratch_forecast({**WEIBULL, "units": 20, "ages": 400, "rate": 150, "periods": 12,
                                          "strategy": "age", "replace_at": 800, "failure_cost": 5000,
                                          "planned_cost": 800, "planned_hours": 2, "corrective_hours": 6,
                                          "spare_cost": 150})
    st = out["strategy"]
    hours, costs = out["views"]["hours"], out["views"]["costs"]
    fails, planned = st["total"]["failures"]["expected"], st["total"]["planned"]["expected"]
    assert hours["total"]["expected"] == pytest.approx(6 * fails + 2 * planned)
    lo, hi = hours["total"]["interval"]
    assert lo <= hours["total"]["expected"] <= hi
    assert costs["total"]["expected"] == pytest.approx(5150 * fails + 950 * planned)
    first = costs["per_period"][0]
    assert first["cost"]["expected"] == pytest.approx(first["planned"] + first["corrective"] + first["spares"])
    assert sum(r["hours"]["expected"] for r in hours["per_period"]) == pytest.approx(hours["total"]["expected"])


def test_no_figures_no_hours_or_costs():
    out = fleet_service.scratch_forecast({**EXP, "units": 3, "ages": 10, "rate": 100, "periods": 6})
    assert out["views"]["hours"] is None and out["views"]["costs"] is None
    # Run to failure: a planned replacement's hours don't count.
    rtf = fleet_service.scratch_forecast({**EXP, "units": 3, "ages": 10, "rate": 100, "periods": 6, "planned_hours": 3})
    assert rtf["views"]["hours"] is None
