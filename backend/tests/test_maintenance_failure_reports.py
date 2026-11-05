"""Reliafy Maintenance: failure reports (the loop from a failure to its closure).
Filing at a position with the fitted item kept as a snapshot, the list by a
position and everything inside it (or a location, an item, a part), the status
rules, corrective actions, the verification and the repeat check, the tree
roll-up, photos, the routes and the MCP area."""

import mongomock
import pytest

from backend.maintenance import service as service_mod
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401

ORG = "user-fr"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _plant(m):
    """Plant › Area › Pump (with an item fitted) and Plant › Other area › Fan; the
    Area is at Building (inside Site), so the Pump is there by inheritance."""
    site = m.create_location("Site")["id"]
    building = m.create_location("Building", parent_id=site)["id"]
    plant = m.create_position("Plant")["id"]
    area = m.create_position("Area", parent_id=plant, location_id=building)["id"]
    pump = m.create_position("Pump", parent_id=area)["id"]
    other = m.create_position("Other area", parent_id=plant)["id"]
    fan = m.create_position("Fan", parent_id=other)["id"]
    m.fit(pump, new_item={"name": "Pump unit 7", "serial": "MU-7"}, on="2025-01-01")
    item = m.position(pump)["fitted"]["item"]["id"]
    return {"site": site, "building": building, "plant": plant, "area": area, "pump": pump, "other": other,
            "fan": fan, "item": item}


def _file(m, pid, title="Seal leaking", **more):
    return m.file_failure_report(pid, title, **more)


# ---- filing ------------------------------------------------------------------------------

def test_filing_defaults_today_the_fitted_item_and_a_mode_in_words(m):
    ids = _plant(m)
    r = _file(m, ids["pump"], failure_mode_text="Seal worn", consequence="operational", found_by="Sam", by="Sam")
    assert r["label"] == "FR-1" and r["number"] == 1 and r["status"] == "reported"
    assert r["occurred_on"] == m.today() == r["filed_on"]
    assert r["item"] == {"id": ids["item"], "name": "Pump unit 7", "serial": "MU-7", "part": None,
                         "item_class": None, "exists": True}
    assert r["failure_mode"]["text"] == "Seal worn" and r["failure_mode"]["ad_hoc"] is True
    assert [fm["text"] for fm in m.position(ids["pump"])["failure_modes"]] == ["Seal worn"]
    assert r["position"] == {"id": ids["pump"], "name": "Pump",
                             "path": [{"id": ids["plant"], "name": "Plant"}, {"id": ids["area"], "name": "Area"}]}
    assert r["history"] == [{"at": r["history"][0]["at"], "by": "Sam", "change": "Reported"}]
    assert r["history"][0]["at"].endswith("+00:00")
    assert r["can"] == {"close": False, "reasons": ["No verification yet: record whether the corrective action "
                                                     "worked."]}
    assert r["open_actions"] == 0 and r["actions"] == [] and r["investigation"] is None
    # The same words name the same mode; the next report is FR-2, by the acting uid when nobody is named.
    again = _file(m, ids["pump"], "Leaking again", failure_mode_text="seal  worn")
    assert again["label"] == "FR-2" and again["failure_mode"]["id"] == r["failure_mode"]["id"]
    assert again["history"][0]["by"] == "tester"
    # By id too; a mode on another position is refused.
    by_id = _file(m, ids["pump"], "Third", failure_mode_id=r["failure_mode"]["id"])
    assert by_id["failure_mode"]["id"] == r["failure_mode"]["id"]
    with pytest.raises(Invalid, match="not this position"):
        _file(m, ids["fan"], "Wrong", failure_mode_id=r["failure_mode"]["id"])


def test_the_item_is_given_or_the_one_fitted_that_day_or_none(m):
    ids = _plant(m)
    # Nothing fitted at the fan: no item.
    assert _file(m, ids["fan"], "Belt snapped")["item"] is None
    # The pump's item went in on 2025-01-01: a failure before that has no item.
    assert _file(m, ids["pump"], "Old failure", occurred_on="2024-06-01")["item"] is None
    assert _file(m, ids["pump"], "Recent", occurred_on="2025-06-01")["item"]["id"] == ids["item"]
    # An item named explicitly, even one not fitted here.
    spare = m.create_item("Spare pump", serial="SP-1")["id"]
    assert _file(m, ids["fan"], "Spare failed on test", item_id=spare)["item"]["serial"] == "SP-1"
    with pytest.raises(NotFound):
        _file(m, ids["fan"], "Ghost", item_id="nope")
    with pytest.raises(Invalid, match="future"):
        _file(m, ids["fan"], "Tomorrow", occurred_on="2199-01-01")
    with pytest.raises(Invalid, match="required"):
        _file(m, ids["fan"], "")
    with pytest.raises(Invalid, match="consequence"):
        _file(m, ids["fan"], "Bad", consequence="severe")
    m.retire_position(ids["fan"])
    with pytest.raises(Invalid, match="retired"):
        _file(m, ids["fan"], "Gone")


