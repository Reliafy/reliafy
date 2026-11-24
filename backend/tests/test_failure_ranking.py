"""The failure ranking (FRACAS) below a position: grouping, de-duplication of a report and
the corrective event that is the same failure, rates with exact Poisson 90% ranges, the
expected count at the pooled rate and its p-value, against hand-worked values."""

import pytest

from backend.maintenance import failure_ranking as fr
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _list, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401

ORG = "user-rank"
WINDOW = {"window": "range", "since": "2025-01-01", "until": "2025-04-10"}  # 100 days: 2,400 h at 24 h a day


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _fleet(m):
    """Fleet › Unit A › Pump (with an item), Unit B › Pump. No duty, no readings: 24 h a day."""
    fleet = m.create_position("Fleet")["id"]
    a = m.create_position("Unit A", parent_id=fleet)["id"]
    b = m.create_position("Unit B", parent_id=fleet)["id"]
    pa = m.create_position("Pump", parent_id=a)["id"]
    pb = m.create_position("Pump", parent_id=b)["id"]
    m.fit(pa, new_item={"name": "Pump A unit", "serial": "PA"}, on="2024-06-01")
    return {"fleet": fleet, "a": a, "b": b, "pa": pa, "pb": pb}


def _seed(m, ids):
    days = ["2025-01-10", "2025-01-25", "2025-02-14", "2025-03-01", "2025-03-20"]
    for d in days:
        m.file_failure_report(ids["pa"], "Seal leaking", occurred_on=d, failure_mode_text="Seal worn")
    m.file_failure_report(ids["pb"], "Seal leaking", occurred_on="2025-02-02", failure_mode_text="Seal worn")
    # A rejected report and a no-fault-found one: neither is a failure.
    rej = m.file_failure_report(ids["pb"], "Not a failure", occurred_on="2025-02-03")
    m.set_failure_report_status(rej["id"], "rejected", note="duplicate")
    nff = m.file_failure_report(ids["pa"], "Noisy", occurred_on="2025-02-20")
    m.set_failure_report_status(nff["id"], "no_fault_found", note="fine on the bench", tested_with="bench")
    # The pump's item removed for a failure on 3 Apr: no report names it, so it counts (sixth at Unit A).
    m.remove(ids["pa"], on="2025-04-03", reason="failure", failure_mode_text="Bearing seized")
    # A past fitment at Unit B's pump ending in a failure 2 days after its report: the same failure.
    m.add_past_fitment(ids["pb"], "2024-12-01", "2025-02-04", reason="failure", new_item={"name": "Pump B old"},
                       failure_mode_text="Seal worn")
    # Outside the window: not counted.
    m.file_failure_report(ids["pb"], "Old", occurred_on="2024-11-01")


def test_rates_ranges_expected_and_p_value_by_hand(m):
    ids = _fleet(m)
    _seed(m, ids)
    out = fr.failure_ranking(m, ids["fleet"], **WINDOW)
    assert out["window"] == {"kind": "range", "since": "2025-01-01", "until": "2025-04-10", "days": 100}
    rows = {r["name"]: r for r in out["rows"]}
    assert [r["name"] for r in out["rows"]] == ["Unit A", "Unit B"]
    a, b = rows["Unit A"], rows["Unit B"]
    # 5 reports + 1 logged removal at A; B: 1 report, its logged failure the same one (merged).
    assert (a["failures"], a["reports"], a["no_fault_found"]) == (6, 5, 1)
    assert (b["failures"], b["reports"]) == (1, 1)
    assert out["totals"]["merged"] == 1 and out["totals"]["failures"] == 7 and out["totals"]["no_fault_found"] == 1
    assert a["hours"] == pytest.approx(2400) and b["hours"] == pytest.approx(2400)
    # 6 in 2,400 h: 2.5 per 1,000 h; exact 90%: chi2(0.05, 12)/2 = 2.6130 and chi2(0.95, 14)/2 = 11.842.
    assert a["rate_per_1000h"]["value"] == pytest.approx(2.5)
    assert a["rate_per_1000h"]["lower"] == pytest.approx(2.6130 / 2.4, rel=1e-3)
    assert a["rate_per_1000h"]["upper"] == pytest.approx(11.842 / 2.4, rel=1e-3)
    # Pooled 7 in 4,800 h: A expects 3.5; P(X >= 6 | 3.5) = 1 - 0.85761 = 0.14239.
    assert a["expected"] == pytest.approx(3.5)
    assert a["p_value"] == pytest.approx(0.14239, abs=1e-4) and a["direction"] == "more"
    assert a["sentence"] == ("6 failures where 3.50 would be expected at the rate of everything here pooled; "
                             "this many or more would happen by chance about 1 time in 7.")
    # B: 1 where 3.5 expected: P(X <= 1 | 3.5) = 4.5 e^-3.5 = 0.13589.
    assert b["too_few"] is False and b["direction"] == "fewer" and b["p_value"] == pytest.approx(0.13589, abs=1e-4)
    assert "this few or fewer would happen by chance about 1 time in 7." in b["sentence"]
    assert a["share"] == pytest.approx(6 / 7) and b["cumulative_share"] == pytest.approx(1.0)
    assert out["sentence"].startswith("7 failures in 1 Jan 2025 to 10 Apr 2025 below Fleet.")


def test_zero_failures_has_an_upper_bound_only():
    r = fr.poisson_range(0, 1000)
    assert r["value"] == 0 and r["lower"] == 0
    assert r["upper"] == pytest.approx(2.9957, rel=1e-3)  # -ln(0.05)
    assert fr.poisson_range(3, 0) is None


