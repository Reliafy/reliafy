"""Supporting-task what-ifs (forecast plan step 7, Nov 2026; forecast-rules 4.5 and 4.6): drop or stretch a
supporting task and the supported life runs at the averaged hazard ratio, the task's own line changes, and
the task's worth is the failures it avoids for its cost. The plan's figures:

* 4.5, the oil change → engine (hazard × 2.5 if not changed; reference 250 h): as planned 0.688 failures;
  stretched to 500 h, × 1.75 on average, 0.957 (a full simulation gives 0.952); dropped, × 2.5, 1.139
  (simulated 1.126). The oil changes avoid about 0.45 failures, some $81,000 a year, for $16,313.
* 4.6, greasing → three spindle bearings with the inspection in place (× 3 if not greased; 50 h): as
  planned 1.65 problems; stretched to 100 h, × 2 on average, 2.45 (simulated 2.44).
"""

from datetime import datetime, timezone

import mongomock
import pytest

from backend.maintenance import forecast_lines as fl
from backend.maintenance import position_models as pm
from backend.maintenance import support_whatif as sw
from backend.maintenance.service import Invalid
from backend.tests.test_forecast_lines import _deck
from backend.tests.test_maintenance_forecast_engine import _m, _rebuilds_the_same

TODAY = "2026-11-24"
ORG = "org-forecast-lines"


@pytest.fixture
def setting(monkeypatch):
    from backend.services import time_zones

    monkeypatch.setattr(time_zones, "_now", lambda: datetime.fromisoformat(TODAY).replace(hour=8, tzinfo=timezone.utc))
    m = _m(ORG)
    m.today = lambda: TODAY
    db = mongomock.MongoClient()["support_whatif"]
    return m, db, pm.fetcher(db, [ORG])


def _truck(m, db):
    db.models.insert_one({"_id": "engine", "id": "engine", "name": "Engine life", "kind": "distribution",
                          "distribution_id": "weibull", "dataset_id": "ds", "spec": {"unit": "hours"},
                          "status": "ready", "owner_id": ORG, "created_at": datetime(2026, 1, 1),
                          "updated_at": datetime(2026, 1, 1),
                          "results": {"distribution_id": "weibull", "unit": "hours",
                                      "params": [{"name": "alpha", "value": 14000}, {"name": "beta", "value": 2.2}]}})
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
    m.set_task_cost(oil, 562.5)
    m.set_task_support(oil, {"failure_mode_ids": [], "impact": {"form": "hazard_ratio", "k": 2.5}})
    return truck, oil


def _engine(lines):
    return sum(x["times"]["expected"] for x in lines["lines"] if x["kind"] == "corrective")


def test_the_averaged_hazard_ratio():
    support = {"impact": {"k": 2.5}, "reference": {"value": 250}, "grace": 0}
    assert sw.multiplier(support, 250, None)["mult"] == 1.0
    assert sw.multiplier(support, 250, {"interval": 500})["mult"] == pytest.approx(1.75)
    assert sw.multiplier(support, 250, {"drop": True})["mult"] == 2.5
    short = sw.multiplier(support, 250, {"interval": 125})
    assert short["mult"] == 1.0 and "no modelled benefit" in short["words"]
    # Grace: overdue only past 250 h × 1.2 = 300 h. Stretched to 500 h: overdue 40% of the time.
    assert sw.multiplier({**support, "grace": 20}, 250, {"interval": 500})["mult"] == pytest.approx(1 + 1.5 * 0.4)
    # No modelled impact: nothing changes, said so.
    assert sw.multiplier({"reference": {"value": 250}}, 250, {"drop": True})["mult"] == 1.0
    # The plan itself past its reference: the impact applies as recorded.
    assert sw.multiplier(support, 500, None)["mult"] == pytest.approx(1.75)


