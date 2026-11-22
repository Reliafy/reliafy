"""The one search for everything (GET /api/search, list kind search): the ranking (exact,
prefix, whole words, inside, a near spelling), each kind found and where it opens, limits
and totals, and access: the active workspace's records only, samples the viewer hid left
out, Reliafy Maintenance's records only for its users, work orders only with work
management on."""

from datetime import datetime, timezone

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import global_search
from backend.services.global_search import Matcher

A, B, OP = "user-a", "user-b", "user-op"
USERS = {
    A: {"uid": A, "email": "a@example.org", "name": "A", "email_verified": True},
    B: {"uid": B, "email": "b@example.org", "name": "B", "email_verified": True},
    OP: {"uid": OP, "email": "op@example.org", "name": "Op", "email_verified": True},
}


# ---- the ranking ---------------------------------------------------------------------------

def test_tiers_exact_prefix_word_inside_near():
    m = Matcher("Oil filter")
    assert m.tier(["oil filter"]) == 0  # the whole name, any case
    assert m.tier(["Oil filter element"]) == 1
    assert m.tier(["Engine oil filter"]) == 2  # every word starts a word
    assert m.tier(["Foil filters"]) == 3  # inside words
    assert Matcher("oil filtr").tier(["Engine oil filter"]) == 4  # a letter missing: near
    assert Matcher("genrator").tier(["Portable generator set"]) == 4
    assert Matcher("genxxtxr set").tier(["Portable generator set"]) is None  # too far
    assert Matcher("generatro").tier(["Portable generator set"]) == 4  # a swap counts as one
    assert Matcher("pupm").tier(["Filter pump"]) == 4
    assert Matcher("avr").tier(["AVR mk 2"]) == 1
    assert Matcher("avx").tier(["AVR mk 2"]) is None  # short words match only as typed
    assert Matcher("P-101").tier(["Filter pump", "P-101"]) == 0  # a tag is a key
    assert Matcher("io-16").tier(["IO-16-A module"]) == 1
    assert Matcher("gs-1001").tier(["TP-1001 · Transfer pump"]) is None  # codes only as typed
    assert Matcher("pump").tier(["Valve"], ["notes about a pump"]) == 2  # extra words match, never exact
    assert Matcher("valve").tier(["Valve"], ["x"]) == 0
    assert not Matcher("   ") and Matcher("  ").tier(["x"]) is None
    # Another first letter is another word, not a typo; a swap of the first two still is.
    assert Matcher("mower").tier(["Lower bathroom toilet"]) is None
    assert Matcher("mower").tier(["Power"]) is None
    assert Matcher("omwer").tier(["Ride-on mower"]) == 4
    assert Matcher("mower", near=False).tier(["Ride-on mowr"]) is None


def test_near_spellings_only_when_nothing_matches_as_typed(client):
    db = client.db
    _doc(db, "datasets", "d1", "Ride-on mower failures", A)
    _doc(db, "rbds", "b1", "Mowing deck", A)  # near "mower" only as a fallback
    _doc(db, "models", "m1", "Mover gearbox", A)  # one letter from "mower"
    client.act_as(A)
    g = _search(client, "mower")
    assert _names(g, "dataset") == ["Ride-on mower failures"] and "model" not in g
    g = _search(client, "mowr")  # nothing as typed: the near spellings
    assert _names(g, "dataset") == ["Ride-on mower failures"]


def test_ranked_best_first_then_by_name():
    hits = [{"name": "b", "tier": 2}, {"name": "A", "tier": 2}, {"name": "z", "tier": 0}]
    assert [h["name"] for h in global_search.ranked(hits)] == ["z", "A", "b"]


def test_unknown_kinds_are_refused_in_words():
    assert global_search.parse_kinds(None) == set(global_search.KINDS)
    assert global_search.parse_kinds("part, model") == {"part", "model"}
    with pytest.raises(ValueError, match="Unknown kind spaceship"):
        global_search.parse_kinds(["spaceship"])


# ---- the register (Reliafy Maintenance) -----------------------------------------------------

@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), "user-search", "tester")


