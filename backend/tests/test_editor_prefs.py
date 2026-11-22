"""The signed-in user's editor preferences: the RBD builder's autosave (on unless turned off)."""

import mongomock
import pytest

ME = {"uid": "u-ed", "email": "ed@mail.example.org", "name": "Ed"}


@pytest.fixture()
def test_db(monkeypatch):
    from backend import db

    d = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", d)
    monkeypatch.setattr(db, "_simulated", True)
    return d


@pytest.fixture()
def client(test_db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db.users.insert_one({"_id": ME["uid"], "email": ME["email"], "name": ME["name"]})
    app.dependency_overrides[get_current_user] = lambda: ME
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_autosave_is_on_until_turned_off(client, test_db):
    assert client.get("/api/me/editor-preferences").json() == {"autosave": True}
    assert client.put("/api/me/editor-preferences", json={"autosave": False}).json() == {"autosave": False}
    assert test_db.users.find_one({"_id": ME["uid"]})["editor_prefs"] == {"autosave": False}
    assert client.get("/api/me/editor-preferences").json() == {"autosave": False}
    assert client.put("/api/me/editor-preferences", json={"autosave": True}).json() == {"autosave": True}
    assert client.put("/api/me/editor-preferences", json={}).status_code == 422


def test_signed_out_is_refused(test_db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    c = TestClient(app)
    assert c.get("/api/me/editor-preferences").status_code == 401
    assert c.put("/api/me/editor-preferences", json={"autosave": False}).status_code == 401