def test_the_item_snapshot_survives_a_later_fitment_change(m):
    ids = _plant(m)
    part = m.create_part("P-1234", "Etanorm 50-200", manufacturer="KSB")["id"]
    cls = m.create_item_class("Centrifugal pump")["id"]
    m.assign_item_class(part, cls)  # the item's class comes through its part
    m.set_item_part(ids["item"], part)
    r = _file(m, ids["pump"], "Seal leaking")
    assert r["item"]["part"] == {"id": part, "part_number": "P-1234", "name": "Etanorm 50-200"}
    assert r["item"]["item_class"] == {"id": cls, "name": "Centrifugal pump"}
    # Replace the item: the report still says what was there.
    m.remove(ids["pump"], on=m.today(), reason="planned")
    m.fit(ids["pump"], new_item={"name": "Pump unit 8", "serial": "MU-8"})
    again = m.failure_report(r["id"])
    assert again["item"]["id"] == ids["item"] and again["item"]["serial"] == "MU-7"
    assert again["item"]["part"]["part_number"] == "P-1234" and again["item"]["exists"] is True
    node = m.s.node(ORG, r["id"])
    assert node["item_serial"] == "MU-7" and node["part_id"] == part and node["item_class_id"] == cls
    assert [i["id"] for i in m.s.out(ORG, r["id"], "INVOLVES")] == [ids["item"]]
    # The list's rows carry the part, and part_id filters on the snapshot.
    rows = m.failure_reports(part_id=part)
    assert [x["id"] for x in rows["reports"]] == [r["id"]]
    assert rows["reports"][0]["part"] == {"id": part, "part_number": "P-1234"}
    assert rows["reports"][0]["item"] == {"id": ids["item"], "name": "Pump unit 7", "serial": "MU-7"}
    assert m.failure_reports(part_id="nope")["total"] == 0
    # Changing the item through update takes the snapshot again (and moves the edge).
    new_item = m.position(ids["pump"])["fitted"]["item"]["id"]
    changed = m.update_failure_report(r["id"], item_id=new_item)
    assert changed["item"]["serial"] == "MU-8" and changed["item"]["part"] is None
    assert changed["history"][-1]["change"] == "Changed the item"
    assert [i["id"] for i in m.s.out(ORG, r["id"], "INVOLVES")] == [new_item]
    cleared = m.update_failure_report(r["id"], item_id=None)
    assert cleared["item"] is None and m.s.out(ORG, r["id"], "INVOLVES") == []


def test_updating_a_reports_own_fields(m):
    ids = _plant(m)
    r = _file(m, ids["pump"], "Seal leaking", failure_mode_text="Seal worn")
    out = m.update_failure_report(r["id"], title="Seal leaking badly", consequence="safety", occurred_on="2026-10-01",
                                  found_by="Ana", description="Oil on the floor", by="Ana")
    assert (out["title"], out["consequence"], out["occurred_on"], out["found_by"]) == (
        "Seal leaking badly", "safety", "2026-10-01", "Ana")
    assert out["history"][-1] == {"at": out["history"][-1]["at"], "by": "Ana",
                                  "change": "Changed what happened, the details, when, who found it, the consequence"}
    # The mode in other words: a new ad-hoc mode; '' clears it; the same value again changes nothing.
    other = m.update_failure_report(r["id"], failure_mode_text="Impeller cracked")
    assert other["failure_mode"]["text"] == "Impeller cracked" and len(other["history"]) == 3
    assert [x["id"] for x in m.s.out(ORG, r["id"], "FOUND")] == [other["failure_mode"]["id"]]
    none = m.update_failure_report(r["id"], failure_mode_id=None)
    assert none["failure_mode"] is None and m.s.out(ORG, r["id"], "FOUND") == []
    same = m.update_failure_report(r["id"], title="Seal leaking badly")
    assert len(same["history"]) == len(none["history"])
    with pytest.raises(Invalid, match="own fields"):
        m.update_failure_report(r["id"], notes="nope")
    with pytest.raises(Invalid, match="not both"):
        m.update_failure_report(r["id"], failure_mode_id="x", failure_mode_text="y")


# ---- listing -----------------------------------------------------------------------------

def test_a_list_shows_reports_below_with_their_level(m):
    ids = _plant(m)
    at_pump = _file(m, ids["pump"], "Seal leaking", occurred_on="2026-10-01")
    at_area = _file(m, ids["area"], "Area flooded", occurred_on="2026-10-02")
    at_fan = _file(m, ids["fan"], "Belt snapped", occurred_on="2026-10-03")
    from_root = m.failure_reports(position_id=ids["plant"])
    assert from_root["total"] == 3 and from_root["scope"] == {"kind": "position", "id": ids["plant"], "name": "Plant",
                                                              "positions": 5}
    assert {r["id"]: r["level"] for r in from_root["reports"]} == {
        at_pump["id"]: ["Area", "Pump"], at_area["id"]: ["Area"], at_fan["id"]: ["Other area", "Fan"]}
    from_area = m.failure_reports(position_id=ids["area"])
    assert [r["id"] for r in from_area["reports"]] == [at_area["id"], at_pump["id"]]  # newest first
    assert {r["id"]: r["level"] for r in from_area["reports"]} == {at_pump["id"]: ["Pump"], at_area["id"]: []}
    # A sibling sees nothing of the pump's; the position alone with below false.
    assert m.failure_reports(position_id=ids["other"])["total"] == 1
    alone = m.failure_reports(position_id=ids["area"], below=False)
    assert [r["id"] for r in alone["reports"]] == [at_area["id"]] and alone["scope"]["positions"] == 1
    assert m.failure_reports(position_id=ids["pump"], below="0")["total"] == 1
    # A position carried by the item fitted there counts as inside, as the tree nests it.
    turbo = m.create_position("Turbo", parent_id=ids["item"])["id"]
    at_turbo = _file(m, turbo, "Turbo seized", occurred_on="2026-10-04")
    rows = m.failure_reports(position_id=ids["pump"])
    assert {r["id"]: r["level"] for r in rows["reports"]} == {at_pump["id"]: [], at_turbo["id"]: ["Pump unit 7", "Turbo"]}
    assert m._report_scope(ids["pump"]) == [ids["pump"], turbo]
    with pytest.raises(Invalid, match="One scope"):
        m.failure_reports(position_id=ids["pump"], location_id=ids["site"])
    with pytest.raises(NotFound):
        m.failure_reports(position_id="nope")


