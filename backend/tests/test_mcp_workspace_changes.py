"""The MCP list kind workspace_changes tool (#41): the same computed facts as the app's
"What changed", for the caller's own workspace, with full links."""

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.test_mcp import _err, _ok
from backend.tests.test_mcp_plans import BASE, FREE, PRO, _call, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")
NOW = datetime.now(timezone.utc)
RESULTS = {"kind": "distribution", "distribution_id": "weibull", "distribution": "Weibull",
           "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}], "n": 20}


def _seed(db, owner):
    db.models.insert_one({"_id": f"{owner}-m", "id": f"{owner}-m", "name": "Pump life", "owner_id": owner,
                          "created_at": NOW - timedelta(days=3), "updated_at": NOW - timedelta(days=3),
                          "results": RESULTS})
    db.fleets.insert_one({"_id": f"{owner}-f", "id": f"{owner}-f", "name": "Trucks", "owner_id": owner,
                          "model_id": f"{owner}-m", "created_at": NOW - timedelta(days=90),
                          "updated_at": NOW - timedelta(days=90), "settings": {}, "items": []})
    db.fleet_alert_events.insert_one({"_id": f"{owner}-e", "fleet_id": f"{owner}-f", "kind": "above",
                                      "threshold": 2.0, "previous_value": 1.0, "new_value": 2.5,
                                      "created_at": NOW - timedelta(days=1), "sent": True})


def test_workspace_changes_reports_the_callers_own_changes_with_links(env):
    _seed(env.db, PRO)
    _seed(env.db, FREE)
    out = _ok(_call(env.oauth[PRO], "list", {"kind": "workspace_changes", "days": 7}))
    assert [(r["id"], r["url"]) for r in out["new"]] == [(f"{PRO}-m", f"{BASE}/modelling/m/{PRO}-m")]
    assert [a["fleet"] for a in out["alerts"]] == ["Trucks"]
    assert out["sentence"] == "In the last 7 days: 1 fleet alert fired and 1 item was added."
    assert out["period"]["label"] == "in the last 7 days"
    assert any(n["what"] == "Failures recorded against the forecast" for n in out["not_compared"])


def test_on_free_fleets_are_left_out_and_said_so(env):
    _seed(env.db, FREE)
    out = _ok(_call(env.oauth[FREE], "list", {"kind": "workspace_changes"}))
    assert out["alerts"] == [] and out["forecasts"] == []
    assert out["not_compared"][0]["what"] == "Fleet forecasts and alerts"
    assert out["sentence"] == "In the last 30 days: 1 item was added."


def test_a_bad_period_is_a_tool_error(env):
    assert "last_visit" in _err(_call(env.oauth[PRO], "list", {"kind": "workspace_changes", "since": "lately"}))
