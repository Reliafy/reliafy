"""The quick forecast tool as a sentence (Decisions › Forecasts; forecast plan step 1, Nov 2026):
work on a schedule (a certain count, no model), a part that fails (the saved-fleet engine, unchanged)
or both, as lines with one owner each. The figures are the plan's worked examples 3.1 to 3.4: the
schedule counts exactly, and the part's failures are worked out (RePyability, not simulated), so they
agree with the lines by owner from the Explorer."""

import pytest

from backend.services.fleet import FleetValidationError
from backend.services.quick_forecast import quick_forecast
from backend.tests.test_api_tools import env  # noqa: F401 - fixtures
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixtures

START = "2026-11-24"
ENGINE = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 14000}, {"name": "beta", "value": 2.2}],
          "unit": "hours", "name": "Engine worn out"}
PLUG = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 345.8}, {"name": "beta", "value": 2.58}],
        "unit": "hours", "name": "Spark plug"}


def _line(out, owner_kind):
    return next(x for x in out["lines"] if x["owner_kind"] == owner_kind)


def test_schedule_only_is_certain_with_no_model():
    """5.2: greasing every 50 h at 12 h a week for 12 months: 626 h, so 12 times, 2.4 h and $216."""
    out = quick_forecast({"start": START, "running": {"hours": 12, "per": "week"},
                          "work": {"name": "Grease deck spindles", "every": 50, "unit": "hours", "hours_each": 0.2,
                                   "cost_each": 18}})
    work = _line(out, "task")
    assert work["number"] == "certain" and work["times"] == {"expected": 12, "interval": None, "each_unit": 12}
    assert work["hours"]["expected"] == pytest.approx(2.4) and work["cost"]["expected"] == pytest.approx(216)
    assert out["totals"]["cost"]["interval"] == [216, 216] and out["totals"]["cost"]["known"]
    assert out["part"] is None and len(out["lines"]) == 1
    assert "assumed just done at the start" in out["notes"][0]
    assert sum(r["work"] for r in out["rows"]) == 12


def test_a_calendar_task_counts_on_dates_whatever_the_running():
    """From 24 Nov 2026 to 23 Nov 2027, assumed just done at the start (the quick tool's rule): every 4 weeks,
    13 more; every month, 11 more (24 Dec to 24 Oct). Plan 3.1's 12 is a first-Tuesday rule from the
    records, counted from the plan's records (test_forecast_lines)."""
    four = quick_forecast({"start": START, "work": {"name": "Lube round", "every": 4, "unit": "weeks"}})
    assert four["end"] == "2027-11-23" and _line(four, "task")["times"]["expected"] == 13
    monthly = quick_forecast({"start": START, "running": {"hours": 2, "per": "day"},
                              "work": {"name": "Test the fire pump", "every": 1, "unit": "months", "hours_each": 1.5,
                                       "cost_each": 120}})
    line = _line(monthly, "task")
    assert line["times"]["expected"] == 11 and line["hours"]["expected"] == pytest.approx(16.5)
    assert line["cost"]["expected"] == pytest.approx(1320) and line["first"] == "2026-12-24"
    # Not running all day doesn't change a calendar task; with no running given, the answer says so.
    assert four["running"]["assumed"] and "all the time" in four["running"]["text"]


def test_the_oil_change_and_the_engine():
    """3.2: one truck at 20 h a day, engine 9,000 h old. 29 oil changes (certain, $16,312.50, 43.5 h); the
    engine's failures 0.688 expected, 64% chance of one or more, range 0 to 1, worked out."""
    out = quick_forecast({"start": START, "running": {"hours": 20, "per": "day"},
                          "work": {"name": "Change engine oil", "every": 250, "hours_each": 1.5, "cost_each": 562.5},
                          "part": {**ENGINE, "age": 9000, "cost_if_fails": 180000, "hours_if_fails": 60}})
    oil, engine = _line(out, "task"), _line(out, "failure")
    assert oil["number"] == "certain" and oil["times"]["expected"] == 29
    assert oil["cost"]["expected"] == pytest.approx(16312.5) and oil["hours"]["expected"] == pytest.approx(43.5)
    # It restarts when the engine is replaced: 250 ÷ (2 × 12,399 h mean life) ≈ 1%, so the count stands with a note.
    assert oil["restart_share"] == pytest.approx(0.0101, abs=0.0005) and "half the time" in oil["note"]
    assert engine["number"] == "worked out" and engine["kind"] == "corrective"
    assert engine["times"]["expected"] == pytest.approx(0.688, abs=0.001)
    assert engine["cost"]["expected"] == pytest.approx(123840, rel=0.001)
    assert engine["times"]["probability"] == pytest.approx(0.64, abs=0.01)  # exact, per unit
    assert engine["times"]["interval"] == [0, 1]
    cost = out["totals"]["cost"]
    # The certain oil changes are added to both ends of the engine's range ($16,313 to $196,313).
    assert cost["interval"] == [pytest.approx(16312.5), pytest.approx(196312.5)] and cost["known"]
    # 90% one-sided: 90% chance of no failure in the first 1,060 h (about 1.7 months at 20 h a day).
    assert out["no_failure_before"]["in_life_unit"] == pytest.approx(1060, rel=0.01)
    assert out["no_failure_before"]["days"] / 30.4375 == pytest.approx(1.75, abs=0.05)