def test_a_list_by_location_item_and_the_whole_workspace(m):
    ids = _plant(m)
    at_pump = _file(m, ids["pump"], "Seal leaking")
    at_fan = _file(m, ids["fan"], "Belt snapped")
    # The pump is at the building by inheritance (its area is); the fan is nowhere.
    by_site = m.failure_reports(location_id=ids["site"])
    assert [r["id"] for r in by_site["reports"]] == [at_pump["id"]]
    assert by_site["scope"] == {"kind": "location", "id": ids["site"], "name": "Site", "positions": 2}
    assert by_site["reports"][0]["level"] == ["Plant", "Area", "Pump"]  # no root: the whole path
    assert m.failure_reports(location_id=ids["building"])["total"] == 1
    by_item = m.failure_reports(item_id=ids["item"])
    assert [r["id"] for r in by_item["reports"]] == [at_pump["id"]] and by_item["scope"]["kind"] == "item"
    whole = m.failure_reports()
    assert {r["id"] for r in whole["reports"]} == {at_pump["id"], at_fan["id"]}
    assert whole["scope"] == {"kind": "workspace", "id": None, "name": None, "positions": 5}


def test_filters_sort_pagination_and_counts(m):
    ids = _plant(m)
    a = _file(m, ids["pump"], "Seal leaking", occurred_on="2026-10-01", consequence="operational",
              failure_mode_text="Seal worn", found_by="Sam")
    b = _file(m, ids["pump"], "Bearing noisy", occurred_on="2026-10-05", consequence="safety",
              failure_mode_text="Bearing worn")
    c = _file(m, ids["fan"], "Belt snapped", occurred_on="2026-10-03", description="The drive belt went")
    d = _file(m, ids["fan"], "Not a failure", occurred_on="2026-10-04")
    m.set_failure_report_status(b["id"], "investigating")
    m.set_failure_report_status(d["id"], "rejected", note="A planned stop")
    root = ids["plant"]
    every = m.failure_reports(position_id=root)
    assert every["counts"] == {"reported": 2, "investigating": 1, "corrective_action": 0, "verifying": 0,
                               "closed": 0, "rejected": 1, "open": 3}
    assert [r["label"] for r in every["reports"]] == ["FR-2", "FR-4", "FR-3", "FR-1"]
    assert [r["label"] for r in m.failure_reports(position_id=root, status="open")["reports"]] == [
        "FR-2", "FR-3", "FR-1"]
    assert [r["label"] for r in m.failure_reports(position_id=root, status="rejected")["reports"]] == ["FR-4"]
    assert [r["label"] for r in m.failure_reports(position_id=root, status="all")["reports"]] == every and True or \
        len(m.failure_reports(position_id=root, status="all")["reports"]) == 4
    # Counts are over the other filters, not the status.
    by_mode = m.failure_reports(position_id=root, failure_mode_id=a["failure_mode"]["id"], status="open")
    assert by_mode["counts"]["open"] == 1 and [r["id"] for r in by_mode["reports"]] == [a["id"]]
    assert [r["id"] for r in m.failure_reports(position_id=root, consequence="safety")["reports"]] == [b["id"]]
    assert [r["label"] for r in m.failure_reports(position_id=root, since="2026-10-03", until="2026-10-04")["reports"]
            ] == ["FR-4", "FR-3"]
    assert [r["id"] for r in m.failure_reports(q="drive belt")["reports"]] == [c["id"]]  # the description
    assert [r["id"] for r in m.failure_reports(q="sam")["reports"]] == [a["id"]]  # who found it
    assert [r["id"] for r in m.failure_reports(q="bearing worn")["reports"]] == [b["id"]]  # the mode
    assert {r["id"] for r in m.failure_reports(q="FAN")["reports"]} == {c["id"], d["id"]}  # the position
    assert [r["label"] for r in m.failure_reports(position_id=root, sort="oldest")["reports"]] == [
        "FR-1", "FR-3", "FR-4", "FR-2"]
    assert [r["label"] for r in m.failure_reports(position_id=root, sort="status")["reports"]] == [
        "FR-3", "FR-1", "FR-2", "FR-4"]  # reported (newest first), investigating, rejected
    assert [r["label"] for r in m.failure_reports(position_id=root, sort="consequence")["reports"]] == [
        "FR-2", "FR-1", "FR-4", "FR-3"]  # safety, operational, then not said
    assert [r["label"] for r in m.failure_reports(position_id=root, sort="position")["reports"]] == [
        "FR-2", "FR-1", "FR-4", "FR-3"]  # Area › Pump before Other area › Fan
    page = m.failure_reports(position_id=root, limit=2, offset=1)
    assert [r["label"] for r in page["reports"]] == ["FR-4", "FR-3"] and page["total"] == 4
    assert m.failure_reports(position_id=root, limit=2, offset=10)["reports"] == []
    for bad in ({"status": "nope"}, {"consequence": "nope"}, {"sort": "nope"}, {"limit": 0}, {"limit": 501},
                {"offset": -1}, {"since": "2026-10-05", "until": "2026-10-01"}, {"since": "yesterday"}):
        with pytest.raises(Invalid):
            m.failure_reports(position_id=root, **bad)
    brief = every["reports"][0]
    assert set(brief) == {"id", "number", "label", "title", "status", "consequence", "occurred_on", "found_by",
                          "position", "level", "failure_mode", "item", "part", "open_actions", "last_change"}
    assert brief["last_change"]["change"] == "Investigating" and brief["failure_mode"] == {
        "id": b["failure_mode"]["id"], "text": "Bearing worn"}


