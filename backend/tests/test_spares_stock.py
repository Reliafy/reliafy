"""Spares stock levels (#31): hold N for a service level over the lead time (plus
the review period), the reorder point, the risk at a given stock and a repairable
part's pool, read off a forecast's own demand distribution, for a position
class's spares (Maintenance) and a fleet's replacement part."""

import math

import mongomock
import numpy as np
import pytest
import surpyval
from scipy.stats import poisson

from backend.maintenance import forecast
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import fleet as fleet_service
from backend.services import spares
from backend.tests.test_maintenance_forecast import RATE, _model, _pumps
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture

ORG = "user-s"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _class_with_part(m, n=3, stock=1, lead=None, per_job=1, **part):
    """n pumps on exponential lives (a constant hazard: each position's failures,
    replacements included, are a Poisson process at RATE a day), one replacement
    part with ``stock`` in the store."""
    pids = _pumps(m, n)
    pid = m.create_part("P-1", "Pump", unit_cost=900)["id"]
    if stock:
        m.adjust_stock(pid, m.create_location("Store")["id"], stock)
    for p in pids:
        m.add_position_part(p, pid, "replacement", quantity=per_job)
    if lead is not None or part:
        m.update_part(pid, lead_time_days=lead, **part)
    _model(m, "Pump")
    return pid


def _stocking(m, **kwargs):
    return forecast.class_forecast(m, "Pump", **kwargs)["spares"][0]["stocking"]


# ---- the distribution --------------------------------------------------------------------

def test_quantiles_are_values_the_demand_takes():
    d = spares.Demand.from_samples([0, 0, 1, 1, 1, 2, 2, 3, 5, 9])
    assert d.quantile(0.5) == 1 and d.quantile(0.7) == 2 and d.quantile(0.9) == 5 and d.quantile(0.95) == 9
    assert d.quantile(0.5) == np.quantile([0, 0, 1, 1, 1, 2, 2, 3, 5, 9], 0.5, method="inverted_cdf")
    assert d.prob_short(2) == pytest.approx(0.3) and d.prob_short(1.5) == pytest.approx(0.5)
    assert d.expected_short(3) == pytest.approx((2 + 6) / 10) and d.mean == pytest.approx(2.4)
    exact = spares.Demand.from_pmf(spares.poisson_pmf(1.8))
    for level in (0.5, 0.9, 0.95, 0.99, 0.999):
        assert exact.quantile(level) == poisson.ppf(level, 1.8)
    assert exact.prob_short(2) == pytest.approx(poisson.sf(2, 1.8))
    assert spares.Demand.from_pmf(spares.poisson_pmf(1.8), per=2).quantile(0.95) == 2 * poisson.ppf(0.95, 1.8)
    curve = exact.curve()
    assert curve[0] == [0.0, pytest.approx(1 - math.exp(-1.8), abs=1e-6)] and curve[-1][1] < 0.001


def test_a_poisson_binomial_count_is_exact():
    p = [0.1, 0.5, 0.9]
    pmf = spares.bernoulli_sum_pmfs([p])[0]
    want = [0.9 * 0.5 * 0.1, 0.1 * 0.5 * 0.1 + 0.9 * 0.5 * 0.1 + 0.9 * 0.5 * 0.9,
            0.1 * 0.5 * 0.1 + 0.1 * 0.5 * 0.9 + 0.9 * 0.5 * 0.9, 0.1 * 0.5 * 0.9]
    assert pmf[:4] == pytest.approx(want) and pmf.sum() == pytest.approx(1)


def test_service_levels_and_durations_are_checked():
    assert spares.service_level(95) == 0.95 and spares.service_level("0.99") == 0.99
    assert spares.service_level(None) is None
    for bad in (0.2, 1, 101, "x"):
        with pytest.raises(spares.SparesError):
            spares.service_level(bad)
    with pytest.raises(spares.SparesError):
        spares.duration(-1, "lead time", 10)


# ---- a position class's spares ---------------------------------------------------------

