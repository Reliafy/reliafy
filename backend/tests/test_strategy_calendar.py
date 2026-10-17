"""Replacement over a shutdown calendar (Strategy › Replacement, "Shutdown
calendar"): RePyability's calendar policy laid on real dates.

The figures are RePyability's own use cases (``repyability/maintenance/
README.md``): UC-13's bearing (Weibull 1000 days, shape 2.5; weekly stop 3,
quarterly shut 2, annual shut 1, any day 4, failure 20) and UC-12's / UC-7's
(Weibull 365 days, shape 2; a shut every 180 days at 100, 150 any day, 400 at
a failure)."""

from datetime import date

import mongomock
import pytest
import surpyval as surv
from fastapi.testclient import TestClient
from repyability import Calendar, NonRepairable, Opportunity

from backend.services import strategy_calendar as sc
from backend.services.strategy import StrategyError

TODAY = "2026-10-18"
UC13 = [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.5}]
BEARING = [{"name": "alpha", "value": 365.0}, {"name": "beta", "value": 2.0}]
UC13_SHUTS = [
    {"name": "weekly stop", "cost": 3, "every": 7, "every_unit": "days", "start": TODAY},
    {"name": "quarterly shut", "cost": 2, "every": 91, "every_unit": "days", "start": TODAY},
    {"name": "annual shut", "cost": 1, "every": 52, "every_unit": "weeks", "start": TODAY},
]
SHUT_180 = [{"name": "shut", "cost": 100, "every": 180, "every_unit": "days", "start": "2027-03-17"}]


def _uc13(**kw):
    args = dict(unit="Days", today=TODAY, opportunities=UC13_SHUTS, failure_cost=20, anytime_cost=4)
    args.update(kw)
    return sc.calendar_replacement("weibull", UC13, **args)


# ---- The numbers are RePyability's ----------------------------------------------------------

def test_uc13_matches_repyability():
    out = _uc13()
    # RePyability on the same calendar, built by hand in model time.
    part = NonRepairable(surv.Weibull.from_params([1000.0, 2.5]))
    cal = Calendar([Opportunity("weekly stop", 3.0, period=7.0), Opportunity("quarterly shut", 2.0, period=91.0),
                    Opportunity("annual shut", 1.0, period=364.0)], failure=20.0, anytime=4.0)
    ref = part.optimal_calendar_policy(cal, method="dp")
    assert out["cost_rate"] == pytest.approx(ref.cost_rate, rel=1e-12)
    # The README's figures: 25.27 over ten years (3,640 days), 0.962 annual replacements and
    # 0.078 failures a year (364 days), the annual shut replacing from 88 days.
    assert out["cost_rate"] * 3640 == pytest.approx(25.27, abs=0.005)
    rows = {r["kind"]: r for r in out["by_kind"]}
    assert rows["annual shut"]["replacements_per_year"] * 364 / 365.25 == pytest.approx(0.962, abs=5e-4)
    assert rows["failure"]["replacements_per_year"] * 364 / 365.25 == pytest.approx(0.078, abs=5e-4)
    assert rows["weekly stop"]["replacements_per_year"] == 0 and rows["quarterly shut"]["replacements_per_year"] == 0
    assert sum(r["cost_per_year"] for r in out["by_kind"]) == pytest.approx(out["cost_per_year"], rel=1e-9)
    assert out["method"] == "dp" and out["basis"] == "exact" and out["period"] == 364.0
    annual = next(ln for ln in out["rule"] if ln["kind"] == "annual shut")
    assert annual["used"] and annual["threshold_min"] == pytest.approx(88.375)
    assert "older than 88.4 days" in annual["text"]
    assert not next(ln for ln in out["rule"] if ln["kind"] == "weekly stop")["used"]
    # Simpler rules: every annual shut 25.48, age replacement on any day 50.41, run to failure 82.05.
    comp = {(c["policy"], c.get("kind")): c for c in out["comparisons"]}
    assert comp[("every", "annual shut")]["cost_rate"] * 3640 == pytest.approx(25.48, abs=0.005)
    assert comp[("age", None)]["cost_rate"] * 3640 == pytest.approx(50.41, abs=0.005)
    assert comp[("age", None)]["age"] == pytest.approx(493.0, abs=0.1)
    assert comp[("run_to_failure", None)]["cost_rate"] * 3640 == pytest.approx(82.05, abs=0.005)
    assert out["savings_vs_age_rule"] == pytest.approx(1 - 25.27 / 50.41, abs=1e-3)
    assert "69% less than running to failure" in out["recommendation"]


