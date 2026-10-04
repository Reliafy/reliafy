"""Availability simulation (repairable RBDs) is a paid feature: free users get
the exact figures (#154) and saved simulation results only, entitled users
simulate (and save), public links never compute, and the repairable sample
ships with a precomputed result."""

import copy

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest

from backend.tests.test_public_rbd_links import _rbd_graph

FREE = "user-free"
PRO = "user-pro"
ADMIN = "user-admin"
BUYER = "user-buyer"

USERS = {
    FREE: {"uid": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
    PRO: {"uid": PRO, "email": "pro@example.org", "name": "Pro", "email_verified": True},
    ADMIN: {"uid": ADMIN, "email": "admin@example.org", "name": "Admin", "email_verified": True},
    BUYER: {"uid": BUYER, "email": "buyer@example.org", "name": "Buyer", "email_verified": True},
}

PRO_PAYLOAD = {
    "detail": (
        "Availability simulation is a paid feature. Subscribe to Pro or buy AI "
        "credits — or download the diagram and run it locally with RePyability."
    ),
    "code": "pro_required",
    "upgrade": True,
}

SAMPLE_ID = "sample-rbd-instrument-air-availability"


def _paywall(r) -> bool:
    """The free user's 402: the Pro payload, plus the quick-run offer (#147)."""
    body = r.json()
    return (r.status_code == 402
            and {k: body.get(k) for k in PRO_PAYLOAD} == PRO_PAYLOAD
            and body["quick"]["remaining_today"] >= 0)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import billing, rbd_analysis

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"admin@example.org"})
    monkeypatch.setattr(rbd_analysis, "_AVAIL_SIMS", 20)  # keep the suite quick
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)

    for uid, user in USERS.items():
        test_db.users.update_one(
            {"_id": uid},
            {"$set": {"email": user["email"], "email_lc": user["email"], "email_verified": True, "name": user["name"]}},
            upsert=True,
        )
    billing.set_plan(test_db, PRO, "pro")
    billing.grant_credits(test_db, BUYER, 500, "purchase")

    # Count real simulations (not the exact, simulate=False, analyses).
    calls = {"n": 0}
    real = rbd_analysis.analyze_availability

    def spy(*args, **kwargs):
        if kwargs.get("simulate", True):
            calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(rbd_analysis, "analyze_availability", spy)

    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: USERS[uid]

    tc.act_as = act_as
    tc.db = test_db
    tc.sims = calls
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _save(client, graph, name="Loop"):
    r = client.post("/api/rbds", json={"name": name, "graph": graph})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _analyze(client, graph, rbd_id=None, force=False):
    body = {"graph": graph, "force": force}
    if rbd_id:
        body["rbd_id"] = rbd_id
    return client.post("/api/rbds/analyze", json=body)


def _with_param(graph, value):
    g = copy.deepcopy(graph)
    g["nodes"][2]["data"]["model"]["params"][0]["value"] = value
    return g


# ---- Cache key ---------------------------------------------------------------

def test_cache_key_ignores_layout_but_tracks_analysis_inputs():
    from backend.services.rbds import availability_cache_key as key

    g = _rbd_graph(repairable=True)
    base = key(g)
    assert len(base) == 64 and base == key(copy.deepcopy(g))

    moved = copy.deepcopy(g)
    for n in moved["nodes"]:
        n["position"] = {"x": 123, "y": 456}
        n.update(selected=True, width=90, height=40, dragging=False,
                 positionAbsolute={"x": 1, "y": 2}, className="rbd-node",
                 sourcePosition="right", measured={"width": 1})
    moved["nodes"].reverse()
    moved["edges"].reverse()
    for e in moved["edges"]:
        e["id"] = "x-" + e["id"]
        e["selected"] = True
    moved["viewport"] = {"zoom": 2}
    assert key(moved) == base

    assert key(_with_param(g, 2100)) != base
    rewired = copy.deepcopy(g)
    rewired["edges"] = rewired["edges"][:-1]
    assert key(rewired) != base
    relabel = copy.deepcopy(g)
    relabel["nodes"][2]["data"]["label"] = "PLC"
    assert key(relabel) != base
    assert key(g, 5000) != base and key(g, 5000) == key(g, 5000.0)
    assert key(g, None) == key(g, 0) == base
    unit = copy.deepcopy(g)
    unit["unit"] = "days"
    assert key(unit) != base


# ---- Entitlement helper ------------------------------------------------------

