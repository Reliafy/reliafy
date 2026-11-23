"""Optimise for a supporting task (forecast plan step 8; forecast-rules 4.4, decision 6): with a one-number
impact (× k if it isn't done) the answer is a break-even, never an interval. In words: it pays for itself
if it costs less than the failures one interval of it holds off. The plan's figures:

* 4.5, the oil change: $180,000 × (0.688 ÷ 7,300 h) × 1.5 × 250 h = $6,360 a change; it costs $562.50.
* 4.6, greasing: about $58 a time with the inspection in place (a problem costs 91.8% × $160 + 8.2% × $900),
  $237 without it (each one a $900 failure).
"""

import pytest

from backend.maintenance import support_whatif as sw
from backend.maintenance import task_optimise
from backend.tests.test_forecast_lines import _deck
from backend.tests.test_support_whatif import _truck, setting  # noqa: F401


def test_4_5_the_oil_change_break_even(setting):  # noqa: F811
    m, db, fetch = setting
    _truck_id, oil = _truck(m, db)
    got = sw.break_even(m, fetch, oil)
    assert got["kind"] == "break_even" and got["interval"] is None and "curve" in got["interval_needs"]
    assert got["break_even"] == pytest.approx(6360, rel=0.005)
    assert got["task_cost"] == pytest.approx(562.5) and got["ratio"] == pytest.approx(562.5 / 6360, rel=0.01)
    assert got["words"].startswith("It pays for itself if one doing costs less than $6,3")
    assert got["assumed"]
    # In the Optimise… answer, beside the modes (none: it supports the whole life).
    out = task_optimise.optimise(m, db, ["org-forecast-lines"], set(), oil)
    assert out["support"]["break_even"] == pytest.approx(got["break_even"])


def test_4_6_greasing_with_and_without_the_inspection(setting):  # noqa: F811
    m, db, fetch = setting
    _deck_id, grease, insp, modes = _deck(m, db)
    m.set_task_support(grease, {"failure_mode_ids": [], "impact": {"form": "hazard_ratio", "k": 3},
                                "source": "assumed"})
    for fm in modes:
        m.set_mode_response(fm, "found", name="Replace the bearing", cost=160)
    with_check = sw.break_even(m, fetch, grease)
    assert with_check["break_even"] == pytest.approx(58, abs=1.5)
    m.retire_task(insp)
    without = sw.break_even(m, fetch, grease)
    assert without["break_even"] == pytest.approx(237, abs=3)


def test_no_impact_or_no_cost_gives_no_number(setting):  # noqa: F811
    m, db, fetch = setting
    _truck_id, oil = _truck(m, db)
    worn = m._modes_on(_truck_id)[0]["id"]
    m.set_mode_costs(worn, failure_cost=None)
    got = sw.break_even(m, fetch, oil)
    assert got["break_even"] is None and "no cost of a failure" in got["gaps"][0]
    m.set_task_support(oil, {"failure_mode_ids": []})
    assert sw.break_even(m, fetch, oil) is None