# ---- the loop: statuses, investigation, actions, verification -----------------------------

def test_every_status_rule(m):
    ids = _plant(m)
    r = _file(m, ids["pump"], "Seal leaking")
    rid = r["id"]
    other = _file(m, ids["fan"], "Belt snapped")["id"]
    with pytest.raises(Invalid, match="status is one of"):
        m.set_failure_report_status(rid, "done")
    # Among the open four, any direction; the same status again changes nothing.
    assert m.set_failure_report_status(rid, "verifying")["status"] == "verifying"
    assert m.set_failure_report_status(rid, "reported", by="Ana")["history"][-1]["change"] == "Reported"
    assert len(m.set_failure_report_status(rid, "reported")["history"]) == 3
    # Close only with a verification, and not one that says it didn't work.
    with pytest.raises(Invalid, match="Record a verification first"):
        m.set_failure_report_status(rid, "closed")
    m.verify_failure_report(rid, "not_worked", notes="Still leaking")
    with pytest.raises(Invalid, match="didn't work"):
        m.set_failure_report_status(rid, "closed")
    assert m.failure_report(rid)["can"]["close"] is False
    m.verify_failure_report(rid, "unclear")
    assert m.failure_report(rid)["can"] == {"close": True}
    closed = m.set_failure_report_status(rid, "closed", note="Signed off", by="Ana")
    assert closed["status"] == "closed" and closed["closed"] == {"on": m.today(), "by": "Ana", "note": "Signed off"}
    assert closed["history"][-1]["change"] == "Closed: Signed off" and closed["can"]["close"] is False
    # Once closed: no edits, no reject; the only move is a reopen, which clears the closure.
    for call in (lambda: m.update_failure_report(rid, title="x"),
                 lambda: m.investigate_failure_report(rid, notes="x"),
                 lambda: m.add_corrective_action(rid, "x"),
                 lambda: m.verify_failure_report(rid, "worked")):
        with pytest.raises(Invalid, match="Reopen it first"):
            call()
    with pytest.raises(Invalid, match="only move"):
        m.set_failure_report_status(rid, "rejected", note="dup")
    reopened = m.set_failure_report_status(rid, "corrective_action", note="Leaked again")
    assert reopened["closed"] is None and reopened["status"] == "corrective_action"
    assert reopened["history"][-1]["change"] == "Reopened as corrective action: Leaked again"
    # Rejecting needs a reason; a duplicate names another report, never itself.
    with pytest.raises(Invalid, match="Say why"):
        m.set_failure_report_status(rid, "rejected")
    with pytest.raises(Invalid, match="itself"):
        m.set_failure_report_status(rid, "rejected", note="dup", duplicate_of=rid)
    with pytest.raises(Invalid, match="another failure report"):
        m.set_failure_report_status(rid, "rejected", note="dup", duplicate_of="nope")
    with pytest.raises(Invalid, match="goes with status rejected"):
        m.set_failure_report_status(rid, "investigating", duplicate_of=other)
    rejected = m.set_failure_report_status(rid, "rejected", note="Same as FR-2", duplicate_of=other)
    assert rejected["rejected"] == {"on": m.today(), "by": "tester", "note": "Same as FR-2", "duplicate_of": other}
    with pytest.raises(Invalid, match="only move"):
        m.set_failure_report_status(rid, "closed")
    back = m.set_failure_report_status(rid, "reported")
    assert back["rejected"] is None and back["history"][-1]["change"] == "Reopened as reported"
    with pytest.raises(NotFound):
        m.set_failure_report_status("nope", "closed")