def test_uc13_schedule_has_dates_thresholds_and_chances():
    out = _uc13()
    assert out["today"] == TODAY and out["schedule_until"] == "2027-10-18"
    big = [r for r in out["schedule"] if r["kind"] != "weekly stop"]
    assert [(r["date"], r["kind"]) for r in big] == [
        ("2026-10-18", "annual shut"), ("2027-01-17", "quarterly shut"), ("2027-04-18", "quarterly shut"),
        ("2027-07-18", "quarterly shut"), ("2027-10-17", "annual shut")]
    assert big[0]["chance"] == pytest.approx(0.9618, abs=1e-4) and big[0]["price"] == 1.0
    assert [round(r["threshold"]) for r in big[1:4]] == [221, 324, 574]
    weekly = [r for r in out["schedule"] if r["kind"] == "weekly stop"]
    assert len(weekly) == 53 - 5 and all(r["chance"] == 0 for r in weekly)  # 5 fall on a cheaper shut


def test_uc7_shuts_every_180_days():
    """docs/maintenance-scheduling.md UC-7: at each shut, replace a bearing at least about 138 days old,
    0.990 a day; age replacement off the schedule 1.117, every shut 1.056, run to failure 1.237."""
    out = sc.calendar_replacement("weibull", BEARING, unit="Days", today=TODAY, opportunities=SHUT_180,
                                  failure_cost=400, anytime_cost=150)
    assert out["cost_rate"] == pytest.approx(0.9903, abs=1e-4)
    shut = next(ln for ln in out["rule"] if ln["kind"] == "shut")
    assert shut["threshold_min"] == pytest.approx(138.0, abs=0.5)
    comp = {(c["policy"], c.get("kind")): c["cost_rate"] for c in out["comparisons"]}
    assert comp[("age", None)] == pytest.approx(1.117, abs=1e-3)
    assert comp[("every", "shut")] == pytest.approx(1.056, abs=1e-3)
    assert comp[("run_to_failure", None)] == pytest.approx(1.237, abs=1e-3)
    assert out["schedule"][0]["date"] == "2027-03-17"
    # No replacement between shuts: the same policy (it never paid), and no age rule to compare.
    shuts_only = sc.calendar_replacement("weibull", BEARING, unit="Days", today=TODAY, opportunities=SHUT_180,
                                         failure_cost=400, anytime_cost=None, method="integration")
    assert shuts_only["cost_rate"] == pytest.approx(out["cost_rate"], rel=1e-4)
    assert shuts_only["age_rule"] is None and shuts_only["method"] == "integration"
    assert shuts_only["rule"][-1]["kind"] == "shut"