def test_hold_matches_a_hand_computed_poisson_case(m):
    # Three positions at RATE a day: demand over a 60-day lead time is Poisson(1.8).
    _class_with_part(m, lead=60)
    st = _stocking(m)
    mu = 3 * RATE * 60
    assert st["lead_time_days"] == 60 and st["lead_time_basis"] == "part" and st["service_level"] == 0.95
    # P(D <= 3) = 0.891, P(D <= 4) = 0.964: hold 4 for 95%.
    assert st["hold"] == poisson.ppf(0.95, mu) == 4 and st["reorder_at"] == 4  # no review: one for one
    assert st["expected_demand"] == pytest.approx(mu, rel=0.05)
    assert st["risk_at_stock"] == pytest.approx(poisson.sf(1, mu), abs=0.03)
    assert st["expected_short"] == pytest.approx(sum((k - 1) * poisson.pmf(k, mu) for k in range(2, 40)), abs=0.06)
    assert st["to_order"] == 3 and st["below_reorder"]
    assert st["hold_cost"] == 3600 and st["to_order_cost"] == 2700
    assert st["summary"].startswith("Hold 4: a 95% chance of no stock-out over the lead time (60 days).")
    assert "one for one" in st["summary"] and ("53%" in st["summary"] or "54%" in st["summary"])
    # The risk curve reads any stock: the same chance at 1 as risk_at_stock.
    assert dict((s, p) for s, p in st["risk_curve"])[1.0] == pytest.approx(st["risk_at_stock"])
    # Constant hazard: every period's window needs the same.
    assert {row["hold"] for row in st["per_period"]} <= {3.0, 4.0, 5.0} and len(st["per_period"]) == 12
    assert st["per_period"][0]["start"] == m.today()


def test_more_service_needs_more_stock(m):
    _class_with_part(m, lead=60)
    holds = [_stocking(m, service_level=sl)["hold"] for sl in (0.5, 0.8, 0.9, 0.95, 0.99, 0.999)]
    assert holds == sorted(holds) and holds[0] < holds[-1]
    risks = [r for _s, r in _stocking(m)["risk_curve"]]
    assert risks == sorted(risks, reverse=True)
    st = _stocking(m, service_level=98)  # a percentage
    assert st["service_level"] == 0.98 and st["service_level_basis"] == "request"
    assert st["hold"] == poisson.ppf(0.98, 1.8) == 5  # P(D <= 4) = 0.964, P(D <= 5) = 0.990


def test_a_longer_lead_time_or_review_needs_more(m):
    _class_with_part(m, lead=60)
    by_lead = [_stocking(m, lead_time_days=d) for d in (10, 30, 60, 120, 240)]
    assert [s["hold"] for s in by_lead] == sorted(s["hold"] for s in by_lead)
    for d, s in zip((10, 30, 60, 120, 240), by_lead):
        assert s["expected_demand"] == pytest.approx(3 * RATE * d, rel=0.08)
        assert s["lead_time_basis"] == "request"
    # The review period adds to the window hold covers; reorder at covers the lead time alone.
    both = _stocking(m, lead_time_days=30, review_days=30)
    assert both["window_days"] == 60 and both["hold"] == by_lead[2]["hold"]
    assert both["reorder_at"] == by_lead[1]["hold"] < both["hold"]
    assert "Reorder when usable stock falls to" in both["summary"]
    assert "lead time and review period (60 days)" in both["summary"]


def test_parts_per_job_scale_the_stock(m):
    _class_with_part(m, lead=60, per_job=2)
    st = _stocking(m)
    assert st["hold"] == 2 * poisson.ppf(0.95, 1.8) and st["hold"] % 2 == 0


def test_a_lead_time_left_unset_is_assumed_and_said(m):
    _class_with_part(m)
    st = _stocking(m)
    assert st["lead_time_days"] == forecast.DEFAULT_LEAD_DAYS and st["lead_time_basis"] == "assumed"
    assert "No lead time is set for this part: 30 days assumed." in st["summary"]


def test_one_parts_lead_time_leaves_the_others_as_they_were(m):
    # The simulation keeps each failure's time and draws each position's lives from
    # its own stream: a longer horizon adds failures after, never moves them.
    pid = _class_with_part(m, lead=60)
    seal = m.create_part("S-1", "Seal")["id"]
    for pos in m.s.nodes(m.org, "Position"):
        m.add_position_part(pos["id"], seal, "component", critical=True)
    m.update_part(seal, lead_time_days=30)
    before = forecast.class_forecast(m, "Pump")
    m.update_part(seal, lead_time_days=400)
    after = forecast.class_forecast(m, "Pump")
    pick = lambda fc: next(s["stocking"] for s in fc["spares"] if s["part"]["id"] == pid)  # noqa: E731
    assert pick(before) == pick(after)
    assert before["expected"] == after["expected"]  # the failure forecast itself doesn't move


def test_a_repairable_pool_covers_the_turnaround(m):
    _class_with_part(m, lead=60, repairable=True, turnaround_days=20)
    st = _stocking(m)
    mu = 3 * RATE * 20
    assert st["repairable"] and st["turnaround_days"] == 20 and st["window_days"] == 20
    assert st["hold"] == poisson.ppf(0.95, mu) and st["reorder_at"] is None
    assert st["summary"].startswith("Keep a pool of 2: a 95% chance of no shortage over the repair turnaround "
                                    "(20 days)") and "one site" in st["summary"]
    # Repairable without a turnaround: bought like any other part.
    m.update_part(m.s.nodes(m.org, "Part")[0]["id"], turnaround_days=None)
    assert not _stocking(m)["repairable"] and _stocking(m)["window_days"] == 60


