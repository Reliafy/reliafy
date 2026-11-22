"""What a failure costs, and the forecast's cost split into planned and unplanned (Nov 2026).

A failure's cost (its repair), its downtime and the cost of an hour down live on the failure mode,
else on the position's class (failure_costs.py). The forecast charges each expected failure that
figure, and splits the planned cost into labour and parts from each task's LSA lines.

The hand check is the mower of test_forecast_counts_maintenance (checks.json from the case's
generator): a year of 600 operating hours in the long run, failures at $900 a spark plug, $700 a
drive belt and $900 a spindle bearing, 4 h out of use a breakdown:

* the maker's 25 h plan: 1.954 plug + 1.311 spindle failures, $2,938 a year unplanned;
* replacing the plugs every 100 h: 0.2419 plug + 1.311 spindle failures, $1,398 a year (the hand
  check's $1,430 adds $33 of oil and air past their limits, which have no life in the forecast).
"""

import pytest

from backend.maintenance import position_forecast as pf
from backend.maintenance.service import Invalid
from backend.tests.test_forecast_counts_maintenance import _mower, setting  # noqa: F401
from backend.tests.test_maintenance_forecast_engine import _rebuilds_the_same
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

COSTS = {"Spark plug electrode worn": 900.0, "Drive belt cracked and breaks": 700.0, "Spindle bearing worn out": 900.0}
HAND_UNPLANNED = {25: 1.9538564895065913 * 900 + 1.3109144114378204 * 900,
                  50: 0.24187372132162593 * 900 + 1.3109144114378204 * 900}
HAND_BREAKDOWNS = {25: 1.9538564895065913 + 1.3109144114378204, 50: 0.24187372132162593 + 1.3109144114378204}


def _costed(m, top):
    """The generator's failure costs: on each failure mode, and on the class of the two spindle
    positions that have no failure mode of their own (a life for every failure there)."""
    for fm in m._modes_on(top):
        m.set_mode_costs(fm["id"], failure_cost=COSTS[fm["text"]], downtime_hours=4)
    for pos in m.s.inn(m.org, top, "PART_OF"):
        m.update_position(pos["id"], position_class="Deck spindle bearing")
    m.set_class_costs("Deck spindle bearing", failure_cost=900, downtime_hours=4)


def _per_600(fc, key, years=slice(4, 10)):
    rows = fc["rows"][years]
    return sum(r[key] or 0 for r in rows) / sum(r["hours"] for r in rows) * 600


@pytest.mark.parametrize("plan", [25, 50])
def test_the_unplanned_cost_a_year_matches_the_hand_check(setting, plan):  # noqa: F811
    m, db, fetch = setting
    top = _mower(m, db, f"Mower on the {plan} h plan", plan)
    _costed(m, top)
    fc = pf.position_forecast(m, top, root=top, period="year", periods=10, fetch=fetch)
    assert _per_600(fc, "failures") == pytest.approx(HAND_BREAKDOWNS[plan], rel=0.04)
    assert _per_600(fc, "unplanned_cost") == pytest.approx(HAND_UNPLANNED[plan], rel=0.04)
    # 4 h out of use a breakdown, at no cost an hour (none set): hours, no dollars.
    assert _per_600(fc, "downtime_hours") == pytest.approx(4 * HAND_BREAKDOWNS[plan], rel=0.04)
    t = fc["totals"]
    assert t["downtime_cost"] == 0 and t["total_complete"]
    assert t["total_cost"] == pytest.approx(t["planned_cost"] + t["unplanned_cost"], abs=0.02)
    assert "Unplanned: expected failures" in fc["cost_basis"]["unplanned"]
    spindle = next(r for r in fc["models"] if r["position"]["id"] != top)
    assert spindle["cost_per_failure"] == 900 and "Deck spindle bearing class's failure cost" in spindle["rests_on"]
    plug = next(r for r in fc["models"] if r["name"] == "Spark plug life")
    assert "$900 (the failure mode's)" in plug["rests_on"] and plug["downtime_hours_each"] == 4
    assert "unplanned)" in fc["answer"]
    _rebuilds_the_same(m)


def test_a_cost_an_hour_down_is_charged_on_each_failure(setting):  # noqa: F811
    m, db, fetch = setting
    top = _mower(m, db, "Mower", 50)
    _costed(m, top)
    before = pf.position_forecast(m, top, root=top, period="year", periods=2, fetch=fetch)["totals"]
    m.set_class_costs("Deck spindle bearing", downtime_rate=50)
    plug = next(fm for fm in m._modes_on(top) if fm["text"].startswith("Spark plug"))
    m.set_mode_costs(plug["id"], downtime_rate=50)
    after = pf.position_forecast(m, top, root=top, period="year", periods=2, fetch=fetch)
    charged = [r for r in after["models"] if r["downtime_rate"] == 50]
    assert {r["name"] for r in charged} == {"Spark plug life", "Spindle bearing life"}
    extra = sum(r["expected_failures"] * 4 * 50 for r in charged)
    assert after["totals"]["unplanned_cost"] == pytest.approx(before["unplanned_cost"] + extra, rel=1e-3)
    assert after["totals"]["downtime_cost"] == pytest.approx(extra, rel=1e-3)


