"""Reads of the graph kept per process until it changes (backend/maintenance/read_cache.py):
the RCM of every position and a position's running clock. A kept read is the same as a
fresh one, and any event, rebuild or new day is a fresh read."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.maintenance.read_cache import cached
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import running_clock as rc

ORG = "user-cache"
EIGHT_A_DAY = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
     "start": "08:00", "stop": "16:00"}]}}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _pump(m, name="Pump"):
    pid = m.create_position(name)["id"]
    ff = m.add_functional_failure(m.add_function(pid, f"{name} works")["id"], "No flow")
    m.add_failure_mode(pid, "Seal leak", functional_failure_id=ff["id"])
    return pid


def _fresh(m):
    """The RCM read again with nothing kept."""
    m.s.read_cache.clear()
    return Maintenance(m.s, m.org, "tester")._rcm_all(None, None)


def _counting(monkeypatch):
    calls = []
    real = Maintenance._rcm_all
    monkeypatch.setattr(Maintenance, "_rcm_all", lambda self, *a: calls.append(1) or real(self, *a))
    return calls


def test_the_rcm_is_read_once_until_the_graph_changes(m, monkeypatch):
    _pump(m)
    calls = _counting(monkeypatch)
    first = m.rcm_all()
    again = Maintenance(m.s, ORG, "someone else").rcm_all()
    assert len(calls) == 1
    assert again == first == _fresh(m)


def test_an_event_reads_it_afresh(m, monkeypatch):
    pid = _pump(m)
    before = m.rcm_all()
    calls = _counting(monkeypatch)
    m.add_failure_mode(pid, "Bearing worn")
    after = m.rcm_all()
    assert len(calls) == 1, "read again after the event"
    assert after != before
    modes = [x["text"] for x in after["positions"][0]["unassigned"]]
    assert "Bearing worn" in modes
    assert after == _fresh(m)


def test_another_workspaces_event_also_reads_it_afresh(m, monkeypatch):
    _pump(m)
    m.rcm_all()
    calls = _counting(monkeypatch)
    Maintenance(m.s, "user-other", "tester").create_position("Fan")
    m.rcm_all()
    assert len(calls) == 1


def test_a_rebuild_reads_it_afresh(m, monkeypatch):
    _pump(m)
    m.rcm_all()
    calls = _counting(monkeypatch)
    m.s.rebuild()
    after = m.rcm_all()
    assert len(calls) == 1
    assert after == _fresh(m)


def test_each_caller_gets_its_own_copy(m):
    _pump(m)
    first = m.rcm_all()
    first["positions"][0]["name"] = "Changed by a caller"
    first["positions"].clear()
    assert m.rcm_all()["positions"][0]["name"] == "Pump"


def test_the_parts_read_for_what_changed_are_kept_apart(m):
    _pump(m)
    assert m.rcm_all(evidence_ids={"no-such-model"})["positions"] == []
    assert len(m.rcm_all()["positions"]) == 1


def test_a_read_the_graph_changed_under_is_not_kept(m):
    pid = _pump(m)
    store = m.s

    def changing():
        out = {"read": "before"}
        m.add_failure_mode(pid, "Changed mid-read")
        return out

    assert cached(store, ("probe",), changing) == {"read": "before"}
    assert cached(store, ("probe",), lambda: {"read": "after"}) == {"read": "after"}


def test_a_store_without_a_token_always_reads():
    class Plain:
        pass

    calls = []
    for _ in range(2):
        cached(Plain(), ("x",), lambda: calls.append(1))
    assert len(calls) == 2


def test_the_running_clock_is_kept_per_day_and_read_afresh_when_the_plan_changes(m, monkeypatch):
    pid = m.create_position("Pump")["id"]
    m.set_operating_plan(pid, EIGHT_A_DAY)
    m.as_of = date(2026, 11, 23).isoformat()
    calls = []
    real = rc._clock_of
    monkeypatch.setattr(rc, "_clock_of", lambda *a: calls.append(1) or real(*a))
    first = rc.for_position(m, pid)
    for reader in (Maintenance(m.s, ORG, "tester"), Maintenance(m.s, ORG, "tester")):
        reader.as_of = m.as_of
        assert rc.for_position(reader, pid) == rc.for_position(m, pid)
    assert first.hours_per_day == pytest.approx(8.0)
    n = len(calls)
    # Another day: read again.
    later = Maintenance(m.s, ORG, "tester")
    later.as_of = (date(2026, 11, 23) + timedelta(days=1)).isoformat()
    rc.for_position(later, pid)
    assert len(calls) == n + 1
    # The plan taken away: read again, and running all the time now.
    m.end_operating_plan(pid, until=m.as_of)
    fresh = Maintenance(m.s, ORG, "tester")
    fresh.as_of = m.as_of
    assert rc.for_position(fresh, pid) == rc.CONTINUOUS
