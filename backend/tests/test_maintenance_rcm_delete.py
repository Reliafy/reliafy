"""Deleting an RCM row with cascade takes everything under it (standards,
functional failures, failure modes, their tasks and links), counts it first with
dry_run, and comes back as a unit with restore_rcm (undo_delete over MCP). The
plain removes keep their old meaning. A rebuilt graph is the same as the live one
at every step."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _ok, _session, env  # noqa: F401

ORG = "user-rcm-delete"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _pump(m):
    """Pump A performs "Pump water" with two standards; "Low flow" breaches the
    first, "No flow" none; modes under each and one placed directly under the
    function (the FME(C)A's way); tasks (one shared with a mode on Pump B's own
    position elsewhere); a cause link from the Plant's failure to "No flow"."""
    plant = m.create_position("Plant")["id"]
    pump = m.create_position("Pump A", parent_id=plant)["id"]
    fn = m.add_function(pump, "Pump water")["id"]
    flow = m.add_standard(fn, "At least 40 L/s")["id"]
    pressure = m.add_standard(fn, "5.5 to 6.5 bar")["id"]
    low = m.add_functional_failure(fn, "Low flow", standard_id=flow)["id"]
    none = m.add_functional_failure(fn, "No flow")["id"]
    impeller = m.add_failure_mode(pump, "Impeller worn", functional_failure_id=low)["id"]
    seal = m.add_failure_mode(pump, "Seal leaks", functional_failure_id=low)["id"]
    shaft = m.add_failure_mode(pump, "Shaft breaks", functional_failure_id=none)["id"]
    direct = m.add_failure_mode(pump, "Coupling slips", function_id=fn)["id"]
    other = m.add_failure_mode(pump, "Motor overheats")["id"]  # under no function: stays
    t_imp = m.add_mode_task(impeller, "Check flow", 3)["id"]
    t_shared = m.add_mode_task(seal, "Walk-round", 1)["id"]
    m.link_task(t_shared, other)
    t_shaft = m.add_mode_task(shaft, "Vibration", 1)["id"]
    fn_plant = m.add_function(plant, "Cool the plant")["id"]
    ff_plant = m.add_functional_failure(fn_plant, "No cooling")["id"]
    m.link_cause(ff_plant, none)
    return dict(plant=plant, pump=pump, fn=fn, flow=flow, pressure=pressure, low=low, none=none, impeller=impeller,
                seal=seal, shaft=shaft, direct=direct, other=other, t_imp=t_imp, t_shared=t_shared, t_shaft=t_shaft,
                ff_plant=ff_plant)


def _node(m, nid):
    return m.s.node(m.org, nid)


def test_the_preview_counts_what_goes_and_writes_nothing(m):
    p = _pump(m)
    events = m.s.event_count(m.org)
    out = m.remove_function(p["fn"], dry_run=True)
    assert m.s.event_count(m.org) == events
    assert out["dry_run"] is True and out["name"] == "Pump water" and out["kind"] == "function"
    assert (out["standards"], out["functional_failures"], out["failure_modes"]) == (2, 2, 4)
    assert out["tasks"] == 2 and out["tasks_kept"] == 1 and out["links"] == 1
    assert out["summary"] == ("Delete “Pump water” and everything under it? 2 performance standards, "
                              "2 functional failures, 4 failure modes, 2 tasks.")
    std = m.remove_standard(p["flow"], dry_run=True)
    assert (std["standards"], std["functional_failures"], std["failure_modes"], std["tasks"]) == (0, 1, 2, 1)
    ff = m.remove_functional_failure(p["none"], dry_run=True)
    assert (ff["functional_failures"], ff["failure_modes"], ff["tasks"], ff["links"]) == (0, 1, 1, 1)
    fm = m.retire_failure_mode(p["direct"], dry_run=True)
    assert fm["failure_modes"] == 0 and fm["summary"] == "Delete “Coupling slips”?"
    assert m.s.event_count(m.org) == events


