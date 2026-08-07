"""Operator push notifications.

Two properties matter more than the happy path: it must be a silent no-op when
unconfigured (self-hosters and CI never set these), and it must never be able
to break the request that triggered it — a signup that fails because a phone
notification failed would be the worst possible trade.
"""

import logging

import pytest

from backend import config
from backend.services import email as email_service
from backend.services import push as push_service


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", "tok-test")
    monkeypatch.setattr(config, "PUSHOVER_USER", "usr-test")


def test_unconfigured_is_a_silent_no_op(monkeypatch, caplog):
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", None)
    monkeypatch.setattr(config, "PUSHOVER_USER", None)
    assert push_service.enabled() is False
    with caplog.at_level(logging.INFO):
        assert push_service.send("Title", "Body") is False
    assert "skipped" in caplog.text


def test_needs_both_halves(monkeypatch):
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", "tok")
    monkeypatch.setattr(config, "PUSHOVER_USER", None)
    assert push_service.enabled() is False
    monkeypatch.setattr(config, "PUSHOVER_USER", "usr")
    assert push_service.enabled() is True


def test_payload_shape(configured, monkeypatch):
    sent = {}
    monkeypatch.setattr(push_service, "_deliver", lambda p: sent.update(p))
    monkeypatch.setattr(push_service.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})())
    assert push_service.send("New signup", "someone@example.com",
                             url="https://reliafy.com/admin", url_title="Dashboard") is True
    assert sent["token"] == "tok-test" and sent["user"] == "usr-test"
    assert sent["title"] == "New signup" and "someone@example.com" in sent["message"]
    assert sent["url_title"] == "Dashboard"


def test_a_failing_provider_never_escalates(configured, monkeypatch):
    """_deliver swallows everything — a dead Pushover must not surface."""
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(push_service.httpx, "post", boom)
    push_service._deliver({"title": "x"})  # must not raise


def test_a_rejected_message_is_logged_not_raised(configured, monkeypatch, caplog):
    class R:
        status_code = 400
        text = '{"errors":["application token is invalid"]}'

    monkeypatch.setattr(push_service.httpx, "post", lambda *a, **k: R())
    with caplog.at_level(logging.WARNING):
        push_service._deliver({"title": "x"})
    assert "rejected" in caplog.text


def test_signup_prefers_push_and_skips_email(configured, monkeypatch):
    pushed, mailed = [], []
    monkeypatch.setattr(push_service, "send",
                        lambda *a, **k: (pushed.append(a), True)[1])
    monkeypatch.setattr(email_service, "send", lambda *a: mailed.append(a))
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"ops@example.com"})
    email_service.new_signup("new@example.com", "New User")
    assert pushed and not mailed


def test_signup_falls_back_to_email_without_push(monkeypatch):
    """An instance configured only with ADMIN_EMAILS must keep working."""
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", None)
    monkeypatch.setattr(config, "PUSHOVER_USER", None)
    mailed = []
    monkeypatch.setattr(email_service, "send", lambda *a: mailed.append(a))
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"ops@example.com"})
    email_service.new_signup("new@example.com", "New User")
    assert len(mailed) == 1 and "new@example.com" in mailed[0][1]


def test_no_secret_reaches_the_logs(configured, monkeypatch, caplog):
    class R:
        status_code = 500
        text = "upstream error"

    monkeypatch.setattr(push_service.httpx, "post", lambda *a, **k: R())
    with caplog.at_level(logging.INFO):
        push_service._deliver({"token": "tok-test", "user": "usr-test", "title": "x"})
    assert "tok-test" not in caplog.text and "usr-test" not in caplog.text