def test_premium_compute_allowed(client, monkeypatch):
    from backend import config
    from backend.services import billing

    db = client.db
    billing.ensure_starter_grant(db, FREE)  # starter credit alone doesn't entitle
    assert billing.premium_compute_allowed(db, USERS[FREE]) is False
    assert billing.premium_compute_allowed(db, USERS[PRO]) is True
    assert billing.premium_compute_allowed(db, USERS[ADMIN]) is True
    assert billing.premium_compute_allowed(db, USERS[BUYER]) is True
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    assert billing.premium_compute_allowed(db, USERS[FREE]) is True


# ---- Free users ----------------------------------------------------------------

def test_free_user_gets_exact_figures_not_the_simulation_and_cache_when_it_matches(client):
    from backend.services import rbds as rbds_service

    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)

    # No paywall: the exact figures, with the simulation offered as Pro.
    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_simulation"] is False and body["cached"] is False
    assert body["simulation_status"]["state"] == "pro_required"
    assert body["can_simulate"] is False and body["can_recompute"] is False
    assert body["exact"]["status"] == "ok" and body["steady_state_availability"] > 0.9
    r = client.get(f"/api/rbds/{rbd_id}/analyze")
    assert r.status_code == 200 and r.json()["simulation_status"]["state"] == "pro_required"
    # Unsaved graphs too; asking for the simulation outright changes nothing.
    assert _analyze(client, graph).json()["has_simulation"] is False
    r = client.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "simulate": True})
    assert r.status_code == 200 and r.json()["simulation_status"]["state"] == "pro_required"
    assert client.sims["n"] == 0
    assert "availability_cache" not in client.db.rbds.find_one({"_id": rbd_id})

    # A saved result for this exact graph (e.g. from a Pro teammate/backfill).
    key = rbds_service.availability_cache_key(graph)
    rbds_service.store_availability(
        client.db, rbd_id, key, {"kind": "repairable", "steady_state_availability": 0.99}, PRO
    )
    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is True and body["computed_at"] and body["can_recompute"] is False
    assert body["has_simulation"] is True and body["simulation_status"]["state"] == "saved"
    assert body["steady_state_availability"] == 0.99
    assert body["exact"]["status"] == "ok"  # the exact figures ride along
    assert client.get(f"/api/rbds/{rbd_id}/analyze").json()["cached"] is True
    # force is ignored for a free user: still the saved result, no simulation.
    assert _analyze(client, graph, rbd_id, force=True).json()["cached"] is True

    # Moving a block doesn't matter; changing a parameter does.
    moved = copy.deepcopy(graph)
    moved["nodes"][3]["position"] = {"x": 999, "y": 999}
    assert _analyze(client, moved, rbd_id).json()["cached"] is True
    changed = _with_param(graph, 2500)
    r = _analyze(client, changed, rbd_id)
    assert r.status_code == 200 and r.json()["has_simulation"] is False
    _save_over = client.post("/api/rbds", json={"name": "Loop", "graph": changed, "id": rbd_id})
    assert _save_over.status_code == 200
    assert client.get(f"/api/rbds/{rbd_id}/analyze").json()["has_simulation"] is False
    assert client.sims["n"] == 0


def test_free_user_meets_the_paywall_on_a_simulation_only_diagram(client):
    """One repair crew for wear-out lives has no exact figures at all
    (long-run or over time): the paywall, as before #154. (Proof tests that
    take time were the example until RePyability 0.12 made them numerical.)"""
    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)
    graph["repair_crews"] = {"crews": 1}
    r = _analyze(client, graph)
    assert _paywall(r)  # with the free quick run offered (#147)
    assert client.sims["n"] == 0


def test_non_repairable_analysis_stays_free(client):
    client.act_as(FREE)
    graph = _rbd_graph(repairable=False)
    rbd_id = _save(client, graph)
    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200 and "cached" not in r.json()
    assert r.json().get("kind") != "repairable" and r.json().get("time")
    assert client.get(f"/api/rbds/{rbd_id}/analyze").status_code == 200
    assert "availability_cache" not in client.db.rbds.find_one({"_id": rbd_id})


# ---- Entitled users --------------------------------------------------------------

