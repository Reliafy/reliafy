"""A forecast as lines by owner (forecast plan step 2, Nov 2026): the plan's worked examples 3.1,
3.2 and 3.4 from records, through Open in › (forecast_lines.node_forecast). Every figure here is the
plan's (forecast-rules-2026-11, section 3), computed with SurPyval 0.29 and RePyability 0.20.

* 3.1: test the fire pump on the first Tuesday of every month, 1.5 h and $120: 12 times from 24 Nov
  2026 to 23 Nov 2027, 18 h, $1,440, certain; no failures line.
* 3.2: a haul truck at 20 h a day, its engine 9,000 h old (Weibull 14,000 h, 2.2); oil every 250 h
  at $562.50 and 1.5 h: 29 changes, $16,313; the engine 0.688 failures expected, 64% chance of one or
  more, 0 to 1, $123,840 at $180,000; in all $140,150 ($16,313 to $196,313).
* 3.4: three spindle bearings 900 h old (Weibull 1,537 h, 3.04), 12 h a week: greasing 12 times
  ($216, 2.4 h), inspecting 6 times ($135, 1.8 h), 1.65 bearing failures if nothing found them
  (0 to 3), 91.8% found in time: 1.52 finds (0 to 3) and 0.14 failures (0 to 1) at $900, $122. The
  follow-on's $160 isn't a record yet (plan step 4): its cost is listed as not counted, and the sum
  with it is checked on its own ($715, $351 to $1,411).
"""

from datetime import datetime, timezone

import mongomock
import pytest

from backend.maintenance import forecast_lines as fl
from backend.maintenance import position_models as pm
from backend.tests.test_maintenance_forecast_engine import _m, _rebuilds_the_same

TODAY = "2026-11-24"
ORG = "org-forecast-lines"


@pytest.fixture
def setting(monkeypatch):
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime.fromisoformat(TODAY).replace(hour=8, tzinfo=timezone.utc))
    m = _m(ORG)
    m.today = lambda: TODAY
    db = mongomock.MongoClient()["forecast_lines"]
    return m, db, pm.fetcher(db, [ORG])