def test_a_gap_is_flagged_never_filled():
    """1.6: no cost if it fails: the failures are counted, their cost is unknown, and the total is the known
    cost with what it leaves out."""
    out = quick_forecast({"start": START, "running": {"hours": 20, "per": "day"},
                          "work": {"name": "Change engine oil", "every": 250, "cost_each": 562.5},
                          "part": {**ENGINE, "age": 9000}})
    engine = _line(out, "failure")
    assert engine["times"]["expected"] > 0 and engine["cost"] is None and engine["hours"] is None
    assert {g["view"] for g in engine["gaps"]} == {"hours", "cost"}
    cost = out["totals"]["cost"]
    assert not cost["known"] and cost["expected"] == pytest.approx(16312.5)
    assert cost["leaves_out"] == ["Engine worn out failures (no cost if it fails)"]
    assert "Change engine oil (no hours each time)" in out["totals"]["hours"]["leaves_out"]


def test_work_that_replaces_the_part_is_a_planned_replacement():
    """3.3, restart (age replacement): plugs every 100 h at 12 h a week, 626 h: 5.77 planned changes and
    0.243 failures, $501 at $49 and $900, worked out."""
    out = quick_forecast({"start": START, "running": {"hours": 12, "per": "week"},
                          "work": {"name": "Replace spark plug", "every": 100, "effect": "replaces", "cost_each": 49},
                          "part": {**PLUG, "age": 0, "cost_if_fails": 900}})
    plan, fail = _line(out, "task"), _line(out, "failure")
    assert plan["replaces"] and plan["number"] == "worked out"
    assert plan["times"]["expected"] == pytest.approx(5.77, abs=0.005)
    assert fail["times"]["expected"] == pytest.approx(0.243, abs=0.001)
    assert out["totals"]["cost"]["expected"] == pytest.approx(501, abs=1)


def test_three_bearings_agree_with_the_lines():
    """3.4 without the inspection: three bearings 900 h old, 626 h: 1.65 failures (0 to 3), a 90% chance of
    at least one (10% of none), $1,486 at $900: the same as the lines by owner give."""
    bearing = {"distribution_id": "weibull", "unit": "hours", "name": "Spindle bearing",
               "params": [{"name": "alpha", "value": 1537}, {"name": "beta", "value": 3.04}]}
    out = quick_forecast({"start": START, "units": 3, "running": {"hours": 12, "per": "week"},
                          "part": {**bearing, "age": 900, "cost_if_fails": 900}})
    fail = _line(out, "failure")
    assert fail["times"]["expected"] == pytest.approx(1.65, abs=0.005) and fail["times"]["interval"] == [0, 3]
    assert out["probability_any"] == pytest.approx(0.90, abs=0.005)
    assert sum(r["failures"] for r in out["rows"]) == pytest.approx(fail["times"]["expected"], rel=1e-6)


@pytest.mark.parametrize("body, words", [
    ({}, "at least one"),
    ({"work": {"name": "x"}}, "how often"),
    ({"work": {"every": 5, "unit": "fortnights"}}, "hours, days"),
    ({"work": {"every": 100, "effect": "replaces"}}, "needs a part"),
    ({"part": {**ENGINE}}, "how old"),
    ({"running": {"hours": 30, "per": "day"}, "work": {"every": 5}}, "more than 24"),
    ({"months": 7, "work": {"every": 5}}, "12, 24, 36 or 60"),
])
def test_what_it_refuses_says_what_to_do(body, words):
    with pytest.raises(FleetValidationError, match=words):
        quick_forecast(body)