@pytest.mark.parametrize("who", [PRO, ADMIN, BUYER, "billing-off"])
def test_entitled_user_computes_caches_and_forces(client, monkeypatch, who):
    from backend import config

    uid = who
    if who == "billing-off":
        monkeypatch.setattr(config, "BILLING_ENABLED", False)
        uid = FREE
    client.act_as(uid)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)

    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["cached"] is False and first["kind"] == "repairable"
    assert client.sims["n"] == 1
    entry = client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]
    assert entry["computed_by"] == uid and entry["computed_at"] == first["computed_at"]
    assert entry["result"]["steady_state_availability"] == first["steady_state_availability"]
    assert "cached" not in entry["result"]

    second = _analyze(client, graph, rbd_id).json()
    assert second["cached"] is True and second["can_recompute"] is True and client.sims["n"] == 1
    assert client.get(f"/api/rbds/{rbd_id}/analyze").json()["cached"] is True

    forced = _analyze(client, graph, rbd_id, force=True).json()
    assert forced["cached"] is False and client.sims["n"] == 2
    forced_get = client.get(f"/api/rbds/{rbd_id}/analyze?force=true").json()
    assert forced_get["cached"] is False and client.sims["n"] == 3

    # Unsaved graph: computes, nothing stored anywhere.
    other = _with_param(graph, 3000)
    r = _analyze(client, other)
    assert r.status_code == 200 and r.json()["cached"] is False
    assert r.json()["computed_at"] is None
    assert client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]["key"] == entry["key"]


def test_unsaved_what_if_does_not_clobber_the_saved_result(client):
    client.act_as(PRO)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)
    _analyze(client, graph, rbd_id)
    key = client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]["key"]

    # Editing without saving: computed, but the saved diagram's result stays.
    what_if = _with_param(graph, 1500)
    assert _analyze(client, what_if, rbd_id).json()["cached"] is False
    assert client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]["key"] == key

    # Once the saved result is stale (diagram re-saved), the next run replaces it.
    client.post("/api/rbds", json={"name": "Loop", "graph": what_if, "id": rbd_id})
    assert _analyze(client, what_if, rbd_id).json()["cached"] is False
    assert _analyze(client, what_if, rbd_id).json()["cached"] is True


def test_read_only_viewer_computes_but_does_not_write(client):
    client.act_as(FREE)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)
    r = client.post("/api/shares", json={
        "collection": "rbds", "artifact_id": rbd_id, "email": USERS[PRO]["email"],
    })
    assert r.status_code == 200, r.text

    client.act_as(PRO)
    assert client.get(f"/api/rbds/{rbd_id}").json()["read_only"] is True
    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200 and r.json()["cached"] is False
    assert client.get(f"/api/rbds/{rbd_id}/analyze").json()["cached"] is False
    assert client.sims["n"] == 2
    assert "availability_cache" not in client.db.rbds.find_one({"_id": rbd_id})


# ---- Public links ---------------------------------------------------------------

def test_public_link_never_simulates(client, monkeypatch):
    from backend.services import rbd_analysis
    from backend.services import rbds as rbds_service

    def boom(*a, **k):
        raise AssertionError("public links must not run the availability simulation")

    monkeypatch.setattr(rbd_analysis, "analyze_availability", boom)

    client.act_as(PRO)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)
    token = client.post(
        "/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id}
    ).json()["token"]

    client.act_as(None)
    a = client.get(f"/api/public/{token}").json()["artifact"]
    assert a["analysis"] is None and a["analysis_error"] is None
    assert a["analysis_note"] == "The owner hasn't run the availability simulation for this diagram yet."

    key = rbds_service.availability_cache_key(graph)
    rbds_service.store_availability(
        client.db, rbd_id, key, {"kind": "repairable", "steady_state_availability": 0.97}, PRO
    )
    a = client.get(f"/api/public/{token}").json()["artifact"]
    assert a["analysis"]["steady_state_availability"] == 0.97
    assert a["analysis"]["cached"] is True and a["analysis_note"] is None
    assert "computed_by" not in str(a)

    # A stale saved result isn't served.
    client.db.rbds.update_one({"_id": rbd_id}, {"$set": {"graph": _with_param(graph, 4000)}})
    a = client.get(f"/api/public/{token}").json()["artifact"]
    assert a["analysis"] is None and a["analysis_note"]

    # Billing off (self-host) still never simulates on a public link.
    from backend import config

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    assert client.get(f"/api/public/{token}").json()["artifact"]["analysis"] is None


