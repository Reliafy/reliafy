"""Reliafy Maintenance: a position class's failure forecast from the register
(#407), on the fleet forecast's renewals engine: expected failures per period
with P10–P90, positions at risk, spares demand against stock, and a budget."""

import math
from datetime import date, timedelta

import mongomock
import pytest
from scipy.stats import poisson

from backend.maintenance import forecast
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound, class_id
from backend.maintenance.store import GraphStore

ORG = "user-f"
RATE = 0.01  # failures a day: a mean life of 100 days


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _model(m, name, distribution="exponential", params=None, unit="days", failures=12):
    """The class's fitted model, as fit_class_model records it."""
    m._emit("class.model_fitted", {
        "id": class_id(m.org, name), "name": name, "model_id": "model-1", "distribution": distribution,
        "params": params or [{"name": "failure_rate", "value": RATE}], "extras": None, "unit": unit,
        "fitted_on": m.today(), "failures": failures, "suspensions": 3})


def _pumps(m, n=3, name="Pump", fitted_days=200):
    out = []
    for i in range(n):
        pid = m.create_position(f"{name} {i + 1}", position_class=name)["id"]
        m.fit(pid, new_item={"name": f"{name} {i + 1} item"}, on=_ago(fitted_days + 10 * i))
        out.append(pid)
    return out


def test_renewals_are_counted_and_the_range_matches_a_poisson_process(m):
    # Exponential lives: each position's failures, replacements included, are a
    # Poisson process at RATE, so the class's count over the horizon is Poisson.
    _pumps(m)
    _model(m, "Pump")
    out = forecast.class_forecast(m, "pump")  # any case
    assert out["position_class"] == "Pump" and out["status"] == "ok"
    mean = 3 * RATE * 12 * 30.4375
    assert out["expected"] == pytest.approx(mean, rel=0.04)
    assert out["expected"] > 3  # more failures than positions: replacements fail again
    lo, hi = poisson.ppf(0.1, mean), poisson.ppf(0.9, mean)
    assert abs(out["interval"][0] - lo) <= 1 and abs(out["interval"][1] - hi) <= 1
    assert out["headline"] == f"≈ {forecast._num(out['expected'])} failures in the next 12 months " \
                              f"(likely {out['interval'][0]:g}–{out['interval'][1]:g})"
    rows = out["per_period"]
    assert len(rows) == 12 and rows[0]["start"] == m.today()
    assert sum(r["expected"] for r in rows) == pytest.approx(out["expected"])
    month = 3 * RATE * 30.4375
    assert rows[5]["expected"] == pytest.approx(month, rel=0.15)
    assert rows[5]["p10"] == poisson.ppf(0.1, month) and rows[5]["p90"] == poisson.ppf(0.9, month)
    assert out["sims"] >= 200 and out["n_forecast"] == 3 and out["not_forecast"] == []


def test_positions_are_ranked_by_their_chance_of_failing_next_period(m):
    pids = _pumps(m, fitted_days=100)
    m.remove(pids[0], on=_ago(50), reason="planned")
    m.fit(pids[0], new_item={"name": "Young pump"}, on=_ago(5))
    alpha, beta = 400.0, 3.0
    _model(m, "Pump", "weibull", [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}])
    out = forecast.class_forecast(m, "Pump", "quarter", 4)
    risk = out["at_risk"]
    assert [r["prob_next_period"] for r in risk] == sorted((r["prob_next_period"] for r in risk), reverse=True)
    assert risk[-1]["item"]["name"] == "Young pump"  # wear-out: the youngest is least at risk

    def cdf(t):
        return 1 - math.exp(-((t / alpha) ** beta))

    top = risk[0]
    a, r = top["age"], 91.3125
    assert top["rate_per_period"] == pytest.approx(r, abs=1e-3) and top["rate_basis"] == "calendar"
    assert top["prob_next_period"] == pytest.approx((cdf(a + r) - cdf(a)) / (1 - cdf(a)))
    assert out["period"] == "quarter" and len(out["per_period"]) == 4