def test_one_unit_now_matches_uc12_with_the_shuts_policy():
    out = sc.calendar_next("weibull", BEARING, age=200, unit="Days", today=TODAY, opportunities=SHUT_180,
                           failure_cost=400, anytime_cost=150)
    # README UC-12 with the shuts' policy: 124.6 at the outage in 150 days, against 150.0 now, 142.8
    # planned in 64 days and 210.4 run to failure; replace now from 263.9 days old.
    assert out["cost_rate"] == pytest.approx(0.990, abs=1e-3)
    assert out["best"]["kind"] == "outage" and out["best"]["date"] == "2027-03-17"
    assert out["best"]["cost"] == pytest.approx(124.6, abs=0.05)
    assert out["best"]["break_even_age"] == pytest.approx(256.1, abs=0.1)
    choices = {c["kind"]: c for c in out["choices"]}
    assert choices["now"]["cost"] == 150.0
    assert choices["planned"]["cost"] == pytest.approx(142.8, abs=0.05)
    assert choices["failure"]["cost"] == pytest.approx(210.4, abs=0.05)
    assert out["replace_from_age"] == pytest.approx(263.9, abs=0.1)
    assert out["now"] is False and out["recommendation"].startswith("Keep it: replace it at the shut on 17 Mar 2027.")
    assert out["policy_next"]["date"] == "2027-03-17" and out["policy_next"]["kind"] == "shut"
    old = sc.calendar_next("weibull", BEARING, age=300, unit="Days", today=TODAY, opportunities=SHUT_180,
                           failure_cost=400, anytime_cost=150)
    assert old["now"] is True and old["recommendation"].startswith("Replace it now")


def test_one_unit_now_without_any_day_replacement():
    with pytest.raises(StrategyError, match="enter what replacing it now would cost"):
        sc.calendar_next("weibull", BEARING, age=200, unit="Days", today=TODAY, opportunities=SHUT_180,
                         failure_cost=400)
    out = sc.calendar_next("weibull", BEARING, age=200, unit="Days", today=TODAY, opportunities=SHUT_180,
                           failure_cost=400, now_cost=250)
    assert "planned" not in {c["kind"] for c in out["choices"]}
    assert out["now_cost"] == 250
    # A shut falling today is the price of replacing now.
    today_shut = [{"name": "shut", "cost": 100, "every": 180, "every_unit": "days", "start": TODAY}]
    out = sc.calendar_next("weibull", BEARING, age=200, unit="Days", today=TODAY, opportunities=today_shut,
                           failure_cost=400)
    assert out["now_cost"] == 100 and out["outages"][0]["date"] == "2027-04-16"


# ---- Dates to model time (today = 0) ----------------------------------------------------------

def test_dates_become_model_time_from_today():
    today = date(2026, 10, 18)
    specs = sc.parse_opportunities([
        {"name": "A", "cost": 1, "every": 6, "every_unit": "months", "start": "2026-11-01"},
        {"name": "B", "cost": 2, "dates": ["2027-01-01", "2026-10-18", "2026-12-25", "2026-01-01"]},
        {"name": "C", "cost": 3, "every": 2, "every_unit": "weeks"},
    ], today, 24.0)  # a model in hours
    a, b, c = specs
    assert a["period"] == pytest.approx(6 * 365.25 / 12 * 24) and a["offset"] == 14 * 24
    # Irregular dates, sorted, today's at 0, a past one left out (and counted).
    assert b["dates"] == ["2026-10-18", "2026-12-25", "2027-01-01"] and b["past_dates_dropped"] == 1
    assert b["times"] == [0.0, 68 * 24.0, 75 * 24.0]
    assert c["period"] == 14 * 24 and c["offset"] == 0 and c["start"] == "2026-10-18"


def test_units_convert_dates_and_the_answer_is_the_same_in_hours():
    days = sc.calendar_replacement("weibull", BEARING, unit="days", today=TODAY, opportunities=SHUT_180,
                                   failure_cost=400, anytime_cost=150)
    hours = sc.calendar_replacement("weibull", [{"name": "alpha", "value": 365.0 * 24}, BEARING[1]], unit="hrs",
                                    today=TODAY, opportunities=SHUT_180, failure_cost=400, anytime_cost=150)
    assert hours["unit"] == "Hours" and hours["units_per_day"] == 24.0
    assert hours["cost_per_year"] == pytest.approx(days["cost_per_year"], rel=1e-6)
    assert hours["schedule"][0]["date"] == days["schedule"][0]["date"] == "2027-03-17"
    assert hours["rule"][0]["threshold_min"] / 24 == pytest.approx(days["rule"][0]["threshold_min"], rel=1e-3)
    assert sc.units_per_day("Months") == pytest.approx(12 / 365.25)
    assert sc.units_per_day("years") == pytest.approx(1 / 365.25)


