"""The P-F calculator in a task's panel starts from the calculation saved with that task: in a
combination of tasks each member keeps its own evidence, so the starting inputs read the member's
(the decision's own evidence is empty there)."""

from types import SimpleNamespace

from backend.services import rcm_intervals


def _mode():
    member = {"outcome": "on_condition", "task_id": "t25", "evidence": {"type": "strategy_analysis", "id": "a1"}}
    other = {"outcome": "on_condition", "task_id": "t50", "evidence": None}
    return {"decision": {"outcome": "on_condition", "evidence": None, "outcomes": [member, other]}}


def _fetch(kind, aid):
    assert (kind, aid) == ("strategy_analysis", "a1")
    return SimpleNamespace(name="Belt: check interval", kind="on_condition_interval",
                           inputs={"pf_interval": 120.0, "pf_unit": "flight hours", "detection_probability": 0.9})


def test_a_members_saved_calculation_is_where_its_task_starts():
    got = rcm_intervals.starting_inputs(_mode(), [], _fetch, task_id="t25")
    assert got["previous"]["kind"] == "on_condition_interval"
    assert got["previous"]["inputs"]["pf_unit"] == "flight hours"
    assert got["evidence"]["id"] == "a1"


def test_a_task_without_its_own_evidence_falls_back_to_the_decisions():
    got = rcm_intervals.starting_inputs(_mode(), [], _fetch, task_id="t50")
    assert "previous" not in got and got["evidence"] is None
