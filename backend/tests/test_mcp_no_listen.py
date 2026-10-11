"""Reliafy serves no `subscriptions/listen` streams (protocol 2026-07-28):
its tools, prompts and resources never change while it runs. So it doesn't
advertise listChanged / subscribe, and a listen request ends at once instead
of holding a request open (which, on Cloud Run, keeps the instance billed)."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from backend import mcp_server
from backend.services import mcp_switch

MODERN = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": MODERN, "io.modelcontextprotocol/clientCapabilities": {}}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(mcp_server, "_authenticate_request",
                        lambda _a: (200, {"uid": "u1", "email": "a@example.com", "email_verified": True}, ""))
    monkeypatch.setattr(mcp_switch, "forced", lambda: True)
    from backend.main import app

    with TestClient(app) as c:
        yield c


def _post(client, method, params, rid=1):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "Authorization": "Bearer x", "MCP-Protocol-Version": MODERN, "Mcp-Method": method}
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": {"_meta": META, **params}}
    return client.post("/mcp", headers=headers, content=json.dumps(body), timeout=20)


def test_no_change_notifications_are_advertised(client):
    caps = _post(client, "server/discover", {}).json()["result"]["capabilities"]
    assert caps["tools"]["listChanged"] is False
    assert caps["prompts"]["listChanged"] is False
    assert caps["resources"] == {"listChanged": False, "subscribe": False}


def test_a_listen_request_ends_at_once(client):
    started = time.monotonic()
    r = _post(client, "subscriptions/listen", {"notifications": {"toolsListChanged": True}}, rid=2)
    assert time.monotonic() - started < 5
    assert r.json()["error"]["code"] == -32601
    assert r.json()["id"] == 2