def test_the_planned_cost_splits_into_labour_and_parts_from_the_lsa(setting):  # noqa: F811
    m, db, fetch = setting
    top = _mower(m, db, "Mower", 50)
    m.set_trade_rate("Mechanic", 90)
    plugs = next(t for t in m._tasks_on(top) if t["name"] == "Replace spark plugs")
    m.set_task_resources(plugs["id"], {"labour": [{"trade": "Mechanic", "people": 1, "hours": 0.3}],
                                       "consumables": [{"name": "Spark plugs, a pair", "qty": 1, "unit": "each", "cost": 22}]})
    grease = next(t for t in m._tasks_on(top) if t["name"] == "Grease deck spindles")
    m.set_task_cost(grease["id"], 21)   # typed: no LSA lines, all "other"
    fc = pf.position_forecast(m, top, root=top, period="year", periods=2, fetch=fetch)
    by = {t["name"]: t for t in fc["tasks"]}
    n_plugs, n_grease = by["Replace spark plugs"]["count"], by["Grease deck spindles"]["count"]
    assert by["Replace spark plugs"]["labour_cost_each"] == 27 and by["Replace spark plugs"]["materials_cost_each"] == 22
    t = fc["totals"]
    assert t["labour_cost"] == pytest.approx(27 * n_plugs) and t["materials_cost"] == pytest.approx(22 * n_plugs)
    assert t["other_planned_cost"] == pytest.approx(21 * n_grease)
    assert t["planned_cost"] == pytest.approx(49 * n_plugs + 21 * n_grease)
    for r in fc["rows"]:
        assert r["labour_cost"] + r["materials_cost"] + r["other_planned_cost"] == pytest.approx(r["planned_cost"],
                                                                                                abs=0.02)


def test_the_mode_overrides_the_class_figure_by_figure(setting):  # noqa: F811
    m, _db, _fetch = setting
    pump = m.create_position("Pump")["id"]
    m.update_position(pump, position_class="Pumps")
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    m.set_class_costs("Pumps", failure_cost=500, downtime_hours=8, downtime_rate=100)
    pos = m._get(pump, "Position")
    c = m.failure_consequence(pos, [seal])
    assert c["per_failure"] == 500 + 8 * 100 and c["sources"]["failure_cost"] == "the Pumps class's failure cost"
    m.set_mode_costs(seal, failure_cost=900, downtime_hours=2)
    c = m.failure_consequence(pos, [seal])
    assert (c["failure_cost"], c["downtime_hours"], c["downtime_rate"]) == (900, 2, 100)
    assert c["per_failure"] == 1100 and c["sources"]["downtime_rate"] == "the Pumps class's"
    assert m.mode_costs(seal)["own"] == {"failure_cost": 900, "downtime_hours": 2, "downtime_rate": None}
    m.set_mode_costs(seal, failure_cost=None)
    assert m.failure_consequence(pos, [seal])["failure_cost"] == 500
    # A life for two modes: the costliest, said.
    gland = m.add_failure_mode(pump, "Gland worn")["id"]
    m.set_mode_costs(gland, failure_cost=3000)
    both = m.failure_consequence(pos, [seal, gland])
    assert both["mode"]["id"] == gland and "the costliest" in both["text"]
    with pytest.raises(Invalid):
        m.set_mode_costs(seal, failure_cost=-1)
    with pytest.raises(Invalid):
        m.set_mode_costs(seal, downtime_hours="lots")
    _rebuilds_the_same(m)


def test_a_greasing_task_is_assumed_to_restore_none_until_told(setting):  # noqa: F811
    m, _db, _fetch = setting
    pos = m.create_position("Fan")["id"]
    bearing = m.add_failure_mode(pos, "Bearing worn")["id"]
    m.decide_failure_mode(bearing, "operational", {"outcome": "fixed_interval", "task": "Grease the bearing",
                                                   "interval": 3, "interval_unit": "months"})
    task = next(t for t in m._tasks_on(pos) if t["name"] == "Grease the bearing")
    r = m._task_view(m._get(task["id"], "Task"))["restoration"]
    assert r["source"] == "assumed" and r["restoration"] == {"kind": "kijima1", "q": 1.0} and "assumed" in r["words"]
    m.set_task_restoration(task["id"], {"kind": "as_new"})
    r = m._task_view(m._get(task["id"], "Task"))["restoration"]
    assert r["source"] == "task" and r["restoration"] is None
    # A replacement is as new, as before.
    m.decide_failure_mode(bearing, "operational", {"outcome": "fixed_interval", "task": "Replace the bearing",
                                                   "interval": 2, "interval_unit": "years"})
    task = next(t for t in m._tasks_on(pos) if t["name"] == "Replace the bearing")
    assert m._task_view(m._get(task["id"], "Task"))["restoration"]["restoration"] is None