def test_rest_and_mcp_twins(env):  # noqa: F811
    body = {"start": START, "running": {"hours": 20, "per": "day"}, "work": {"name": "Change engine oil", "every": 250}}
    v1 = env.post("/api/v1/analyse/forecast", body)
    assert v1.status_code == 200, v1.text
    assert _line(v1.json(), "task")["times"]["expected"] == 29
    # A saved model by id, as the other calculators take it.
    bad = env.post("/api/v1/analyse/forecast", {**body, "model_id": "nope", "part": {"age": 10}})
    assert bad.status_code >= 400 and "Model not found" in bad.text
    # Pro over MCP and REST, like analyse fleet_forecast (the app's tool keeps today's rule).
    from backend import mcp_server

    assert "analyse.forecast" in mcp_server.PRO_ONLY_TOOLS


def test_the_app_route(api):  # noqa: F811
    body = {"start": START, "running": {"hours": 20, "per": "day"}, "work": {"name": "Change engine oil", "every": 250}}
    r = api.post("/api/fleet/quick-forecast", json=body)
    assert r.status_code == 200, r.text
    assert _line(r.json(), "task")["times"]["expected"] == 29 and r.json()["saved"] is False
    assert api.post("/api/fleet/quick-forecast", json={}).status_code == 422


def test_work_that_keeps_its_schedule_is_block_replacement():
    """3.3, keep: plugs every 100 h on the schedule, failures or not: 6 planned changes, 0.241 failures, $511."""
    out = quick_forecast({"start": START, "running": {"hours": 12, "per": "week"},
                          "work": {"name": "Replace spark plug", "every": 100, "effect": "replaces", "cost_each": 49,
                                   "on_replace": "keep"},
                          "part": {**PLUG, "age": 0, "cost_if_fails": 900}})
    plan, fail = _line(out, "task"), _line(out, "failure")
    assert plan["times"]["expected"] == pytest.approx(6.0, abs=0.001) and plan["times"]["interval"] == [6, 6]
    assert fail["times"]["expected"] == pytest.approx(0.241, abs=0.001)
    assert out["totals"]["cost"]["expected"] == pytest.approx(511, abs=1)
    assert any("block replacement" in n for n in out["notes"])


def test_supporting_work_stretched_and_its_worth():
    """4.5 in the quick tool: the oil change keeps the engine on its life (× 2.5 if not changed). Stretched to
    500 h: 0.957 failures (× 1.75 on average), 14 changes; its worth: avoids about 0.45 failures, $81,000 a
    year, for $16,313. Nothing is saved."""
    out = quick_forecast({"start": START, "running": {"hours": 20, "per": "day"},
                          "work": {"name": "Change engine oil", "every": 250, "effect": "supports", "impact_k": 2.5,
                                   "cost_each": 562.5, "whatif": {"interval": 500}},
                          "part": {**ENGINE, "age": 9000, "cost_if_fails": 180000}})
    assert _line(out, "failure")["times"]["expected"] == pytest.approx(0.688, abs=0.002)
    alt = out["whatif"]
    assert alt["ratio"]["mult"] == pytest.approx(1.75) and not alt["approximate"]
    assert next(x for x in alt["lines"] if x["owner_kind"] == "failure")["times"]["expected"] == pytest.approx(0.957, abs=0.003)
    assert next(x for x in alt["lines"] if x["owner_kind"] == "task")["times"]["expected"] == 14
    w = out["worth"]
    assert w["avoids_failures"] == pytest.approx(0.451, abs=0.005) and w["costs"] == pytest.approx(16312.5)
    assert w["words"].startswith("Worth: avoids about $81")
    # Dropped: the work's line goes, the engine at × 2.5.
    dropped = quick_forecast({"start": START, "running": {"hours": 20, "per": "day"},
                              "work": {"name": "Change engine oil", "every": 250, "effect": "supports", "impact_k": 2.5,
                                       "whatif": {"drop": True}},
                              "part": {**ENGINE, "age": 9000, "cost_if_fails": 180000}})
    assert [x["owner_kind"] for x in dropped["whatif"]["lines"]] == ["failure"]
    assert dropped["whatif"]["lines"][0]["times"]["expected"] == pytest.approx(1.139, abs=0.003)