def test_part_settings_are_checked_and_shown(m):
    pid = _class_with_part(m, lead=45, service_level=99)
    part = m.part(pid)
    assert part["lead_time_days"] == 45 and part["service_level"] == 0.99 and part["repairable"] is None
    assert _stocking(m)["service_level_basis"] == "part"
    with pytest.raises(Invalid, match="service level"):
        m.update_part(pid, service_level=0.3)
    with pytest.raises(Invalid, match="lead time"):
        m.update_part(pid, lead_time_days=-2)
    m.update_part(pid, lead_time_days=None)  # cleared
    assert m.part(pid)["lead_time_days"] is None


def test_bad_stocking_requests_are_refused(m):
    _class_with_part(m)
    with pytest.raises(Invalid):
        forecast.class_forecast(m, "Pump", service_level=0.1)
    with pytest.raises(Invalid):
        forecast.class_forecast(m, "Pump", lead_time_days=5000)


def test_the_plan_and_the_brief_forms(m):
    _class_with_part(m, lead=60)
    fc = forecast.class_forecast(m, "Pump", "quarter", 4)
    plan = forecast.spares_plan(fc)
    part = plan["parts"][0]
    assert plan["position_class"] == "Pump" and plan["period"] == "quarter"
    assert part["hold"] == 4 and len(part["per_period"]) == 4 and part["risk_curve"]
    assert part["stock_by_location"][0]["quantity"] == 1 and part["stock"] == 1
    assert len(part["demand_per_period"]) == 4
    assert "single site" in plan["stocking"]["note"] and plan["stocking"]["sims"] >= 500
    brief = forecast.without_plans(fc)["spares"][0]["stocking"]
    assert "per_period" not in brief and "risk_curve" not in brief and brief["hold"] == 4


def test_the_digest_flags_stock_below_the_reorder_point(monkeypatch):
    from backend import config
    from backend.maintenance import daily
    from backend.services import email as email_service

    sent = []
    monkeypatch.setattr(email_service, "send", lambda to, subject, body, **k: sent.append(body))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"me@example.org"})
    db = mongomock.MongoClient()["daily_spares"]
    db.users.insert_one({"_id": ORG, "email": "me@example.org", "email_verified": True})
    store = GraphStore(":memory:", PROJECTORS)
    m = Maintenance(store, ORG)
    pid = _class_with_part(m)  # no lead time of its own: assumed, so not flagged
    assert forecast.digest_spares(m)[1] == []
    m.update_part(pid, lead_time_days=60)
    below = forecast.digest_spares(m)[1]
    assert [b["part"]["part_number"] for b in below] == ["P-1"] and below[0]["reorder_at"] == 4
    m.create_task(m.s.nodes(m.org, "Position")[0]["id"], "Grease", 1, "weeks")
    assert daily.run(db, store)["emails"] == 1
    assert "Spares below the reorder point their lead time needs:" in sent[0]
    assert "P-1 Pump for Pump: 1 usable, reorder at 4, hold 4 (95% service level)" in sent[0]


