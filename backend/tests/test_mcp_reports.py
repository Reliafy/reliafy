"""MCP sharing create_report (#30): several items on one share page, managed with
the share-link tools. Through the real MCP mount (helpers and the ``env``
fixture come from test_mcp.py); the viewer is a plain TestClient."""

import matplotlib

matplotlib.use("Agg")

import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, B, GRAPH, _call, _err, _ok, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")


def _viewer():
    from backend.main import app

    return TestClient(app)


def _token(url):
    return url.rsplit("/p/", 1)[1]


def test_create_report_is_on_every_plan_and_counted():
    from backend.mcp_server import PRO_ONLY_TOOLS, UNGATED_TOOLS

    assert "create_report" not in PRO_ONLY_TOOLS | UNGATED_TOOLS


def test_agent_creates_a_report_and_a_viewer_opens_it(env):
    from backend.services import samples

    samples.seed_samples(env.db)  # a report may hold samples as well as the user's own items
    rid = _ok(_call(env.token[A], "rbd", {"action": "create", "name": "Pump skid", "unit": "Hours", **GRAPH}))["id"]
    out = _ok(_call(env.token[A], "sharing", {"action": "create_report",
        "title": "Pump skid review",
        "author": "Alice, Acme",
        "introduction": "What the diagram says.",
        "items": [{"kind": "rbd", "id": rid, "note": "Two pumps in parallel."},
                  {"kind": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}],
        "label": "for the client",
    }))
    assert out["kind"] == "report" and out["name"] == "Pump skid review" and out["label"] == "for the client"
    assert out["url"].startswith("https://reliafy.com/p/") and out["protected"] is False
    assert [s["kind"] for s in out["sections"]] == ["rbd", "strategy_analysis"]
    assert out["sections"][0]["name"] == "Pump skid"
    assert env.db.reports.find_one({"_id": out["report_id"]})["owner_id"] == A

    page = _viewer().get(f"/api/public/{_token(out['url'])}").json()
    assert page["collection"] == "reports"
    report = page["artifact"]
    assert report["name"] == "Pump skid review" and report["author"] == "Alice, Acme"
    rbd, strategy = report["sections"]
    assert rbd["note"] == "Two pumps in parallel." and rbd["artifact"]["analysis"]["mttf"] > 0
    assert strategy["artifact"]["results"]["optimal_time"] > 0

    # The share-link tools manage it like any other link.
    listed = _ok(_call(env.token[A], "list", {"kind": "share_links", "item_kind": "report"}))
    assert [link["token"] for link in listed["links"]] == [out["token"]]
    _ok(_call(env.token[A], "sharing", {"action": "revoke_link", "token": out["url"]}))
    assert _viewer().get(f"/api/public/{out['token']}").status_code == 404


def test_report_with_a_passphrase_and_expiry(env):
    rid = _ok(_call(env.token[A], "rbd", {"action": "create", "name": "Skid", "unit": "Hours", **GRAPH}))["id"]
    out = _ok(_call(env.token[A], "sharing", {"action": "create_report",
        "title": "Protected", "items": [{"kind": "rbd", "id": rid}], "password": True, "expires_in_days": 7}))
    assert out["protected"] is True and out["passphrase"] and out["expires_at"]
    viewer = _viewer()
    assert viewer.get(f"/api/public/{out['token']}").status_code == 401
    unlock = viewer.post(f"/api/public/{out['token']}/unlock", json={"password": out["passphrase"]}).json()
    r = viewer.get(f"/api/public/{out['token']}", headers={"X-Share-Unlock": unlock["unlock_token"]})
    assert r.status_code == 200 and r.json()["artifact"]["name"] == "Protected"


def test_create_report_refuses_another_user_s_items(env):
    rid = _ok(_call(env.token[A], "rbd", {"action": "create", "name": "A's skid", "unit": "Hours", **GRAPH}))["id"]
    msg = _err(_call(env.token[B], "sharing", {"action": "create_report", "title": "Nope", "items": [{"kind": "rbd",
        "id": rid}]}))
    assert "wasn't found among your own" in msg
    assert env.db.reports.count_documents({}) == 0 and env.db.public_links.count_documents({}) == 0


def test_share_link_can_republish_a_report(env):
    """A report has its own kind in sharing create_link, so an agent can add a second
    link (one per recipient), and a user's report can't be linked by another."""
    rid = _ok(_call(env.token[A], "rbd", {"action": "create", "name": "Skid", "unit": "Hours", **GRAPH}))["id"]
    out = _ok(_call(env.token[A], "sharing", {"action": "create_report", "title": "R", "items": [{"kind": "rbd",
        "id": rid}]}))
    again = _ok(_call(env.token[A], "sharing", {"action": "create_link", "kind": "report", "id": out["report_id"]}))
    assert again["token"] != out["token"] and again["kind"] == "report"
    assert "No report with that id" in _err(_call(env.token[B], "sharing",
                                                  {"action": "create_link", "kind": "report", "id": out["report_id"]}))
