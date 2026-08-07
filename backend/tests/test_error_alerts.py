"""Operator crash alerts.

The two ways an alert channel dies are silence (it never fires) and noise (it
fires so often it gets muted). Both are tested here: expected user errors must
never alert, real crashes must, and a storm must throttle rather than empty
itself into someone's pocket.
"""

import logging

import pytest

from backend import config
from backend.fitting import FitError
from backend.services import push as push_service


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Each test starts with an empty throttle and a captured sender."""
    push_service._seen.clear()
    push_service._recent.clear()
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", "tok")
    monkeypatch.setattr(config, "PUSHOVER_USER", "usr")
    monkeypatch.setattr(config, "PUSH_ERROR_ALERTS", True)
    sent = []
    monkeypatch.setattr(push_service, "send",
                        lambda *a, **k: (sent.append((a, k)), True)[1])
    return sent


def _raise(exc):
    try:
        raise exc
    except type(exc) as e:
        return e


def test_a_real_crash_alerts_with_type_and_location(clean_state):
    assert push_service.alert_error("fit", _raise(IndexError("list index out of range"))) is True
    (title, body), _ = clean_state[0]
    assert "Reliafy error" in title and "fit" in title
    assert "IndexError" in body and "list index out of range" in body
    assert "test_error_alerts.py:" in body      # where it happened


def test_expected_user_errors_never_alert(clean_state):
    """A censored-only dataset is the product working, not a crash. If these
    alerted, the real ones would be lost in the noise."""
    handler = push_service.PushErrorHandler(level=logging.ERROR)
    for exc in (FitError("only 1 of 8 rows is a failure"),):
        rec = logging.LogRecord("backend.main", logging.ERROR, __file__, 1,
                                "fit failed", None, (type(exc), exc, None))
        handler.emit(rec)
    assert clean_state == []


def test_a_plain_error_log_without_an_exception_does_not_alert(clean_state):
    handler = push_service.PushErrorHandler(level=logging.ERROR)
    rec = logging.LogRecord("backend.x", logging.ERROR, __file__, 1, "just a message", None, None)
    handler.emit(rec)
    assert clean_state == []


def test_the_same_fault_is_reported_once_per_window(clean_state):
    exc = _raise(ValueError("boom"))
    assert push_service.alert_error("fit", exc) is True
    assert push_service.alert_error("fit", exc) is False      # repeat, suppressed
    assert push_service.alert_error("rbds", exc) is True      # different place
    assert len(clean_state) == 2


def test_a_storm_is_capped_and_says_so(clean_state):
    """A bad deploy must not empty its stack traces into someone's pocket."""
    for i in range(20):
        push_service.alert_error(f"place-{i}", _raise(ValueError("boom")))
    assert len(clean_state) == push_service._HOURLY_CAP
    last_body = clean_state[-1][0][1]
    assert "alert limit reached" in last_body


def test_alerting_never_raises(monkeypatch, clean_state):
    """Whatever happens in here must not escape into the request."""
    monkeypatch.setattr(push_service, "send",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network")))
    handler = push_service.PushErrorHandler(level=logging.ERROR)
    exc = _raise(IndexError("x"))
    rec = logging.LogRecord("backend.main", logging.ERROR, __file__, 1,
                            "boom", None, (type(exc), exc, exc.__traceback__))
    handler.emit(rec)          # must not raise


def test_it_is_off_unless_configured(monkeypatch):
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", None)
    assert push_service.install_error_alerts() is False
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", "tok")
    monkeypatch.setattr(config, "PUSHOVER_USER", "usr")
    monkeypatch.setattr(config, "PUSH_ERROR_ALERTS", False)
    assert push_service.install_error_alerts() is False


def test_installing_twice_attaches_one_handler(monkeypatch):
    monkeypatch.setattr(config, "PUSHOVER_TOKEN", "tok")
    monkeypatch.setattr(config, "PUSHOVER_USER", "usr")
    monkeypatch.setattr(config, "PUSH_ERROR_ALERTS", True)
    root = logging.getLogger()
    before = [h for h in root.handlers if isinstance(h, push_service.PushErrorHandler)]
    for h in before:
        root.removeHandler(h)
    try:
        assert push_service.install_error_alerts() is True
        assert push_service.install_error_alerts() is True
        assert len([h for h in root.handlers
                    if isinstance(h, push_service.PushErrorHandler)]) == 1
    finally:
        for h in [h for h in root.handlers if isinstance(h, push_service.PushErrorHandler)]:
            root.removeHandler(h)


def test_no_secret_or_upload_data_in_the_alert(clean_state):
    """The alert carries the fault, not the payload."""
    exc = _raise(ValueError("bad value in column 'serial_number'"))
    push_service.alert_error("models", exc, "Failed to save model")
    (title, body), _ = clean_state[0]
    assert "tok" not in body and "usr" not in body
    assert len(body) < 500          # a summary, not a traceback dump
