"""A combination of tasks (RCM II): one failure mode's decision holding two or
more outcomes, a regular inspection plus a fixed-time replacement, each with a
task of its own on the position. Additive: the members are a new event
(failure_mode.outcomes_set); a plain decision emits exactly what it did, and
every graph rebuilds the same."""

import pytest

from backend.maintenance import rcm_decisions
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "user-a"

COMBO = {"outcomes": [
    {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months"},
    {"outcome": "fixed_interval", "task": "Replace the bearing", "interval": 24, "interval_unit": "months"},
], "notes": "Safety: neither task alone is enough."}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type=None):
    """The log, oldest first."""
    return [e for e in reversed(m.s.events(ORG, 5000)) if type is None or e["type"] == type]


def _mode(m, text="Bearing worn"):
    pump = m.create_position("Pump")
    return pump, m.add_failure_mode(pump["id"], text)


def _live(m, position_id):
    return {t["name"]: t for t in m.s.inn(ORG, position_id, "ON") if t["label"] == "Task" and not t.get("retired")}


def test_a_combination_gets_a_task_per_member_with_its_own_outcome(m):
    pump, fm = _mode(m)
    out = m.decide_failure_mode(fm["id"], "safety", COMBO)
    d = out["decision"]
    assert d["outcome"] == "on_condition" and d["task"] == "Vibration check" and d["interval"] == 1
    assert [(o["outcome"], o["task"], o["interval"], o["interval_unit"]) for o in d["outcomes"]] == [
        ("on_condition", "Vibration check", 1, "months"), ("fixed_interval", "Replace the bearing", 24, "months")]
    tasks = _live(m, pump["id"])
    assert {n: t["outcome"] for n, t in tasks.items()} == {
        "Vibration check": "on_condition", "Replace the bearing": "fixed_interval"}
    assert d["task_id"] == tasks["Vibration check"]["id"] == d["outcomes"][0]["task_id"]
    assert d["outcomes"][1]["task_id"] == tasks["Replace the bearing"]["id"]
    [ev] = _events(m, "failure_mode.outcomes_set")
    assert ev["payload"] == {"id": fm["id"], "outcomes": [
        {"outcome": "on_condition", "task_id": tasks["Vibration check"]["id"]},
        {"outcome": "fixed_interval", "task_id": tasks["Replace the bearing"]["id"]}]}
    # The position's own list and the bulk read show every member.
    assert m._mode_view(m.s.node(ORG, fm["id"]))["outcomes"] == ["on_condition", "fixed_interval"]
    [p] = m.rcm_worksheet(pump["id"], "this")["positions"]
    assert [o["outcome"] for o in p["unassigned"][0]["decision"]["outcomes"]] == ["on_condition", "fixed_interval"]
    _rebuilds_the_same(m)


