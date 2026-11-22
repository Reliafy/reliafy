"""Availability read at the times asked about (the repairable calculator's "At a time" and
"Out to a horizon" questions): checked by hand on one block with exponential failures and repairs."""

import math

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.tests.test_availability_paid import client  # noqa: E402,F401
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401
from backend.tests.test_rbd_costs import _exp, _node  # noqa: E402

LAM = 0.01  # failures per hour (mean life 100 h)
MU = 0.1  # repairs per hour (mean repair 10 h)


def _one_block():
    io = [{"id": "input", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "Input"}},
          {"id": "output", "type": "output", "position": {"x": 300, "y": 0}, "data": {"label": "Output"}}]
    pump = _node("pump", model=_exp(LAM), repair=_exp(MU))
    return {"repairable": True, "unit": "hours", "nodes": [*io, pump],
            "edges": [{"id": "e0", "source": "input", "target": "pump"},
                      {"id": "e1", "source": "pump", "target": "output"}]}


def _a(t):
    return MU / (LAM + MU) + LAM / (LAM + MU) * math.exp(-(LAM + MU) * t)


def _mission(t):
    s = LAM + MU
    return MU / s + LAM / (s * s * t) * (1 - math.exp(-s * t))


@pytest.mark.parametrize("t", [5.0, 50.0, 500.0])
def test_point_and_mission_availability_match_the_closed_form(t):
    out = ra.availability_at_times(_one_block(), [t])
    assert out["status"] == "ok" and out["method"] == "exact"
    row = out["rows"][0]
    assert row["t"] == t
    assert row["availability"] == pytest.approx(_a(t), rel=1e-6)
    assert row["mission_availability"] == pytest.approx(_mission(t), rel=1e-5)
    # Downtime by t is (1 - mean availability) * t.
    assert row["downtime"] == pytest.approx((1 - _mission(t)) * t, rel=1e-4)
    assert row["expected_failures"] > 0


def test_many_times_in_order_and_zero():
    out = ra.availability_at_times(_one_block(), [0, 10, 100])
    assert [r["t"] for r in out["rows"]] == [0.0, 10.0, 100.0]
    assert out["rows"][0]["availability"] == 1.0
    assert out["rows"][1]["availability"] > out["rows"][2]["availability"] > MU / (LAM + MU)


def test_endpoint_carries_at_times_for_free_users(client):
    from backend.tests.test_availability_paid import FREE

    client.act_as(FREE)
    r = client.post("/api/rbds/analyze", json={"graph": _one_block(), "t_max": 200, "simulate": False,
                                               "times": [50, 150]})
    assert r.status_code == 200, r.text
    at = r.json()["exact"]["at_times"]
    assert at["status"] == "ok" and [row["t"] for row in at["rows"]] == [50.0, 150.0]
    assert at["rows"][0]["availability"] == pytest.approx(_a(50), rel=1e-6)
    # The horizon's own figures (out to 200 h) come beside it.
    assert r.json()["exact"]["mission_availability"] == pytest.approx(_mission(200), rel=1e-5)
    bad = client.post("/api/rbds/analyze", json={"graph": _one_block(), "simulate": False, "times": [-3]})
    assert bad.status_code == 422


def test_check_times_refuses_negative_and_infinite():
    from backend.routers.rbds import _check_times

    assert _check_times(None) is None
    assert _check_times([1, 2.5]) == [1.0, 2.5]
    for bad in ([-1], [float("inf")], [float("nan")]):
        with pytest.raises(ra.AnalysisError):
            _check_times(bad)


def test_connector_reads_availability_at_times(env):
    from backend.tests.test_rbd_discount_crews import _m as m
    rid = _ok(_call(env.token[A], "change", {"action": "rbd_create", "name": "One pump", "unit": "Hours",
        "repairable": True,
        "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                  {"id": "p", "type": "component", "model": m("exponential", failure_rate=LAM), "repair": m("exponential", failure_rate=MU)}],
        "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}))["id"]
    res = _ok(_call(env.token[A], "analyse", {"action": "rbd", "rbd_id": rid, "simulate": False,
                                                   "t_max": 200, "times": [25, 100]}))
    rows = res["exact"]["at_times"]["rows"]
    assert [r["t"] for r in rows] == [25.0, 100.0]
    assert rows[1]["availability"] == pytest.approx(_a(100), rel=1e-6)
    assert res["exact"]["mission_availability"] == pytest.approx(_mission(200), rel=1e-5)
    bad = _err(_call(env.token[A], "analyse", {"action": "rbd", "rbd_id": rid, "times": [-1]}))
    assert "times" in str(bad)