def test_month_shuts_show_on_their_calendar_dates():
    assert sc.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert sc.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    out = sc.calendar_replacement("weibull", BEARING, unit="Days", today=TODAY, failure_cost=400, anytime_cost=150,
                                  opportunities=[{"name": "shut", "cost": 100, "every": 3, "every_unit": "months",
                                                  "start": "2026-01-31"}])
    # Every 3 months from 31 January: the 31st, or the month's last day.
    assert [r["date"] for r in out["schedule"]] == ["2026-10-31", "2027-01-31", "2027-04-30", "2027-07-31"]


def test_irregular_dates_are_a_plan_repeated():
    shuts = [{"name": "turnaround", "cost": 1, "dates": ["2027-01-26", "2027-12-12", "2028-12-25"]}]
    out = sc.calendar_replacement("weibull", UC13, unit="Days", today=TODAY, opportunities=shuts, failure_cost=20,
                                  anytime_cost=4)
    part = NonRepairable(surv.Weibull.from_params([1000.0, 2.5]))
    ref = part.optimal_calendar_policy(Calendar([Opportunity("turnaround", 1.0, dates=[100.0, 420.0, 799.0])],
                                                failure=20.0, anytime=4.0), method="dp")
    assert out["cost_rate"] == pytest.approx(ref.cost_rate, rel=1e-12)
    assert [r["date"] for r in out["schedule"]] == ["2027-01-26"]
    assert out["determined_until_date"] is not None
    assert any("repeat after the last one" in n for n in out["notes"])


def test_inputs_are_checked_in_plain_words():
    base = dict(unit="Days", today=TODAY, failure_cost=400, anytime_cost=150)
    bad = [
        (dict(unit="Cycles"), "unit of time"),
        (dict(unit=""), "time unit"),
        (dict(failure_cost=None), "failure"),
        (dict(opportunities=[{"name": "s", "cost": 1}]), "how often"),
        (dict(opportunities=[{"name": "s", "cost": 1, "every": 7, "dates": ["2027-01-01"]}]), "not both"),
        (dict(opportunities=[{"name": "s", "cost": 1, "dates": ["2020-01-01"]}]), "before today"),
        (dict(opportunities=[{"name": "s", "cost": 1, "dates": ["soon"]}]), "isn't a date"),
        (dict(opportunities=[{"name": "anytime", "cost": 1, "every": 7}]), "call the shut something else"),
        (dict(opportunities=[{"name": "S", "cost": 1, "every": 7}, {"name": "s", "cost": 2, "every": 9}]),
         "Two shuts"),
        (dict(opportunities=[{"name": f"s{i}", "cost": 1, "every": 7 + i} for i in range(9)]), "At most 8"),
        (dict(opportunities=[{"name": "s", "cost": -1, "every": 7}]), "at least 0"),
        (dict(opportunities=[{"name": "s", "cost": 1, "every": 7, "every_unit": "fortnights"}]), "every"),
        (dict(opportunities=[], anytime_cost=None), "at least one shut"),
        (dict(method="magic", opportunities=SHUT_180), "method"),
        (dict(method="integration", opportunities=SHUT_180), "no replacement between shuts"),
    ]
    for over, words in bad:
        with pytest.raises(StrategyError, match=words):
            sc.calendar_replacement("weibull", BEARING, **{**base, **over})


def test_a_limited_failure_population_is_refused_plainly():
    with pytest.raises(StrategyError, match="limited failure population"):
        sc.calendar_replacement("weibull", BEARING, extras={"p": 0.7}, unit="Days", today=TODAY,
                                opportunities=SHUT_180, failure_cost=400, anytime_cost=150)
    # Offset and zero-inflated fits are taken as fitted.
    out = sc.calendar_replacement("weibull", BEARING, extras={"gamma": 50.0}, unit="Days", today=TODAY,
                                  opportunities=SHUT_180, failure_cost=400, anytime_cost=150, max_age=3000)
    assert out["cost_rate"] < 0.99 and out["max_age"] == 3000