def _plant(m):
    """Riverside › Pump house holding Pumping station › Filter pump (P-101, Grundfos CR
    SN-42 fitted); a store with oil filters (part OF-200, 3 on hand); a product, Portable
    generator set (part GEN-5), with an AVR position in its design and one built, G-1."""
    site = m.create_location("Riverside")["id"]
    house = m.create_location("Pump house", parent_id=site)["id"]
    store = m.create_location("Depot store", parent_id=site)["id"]
    station = m.create_position("Pumping station", location_id=house)["id"]
    p1 = m.create_position("Filter pump", tag="P-101", parent_id=station)["id"]
    m.fit(p1, new_item={"name": "Grundfos CR", "serial": "SN-42"})
    part = m.create_part("OF-200", "Oil filter")["id"]
    m.adjust_stock(part, store, 3)
    gen = m.create_product("Portable generator set", part_number="GEN-5")
    avr = m.create_position("AVR", parent_id=gen["id"])["id"]
    m.build_item(gen["id"], "G-1", dry_run=False)
    return dict(site=site, house=house, store=store, station=station, p1=p1, part=part, gen=gen["id"], avr=avr)


def _find(m, q, kinds, limit=5):
    return m.search_records(Matcher(q).tier, set(kinds), limit)


def test_a_part_by_number_or_name_with_its_stock(m):
    ids = _plant(m)
    total, hits = _find(m, "OF-200", ["part"])["part"]
    assert total == 1 and hits[0]["id"] == ids["part"] and hits[0]["tier"] == 0
    assert hits[0]["name"] == "OF-200 · Oil filter" and "3 on hand" in hits[0]["context"]
    assert hits[0]["path"] == f"/asset-register/parts/{ids['part']}"
    assert _find(m, "oil filtr", ["part"])["part"][1][0]["id"] == ids["part"]  # a typo


def test_a_product_by_name_and_its_design_positions_open_on_it(m):
    ids = _plant(m)
    _, products = _find(m, "generator", ["product"])["product"]
    assert [p["id"] for p in products] == [ids["gen"]]
    assert products[0]["path"] == f"/products/{ids['gen']}" and "part GEN-5" in products[0]["context"]
    _, positions = _find(m, "avr", ["position"])["position"]
    design = next(p for p in positions if p["id"] == ids["avr"])
    assert design["path"] == f"/products/{ids['gen']}?sel={ids['avr']}"
    assert design["context"].startswith("In product Portable generator set")
    # The built unit's own AVR is an asset's position, opening in the Explorer.
    assert any(p["id"] != ids["avr"] and p["path"].startswith("/asset-register/explorer?") for p in positions)


def test_a_position_by_tag_opens_in_the_explorer_on_its_asset(m):
    ids = _plant(m)
    _, hits = _find(m, "p-101", ["position"])["position"]
    assert hits[0]["id"] == ids["p1"] and hits[0]["name"] == "P-101 · Filter pump" and hits[0]["tier"] == 0
    assert hits[0]["path"] == f"/asset-register/explorer?arrange=locations&root={ids['site']}&sel={ids['p1']}"
    assert "Riverside" in hits[0]["context"]


def test_assets_locations_and_items(m):
    ids = _plant(m)
    found = _find(m, "riverside depot", ["asset", "location"])
    assert found["asset"] == (0, []) and found["location"][1][0]["id"] == ids["store"]
    assert found["location"][1][0]["path"] == (
        f"/asset-register/explorer?arrange=locations&root={ids['site']}&sel={ids['store']}")
    asset = _find(m, "riverside", ["asset"])["asset"][1][0]
    assert asset["path"] == f"/asset-register/explorer?arrange=locations&root={ids['site']}&sel={ids['site']}"
    item = _find(m, "sn-42", ["item"])["item"][1][0]
    assert item["tier"] == 0 and "fitted to Filter pump" in item["context"]
    assert item["path"].endswith(f"root={ids['site']}&sel={ids['p1']}")


def test_limit_keeps_the_best_and_counts_them_all(m):
    site = m.create_location("Yard")["id"]
    for i in range(7):
        m.create_position(f"Pump {i}", location_id=site)
    m.create_position("Pump", location_id=site)
    total, hits = _find(m, "pump", ["position"], limit=3)["position"]
    assert total == 8 and len(hits) == 3 and hits[0]["name"] == "Pump" and hits[0]["tier"] == 0


