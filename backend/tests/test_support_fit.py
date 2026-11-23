"""A supporting task's impact fitted from history (forecast plan step 9, Nov 2026; forecast-rules 4.7): each item's
time cut into on time and overdue, a covariate fit (SurPyval Weibull PH, overdue as a time-varying covariate)
and a group comparison beside it, the 90% two-sided range, "not shown to matter" where it includes 1, and the
identifiability check when service timing barely varies."""

import numpy as np
import pytest

from backend.maintenance import support_fit as sf
from backend.tests.test_maintenance_forecast_engine import _m, _rebuilds_the_same


def _simulate(k: float, intervals, n: int = 80, seed: int = 7, limit: float = 100.0, alpha=1500.0, beta=2.5):
    """Items aged on a Weibull hazard, × k while more than ``limit`` hours past their last service; each service
    gap drawn from ``intervals``; censored at 4,000 h."""
    rng = np.random.default_rng(seed)

    def cum(t):
        return (t / alpha) ** beta

    units = []
    for _ in range(n):
        rows, served, acc, target = [], 0.0, 0.0, rng.exponential()
        failed = False
        while not failed and served < 4000:
            nxt = min(served + float(rng.choice(intervals)), 4000.0)
            for lo, hi, z in ((served, min(nxt, served + limit), 0), (served + limit, nxt, 1)):
                if hi <= lo:
                    continue
                rate = k if z else 1.0
                inc = rate * (cum(hi) - cum(lo))
                if acc + inc >= target:
                    tf = alpha * (cum(lo) + (target - acc) / rate) ** (1 / beta)
                    rows.append((lo, tf, z))
                    failed = True
                    break
                acc += inc
                rows.append((lo, hi, z))
            served = nxt
        units.append({"rows": rows, "failed": failed})
    return units


def test_a_known_impact_is_found_with_its_range():
    got = sf.estimate(_simulate(2.0, [60, 90, 120, 160, 200]))
    assert got["identifiable"] and got["shown"]
    lo, hi = got["range"]
    assert lo < 2.0 < hi and got["k"] == pytest.approx(2.0, rel=0.4)
    assert "covariate fit" in got["method"] and got["group"]["k"] > 1
    assert got["words"].startswith("Fitted: failure rate ×")


def test_no_effect_is_not_shown_to_matter():
    got = sf.estimate(_simulate(1.0, [60, 90, 120, 160, 200], seed=3))
    assert got["identifiable"] and not got["shown"] and got["range"][0] < 1 < got["range"][1]
    assert got["words"].startswith("Not shown to matter in this data")


def test_service_timing_that_barely_varies_cant_be_estimated():
    got = sf.estimate(_simulate(2.0, [50], seed=5))  # always on time: never overdue
    assert not got["identifiable"] and got["k"] is None
    assert "Service timing barely varies" in got["words"]
    few = sf.estimate([{"rows": [(0, 100, 0), (100, 150, 1)], "failed": True}])
    assert not few["identifiable"] and "Too few failures" in few["words"]


def test_the_history_from_the_records():
    """One pump fitted 1 Jan, its strainer cleaned (every 30 days) on 21 Jan and 1 Apr, failed 11 Apr: on time
    to 21 Jan + 30 days (20 + 30 days), overdue from 20 Feb to 1 Apr (40 days), on time again to 11 Apr (10)."""
    m = _m("org-support-fit")
    m.today = lambda: "2026-11-24"
    pump = m.create_position("Pump")["id"]
    seal = m.add_failure_mode(pump, "Seal wears out")["id"]
    task = m.create_task(pump, "Clean the strainer", 30, "days")["id"]
    m.set_task_support(task, {"failure_mode_ids": [], "impact": {"form": "hazard_ratio", "k": 2}})
    m.fit(pump, new_item={"name": "Pump 1"}, on="2026-01-01")
    for day in ("2026-01-21", "2026-04-01"):
        wo = m.open_work_order(pump, "Clean the strainer", type="preventive", task_id=task, opened=day)
        m.close_work_order(wo["id"], [{"kind": "other"}], on=day)
    m.remove(pump, on="2026-04-11", reason="failure", failure_mode_id=seal)
    units, info = sf.history(m, m._get(task, "Task"))
    assert info["services"] == 2 and info["clock"] == "days on the calendar"
    assert units == [{"rows": [(0.0, 20.0, 0), (20.0, 50.0, 0), (50.0, 90.0, 1), (90.0, 100.0, 0)], "failed": True,
                      "position": pump}]
    out = m.fit_support(task)
    assert not out["identifiable"] and "Too few failures" in out["words"]
    assert out["history"]["items"] == 1
    _rebuilds_the_same(m)


def test_using_a_fit_keeps_its_evidence():
    m = _m("org-support-fit-use")
    pos = m.create_position("Pump")["id"]
    task = m.create_task(pos, "Grease", 50, "hours")["id"]
    evidence = {"method": "covariate fit", "k": 1.92, "low": 1.25, "high": 2.95, "failures": 60,
                "overdue_share": 0.31, "fitted_on": "2026-11-24"}
    view = m.set_task_support(task, {"failure_mode_ids": [], "impact": {"form": "hazard_ratio", "k": 1.92},
                                     "source": "fitted", "evidence": evidence})
    assert view["support"]["source"] == "fitted" and view["support"]["evidence"]["low"] == 1.25
    assert "90% two-sided 1.2 to 3" in view["support"]["words"] or "90% two-sided 1.3 to 3" in view["support"]["words"]
