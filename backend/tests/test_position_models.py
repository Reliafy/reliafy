"""Life models on positions (the Explorer's Modelling tab, position_models.py): a link
names a saved model (never a copy), attaching and taking off are events that replay to
the same graph, a position's own history (or its class's) is fitted and attached, a built
item inherits its design's links, the reads describe each model and what uses it, and the
interval calculators start from them."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore

ORG = "org-models"
SAMPLE = "sample-model-bearings-weibull"
OWNERS = [ORG, "__samples__"]


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["position_models"]
    samples.seed_samples(d)
    return d


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _history(m, pid, lives, mode_ids=None, start=date(2018, 1, 1)):
    """Items fitted one after another at a position, each failing after its life (by the
    mode given for it, if any)."""
    on = start
    for i, life in enumerate(lives):
        m.fit(pid, new_item={"name": f"Unit {pid[-4:]}-{i}"}, on=on.isoformat())
        on = on + timedelta(days=life)
        mode = (mode_ids or [None] * len(lives))[i]
        m.remove(pid, on=on.isoformat(), reason="failure", failure_mode_id=mode)


def test_link_and_unlink_are_events_that_replay(m, db):
    pump = m.create_position("Pump A")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, [seal], note="Same bearings as the OEM's")
    assert link["role"] == "assigned" and link["model_id"] == SAMPLE and link["name"].startswith("Bearing life")
    assert link["failure_modes"] == [{"id": seal, "text": "Seal leaks", "gone": False}]
    assert [x["id"] for x in m.position(pump)["models"]] == [link["id"]]
    # Linked, never copied: the model store holds the one sample.
    assert db.models.count_documents({"_id": SAMPLE}) == 1
    _same_after_rebuild(m)
    with pytest.raises(Invalid, match="already on Pump A"):
        pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, [seal])
    with pytest.raises(NotFound):
        pm.link_saved(m, db, OWNERS, set(), pump, "model", "no-such-model")
    other = m.create_position("Pump B")["id"]
    elsewhere = m.add_failure_mode(other, "Impeller wear")["id"]
    with pytest.raises(Invalid, match="failure modes of this position"):
        m.link_position_model(pump, "model", SAMPLE, failure_mode_ids=[elsewhere])
    out = m.unlink_position_model(link["id"])
    assert out["unlinked"] == link["id"] and m.position(pump)["models"] == []
    with pytest.raises(Invalid, match="already taken off"):
        m.unlink_position_model(link["id"])
    types = [e["type"] for e in m.s.events(ORG, 100)]
    assert "position.model_linked" in types and "position.model_unlinked" in types
    _same_after_rebuild(m)


def test_replace_swaps_one_model_for_another(m, db):
    pump = m.create_position("Pump A")["id"]
    first = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE)
    second = pm.link_saved(m, db, OWNERS, set(), pump, "model", "sample-model-bearings-lognormal",
                           replace_link_id=first["id"])
    assert [x["id"] for x in m.position_models(pump)] == [second["id"]]
    with pytest.raises(Invalid, match="isn't on this position"):
        pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, replace_link_id="nope")
    _same_after_rebuild(m)


def test_fit_from_the_position_history_then_the_class(m, db):
    pump = m.create_position("Pump A", position_class="Slurry pump")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    bearing = m.add_failure_mode(pump, "Bearing seizes")["id"]
    _history(m, pump, [300, 420, 380, 510], [seal, bearing, seal, seal])
    link = pm.fit_position_model(m, db, pump)
    assert link["role"] == "fitted" and link["source"]["scope"] == "position"
    assert link["source"]["failures"] == 4 and db.models.count_documents({"_id": link["model_id"]}) == 1
    # For one failure mode: the bearing failure censors the row.
    sealed = pm.fit_position_model(m, db, pump, failure_mode_ids=[seal])
    assert sealed["source"]["failures"] == 3 and sealed["failure_modes"][0]["text"] == "Seal leaks"
    # Thin history: the class pools its positions' failures (auto falls back).
    for i in range(3):
        other = m.create_position(f"Pump {i}", position_class="Slurry pump")["id"]
        _history(m, other, [350 + 40 * i, 460])
    thin = m.create_position("Pump new", position_class="Slurry pump")["id"]
    pooled = pm.fit_position_model(m, db, thin)
    assert pooled["source"]["scope"] == "class" and pooled["source"]["class_name"] == "Slurry pump"
    assert pm.source_text(pooled).startswith("Fitted from the class Slurry pump's pooled history")
    assert pm.stale(m, link) is None
    _history(m, pump, [200], start=date(2021, 1, 1))
    assert pm.stale(m, link) == "1 failure since it was fitted: refit it"
    lonely = m.create_position("Odd pump")["id"]
    with pytest.raises(Invalid, match="has 0 failures"):
        pm.fit_position_model(m, db, lonely)
    _same_after_rebuild(m)


def test_from_class_needs_a_class_model(m, db):
    from backend.maintenance import loop

    pump = m.create_position("Pump A", position_class="Duty pump")["id"]
    with pytest.raises(Invalid, match="no fitted model yet"):
        pm.link_from_class(m, db, OWNERS, set(), pump)
    _history(m, pump, [300, 420, 380])
    loop.fit_class_model(m, db, "Duty pump")
    link = pm.link_from_class(m, db, OWNERS, set(), pump)
    assert link["role"] == "class" and link["source"] == {"class_name": "Duty pump"}
    assert pm.source_text(link) == "From the class Duty pump"


def test_a_built_item_inherits_its_designs_models(m, db):
    product = m.create_product("Drone", part_number="DR-1")["id"]
    motor = m.create_position("Motor", parent_id=product)["id"]
    wear = m.add_failure_mode(motor, "Bearing wear")["id"]
    pm.link_saved(m, db, OWNERS, set(), motor, "model", SAMPLE, [wear])
    built = m.build_item(product, "SN-1", dry_run=False)
    copy = next(r["id"] for r in built["positions"] if r["design_position_id"] == motor)
    [inherited] = m.position_models(copy)
    assert inherited["role"] == "design" and inherited["model_id"] == SAMPLE
    assert inherited["source"]["design_position_id"] == motor
    assert [f["text"] for f in inherited["failure_modes"]] == ["Bearing wear"]
    assert inherited["failure_modes"][0]["id"] != wear  # the built position's own mode
    assert pm.source_text(inherited) == "From the product's design"
    _same_after_rebuild(m)


def test_the_reads_describe_each_model_and_what_uses_it(m, db):
    pump = m.create_position("Pump A")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, [seal])
    rec = pm.link_saved(m, db, OWNERS, set(), pump, "recurrent_model", "sample-rec-compressors")
    deg = pm.link_saved(m, db, OWNERS, set(), pump, "degradation_model", "sample-deg-brake-wear")
    m.decide_failure_mode(seal, consequence="operational",
                          decision={"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": SAMPLE}})
    rows = {r["id"]: r for r in pm.describe(m, db, OWNERS, set(), m.all_position_models())}
    weibull = rows[link["id"]]["model"]
    assert weibull["kind"] == "Weibull" and weibull["unit"]
    nums = {n["id"]: n for n in weibull["numbers"]}
    assert nums["char_life"]["lower"] < nums["char_life"]["value"] < nums["char_life"]["upper"]
    assert {"shape", "mean", "b10"} <= set(nums)
    assert weibull["quality"]["word"] == "Good" and weibull["counts"]["failures"] == 30
    assert [d["failure_mode_id"] for d in rows[link["id"]]["used_by"]["decisions"]] == [seal]
    repairable = rows[rec["id"]]["model"]
    assert repairable["kind"].startswith("Repairable") and repairable["trend"] == "Getting worse"
    assert rows[deg["id"]]["model"]["kind"] == "Degradation"
    full = pm.detail(m, db, OWNERS, set(), link["id"])
    assert full["curves"]["x"] and full["curves"]["sf"] and full["params"][0]["name"] == "alpha"
    assert full["origin"].startswith("Age since new") and full["position"]["name"] == "Pump A"
    # A model the reader can't open any more reads as missing, not an error.
    db.models.delete_one({"_id": SAMPLE})
    gone = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert next(r for r in gone if r["id"] == link["id"])["model"] is None


def test_the_interval_inputs_start_from_the_positions_model(m, db):
    from backend.services import rcm_intervals

    pump = m.create_position("Pump A")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    doc = pm.fetcher(db, OWNERS)("model", SAMPLE)
    got = rcm_intervals.starting_inputs(m.rcm_mode(seal), [], lambda *a: None, [("model", doc)])
    assert got["life_model"]["model_id"] == SAMPLE and got["life_model"]["source"] == "position"
    assert got["device"]["model_id"] == SAMPLE and got["onset_rate"]["source"] == "position_model"
    deg = pm.fetcher(db, OWNERS)("degradation_model", "sample-deg-brake-wear")
    got = rcm_intervals.starting_inputs(m.rcm_mode(seal), [], lambda *a: None, [("degradation_model", deg)])
    assert got["pf"]["source"] == "position_model"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router
    from backend.services import samples

    d = mongomock.MongoClient()["position_models_rest"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_link_read_and_unlink_over_rest(client):
    pump = client.post("/api/maintenance/positions", json={"name": "Pump"}).json()["id"]
    r = client.post(f"/api/maintenance/positions/{pump}/models", json={"model_id": SAMPLE})
    assert r.status_code == 200, r.text
    link = r.json()
    listed = client.get("/api/maintenance/position-models", params={"position_ids": pump}).json()["links"]
    assert [x["id"] for x in listed] == [link["id"]] and listed[0]["model"]["kind"] == "Weibull"
    full = client.get(f"/api/maintenance/position-models/{link['id']}").json()
    assert full["curves"]["sf"] and full["source_text"].startswith("Assigned")
    bad = client.post(f"/api/maintenance/positions/{pump}/models", json={"fit": True})
    assert bad.status_code == 422 and "failure" in bad.json()["detail"]
    nope = client.post(f"/api/maintenance/positions/{pump}/models", json={"from_class": True})
    assert nope.status_code == 422 and "no position class" in nope.json()["detail"]
    assert client.delete(f"/api/maintenance/position-models/{link['id']}").status_code == 200
    assert client.get("/api/maintenance/position-models").json()["links"] == []