# ---- Gating, the job and the routes -------------------------------------------------------------

@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_calendar_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _inputs(**kw):
    return {"distribution_id": "weibull", "params": BEARING, "unit": "Days", "today": TODAY,
            "opportunities": SHUT_180, "failure_cost": 400, "anytime_cost": 150, **kw}


def test_exact_methods_are_free_and_sampling_is_pro(session):
    from backend.services import strategy_calendar_api as api

    code, out = api.run(session, {"uid": "u1"}, _inputs(), entitled=False)
    assert code == 200 and out["method"] == "dp"
    code, out = api.run(session, {"uid": "u1"}, _inputs(method="sampling"), entitled=False)
    assert code == 402 and out["code"] == "pro_required"
    # Entitled, with no queue (self-hosted): it runs here, sampled, with a standard error.
    code, out = api.run(session, {"uid": "u1"}, _inputs(method="sampling", mc_samples=8), entitled=True)
    assert code == 200 and out["method"] == "sampling" and out["cost_rate_se"] > 0
    assert out["cost_rate"] == pytest.approx(0.9903, abs=4 * out["cost_rate_se"])
    assert out["mc_samples"] == 8


def test_sampling_queues_a_job_and_its_view_is_the_result(session, monkeypatch):
    from backend.services import compute_core, compute_queue, rbd_jobs
    from backend.services import strategy_calendar_api as api

    queued = []
    monkeypatch.setattr(compute_queue, "configured", lambda: True)
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: queued.append((job_id, kind, request)))
    with pytest.raises(StrategyError, match="isn't a date"):  # checked before anything is queued
        api.run(session, {"uid": "u1"}, _inputs(method="sampling", today="tomorrow"), entitled=True)
    assert not queued
    code, body = api.run(session, {"uid": "u1"}, _inputs(method="sampling", mc_samples=8), entitled=True)
    assert code == 202 and body["job"]["kind"] == "calendar_replacement"
    job_id, kind, request = queued[0]
    assert kind == "calendar_replacement" and request["seed"] is None and request["today"] == TODAY
    code2, body2 = api.run(session, {"uid": "u1"}, _inputs(method="sampling", mc_samples=8), entitled=True)
    assert code2 == 202 and body2["job"]["job_id"] == job_id and len(queued) == 1
    # What the compute service would post back (the exact answer stands in for speed).
    result = compute_core.to_wire(sc.calendar_replacement("weibull", BEARING, unit="Days", today=TODAY,
                                                          opportunities=SHUT_180, failure_cost=400,
                                                          anytime_cost=150))
    assert rbd_jobs.apply_callback(session, {"job_id": job_id, "status": "done", "result": result})
    view = rbd_jobs.view(session, rbd_jobs.get(session, job_id), True)
    assert view["status"] == "done" and view["result"]["cost_rate"] == result["cost_rate"]
    code3, done = api.run(session, {"uid": "u1"}, _inputs(method="sampling", mc_samples=8), entitled=True)
    assert code3 == 200 and done["cost_rate"] == result["cost_rate"]


def test_the_compute_runner_reports_the_users_mistakes():
    from backend.services import compute_core
    from backend.services.rbd_analysis import AnalysisError

    assert "calendar_replacement" in compute_core.KINDS
    request = compute_core.calendar_request(_inputs(method="dp"))
    assert compute_core.run("calendar_replacement", request)["cost_rate"] == pytest.approx(0.9903, abs=1e-4)
    with pytest.raises(AnalysisError, match="unit of time"):
        compute_core.run("calendar_replacement", {**request, "unit": "Cycles"})
    with pytest.raises(compute_core.InvalidRequest, match="Unknown fields"):
        compute_core.run("calendar_replacement", {**request, "graph": {}})


