"""The MCP outage-history tools (issue #159): upload_outage_log and
system_history — lean output, owner-only, samples refused."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest

from backend.tests.test_outage_logs import GRAPH, LOG

A, B = "user-a", "user-b"


@pytest.fixture()
def mcp_env(monkeypatch):
    from backend import config, db
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["reliafy_outage_mcp"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    for uid in (A, B):
        test_db.users.insert_one({"_id": uid, "email": f"{uid}@example.org", "name": uid})

    class Env:
        db = test_db
        token = {uid: tokens.create_token(test_db, uid, "mcp")["token"] for uid in (A, B)}

    return Env


def test_mcp_upload_and_history(mcp_env):
    from backend.services import rbds as rbds_service
    from backend.tests.test_mcp import _call, _err, _ok

    rbd = rbds_service.save_rbd(mcp_env.db, "Plant", GRAPH, A)
    tok = mcp_env.token[A]
    assert "no outage log yet" in _err(_call(tok, "system_history", {"rbd_id": rbd.id}))

    out = _ok(_call(tok, "upload_outage_log", {"rbd_id": rbd.id, "csv": LOG, "window_start": "0",
                                               "window_end": "1000", "name": "Log"}))
    assert out["n_outages"] == 9 and out["unmapped"] == []
    assert out["url"].endswith(f"/rbds/b/{rbd.id}?tab=outages")
    assert out["history"]["kpis"]["availability"] == pytest.approx(0.91)

    hist = _ok(_call(tok, "system_history", {"rbd_id": rbd.id}))
    assert hist["log_id"] == out["log_id"]
    assert hist["kpis"]["outages"] == 6
    top = hist["top_outages"]
    assert len(top) == 6 and top[0]["duration"] == 30 and top[0]["cause"] == "Valve B"
    assert [c["label"] for c in hist["components"]] == ["Valve B", "Pump A", "Fan C", "Fan D"]
    assert "series" not in hist and "bars" not in hist  # lean

    # Explicit columns, and bad data comes back as a tool error listing the rows.
    cols = {"asset": "Asset", "start": "Outage start", "end": "Restored"}
    assert _ok(_call(tok, "upload_outage_log", {"rbd_id": rbd.id, "csv": LOG, "columns": cols}))["columns"] == cols
    msg = _err(_call(tok, "upload_outage_log", {"rbd_id": rbd.id, "csv": "asset,start,end\nPump A,5,1\n"}))
    assert "Row 2" in msg and "before it starts" in msg

    # Owner-only: B can't read A's log, or upload to A's diagram.
    other = mcp_env.token[B]
    assert "not found" in _err(_call(other, "system_history", {"rbd_id": rbd.id})).lower()
    assert "not found" in _err(_call(other, "upload_outage_log", {"rbd_id": rbd.id, "csv": LOG})).lower()


def test_mcp_refuses_samples(mcp_env):
    from backend import config
    from backend.tests.test_mcp import _call, _err

    mcp_env.db.rbds.insert_one({"_id": "sample-rbd", "id": "sample-rbd", "name": "Sample",
                                "owner_id": config.SAMPLE_OWNER, "graph": GRAPH})
    msg = _err(_call(mcp_env.token[A], "upload_outage_log", {"rbd_id": "sample-rbd", "csv": LOG}))
    assert "shared sample" in msg and "clone_rbd" in msg
    assert mcp_env.db.outage_logs.count_documents({}) == 0


# ---- plans: the Free allowance and storage cap ---------------------------------------------

from backend.tests.test_mcp_plans import env  # noqa: E402,F401 - the plans suite's OAuth users


def test_free_plan_counts_calls_and_caps_logs(env):
    from backend.services import billing
    from backend.services import rbds as rbds_service
    from backend.tests.test_mcp import _err, _ok
    from backend.tests.test_mcp_plans import FREE, PRO, _call

    rbd = rbds_service.save_rbd(env.db, "Plant", GRAPH, FREE)
    token = env.oauth[FREE]
    assert _ok(_call(token, "upload_outage_log", {"rbd_id": rbd.id, "csv": LOG, "window_end": "1000"}))["log_id"]
    assert _ok(_call(token, "system_history", {"rbd_id": rbd.id}))["kpis"]["outages"] == 6
    assert billing.mcp_calls_used(env.db, FREE, "free") == 2
    # The Free plan keeps one outage log; the refusal isn't counted.
    msg = _err(_call(token, "upload_outage_log", {"rbd_id": rbd.id, "csv": LOG}))
    assert "limit of 1 saved outage logs" in msg and "upgrade" in msg.lower()
    assert billing.mcp_calls_used(env.db, FREE, "free") == 2
    assert env.db.outage_logs.count_documents({"owner_id": FREE}) == 1

    # Pro: no cap.
    pro = rbds_service.save_rbd(env.db, "Plant", GRAPH, PRO)
    for _ in range(3):
        assert _ok(_call(env.oauth[PRO], "upload_outage_log", {"rbd_id": pro.id, "csv": LOG}))["log_id"]