def test_work_orders_by_number_or_title(m):
    ids = _plant(m)
    wo = m.open_work_order(ids["p1"], "Replace seal")
    _, hits = _find(m, "replace seal", ["work_order"])["work_order"]
    assert hits[0]["id"] == wo["id"] and hits[0]["path"] == f"/maintenance/work-orders/{wo['id']}"


# ---- over HTTP: access ---------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"op@example.org"})
    monkeypatch.setattr(config, "WORK_MANAGEMENT", True)
    test_db = mongomock.MongoClient()["global_search"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    for uid, u in USERS.items():
        test_db.users.update_one({"_id": uid}, {"$set": {"email": u["email"], "email_lc": u["email"],
                                                         "email_verified": True, "name": u["name"]}}, upsert=True)
    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: dict(USERS[uid])

    tc.act_as, tc.db, tc.store = act_as, test_db, store
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _doc(db, coll, _id, name, owner, **extra):
    db[coll].insert_one({"_id": _id, "name": name, "owner_id": owner,
                         "created_at": datetime(2026, 11, 3, tzinfo=timezone.utc), **extra})


def _search(client, q, ws=None, **params):
    headers = {"X-Workspace-Id": ws} if ws else {}
    r = client.get("/api/search", params={"q": q, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return {g["kind"]: g for g in r.json()["groups"]}


def _names(groups, kind):
    return [r["name"] for r in groups.get(kind, {}).get("results", [])]


def test_each_kind_of_saved_record_is_found_and_opens_on_its_page(client):
    from backend.config import SAMPLE_OWNER

    db = client.db
    _doc(db, "datasets", "d1", "Haul truck pumps", A)
    _doc(db, "models", "m1", "Haul truck pump life", A, kind="distribution", results={"distribution": "Weibull"})
    _doc(db, "models", "j1", "Haul truck pump condition", A, kind="joint")
    _doc(db, "recurrent_models", "r1", "Haul truck pump repairs", A)
    _doc(db, "rbds", "b1", "Haul truck pump system", A)
    _doc(db, "fault_trees", "f1", "Haul truck pump trip", A)
    _doc(db, "strategy_analyses", "s1", "Haul truck pump test plan", A, kind="demonstration_test")
    _doc(db, "fleets", "fl1", "Haul truck pump fleet", A)
    _doc(db, "reports", "rp1", "Haul truck pump review", A)
    _doc(db, "rcm_studies", "rc1", "Haul truck pump RCM", A)
    _doc(db, "models", "sm", "Sample haul truck pump", SAMPLE_OWNER)
    client.act_as(A)
    g = _search(client, "haul truck pump", limit=20)
    assert _names(g, "dataset") == ["Haul truck pumps"] and g["dataset"]["results"][0]["path"] == "/data/d1"
    paths = {r["id"]: r["path"] for r in g["model"]["results"]}
    assert paths == {"m1": "/models/m/m1", "j1": "/models/joint/j1", "r1": "/models/recurrent/r1",
                     "sm": "/models/m/sm"}
    life = next(r for r in g["model"]["results"] if r["id"] == "m1")
    assert life["context"] == "Non-repairable model · Weibull" and life["updated_at"].startswith("2026-11-03")
    assert next(r for r in g["model"]["results"] if r["id"] == "sm")["sample"] is True
    assert g["rbd"]["results"][0]["path"] == "/systems/b/b1"
    assert g["fault_tree"]["results"][0]["path"] == "/systems/fault-trees/f1"
    analyses = {r["id"]: (r["path"], r["context"]) for r in g["analysis"]["results"]}
    assert analyses["s1"] == ("/strategy/analyses/s1", "Test plan (demonstration test)")
    assert analyses["fl1"][0] == "/forecasts/fl1" and analyses["rc1"][0] == "/maintenance/rcm/rc1"
    assert g["report"]["results"][0]["path"] == "/reports?open=rp1"
    # Only the kinds asked for.
    assert set(_search(client, "haul truck pump", kinds="rbd,dataset")) == {"rbd", "dataset"}
    r = client.get("/api/search", params={"q": "x", "kinds": "spaceship"})
    assert r.status_code == 422 and "spaceship" in r.json()["detail"]
    assert client.get("/api/search", params={"q": " "}).json() == {"q": "", "groups": [], "took_ms": 0}


def test_the_best_group_comes_first_and_limits_hold(client):
    db = client.db
    for i in range(8):
        _doc(db, "datasets", f"d{i}", f"Conveyor data {i}", A)
    _doc(db, "rbds", "b", "Conveyor", A)
    client.act_as(A)
    r = client.get("/api/search", params={"q": "conveyor", "limit": 3}).json()
    assert [g["kind"] for g in r["groups"]][:2] == ["rbd", "dataset"]  # the exact name leads
    data = r["groups"][1]
    assert data["total"] == 8 and len(data["results"]) == 3
    assert client.get("/api/search", params={"q": "x", "limit": 99}).status_code == 422


def test_never_another_workspaces_names(client):
    db = client.db
    _doc(db, "datasets", "mine", "Gearbox mine", A)
    _doc(db, "datasets", "theirs", "Gearbox theirs", B)
    client.act_as(A)
    tid = client.post("/api/teams", json={"name": "Crew"}).json()["id"]
    _doc(db, "datasets", "team", "Gearbox team", f"team:{tid}")
    assert _names(_search(client, "gearbox"), "dataset") == ["Gearbox mine"]
    # In the team's workspace: the team's alone (team lists leave the samples out too).
    assert _names(_search(client, "gearbox", ws=tid), "dataset") == ["Gearbox team"]
    client.act_as(B)
    assert _names(_search(client, "gearbox"), "dataset") == ["Gearbox theirs"]
    assert client.get("/api/search", params={"q": "gearbox"}, headers={"X-Workspace-Id": tid}).status_code == 403
    client.act_as(None)
    assert client.get("/api/search", params={"q": "gearbox"}).status_code == 401


def test_a_hidden_sample_and_a_shared_item(client):
    from backend.config import SAMPLE_OWNER

    db = client.db
    _doc(db, "datasets", "s1", "Bearing sample", SAMPLE_OWNER)
    _doc(db, "datasets", "s2", "Bearing other sample", SAMPLE_OWNER)
    _doc(db, "datasets", "bs", "Bearing of B", B)
    db.users.update_one({"_id": A}, {"$set": {"hidden_samples": ["s2"]}})
    db.shares.insert_one({"_id": "sh", "recipient_uid": A, "collection": "datasets", "artifact_id": "bs"})
    client.act_as(A)
    assert sorted(_names(_search(client, "bearing"), "dataset")) == ["Bearing of B", "Bearing sample"]


def test_maintenance_records_only_for_its_users_and_work_orders_only_with_work_management(client, monkeypatch):
    from backend import config

    m = Maintenance(client.store, OP, OP)
    ids = _plant(m)
    m.open_work_order(ids["p1"], "Replace seal")
    other = Maintenance(client.store, A, A)
    other.create_part("OF-201", "Oil filter of A")
    client.act_as(OP)
    g = _search(client, "oil filter")
    assert _names(g, "part") == ["OF-200 · Oil filter"]  # its own register only
    assert _names(_search(client, "replace seal"), "work_order") == ["Replace seal"]
    monkeypatch.setattr(config, "WORK_MANAGEMENT", False)
    assert "work_order" not in _search(client, "replace seal")
    client.act_as(A)  # not one of Maintenance's users
    assert not set(_search(client, "oil filter")) & set(global_search.MAINTENANCE_KINDS)


def test_the_mcp_and_rest_twin(client, monkeypatch, mcp_on):
    from backend.services import tokens

    _doc(client.db, "rbds", "b1", "Cooling water", A)
    _doc(client.db, "rbds", "b2", "Cooling water of B", B)
    token = tokens.create_token(client.db, A, "api")["token"]
    client.act_as(None)
    r = client.post("/api/v1/list/search", json={"q": "cooling watr"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_notice"]
    rbds = next(g for g in body["groups"] if g["kind"] == "rbd")["results"]
    assert [x["id"] for x in rbds] == ["b1"] and rbds[0]["url"].endswith("/systems/b/b1")
    assert "tier" not in rbds[0] and "path" not in rbds[0]
    r = client.post("/api/v1/list/search", json={"q": "x", "kinds": ["nope"]},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code >= 400 and "Unknown kind nope" in r.text