def test_investigation_and_corrective_actions(m):
    ids = _plant(m)
    rid = _file(m, ids["pump"], "Seal leaking")["id"]
    out = m.investigate_failure_report(rid, notes="Ran dry overnight", root_cause_category="operation",
                                       root_cause="Suction valve left shut", whys=["Why? valve shut", "Why? no tag"],
                                       by="Ana")
    assert out["investigation"] == {"notes": "Ran dry overnight", "root_cause_category": "operation",
                                    "root_cause": "Suction valve left shut", "whys": ["Why? valve shut", "Why? no tag"],
                                    "on": m.today(), "by": "Ana"}
    assert out["history"][-1]["change"] == "Investigated: Suction valve left shut"
    # A field left out keeps its value; '' clears the category; the vocabulary is checked.
    again = m.investigate_failure_report(rid, whys=["Why? valve shut", "", "Why? no tag", "Why? no procedure"])
    assert again["investigation"]["notes"] == "Ran dry overnight" and len(again["investigation"]["whys"]) == 3
    assert m.investigate_failure_report(rid, root_cause_category="")["investigation"]["root_cause_category"] is None
    with pytest.raises(Invalid, match="root cause category"):
        m.investigate_failure_report(rid, root_cause_category="gremlins")
    with pytest.raises(Invalid, match="At most 7"):
        m.investigate_failure_report(rid, whys=["w"] * 8)

    wo = m.open_work_order(ids["pump"], "Fit new seal")
    with pytest.raises(Invalid, match="required"):
        m.add_corrective_action(rid, "")
    with pytest.raises(Invalid, match="work_order_id must be"):
        m.add_corrective_action(rid, "Fit seal", work_order_id="nope")
    r = m.add_corrective_action(rid, "Fit a new seal", owner="Sam", due="2026-11-20", work_order_id=wo["id"],
                                work_order_ref="WO-77", by="Ana")
    [action] = r["actions"]
    assert action == {"id": action["id"], "what": "Fit a new seal", "owner": "Sam", "due": "2026-11-20",
                      "status": "open", "done_on": None, "work_order_id": wo["id"], "work_order_ref": "WO-77",
                      "added": {"on": m.today(), "by": "Ana"}}
    assert r["open_actions"] == 1 and r["history"][-1]["change"] == "Action added: Fit a new seal"
    done = m.update_corrective_action(rid, action["id"], status="done", by="Sam")
    assert done["actions"][0]["status"] == "done" and done["actions"][0]["done_on"] == m.today()
    assert done["open_actions"] == 0 and done["history"][-1]["change"] == "Action done: Fit a new seal"
    back = m.update_corrective_action(rid, action["id"], status="open", what="Fit a new seal and bearing",
                                      work_order_id="none", work_order_ref="")
    assert back["actions"][0]["done_on"] is None and back["actions"][0]["work_order_id"] is None
    assert back["history"][-1]["change"] == "Action reopened: Fit a new seal and bearing"
    dated = m.update_corrective_action(rid, action["id"], status="done", done_on="2026-11-01")
    assert dated["actions"][0]["done_on"] == "2026-11-01"
    assert len(m.update_corrective_action(rid, action["id"], owner="Sam")["history"]) == len(dated["history"])
    with pytest.raises(Invalid, match="status is one of"):
        m.update_corrective_action(rid, action["id"], status="finished")
    with pytest.raises(Invalid, match="fields are"):
        m.update_corrective_action(rid, action["id"], notes="x")
    with pytest.raises(NotFound):
        m.update_corrective_action(rid, "nope", status="done")
    for i in range(service_mod.MAX_ACTIONS_PER_REPORT - 1):
        m.add_corrective_action(rid, f"Step {i}")
    with pytest.raises(LimitReached, match="at most 50"):
        m.add_corrective_action(rid, "One too many")


def test_verification_and_the_repeat_check(m):
    ids = _plant(m)
    r = _file(m, ids["pump"], "Seal leaking", occurred_on="2026-10-01", failure_mode_text="Seal worn")
    rid, mode = r["id"], r["failure_mode"]["id"]
    assert r["repeat_check"] == {"since": "2026-10-01", "repeats": 0, "same_mode_repeats": 0, "latest": None}
    with pytest.raises(Invalid, match="result is one of"):
        m.verify_failure_report(rid, "yes")
    with pytest.raises(Invalid, match="future"):
        m.verify_failure_report(rid, "worked", verified_on="2199-01-01")
    v = m.verify_failure_report(rid, "worked", notes="Dry for a month", verified_on="2026-10-06", by="Ana")
    assert v["verification"] == {"result": "worked", "notes": "Dry for a month", "verified_on": "2026-10-06",
                                 "on": m.today(), "by": "Ana"}
    assert v["history"][-1]["change"] == "Verified: it worked" and v["repeat_check"]["since"] == "2026-10-06"
    # The latest action done comes first.
    aid = m.add_corrective_action(rid, "Fit seal")["actions"][0]["id"]
    m.update_corrective_action(rid, aid, status="done", done_on="2026-10-04")
    assert m.failure_report(rid)["repeat_check"]["since"] == "2026-10-04"
    # Later reports at the same position count (the same mode counted too); rejected ones
    # and other positions' don't; one on the day of the fix isn't after it.
    _file(m, ids["pump"], "Leaking again", occurred_on="2026-10-10", failure_mode_id=mode)
    _file(m, ids["pump"], "Bearing noisy", occurred_on="2026-10-12", failure_mode_text="Bearing worn")
    _file(m, ids["pump"], "Same day", occurred_on="2026-10-04")
    rejected = _file(m, ids["pump"], "Not a failure", occurred_on="2026-10-15", failure_mode_id=mode)["id"]
    m.set_failure_report_status(rejected, "rejected", note="Planned stop")
    _file(m, ids["fan"], "Belt snapped", occurred_on="2026-10-20")
    assert m.failure_report(rid)["repeat_check"] == {"since": "2026-10-04", "repeats": 2, "same_mode_repeats": 1,
                                                     "latest": "2026-10-12"}


def test_history_names_who_and_when_for_every_change(m):
    ids = _plant(m)
    rid = _file(m, ids["pump"], "Seal leaking", by="Sam")["id"]
    m.update_failure_report(rid, consequence="safety", by="Ana")
    m.set_failure_report_status(rid, "investigating", note="Looking", by="Ana")
    m.investigate_failure_report(rid, root_cause_category="wear", by="Ana")
    aid = m.add_corrective_action(rid, "Fit seal", by="Ana")["actions"][0]["id"]
    m.update_corrective_action(rid, aid, status="done", by="Sam")
    m.verify_failure_report(rid, "worked", by="Sam")
    r = m.set_failure_report_status(rid, "closed", by="Ana")
    assert [(h["by"], h["change"]) for h in r["history"]] == [
        ("Sam", "Reported"), ("Ana", "Changed the consequence"), ("Ana", "Investigating: Looking"),
        ("Ana", "Investigated: wear"), ("Ana", "Action added: Fit seal"), ("Sam", "Action done: Fit seal"),
        ("Sam", "Verified: it worked"), ("Ana", "Closed")]
    assert all(h["at"] for h in r["history"])
    # The event log carries the same who and when (the projection reads only the payload).
    filed = [e for e in m.s.events(ORG, type="failure_report.filed")]
    assert filed and filed[0]["payload"]["by"] == "Sam" and filed[0]["payload"]["on"] == m.today()


