"""The Data model page's design layer (backend/maintenance/graph_design.py): the
``data_model`` document in app_settings, checked and returned to people with
graph access only, and never written by the app. The documents here are tiny
and invented."""

import mongomock
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import config
from backend.maintenance import graph_design
from backend.maintenance.graph_design import DataModelDesign
from backend.maintenance.service import PROJECTORS
from backend.maintenance.store import GraphStore

OWNER, OTHER = "owner-1", "other-1"

DESIGN = {
    "_id": "data_model",
    "updated": "2026-10-01T09:00:00+00:00",
    "nodes": [
        {"id": "w", "label": "Widget", "structure": "thing", "definition": "A small thing.\nIt fits in a box."},
        {"id": "b", "label": "Box"},
        {"id": "c", "label": "Crate", "definition": "A big box."},
    ],
    "edges": [
        {"from": "w", "type": "INSIDE", "to": "b", "status": "decided"},
        {"from": "b", "type": "INSIDE", "to": "c", "status": "proposed", "note": "Boxes go in crates."},
        {"from": "w", "type": "NEXT_TO", "to": "w"},
    ],
}


@pytest.fixture()
def env(monkeypatch):
    from backend import db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"owner@example.org", "m@example.org"})
    monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", {"owner@example.org"})
    test_db = mongomock.MongoClient()["reliafy_graph_design"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    users = {OWNER: {"uid": OWNER, "email": "owner@example.org", "name": "O", "email_verified": True},
             OTHER: {"uid": OTHER, "email": "m@example.org", "name": "M", "email_verified": True}}
    for u in users.values():
        test_db.users.insert_one({"_id": u["uid"], "email": u["email"], "name": u["name"], "email_verified": True})
    who = {"user": users[OWNER]}
    app.dependency_overrides[get_current_user] = lambda: who["user"]

    def as_user(uid):
        who["user"] = users[uid]

    try:
        yield type("Env", (), {"db": test_db, "client": TestClient(app), "as_user": staticmethod(as_user)})
    finally:
        app.dependency_overrides.clear()


def test_graph_access_only_and_access_says_who_has_it(env):
    env.db.app_settings.insert_one(dict(DESIGN))
    env.as_user(OTHER)  # Maintenance, but no graph access
    assert env.client.get("/api/maintenance/graph/design").status_code == 404
    assert env.client.get("/api/maintenance/access").json() == {"allowed": True, "graph": False}
    env.as_user(OWNER)
    assert env.client.get("/api/maintenance/access").json() == {"allowed": True, "graph": True}
    assert env.client.get("/api/maintenance/graph/design").status_code == 200


def test_none_stored_says_so(env):
    r = env.client.get("/api/maintenance/graph/design")
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": "No design has been stored yet."}


def test_the_stored_design_comes_back_checked_and_unchanged_in_the_database(env):
    env.db.app_settings.insert_one(dict(DESIGN))
    before = env.db.app_settings.find_one({"_id": "data_model"})
    got = env.client.get("/api/maintenance/graph/design").json()
    assert got["available"] is True and got["updated"] == "2026-10-01T09:00:00+00:00"
    assert [n["label"] for n in got["nodes"]] == ["Widget", "Box", "Crate"]
    assert got["nodes"][1] == {"id": "b", "label": "Box", "structure": None, "definition": None}
    assert got["edges"][1] == {"from": "b", "type": "INSIDE", "to": "c", "status": "proposed",
                               "note": "Boxes go in crates."}
    assert got["edges"][2]["status"] == "decided"  # the default
    assert "_id" not in got
    # Read only: the stored document is as it was, and nothing else was written.
    assert env.db.app_settings.find_one({"_id": "data_model"}) == before
    assert env.db.app_settings.count_documents({}) == 1


def test_a_document_that_fails_its_checks_is_not_drawn_and_the_reason_is_plain(env):
    bad = dict(DESIGN, edges=[{"from": "w", "type": "INSIDE", "to": "nowhere"}])
    env.db.app_settings.insert_one(bad)
    got = env.client.get("/api/maintenance/graph/design").json()
    assert got["available"] is False
    assert got["reason"].startswith("The stored design doesn't pass its checks")
    assert "nowhere" in got["reason"] and "nodes" not in got


def test_a_stored_date_comes_back_as_iso_text():
    from datetime import datetime, timezone

    doc = DataModelDesign.model_validate(dict(DESIGN, updated=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    assert doc.public()["updated"] == "2026-10-01T00:00:00+00:00"


@pytest.mark.parametrize("change, problem", [
    ({"nodes": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]}, "used twice"),
    ({"nodes": [{"id": "a b", "label": "A"}]}, "letters, digits"),
    ({"nodes": [{"id": "a", "label": "<b>A</b>"}]}, "letters, digits"),
    ({"nodes": [{"id": "a", "label": "A" * 65}]}, "at most 64"),
    ({"nodes": [{"id": "a", "label": "A", "definition": "x" * 1001}]}, "at most 1000"),
    ({"nodes": [{"id": f"n{i}", "label": "A"} for i in range(graph_design.MAX_NODES + 1)]}, "at most 200"),
    ({"edges": [{"from": "w", "type": "IN SIDE", "to": "b"}]}, "letters, digits"),
    ({"edges": [{"from": "w", "type": "INSIDE", "to": "b", "status": "maybe"}]}, "'decided' or 'proposed'"),
    ({"edges": [{"from": "w", "type": "INSIDE", "to": "zz"}]}, "isn't listed: zz"),
    ({"updated": "x" * 41}, "too long"),
    ({"nodes": "Widget"}, "valid list"),
])
def test_the_checks(change, problem):
    with pytest.raises(ValidationError) as err:
        DataModelDesign.model_validate(dict(DESIGN, **change))
    assert problem in str(err.value)


def test_text_is_kept_as_plain_text():
    """Free text comes back as text (the page shows it as text, never as HTML):
    control characters dropped, new lines kept, markup left as typed."""
    doc = DataModelDesign.model_validate(dict(DESIGN, nodes=[
        {"id": "w", "label": "Widget", "definition": "  <script>alert(1)</script>\x00\x1b line\nnext  "},
        {"id": "b", "label": "Box", "structure": "\x07"},
        {"id": "c", "label": "Crate"},
    ]))
    nodes = doc.public()["nodes"]
    assert nodes[0]["definition"] == "<script>alert(1)</script> line\nnext"
    assert nodes[1]["structure"] is None  # nothing left once the control character goes


def test_extra_keys_are_ignored():
    doc = DataModelDesign.model_validate(dict(DESIGN, extra={"x": 1}, nodes=[
        {"id": "w", "label": "Widget", "colour": "red"}, {"id": "b", "label": "Box"}, {"id": "c", "label": "Crate"}]))
    assert "colour" not in doc.public()["nodes"][0] and "extra" not in doc.public()
