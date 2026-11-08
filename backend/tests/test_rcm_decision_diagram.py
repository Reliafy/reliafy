"""The RCM decision diagram (SAE JA1011, RCM II): two questions (evident or
hidden, then the consequence category), the task order, the refusals and the
default actions (backend/maintenance/rcm_decisions.py), as the service applies
them, with the old fifth value "hidden" read and accepted as an alias."""

import pytest

from backend.maintenance import fmea_sheet, rcm_decisions
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import rcm_import

ORG = "user-a"
FF = {"outcome": "failure_finding", "task": "Test the trip", "interval": 6, "interval_unit": "months"}
COMBO = {"outcomes": [{"outcome": "on_condition", "task": "Vibration", "interval": 1, "interval_unit": "months"},
                      {"outcome": "fixed_interval", "task": "Replace", "interval": 2, "interval_unit": "years"}]}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _mode(m, text="Mode"):
    pid = m.create_position(f"Pump {text}")["id"]
    return m.add_failure_mode(pid, text)["id"]


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


@pytest.mark.parametrize("hidden,consequence,decision,words", [
    (False, "safety", {"outcome": "rtf", "rtf_basis": "random"}, "A safety consequence can't be run to failure"),
    (False, "environmental", {"outcome": "accept"}, "An environmental consequence can't be run to failure"),
    (True, "safety", {"outcome": "rtf", "rtf_basis": "random"}, "risk of the multiple failure tolerable"),
    (False, "operational", FF, "Failure finding is for hidden failures only"),
])
def test_the_diagram_refuses(m, hidden, consequence, decision, words):
    mode = _mode(m)
    n = m.s.event_count(ORG)
    with pytest.raises(Invalid, match=words):
        m.decide_failure_mode(mode, consequence, decision, hidden=hidden)
    assert m.s.event_count(ORG) == n  # nothing written


@pytest.mark.parametrize("hidden,consequence,decision", [
    (False, "operational", {"outcome": "rtf", "rtf_basis": "uneconomic"}),
    (True, "operational", {"outcome": "accept"}),
    (True, "safety", FF),
    (False, "safety", {"outcome": "redesign"}),
    (False, "safety", COMBO),
    (True, "environmental", COMBO),
    (None, None, {"outcome": "rtf", "rtf_basis": "random"}),  # not answered yet: nothing hangs on it
])
def test_the_diagram_allows(m, hidden, consequence, decision):
    mode = _mode(m)
    out = m.decide_failure_mode(mode, consequence, decision, hidden=hidden if hidden is not None else ...)
    assert out["hidden"] is hidden and out["consequence"] == consequence
    assert "kept as it was saved" not in out.get("advice", "")
    _same_after_rebuild(m)


@pytest.mark.parametrize("hidden,consequence,outcome,then,redesign", [
    (False, "safety", "redesign", None, "compulsory"),
    (False, "environmental", "redesign", None, "compulsory"),
    (False, "operational", "rtf", None, "desirable"),
    (False, "non_operational", "rtf", None, "desirable"),
    (True, "safety", "failure_finding", "redesign", "compulsory"),
    (True, "environmental", "failure_finding", "redesign", "compulsory"),
    (True, "operational", "failure_finding", "rtf", "desirable"),
    (True, "non_operational", "failure_finding", "rtf", "desirable"),
])
def test_each_default_action(hidden, consequence, outcome, then, redesign):
    d = rcm_decisions.default_action(hidden, consequence)
    assert (d["outcome"], d["then"], d["redesign"]) == (outcome, then, redesign) and d["text"]


def test_no_default_action_until_the_category_is_known():
    assert rcm_decisions.default_action(None, None) is None
    assert "multiple failure would do" in rcm_decisions.default_action(True, None)["text"]