# ---- the tree, the position view, photos, rebuilds, limits -------------------------------

def test_the_tree_rolls_open_reports_up_and_drops_them_when_closed(m):
    ids = _plant(m)
    a = _file(m, ids["pump"], "Seal leaking")["id"]
    b = _file(m, ids["area"], "Area flooded")["id"]
    _file(m, ids["fan"], "Belt snapped")

    def rows():
        return {r["name"]: r for r in m.tree_rows()["positions"]}

    before = rows()
    assert before["Pump"]["status"] == {"open_reports": 1} and "inside" not in before["Pump"]
    assert before["Area"]["status"] == {"open_reports": 1} and before["Area"]["inside"]["open_reports"] == 1
    assert before["Plant"]["inside"]["open_reports"] == 3 and "status" not in before["Plant"]
    assert before["Other area"]["inside"]["open_reports"] == 1
    assert m.position(ids["area"])["failure_reports"] == {"open": 1, "total": 1, "latest_on": m.today()}
    assert m.position(ids["plant"])["failure_reports"] == {"open": 0, "total": 0, "latest_on": None}
    m.verify_failure_report(a, "worked")
    m.set_failure_report_status(a, "closed")
    m.set_failure_report_status(b, "rejected", note="Not a failure")
    after = rows()
    assert "status" not in after["Pump"] and "status" not in after["Area"]
    assert after["Area"]["inside"] == {"positions": 1} and after["Plant"]["inside"]["open_reports"] == 1
    assert m.position(ids["pump"])["failure_reports"] == {"open": 0, "total": 1, "latest_on": m.today()}
    # The nested tree carries the same counts.
    plant = next(t for t in m.tree() if t["name"] == "Plant")
    assert plant["inside"]["open_reports"] == 1 and plant["status"]["open_reports"] == 0


def test_photos_go_on_a_report(m):
    ids = _plant(m)
    rid = _file(m, ids["pump"], "Seal leaking")["id"]
    m.add_photo("ph1", rid, {"width": 10, "height": 10, "taken_on": "2026-10-01"}, "The leak")
    r = m.failure_report(rid)
    assert [p["caption"] for p in r["photos"]] == ["The leak"]
    assert m.photo("ph1")["on"] == [{"id": rid, "kind": "FailureReport", "name": "Seal leaking"}]
    assert m.photo_target(rid)["label"] == "FailureReport"
    task = m.create_task(ids["pump"], "Check", 1, "months")["id"]
    with pytest.raises(NotFound):
        m.photo_target(task)


def test_a_rebuilt_graph_matches(m):
    ids = _plant(m)
    part = m.create_part("P-1", "Seal kit")["id"]
    m.set_item_part(ids["item"], part)
    r = _file(m, ids["pump"], "Seal leaking", failure_mode_text="Seal worn", by="Sam")
    rid = r["id"]
    m.update_failure_report(rid, failure_mode_text="Impeller cracked", found_by="Ana")
    m.set_failure_report_status(rid, "investigating")
    m.investigate_failure_report(rid, root_cause="Cavitation", whys=["Why? low suction"])
    aid = m.add_corrective_action(rid, "Fit seal", work_order_id=m.open_work_order(ids["pump"], "Seal")["id"])
    aid = aid["actions"][0]["id"]
    m.update_corrective_action(rid, aid, status="done")
    m.verify_failure_report(rid, "worked")
    m.set_failure_report_status(rid, "closed", note="Done")
    m.set_failure_report_status(rid, "reported")
    other = _file(m, ids["fan"], "Dup")["id"]
    m.set_failure_report_status(other, "rejected", note="Dup", duplicate_of=rid)
    m.update_failure_report(rid, item_id=None)
    m.add_photo("ph1", rid, {"width": 10, "height": 10}, "Leak")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_limits(m, monkeypatch):
    ids = _plant(m)
    with pytest.raises(Invalid, match="report's title is at most 200"):
        _file(m, ids["pump"], "x" * 201)
    with pytest.raises(Invalid, match="name of who found it"):
        _file(m, ids["pump"], "Leak", found_by="x" * 201)
    monkeypatch.setattr(service_mod, "MAX_REPORTS", 2)
    _file(m, ids["pump"], "One")
    _file(m, ids["pump"], "Two")
    with pytest.raises(LimitReached, match="at most 2 failure reports"):
        _file(m, ids["pump"], "Three")
    # The daily run isn't limited.
    free = Maintenance(m.s, ORG, "tester", limited=False)
    assert free.file_failure_report(ids["pump"], "Three")["label"] == "FR-3"


# ---- the routes --------------------------------------------------------------------------

