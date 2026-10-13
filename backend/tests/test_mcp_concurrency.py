"""How many MCP tool calls run at once: per user and per instance, slots held
until the work ends (not just the request), and tool threads kept apart from
the pool the app's own routes use."""

import threading
import time

import anyio
import httpx2
import mongomock
import pytest

pytestmark = pytest.mark.usefixtures("mcp_on")

USERS = [f"user-{i}" for i in range(6)]


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import datasets as datasets_service
    from backend.services import tokens, usage

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["reliafy_mcp_concurrency"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(usage, "_next_rollup", float("inf"))
    ingest_router._hits.clear()
    for uid in USERS:
        test_db.users.insert_one({"_id": uid, "email": f"{uid}@example.org", "name": uid})

    class Env:
        token = {uid: tokens.create_token(test_db, uid, "mcp")["token"] for uid in USERS}
        release = threading.Event()
        running = 0
        peak = 0
        finished = 0
        lock = threading.Lock()

    def held_list(*args, **kwargs):
        with Env.lock:
            Env.running += 1
            Env.peak = max(Env.peak, Env.running)
        try:
            Env.release.wait(10)
            return []
        finally:
            with Env.lock:
                Env.running -= 1
                Env.finished += 1

    monkeypatch.setattr(datasets_service, "list_datasets", held_list)
    yield Env
    Env.release.set()


BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_datasets", "arguments": {}}}


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18"}


async def _wait_for(cond, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not cond() and time.monotonic() < deadline:
        await anyio.sleep(0.02)
    assert cond()


def _serve(fn):
    from backend.main import app
    from backend.mcp_server import mcp_http_app

    out = {}

    async def main():
        async with mcp_http_app.lifespan():
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver",
                                          timeout=30) as hc:
                out["value"] = await fn(hc)

    anyio.run(main)
    return out.get("value")


def _text(resp) -> str:
    return resp.json()["result"]["content"][0]["text"]


def test_one_user_runs_a_few_tool_calls_at_once(env):
    from backend import mcp_server

    a, b = USERS[0], USERS[1]

    async def scenario(hc):
        replies = []

        async def call(uid):
            replies.append((uid, await hc.post("/mcp", json=BODY, headers=_headers(env.token[uid]))))

        async with anyio.create_task_group() as tg:
            for _ in range(mcp_server.MCP_USER_CONCURRENCY):
                tg.start_soon(call, a)
            await _wait_for(lambda: env.running == mcp_server.MCP_USER_CONCURRENCY)
            # One more from the same user: refused at once, with the reason.
            extra = await hc.post("/mcp", json=BODY, headers=_headers(env.token[a]))
            assert extra.status_code == 200
            result = extra.json()["result"]
            assert result["isError"] is True and "running at once" in _text(extra)
            # Another user isn't held up by it.
            tg.start_soon(call, b)
            await _wait_for(lambda: env.running == mcp_server.MCP_USER_CONCURRENCY + 1)
            env.release.set()
        return replies

    replies = _serve(scenario)
    assert len(replies) == mcp_server.MCP_USER_CONCURRENCY + 1
    assert all(r.status_code == 200 and not r.json()["result"].get("isError") for _, r in replies)
    assert mcp_server._SLOTS.running() == 0


def test_instance_wide_cap_queues_then_refuses(env, monkeypatch):
    from backend import mcp_server

    monkeypatch.setattr(mcp_server, "MCP_GLOBAL_CONCURRENCY", 3)
    monkeypatch.setattr(mcp_server, "MCP_SLOT_WAIT_S", 0.3)

    async def scenario(hc):
        async def call(uid):
            await hc.post("/mcp", json=BODY, headers=_headers(env.token[uid]))

        async with anyio.create_task_group() as tg:
            for uid in USERS[:3]:
                tg.start_soon(call, uid)
            await _wait_for(lambda: env.running == 3)
            started = time.monotonic()
            busy = await hc.post("/mcp", json=BODY, headers=_headers(env.token[USERS[3]]))
            waited = time.monotonic() - started
            assert busy.json()["result"]["isError"] is True and "busy" in _text(busy)
            assert 0.25 <= waited < 5
            env.release.set()

    _serve(scenario)
    assert env.peak == 3
    assert mcp_server._SLOTS.running() == 0


def test_slots_stay_taken_until_work_after_a_timeout_ends(env, monkeypatch):
    from backend import config, mcp_server

    monkeypatch.setattr(config, "MCP_REQUEST_TIMEOUT_S", 0.5)
    uid = USERS[0]

    async def scenario(hc):
        r = await hc.post("/mcp", json=BODY, headers=_headers(env.token[uid]))
        assert r.status_code == 504
        # The request has ended, the work hasn't: it still holds its slots.
        assert env.running == 1
        assert mcp_server._SLOTS.running(uid) == 1 and mcp_server._SLOTS.running() == 1
        env.release.set()
        await _wait_for(lambda: mcp_server._SLOTS.running() == 0)
        assert env.finished == 1

    _serve(scenario)


def test_tool_calls_leave_the_app_worker_pool_free(env):
    from backend import mcp_server

    async def scenario(hc):
        async def call(uid):
            await hc.post("/mcp", json=BODY, headers=_headers(env.token[uid]))

        async with anyio.create_task_group() as tg:
            for uid in USERS:
                for _ in range(8):
                    tg.start_soon(call, uid)
            await _wait_for(lambda: env.running == min(len(USERS) * mcp_server.MCP_USER_CONCURRENCY,
                                                       mcp_server.MCP_GLOBAL_CONCURRENCY))
            started = time.monotonic()
            r = await hc.get("/.well-known/oauth-authorization-server")
            assert r.status_code == 200
            assert time.monotonic() - started < 1.0
            assert anyio.to_thread.current_default_thread_limiter().borrowed_tokens == 0
            env.release.set()

    _serve(scenario)
    assert env.peak <= mcp_server.MCP_GLOBAL_CONCURRENCY
    assert mcp_server._SLOTS.running() == 0


def test_a_call_cancelled_before_its_thread_starts_gives_its_slots_back(monkeypatch):
    from backend import mcp_server

    ran = []
    held = anyio.CapacityLimiter(1)
    monkeypatch.setattr(mcp_server, "_TOOL_THREADS", held)

    async def main():
        await held.acquire_on_behalf_of("someone")  # no thread free for the call
        with anyio.move_on_after(0.2):
            await mcp_server._run_in_slot("u", lambda: ran.append(1))
        assert mcp_server._SLOTS.running("u") == 0 and mcp_server._SLOTS.running() == 0
        held.release_on_behalf_of("someone")
        await anyio.sleep(0.1)

    anyio.run(main)
    assert ran == []


def test_slots_are_given_back_when_a_tool_raises():
    from backend import mcp_server

    def boom():
        raise ValueError("bad input")

    async def main():
        with pytest.raises(ValueError):
            await mcp_server._run_in_slot("u", boom)

    anyio.run(main)
    assert mcp_server._SLOTS.running("u") == 0 and mcp_server._SLOTS.running() == 0


def test_heavy_tools_are_registered_tools():
    from backend import mcp_server

    names = {t.name for t in anyio.run(mcp_server.mcp.list_tools)}
    assert mcp_server.HEAVY_TOOLS <= names
    assert mcp_server.TEXT_RESULT_TOOLS <= names


def test_heavy_calculations_have_a_smaller_limit_of_their_own():
    from backend import mcp_server
    from mcp.server.mcpserver.exceptions import ToolError

    release = threading.Event()
    started = []

    def held():
        started.append(1)
        release.wait(10)
        return "done"

    async def main():
        results = []

        async def heavy():
            results.append(await mcp_server._run_in_slot("u", held, heavy=True))

        async with anyio.create_task_group() as tg:
            for _ in range(mcp_server.MCP_USER_HEAVY):
                tg.start_soon(heavy)
            await _wait_for(lambda: len(started) == mcp_server.MCP_USER_HEAVY)
            with pytest.raises(ToolError, match="calculations"):
                await mcp_server._run_in_slot("u", held, heavy=True)
            # A light call from the same user still runs.
            assert await mcp_server._run_in_slot("u", lambda: "light") == "light"
            # Another user's heavy call too.
            assert await mcp_server._run_in_slot("v", lambda: "ok", heavy=True) == "ok"
            release.set()
        assert results == ["done"] * mcp_server.MCP_USER_HEAVY

    anyio.run(main)
    assert mcp_server._HEAVY_SLOTS.running() == 0 and mcp_server._SLOTS.running() == 0


def test_instance_heavy_cap_waits_then_refuses(monkeypatch):
    from backend import mcp_server
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(mcp_server, "MCP_GLOBAL_HEAVY", 1)
    monkeypatch.setattr(mcp_server, "MCP_SLOT_WAIT_S", 0.2)
    release = threading.Event()

    async def main():
        async with anyio.create_task_group() as tg:
            tg.start_soon(mcp_server._run_in_slot, "a", lambda: release.wait(10), True)
            await _wait_for(lambda: mcp_server._HEAVY_SLOTS.running() == 1)
            with pytest.raises(ToolError, match="busy"):
                await mcp_server._run_in_slot("b", lambda: None, True)
            # Nothing of the refused call is left holding a slot.
            assert mcp_server._SLOTS.running("b") == 0 and mcp_server._HEAVY_SLOTS.running("b") == 0
            assert mcp_server._SLOTS.running() == 1
            release.set()

    anyio.run(main)
    assert mcp_server._HEAVY_SLOTS.running() == 0 and mcp_server._SLOTS.running() == 0


def test_inline_fit_data_is_capped_in_the_schema():
    from backend import mcp_server

    tools = {t.name: t for t in anyio.run(mcp_server.mcp.list_tools)}
    for name in ("fit_distribution", "fit_and_save_model", "compare_groups"):
        prop = tools[name].input_schema["properties"]["data"]
        schemas = prop.get("anyOf", [prop])
        assert any(s.get("maxItems") == mcp_server._INLINE_MAX_ROWS for s in schemas), name


def test_file_reads_over_mcp_finish_within_the_request_cap(monkeypatch):
    from backend import config, mcp_server
    from backend.services import import_guard

    monkeypatch.setattr(config, "MCP_REQUEST_TIMEOUT_S", 60)
    assert mcp_server._import_budget() == 50.0 < import_guard.BUDGET_SECONDS
    monkeypatch.setattr(config, "MCP_REQUEST_TIMEOUT_S", 600)
    assert mcp_server._import_budget() == import_guard.BUDGET_SECONDS
