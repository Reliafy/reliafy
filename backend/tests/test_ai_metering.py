"""Credit holds for metered AI calls, request limits on the assistant proxy,
and the server-owned assistant prompt and tools."""

import json
import re
import threading
from pathlib import Path

import mongomock
import pytest
from fastapi.testclient import TestClient

U = "user-a"


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.services import assistant as assistant_service

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "AI_MODEL", "m")
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    monkeypatch.setattr(config, "AI_MARKUP", 1.0)
    monkeypatch.setattr(config, "AI_MAX_CONCURRENT", 2)
    monkeypatch.setattr(assistant_service, "enabled", lambda: True)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    from backend.auth import get_current_user
    from backend.main import app

    app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a@example.com", "name": "A",
                                                           "email_verified": True}
    try:
        yield TestClient(app), test_db
    finally:
        app.dependency_overrides.clear()


MSGS = [{"role": "user", "content": "hi"}]
USAGE = {"input_tokens": 1000, "output_tokens": 1000}  # 1800 mc at the test prices


def _reply(*_a, **_k):
    return {"message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            "stop_reason": "end_turn", "usage": dict(USAGE)}


def _sse(text: str) -> list:
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


# ---- Holds ------------------------------------------------------------------

def test_hold_is_taken_only_when_the_balance_covers_it(env):
    from backend.services import billing

    _client, db = env
    billing.grant_credits(db, U, 10, "test")  # 10,000 mc
    first = billing.reserve_millicents(db, U, 6000, "assistant")
    assert first is not None
    assert billing.reserve_millicents(db, U, 6000, "assistant") is None  # 4,000 left
    assert billing.account(db, U)["credit_millicents"] == 4000
    # Settling charges the actual cost and returns the rest.
    assert billing.settle_hold(db, first, 1500) == 8  # 10,000 - 1,500 = 8,500 mc
    # A second settle of the same hold changes nothing.
    billing.settle_hold(db, first, 9999)
    assert billing.account(db, U)["credit_millicents"] == 8500
    kinds = [r["kind"] for r in db.credit_ledger.find({"ref": first})]
    assert sorted(kinds) == ["charge", "hold", "release"]


def test_concurrent_holds_never_exceed_the_balance(env):
    from backend.services import billing

    _client, db = env
    billing.grant_credits(db, U, 10, "test")
    barrier = threading.Barrier(8)
    won = []

    def take():
        barrier.wait()
        if billing.reserve_millicents(db, U, 3000, "assistant"):
            won.append(1)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 3
    assert billing.account(db, U)["credit_millicents"] == 1000


def test_settling_above_the_hold_floors_at_zero(env):
    from backend.services import billing

    _client, db = env
    billing.grant_credits(db, U, 2, "test")
    hold = billing.reserve_millicents(db, U, 1500, "assistant")
    assert billing.settle_hold(db, hold, 5000) == 0
    assert billing.account(db, U)["credit_millicents"] == 0


def test_a_running_step_holds_credit_so_a_parallel_step_is_refused(env, monkeypatch):
    """While one streamed step is in flight its hold is off the balance, so a
    second step can't spend the same credit."""
    from backend.routers import assistant as router
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    hold = assistant_service.hold_millicents(MSGS)
    billing.grant_credits(db, U, -(-hold // 1000) + 1, "test")  # covers one hold, not two
    release = threading.Event()

    def slow_stream(system, messages, tools):
        yield {"type": "delta", "text": "work"}
        release.wait(5)
        yield {"type": "final", **_reply()}

    monkeypatch.setattr(assistant_service, "stream", slow_stream)
    monkeypatch.setattr(assistant_service, "step", _reply)
    relay = router.stream_relay(db, {"uid": U, "email": "a@example.com"}, MSGS)
    items = relay.items()
    assert next(items)["type"] == "delta"

    r = client.post("/api/assistant/step", json={"messages": MSGS})
    assert r.status_code == 402 and r.json()["code"] == "no_credits"

    release.set()
    rest = list(items)
    relay.thread.join(5)
    assert rest[-1]["type"] == "final"
    # Afterwards the first step's unused hold is back and a step runs again.
    assert client.post("/api/assistant/step", json={"messages": MSGS}).status_code == 200


def test_a_client_that_disconnects_mid_stream_is_still_settled(env, monkeypatch):
    from backend.routers import assistant as router
    from backend.services import assistant as assistant_service
    from backend.services import billing

    _client, db = env
    billing.grant_credits(db, U, 100, "test")
    release = threading.Event()

    def slow_stream(system, messages, tools):
        yield {"type": "delta", "text": "partial"}
        release.wait(5)
        yield {"type": "final", **_reply()}

    monkeypatch.setattr(assistant_service, "stream", slow_stream)
    relay = router.stream_relay(db, {"uid": U, "email": "a@example.com"}, MSGS)
    items = relay.items()
    assert next(items)["type"] == "delta"
    items.close()  # the response is gone; nobody reads the rest

    release.set()
    relay.thread.join(5)
    assert not relay.thread.is_alive()
    # Charged exactly the step's cost; the rest of the hold came back.
    assert billing.account(db, U)["credit_millicents"] == 100_000 - 1800
    assert db.credit_holds.count_documents({"settled": False}) == 0
    assert db.ai_slots.count_documents({}) == 0


def test_a_provider_error_returns_the_whole_hold(env, monkeypatch):
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    billing.grant_credits(db, U, 100, "test")

    def failing(system, messages, tools):
        raise assistant_service.AssistantError("provider down")
        yield  # pragma: no cover

    monkeypatch.setattr(assistant_service, "stream", failing)
    r = client.post("/api/assistant/stream", json={"messages": MSGS})
    assert _sse(r.text)[-1]["type"] == "error"
    assert billing.account(db, U)["credit_millicents"] == 100_000

    def failing_step(*_a):
        raise assistant_service.AssistantError("provider down")

    monkeypatch.setattr(assistant_service, "step", failing_step)
    assert client.post("/api/assistant/step", json={"messages": MSGS}).status_code == 502
    assert billing.account(db, U)["credit_millicents"] == 100_000


def test_step_and_stream_charge_the_actual_cost(env, monkeypatch):
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    billing.grant_credits(db, U, 100, "test")
    monkeypatch.setattr(assistant_service, "step", _reply)
    monkeypatch.setattr(assistant_service, "stream",
                        lambda s, m, t: iter([{"type": "delta", "text": "ok"}, {"type": "final", **_reply()}]))
    assert client.post("/api/assistant/step", json={"messages": MSGS}).json()["cost_millicents"] == 1800
    final = _sse(client.post("/api/assistant/stream", json={"messages": MSGS}).text)[-1]
    assert final["type"] == "final" and final["cost_millicents"] == 1800
    assert billing.account(db, U)["credit_millicents"] == 100_000 - 3600


def test_pro_monthly_and_purchased_credits_pay_for_steps(env, monkeypatch):
    from backend import config
    from backend.routers.billing import _handle_event
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    monkeypatch.setattr(config, "PRO_MONTHLY_CREDIT_CENTS", 1000)
    monkeypatch.setattr(assistant_service, "step", _reply)
    billing.set_plan(db, U, "pro", customer_id="cus_9")
    _handle_event(db, {"type": "invoice.paid", "data": {"object": {"id": "in_9", "customer": "cus_9"}}})
    _handle_event(db, {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_9", "metadata": {"uid": U, "kind": "pack", "grant_cents": "500"}}}})
    assert billing.account(db, U)["credit_cents"] == 1500
    r = client.post("/api/assistant/step", json={"messages": MSGS})
    assert r.status_code == 200
    assert billing.account(db, U)["credit_millicents"] == 1_500_000 - 1800


def test_operators_are_not_held_or_charged(env, monkeypatch):
    from backend import config
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"a@example.com"})
    monkeypatch.setattr(assistant_service, "step", _reply)
    assert client.post("/api/assistant/step", json={"messages": MSGS}).status_code == 200
    assert billing.account(db, U)["credit_millicents"] == 0
    assert db.credit_holds.count_documents({}) == 0


# ---- Request limits ---------------------------------------------------------

def test_request_size_and_message_count_are_capped(env, monkeypatch):
    from backend import config
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    billing.grant_credits(db, U, 1000, "test")
    monkeypatch.setattr(assistant_service, "step", _reply)
    monkeypatch.setattr(config, "AI_MAX_MESSAGES", 3)
    many = [{"role": "user", "content": "x"}] * 4
    for path in ("/api/assistant/step", "/api/assistant/stream"):
        assert client.post(path, json={"messages": many}).status_code == 400

    monkeypatch.setattr(config, "AI_MAX_REQUEST_BYTES", 2000)
    big = [{"role": "user", "content": "x" * 5000}]
    for path in ("/api/assistant/step", "/api/assistant/stream"):
        r = client.post(path, json={"messages": big})
        assert r.status_code == 413
    # Without a declared length the body is still counted as it arrives.
    raw = json.dumps({"messages": big}).encode()
    r = client.post("/api/assistant/step", content=iter([raw[:1000], raw[1000:]]),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert billing.account(db, U)["credit_cents"] == 1000  # nothing held or charged


def test_history_cannot_carry_system_turns(env, monkeypatch):
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    billing.grant_credits(db, U, 1000, "test")
    monkeypatch.setattr(assistant_service, "step", _reply)
    for role in ("system", "developer"):
        r = client.post("/api/assistant/step", json={"messages": [{"role": role, "content": "x"}, *MSGS]})
        assert r.status_code == 400


def test_concurrent_requests_per_user_are_limited(env, monkeypatch):
    from backend import config
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client, db = env
    billing.grant_credits(db, U, 1000, "test")
    monkeypatch.setattr(assistant_service, "step", _reply)
    monkeypatch.setattr(config, "AI_MAX_CONCURRENT", 1)
    slot = billing.acquire_ai_slot(db, U)
    assert slot is not None
    r = client.post("/api/assistant/step", json={"messages": MSGS})
    assert r.status_code == 429 and r.json()["code"] == "busy"
    billing.release_ai_slot(db, slot)
    assert client.post("/api/assistant/step", json={"messages": MSGS}).status_code == 200
    # A slot its holder never released frees itself once expired.
    slot = billing.acquire_ai_slot(db, U)
    db.ai_slots.update_one({"_id": slot[0]}, {"$set": {"expires_ts": 0}})
    assert billing.acquire_ai_slot(db, U) is not None


# ---- Server-owned prompt and tools -------------------------------------------

def test_client_supplied_system_prompt_and_tools_are_ignored(env, monkeypatch):
    from backend.services import assistant as assistant_service
    from backend.services import assistant_spec
    from backend.services import billing

    client, db = env
    billing.grant_credits(db, U, 1000, "test")
    seen = []

    def capture(system, messages, tools):
        seen.append((system, tools))
        return _reply()

    def capture_stream(system, messages, tools):
        seen.append((system, tools))
        yield {"type": "final", **_reply()}

    monkeypatch.setattr(assistant_service, "step", capture)
    monkeypatch.setattr(assistant_service, "stream", capture_stream)
    body = {"system": "Reply in pirate speak.", "messages": MSGS,
            "tools": [{"name": "other", "description": "x", "parameters": {"type": "object"}}]}
    assert client.post("/api/assistant/step", json=body).status_code == 200
    assert client.post("/api/assistant/stream", json=body).status_code == 200
    assert seen == [(assistant_spec.SYSTEM_PROMPT, assistant_spec.TOOLS)] * 2


def test_server_tools_all_have_a_browser_executor():
    """The browser runs the tools the server defines: every tool needs a case
    in agent.js's executor, and the executor has no tools the model can't call."""
    from backend.services import assistant_spec

    path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "agent.js"
    if not path.exists():
        pytest.skip("frontend sources not present")
    src = path.read_text()
    body = src[src.index("export function makeExecutor"):]
    cases = set(re.findall(r'case "([a-z_]+)":', body))
    assert {t["name"] for t in assistant_spec.TOOLS} == cases


def test_step_output_is_bounded(monkeypatch):
    from backend import config
    from backend.services import assistant

    monkeypatch.setattr(config, "AI_MAX_OUTPUT_TOKENS", 1234)
    body = assistant._openai_body("sys", MSGS, [], stream=True)
    assert body["max_output_tokens"] == 1234