def test_small_counts_are_too_few_to_tell(m):
    ids = _fleet(m)
    m.file_failure_report(ids["pa"], "Leak", occurred_on="2025-02-01")
    m.file_failure_report(ids["pa"], "Leak", occurred_on="2025-03-01")
    out = fr.failure_ranking(m, ids["fleet"], **WINDOW)
    a = next(r for r in out["rows"] if r["name"] == "Unit A")
    assert a["too_few"] is True and a["sentence"].endswith("too few to tell apart from chance.")


def test_chance_words():
    assert fr.chance_words(0.0004) == "less than 1 time in 1,000"
    assert fr.chance_words(0.0021) == "about 1 time in 480"
    assert fr.chance_words(0.35) == "about 4 times in 10"


def test_group_by_failure_mode_and_part(m):
    ids = _fleet(m)
    _seed(m, ids)
    modes = fr.failure_ranking(m, ids["fleet"], group_by="failure_mode", **WINDOW)
    by = {r["name"]: r for r in modes["rows"]}
    # Seal worn: 5 at A + 1 at B; it is on both pumps (4,800 h). Bearing seized: 1, on A's pump only.
    assert by["Seal worn"]["failures"] == 6 and by["Seal worn"]["hours"] == pytest.approx(4800)
    assert by["Bearing seized"]["failures"] == 1 and by["Bearing seized"]["hours"] == pytest.approx(2400)
    assert modes["rows"][0]["name"] == "Seal worn"
    # Open in › Failure reports: both pumps' "Seal worn" modes, so the list shows all six (and the no-fault-found
    # report has no mode).
    ids_ = by["Seal worn"]["filter"]["failure_mode_id"]
    assert len(ids_.split(",")) == 2
    listed = m.failure_reports(ids["fleet"], failure_mode_id=ids_, since="2025-01-01", until="2025-04-10")
    assert listed["total"] == 6
    parts = fr.failure_ranking(m, ids["fleet"], group_by="part", **WINDOW)
    # No part numbers or classes here: every failure in the one "not recorded" row, with no rate.
    assert [r["name"] for r in parts["rows"]] == ["No part or item class recorded"]
    assert parts["rows"][0]["rate_per_1000h"] is None and parts["rows"][0]["expected"] is None


def test_rank_by_rate_and_cost_and_the_unit_opened(m):
    ids = _fleet(m)
    _seed(m, ids)
    mode = next(fm for fm in m.position(ids["pb"])["failure_modes"] if fm["text"] == "Seal worn")
    m.set_mode_costs(mode["id"], failure_cost=1000, downtime_hours=8)
    out = fr.failure_ranking(m, ids["fleet"], rank_by="cost", **WINDOW)
    # Only B's seal mode has a cost: B ranks first by cost; A's six have none set.
    assert out["rows"][0]["name"] == "Unit B" and out["rows"][0]["cost"] == pytest.approx(1000)
    assert out["rows"][0]["downtime_hours"] == pytest.approx(8)
    assert out["totals"]["cost_missing"] == 6
    # Opened at Unit A: its pump is the one group.
    inner = fr.failure_ranking(m, ids["a"], **WINDOW)
    assert [r["name"] for r in inner["rows"]] == ["Pump"] and inner["rows"][0]["failures"] == 6


def test_empty_window_and_bad_arguments(m):
    ids = _fleet(m)
    out = fr.failure_ranking(m, ids["fleet"])
    assert out["totals"]["failures"] == 0 and out["sentence"].startswith("No failures recorded in the last 12 months")
    assert out["window"]["kind"] == "12m"
    with pytest.raises(Invalid, match="group_by"):
        fr.failure_ranking(m, ids["fleet"], group_by="colour")
    with pytest.raises(Invalid, match="rank_by"):
        fr.failure_ranking(m, ids["fleet"], rank_by="mood")


def test_duty_basis_counts_its_hours(m):
    ids = _fleet(m)
    _seed(m, ids)
    m.set_operating_plan(ids["a"], {"background": {"kind": "rate", "amount": 6, "per": "day"}}, from_="2024-01-01")
    out = fr.failure_ranking(m, ids["fleet"], rank_by="rate", **WINDOW)
    rows = {r["name"]: r for r in out["rows"]}
    assert rows["Unit A"]["hours"] == pytest.approx(600, rel=1e-6)
    # Ranked by rate, the answer gives the top group's rate (a share of summed rates means nothing).
    # A: 6 in 600 h = 10 per 1,000 h; B: 1 in 2,400 h.
    assert out["rows"][0]["name"] == "Unit A" and out["sentence"].endswith("Unit A: 10.0 per 1,000 h.")
    assert out["basis"]["counts"]["duty"] >= 1 and out["basis"]["counts"]["continuous"] >= 1


def test_the_tool(env):  # noqa: F811
    from backend.tests.test_maintenance_mcp import _do, _ok

    async def run(client):
        fleet = _ok(await _do(client, "maintenance", "positions.create", name="Fleet"))
        unit = _ok(await _do(client, "maintenance", "positions.create", name="Unit", parent_id=fleet["id"]))
        _ok(await _do(client, "maintenance", "failure_reports.file", position_id=unit["id"], title="Broke"))
        out = _ok(await _list(client, "fracas", position_id=fleet["id"], rank_by="rate"))
        bad = await _list(client, "fracas", position_id=fleet["id"], group_by="colour")
        return out, bad

    out, bad = _session(env["token"], run)
    assert out["totals"]["failures"] == 1 and out["rows"][0]["name"] == "Unit" and out["rank_by"] == "rate"
    assert bad.is_error