def test_deciding_the_same_combination_again_changes_nothing(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    n = len(_events(m))
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    assert len(_events(m)) == n
    # A member's interval changes its own task only.
    changed = {**COMBO, "outcomes": [COMBO["outcomes"][0], {**COMBO["outcomes"][1], "interval": 18}]}
    m.decide_failure_mode(fm["id"], "safety", changed)
    tasks = _live(m, pump["id"])
    assert tasks["Replace the bearing"]["interval"] == 18 and tasks["Vibration check"]["interval"] == 1
    _rebuilds_the_same(m)


def test_clearing_a_combination_retires_both_tasks(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    out = m.decide_failure_mode(fm["id"], decision=None)
    assert out["decision"] is None and _live(m, pump["id"]) == {}
    assert m.s.node(ORG, fm["id"]).get("outcomes") is None
    assert _events(m, "failure_mode.outcomes_set")[-1]["payload"]["outcomes"] == []
    _rebuilds_the_same(m)


def test_back_to_one_outcome_keeps_its_task_and_retires_the_other(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    kept = _live(m, pump["id"])["Replace the bearing"]["id"]
    d = m.decide_failure_mode(fm["id"], "safety", {"outcome": "fixed_interval", "task": "Replace the bearing",
                                                    "interval": 24, "interval_unit": "months"})["decision"]
    assert "outcomes" not in d and d["task_id"] == kept
    assert list(_live(m, pump["id"])) == ["Replace the bearing"]
    _rebuilds_the_same(m)


def test_a_single_decision_adopts_its_task_into_a_combination(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", {"outcome": "on_condition", "task": "Vibration check", "interval": 1,
                                               "interval_unit": "months"})
    own = m.rcm_mode(fm["id"])["decision"]["task_id"]
    d = m.decide_failure_mode(fm["id"], "safety", COMBO)["decision"]
    assert d["task_id"] == own and len(_live(m, pump["id"])) == 2
    # A member may name an existing task on the position (task_id), adopted as it is.
    other = m.add_failure_mode(pump["id"], "Seal leaks")
    d2 = m.decide_failure_mode(other["id"], "safety", {"outcomes": [
        {"outcome": "on_condition", "task_id": own},
        {"outcome": "failure_finding", "task": "Test the leak alarm", "interval": 6, "interval_unit": "months"}]})
    assert d2["decision"]["outcomes"][0]["task_id"] == own
    assert d2["decision"]["outcomes"][0]["interval"] == 1
    _rebuilds_the_same(m)


def test_redesign_sits_beside_one_scheduled_task(m):
    pump, fm = _mode(m)
    d = m.decide_failure_mode(fm["id"], "safety", {"outcomes": [
        {"outcome": "redesign"},
        {"outcome": "on_condition", "task": "Daily walk-round", "interval": 1, "interval_unit": "days"}]})["decision"]
    # The scheduled task is the decision's own; the redesign has no task.
    assert d["outcome"] == "on_condition"
    assert [(o["outcome"], o["task_id"] is not None) for o in d["outcomes"]] == [("on_condition", True),
                                                                                   ("redesign", False)]
    assert list(_live(m, pump["id"])) == ["Daily walk-round"]


@pytest.mark.parametrize("outcomes, words", [
    ([{"outcome": "rtf"}, {"outcome": "on_condition", "interval": 1}], "stand alone"),
    ([{"outcome": "accept"}, {"outcome": "fixed_interval", "interval": 1}], "stand alone"),
    ([{"outcome": "redesign"}, {"outcome": "on_condition", "interval": 1}, {"outcome": "redesign"}],
     "optionally with one redesign"),
    ([{"outcome": "on_condition", "interval": 1}, {"outcome": "fixed_interval"}], "needs its interval"),
    ([{"outcome": "on_condition", "interval": 1}, {"outcome": "nope"}], "one of"),
    ([{"outcome": "redesign", "task": "x"}, {"outcome": "on_condition", "interval": 1}], "doesn't"),
])
def test_combinations_that_cant_be_are_refused_with_what_is_allowed(m, outcomes, words):
    pump, fm = _mode(m)
    n = len(_events(m))
    with pytest.raises(Invalid) as err:
        m.decide_failure_mode(fm["id"], "safety", {"outcomes": outcomes})
    assert words in str(err.value)
    assert len(_events(m)) == n


def test_a_single_decision_emits_what_it_always_has(m):
    """Deciding one outcome (also given as a one-member outcomes list) emits the
    same events, with the same payload keys, as before combinations existed."""
    pump, fm = _mode(m)
    one = {"outcome": "on_condition", "task": "Vibration check", "interval": 1, "interval_unit": "months"}
    n = len(_events(m))
    m.decide_failure_mode(fm["id"], "operational", one)
    shape = [(e["type"], sorted(e["payload"]["changes"] if e["type"] == "failure_mode.analysed" else e["payload"]))
             for e in _events(m)[n:]]
    assert shape == [
        ("failure_mode.analysed", ["consequence", "outcome"]),
        ("task.added", ["failure_mode_id", "id", "interval", "name", "outcome", "position_id", "start", "unit"]),
        ("failure_mode.analysed", ["task_id"]),
    ]
    assert not _events(m, "failure_mode.outcomes_set")
    other = m.add_failure_mode(pump["id"], "Seal leaks")
    n = len(_events(m))
    m.decide_failure_mode(other["id"], "operational", {"outcomes": [one]})
    assert [e["type"] for e in _events(m)[n:]] == ["failure_mode.analysed", "task.added", "failure_mode.analysed"]
    assert "outcomes" not in m.rcm_mode(other["id"])["decision"]


def test_a_member_whose_task_goes_counts_as_scheduled_without_a_task(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    second = m.rcm_mode(fm["id"])["decision"]["outcomes"][1]["task_id"]
    m.retire_task(second, "Not needed")
    d = m.rcm_mode(fm["id"])["decision"]
    assert d["outcomes"][1] == {"outcome": "fixed_interval", "task_id": None}
    from backend.maintenance.service import _rcm_rollup

    assert _rcm_rollup(m._rcm_index(), {fm["id"]})["scheduled_without_task"] == 1


def test_copying_a_position_copies_its_combination(m):
    pump, fm = _mode(m)
    m.decide_failure_mode(fm["id"], "safety", COMBO)
    copy = m.copy_position(pump["id"], "Pump 2")
    [cm] = m.position(copy["id"])["failure_modes"]
    d = m.rcm_mode(cm["id"])["decision"]
    tasks = _live(m, copy["id"])
    assert [(o["outcome"], o["task_id"]) for o in d["outcomes"]] == [
        ("on_condition", tasks["Vibration check"]["id"]), ("fixed_interval", tasks["Replace the bearing"]["id"])]
    _rebuilds_the_same(m)


def test_advice_reads_every_member():
    assert rcm_decisions.advice("safety", "on_condition", ["on_condition", "fixed_interval"]) is None
    assert "combination" in rcm_decisions.advice("operational", "on_condition", ["on_condition", "fixed_interval"])
    assert "multiple failure would do" in rcm_decisions.advice("hidden", "on_condition",
                                                                ["on_condition", "fixed_interval"])
    assert rcm_decisions.advice("safety", "on_condition") is None


# ---- a worksheet: repeated rows build the combination, the export writes it back ------------

def _sheet_csv(rows) -> bytes:
    import csv
    import io

    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


SHEET_HEADER = ["Function", "Functional failure", "Failure mode", "Consequence", "Decision", "Task", "Interval",
                "Interval unit"]


def _import(m, pid, rows, dry_run=False):
    from backend.maintenance import rcm_sheet
    from backend.services import excel

    table = excel.read_csv(_sheet_csv([SHEET_HEADER, *rows]), "rcm.csv")
    return rcm_sheet.run(m, pid, table, rcm_sheet.default_options(table), dry_run=dry_run)


def _decisions(m, pid):
    """Each mode's decision as a comparable shape: outcomes (or the one), with
    each member's task, interval and unit; and the tasks outside it."""
    out = {}
    for fm in m.position(pid)["failure_modes"]:
        d = m.rcm_mode(fm["id"])["decision"] or {}
        members = d.get("outcomes") or ([{k: d.get(k) for k in ("outcome", "task", "interval", "interval_unit")}]
                                        if d else [])
        mine = {o.get("task_id") for o in d.get("outcomes") or []} | {d.get("task_id")}
        out[fm["text"]] = (
            m.rcm_mode(fm["id"])["consequence"],
            [(o["outcome"], o.get("task"), o.get("interval"), o.get("interval_unit")) for o in members],
            sorted((t["name"], t["outcome"]) for t in d.get("tasks") or [] if t["id"] not in mine),
        )
    return out


def test_repeated_rows_with_other_outcomes_build_a_combination_in_row_order(m):
    pid = m.create_position("Pump")["id"]
    rows = [
        ["Pump water", "No flow", "Bearing worn", "Safety", "On-condition", "Vibration check", "1", "months"],
        ["", "", "Bearing worn", "", "Fixed interval", "Replace the bearing", "24", "months"],
        # The same kind again with a task of its own: another member (one kind may repeat).
        ["", "", "Bearing worn", "", "On-condition", "Oil sample", "3", "months"],
        # The same task again: a repeat, passed over.
        ["", "", "Bearing worn", "", "On-condition", "Oil sample", "3", "months"],
        ["", "", "Seal leaks", "Environmental", "Failure finding", "Test the leak alarm", "6", "months"],
        ["", "", "Seal leaks", "", "Redesign", "", "", ""],
        # rtf can't join: the row passes over (a repeat), as before.
        ["", "", "Impeller wear", "Operational", "Fixed interval", "Swap impeller", "12", "months"],
        ["", "", "Impeller wear", "", "Run to failure", "", "", ""],
    ]
    preview = _import(m, pid, rows, dry_run=True)
    assert preview["ok"], preview["errors"]
    assert preview["counts"]["combinations"] == 2 and preview["counts"]["tasks"] == 5
    out = _import(m, pid, rows)
    assert out["ok"], out["errors"]
    got = _decisions(m, pid)
    assert got["Bearing worn"] == ("safety", [("on_condition", "Vibration check", 1, "months"),
                                              ("fixed_interval", "Replace the bearing", 24, "months"),
                                              ("on_condition", "Oil sample", 3, "months")], [])
    assert any("repeat" in w for w in out["warnings"])
    assert got["Seal leaks"] == ("environmental", [("failure_finding", "Test the leak alarm", 6, "months"),
                                                   ("redesign", None, None, None)], [])
    assert got["Impeller wear"][1] == [("fixed_interval", "Swap impeller", 12, "months")]
    _rebuilds_the_same(m)


def test_a_combination_exported_and_imported_gives_the_same_decisions(m):
    from backend.maintenance import fmea_sheet, rcm_sheet
    from backend.services import excel

    pump = m.create_position("Pump")
    fn = m.add_function(pump["id"], "Pump water")
    ff = m.add_functional_failure(fn["id"], "No flow")
    bearing = m.add_failure_mode(pump["id"], "Bearing worn", functional_failure_id=ff["id"])
    seal = m.add_failure_mode(pump["id"], "Seal leaks", functional_failure_id=ff["id"])
    alarm = m.add_failure_mode(pump["id"], "Leak alarm dead", functional_failure_id=ff["id"])
    plain = m.add_failure_mode(pump["id"], "Impeller wear", functional_failure_id=ff["id"])
    m.decide_failure_mode(bearing["id"], "safety", {"outcomes": [
        *COMBO["outcomes"], {"outcome": "on_condition", "task": "Oil sample", "interval": 3, "interval_unit": "months"}]})
    m.decide_failure_mode(seal["id"], "environmental", {"outcomes": [
        {"outcome": "redesign"},
        {"outcome": "on_condition", "task": "Daily walk-round", "interval": 1, "interval_unit": "days"}]})
    m.decide_failure_mode(alarm["id"], "hidden", {"outcomes": [
        {"outcome": "failure_finding", "task": "Test the alarm", "interval": 6, "interval_unit": "months"},
        {"outcome": "on_condition", "task": "Check the sensor", "interval": 1, "interval_unit": "months"},
        {"outcome": "fixed_interval", "task": "Replace the sensor", "interval": 5, "interval_unit": "years"}]})
    m.decide_failure_mode(plain["id"], "operational", {"outcome": "fixed_interval", "task": "Swap impeller",
                                                       "interval": 12, "interval_unit": "months"})
    rows = fmea_sheet.rows(m.rcm_worksheet(pump["id"], "this"))
    col = {h: i for i, h in enumerate(rows[0])}
    # One row per member, in its order (the redesign too; one kind twice).
    assert [(r[col["Failure mode"]], r[col["Decision"]], r[col["Task"]]) for r in rows[1:]] == [
        ("Bearing worn", "On condition", "Vibration check"),
        ("Bearing worn", "Fixed interval", "Replace the bearing"),
        ("Bearing worn", "On condition", "Oil sample"),
        ("Seal leaks", "On condition", "Daily walk-round"),
        ("Seal leaks", "Redesign", ""),
        ("Leak alarm dead", "Failure finding", "Test the alarm"),
        ("Leak alarm dead", "On condition", "Check the sensor"),
        ("Leak alarm dead", "Fixed interval", "Replace the sensor"),
        ("Impeller wear", "Fixed interval", "Swap impeller"),
    ]
    table = excel.read_csv(_sheet_csv(rows), "Pump FMECA.csv")
    fresh = m.create_position("Pump 2")["id"]
    out = rcm_sheet.run(m, fresh, table, rcm_sheet.default_options(table), dry_run=False)
    assert out["ok"], out["errors"]
    assert _decisions(m, fresh) == _decisions(m, pump["id"])
    # Onto the same position: nothing to add.
    events = m.s.event_count(ORG)
    assert rcm_sheet.run(m, pump["id"], table, rcm_sheet.default_options(table), dry_run=False)["ok"]
    assert m.s.event_count(ORG) == events
    _rebuilds_the_same(m)


def test_the_tabs_csv_layout_reads_back_as_the_combination(m):
    """The RCM tab's Export CSV (frontend/src/rcmImport.js positionRcmRows, its
    test writes these rows): short outcome labels, a member per row."""
    pid = m.create_position("Pump")["id"]
    rows = [
        ["Pump water", "No flow", "Bearing worn", "Safety", "On-condition", "Vibration check", "1", "months"],
        ["Pump water", "No flow", "Bearing worn", "", "Fixed-interval", "Replace the bearing", "24", "months"],
    ]
    assert _import(m, pid, rows)["ok"]
    [d] = [m.rcm_mode(fm["id"])["decision"] for fm in m.position(pid)["failure_modes"]]
    assert [(o["outcome"], o["task"]) for o in d["outcomes"]] == [("on_condition", "Vibration check"),
                                                                  ("fixed_interval", "Replace the bearing")]


# ---- several tasks of one kind (Derryn, 9 Nov 2026) ----------------------------------------

POOL = {"outcomes": [
    {"outcome": "fixed_interval", "task": "Acid top-up", "interval": 1, "interval_unit": "weeks"},
    {"outcome": "fixed_interval", "task": "Deep clean", "interval": 12, "interval_unit": "months"},
    {"outcome": "on_condition", "task": "Shop water test", "interval": 1, "interval_unit": "months",
     "on_found": "Adjust the dosing"},
]}


def _members(m, mode_id):
    return [(o["outcome"], o.get("task"), o.get("interval")) for o in m.rcm_mode(mode_id)["decision"]["outcomes"]]


def test_one_kind_may_come_several_times_each_with_its_own_task(m):
    pump, fm = _mode(m, "pH drifts")
    d = m.decide_failure_mode(fm["id"], "operational", POOL)["decision"]
    assert _members(m, fm["id"]) == [("fixed_interval", "Acid top-up", 1), ("fixed_interval", "Deep clean", 12),
                                     ("on_condition", "Shop water test", 1)]
    ids = [o["task_id"] for o in d["outcomes"]]
    assert len(set(ids)) == 3 and d["task_id"] == ids[0]
    assert {n: t["outcome"] for n, t in _live(m, pump["id"]).items()} == {
        "Acid top-up": "fixed_interval", "Deep clean": "fixed_interval", "Shop water test": "on_condition"}
    assert d["outcomes"][2]["on_found"] == "Adjust the dosing"
    # The payload is the list it always was: one entry per member, now with a kind twice.
    [ev] = _events(m, "failure_mode.outcomes_set")
    assert [o["outcome"] for o in ev["payload"]["outcomes"]] == ["fixed_interval", "fixed_interval", "on_condition"]
    # The same again, as a reader sends it back (each member by its task_id): nothing changes.
    n = len(_events(m))
    again = {"outcomes": [{"outcome": o["outcome"], "task_id": o["task_id"]} for o in d["outcomes"]]}
    m.decide_failure_mode(fm["id"], "operational", again)
    assert len(_events(m)) == n
    # Without task_ids, by name or by the n-th of its kind: the same tasks, nothing new.
    m.decide_failure_mode(fm["id"], "operational", POOL)
    assert len(_events(m)) == n
    _rebuilds_the_same(m)


def test_taking_one_member_off_keeps_the_others_by_their_task(m):
    pump, fm = _mode(m, "pH drifts")
    d = m.decide_failure_mode(fm["id"], "operational", POOL)["decision"]
    weekly, annual, shop = [o["task_id"] for o in d["outcomes"]]
    # Leave the weekly top-up out: the annual deep clean and the shop test keep their tasks.
    out = m.decide_failure_mode(fm["id"], "operational", {"outcomes": [
        {"outcome": "fixed_interval", "task_id": annual}, {"outcome": "on_condition", "task_id": shop}]})["decision"]
    assert [o["task_id"] for o in out["outcomes"]] == [annual, shop]
    assert out["task_id"] == annual
    assert set(_live(m, pump["id"])) == {"Deep clean", "Shop water test"}
    # Its on_found went with the shop test's task, not with its place in the list.
    assert out["outcomes"][1]["on_found"] == "Adjust the dosing"
    # A member renamed by its task_id renames that task only.
    out = m.decide_failure_mode(fm["id"], "operational", {"outcomes": [
        {"outcome": "fixed_interval", "task_id": annual, "task": "Deep clean and descale", "interval": 6,
         "interval_unit": "months"}, {"outcome": "on_condition", "task_id": shop}]})["decision"]
    assert _members(m, fm["id"]) == [("fixed_interval", "Deep clean and descale", 6),
                                     ("on_condition", "Shop water test", 1)]
    _rebuilds_the_same(m)


def test_one_task_cannot_be_two_members_and_one_redesign_at_most(m):
    pump, fm = _mode(m, "pH drifts")
    d = m.decide_failure_mode(fm["id"], "operational", POOL)["decision"]
    with pytest.raises(Invalid, match="named twice"):
        m.decide_failure_mode(fm["id"], "operational", {"outcomes": [
            {"outcome": "fixed_interval", "task_id": d["outcomes"][0]["task_id"]},
            {"outcome": "fixed_interval", "task_id": d["outcomes"][0]["task_id"]}]})
    assert rcm_decisions.combination_ok(["fixed_interval", "fixed_interval"])
    assert rcm_decisions.combination_ok(["fixed_interval", "fixed_interval", "redesign"])
    assert rcm_decisions.combination_ok(["on_condition", "redesign"])
    assert not rcm_decisions.combination_ok(["on_condition", "redesign", "redesign"])
    assert not rcm_decisions.combination_ok(["fixed_interval", "rtf"])
    # Failure finding is still for hidden failures only.
    with pytest.raises(Invalid, match="hidden failures only"):
        m.decide_failure_mode(fm["id"], "operational", {"outcomes": [
            *POOL["outcomes"], {"outcome": "failure_finding", "task": "Test alarm", "interval": 6}]}, hidden=False)


def test_evidence_per_member_of_one_kind_names_the_task_that_has_none(m):
    from types import SimpleNamespace

    analysis = SimpleNamespace(id="sa1", name="Top-up interval", kind="optimal_replacement",
                               results={"beneficial": True, "optimal_time": 1, "savings": 0.2, "unit": "weeks"})
    pump, fm = _mode(m, "pH drifts")
    d = m.decide_failure_mode(fm["id"], "operational", {"outcomes": [
        {**POOL["outcomes"][0], "evidence": {"type": "strategy_analysis", "id": "sa1"}}, POOL["outcomes"][1]]})["decision"]
    out = rcm_decisions.resolve_decision(d, lambda t, i: analysis if (t, i) == ("strategy_analysis", "sa1") else None)
    assert out["status"] == "partly"
    assert out["reason"] == "Partly evidenced: the fixed interval “Deep clean” task has none."
    assert [o["status"] for o in out["outcomes"]] == ["supported", "unevidenced"]
