"""What a fixed-interval task leaves the item as (Kijima restoration, every Nth a replacement), how
its interval is counted, shutdown packages, and how a repairable RBD's tree plan reads them
(restoration.py, shutdowns.py, rbd_tree_plan.py). New events only; rebuild equals live. While the
installed RePyability can't take them, the plan says so and computes with what it can."""

from datetime import date, timedelta

import pytest

from backend.maintenance import rbd_tree_plan as tp
from backend.maintenance.service import Invalid
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_rbd_tree_plan import _block_of, _graph, _same_after_rebuild, _station, db, m  # noqa: F401

KIJIMA2 = {"kind": "kijima2", "q": 0.3, "replace_every": 3}


@pytest.fixture()
def lib_now(monkeypatch):
    """The library as installed today: no restoration, no shutdowns."""
    from backend.services import repy_compat

    monkeypatch.setattr(repy_compat, "_PLAN_SUPPORTS", {"restoration": False, "shutdowns": False})


@pytest.fixture()
def lib_next(monkeypatch):
    """The next library release: it takes restoration (and shutdowns, which the app still holds back)."""
    from backend.services import repy_compat

    monkeypatch.setattr(repy_compat, "_PLAN_SUPPORTS", {"restoration": True, "shutdowns": True})


def test_restoration_is_checked_and_set_on_the_task(m):
    p = m.create_position("Pump")["id"]
    t = m.create_task(p, "Overhaul", 12, "months", outcome="fixed_interval")
    view = m.set_task_restoration(t["id"], {"kind": "kijima2", "restores": 70, "replace_every": 3})
    r = view["restoration"]
    assert r["restoration"] == {"kind": "kijima2", "q": 0.3, "replace_every": 3}
    assert r["words"] == "Restores 70% of its age (Kijima II) · every 3rd task a full replacement"
    assert r["source"] == "task"
    for bad, said in [({"kind": "kijima9", "q": 0.2}, "kind is one of"),
                      ({"kind": "kijima1", "q": 1.4}, "from 0"),
                      ({"kind": "kijima1"}, "how much"),
                      ({"kind": "kijima1", "q": 0.2, "replace_every": 1}, "from 2"),
                      ({"kind": "kijima1", "q": 0.2, "replacement_cost": 5}, "goes with replace_every"),
                      ({"kind": "as_new", "q": 0.2}, "takes no q")]:
        with pytest.raises(Invalid, match=said):
            m.set_task_restoration(t["id"], bad)
    routine = m.create_task(p, "Wipe down", 1, "weeks")
    with pytest.raises(Invalid, match="isn't a replace-or-restore task"):
        m.set_task_restoration(routine["id"], KIJIMA2)
    # Cleared: as new again.
    assert m.set_task_restoration(t["id"], None)["restoration"]["restoration"] is None
    _same_after_rebuild(m)


def test_decisions_that_disagree_take_the_least_restoring_and_say_so(m):
    p = m.create_position("Gearbox")["id"]
    wear = m.add_failure_mode(p, "Gear wear")["id"]
    pit = m.add_failure_mode(p, "Pitting")["id"]
    t = m.create_task(p, "Overhaul", 12, "months", outcome="fixed_interval", failure_mode_ids=[wear, pit])
    m.set_task_restoration(t["id"], {"kind": "kijima2", "q": 0.3})
    m.set_task_restoration(t["id"], {"kind": "kijima1", "q": 0.5}, failure_mode_id=pit)
    r = m._task_view(m._get(t["id"], "Task"))["restoration"]
    assert r["restoration"] == {"kind": "kijima1", "q": 0.5}  # less restoring: never an average
    assert r["source"] == "decision" and "disagree" in r["conflict"]
    assert {x["failure_mode_id"]: x["own"] for x in r["by_mode"]} == {wear: False, pit: True}
    # Set on the task as a whole: for every mode again.
    m.set_task_restoration(t["id"], {"kind": "kijima2", "q": 0.3})
    r = m._task_view(m._get(t["id"], "Task"))["restoration"]
    assert r["conflict"] is None and r["source"] == "task"
    with pytest.raises(Invalid, match="doesn't serve"):
        m.set_task_restoration(t["id"], KIJIMA2, failure_mode_id=m.add_failure_mode(p, "Other")["id"])
    _same_after_rebuild(m)


