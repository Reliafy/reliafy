"""The /mcp endpoint logs every request (method, answer, time open) and ends
any request that outlives MCP_REQUEST_TIMEOUT_S, so one left open can't hold
the web instance until the platform's timeout."""

import json
import logging
import time

import anyio
import pytest
from fastapi.testclient import TestClient

from backend import config
from backend import mcp_server
from backend.services import usage as usage_service

USER = {"uid": "u1", "email": "a@example.com", "email_verified": True}
AUTH = {"Authorization": "Bearer x", "Accept": "application/json, text/event-stream"}


# MCP switched on (on the cloud it is off by default): backend/services/mcp_switch.py.
pytestmark = pytest.mark.usefixtures("mcp_on")


class _Manager:
    """Stands in for the SDK's session manager: answers, hangs, or answers
    and then never finishes the response."""

    def __init__(self, mode):
        self.mode = mode

    async def handle_request(self, scope, receive, send):
        while True:  # read the whole body, as the SDK does
            message = await receive()
            if not message.get("more_body"):
                break
        if self.mode == "hang":
            await anyio.sleep(30)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        if self.mode == "open":
            await send({"type": "http.response.body", "body": body, "more_body": True})
            await anyio.sleep(30)
        await send({"type": "http.response.body", "body": body})


@pytest.fixture()
def endpoint(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=mcp_server.logger.name)
    monkeypatch.setattr(mcp_server, "_authenticate_request", lambda _a: (200, USER, ""))
    monkeypatch.setattr(usage_service, "enabled", lambda: False)
    monkeypatch.setattr(config, "MCP_REQUEST_TIMEOUT_S", 0.5)

    def make(mode):
        monkeypatch.setattr(mcp_server.mcp_http_app, "_manager", _Manager(mode))
        return TestClient(mcp_server.mcp_http_app)
    return make


def _call(name="list_models"):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {"x": 1}}}


def test_a_request_is_logged_with_its_method_and_not_its_arguments(endpoint, caplog):
    r = endpoint("answer").post("/mcp", json=_call(), headers=AUTH)
    assert r.status_code == 200
    line = next(m for m in caplog.messages if m.startswith("MCP request"))
    assert "tools/call:list_models" in line and "status 200" in line and "complete" in line
    assert '"x"' not in line and "arguments" not in line
    assert caplog.records[-1].levelno == logging.INFO


def test_a_request_that_never_answers_is_stopped_at_the_cap(endpoint, caplog):
    r = endpoint("hang").post("/mcp", json=_call(), headers=AUTH)
    assert r.status_code == 504
    line = next(m for m in caplog.messages if m.startswith("MCP request"))
    assert "not started" in line


def test_a_response_left_open_is_ended_at_the_cap_and_logged(endpoint, caplog):
    started = time.monotonic()
    endpoint("open").post("/mcp", json=_call(), headers=AUTH)
    assert time.monotonic() - started < 10  # the cap, not the stand-in's 30 s, ended it
    line = next(m for m in caplog.messages if m.startswith("MCP request"))
    assert "NOT complete" in line and "status 200" in line


def test_rpc_summary_names_methods_and_replies_only():
    batch = [{"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 4, "result": {"secret": 1}}]
    assert mcp_server._rpc_summary(json.dumps(batch).encode()) == "notifications/initialized,response"
    assert mcp_server._rpc_summary(b"{not json") == "(not JSON)"
    assert mcp_server._rpc_summary(None) == "(body not read)"