def test_a_function_delete_takes_everything_under_it_and_undo_brings_it_back(m):
    p = _pump(m)
    before = {k: dict(_node(m, p[k])) for k in ("fn", "flow", "low", "none", "impeller", "direct", "t_imp")}
    out = m.remove_function(p["fn"], cascade=True)
    assert out["summary"].startswith("Deleted “Pump water” and everything under it.")
    assert _node(m, p["fn"])["removed"] and _node(m, p["flow"])["removed"] and _node(m, p["none"])["removed"]
    assert all(_node(m, p[k])["retired"] for k in ("impeller", "seal", "shaft", "direct", "t_imp", "t_shaft"))
    # The shared task stays (it serves "Motor overheats"), unlinked from the mode that went.
    assert not _node(m, p["t_shared"]).get("retired")
    assert [x["id"] for x in m.s.out(m.org, p["t_shared"], "MITIGATES")] == [p["other"]]
    assert not _node(m, p["other"]).get("retired")
    assert m.s.out(m.org, p["ff_plant"], "RESULTS_FROM") == []
    _same_after_rebuild(m)

    back = m.restore_rcm(p["fn"])
    assert back["skipped"] == [] and back["failure_modes_restored"] == 4 and back["tasks_restored"] == 2
    assert (back["standards_restored"], back["functional_failures_restored"], back["links_restored"]) == (2, 2, 1)
    for k in ("fn", "flow", "low", "none"):
        assert not _node(m, p[k]).get("removed")
    assert all(not _node(m, p[k]).get("retired") for k in ("impeller", "seal", "shaft", "direct", "t_imp", "t_shaft"))
    # Where everything was: the breach, the modes' places, the shared task's link, the cause.
    assert [x["id"] for x in m.s.out(m.org, p["low"], "BREACHES")] == [p["flow"]]
    assert {x["id"] for x in m.s.out(m.org, p["low"], "CAUSED_BY")} == {p["impeller"], p["seal"]}
    assert [x["id"] for x in m.s.out(m.org, p["fn"], "FAILS_DIRECTLY_AS")] == [p["direct"]]
    assert {x["id"] for x in m.s.out(m.org, p["t_shared"], "MITIGATES")} == {p["other"], p["seal"]}
    assert [x["id"] for x in m.s.out(m.org, p["ff_plant"], "RESULTS_FROM")] == [p["none"]]
    assert m.function(p["fn"])["failures"][0]["text"] == "Low flow"
    for k, was in before.items():
        assert _node(m, p[k])["text" if k != "t_imp" else "name"] == was["text" if k != "t_imp" else "name"]
    _same_after_rebuild(m)
    with pytest.raises(Invalid, match="Nothing deleted"):
        m.restore_rcm(p["fn"])


def test_a_standard_delete_takes_the_failures_breaching_it(m):
    p = _pump(m)
    m.remove_standard(p["flow"], cascade=True)
    assert _node(m, p["flow"])["removed"] and _node(m, p["low"])["removed"]
    assert _node(m, p["impeller"])["retired"] and _node(m, p["seal"])["retired"]
    assert not _node(m, p["none"]).get("removed") and not _node(m, p["pressure"]).get("removed")
    _same_after_rebuild(m)
    m.restore_rcm(p["flow"])
    assert [x["id"] for x in m.s.out(m.org, p["low"], "BREACHES")] == [p["flow"]]
    assert not _node(m, p["impeller"]).get("retired")
    _same_after_rebuild(m)


def test_a_failure_delete_takes_its_modes_tasks_and_links(m):
    p = _pump(m)
    out = m.remove_functional_failure(p["none"], cascade=True)
    assert out["links_removed"] == 1 and out["tasks_retired"] == [p["t_shaft"]]
    assert _node(m, p["shaft"])["retired"] and _node(m, p["t_shaft"])["retired"]
    _same_after_rebuild(m)
    back = m.restore_rcm(p["none"])
    assert back["links_restored"] == 1 and not _node(m, p["shaft"]).get("retired")
    _same_after_rebuild(m)


def test_a_mode_delete_and_undo_and_plain_restore_still_works(m):
    p = _pump(m)
    m.retire_failure_mode(p["seal"], cascade=True)
    assert _node(m, p["seal"])["retired"] and p["seal"] not in {
        x["id"] for x in m.s.out(m.org, p["t_shared"], "MITIGATES")}
    m.restore_rcm(p["seal"])
    assert p["seal"] in {x["id"] for x in m.s.out(m.org, p["t_shared"], "MITIGATES")}
    # A cascade delete of a mode can also come back with the plain restore (its sole task with it).
    m.retire_failure_mode(p["impeller"], cascade=True)
    m.restore_failure_mode(p["impeller"])
    assert not _node(m, p["t_imp"]).get("retired")
    _same_after_rebuild(m)