def test_an_rcm_decision_sets_its_tasks_restoration(m):
    p = m.create_position("Fan")["id"]
    fm = m.add_failure_mode(p, "Bearing wear", consequence="operational")["id"]
    m.decide_failure_mode(fm, decision={"outcome": "fixed_interval", "task": "Overhaul the fan", "interval": 6,
                                        "interval_unit": "months", "restoration": {"kind": "kijima1", "q": 0.4}})
    task = m._tasks_on(p)[0]
    assert task["restorations"] == {fm: {"kind": "kijima1", "q": 0.4}}
    with pytest.raises(Invalid, match="restoration factor"):
        m.decide_failure_mode(fm, decision={"outcome": "fixed_interval", "task": "Overhaul the fan", "interval": 6,
                                            "interval_unit": "months", "restoration": {"kind": "kijima1", "q": 3}})
    _same_after_rebuild(m)


def test_basis_and_older_than(m):
    p = m.create_position("Compressor")["id"]
    t = m.create_task(p, "Service", 6, "months", outcome="fixed_interval")
    assert m._task_view(m._get(t["id"], "Task"))["basis"] == "calendar"
    assert m.set_task_basis(t["id"], "operating")["basis"] == "operating"
    by_meter = m.create_task(p, "Change oil", 500, "hours", outcome="fixed_interval")
    assert m._task_view(m._get(by_meter["id"], "Task"))["basis"] == "operating"
    with pytest.raises(Invalid, match="counted on a meter"):
        m.set_task_basis(by_meter["id"], "operating")
    assert m.set_task_older_than(t["id"], {"value": 18, "unit": "months"})["older_than"] == {"value": 18,
                                                                                              "unit": "months"}
    with pytest.raises(Invalid, match="unit is one of"):
        m.set_task_older_than(t["id"], {"value": 18, "unit": "fortnights"})
    _same_after_rebuild(m)


def test_a_shutdown_package(m):
    plant = m.create_position("Line 1")["id"]
    a = m.create_position("Crusher", parent_id=plant)["id"]
    t = m.create_task(a, "Reline", 12, "months", outcome="fixed_interval")
    pkg = m.create_package("Annual shut", position_id=plant, every=12, unit="months", tasks=[t["id"]])
    out = m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "cost": 15000, "scope": [a]})
    assert out["shutdown"]["duration_hours"] == 72 and out["shutdown"]["scope"] == [{"id": a, "name": "Crusher"}]
    # The whole position is the default (stored as no scope).
    assert m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "scope": [plant]})["shutdown"]["scope"] is None
    other = m.create_position("Elsewhere")["id"]
    with pytest.raises(Invalid, match="isn't Line 1 or inside it"):
        m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "scope": [other]})
    with pytest.raises(Invalid, match="how long"):
        m.set_package_shutdown(pkg["id"], {"cost": 5})
    with pytest.raises(Invalid, match="overlap"):
        m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "dates": ["2027-01-01", "2027-01-02"]})
    shuts = m.shutdowns_for(plant)
    assert [s["package"]["id"] for s in shuts] == [pkg["id"]] and shuts[0]["tasks"] == [t["id"]]
    assert m.set_package_shutdown(pkg["id"], None)["shutdown"] is None
    assert m.shutdowns_for(plant) == []
    _same_after_rebuild(m)


