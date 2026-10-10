"""What to improve: step limits per lever (#324). A step stops at
RePyability's range for the lever (a coverage can't pass 1, a count is
whole) and at the user's own limit, in the values shown."""

import matplotlib

matplotlib.use("Agg")

import math

import pytest

from backend.services import rbd_sensitivity as rs
from backend.services.rbd_analysis import AnalysisError
from backend.tests.test_availability_paid import FREE, client  # noqa: F401 - fixture
from backend.tests.test_rbd_costs import _exp, _ln, _node, _series, _w
from backend.tests.test_rbd_sensitivity import _built, _priced, _rows


def _tested():
    """A valve whose proof tests find 90% of failures, then a pump."""
    return _series(
        _node("valve", model=_exp(2e-6), instant_repair=True,
              inspection={"interval": 8760, "cost": 500, "coverage": 0.9, "full_test": 43800}),
        _node("pump", model=_w(1000, 2), repair=_ln(2, 0.5)))


def _crewed():
    """Two exponential pumps in series sharing one repair crew: exact (the
    crews' Markov chain), with one more crew as a lever."""
    return _series(_node("a", model=_exp(1e-3), repair=_exp(0.1)), _node("b", model=_exp(2e-3), repair=_exp(0.2)),
                   repair_crews={"crews": 1})


def test_a_step_stops_at_the_users_limit():
    graph = _priced()
    free = _rows(rs.analyze_sensitivity(graph))
    row = free["pump|repairability.mu"]
    assert row["direction"] == "decrease" and "limit" not in row
    floor = (row["shown_value"] + row["shown_to"]) / 2  # half a step away
    out = _rows(rs.analyze_sensitivity(graph, limits={"pump|repairability.mu": {"min": floor}}))
    got = out["pump|repairability.mu"]
    assert got["limited"] == "yours" and got["limit"] == {"min": floor}
    assert got["shown_to"] == pytest.approx(floor, rel=1e-9)
    assert got["change"] == "a shorter mean repair time, to your limit"
    # The effect is the diagram's exact value with the lever at the limit.
    rbd, working, broken = _built(graph)
    lever = next(lv for lv in rbd.levers() if lv.key == "pump" and lv.name == "repairability.mu")
    moved = rbd.with_levers({lever: got["to"]}).mean_unavailability()
    assert got["effect"]["availability"] == pytest.approx(rbd.mean_unavailability() - moved, rel=1e-9)
    assert 0 < got["effect"]["availability"] < free["pump|repairability.mu"]["effect"]["availability"]
    # Other levers are untouched.
    assert out["valve|reliability.failure_rate"]["to"] == free["valve|reliability.failure_rate"]["to"]


def test_a_lever_at_its_limit_is_unranked():
    graph = _priced()
    row = _rows(rs.analyze_sensitivity(graph))["pump|reliability.alpha"]
    out = rs.analyze_sensitivity(graph, limits={"pump|reliability.alpha": {"max": row["shown_value"]}})
    got = _rows(out)["pump|reliability.alpha"]
    assert got.get("effect") is None and got["unranked"].startswith("Already at your limit")
    assert got["rank"] == len(out["levers"]) or got["benefit"] is None


def test_a_rate_parameters_limit_is_on_its_mean():
    """An exponential life's lever is its rate: a shown maximum mean life is
    a minimum rate."""
    graph = _priced()
    row = _rows(rs.analyze_sensitivity(graph))["valve|reliability.failure_rate"]
    assert row["kind"] == "mean" and row["direction"] == "increase"
    cap = row["shown_value"] * 1.04
    got = _rows(rs.analyze_sensitivity(graph, limits={"valve|reliability.failure_rate": {"max": cap}}))
    got = got["valve|reliability.failure_rate"]
    assert got["shown_to"] == pytest.approx(cap) and got["to"] == pytest.approx(1 / cap)


def test_repyabilitys_range_stops_a_coverage_at_one():
    graph = _tested()
    rbd, _, _ = _built(graph)
    lever = next(lv for lv in rbd.levers() if lv.name == "inspection.coverage")
    assert lever.bounds[1] == 1.0
    out = _rows(rs.analyze_sensitivity(graph, step=0.5))
    got = out["valve|inspection.coverage"]
    assert got["to"] == 1.0 and got["limited"] == "range"
    assert got["change"] == "a higher proof-test coverage, to its limit"


def test_a_count_stops_at_the_users_limit():
    graph = _crewed()
    rows = _rows(rs.analyze_sensitivity(graph))
    assert rows["repair_crews"]["to"] == 2.0 and rows["repair_crews"]["effect"]
    out = _rows(rs.analyze_sensitivity(graph, limits={"repair_crews": {"max": 1}}))
    assert out["repair_crews"]["unranked"] == "Already at your limit." and not out["repair_crews"].get("effect")


def test_limits_are_checked():
    with pytest.raises(AnalysisError, match="not levers"):
        rs.analyze_sensitivity(_priced(), limits={"pump|nope": {"min": 1}})
    for bad in ({"x": 3}, {"x": {"min": "a"}}, {"x": {"min": 5, "max": 1}}, {"x": {"low": 1}},
                {"x": {"min": math.inf}}):
        with pytest.raises(AnalysisError):
            rs.parse_limits(bad)
    assert rs.parse_limits({"x": {"min": "", "max": None}}) == {}
    assert rs.options(limits={"x": {"min": 4}})["limits"] == {"x": {"min": 4.0}}
    assert "limits" not in rs.options()


def test_app_takes_limits(client):
    client.act_as(FREE)
    r = client.post("/api/rbds/sensitivity", json={"graph": _priced(),
                                                    "limits": {"pump|repairability.mu": {"min": 7.0}}})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["levers"] if x["id"] == "pump|repairability.mu")
    assert row["limit"] == {"min": 7.0}
    assert row.get("shown_to") is None or row["shown_to"] >= 7.0 - 1e-9
    bad = client.post("/api/rbds/sensitivity", json={"graph": _priced(), "limits": {"nope": {"min": 1}}})
    assert bad.status_code == 422