def test_undo_skips_what_changed_since_and_needs_its_parents(m):
    p = _pump(m)
    m.remove_functional_failure(p["low"], cascade=True)
    m.add_failure_mode(p["pump"], "Impeller worn")  # the same name, added meanwhile
    back = m.restore_rcm(p["low"])
    assert len(back["skipped"]) == 2 and "Impeller worn" in back["skipped"][0]
    assert _node(m, p["impeller"])["retired"] and not _node(m, p["seal"]).get("retired")
    _same_after_rebuild(m)
    m.remove_functional_failure(p["none"], cascade=True)
    m.remove_function(p["fn"], cascade=True)
    with pytest.raises(Invalid, match="function is deleted"):
        m.restore_rcm(p["none"])
    m.restore_rcm(p["fn"])
    m.restore_rcm(p["none"])
    assert not _node(m, p["shaft"]).get("retired")
    _same_after_rebuild(m)


def test_plain_removes_keep_their_meaning(m):
    p = _pump(m)
    out = m.remove_function(p["fn"])
    assert out["failure_modes_unassigned"] == 4
    assert not _node(m, p["impeller"]).get("retired")
    with pytest.raises(Invalid, match="Nothing deleted"):
        m.restore_rcm(p["fn"])


def test_function_documents_go_and_come_back(m):
    p = _pump(m)
    doc = m.add_document("https://example.org/pump.pdf", "Datasheet", target_id=p["fn"])["id"]
    out = m.remove_function(p["fn"], cascade=True)
    assert out["documents_removed"] == [doc] and _node(m, doc)["removed"]
    m.restore_rcm(p["fn"])
    assert not _node(m, doc).get("removed")
    _same_after_rebuild(m)


@pytest.fixture()
def client(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_delete_and_undo_over_rest(client):
    pos = client.post("/api/maintenance/positions", json={"name": "Pump"}).json()["id"]
    fn = client.post(f"/api/maintenance/positions/{pos}/functions", json={"text": "Pump water"}).json()["id"]
    ff = client.post(f"/api/maintenance/functions/{fn}/failures", json={"text": "No flow"}).json()["id"]
    client.post(f"/api/maintenance/positions/{pos}/failure-modes", json={"text": "Shaft", "functional_failure_id": ff})
    preview = client.delete(f"/api/maintenance/functions/{fn}?cascade=true&dry_run=true")
    assert preview.status_code == 200 and preview.json()["failure_modes"] == 1
    assert preview.json()["summary"] == "Delete “Pump water” and everything under it? 1 functional failure, 1 failure mode."
    done = client.delete(f"/api/maintenance/functions/{fn}?cascade=true")
    assert done.status_code == 200 and done.json()["deleted"] == fn
    back = client.post(f"/api/maintenance/rcm/{fn}/restore")
    assert back.status_code == 200 and back.json()["failure_modes_restored"] == 1
    assert client.post(f"/api/maintenance/rcm/{fn}/restore").status_code == 422
    for path in (f"/functional-failures/{ff}", f"/failure-modes/x"):
        r = client.delete(f"/api/maintenance{path}?dry_run=true")
        assert r.status_code in (200, 404)


def test_delete_and_undo_over_mcp(env):
    async def go(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Pump"))["id"]
        fn = _ok(await _do(client, "maintenance", "failure_modes.add_function", position_id=pos, text="Pump water"))["id"]
        ff = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=fn,
                           text="No flow"))["id"]
        _ok(await _do(client, "maintenance", "failure_modes.add", position_id=pos, text="Shaft",
                      functional_failure_id=ff))
        counts = _ok(await _do(client, "maintenance", "failure_modes.remove_functional_failure",
                               functional_failure_id=ff, cascade=True, dry_run=True))
        done = _ok(await _do(client, "maintenance", "failure_modes.remove_functional_failure",
                             functional_failure_id=ff, cascade=True))
        back = _ok(await _do(client, "maintenance", "failure_modes.undo_delete", deleted_id=ff))
        return counts, done, back

    counts, done, back = _session(env["token"], go)
    assert counts["dry_run"] and counts["failure_modes"] == 1
    assert done["deleted"] and back["failure_modes_restored"] == 1 and back["functional_failures_restored"] == 1