def test_the_forecast_lists_what_to_enter_with_links(setting):  # noqa: F811
    m, db, fetch = setting
    top = _mower(m, db, "Mower", 25)
    fc = pf.position_forecast(m, top, root=top, period="year", periods=1, fetch=fetch)
    p = fc["prompts"]
    # Every failure mode lacks a cost, and the two spindles' lives with no mode and no class.
    texts = {x["mode"]["text"] for x in p["no_failure_cost"] if x["mode"]}
    assert texts == set(COSTS) and all(x["counted"] for x in p["no_failure_cost"])
    plug = next(x for x in p["no_failure_cost"] if x["mode"] and x["mode"]["text"].startswith("Spark"))
    assert plug["link"].startswith("/asset-register/explorer?") and f"sel={plug['mode']['id']}" in plug["link"] \
        and "tab=rcm" in plug["link"] and f"root={top}" in plug["link"]
    assert sum(1 for x in p["no_failure_cost"] if x["mode"] is None) == 2
    assert "no_failure_cost" in {s["kind"] for s in fc["states"]}
    # The plug inspection has no P-F interval; greasing restores none (set so here).
    assert [x["task"]["name"] for x in p["no_pf"]] == ["Inspect spark plug"]
    effect = {x["task"]["name"]: x for x in p["no_effect"]}
    assert {"Inspect spark plug", "Grease deck spindles"} <= set(effect)
    assert "Check drive belt" not in effect   # counted: its P-F calculation is linked
    assert "mtask=" in effect["Grease deck spindles"]["link"] and "tab=maintenance" in effect["Grease deck spindles"]["link"]
    _costed(m, top)
    fc = pf.position_forecast(m, top, root=top, period="year", periods=1, fetch=fetch)
    assert fc["prompts"]["no_failure_cost"] == [] and "no_failure_cost" not in {s["kind"] for s in fc["states"]}


def test_costs_through_the_rest_routes(api, monkeypatch):  # noqa: F811
    from backend.routers import maintenance as router
    from backend.tests.test_maintenance_forecast_engine import _m
    from backend.tests.test_maintenance_rcm_api import UID

    m = _m(UID, router._store)
    pump = m.create_position("Pump")["id"]
    m.update_position(pump, position_class="Pumps")
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    r = api.patch(f"/api/maintenance/failure-modes/{seal}", json={"failure_cost": 1200, "downtime_hours": 6})
    assert r.status_code == 200, r.text
    assert r.json()["costs"]["own"] == {"failure_cost": 1200, "downtime_hours": 6, "downtime_rate": None}
    r = api.put("/api/maintenance/classes/costs", json={"position_class": "Pumps", "downtime_rate": 75})
    assert r.status_code == 200, r.text
    assert r.json()["costs"]["downtime_rate"] == 75
    got = api.get(f"/api/maintenance/failure-modes/{seal}/costs").json()
    assert got["used"]["per_failure"] == 1200 + 6 * 75 and got["used"]["sources"]["downtime_rate"] == "the Pumps class's"
    r = api.patch(f"/api/maintenance/failure-modes/{seal}", json={"failure_cost": None})
    assert r.json()["costs"]["own"]["failure_cost"] is None
    bad = api.patch(f"/api/maintenance/failure-modes/{seal}", json={"downtime_hours": -2})
    assert bad.status_code == 422 and "downtime per failure" in bad.text


def test_costs_over_mcp(env):  # noqa: F811
    """failure_modes.update and reliability.set_class_costs take the figures; the forecast tool reads them."""
    from backend.tests.test_maintenance_mcp import _do, _get, _ok, _session

    async def flow(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Pump", position_class="Pumps"))["id"]
        mode = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pos, text="Seal leaks"))["id"]
        set_ = _ok(await _do(client, "maintenance", "failure_modes.update", failure_mode_id=mode, failure_cost=1500,
                             downtime_hours=3))
        cls = _ok(await _do(client, "maintenance", "reliability.set_class_costs", position_class="Pumps",
                            downtime_rate=40))
        cleared = _ok(await _do(client, "maintenance", "failure_modes.update", failure_mode_id=mode,
                                clear=["downtime_hours"]))
        fc = _ok(await _get(client, "forecast", pos))
        return set_, cls, cleared, fc

    set_, cls, cleared, fc = _session(env["token"], flow)
    assert set_["costs"]["used"]["per_failure"] == 1500
    assert cls["costs"]["downtime_rate"] == 40
    assert cleared["costs"]["own"]["downtime_hours"] is None
    assert "prompts" in fc and fc["totals"]["total_cost"] == 0
