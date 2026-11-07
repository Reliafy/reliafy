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
    ([{"outcome": "on_condition", "interval": 1}, {"outcome": "on_condition", "interval": 2}], "no outcome twice"),
    ([{"outcome": "redesign"}, {"outcome": "on_condition", "interval": 1},
      {"outcome": "fixed_interval", "interval": 2}], "redesign beside one"),
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
    assert "Hidden consequences usually take" in rcm_decisions.advice("hidden", "on_condition",
                                                                       ["on_condition", "fixed_interval"])
    assert rcm_decisions.advice("safety", "on_condition") is None
