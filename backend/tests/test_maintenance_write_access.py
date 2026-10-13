"""Reliafy Maintenance: a team member who may only view, or anyone in a frozen
team, can read the team's maintenance data but not change it."""

import mongomock
import pytest

from backend.maintenance import photos
from backend.maintenance.service import PROJECTORS
from backend.maintenance.store import GraphStore

UID = "user-l"


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"l@example.org"})
    test_db = mongomock.MongoClient()["maint_limits_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    user = {"uid": UID, "email": "l@example.org", "name": "L", "email_verified": True}
    test_db.users.insert_one({"_id": UID, "email": "l@example.org", "name": "L", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield {"client": TestClient(app), "db": test_db, "user": user, "app": app, "router": router}
    finally:
        app.dependency_overrides.clear()



def test_view_only_and_frozen_team_members_cant_write(api):
    from backend.services.access import AccessCtx, get_access

    client, app = api["client"], api["app"]
    pid = None
    for frozen, view_only in ((True, False), (False, True)):
        def ctx(frozen=frozen, view_only=view_only):
            return AccessCtx(user=api["user"], uid=UID, workspace="t1", write_owner="team:t1",
                             read_owners=[UID, "team:t1"], list_owners=["team:t1"], frozen=frozen,
                             member_view_only=view_only)
        app.dependency_overrides[get_access] = ctx
        r = client.post("/api/maintenance/positions", json={"name": "P"})
        assert r.status_code == 402
        assert r.json()["code"] == ("team_frozen" if frozen else "member_pro_required") and r.json()["upgrade"]
        assert client.post("/api/maintenance/photo-links", json={"target_id": "x"}).status_code == 402
        assert client.delete("/api/maintenance/photos/x").status_code == 402
        assert client.get("/api/maintenance/overview").status_code == 200  # reading still works
        assert client.patch("/api/maintenance/settings", json={"digest": False}).status_code == 200  # their own
    app.dependency_overrides.pop(get_access)
    pid = client.post("/api/maintenance/positions", json={"name": "P"}).json()["id"]
    assert pid