def test_refitting_a_referenced_model_makes_the_saved_result_stale(client, monkeypatch):
    """#92: a block that references a saved fitted model by id (here a
    proportional-hazards one) carries only the id, so the model's fit is part
    of the availability and exact keys (with the window and state as before):
    a refit invalidates the saved results, a rename doesn't."""
    import io

    import numpy as np
    import pandas as pd

    from backend.routers import rbds as rbds_routes
    from backend.services import datasets as ds_service
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service

    # The exact figures aren't computed here (the saved ones are what free
    # viewers and public links rely on): stub them for the app's endpoint.
    monkeypatch.setattr(rbds_routes, "exact_payload", lambda *a, **k: {
        "steady_state_availability": 0.9, "exact": {"status": "ok"}})

    db = client.db
    buf = io.StringIO()
    rng = np.random.default_rng(3)
    age = rng.normal(50, 10, 80)
    pd.DataFrame({"t": np.round(rng.weibull(1.5, 80) * 900 * np.exp(-0.02 * (age - 50)), 2),
                  "c": (rng.random(80) < 0.2).astype(int),
                  "age": np.round(age, 1)}).to_csv(buf, index=False)
    dataset = ds_service.create_dataset(db, "pumps.csv", buf.getvalue().encode(), FREE)
    model = models_service.save_model(db, "Pump PH", dataset, "weibull_ph", {"x": "t"}, ["age"], None,
                                      owner_id=FREE)
    assert model.kind == "regression"

    graph = _rbd_graph(repairable=True)
    graph["nodes"][3]["data"]["model"] = {
        "source": "saved", "kind": "regression", "modelId": model.id, "name": "Pump PH",
        "distribution": "Weibull PH", "distribution_id": "weibull_ph",
        "covariates": [{"name": "age", "type": "number", "default": 50.0}]}
    # Parametric blocks carry their parameters, so only the resolved model
    # counts, and a diagram without one keeps its key (saved results and the
    # samples' precomputed ones still serve).
    models = rbds_service.model_fingerprints(db, graph, FREE)
    assert list(models) == [model.id] and models[model.id]
    plain = _rbd_graph(repairable=True)
    assert rbds_service.model_fingerprints(db, plain, FREE) == {}
    assert rbds_service.availability_cache_key(plain, models={}) == rbds_service.availability_cache_key(plain)
    assert rbds_service.exact_cache_key(plain, None, None, {}) == rbds_service.exact_cache_key(plain, None, None)
    # The window and the state still key both.
    assert rbds_service.availability_cache_key(graph, 500, models) != rbds_service.availability_cache_key(
        graph, None, models)
    assert rbds_service.exact_cache_key(graph, None, {"n": {"age": 1}}, models) != rbds_service.exact_cache_key(
        graph, None, None, models)

    client.act_as(FREE)
    rbd_id = _save(client, graph)
    rbds_service.store_availability(
        db, rbd_id, rbds_service.availability_cache_key(graph, models=models),
        {"kind": "repairable", "steady_state_availability": 0.97}, PRO,
    )
    rbds_service.store_exact(db, rbd_id, rbds_service.exact_cache_key(graph, None, None, models),
                             {"steady_state_availability": 0.97, "exact": {"status": "ok"}})
    doc = db.rbds.find_one({"_id": rbd_id})
    assert rbds_service.should_store_availability(
        doc, rbds_service.availability_cache_key(graph, models=models), db, FREE)
    token = client.post(
        "/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id}
    ).json()["token"]

    def served():
        state = client.get(f"/api/rbds/{rbd_id}/analyze").json()["simulation_status"]["state"]
        client.act_as(None)
        public = client.get(f"/api/public/{token}").json()["artifact"]["analysis"]
        client.act_as(FREE)
        return state == "saved", public is not None and public.get("has_simulation") is True, public

    assert served()[:2] == (True, True)
    assert served()[2]["exact"] == {"status": "ok"}
    models_service.rename_model(db, model.id, "Pump bank PH", FREE)
    assert served()[:2] == (True, True)

    # An edit that doesn't touch the model leaves the result current; one
    # that changes a block puts it out of date (MCP edit_rbd's note).
    moved = copy.deepcopy(graph)
    moved["nodes"][3]["position"] = {"x": 999, "y": 9}
    assert not rbds_service.availability_outdated_by(doc, graph, moved, db, FREE)
    assert rbds_service.availability_outdated_by(doc, graph, _with_param(graph, 2100), db, FREE)

    # Refit (censoring now counted): the graph is unchanged, the results aren't valid.
    models_service.update_fit(db, model.id, FREE, "weibull_ph", {"x": "t", "c": "c"},
                              ["age"], None, None, None)
    refit = rbds_service.model_fingerprints(db, graph, FREE)
    assert refit != models
    assert served()[:2] == (False, False)
    # Neither the saved simulation nor the saved exact figures are served publicly.
    assert served()[2] is None
    doc = db.rbds.find_one({"_id": rbd_id})
    assert not rbds_service.cached_availability(doc, rbds_service.availability_cache_key(graph, models=refit))
    assert not rbds_service.cached_exact(doc, rbds_service.exact_cache_key(graph, None, None, refit))
    # A fresh run for the diagram as saved replaces the stale one.
    assert rbds_service.should_store_availability(
        doc, rbds_service.availability_cache_key(graph, models=refit), db, FREE)