def test_routes(session, monkeypatch):
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import billing as billing_service

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1", "email": "a@example.org", "name": "A"}
    try:
        client = TestClient(app)
        body = _inputs()
        r = client.post("/api/strategy/calendar-replacement", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["cost_rate"] == pytest.approx(0.9903, abs=1e-4)
        r = client.post("/api/strategy/calendar-replacement", json={**body, "unit": "Cycles"})
        assert r.status_code == 422 and "unit of time" in r.json()["detail"]
        r = client.post("/api/strategy/calendar-next", json={**body, "age": 200})
        assert r.status_code == 200 and r.json()["best"]["date"] == "2027-03-17"
        r = client.post("/api/strategy/calendar-next", json=body)
        assert r.status_code == 422 and "age" in r.json()["detail"]
        monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda *a, **k: False)
        r = client.post("/api/strategy/calendar-replacement", json={**body, "method": "sampling"})
        assert r.status_code == 402 and r.json()["code"] == "pro_required"
        # Plain age replacement is unchanged.
        r = client.post("/api/strategy/optimal-replacement", json={"distribution_id": "weibull", "params": BEARING,
                                                                   "planned_cost": 150, "unplanned_cost": 400,
                                                                   "unit": "Days"})
        assert r.status_code == 200
        assert r.json()["optimal_time"] == pytest.approx(297.6, abs=0.1)
        assert r.json()["optimal_cost_rate"] == pytest.approx(1.117, abs=1e-3)
    finally:
        app.dependency_overrides.clear()
    client = TestClient(app)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    assert client.post("/api/strategy/calendar-replacement", json=_inputs()).status_code == 401


# ---- MCP: strategy calendar_replacement / next_replacement -----------------------------------------

from backend.tests.test_mcp_plans import FREE, PRO, _call, env  # noqa: E402,F401
from backend.tests.test_mcp import _ok  # noqa: E402

MCP_SHUTS = [{"name": "shut", "cost": 100, "every": 180, "every_unit": "days", "start": "2027-03-17"}]


@pytest.mark.usefixtures("mcp_on")
def test_mcp_calendar_replacement_and_next_replacement(env):
    args = {"action": "calendar_replacement", "distribution_id": "weibull", "params": BEARING, "unit": "days",
            "shuts": MCP_SHUTS, "failure_cost": 400, "anytime_cost": 150, "today": TODAY}
    out = _ok(_call(env.oauth[PRO], "strategy", args))
    assert out["cost_rate"] == pytest.approx(0.9903, abs=1e-4) and out["method"] == "dp"
    assert out["schedule"] and all(r["chance"] >= 1e-3 for r in out["schedule"]) and "schedule_note" in out
    assert "shut" in out["rule"][0]["text"]
    # Free gets the exact answer; sampling is Pro, so a Free call is answered exactly, with a note.
    free = _ok(_call(env.oauth[FREE], "strategy", {**args, "method": "sampling"}))
    assert free["method"] == "dp" and "part of Pro" in free["pro_note"]
    nxt = _ok(_call(env.oauth[PRO], "strategy", {**{k: v for k, v in args.items() if k != "action"},
                                                  "action": "next_replacement", "age": 200}))
    assert nxt["best"]["kind"] == "outage" and nxt["replace_from_age"] == pytest.approx(263.9, abs=0.1)
    # A saved model brings its unit.
    saved = _ok(_call(env.oauth[PRO], "models", {"action": "save", "name": "Bearing", "distribution": "weibull",
                                                  "params": BEARING, "unit": "days"}))
    by_id = _ok(_call(env.oauth[PRO], "strategy", {"action": "calendar_replacement", "model_id": saved["model_id"],
                                                   "shuts": MCP_SHUTS, "failure_cost": 400, "anytime_cost": 150,
                                                   "today": TODAY}))
    assert by_id["cost_rate"] == pytest.approx(out["cost_rate"], rel=1e-12) and by_id["unit"] == "Days"