UID = "user-fr-api"


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"fr@example.org"})
    test_db = mongomock.MongoClient()["maint_failure_reports_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": UID, "email": "fr@example.org", "name": "Frances", "email_verified": True}
    test_db.users.insert_one({"_id": UID, "email": "fr@example.org", "name": "Frances", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_nine_routes(api):
    from backend.auth import get_current_user
    from backend.main import app

    M = "/api/maintenance"
    plant = api.post(f"{M}/positions", json={"name": "Plant"}).json()
    pump = api.post(f"{M}/positions", json={"name": "Pump", "parent_id": plant["id"]}).json()
    api.post(f"{M}/positions/{pump['id']}/fit", json={"new_item": {"name": "Pump unit 7", "serial": "MU-7"}})
    r = api.post(f"{M}/failure-reports", json={"position_id": pump["id"], "title": "Seal leaking",
                                               "failure_mode_text": "Seal worn", "consequence": "operational"})
    assert r.status_code == 200, r.text
    report = r.json()
    rid = report["id"]
    assert report["label"] == "FR-1" and report["item"]["serial"] == "MU-7"
    assert report["history"][0]["by"] == "Frances"  # the signed-in user's name by default
    named = api.post(f"{M}/failure-reports", json={"position_id": pump["id"], "title": "Second", "by": "Sam"}).json()
    assert named["history"][0]["by"] == "Sam"
    assert api.post(f"{M}/failure-reports", json={"position_id": pump["id"]}).status_code == 422
    assert api.post(f"{M}/failure-reports", json={"position_id": "nope", "title": "x"}).status_code == 404

    listed = api.get(f"{M}/failure-reports", params={"position_id": plant["id"]}).json()
    assert listed["total"] == 2 and listed["counts"]["open"] == 2 and listed["reports"][0]["level"] == ["Pump"]
    assert api.get(f"{M}/failure-reports", params={"position_id": plant["id"], "below": "0"}).json()["total"] == 0
    assert api.get(f"{M}/failure-reports", params={"status": "open", "q": "seal", "sort": "oldest", "limit": 1,
                                                   "offset": 0}).json()["reports"][0]["id"] == rid
    bad = api.get(f"{M}/failure-reports", params={"status": "nope"})
    assert bad.status_code == 422 and "status is open, all" in bad.json()["detail"]
    assert api.get(f"{M}/failure-reports", params={"position_id": "nope"}).status_code == 404

    got = api.get(f"{M}/failure-reports/{rid}")
    assert got.status_code == 200 and got.json()["title"] == "Seal leaking"
    assert api.get(f"{M}/failure-reports/nope").status_code == 404
    assert api.get(f"{M}/failure-reports/nope").json() == {"detail": "Not found."}

    patched = api.patch(f"{M}/failure-reports/{rid}", json={"title": "Seal leaking badly", "by": "Ana"})
    assert patched.status_code == 200 and patched.json()["history"][-1] == {
        "at": patched.json()["history"][-1]["at"], "by": "Ana", "change": "Changed what happened"}
    assert api.patch(f"{M}/failure-reports/{rid}", json={"nope": 1}).status_code == 422

    inv = api.put(f"{M}/failure-reports/{rid}/investigation", json={"root_cause_category": "wear",
                                                                     "root_cause": "Seal face scored"})
    assert inv.status_code == 200 and inv.json()["investigation"]["root_cause"] == "Seal face scored"
    assert api.put(f"{M}/failure-reports/{rid}/investigation", json={"root_cause_category": "x"}).status_code == 422

    act = api.post(f"{M}/failure-reports/{rid}/actions", json={"what": "Fit a new seal", "owner": "Sam",
                                                               "work_order_ref": "WO-12"})
    assert act.status_code == 200
    [action] = act.json()["actions"]
    assert action["work_order_ref"] == "WO-12" and action["status"] == "open"
    assert api.post(f"{M}/failure-reports/{rid}/actions", json={}).status_code == 422
    upd = api.patch(f"{M}/failure-reports/{rid}/actions/{action['id']}", json={"status": "done"})
    assert upd.status_code == 200 and upd.json()["actions"][0]["done_on"]
    assert api.patch(f"{M}/failure-reports/{rid}/actions/nope", json={"status": "done"}).status_code == 404

    refused = api.post(f"{M}/failure-reports/{rid}/status", json={"status": "closed"})
    assert refused.status_code == 422 and "verification" in refused.json()["detail"]
    ver = api.put(f"{M}/failure-reports/{rid}/verification", json={"result": "worked", "notes": "Dry"})
    assert ver.status_code == 200 and ver.json()["verification"]["result"] == "worked"
    assert ver.json()["repeat_check"] == {"since": ver.json()["actions"][0]["done_on"], "repeats": 0,
                                          "same_mode_repeats": 0, "latest": None}  # FR-2 is from the fix's day
    assert api.put(f"{M}/failure-reports/{rid}/verification", json={"result": "maybe"}).status_code == 422
    closed = api.post(f"{M}/failure-reports/{rid}/status", json={"status": "closed", "note": "Done"})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert closed.json()["closed"]["by"] == "Frances"
    assert api.post(f"{M}/failure-reports/{rid}/status", json={"status": "nope"}).status_code == 422
    assert api.post(f"{M}/failure-reports/nope/status", json={"status": "closed"}).status_code == 404

    tree = api.get(f"{M}/tree").json()
    assert next(p for p in tree["positions"] if p["name"] == "Plant")["inside"]["open_reports"] == 1
    assert api.get(f"{M}/positions/{pump['id']}").json()["failure_reports"] == {"open": 1, "total": 2,
                                                                                "latest_on": closed.json()["occurred_on"]}
    # Signed out, the routes answer 401 (they're on the maintenance router with its deps).
    app.dependency_overrides.pop(get_current_user)
    assert api.get(f"{M}/failure-reports").status_code == 401
    assert api.post(f"{M}/failure-reports", json={}).status_code == 401
    assert api.get(f"{M}/failure-reports/{rid}").status_code == 401


def test_view_only_members_cant_file(api):
    from backend.main import app
    from backend.services.access import AccessCtx, get_access

    user = {"uid": UID, "email": "fr@example.org", "name": "Frances", "email_verified": True}
    app.dependency_overrides[get_access] = lambda: AccessCtx(
        user=user, uid=UID, workspace="t1", write_owner="team:t1", read_owners=[UID, "team:t1"],
        list_owners=["team:t1"], member_view_only=True)
    assert api.get("/api/maintenance/failure-reports").status_code == 200
    r = api.post("/api/maintenance/failure-reports", json={"position_id": "x", "title": "x"})
    assert r.status_code == 402 and r.json()["code"] == "member_pro_required"
    assert api.post("/api/maintenance/failure-reports/x/status", json={"status": "closed"}).status_code == 402


# ---- over MCP ----------------------------------------------------------------------------

def test_failure_reports_over_mcp(env):  # noqa: F811
    async def flow(client):
        plant = _ok(await _do(client, "maintenance", "positions.create", name="Plant"))
        pump = _ok(await _do(client, "maintenance", "positions.create", name="Pump", parent_id=plant["id"]))
        _ok(await _do(client, "maintenance", "fitments.fit", position_id=pump["id"], item_name="Pump unit 7",
                      serial="MU-7"))
        filed = _ok(await _do(client, "maintenance", "failure_reports.file", position_id=pump["id"],
                              title="Seal leaking", failure_mode_text="Seal worn", consequence="operational"))
        missing = await _do(client, "maintenance", "failure_reports.file", position_id=pump["id"])
        rid = filed["id"]
        _ok(await _do(client, "maintenance", "failure_reports.set_status", report_id=rid, status="investigating"))
        _ok(await _do(client, "maintenance", "failure_reports.investigate", report_id=rid,
                      root_cause_category="wear", whys=["Why? old seal"]))
        with_action = _ok(await _do(client, "maintenance", "failure_reports.add_action", report_id=rid,
                                    what="Fit a new seal", owner="Sam"))
        aid = with_action["actions"][0]["id"]
        _ok(await _do(client, "maintenance", "failure_reports.update_action", report_id=rid, action_id=aid,
                      status="done"))
        _ok(await _do(client, "maintenance", "failure_reports.update", report_id=rid, found_by="Ana"))
        _ok(await _do(client, "maintenance", "failure_reports.verify", report_id=rid, result="worked"))
        closed = _ok(await _do(client, "maintenance", "failure_reports.set_status", report_id=rid, status="closed",
                               note="Done"))
        refused = await _do(client, "maintenance", "failure_reports.add_action", report_id=rid, what="Late")
        got = _ok(await _get(client, "failure_report", rid))
        listed = _ok(await _list(client, "failure_reports", position_id=plant["id"], status="all", sort="newest"))
        alone = _ok(await _list(client, "failure_reports", position_id=plant["id"], below=False))
        by_item = _ok(await _list(client, "failure_reports", item_id=got["item"]["id"], since="2000-01-01"))
        bad_status = await _list(client, "failure_reports", status="planned")
        events = _ok(await _list(client, "events", limit=3, since=0, type="failure_report.filed"))
        batch = _ok(await client.call_tool("maintenance", {"action": "apply", "dry_run": False, "operations": [
            {"ref": "r", "do": "failure_reports.file", "args": {"position_id": pump["id"], "title": "Bearing noisy"}},
            {"do": "failure_reports.investigate", "args": {"report_id": "@r", "root_cause_category": "wear",
                                                           "root_cause": "Ran dry"}},
        ]}))
        after = _ok(await _get(client, "failure_report", batch["results"][0]["result"]["id"]))
        guide = _ok(await client.call_tool("maintenance", {"action": "guide", "topic": "failures"}))
        return filed, missing, closed, refused, got, listed, alone, by_item, bad_status, events, batch, after, guide

    (filed, missing, closed, refused, got, listed, alone, by_item, bad_status, events, batch, after,
     guide) = _session(env["token"], flow)
    assert filed["label"] == "FR-1" and filed["history"][0]["by"] == "M"  # the caller's name
    assert missing.is_error and "needs title" in missing.content[0].text
    assert closed["status"] == "closed" and closed["closed"]["by"] == "M"
    assert refused.is_error and "Reopen it first" in refused.content[0].text
    assert got["investigation"]["root_cause_category"] == "wear" and got["found_by"] == "Ana"
    assert [h["change"] for h in got["history"]][:3] == ["Reported", "Investigating", "Investigated: wear"]
    assert listed["total"] == 1 and listed["reports"][0]["level"] == ["Pump"] and listed["counts"]["closed"] == 1
    assert alone["total"] == 0 and by_item["total"] == 1
    assert bad_status.is_error and "kind 'failure_reports' takes status open" in bad_status.content[0].text
    assert [e["type"] for e in events["events"]] == ["failure_report.filed"]
    assert batch["applied"] == 2 and after["label"] == "FR-2"
    assert after["investigation"]["root_cause"] == "Ran dry" and after["status"] == "reported"
    assert "repeat_check" in guide["guide"] and "failure_reports.file" in guide["guide"]
