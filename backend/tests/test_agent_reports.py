"""Problems agents report about the tools (report_problem), and their status."""

import mongomock
import pytest

from backend.services import agent_reports


@pytest.fixture()
def db():
    return mongomock.MongoClient().db


def test_report_then_check_its_status(db):
    r = agent_reports.create(db, "u1", kind="error", summary="fit refused a valid censor column",
                             tool="life_data_analysis", action="fit", happened="ToolError: ...")
    assert r["status"] == "new" and not r["fix_live"]
    assert agent_reports.mine(db, "u1", r["report_id"])["summary"].startswith("fit refused")
    fixed = agent_reports.update(db, r["report_id"], status="fixed", note="Thanks", fixed_in="2026-10-20")
    assert fixed["fix_live"] and fixed["fixed_in"] == "2026-10-20"
    assert agent_reports.mine(db, "u1")["reports"][0]["status"] == "fixed"


def test_reports_are_private_and_checked(db):
    r = agent_reports.create(db, "u1", kind="docs", summary="guide names an action that doesn't exist")
    with pytest.raises(LookupError):
        agent_reports.mine(db, "u2", r["report_id"])
    assert agent_reports.mine(db, "u2") == {"reports": []}
    with pytest.raises(agent_reports.Invalid):
        agent_reports.create(db, "u1", kind="nonsense", summary="x")
    with pytest.raises(agent_reports.Invalid):
        agent_reports.create(db, "u1", kind="error", summary="  ")
    with pytest.raises(agent_reports.Invalid):
        agent_reports.update(db, r["report_id"], status="done")
    long = agent_reports.create(db, "u1", kind="other", summary="s" * 500, detail="d" * 10_000)
    assert len(long["summary"]) == 200


def test_a_daily_limit(db):
    for _ in range(agent_reports.PER_DAY):
        agent_reports.create(db, "u3", kind="other", summary="again")
    with pytest.raises(agent_reports.Invalid, match="daily limit"):
        agent_reports.create(db, "u3", kind="other", summary="once more")