def _life(db, mid, name, alpha, beta):
    db.models.insert_one({"_id": mid, "id": mid, "name": name, "kind": "distribution", "distribution_id": "weibull",
                          "dataset_id": "ds-" + mid, "spec": {"unit": "hours"}, "status": "ready", "owner_id": ORG,
                          "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
                          "results": {"distribution_id": "weibull", "unit": "hours",
                                      "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}})


def _by(out, kind, owner=None):
    return next(x for x in out["lines"]["lines"] if x["kind"] == kind and (owner is None or x["owner"] == owner))


def test_3_1_a_calendar_task_with_no_model(setting):
    m, _db, fetch = setting
    pump = m.create_position("Fire pump")["id"]
    task = m.create_task(pump, "Test the fire pump", 1, "months",
                         rule={"kind": "monthly", "every": 1, "weekday": "Tuesday", "nth": 1})["id"]
    m.set_task_resources(task, {"labour": [{"trade": "Fitter", "people": 1, "hours": 1.5}]})
    m.set_task_cost(task, 120)
    out = fl.node_forecast(m, fetch, "position", pump, pump, 12)
    assert (out["start"], out["end"]) == ("2026-11-24", "2027-11-23")
    line = _by(out, "planned")
    assert line["number"] == "certain" and line["times"] == {"expected": 12, "interval": None}
    assert line["hours"]["expected"] == pytest.approx(18) and line["cost"]["expected"] == pytest.approx(1440)
    dates = next(t for t in out["tasks"] if t["id"] == task)["dates"]
    assert (dates[0], dates[-1]) == ("2026-12-01", "2027-11-02")
    assert not [x for x in out["lines"]["lines"] if x["owner_kind"] == "failure_mode"]
    cost = out["lines"]["totals"]["cost"]
    assert cost["expected"] == pytest.approx(1440) and cost["interval"] == [1440, 1440] and cost["known"]
    # The same from the task itself.
    one = fl.node_forecast(m, fetch, "task", task, pump, 12)
    assert _by(one, "planned")["times"]["expected"] == 12 and one["of"]["name"] == "Test the fire pump"


def test_3_2_the_oil_change_and_the_engine(setting):
    m, db, fetch = setting
    _life(db, "engine", "Engine life", 14000, 2.2)
    truck = m.create_position("Haul truck 7")["id"]
    m.fit(truck, new_item={"name": "Engine SN 1"}, on="2025-06-01")
    m.set_operating_plan(truck, {"background": {"kind": "rate", "amount": 20, "per": "day"}}, from_="2025-06-01")
    meter = m.add_point(truck, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(meter, 0, on="2025-06-01")
    m.record_reading(meter, 9000, on=TODAY)
    worn = m.add_failure_mode(truck, "Engine worn out")["id"]
    m.set_mode_costs(worn, failure_cost=180000)
    pm.link_saved(m, db, [ORG], set(), truck, "model", "engine", [worn])
    oil = m.create_task(truck, "Change engine oil", 250, "hours")["id"]
    m.set_task_resources(oil, {"labour": [{"trade": "Mechanic", "people": 1, "hours": 1.5}]})
    m.set_task_cost(oil, 562.5)
    out = fl.node_forecast(m, fetch, "position", truck, truck, 12)
    lines = out["lines"]
    change = _by(out, "planned", "Change engine oil")
    assert change["times"]["expected"] == 29 and change["number"] == "certain"
    assert change["cost"]["expected"] == pytest.approx(16312.5) and change["hours"]["expected"] == pytest.approx(43.5)
    engine = _by(out, "corrective", "Engine worn out")
    assert engine["number"] == "worked out"
    assert engine["times"]["expected"] == pytest.approx(0.688, abs=0.002)
    assert engine["times"]["probability"] == pytest.approx(0.64, abs=0.005)
    assert engine["times"]["interval"] == [0, 1]
    assert engine["cost"]["expected"] == pytest.approx(123840, rel=0.003)
    # With no response if it fails, the hours to put a failure right are said unknown, never guessed.
    assert any("no response if it fails" in g["text"] for g in engine["gaps"])
    assert any(x["kind"] == "no_response" and "respond=failure" in x["link"] for x in lines["not_counted"])
    cost = lines["totals"]["cost"]
    assert cost["expected"] == pytest.approx(140150, rel=0.003)
    assert cost["interval"] == [pytest.approx(16312.5), pytest.approx(196312.5)] and cost["known"]
    assert cost["by_kind"]["planned"] == pytest.approx(16312.5)
    assert not lines["totals"]["hours"]["known"]

    # If it fails anyway: replace the engine, 60 h and $180,000 (plan step 3). The failure cost now comes
    # from it (the typed figure cleared), and the hours are counted: 41 h expected (0 to 60).
    m.set_mode_costs(worn, failure_cost=None)
    m.set_mode_response(worn, "failure", name="Replace the engine",
                        labour=[{"trade": "Mechanic", "people": 1, "hours": 60}], cost=180000,
                        spares=[{"name": "Engine", "qty": 1}])
    out = fl.node_forecast(m, fetch, "position", truck, truck, 12)
    engine = _by(out, "corrective", "Engine worn out")
    assert engine["response"]["name"] == "Replace the engine" and not engine["gaps"]
    assert engine["cost"]["expected"] == pytest.approx(123840, rel=0.003)
    assert engine["hours"]["expected"] == pytest.approx(41.3, abs=0.2)
    assert engine["spares"][0]["name"] == "Engine"
    hours = out["lines"]["totals"]["hours"]
    assert hours["known"] and hours["expected"] == pytest.approx(85, abs=0.5)
    assert hours["interval"] == [pytest.approx(43.5), pytest.approx(103.5)]
    assert "its corrective response's (Replace the engine)" in engine["cost"]["basis"]
    # A typed cost of a failure overrides the response's.
    m.set_mode_costs(worn, failure_cost=200000)
    typed = _by(fl.node_forecast(m, fetch, "position", truck, truck, 12), "corrective", "Engine worn out")
    assert typed["cost"]["expected"] == pytest.approx(0.688 * 200000, rel=0.003)
    assert "typed over its corrective response" in typed["cost"]["basis"]
    # The response is a task raised by the failure: never put on dates, never in the scheduled lines.
    assert [x["owner"] for x in out["lines"]["lines"] if x["kind"] == "planned"] == ["Change engine oil"]
    _rebuilds_the_same(m)


def _deck(m, db):
    _life(db, "spindle", "Spindle bearing life", 1537, 3.04)
    # Play shows 120 h before failure; one inspection spots it 90% of the time (assumed in the plan).
    db.strategy_analyses.insert_one({"_id": "pf", "id": "pf", "name": "Bearing play P-F", "owner_id": ORG,
                                     "kind": "on_condition_interval", "results": {},
                                     "inputs": {"pf_interval": 120, "pf_unit": "hours", "detection_probability": 0.9}})
    deck = m.create_position("Cutting deck")["id"]
    m.set_operating_plan(deck, {"background": {"kind": "rate", "amount": 12, "per": "week"}}, from_="2025-01-01")
    meter = m.add_point(deck, "Hour meter", kind="counter", unit="hours")["id"]
    m.record_reading(meter, 0, on="2025-06-02")
    m.record_reading(meter, 900, on=TODAY)
    modes = []
    for k in (1, 2, 3):
        p = m.create_position(f"Spindle {k}", parent_id=deck)["id"]
        m.fit(p, new_item={"name": f"Bearing {k}"}, on="2025-06-02")
        fm = m.add_failure_mode(p, "Spindle bearing worn out")["id"]
        m.set_mode_costs(fm, failure_cost=900)
        pm.link_saved(m, db, [ORG], set(), p, "model", "spindle", [fm])
        modes.append(fm)
    m.set_trade_rate("Fitter", 75)
    grease = m.create_task(deck, "Grease deck spindles", 50, "hours")["id"]
    m.set_task_resources(grease, {"labour": [{"trade": "Fitter", "people": 1, "hours": 0.2}]})
    m.set_task_cost(grease, 18)
    insp = m.create_task(deck, "Inspect bearings for play", 100, "hours", outcome="on_condition",
                         failure_mode_ids=modes)["id"]
    m.set_task_resources(insp, {"labour": [{"trade": "Fitter", "people": 1, "hours": 0.3}]})
    m.set_task_cost(insp, 22.5)
    for fm in modes:
        m.decide_failure_mode(fm, "operational", {"outcome": "on_condition",
                                                  "evidence": {"type": "strategy_analysis", "id": "pf"}}, task_id=insp)
    # Greasing keeps the bearings on their life (assumed impact × 3 if not done; plan 4.6).
    m.set_task_support(grease, {"failure_mode_ids": [], "impact": {"form": "hazard_ratio", "k": 3},
                                "source": "assumed"})
    return deck, grease, insp, modes


def test_3_4_the_mower_deck_by_owner(setting):
    m, db, fetch = setting
    deck, grease, insp, modes = _deck(m, db)
    out = fl.node_forecast(m, fetch, "position", deck, deck, 12)
    lines = out["lines"]
    g, i = _by(out, "planned", "Grease deck spindles"), _by(out, "planned", "Inspect bearings for play")
    assert (g["times"]["expected"], g["hours"]["expected"], g["cost"]["expected"]) == (12, pytest.approx(2.4), 216)
    assert (i["times"]["expected"], i["hours"]["expected"], i["cost"]["expected"]) == (6, pytest.approx(1.8), 135)
    # A supporting task reads "keeps it on its life", never "restores 0%"; its count is unchanged.
    assert g["does"]["kind"] == "supports" and g["does"]["text"].startswith("Keeps it on its life")
    assert "92%" in i["does"]["text"]
    mode = _by(out, "failures", "Spindle bearing worn out")
    assert mode["times"]["expected"] == pytest.approx(1.65, abs=0.005) and mode["times"]["interval"] == [0, 3]
    assert mode["found_share"] == pytest.approx(0.918, abs=0.001) and len(mode["positions"]) == 3
    found = _by(out, "follow_on", "Spindle bearing worn out")
    missed = _by(out, "corrective", "Spindle bearing worn out")
    assert found["times"]["expected"] == pytest.approx(1.52, abs=0.01) and found["times"]["interval"] == [0, 3]
    assert missed["times"]["expected"] == pytest.approx(0.14, abs=0.01) and missed["times"]["interval"] == [0, 1]
    assert missed["cost"]["expected"] == pytest.approx(122, abs=1)
    assert found["cost"] is None
    assert any(x["kind"] == "no_follow_on" and "respond=found" in x["link"] for x in lines["not_counted"])
    cost = lines["totals"]["cost"]
    assert cost["by_kind"]["planned"] == pytest.approx(351) and cost["by_kind"]["corrective"] == pytest.approx(122, abs=1)
    assert not cost["known"] and cost["interval"][0] == pytest.approx(351)
    assert lines["totals"]["hours"]["expected"] == pytest.approx(4.2)
    # Spares: the like bearings, 1.65 (0 to 3), whoever's line they're on.
    assert lines["totals"]["spares"]["like_items"]["expected"] == pytest.approx(1.65, abs=0.005)
    assert lines["totals"]["spares"]["like_items"]["interval"] == [0, 3]


def test_3_4_with_its_follow_on_and_corrective_response(setting):
    """The plan's 3.4 in full, from records: found at an inspection, replace the bearing (1 h and an $85
    bearing, $160); missed, replace the spindle after it fails (4 h, $900 all in). Follow-on 1.52 finds,
    $242, 1.5 h; corrective 0.14 failures, $122, 0.5 h; the deck $715 ($351 to $1,411), 6.3 h (4.2 to 9.2)."""
    m, db, fetch = setting
    deck, _grease, _insp, modes = _deck(m, db)
    for fm in modes:
        m.set_mode_costs(fm, failure_cost=None)
        m.set_mode_response(fm, "found", name="Replace the bearing",
                            labour=[{"trade": "Fitter", "people": 1, "hours": 1}], cost=160,
                            spares=[{"name": "Spindle bearing", "qty": 1}])
        m.set_mode_response(fm, "failure", name="Replace the spindle",
                            labour=[{"trade": "Fitter", "people": 1, "hours": 4}], cost=900)
    assert m.mode_costs(modes[0])["has_check"]
    out = fl.node_forecast(m, fetch, "position", deck, deck, 12)
    lines = out["lines"]
    found = _by(out, "follow_on", "Spindle bearing worn out")
    missed = _by(out, "corrective", "Spindle bearing worn out")
    assert found["response"]["name"] == "Replace the bearing" and not found["gaps"]
    assert found["cost"]["expected"] == pytest.approx(242, abs=1) and found["hours"]["expected"] == pytest.approx(1.5, abs=0.02)
    assert found["spares"][0] == {"name": "Spindle bearing", "part_id": None, "expected": pytest.approx(1.514, abs=0.002)}
    assert missed["cost"]["expected"] == pytest.approx(122, abs=1) and missed["hours"]["expected"] == pytest.approx(0.54, abs=0.01)
    cost, hours = lines["totals"]["cost"], lines["totals"]["hours"]
    assert cost["known"] and cost["expected"] == pytest.approx(715, abs=2)
    assert cost["interval"] == [pytest.approx(351), pytest.approx(1411)]
    assert cost["by_kind"]["follow_on"] == pytest.approx(242, abs=1)
    assert hours["known"] and hours["expected"] == pytest.approx(6.3, abs=0.05)
    assert hours["interval"] == [pytest.approx(4.2), pytest.approx(9.2)]
    assert not [x for x in lines["not_counted"] if x["kind"] in ("no_follow_on", "no_response")]


def test_3_4_the_sum_with_a_follow_on():
    """With the follow-on at $160 (plan step 4), the deck's total: $715 expected, $351 to $1,411 (90%
    two-sided), from the three bearings' count (10%, 34%, 40%, 16% for 0 to 3) and 91.8% found."""
    pmf = [0.10, 0.34, 0.40, 0.16]
    got = fl._chance_sum([(pmf, 0.918, 900.0, 160.0)])
    assert 351 + got["expected"] == pytest.approx(715, abs=8)
    assert [351 + x for x in got["interval"]] == [351, 1411]
    # And the hours: 4.2 planned, 1 h a find and 4 h a failure: 4.2 to 9.2.
    hours = fl._chance_sum([(pmf, 0.918, 4.0, 1.0)])
    assert [4.2 + x for x in hours["interval"]] == [pytest.approx(4.2), pytest.approx(9.2)]


def test_gaps_are_listed_with_their_fix(setting):
    """No cost of a failure: the failures are counted, their cost is unknown and the total is the known
    total; a fitted position with no life model says its failures aren't forecast."""
    m, db, fetch = setting
    deck, _g, _i, modes = _deck(m, db)
    m.set_mode_costs(modes[0], failure_cost=None)
    belt = m.create_position("Deck belt", parent_id=deck)["id"]
    m.fit(belt, new_item={"name": "Belt 1"}, on="2025-06-02")
    out = fl.node_forecast(m, fetch, "position", deck, deck, 12)
    texts = [x["text"] for x in out["lines"]["not_counted"]]
    assert "Deck belt: no life model, so its failures are not forecast" in texts
    assert any("no response if it fails, so the hours, spares and cost to put a failure right are unknown" in t
               for t in texts)
    no_cost = [x for x in out["lines"]["lines"] if x["kind"] == "corrective" and x["cost"] is None]
    assert no_cost and no_cost[0]["times"]["expected"] > 0
    assert any("no cost of a failure" in t for t in out["lines"]["totals"]["cost"]["leaves_out"])


def test_a_package_and_a_bad_horizon(setting):
    m, db, fetch = setting
    deck, grease, insp, _modes = _deck(m, db)
    pkg = m.create_package("Deck service", position_id=deck, every=50, unit="hours", tasks=[grease])["id"]
    out = fl.node_forecast(m, fetch, "package", pkg, deck, 12)
    assert [x["owner"] for x in out["lines"]["lines"] if x["kind"] == "planned"] == ["Grease deck spindles"]
    assert out["of"] == {"kind": "package", "id": pkg, "name": "Deck service", "months": 12}
    with pytest.raises(Exception, match="12, 24, 36 or 60"):
        fl.node_forecast(m, fetch, "position", deck, deck, 7)


def test_the_route_and_the_mcp_twin(api):  # noqa: F811
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Fire pump"}).json()
    task = api.post(f"{M}/positions/{pump['id']}/tasks", json={"name": "Test the fire pump", "interval": 1,
                                        "unit": "months"}).json()
    r = api.get(f"{M}/positions/{pump['id']}/forecast-lines?months=12")
    assert r.status_code == 200, r.text
    assert [x["owner"] for x in r.json()["lines"]["lines"]] == ["Test the fire pump"]
    t = api.get(f"{M}/tasks/{task['id']}/forecast-lines")
    assert t.status_code == 200 and t.json()["of"]["kind"] == "task"
    assert api.get(f"{M}/things/{pump['id']}/forecast-lines").status_code == 404
    assert api.get(f"{M}/positions/{pump['id']}/forecast-lines?months=7").status_code >= 400
    # The MCP twin (maintenance get.forecast with months): the same lines.
    from backend.maintenance import mcp_tools

    assert "months" in mcp_tools.GET_KINDS["forecast"][1].split()


from backend.tests.test_maintenance_rcm_api import api  # noqa: E402,F401,F811