def test_the_rest_routes(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_spares"])
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        client = TestClient(app)
        pid = _class_with_part(Maintenance(store, ORG, ORG))
        res = client.patch(f"/api/maintenance/parts/{pid}", json={"lead_time_days": 60, "repairable": False})
        assert res.status_code == 200 and res.json()["lead_time_days"] == 60
        assert client.patch(f"/api/maintenance/parts/{pid}", json={"service_level": 2}).status_code == 422
        url = "/api/maintenance/classes/forecast"
        res = client.get(url, params={"position_class": "Pump", "service_level": 0.99, "review_days": 30})
        assert res.status_code == 200, res.text
        st = res.json()["spares"][0]["stocking"]
        assert st["service_level"] == 0.99 and st["window_days"] == 90 and st["per_period"]
        assert client.get(url, params={"position_class": "Pump", "service_level": 0.2}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---- a fleet's replacement part --------------------------------------------------------

def _exponential(rate=RATE):
    return surpyval.Exponential.from_params([rate])


def test_a_renewals_fleet_matches_poisson():
    # Exponential lives with renewals: 4 items using 30 a month at RATE per unit of
    # use: demand over a 2-month lead time is Poisson(4 × 30 × 2 × RATE) = 2.4.
    ages, rates = np.array([10.0, 50, 80, 200]), np.full(4, 30.0)
    out = fleet_service.spares_answer({"lead_time": 2, "stock": 2, "unit_cost": 100}, "renewals", _exponential(),
                                      ages, rates, 12, "months")
    mu = 2.4
    assert out["status"] == "ok" and out["hold"] == poisson.ppf(0.95, mu) and out["reorder_at"] == out["hold"]
    assert out["risk_at_stock"] == pytest.approx(poisson.sf(2, mu), abs=0.03)
    assert out["hold_cost"] == 100 * out["hold"] and len(out["per_period"]) == 12
    assert "lead time (2 months)" in out["summary"] and "simulated" in out["basis"]
    one = fleet_service.spares_answer({"lead_time": 1, "per_failure": 2}, "renewals", _exponential(), ages, rates,
                                      3, "months")
    assert one["hold"] == 2 * poisson.ppf(0.95, 1.2) and "lead time (1 month)" in one["summary"]


def test_a_first_failures_fleet_is_exact():
    # Each item fails at most once: the count over the lead time is Poisson-binomial.
    dist = surpyval.Weibull.from_params([100.0, 2.0])
    ages, rates = np.array([20.0, 60, 90]), np.array([10.0, 10, 10])
    out = fleet_service.spares_answer({"lead_time": 3, "service_level": 0.9}, "single", dist, ages, rates, 6,
                                      "weeks")
    p = [(dist.ff(a + 30) - dist.ff(a)) / dist.sf(a) for a in ages]
    pmf = spares.bernoulli_sum_pmfs([p])[0]
    want = int(np.searchsorted(np.cumsum(pmf), 0.9 - 1e-9))
    assert out["hold"] == want and "Exact" in out["basis"]
    assert out["expected_demand"] == pytest.approx(sum(p))
    # A later window: the items still running then, from now.
    later = out["per_period"][3]
    s = lambda a, x: dist.sf(a + x) / dist.sf(a)  # noqa: E731
    assert later["expected_demand"] == pytest.approx(sum(s(a, 30) - s(a, 60) for a in ages))


def test_a_repairable_fleet_is_poisson():
    class Hpp:
        def cif(self, x):
            return 0.02 * np.asarray(x, dtype=float)

    ages, rates = np.array([100.0, 300]), np.array([50.0, 50])
    out = fleet_service.spares_answer({"lead_time": 2, "review": 1}, "repairable", Hpp(), ages, rates, 4, "months")
    assert out["hold"] == poisson.ppf(0.95, 0.02 * 50 * 3 * 2) and out["reorder_at"] == poisson.ppf(0.95, 4)
    assert "lead time and review period (3 months)" in out["summary"]
    pool = fleet_service.spares_answer({"repairable": True, "turnaround": 1}, "repairable", Hpp(), ages, rates, 4,
                                       "months")
    assert pool["hold"] == poisson.ppf(0.95, 2) and pool["reorder_at"] is None and "pool" in pool["summary"]
    assert fleet_service.spares_answer({}, "repairable", Hpp(), ages, rates, 4, "months")["status"] == \
        "needs_lead_time"


def test_fleet_spares_settings_are_kept_and_answered(env):
    from backend.tests.test_fleet_alerts import _mcp_fleet

    fid = _mcp_fleet(env)
    with pytest.raises(fleet_service.FleetValidationError):
        fleet_service.replace_items(env.db, fid, {"periods": 6, "spares": {"lead_time": 2, "service_level": 3}},
                                    [{"name": "P1", "current_use": 40}], A)
    fleet = fleet_service.replace_items(
        env.db, fid, {"periods": 6, "default_rate": 5, "method": "renewals",
                      "spares": {"lead_time": "2", "service_level": 0.9, "stock": 1, "per_failure": None}},
        [{"name": f"P{i}", "current_use": 40 + i} for i in range(5)], A)
    assert fleet.settings["spares"] == {"lead_time": 2.0, "service_level": 0.9, "stock": 1.0}
    out = fleet_service.compute(env.db, fleet, A, spares_opts=fleet.settings["spares"])
    assert out["spares"]["status"] == "ok" and out["spares"]["service_level"] == 0.9
    assert "spares" not in fleet_service.compute(env.db, fleet, A)


@pytest.mark.usefixtures("mcp_on")
def test_fleet_spares_over_mcp(env):
    from backend.tests.test_fleet_alerts import _mcp_fleet

    fid = _mcp_fleet(env)
    out = _ok(_call(env.token[A], "strategy", {"action": "fleet_forecast", "fleet_id": fid,
                                               "spares": {"lead_time": 3, "stock": 0}}))
    sp = out["forecast"]["spares"]
    assert sp["status"] == "ok" and sp["lead_time"] == 3 and sp["risk_at_stock"] >= 0 and sp["summary"]
    plain = _ok(_call(env.token[A], "strategy", {"action": "fleet_forecast", "fleet_id": fid}))
    assert "spares" not in plain["forecast"]
    bad = _call(env.token[A], "strategy", {"action": "fleet_forecast", "fleet_id": fid,
                                           "spares": {"lead_time": -1}})
    assert "lead time" in _err(bad)
