"""A user's own data libraries (backend/library/user.py): made, renamed and
deleted like any saved kind; a saved life model added as a record (a snapshot
with its bounds, the model linked) and removed again; the record searched,
read, used as a model and as a prior beside the published sources; one
library counts as one saved item on Free; the same over MCP and REST (the
parity test in test_api_tools.py covers the routing)."""

from __future__ import annotations

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.library import schema, service
from backend.library import user as user_lib
from backend.tests.test_mcp import _call, _err, _ok
from backend.tests.test_mcp_plans import FREE, PRO, UPGRADE, env  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")

WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
CSV = "time,c\n" + "\n".join(f"{t},{k}" for t, k in [(120, 0), (340, 0), (510, 1), (700, 0), (980, 0), (1200, 1),
                                                    (1500, 0), (1700, 0), (800, 0), (650, 0)])


@pytest.fixture()
def web(monkeypatch):
    """The web app signed in as a Free user (billing on), switchable to Pro."""
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["library_user"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)
    test_db.users.insert_many([
        {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
        {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro", "email_verified": True},
    ])
    who = {"uid": PRO}
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": who["uid"], "email": f"{who['uid']}@example.org", "name": "U", "email_verified": True}
    tc = TestClient(app)
    tc.who = who
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _params_model(web, name="Pump W", distribution="weibull", params=WEIBULL, unit="hours"):
    r = web.post("/api/models/from-params", json={"name": name, "distribution": distribution, "params": params, "unit": unit})
    assert r.status_code == 200, r.text
    return r.json()


def _fitted_model(web, name="Fitted pump"):
    ds = web.post("/api/datasets", files={"file": ("d.csv", CSV.encode(), "text/csv")})
    assert ds.status_code == 200, ds.text
    r = web.post("/api/models", data={"name": name, "dataset_id": ds.json()["id"], "distribution": "weibull", "x": "time",
                                      "c": "c", "unit": "hours"})
    assert r.status_code == 200, r.text
    return r.json(), ds.json()["id"]


# ---- the schema ------------------------------------------------------------------------------

def test_a_life_record_is_usable_as_a_model_and_a_prior_and_its_summary_checks():
    rec = {"id": "lib:1", "source": "lib", "version": 1, "name": "Pump", "label": "Pump: wear", "source_text": "x",
           "equipment_type": "pump", "kind": "life", "basis": "fitted", "failure_mode": {"code": "wear", "name": "wear"},
           "citation": {k: "x" for k in ("title", "publisher", "table", "page", "year", "url", "retrieved")},
           "licence": {"id": "cc-by-4.0", "attribution": "x"}, "units": {"value": "hours"},
           "distribution": {"family": "weibull", "params": WEIBULL},
           "summary": schema.life_summary("weibull", {"alpha": 1200.0, "beta": 2.5})}
    assert schema.problems(rec) == []
    assert service.usable_as(rec, "model") and service.usable_as(rec, "prior")
    assert service.left_out_by([rec], "model") == {}
    # A stated mean that isn't the parameters' is caught; an exponential's mean life is 1 / the rate.
    bad = {**rec, "summary": {**rec["summary"], "mean": 10.0}}
    assert any("mean 10.0 disagrees" in p for p in schema.problems(bad))
    assert schema.life_summary("exponential", {"failure_rate": 0.001})["mean"] == pytest.approx(1000.0)
    assert schema.life_summary("normal", {"mu": 100.0, "sigma": 10.0})["b10"] == pytest.approx(87.18, abs=0.01)
    for family in ("weibull", "exponential", "lognormal", "normal", "gamma"):
        assert family in schema.FAMILIES_BY_KIND["life"]


# ---- the web app -----------------------------------------------------------------------------

def test_make_a_library_add_a_model_read_it_everywhere_and_remove_it(web):
    lib = web.post("/api/library/mine", json={"name": "Site pumps", "description": "Our fleet", "notes": "Internal use."})
    assert lib.status_code == 200, lib.text
    lid = lib.json()["id"]
    assert web.get("/api/library/mine").json()["libraries"][0] == {**lib.json(), "read_only": False} | {"records": 0}

    # The sources list has it first, marked as the user's, and the answer isn't cached.
    r = web.get("/api/library/sources")
    assert r.headers["cache-control"] == "private, no-store"
    first = r.json()["sources"][0]
    assert first["id"] == lid and first["mine"] is True and first["records"] == 0 and first["basis"] == "fitted"

    # A saved model is in no library until it's added; adding snapshots it.
    model, _ = _fitted_model(web)
    assert web.get(f"/api/library/search?source={lid}").json()["total"] == 0
    r = web.post(f"/api/library/mine/{lid}/records", json={"model_id": model["id"], "failure_mode": "Bearing wear",
                                                            "equipment_type": "pump", "notes": "From the 2025 fleet data."})
    assert r.status_code == 200, r.text
    rec = r.json()["record"]
    assert rec["kind"] == "life" and rec["basis"] == "fitted" and rec["label"] == "Fitted pump: Bearing wear"
    assert rec["distribution"]["family"] == "weibull" and rec["distribution"]["level"] == 0.90
    assert all(len(p["ci"]) == 2 for p in rec["distribution"]["params"])
    assert rec["units"]["value"] == "Hours" and rec["model"]["id"] == model["id"]
    assert rec["evidence"] == {"n": 10, "failures": 8, "suspensions": 2, "method": "mle"}
    assert set(rec["summary"]) == {"mean", "median", "b10", "p05", "p95"}
    assert rec["id"].startswith(f"{lid}:")

    # Found by search (the kind filter, the use filter, by words), first on a tie; read in full with its model.
    hits = web.get("/api/library/search?q=bearing&use=prior").json()
    assert hits["total"] == 1 and hits["results"][0]["source"] == "Site pumps" and hits["results"][0]["mine"] is True
    assert hits["results"][0]["b10"] == pytest.approx(rec["summary"]["b10"])
    assert web.get("/api/library/search?kind=life").json()["total"] == 1
    assert web.get(f"/api/library/search?source={lid}").json()["total"] == 1
    everything = web.get("/api/library/search?page_size=5").json()
    assert everything["results"][0]["id"] == rec["id"]  # the user's record comes first on a tie
    detail = web.get(f"/api/library/records/{rec['id']}").json()
    assert detail["library"]["name"] == "Site pumps" and detail["library"]["notes"] == "Internal use."
    assert detail["model_link"] == {"id": model["id"], "name": "Fitted pump", "exists": True}
    bm = detail["block_model"]
    assert bm["model"]["distribution_id"] == "weibull" and bm["bounds_level"] == 0.90 and set(bm["bounds"]) == {"alpha", "beta"}
    assert "snapshot" in bm["badge"]

    # A later refit doesn't change the record (it's a snapshot).
    web.db.models.update_one({"_id": model["id"]}, {"$set": {"results.params.0.value": 1.0}})
    assert web.get(f"/api/library/records/{rec['id']}").json()["record"]["distribution"]["params"][0]["value"] != 1.0

    # Use as a model: the snapshot's family, parameters and bounds, the record named on the model.
    r = web.post("/api/models/from-library", json={"record_id": rec["id"]})
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["results"]["params"][0]["value"] == pytest.approx(rec["distribution"]["params"][0]["value"])
    assert made["results"]["params"][0]["ci"] == rec["distribution"]["params"][0]["ci"]
    assert "library record's" in made["results"]["ci_note"] and made["results"]["library"]["library_id"] == lid

    # The model deleted: the record stays, its link says so.
    assert web.delete(f"/api/models/{model['id']}").status_code == 200
    detail = web.get(f"/api/library/records/{rec['id']}").json()
    assert detail["model_link"]["exists"] is False and detail["record"]["model"]["name"] == "Fitted pump"

    # Rename and edit; remove the record; delete the library.
    r = web.patch(f"/api/library/mine/{lid}", json={"name": "Pumps", "notes": ""})
    assert r.status_code == 200 and r.json()["name"] == "Pumps" and r.json()["notes"] == ""
    assert web.patch(f"/api/library/mine/{lid}", json={}).status_code == 422
    r = web.delete(f"/api/library/mine/{lid}/records/{rec['id']}")
    assert r.status_code == 200 and r.json()["removed"] is True
    assert web.get(f"/api/library/search?source={lid}").json()["total"] == 0
    assert web.delete(f"/api/library/mine/{lid}").status_code == 200
    assert web.get("/api/library/mine").json()["libraries"] == []
    assert web.get(f"/api/library/records/{rec['id']}").status_code == 404


def test_only_parametric_life_models_go_in_and_only_your_own(web):
    lid = web.post("/api/library/mine", json={"name": "Mine"}).json()["id"]
    # A sample model isn't yours to snapshot? It is readable, so it can be added (a snapshot takes nothing from it);
    # a model that isn't a plain parametric life model is refused in words.
    r = web.post("/api/models/from-params", json={"name": "Offset W", "distribution": "weibull", "params": WEIBULL,
                                                   "unit": "hours", "extras": {"offset": True, "gamma": 10}})
    if r.status_code == 200 and len(r.json()["results"]["params"]) > 2:
        out = web.post(f"/api/library/mine/{lid}/records", json={"model_id": r.json()["id"]})
        assert out.status_code == 422 and "plain family" in out.json()["detail"]
    assert web.post(f"/api/library/mine/{lid}/records", json={"model_id": "nope"}).status_code == 404
    # Another user's library is not yours: not found, not changed.
    web.who["uid"] = FREE
    assert web.get(f"/api/library/search?source={lid}").status_code == 422  # unknown source for this user
    assert web.patch(f"/api/library/mine/{lid}", json={"name": "Taken"}).status_code == 404
    assert web.delete(f"/api/library/mine/{lid}").status_code == 404
    web.who["uid"] = PRO
    assert web.get("/api/library/mine").json()["libraries"][0]["name"] == "Mine"


def test_a_life_record_as_the_prior_of_a_dataset_fit(web):
    lid = web.post("/api/library/mine", json={"name": "Priors"}).json()["id"]
    model, dsid = _fitted_model(web)
    rec = web.post(f"/api/library/mine/{lid}/records", json={"model_id": model["id"]}).json()["record"]
    body = {"dataset_id": dsid, "time_column": "time", "censor_column": "c", "unit": "hours", "distribution": "exponential",
            "prior": {"kind": "library", "record_id": rec["id"]}}
    r = web.post("/api/models/fit-with-prior", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    # The prior is in the record's own family, whatever distribution was asked for, with its bounds.
    assert out.get("refused") is None and out["distribution"] == "weibull" and out["can_save"]
    assert "90% between the record's bounds" in out["prior_note"]
    # A parameters-only model has no bounds: the default spread, said in the note.
    plain = _params_model(web, "Plain")
    rec2 = web.post(f"/api/library/mine/{lid}/records", json={"model_id": plain["id"]}).json()["record"]
    out2 = web.post("/api/models/fit-with-prior", json={**body, "prior": {"kind": "library", "record_id": rec2["id"]}}).json()
    assert "no bounds" in out2["prior_note"] and "30%" in out2["prior_note"]
    # Data in days, the record in hours: converted; a unit of use that isn't the record's is refused in words.
    assert web.post("/api/models/fit-with-prior", json={**body, "unit": "days"}).json().get("refused") is None
    cycles = _params_model(web, "Cycles", unit="cycles")
    rec3 = web.post(f"/api/library/mine/{lid}/records", json={"model_id": cycles["id"]}).json()["record"]
    out3 = web.post("/api/models/fit-with-prior", json={**body, "prior": {"kind": "library", "record_id": rec3["id"]}}).json()
    assert "give the data in the record's unit" in out3["refused"]
    # Saved: a model whose bounds are credible intervals.
    r = web.post("/api/models/fit-with-prior", json={**body, "save": True, "name": "Updated pump"})
    assert r.status_code == 200 and r.json()["results"]["method"] == "bayesian_update"


def test_a_life_record_as_a_prior_on_a_position(web):
    """The Fit dialog's "A library record" path on a position's history takes a life record too."""
    from backend.maintenance import library_models
    from backend.services import bayes_life as bl

    lid = web.post("/api/library/mine", json={"name": "Priors"}).json()["id"]
    model, _ = _fitted_model(web)
    rec = web.post(f"/api/library/mine/{lid}/records", json={"model_id": model["id"]}).json()["record"]
    base = library_models.prior_base({"kind": "library", "record_id": rec["id"]}, "exponential", web.db, [PRO])
    assert base["distribution"] == "weibull" and base["unit"] == "Hours" and set(base["priors"]) == {"alpha", "beta"}
    rows = bl.given_rows([100.0, 400.0, 900.0], [0, 0, 1])
    fitted, result, _ = bl.update(base, "guide", rows, None, base["priors"])
    assert fitted is not None and result["distribution"] == "weibull"
    # A normal or gamma record can't be a prior here (the update takes Weibull, exponential, lognormal).
    normal = _params_model(web, "N", "normal", [{"name": "mu", "value": 500.0}, {"name": "sigma", "value": 50.0}])
    rec2 = web.post(f"/api/library/mine/{lid}/records", json={"model_id": normal["id"]}).json()["record"]
    with pytest.raises(ValueError, match="normal model"):
        library_models.prior_base({"kind": "library", "record_id": rec2["id"]}, "weibull", web.db, [PRO])


def test_one_library_is_one_saved_item_on_free(web):
    from backend import config
    from backend.services import billing

    assert billing.plan_caps("free")["libraries"] == config.FREE_MAX_LIBRARIES == 1
    web.who["uid"] = FREE
    first = web.post("/api/library/mine", json={"name": "One"})
    assert first.status_code == 200
    over = web.post("/api/library/mine", json={"name": "Two"})
    assert over.status_code == 402 and over.json()["code"] == "cap"
    assert over.json()["detail"] == ("You've reached the free-plan limit of 1 library. "
                                     "Upgrade to Pro for unlimited libraries.")
    # Records inside it don't count: several models go in, and editing is still allowed.
    for i in range(3):
        m = _params_model(web, f"M{i}")
        assert web.post(f"/api/library/mine/{first.json()['id']}/records", json={"model_id": m["id"]}).status_code == 200
    assert web.patch(f"/api/library/mine/{first.json()['id']}", json={"name": "Renamed"}).status_code == 200
    usage = web.get("/api/billing").json()
    assert usage["usage"]["libraries"] == 1 and usage["caps"]["libraries"] == 1
    web.who["uid"] = PRO
    for i in range(3):
        assert web.post("/api/library/mine", json={"name": f"P{i}"}).status_code == 200


def test_signed_out_reads_stay_public_and_cached(monkeypatch):
    from backend import config, db
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["library_public"])
    monkeypatch.setattr(db, "_simulated", True)
    tc = TestClient(app)
    r = tc.get("/api/library/sources")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=3600"
    assert all(not s.get("mine") for s in r.json()["sources"])
    assert tc.get("/api/library/mine").status_code == 401
    assert tc.post("/api/library/mine", json={"name": "x"}).status_code == 401


# ---- MCP and REST ----------------------------------------------------------------------------

def test_the_library_actions_over_mcp(env):  # noqa: F811
    pro = env.oauth[PRO]
    lib = _ok(_call(pro, "change", {"action": "library_create", "args": {"name": "Agent's library", "description": "Made over MCP"}}))
    assert lib["saved"] and lib["url"].endswith(f"/libraries/{lib['library_id']}") and lib["visibility"] == "private"
    lid = lib["library_id"]
    listed = _ok(_call(pro, "list", {"kind": "libraries", "args": {"scope": "yours"}}))
    assert [x["name"] for x in listed["libraries"]] == ["Agent's library"]
    everything = _ok(_call(pro, "list", {"kind": "libraries"}))["libraries"]
    assert {x["id"] for x in everything if x["builtin"]} == {"mil-hdbk-217f-n2", "nswc-11", "nrc-inl-2020"}
    model = _ok(_call(pro, "change", {"action": "model_save", "args": {"name": "Saved W", "distribution": "weibull",
                                                                         "params": WEIBULL, "unit": "hours"}}))
    added = _ok(_call(pro, "change", {"action": "library_add", "args": {
        "library_id": lid, "model_id": model["model_id"], "failure_mode": "Seal leak", "equipment_type": "pump"}}))
    assert added["saved"] and added["entry"]["type"] == "model"
    assert added["entry"]["model"]["basis_text"] == "From parameters" and added["entry"]["model"]["fitted_on"] is None
    got = _ok(_call(pro, "get", {"kind": "library", "args": {"id": lid}}))
    assert got["entries"][0]["id"] == added["entry_id"] and got["name"] == "Agent's library"
    one = _ok(_call(pro, "get", {"kind": "library", "args": {"id": lid, "entry_id": added["entry_id"]}}))
    assert [p["name"] for p in one["model"]["params"]] == ["alpha", "beta"]
    # A life model entry is found by the library search and read in full like a published record.
    found = _ok(_call(pro, "list", {"kind": "library", "args": {"query": "seal leak"}}))
    assert found["results"][0]["id"] == added["entry_id"]
    full = _ok(_call(pro, "get", {"kind": "library_record", "args": {"id": added["entry_id"]}}))
    assert full["library"]["id"] == lid and full["model_link"]["exists"] is True
    renamed = _ok(_call(pro, "change", {"action": "library_update", "args": {"library_id": lid, "name": "Pumps"}}))
    assert renamed["name"] == "Pumps"
    # Public needs a licence, a citation and the user's word; then anyone can read it.
    msg = _err(_call(pro, "change", {"action": "library_update", "args": {"library_id": lid, "visibility": "public"}}))
    assert "a licence" in msg and "source or citation" in msg and "right to publish" in msg
    pub = _ok(_call(pro, "change", {"action": "library_update", "args": {
        "library_id": lid, "visibility": "public", "licence": "own-cc-by-4.0", "citation": "Our pump records, 2025",
        "rights_confirmed": True}}))
    assert pub["visibility"] == "public" and pub["licence"]["id"] == "own-cc-by-4.0"
    free = env.oauth[FREE]
    seen = _ok(_call(free, "get", {"kind": "library", "args": {"id": lid}}))
    assert seen["can_edit"] is False and seen["relation"] == "public"
    assert "Only the library's owner" in _err(_call(free, "change", {"action": "library_remove", "args": {
        "library_id": lid, "entry_id": added["entry_id"]}}))
    copied = _ok(_call(free, "change", {"action": "library_use", "args": {"library_id": lid, "entry_id": added["entry_id"]}}))
    assert copied["model"]["name"] == "Saved W" and copied["dataset"] is None
    mine = env.db.models.find_one({"_id": copied["model"]["id"]})
    assert mine["owner_id"] == FREE and mine["from_library"]["entry_id"] == added["entry_id"]
    # Errors in words; another user can't see a private library.
    msg = _err(_call(pro, "change", {"action": "library_add", "args": {"library_id": lid, "model_id": "nope"}}))
    assert "Model not found" in msg
    _ok(_call(pro, "change", {"action": "library_update", "args": {"library_id": lid, "visibility": "private"}}))
    assert "Library not found" in _err(_call(free, "get", {"kind": "library", "args": {"id": lid}}))
    removed = _ok(_call(pro, "change", {"action": "library_remove", "args": {"library_id": lid, "entry_id": added["entry_id"]}}))
    assert removed["removed"]
    gone = _ok(_call(pro, "change", {"action": "library_delete", "args": {"library_id": lid}}))
    assert gone["deleted"] and _ok(_call(pro, "list", {"kind": "libraries", "args": {"scope": "yours"}}))["libraries"] == []


def test_the_free_cap_over_mcp_and_rest(env, monkeypatch):  # noqa: F811
    from backend.services import billing, tokens

    free = env.oauth[FREE]
    assert _ok(_call(free, "change", {"action": "library_create", "args": {"name": "One"}}))["saved"]
    msg = _err(_call(free, "change", {"action": "library_create", "args": {"name": "Two"}}))
    assert "limit of 1 saved librar" in msg and UPGRADE in msg
    assert _ok(_call(free, "get", {"kind": "account"}))["storage"]["libraries"] == {"used": 1, "limit": 1}
    # REST is the MCP action.
    monkeypatch.setattr(billing, "api_access_allowed", lambda db, user: True)
    token = tokens.create_token(env.db, FREE, "api")["token"]
    from backend.main import app

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/change/library_create", json={"name": "Three"}, headers=headers)
    assert r.status_code >= 400 and "limit of 1 saved librar" in r.text
    r = client.post("/api/v1/list/libraries", json={}, headers=headers)
    assert r.status_code == 200 and [x["name"] for x in r.json()["libraries"] if not x["builtin"]] == ["One"]


def test_dataset_upload_into_a_library_over_mcp(env):  # noqa: F811
    pro = env.oauth[PRO]
    lid = _ok(_call(pro, "change", {"action": "library_create", "args": {"name": "Sites"}}))["library_id"]
    csv = "site,time,c\nA,10,0\nA,20,1\nB,30,0\nB,40,0"
    out = _ok(_call(pro, "change", {"action": "dataset_upload", "args": {
        "name": "Sites", "csv": csv, "dataset_col": "site", "x_col": "time", "c_col": "c", "library_id": lid}}))
    assert len(out["datasets"]) == 2 and len(out["library"]["added"]) == 2
    assert out["library"]["url"].endswith(f"/libraries/{lid}")
    got = _ok(_call(pro, "get", {"kind": "library", "args": {"id": lid}}))
    assert [e["type"] for e in got["entries"]] == ["data", "data"]
    # Someone else's library: refused before anything is saved.
    before = env.db.datasets.count_documents({"owner_id": FREE})
    msg = _err(_call(env.oauth[FREE], "change", {"action": "dataset_upload", "args": {
        "name": "X", "csv": csv, "library_id": lid}}))
    assert "Library not found" in msg and env.db.datasets.count_documents({"owner_id": FREE}) == before
