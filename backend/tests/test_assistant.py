"""The metered assistant's provider request body.

The one setting worth pinning is ``store``: it decides whether OpenAI retains
each response for the operator to read back. It must stay off unless an operator
deliberately turns it on, because it moves user conversations into a provider's
retention — a self-hosted instance should not start doing that on upgrade.
"""

from backend import config
from backend.services import assistant


def _body(**over):
    return assistant._openai_body("sys", [{"role": "user", "content": "hi"}], [], stream=False, **over)


def test_store_is_off_by_default():
    """Default must be private: no provider-side transcript retention."""
    assert config.AI_STORE is False
    assert _body()["store"] is False


def test_store_follows_config(monkeypatch):
    monkeypatch.setattr(config, "AI_STORE", True)
    assert _body()["store"] is True
    monkeypatch.setattr(config, "AI_STORE", False)
    assert _body()["store"] is False


def test_store_does_not_change_what_we_send(monkeypatch):
    """``store`` is purely a provider-side retention flag. The conversation is
    resent in full every step either way, so turning it on must not alter the
    request — otherwise enabling logging would quietly change the assistant."""
    monkeypatch.setattr(config, "AI_STORE", False)
    off = _body()
    monkeypatch.setattr(config, "AI_STORE", True)
    on = _body()
    assert {k: v for k, v in off.items() if k != "store"} == \
           {k: v for k, v in on.items() if k != "store"}


def test_env_parsing_is_forgiving(monkeypatch):
    """Operators write AI_STORE=true/1/yes; anything else means off."""
    import importlib

    for raw, want in (("true", True), ("TRUE", True), ("1", True), ("yes", True),
                      ("on", True), ("false", False), ("", False), ("nope", False)):
        monkeypatch.setenv("AI_STORE", raw)
        assert importlib.reload(config).AI_STORE is want, raw
    monkeypatch.delenv("AI_STORE", raising=False)
    assert importlib.reload(config).AI_STORE is False