def test_a_model_by_use_goes_by_the_counter_and_says_when_it_has_no_rate(m):
    a, b, c = (m.create_position(f"Engine {x}", position_class="Engine")["id"] for x in "ABC")
    m.create_position("Engine D", position_class="Engine")  # nothing fitted
    for pid in (a, b, c):
        m.fit(pid, new_item={"name": f"Engine in {pid[:4]}"}, on=_ago(100))
    hours = m.add_point(a, "Run hours", kind="counter", unit="hours")["id"]
    for day, value in ((100, 1000), (50, 1500), (10, 1900)):
        m.record_reading(hours, value, on=_ago(day))
    once = m.add_point(c, "Run hours", kind="counter", unit="hours")["id"]
    m.record_reading(once, 50, on=_ago(3))
    _model(m, "Engine", "weibull", [{"name": "alpha", "value": 5000.0}, {"name": "beta", "value": 2.0}],
           unit="hours")
    out = forecast.class_forecast(m, "Engine")
    assert out["n_positions"] == 4 and out["n_forecast"] == 1
    row = out["at_risk"][0]
    # 900 hours read since it went in, and 10 days at 10 hours a day since the last reading.
    assert row["position"]["id"] == a and row["rate_basis"] == "counter"
    assert row["age"] == pytest.approx(1000) and row["rate_per_period"] == pytest.approx(304.375)
    assert row["counter"]["reading"] == 1900
    why = {s["position"]["name"]: s["reason"] for s in out["not_forecast"]}
    assert why["Engine B"] == "no hours counter on this position"
    assert "two readings" in why["Engine C"]
    assert why["Engine D"] == "nothing fitted"
    assert any("usage rate" in n for n in out["notes"])
    assert out["expected"] > 0  # the one with a rate is still forecast


def test_nothing_to_forecast_says_so_rather_than_zero_failures(m):
    m.create_position("Spare pump", position_class="Pump")
    _model(m, "Pump")
    out = forecast.class_forecast(m, "Pump")
    assert out["n_forecast"] == 0 and out["expected"] == 0
    assert out["headline"] == "No position of Pump has an item fitted that can be forecast."
    assert out["not_forecast"][0]["reason"] == "nothing fitted"


def test_spares_demand_is_failures_times_quantity_per_job_against_stock(m):
    pids = _pumps(m)
    store = m.create_location("Store")["id"]
    whole = m.create_part("P-1", "Pump")["id"]
    seal = m.create_part("S-3", "Seal kit")["id"]
    oil = m.create_part("O-1", "Oil")["id"]  # neither the replacement nor critical: not tallied
    m.adjust_stock(whole, store, 4)
    for pid in pids:
        m.add_position_part(pid, whole, "replacement", quantity=2)
        m.add_position_part(pid, oil, "consumable", quantity=5)
    m.add_position_part(pids[0], seal, "component", quantity=3, critical=True)
    _model(m, "Pump")
    out = forecast.class_forecast(m, "Pump")
    spares = {s["part"]["part_number"]: s for s in out["spares"]}
    assert set(spares) == {"P-1", "S-3"}
    p1, s3 = spares["P-1"], spares["S-3"]
    assert p1["expected"] == pytest.approx(2 * out["expected"])
    for k in range(12):
        assert p1["per_period"][k]["mean"] == pytest.approx(2 * out["per_period"][k]["expected"])
    first = next(r for r in out["at_risk"] if r["position"]["id"] == pids[0])
    assert s3["expected"] == pytest.approx(3 * first["expected_failures"])
    assert s3["critical"] and s3["min_on_hand"] == 3 and s3["usable_on_hand"] == 0
    assert p1["usable_on_hand"] == 4 and p1["stock"][0]["quantity"] == 4 and p1["positions"] == 3
    covered = [c["prob_covered"] for c in p1["cumulative"]]
    assert covered == sorted(covered, reverse=True) and p1["cumulative"][-1]["mean"] == pytest.approx(p1["expected"])
    assert p1["short"]  # ≈ 22 over the year against 4
    assert p1["cumulative"][p1["covered_periods"]]["p90"] > 4 >= p1["cumulative"][p1["covered_periods"] - 1]["p90"]
    assert all(c["p50"] <= c["p90"] <= c["p95"] for c in p1["cumulative"])


def test_the_budget_prices_failures_and_planned_replacements(m):
    pids = _pumps(m)
    # Due in about a month, then every 6 months: twice in the year.
    m.create_task(pids[0], "Replace pump", 6, "months", outcome="fixed_interval", last_done=_ago(150))
    m.create_task(pids[1], "Inspect", 1, "months", outcome="on_condition")  # not a replacement
    _model(m, "Pump")
    assert forecast.class_forecast(m, "Pump")["budget"] is None  # no costs yet
    m.set_class_costs("Pump", planned_cost=400, failure_cost=4000)
    out = forecast.class_forecast(m, "Pump")
    budget = out["budget"]
    assert budget["basis"] == "failure_cost" and budget["cost_per_failure"] == 4000
    assert budget["failures"] == pytest.approx(4000 * out["expected"])
    assert budget["planned_count"] == 2 and budget["planned"] == 800
    assert budget["expected"] == pytest.approx(budget["failures"] + 800)
    assert budget["interval"] == [4000 * out["interval"][0] + 800, 4000 * out["interval"][1] + 800]
    assert sum(r["planned_count"] for r in budget["per_period"]) == 2
    assert any("Planned replacements" in n for n in out["notes"])


