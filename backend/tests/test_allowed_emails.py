"""ALLOWED_EMAILS turns a deployment into a private test site."""

import pytest
from fastapi import HTTPException

from backend import auth, config


def _claims(email, verified=True):
    return {"uid": "u1", "email": email, "name": "N", "email_verified": verified}


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DISABLED", False)

    def as_user(email, verified=True):
        monkeypatch.setattr(auth, "_verified_claims", lambda token: _claims(email, verified))
        return auth.get_current_user("Bearer t")

    return as_user


def test_open_by_default(signed_in, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", set())
    assert signed_in("anyone@example.com")["email"] == "anyone@example.com"


def test_listed_verified_address_gets_in_whatever_the_case(signed_in, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", {"me@example.com"})
    assert signed_in("Me@Example.com")["uid"] == "u1"


def test_other_address_is_refused(signed_in, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", {"me@example.com"})
    with pytest.raises(HTTPException) as e:
        signed_in("you@example.com")
    assert e.value.status_code == 403


def test_listed_but_unverified_address_is_refused(signed_in, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", {"me@example.com"})
    with pytest.raises(HTTPException) as e:
        signed_in("me@example.com", verified=False)
    assert e.value.status_code == 403