def test_4_5_the_oil_change_stretched_and_dropped(setting):
    m, db, fetch = setting
    truck, oil = _truck(m, db)
    out = fl.node_forecast(m, fetch, "position", truck, truck, 12, whatif={oil: {"interval": 500}})
    assert _engine(out["lines"]) == pytest.approx(0.688, abs=0.002)
    assert _engine(out["whatif"]["lines"]) == pytest.approx(0.957, abs=0.003)
    ratio = out["whatif"]["ratios"][0]
    assert ratio["mult"] == pytest.approx(1.75) and not ratio["approximate"]
    change = next(x for x in out["whatif"]["lines"]["lines"] if x.get("task_id") == oil)
    assert change["times"]["expected"] == 14  # every 500 h over 7,300 h
    # Dropped: × 2.5 the whole period, and the oil changes' worth.
    dropped = fl.node_forecast(m, fetch, "position", truck, truck, 12, whatif={oil: {"drop": True}})
    assert _engine(dropped["whatif"]["lines"]) == pytest.approx(1.139, abs=0.003)
    assert not any(x.get("task_id") == oil for x in dropped["whatif"]["lines"]["lines"])
    w = out["lines"]["worth"][0]
    assert w["task_id"] == oil and w["costs"] == pytest.approx(16312.5)
    assert w["avoids_failures"] == pytest.approx(0.451, abs=0.005)
    assert w["avoids_cost"] == pytest.approx(0.451 * 180000, rel=0.01) and w["words"].startswith("Worth: avoids about $81")
    assert next(x for x in out["lines"]["lines"] if x.get("task_id") == oil)["worth"]["task_id"] == oil
    # Nothing is written: the plan as recorded reads the same after.
    again = fl.node_forecast(m, fetch, "position", truck, truck, 12)
    assert _engine(again["lines"]) == pytest.approx(0.688, abs=0.002) and "whatif" not in again
    _rebuilds_the_same(m)
    with pytest.raises(Invalid, match="supporting task"):
        fl.node_forecast(m, fetch, "position", truck, truck, 12, whatif={"nope": {"drop": True}})


def test_4_5_the_plan_past_its_reference_applies_the_impact(setting):
    """The oil change's own interval made 500 h while the life assumes 250 h: the plan as recorded runs
    the engine at × 1.75 (rule 2: stretching an interval never silently changes nothing)."""
    m, db, fetch = setting
    truck, oil = _truck(m, db)
    m.update_task(oil, interval=500)
    out = fl.node_forecast(m, fetch, "position", truck, truck, 12)
    assert _engine(out["lines"]) == pytest.approx(0.957, abs=0.003)
    assert out["models"][0]["support_hr"]["mult"] == pytest.approx(1.75)


def test_4_6_greasing_stretched_with_the_inspection(setting):
    m, db, fetch = setting
    deck, grease, _insp, _modes = _deck(m, db)
    out = fl.node_forecast(m, fetch, "position", deck, deck, 12, whatif={grease: {"interval": 100}})
    problems = sum(x["times"]["expected"] for x in out["whatif"]["lines"]["lines"] if x["kind"] == "failures")
    assert problems == pytest.approx(2.45, abs=0.02)
    assert next(x for x in out["whatif"]["lines"]["lines"] if x.get("task_id") == grease)["times"]["expected"] == 6


def test_the_route_takes_a_what_if(api):  # noqa: F811
    import json

    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump"}).json()
    task = api.post(f"{M}/positions/{pump['id']}/tasks", json={"name": "Grease", "interval": 50, "unit": "hours"}).json()
    assert api.patch(f"{M}/tasks/{task['id']}", json={"support": {"impact": {"form": "hazard_ratio", "k": 2}}}).status_code == 200
    plan = json.dumps({task["id"]: {"drop": True}})
    r = api.get(f"{M}/positions/{pump['id']}/forecast-lines", params={"whatif": plan})
    assert r.status_code == 200, r.text
    assert r.json()["whatif"]["plan"] == {task["id"]: {"drop": True}}
    assert not [x for x in r.json()["whatif"]["lines"]["lines"] if x.get("task_id") == task["id"]]
    assert api.get(f"{M}/positions/{pump['id']}/forecast-lines", params={"whatif": "{nope"}).status_code == 422
    from backend.maintenance import mcp_tools

    assert "whatif" in mcp_tools.GET_KINDS["forecast"][1].split()


from backend.tests.test_maintenance_rcm_api import api  # noqa: E402,F401,F811
