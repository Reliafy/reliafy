"""What a user does: roles saved per user, everything shown by default,
and the one-time question for new users."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from backend.config import SAMPLE_OWNER
from backend.services import roles as roles_service

UID = "user-roles"
NOTHING = {"risk": False}


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["roles_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": UID, "email": "roles@example.org", "name": "Roles", "email_verified": True}
    try:
        yield TestClient(app), test_db
    finally:
        app.dependency_overrides.clear()


def test_roles_are_known_ids_each_once_in_the_order_picked():
    assert roles_service.clean(["technician", "planner", "technician"]) == ["technician", "planner"]
    assert roles_service.clean([]) == []
    for bad in (None, "analyst", ["analyst", "astronaut"], [3]):
        with pytest.raises(roles_service.BadRoles):
            roles_service.clean(bad)


def test_a_new_user_is_asked_once_and_sees_everything_until_they_answer(api):
    client, _ = api
    # First sight of the account (the profile is made on this request): new, so asked.
    assert client.get("/api/me/roles").json() == {"roles": [], "offer": True, "uses": NOTHING}
    assert client.post("/api/me/roles/dismiss").json() == {"roles": [], "offer": False}
    assert client.get("/api/me/roles").json() == {"roles": [], "offer": False, "uses": NOTHING}


def test_saving_roles_keeps_their_order_and_answers_the_question(api):
    client, db = api
    r = client.put("/api/me/roles", json={"roles": ["technician", "planner"]})
    assert r.status_code == 200 and r.json() == {"roles": ["technician", "planner"], "offer": False}
    assert client.get("/api/me/roles").json() == {"roles": ["technician", "planner"], "offer": False,
                                                  "uses": NOTHING}
    assert db.users.find_one({"_id": UID})["roles"] == ["technician", "planner"]
    # Clearing them shows everything again; the question stays answered.
    assert client.put("/api/me/roles", json={"roles": []}).json() == {"roles": [], "offer": False}


def test_unknown_roles_are_refused(api):
    client, _ = api
    for body in ({"roles": ["astronaut"]}, {"roles": "analyst"}, {}):
        r = client.put("/api/me/roles", json=body)
        assert r.status_code == 422, body
    assert client.get("/api/me/roles").json()["roles"] == []


def test_an_existing_user_isnt_asked_and_sees_everything(api):
    client, db = api
    db.users.insert_one({"_id": UID, "email": "roles@example.org",
                         "created_at": datetime.now(timezone.utc) - timedelta(days=90)})
    assert client.get("/api/me/roles").json() == {"roles": [], "offer": False, "uses": NOTHING}


def test_a_stored_role_no_longer_known_is_left_out(api):
    client, db = api
    db.users.insert_one({"_id": UID, "roles": ["planner", "retired-role"],
                         "created_at": datetime.now(timezone.utc)})
    assert client.get("/api/me/roles").json() == {"roles": ["planner"], "offer": False, "uses": NOTHING}


def test_risk_shows_once_the_workspace_tracks_items_or_fits_a_condition_model(api):
    client, db = api
    uses = lambda **h: client.get("/api/me/roles", headers=h).json()["uses"]  # noqa: E731
    # The shared samples (a tracked fleet, degradation and joint models) don't count.
    db.tracked_fleets.insert_one({"_id": "sample-tracked-trucks", "owner_id": SAMPLE_OWNER})
    db.models.insert_one({"_id": "sample-joint", "owner_id": SAMPLE_OWNER, "kind": "joint"})
    db.models.insert_one({"_id": "life", "owner_id": UID, "kind": "life"})
    assert uses() == {"risk": False}
    for collection, doc in (
        ("tracked_fleets", {"_id": "f1", "owner_id": UID}),
        ("degradation_models", {"_id": "d1", "owner_id": UID}),
        ("models", {"_id": "j1", "owner_id": UID, "kind": "joint"}),
    ):
        db[collection].insert_one(doc)
        assert uses() == {"risk": True}, collection
        db[collection].delete_one({"_id": doc["_id"]})
    # A team workspace answers for the team's own records; one the user isn't in, for nothing.
    db.teams.insert_one({"_id": "t1", "name": "Team", "owner_uid": UID, "members": [{"uid": UID, "role": "owner"}]})
    db.tracked_fleets.insert_one({"_id": "f2", "owner_id": UID})
    assert uses(**{"X-Workspace-Id": "t1"}) == {"risk": False}
    assert uses(**{"X-Workspace-Id": "nope"}) == {"risk": False}
    db.degradation_models.insert_one({"_id": "d2", "owner_id": "team:t1"})
    assert uses(**{"X-Workspace-Id": "t1"}) == {"risk": True}