def test_public_link_non_repairable_unchanged(client):
    client.act_as(FREE)
    rbd_id = _save(client, _rbd_graph(repairable=False))
    token = client.post(
        "/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id}
    ).json()["token"]
    client.act_as(None)
    a = client.get(f"/api/public/{token}").json()["artifact"]
    assert a["analysis"].get("kind") != "repairable" and a["analysis"].get("time") and a["analysis_note"] is None


# ---- Samples ------------------------------------------------------------------------

def test_sample_is_seeded_with_a_result_and_served_to_free_users(client):
    from backend.services import samples

    samples.seed_samples(client.db)
    assert client.sims["n"] == 1
    entry = client.db.rbds.find_one({"_id": SAMPLE_ID})["availability_cache"]
    assert entry["result"]["n_simulations"] == samples.SAMPLE_AVAIL_SIMS
    samples.seed_samples(client.db)  # idempotent: key matches, no recompute
    assert client.sims["n"] == 1

    client.act_as(FREE)
    r = client.get(f"/api/rbds/{SAMPLE_ID}/analyze")
    assert r.status_code == 200 and r.json()["cached"] is True
    graph = client.get(f"/api/rbds/{SAMPLE_ID}").json()["graph"]
    r = _analyze(client, graph, SAMPLE_ID)
    assert r.status_code == 200 and r.json()["cached"] is True
    assert r.json()["steady_state_availability"] > 0.9

    # Entitled re-run of a sample computes but never writes the shared doc.
    client.act_as(PRO)
    assert _analyze(client, graph, SAMPLE_ID, force=True).json()["cached"] is False
    assert client.db.rbds.find_one({"_id": SAMPLE_ID})["availability_cache"] == entry

    # A changed sample graph is re-seeded.
    client.db.rbds.update_one({"_id": SAMPLE_ID}, {"$set": {"graph.unit": "days"}})
    samples.seed_samples(client.db)
    assert client.sims["n"] == 3


# ---- Backfill script ------------------------------------------------------------------

def test_backfill_script_dry_run_and_apply(client, capsys):
    from backend.config import SAMPLE_OWNER
    from backend.scripts import backfill_availability_cache as backfill
    from backend.services import rbds as rbds_service

    db = client.db
    graph = _rbd_graph(repairable=True)

    def put(rid, owner, g):
        db.rbds.insert_one({"_id": rid, "name": rid, "owner_id": owner, "graph": g})

    put("r-pro", PRO, graph)
    put("r-admin", ADMIN, graph)
    put("r-buyer", BUYER, graph)
    put("r-free", FREE, graph)                         # owner not entitled
    put("r-plain", PRO, _rbd_graph(repairable=False))  # not repairable
    put("r-sample", SAMPLE_OWNER, graph)               # seeding's job
    put("r-done", PRO, graph)                          # already has a matching result
    rbds_service.store_availability(
        db, "r-done", rbds_service.availability_cache_key(graph), {"kind": "repairable"}, PRO
    )
    put("r-stale", PRO, graph)                         # saved result for an older graph
    rbds_service.store_availability(
        db, "r-stale", rbds_service.availability_cache_key(_with_param(graph, 10)),
        {"kind": "repairable"}, PRO,
    )
    db.teams.insert_one({"_id": "t1", "owner_uid": PRO, "members": [{"uid": PRO}]})
    put("r-team", "team:t1", graph)                    # judged by the team owner

    expected = {"r-pro", "r-admin", "r-buyer", "r-stale", "r-team"}
    assert {r["id"] for r in backfill.candidates(db)} == expected

    # Dry run (the default) writes nothing.
    assert backfill.main([]) == 0
    out = capsys.readouterr().out
    assert "needing a saved availability result: 5" in out and "Dry run" in out
    assert client.sims["n"] == 0
    assert "availability_cache" not in db.rbds.find_one({"_id": "r-pro"})

    assert backfill.main(["--apply", "--limit", "2"]) == 0
    assert client.sims["n"] == 2
    assert backfill.main(["--apply"]) == 0
    assert client.sims["n"] == 5
    for rid in expected:
        entry = db.rbds.find_one({"_id": rid})["availability_cache"]
        assert entry["key"] == rbds_service.availability_cache_key(graph)
        assert entry["computed_by"] == "backfill"
        assert entry["result"]["kind"] == "repairable"
    assert backfill.candidates(db) == []
    assert "availability_cache" not in db.rbds.find_one({"_id": "r-free"})