def test_the_plan_says_what_waits_for_the_library_and_computes_with_what_it_can(m, db, lib_now):
    plant, a, b, rbd = _station(m, db)
    t = m.create_task(a, "Overhaul", 12, "months", outcome="fixed_interval")
    m.set_task_cost(t["id"], 900)
    m.set_task_restoration(t["id"], KIJIMA2)
    tb = m.create_task(b, "Replace", 24, "months", outcome="fixed_interval")
    m.set_task_older_than(tb["id"], {"value": 18, "unit": "months"})
    pkg = m.create_package("Annual shut", position_id=plant, every=12, unit="months", tasks=[tb["id"]])
    m.set_package_shutdown(pkg["id"], {"duration_hours": 72, "cost": 15000})
    graph = _graph(db, rbd)
    plans = tp.plans_for_graph(m, rbd, graph)
    assert plans["supports"] == {"restoration": ["as_new"], "shutdowns": False}
    ra = plans["blocks"][_block_of(graph, "Pump A")["id"]]
    assert ra["restoration"]["kind"] == "kijima2" and ra["restoration"]["q"] == 0.3
    assert any(tp.PENDING in x and "calculated as new" in x for x in ra["pending"])
    assert "restoration" not in ra["plan"]  # computed as new, never silently
    merged = tp.merge(_block_of(graph, "Pump A")["data"], ra)
    assert "restoration" not in merged["preventive"] and merged["preventive"]["interval"] == 12 * 730.5
    rb = plans["blocks"][_block_of(graph, "Pump B")["id"]]
    assert any("Done at the shutdown “Annual shut”, only if older than 18 months" in x for x in rb["pending"])
    assert "shutdown" not in rb["plan"]
    [shut] = plans["shutdowns"]
    assert shut["pending"] == tp.PENDING and shut["spec"]["period"] == 12 * 730.5
    assert shut["spec"]["duration"] == 72 and shut["spec"]["scope"] is None and shut["spec"]["cost"] == 15000
    assert 0 <= shut["spec"]["offset"] < shut["spec"]["period"]
    assert [x["label"] for x in shut["blocks"]] == ["Pump B"]
    assert "shutdowns" not in tp.apply(graph, plans)
    # A change to what it leaves the block as is a new version of the task, even while pending.
    before = tp.fingerprint(plans)
    m.set_task_restoration(t["id"], {"kind": "kijima2", "q": 0.5})
    assert tp.fingerprint(tp.plans_for_graph(m, rbd, graph))[t["id"]] != before[t["id"]]


def test_with_the_next_library_the_plan_is_in_its_shape(m, db, lib_next):
    plant, a, b, rbd = _station(m, db)
    t = m.create_task(a, "Overhaul", 12, "months", outcome="fixed_interval")
    m.set_task_restoration(t["id"], KIJIMA2)  # no replacement cost: 0, flagged
    graph = _graph(db, rbd)
    plans = tp.plans_for_graph(m, rbd, graph)
    assert plans["supports"]["restoration"] == ["as_new", "kijima1", "kijima2"]
    assert plans["supports"]["shutdowns"] is False  # the app holds them back until the builder takes them
    ra = plans["blocks"][_block_of(graph, "Pump A")["id"]]
    assert ra["pending"] == [] and any("No replacement cost" in f for f in ra["flags"])
    pm = tp.merge(_block_of(graph, "Pump A")["data"], ra)["preventive"]
    assert pm["restoration"] == {"model": "kijima2", "q": 0.3}
    assert pm["replace_every"] == 3 and pm["replacement_cost"] == 0.0
    from backend.services import rbd_maintenance

    spec = rbd_maintenance.preventive_spec({"preventive": pm}, "Pump A")
    assert spec["restoration"] == {"model": "kijima2", "q": 0.3} and spec["replace_every"] == 3


def test_operating_basis_goes_through_the_duty_and_a_meter_proposes_one(m, db, lib_now):
    _, a, _, rbd = _station(m, db)
    t = m.create_task(a, "Service", 6, "months", outcome="fixed_interval")
    m.set_task_basis(t["id"], "operating")
    meter = m.add_point(a, "Run hours", kind="counter", unit="hours")["id"]
    start = date.fromisoformat(m.today()) - timedelta(days=100)
    m.record_reading(meter, 1000, on=start.isoformat())
    m.record_reading(meter, 1000 + 100 * 6, on=(start + timedelta(days=100)).isoformat())  # 6 h a day
    graph = _graph(db, rbd)
    ra = tp.plans_for_graph(m, rbd, graph)["blocks"][_block_of(graph, "Pump A")["id"]]
    assert ra["plan"]["interval"] is None and ra["plan"]["operating_interval"] == 6 * 730.5
    prop = ra["duty_proposal"]
    assert prop["duty"] == 0.25 and prop["words"] == "Runs 25% of the time" and prop["point"]["id"] == meter


def test_new_task_fields_over_rest_and_mcp_parity_args(env):  # noqa: F811
    from backend.maintenance import mcp_tools

    _, table = mcp_tools.TOOL_TABLES["maintenance"]
    assert {"restoration", "basis", "older_than"} <= set(table["tasks.update"][1].split())
    assert "shutdown" in table["packages.create"][1].split() and "shutdown" in table["packages.update"][1].split()
