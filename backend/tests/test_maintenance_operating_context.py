"""A position's operating context: how it's used (the load, the environment, the
hours it runs), a text field of its own beside the short description. Set on
create and update (the app's routes, MCP and the REST API), carried by a copy,
replayed the same, and harmless to code that doesn't know it."""

import mongomock
import pytest

from backend.maintenance.service import LONG_TEXT, PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore, new_id

ORG = "user-a"
SAID = "Runs 20 hours a day.\n\nSalt air, 35 °C summers; full load from 6 am."


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def test_set_on_create_changed_cleared_and_kept_apart_from_the_description(m):
    plain = m.create_position("Pump A", description="Centrifugal pump")
    assert m.position(plain["id"])["operating_context"] == ""
    assert "operating_context" not in plain  # never stored empty: older events replay as before
    p = m.create_position("Pump B", description="Centrifugal pump", operating_context=f"  {SAID}  ")
    got = m.position(p["id"])
    assert got["operating_context"] == SAID and got["description"] == "Centrifugal pump"

    m.update_position(p["id"], name="Pump B1")  # other changes leave it alone
    assert m.position(p["id"])["operating_context"] == SAID
    m.update_position(p["id"], operating_context="Standby only.")
    assert m.position(p["id"])["operating_context"] == "Standby only."
    m.update_position(p["id"], operating_context="")
    assert m.position(p["id"])["operating_context"] == ""
    assert m.position(p["id"])["description"] == "Centrifugal pump"


def test_the_same_length_limit_as_the_description(m):
    p = m.create_position("Pump", operating_context="x" * LONG_TEXT)
    assert len(m.position(p["id"])["operating_context"]) == LONG_TEXT
    with pytest.raises(Invalid) as err:
        m.create_position("Pump 2", operating_context="x" * (LONG_TEXT + 1))
    assert str(err.value) == f"The operating context is at most {LONG_TEXT} characters; this one is {LONG_TEXT + 1}. " \
                             "Shorten it."
    with pytest.raises(Invalid):
        m.update_position(p["id"], operating_context="y" * (LONG_TEXT + 1))


def test_a_copy_carries_it_and_the_log_replays_the_same(m):
    top = m.create_position("Station 1", operating_context=SAID)
    m.create_position("Pump", parent_id=top["id"])
    copy = m.copy_position(top["id"], "Station 2")
    assert m.position(copy["id"])["operating_context"] == SAID
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
    m.s.rebuild()  # twice: still the same
    assert m.s.snapshot() == before


# The projectors as they were before the field (the live code until this ships), to
# show that replaying the new events through them works and changes nothing else.
def _old_created(s, org, p):
    s.put_node(org, p["id"], "Position", {
        "name": p["name"], "tag": p.get("tag", ""), "position_class": p.get("position_class", ""),
        "description": p.get("description", ""), "created": p["on"],
    })
    if p.get("parent_id"):
        s.put_edge(org, "PART_OF", p["id"], p["parent_id"])
    if p.get("location_id"):
        s.put_edge(org, "LOCATED_AT", p["id"], p["location_id"])


def _old_updated(s, org, p):
    changes = {k: v for k, v in p["changes"].items() if k not in ("parent_id", "location_id")}
    if changes:
        s.patch_node(org, p["id"], changes)


def test_the_code_before_the_field_replays_the_new_events_harmlessly(m):
    p = m.create_position("Pump", description="Centrifugal pump", operating_context=SAID)
    q = m.create_position("Fan", description="Axial fan")
    m.update_position(q["id"], operating_context="Dusty; runs on demand.")

    old = GraphStore(":memory:", {**PROJECTORS, "position.created": _old_created,
                                  "position.updated": _old_updated})
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert "operating_context" not in old.node(ORG, p["id"])  # an unknown key on create: ignored
    assert old.node(ORG, p["id"])["description"] == "Centrifugal pump"
    # On update, the old projector patches every key it's given: stored, unused, harmless.
    assert old.node(ORG, q["id"])["operating_context"] == "Dusty; runs on demand."
    assert Maintenance(old, ORG, "tester").position(q["id"])["name"] == "Fan"


def test_over_the_app_routes(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_ctx"])
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    try:
        client = TestClient(app)
        made = client.post("/api/maintenance/positions", json={"name": "Pump", "operating_context": SAID})
        assert made.status_code == 200, made.text
        pid = made.json()["id"]
        assert client.get(f"/api/maintenance/positions/{pid}").json()["operating_context"] == SAID
        r = client.patch(f"/api/maintenance/positions/{pid}", json={"operating_context": "Indoors."})
        assert r.status_code == 200 and r.json()["operating_context"] == "Indoors."
        r = client.patch(f"/api/maintenance/positions/{pid}", json={"operating_context": ""})
        assert r.json()["operating_context"] == ""
        r = client.patch(f"/api/maintenance/positions/{pid}", json={"operating_context": "z" * (LONG_TEXT + 1)})
        assert r.status_code == 422 and "operating context is at most" in r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
