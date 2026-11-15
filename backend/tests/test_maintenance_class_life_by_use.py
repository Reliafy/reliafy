"""Reliafy Maintenance: a class's lives counted by use (flight hours), not only days.

The fixture has the shape of a small UAS fleet: air vehicles with a flight-hours
counter read quarterly, a generator belt inside each (no counter of its own: it
runs whenever its air vehicle flies) and 25 / 50 FH tasks. Lives in hours come
from the counter, honestly: a failure between two readings is a range (interval
censored), a life the readings can't bound is left out and counted.

Classes that run on the calendar keep every number they had (the last tests)."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance import forecast, loop
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-uas"
START = 1100  # days ago the fleet's records start
QUARTER = 91
# Each air vehicle's flight hours a day, and its belts' lives in flight hours (the last one still fitted).
FLEET = {
    "AV-01": (0.60, [150, 170]),
    "AV-02": (0.70, [140, 190, 160]),
    "AV-03": (0.80, [175, 130]),
    "AV-04": (0.55, [165]),
    "AV-05": (0.65, [145, 185]),
    "AV-06": (0.75, [155, 135, 180]),
}


def _ago(days: float) -> str:
    return (date.today() - timedelta(days=round(days))).isoformat()


def _fleet(m: Maintenance) -> dict:
    """The fleet: {AV name: (av id, belt id, counter id)}."""
    out = {}
    for name, (per_day, lives) in FLEET.items():
        av = m.create_position(name, position_class="Air vehicle")["id"]
        belt = m.create_position("Generator belt", parent_id=av, position_class="Generator belt")["id"]
        fh = m.add_point(av, "Airframe flight hours (FH)", kind="counter", unit="hours")["id"]
        for d in range(START, -1, -QUARTER):  # quarterly readings, the last one 3 days ago at most
            m.record_reading(fh, round(per_day * (START - d), 1), on=_ago(d))
        m.fit(av, new_item={"name": f"{name} airframe"}, on=_ago(START))
        day = START
        m.fit(belt, new_item={"name": f"{name} belt 0"}, on=_ago(day))
        for n, life in enumerate(lives):
            day -= life / per_day
            if day <= 0:
                break
            m.remove(belt, on=_ago(day), reason="failure", failure_mode_text="Belt worn through")
            m.fit(belt, new_item={"name": f"{name} belt {n + 1}"}, on=_ago(day))
        m.create_task(av, "PMU 25 FH inspection", 25, "hours", outcome="on_condition")
        m.create_task(av, "PMU 50 FH inspection", 50, "hours", outcome="on_condition")
        m.create_task(belt, "Replace generator belt", 50, "hours", outcome="fixed_interval")
        out[name] = (av, belt, fh)
    return out


@pytest.fixture()
def uas():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    return m, _fleet(m), mongomock.MongoClient()["uas"]


def test_lives_by_use_come_from_the_counter_above_and_failures_between_readings_are_ranges(uas):
    m, fleet, _db = uas
    data = m.class_life_data("Generator belt", "FH")  # FH is hours
    assert data["unit"] == "hours"
    assert [c["position"]["name"] for c in data["counters"]] == sorted(FLEET)  # each belt counted on its AV's
    failed = [r for r in data["rows"] if r["status"] == "failed"]
    assert failed and all(r["c"] == 2 and r["xl"] < r["xr"] for r in failed)
    # The true life (in hours) is inside every failure's range, and the range is at most two quarters' flying.
    for r in failed:
        per_day = FLEET[r["position"] if r["position"] in FLEET else
                        next(n for n, (_, b, _) in fleet.items() if b == r["position_id"])][0]
        true = (date.fromisoformat(r["failed_on"] if r.get("failed_on") else r["to"])
                - date.fromisoformat(r["from"])).days * per_day
        assert r["xl"] - 1e-6 <= true <= r["xr"] + 1e-6
        assert r["xr"] - r["xl"] <= 2 * QUARTER * per_day + 1e-6
    # Still fitted: censored at the hours it surely flew (to the last reading), never more.
    for r in (r for r in data["rows"] if r["status"] == "still fitted"):
        assert r["c"] == 1 and "xl" not in r
    # Nothing is left out here: every fitment has readings either side.
    assert data["excluded"] == [] and "Lives in hours" in data["note"]
    # The calendar lives are as they were.
    days = m.class_life_data("Generator belt")
    assert "unit" not in days and len(days["rows"]) == len(data["rows"])
    assert all(r["c"] in (0, 1) and "xl" not in r for r in days["rows"])


def test_a_life_the_readings_cant_bound_is_left_out_and_counted(uas):
    m, fleet, _db = uas
    av, belt, fh = fleet["AV-04"]
    # A failure after the counter's last reading: no reading after it bounds its life from above.
    m.remove(belt, on=_ago(1), reason="failure", failure_mode_text="Belt worn through")
    m.fit(belt, new_item={"name": "AV-04 belt 2"}, on=_ago(1))
    # A class with no counter anywhere above it.
    lonely = m.create_position("Ground belt", position_class="Generator belt")["id"]
    m.fit(lonely, new_item={"name": "GB"}, on=_ago(50))
    data = m.class_life_data("Generator belt", "hours")
    why = {(r["position_id"], r["status"]): r["reason"] for r in data["excluded"]}
    assert why[(belt, "failed")].startswith("failed after the last hours reading")
    assert why[(lonely, "still fitted")] == "no hours counter on this position or above it"
    # And the belt fitted after it: no reading since it went in.
    assert why[(belt, "still fitted")] == "no hours reading while it was fitted"
    assert "3 fitments left out (1 of them failures)" in data["note"]
    assert all(r["fitment_id"] not in {e["fitment_id"] for e in data["excluded"]} for r in data["rows"])


def test_a_model_by_use_is_fitted_saved_on_the_class_and_proposes_for_tasks_by_use(uas):
    m, fleet, db = uas
    m.set_class_costs("Generator belt", planned_cost=200, failure_cost=3000)
    out = loop.fit_class_model(m, db, "Generator belt", "weibull", unit="hours")
    model = out["model"]
    assert model["unit"] == "hours" and out["unit"] == "hours"
    assert model["failures"] == sum(len(lives) for _, lives in FLEET.values())  # every belt failure is bounded
    saved = db.models.find_one({"_id": model["model_id"]})
    assert saved and "in hours" in saved["name"]
    alpha = next(p["value"] for p in model["params"] if p["name"] == "alpha")
    # The belts' lives in flight hours (the long-running belts still fitted pull it above the failures).
    assert 150 < alpha < 450
    in_days = loop.fit_class_model(m, mongomock.MongoClient()["other"], "Generator belt", unit="days")["model"]
    assert next(p["value"] for p in in_days["params"] if p["name"] == "alpha") > 1.2 * alpha  # not days
    loop.fit_class_model(m, db, "Generator belt", "weibull", unit="hours")  # back to hours
    # Proposals for the 50 FH replacement task, in hours; none for the 25 / 50 FH inspections (on condition).
    made = out["proposals"]
    assert len(made) == len(FLEET) and all(p["proposed"]["unit"] == "hours" for p in made)
    assert {p["position"]["name"] for p in made} == {"Generator belt"}
    assert "characteristic life" in made[0]["reason"] and " hours" in made[0]["reason"]
    assert made[0]["proposed"]["interval"] != 50
    # The pending ones are still the hours proposals.
    assert all(p["proposed"]["unit"] == "hours" for p in m.proposals("pending"))
    # A refit with no unit keeps the class's unit; the daily refit doesn't run again with nothing new.
    again = loop.fit_class_model(m, db, "Generator belt")
    assert again["model"]["unit"] == "hours"
    assert loop.refit_stale(m, db) == []
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_economics_by_use_turn_the_cost_per_hour_into_a_year_through_the_rate_or_plan(uas):
    m, fleet, db = uas
    m.set_class_costs("Generator belt", planned_cost=200, failure_cost=3000)
    loop.fit_class_model(m, db, "Generator belt", unit="hours")
    out = loop.economics(m, "Generator belt")
    assert out["unit"] == "hours" and out["positions"] == len(FLEET)
    use = {u["position"]["id"]: u for u in out["use_per_year"]}
    for name, (av, belt, _fh) in fleet.items():
        assert use[belt]["basis"] == "counter"
        assert use[belt]["per_year"] == pytest.approx(FLEET[name][0] * 365.25, rel=0.02)
    plans = {o["plan"]: o for o in out["options"]}
    assert plans["current plan"]["interval"] == "50 hours"
    assert plans["best interval"]["interval"].endswith(" hours")
    assert plans["run to failure"]["per_year"] > plans["best interval"]["per_year"]
    # A what-if in hours, and one on the calendar (each position's rate turns it into hours).
    hours = loop.economics(m, "Generator belt", interval=100)
    assert hours["options"][-1]["interval"] == "100 hours"
    months = loop.economics(m, "Generator belt", interval=6, unit="months")
    assert months["options"][-1]["interval"] == "6 months"
    with pytest.raises(Invalid):
        loop.economics(m, "Generator belt", interval=100, unit="km")
    # An operating plan on AV-01 (inherited by its belt) sets its hours a year: 2 h a day.
    av1, belt1, _ = fleet["AV-01"]
    m.set_operating_plan(av1, {"background": {"kind": "rate", "amount": 2, "per": "day"}})
    planned = {u["position"]["id"]: u for u in loop.economics(m, "Generator belt")["use_per_year"]}
    assert planned[belt1]["basis"] == "plan"
    assert planned[belt1]["per_year"] == pytest.approx(2 * 365.25, rel=0.01)


def test_the_class_forecast_runs_on_the_hours_model_through_the_counter_above(uas):
    m, fleet, db = uas
    loop.fit_class_model(m, db, "Generator belt", unit="hours")
    out = forecast.class_forecast(m, "Generator belt", "quarter", 4)
    assert out["model"]["unit"] == "hours" and out["n_forecast"] == len(FLEET)
    assert all(r["rate_basis"] == "counter" for r in out["at_risk"])
    assert out["expected"] > 0


def test_a_calendar_unit_other_than_days_is_refused(uas):
    m, _fleet_, db = uas
    with pytest.raises(Invalid):
        m.class_life_data("Generator belt", "months")
    with pytest.raises(Invalid):
        loop.fit_class_model(m, db, "Generator belt", unit="weeks")


# ---- classes on the calendar: nothing moves --------------------------------------------

def test_a_calendar_class_with_counters_fits_and_costs_exactly_as_before(uas):
    """The belt class fitted with no unit (as every call made before) is the days model:
    the same rows, the same parameters, the same proposals (none: its task is by use)
    and the same economics as asking for days outright."""
    m, _fleet_, db = uas
    m.set_class_costs("Generator belt", planned_cost=200, failure_cost=3000)
    assert m.class_life_data("Generator belt") == m.class_life_data("Generator belt", "days")
    plain = loop.fit_class_model(m, db, "Generator belt")
    assert plain["model"]["unit"] == "days" and "unit" not in plain and "failures_seen" not in plain["model"]
    assert plain["proposals"] == []  # a days model doesn't propose for a task by use
    days = loop.fit_class_model(m, db, "Generator belt", unit="days")
    assert [p["value"] for p in days["model"]["params"]] == pytest.approx([p["value"] for p in plain["model"]["params"]])
    econ = loop.economics(m, "Generator belt")
    assert "unit" not in econ and econ == loop.economics(m, "Generator belt", unit="months")


def test_the_rest_routes_take_the_unit(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_uas"])
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        client = TestClient(app)
        m = Maintenance(store, ORG, ORG)
        _fleet(m)
        m.set_class_costs("Generator belt", planned_cost=200, failure_cost=3000)
        one = client.get("/api/maintenance/classes/one", params={"position_class": "Generator belt"}).json()
        assert one["life_units"] == ["days", "hours"]
        pooled = client.get("/api/maintenance/classes/life-data",
                            params={"position_class": "Generator belt", "unit": "hours"}).json()
        assert pooled["unit"] == "hours" and pooled["rows"]
        fit = client.post("/api/maintenance/classes/fit", json={"position_class": "Generator belt", "unit": "hours"})
        assert fit.status_code == 200, fit.text
        assert fit.json()["model"]["unit"] == "hours"
        econ = client.get("/api/maintenance/classes/economics",
                          params={"position_class": "Generator belt", "interval": 100}).json()
        assert econ["unit"] == "hours" and econ["options"][-1]["interval"] == "100 hours"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
