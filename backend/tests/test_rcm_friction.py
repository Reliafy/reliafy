"""RCM friction fixes (Nov 2026): the same task on identical positions (task twins, offered after
an interval change), and one failure mode's own restoration shown and cleared from the RCM."""

from backend.tests.test_explorer_redundancy import _ok, client  # noqa: F401
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_rbd_tree_plan import _same_after_rebuild, db, m  # noqa: F401


def test_twins_are_the_same_task_on_positions_of_the_same_class(m):
    a = m.create_position("Pump A", position_class="Raw water pump")["id"]
    b = m.create_position("Pump B", position_class="raw water pump")["id"]
    c = m.create_position("Fan", position_class="Fan")["id"]
    ta = m.create_task(a, "Replace the seal", 14800, "hours", outcome="fixed_interval")
    tb = m.create_task(b, "Replace  the seal", 12000, "hours", outcome="fixed_interval")
    m.create_task(b, "Grease", 3, "months")
    m.create_task(c, "Replace the seal", 12000, "hours")
    out = m.task_twins(ta["id"])
    assert [t["id"] for t in out["twins"]] == [tb["id"]]
    assert out["twins"][0]["position"]["name"] == "Pump B" and out["twins"][0]["same"] is False
    m.update_task(tb["id"], interval=14800)
    assert m.task_twins(ta["id"])["twins"][0]["same"] is True


def test_twins_without_a_class_are_siblings_named_alike(m):
    st = m.create_position("Station")["id"]
    p1 = m.create_position("Pump 1", parent_id=st)["id"]
    p2 = m.create_position("Pump 2", parent_id=st)["id"]
    m.create_position("Pumphouse", parent_id=st)
    other = m.create_position("Elsewhere")["id"]
    p3 = m.create_position("Pump 3", parent_id=other)["id"]
    t1 = m.create_task(p1, "Overhaul", 2, "years")
    t2 = m.create_task(p2, "Overhaul", 3, "years")
    m.create_task(p3, "Overhaul", 3, "years")  # another parent: not a twin
    assert [t["id"] for t in m.task_twins(t1["id"])["twins"]] == [t2["id"]]
    assert m._name_stem("Pump") == "pump" and m._name_stem("Pump-B") == "pump" and m._name_stem("Pump 12") == "pump"


def test_the_rcm_lists_a_modes_own_restoration(m):
    p = m.create_position("Gearbox")["id"]
    fm = m.add_failure_mode(p, "Gear wear", consequence="operational")["id"]
    m.decide_failure_mode(fm, "operational", {"outcome": "fixed_interval", "task": "Overhaul", "interval": 12,
                                              "interval_unit": "months"})
    t = m.rcm_mode(fm)["decision"]["tasks"][0]["id"]
    m.set_task_restoration(t, {"kind": "kijima2", "q": 0.3})
    m.set_task_restoration(t, {"kind": "kijima1", "q": 0.5}, failure_mode_id=fm)
    mine = m.rcm_mode(fm)["decision"]["tasks"][0]
    assert mine["restoration"] == {"kind": "kijima2", "q": 0.3}
    assert mine["restorations"] == {fm: {"kind": "kijima1", "q": 0.5}}
    _same_after_rebuild(m)


def test_rest_clears_one_modes_own_restoration(client):
    p = _ok(client.post("/api/maintenance/positions", json={"name": "Gearbox"}))["id"]
    fm = _ok(client.post(f"/api/maintenance/positions/{p}/failure-modes", json={"text": "Gear wear"}))["id"]
    t = _ok(client.post(f"/api/maintenance/positions/{p}/tasks",
                        json={"name": "Overhaul", "interval": 12, "unit": "months", "outcome": "fixed_interval",
                              "failure_mode_ids": [fm]}))["id"]
    _ok(client.patch(f"/api/maintenance/tasks/{t}", json={"restoration": {"kind": "kijima2", "q": 0.3}}))
    view = _ok(client.patch(f"/api/maintenance/tasks/{t}",
                            json={"restoration": {"kind": "kijima1", "q": 0.5, "failure_mode_id": fm}}))
    assert [x["own"] for x in view["restoration"]["by_mode"]] == [True]
    # Only the failure mode's id: its own is cleared, the task's stands for it again.
    view = _ok(client.patch(f"/api/maintenance/tasks/{t}", json={"restoration": {"failure_mode_id": fm}}))
    assert [x["own"] for x in view["restoration"]["by_mode"]] == [False]
    assert view["restoration"]["restoration"] == {"kind": "kijima2", "q": 0.3}
    twins = _ok(client.get(f"/api/maintenance/tasks/{t}/twins"))
    assert twins["twins"] == [] and twins["task"]["id"] == t