def test_the_class_replacement_cost_prices_failures_when_no_failure_cost_is_set(m):
    _pumps(m)
    _model(m, "Pump")
    m.set_class_replacement_cost("Pump", {"amount": 1500, "currency": "AUD"})
    budget = forecast.class_forecast(m, "Pump")["budget"]
    assert budget["basis"] == "replacement_cost" and budget["currency"] == "AUD"
    assert budget["planned_cost"] is None and budget["planned_count"] == 0


def test_it_follows_the_register_and_is_kept_until_the_next_change(m):
    pids = _pumps(m)
    _model(m, "Pump")
    first = forecast.class_forecast(m, "Pump")
    assert forecast.class_forecast(m, "Pump") == first
    m.remove(pids[0], reason="failure", failure_mode_text="Seized")
    after = forecast.class_forecast(m, "Pump")
    assert after["n_forecast"] == 2 and after["expected"] < first["expected"]


def test_bad_requests_are_refused(m):
    _pumps(m)
    with pytest.raises(Invalid, match="Fit a life model"):
        forecast.class_forecast(m, "Pump")
    _model(m, "Pump")
    with pytest.raises(Invalid):
        forecast.class_forecast(m, "Pump", "fortnight")
    with pytest.raises(Invalid):
        forecast.class_forecast(m, "Pump", "year", 11)  # more than 10 years
    with pytest.raises(Invalid):
        forecast.class_forecast(m, "Pump", "month", 0)
    with pytest.raises(NotFound):
        forecast.class_forecast(m, "Turbine")
    m._emit("class.model_fitted", {"id": class_id(m.org, "Pump"), "name": "Pump", "model_id": "x",
                                   "distribution": "weibull", "params": [{"name": "alpha", "value": 1.0},
                                                                         {"name": "beta", "value": 1.0}],
                                   "extras": {"p": 0.5}, "unit": "days", "fitted_on": m.today(),
                                   "failures": 5, "suspensions": 0})
    with pytest.raises(Invalid, match="limited-failure"):
        forecast.class_forecast(m, "Pump")


def test_the_daily_digest_flags_critical_spares_the_forecast_needs_next_month(monkeypatch):
    from backend import config
    from backend.maintenance import daily
    from backend.services import email as email_service

    sent = []
    monkeypatch.setattr(email_service, "send", lambda to, subject, body, **k: sent.append(body))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"me@example.org"})
    db = mongomock.MongoClient()["daily_forecast"]
    db.users.insert_one({"_id": ORG, "email": "me@example.org", "email_verified": True})
    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, ORG)
    pids = _pumps(m)
    part = m.create_part("P-1", "Pump")["id"]
    for pid in pids:
        m.add_position_part(pid, part, "replacement", critical=True, min_on_hand=0)
    m.create_task(pids[0], "Grease", 1, "weeks")
    _model(m, "Pump")
    flagged = forecast.short_next_month(m)
    assert [f["part"]["part_number"] for f in flagged] == ["P-1"]
    assert flagged[0]["expected"] == pytest.approx(3 * RATE * 30.4375, rel=0.2)
    assert daily.run(db, store)["emails"] == 1
    assert "the failure forecast needs more of next month" in sent[0] and "P-1 Pump for Pump: ≈ 0.9" in sent[0]
    m.adjust_stock(part, m.create_location("Store")["id"], 5)
    assert forecast.short_next_month(m) == []


def test_the_rest_route(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_forecast"])
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
        _pumps(m, name="Pool pump")
        url = "/api/maintenance/classes/forecast"
        assert client.get(url, params={"position_class": "Pool pump"}).status_code == 422  # no model yet
        _model(m, "Pool pump")
        res = client.get(url, params={"position_class": "pool pump", "period": "quarter", "periods": 4})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["position_class"] == "Pool pump" and body["period"] == "quarter" and len(body["per_period"]) == 4
        assert client.get(url, params={"position_class": "Pool pump", "period": "decade"}).status_code == 422
        assert client.get(url, params={"position_class": "Nope"}).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