def test_a_saved_hidden_consequence_reads_as_hidden_with_its_category_to_say(m):
    """A mode saved with the old fifth value (the event says consequence: hidden)."""
    mode = _mode(m)
    m._emit("failure_mode.updated", {"id": mode, "changes": {"consequence": "hidden"}})
    read = m.rcm_mode(mode)
    assert read["hidden"] is True and read["consequence"] is None
    assert "say what the multiple failure would do" in read["advice"]
    # Saying the category keeps the first answer.
    out = m.decide_failure_mode(mode, "safety", FF)
    assert out["hidden"] is True and out["consequence"] == "safety" and "advice" not in out
    _same_after_rebuild(m)


def test_the_alias_sets_hidden_and_keeps_the_category(m):
    mode = _mode(m)
    m.decide_failure_mode(mode, "operational", hidden=False)
    out = m.decide_failure_mode(mode, "hidden", FF)
    assert out["hidden"] is True and out["consequence"] == "operational"
    with pytest.raises(Invalid, match="says the failure is hidden, but hidden is false"):
        m.decide_failure_mode(mode, "hidden", hidden=False)
    with pytest.raises(Invalid, match="hidden is true"):
        m.decide_failure_mode(mode, hidden="yes")
    _same_after_rebuild(m)


def test_editing_the_category_of_an_old_hidden_mode_keeps_it_hidden(m):
    mode = _mode(m)
    m._emit("failure_mode.updated", {"id": mode, "changes": {"consequence": "hidden"}})
    m.update_failure_mode(mode, consequence="environmental")
    read = m.rcm_mode(mode)
    assert read["hidden"] is True and read["consequence"] == "environmental"
    _same_after_rebuild(m)


def test_a_decision_the_diagram_refuses_now_is_kept_and_flagged(m):
    """Saved before the diagram was enforced (or imported): never refused on read."""
    mode = _mode(m)
    out = m.decide_failure_mode(mode, "safety", {"outcome": "rtf", "rtf_basis": "random"}, strict=False)
    assert out["decision"]["outcome"] == "rtf"
    assert "can't be run to failure" in out["advice"] and "kept as it was saved" in out["advice"]
    # A category and no answer to the first question reads as evident (the old five values were exclusive).
    assert out["hidden"] is False


def test_a_hidden_failure_run_to_failure_asks_about_failure_finding():
    words = rcm_decisions.advice("operational", "rtf", hidden=True)
    assert "failure-finding task before no scheduled maintenance" in words


def test_the_vocabulary_has_two_questions_and_plain_labels():
    options = rcm_decisions.options()
    assert [o["id"] for o in options["evident_hidden"]] == ["evident", "hidden"]
    assert [c["id"] for c in options["consequences"]] == ["safety", "environmental", "operational",
                                                          "non_operational"]
    assert options["task_order"] == ["on_condition", "fixed_interval", "failure_finding"]
    assert [o["label"] for o in options["outcomes"]] == ["On condition", "Fixed interval", "Run to failure",
                                                         "Failure finding", "Redesign", "Accept"]
    assert all(c["worth_doing"] for c in options["consequences"])


def test_labels_and_the_import_read_both_answers():
    assert rcm_decisions.consequence_label(True, "safety") == "Hidden · Safety"
    assert rcm_decisions.consequence_label(False, "operational") == "Operational"
    assert rcm_decisions.consequence_label(True, None) == "Hidden"
    assert rcm_decisions.consequence_label(None, None) == ""
    for cell, cat in (("Hidden · Safety", "safety"), ("H S", "safety"), ("Hidden - non-operational", "non_operational"),
                      ("Hidden", None)):
        assert rcm_import.guess_consequence(cell) == "hidden"
        assert rcm_import.category_beside_hidden(cell) == cat, cell


def test_the_fmeca_export_writes_both_answers(m):
    pid = m.create_position("Pump")["id"]
    mode = m.add_failure_mode(pid, "Trip dead")["id"]
    m.decide_failure_mode(mode, "safety", FF, hidden=True)
    rows = fmea_sheet.rows(m.rcm_worksheet(pid, "this"))
    col = rows[0].index("Consequence")
    assert [r[col] for r in rows[1:] if r[col]] == ["Hidden · Safety"]
