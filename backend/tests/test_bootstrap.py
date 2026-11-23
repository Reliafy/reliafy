"""The app frame's one request (GET /api/me/bootstrap): each part is what its own
route answers; a part that fails is named and the rest still come back; the old
routes stay."""

import pytest
from fastapi.testclient import TestClient

UID = "user-boot"
USER = {"uid": UID, "email": "a@x.com", "name": "Ann", "email_verified": True}

ROUTES = {
    "me": "/api/me",
    "roles": "/api/me/roles",
    "time_zone": "/api/me/time-zone",
    "currency": "/api/me/currency",
    "teams": "/api/teams",
    "invites": "/api/teams/invites",
    "extensions": "/api/extensions",
    "maintenance_access": "/api/maintenance/access",
}


@pytest.fixture()
def client(monkeypatch):
    import mongomock

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    monkeypatch.setattr(db_mod, "_db", mongomock.MongoClient()["bootstrap_test"])
    monkeypatch.setattr(db_mod, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USER
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def _settled(client):
    # The first read upserts the profile: read once so both sides see the same user.
    assert client.get("/api/me/bootstrap").status_code == 200


def test_each_part_is_what_its_own_route_answers(client):
    client.put("/api/me/time-zone", json={"time_zone": "Australia/Brisbane"})
    client.put("/api/me/currency", json={"currency_symbol": "€"})
    client.put("/api/me/roles", json={"roles": ["analyst"]})
    _settled(client)
    out = client.get("/api/me/bootstrap").json()
    assert out["errors"] == {}
    singles = {name: client.get(url) for name, url in ROUTES.items()}
    for name, res in singles.items():
        assert res.status_code == 200, (name, res.text)
        assert out["parts"][name] == res.json(), name
    assert out["parts"]["time_zone"] == {"time_zone": "Australia/Brisbane"}
    assert out["parts"]["currency"] == {"currency_symbol": "€"}
    assert out["parts"]["maintenance_access"]["allowed"] is True


def test_roles_follow_the_workspace_asked_for(client):
    _settled(client)
    headers = {"X-Workspace-Id": "team-not-mine"}
    out = client.get("/api/me/bootstrap", headers=headers).json()
    assert out["parts"]["roles"] == client.get("/api/me/roles", headers=headers).json()


def test_a_part_that_fails_is_named_and_the_rest_still_come_back(client, monkeypatch):
    from backend.routers import auth

    def broken(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(auth, "get_roles", broken)
    r = client.get("/api/me/bootstrap")
    assert r.status_code == 200
    out = r.json()
    assert set(out["errors"]) == {"roles"}
    assert {"me", "teams", "time_zone", "extensions", "maintenance_access"} <= set(out["parts"])


def test_signed_out_it_is_refused(client):
    from backend.auth import get_current_user
    from backend.main import app

    app.dependency_overrides.pop(get_current_user, None)
    assert client.get("/api/me/bootstrap").status_code == 401
