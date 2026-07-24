"""Reliability Agent session history: record, list, ownership, transcript."""

import mongomock
import pytest


@pytest.fixture()
def db():
    return mongomock.MongoClient()["reliafy_test"]


def test_record_list_and_ownership(db):
    from backend.services import reliability_agent as ag

    ag.record_session_turn(db, "u1", "sesn_1", "Analyze my pump failure data please")
    ag.record_session_turn(db, "u1", "sesn_1", "follow-up question")  # second turn
    ag.record_session_turn(db, "u1", "sesn_2", "A different analysis")
    ag.record_session_turn(db, "u2", "sesn_3", "Someone else's run")

    sessions = ag.list_sessions(db, "u1")
    assert {s["id"] for s in sessions} == {"sesn_1", "sesn_2"}  # scoped to owner
    s1 = next(s for s in sessions if s["id"] == "sesn_1")
    assert s1["title"] == "Analyze my pump failure data please"  # first message
    assert s1["turns"] == 2  # bumped per turn
    # Sorted newest-activity-first (updated_at descending).
    ups = [s["updated_at"] for s in sessions]
    assert ups == sorted(ups, reverse=True)

    assert ag.owns_session(db, "u1", "sesn_1")
    assert not ag.owns_session(db, "u2", "sesn_1")


class _FakeEvents:
    def __init__(self, events):
        self._events = events

    def list(self, _session_id):
        return self._events


def test_get_transcript_rebuilds_message_shape(db, monkeypatch):
    from backend.services import reliability_agent as ag

    events = [
        {"type": "user.message", "content": [{"type": "text", "text": "Fit a Weibull"}]},
        {"type": "agent.message", "content": [{"type": "text", "text": "I'll fit it."}]},
        {"type": "agent.tool_use", "name": "bash", "input": {"command": "python fit.py"}},
        {"type": "agent.tool_result", "content": [{"type": "text", "text": "alpha=5 <<RELIAFY_IMG>>iVBORw0"}]},
        {"type": "agent.message", "content": [{"type": "text", "text": "Done — α=5, β=2."}]},
    ]

    import types

    fake = types.SimpleNamespace(
        beta=types.SimpleNamespace(
            sessions=types.SimpleNamespace(events=_FakeEvents(events))
        )
    )
    monkeypatch.setattr(ag, "_client", lambda: fake)
    msgs = ag.get_transcript(db, "sesn_1")

    assert msgs[0] == {"role": "user", "text": "Fit a Weibull"}
    assert msgs[1]["role"] == "agent"
    parts = msgs[1]["parts"]
    kinds = [p["type"] for p in parts]
    assert kinds == ["text", "code", "result", "text"]
    assert parts[1]["code"] == "python fit.py"
    # Truncated chart base64 is stripped from the saved copy.
    assert "RELIAFY_IMG" not in parts[2]["output"]
    assert parts[3]["text"] == "Done — α=5, β=2."
