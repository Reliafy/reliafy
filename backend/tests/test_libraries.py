"""Libraries (backend/library/entries.py, /api/libraries): made, filled with
snapshots of datasets and models, updated from the original, shared with
workspaces or made public (with a licence, a citation and the owner's word),
read signed out when public, used (copied with where it came from), and
listed beside the built-in handbooks; caps on Free."""

from __future__ import annotations

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp_plans import FREE, PRO

WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
CSV = "time,c\n" + "\n".join(f"{t},{k}" for t, k in [(120, 0), (340, 0), (510, 1), (700, 0), (980, 0), (1200, 1),
                                                    (1500, 0), (1700, 0), (800, 0), (650, 0)])
OTHER = "other-user"
BUILTIN = {"mil-hdbk-217f-n2", "nswc-11", "nrc-inl-2020"}


@pytest.fixture()
def web(monkeypatch):
    """The web app with billing on: PRO (Pro), FREE (Free) and OTHER (Pro), switchable; ``who['uid'] = None``
    is signed out."""
    from fastapi import HTTPException

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["libraries"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)
    test_db.users.insert_many([
        {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
        {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro", "email_verified": True},
        {"_id": OTHER, "email": "other@example.org", "name": "Other", "plan": "pro", "email_verified": True},
    ])
    test_db.teams.insert_one({"_id": "team1", "name": "Plant team", "owner_uid": OTHER,
                              "members": [{"uid": OTHER, "role": "owner"}]})
    who = {"uid": PRO}

    def current():
        if who["uid"] is None:
            raise HTTPException(status_code=401, detail="Sign in.")
        return {"uid": who["uid"], "email": f"{who['uid']}@example.org", "name": "U", "email_verified": True}

    app.dependency_overrides[get_current_user] = current
    tc = TestClient(app)
    tc.who = who
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _dataset(web, csv=CSV, name="d.csv"):
    r = web.post("/api/datasets", files={"file": (name, csv.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _fitted(web, dsid, name="Fitted pump"):
    r = web.post("/api/models", data={"name": name, "dataset_id": dsid, "distribution": "weibull", "x": "time",
                                      "c": "c", "unit": "hours"})
    assert r.status_code == 200, r.text
    return r.json()


def _params(web, name="Pump W"):
    r = web.post("/api/models/from-params", json={"name": name, "distribution": "weibull", "params": WEIBULL,
                                                   "unit": "hours"})
    assert r.status_code == 200, r.text
    return r.json()


def _library(web, name="Site pumps", **extra):
    r = web.post("/api/libraries", json={"name": name, "description": "Our pump fleet", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _make_public(web, lid):
    r = web.put(f"/api/libraries/{lid}/visibility", json={
        "visibility": "public", "licence": "own-cc-by-4.0", "citation": "Site pump records 2020-2025",
        "rights_confirmed": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_make_a_library_add_snapshots_and_read_it(web):
    lib = _library(web)
    lid = lib["id"]
    assert lib["visibility"] == "private" and lib["relation"] == "yours" and lib["can_edit"]
    assert lib["entries"] == [] and lib["counts"] == {"data": 0, "model": 0, "total": 0} and not lib["indexable"]

    ds = _dataset(web)
    fitted = _fitted(web, ds["id"])
    plain = _params(web)
    # Nothing is in a library until it's added.
    assert web.get(f"/api/libraries/{lid}").json()["entries"] == []
    r = web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]})
    assert r.status_code == 200, r.text
    data_entry = r.json()["entry"]
    assert data_entry["type"] == "data" and data_entry["version"] == 1
    assert data_entry["data"]["n_rows"] == 10 and data_entry["data"]["columns"] == ["time", "c"]
    assert data_entry["data"]["reading_summary"].startswith("x = time")
    assert data_entry["origin"]["url"] == f"/data/{ds['id']}" and data_entry["origin"]["exists"]
    # The same dataset twice is refused in words.
    again = web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]})
    assert again.status_code == 422 and "already in" in again.json()["detail"]

    m1 = web.post(f"/api/libraries/{lid}/entries", json={"model_id": fitted["id"]}).json()["entry"]
    m2 = web.post(f"/api/libraries/{lid}/entries", json={"model_id": plain["id"]}).json()["entry"]
    # A fitted model shows the dataset it was fitted on (it's in the library) and its B10 with a 90% lower bound.
    assert m1["model"]["fitted_on"] == {"entry_id": data_entry["id"], "name": ds["name"]}
    assert m1["model"]["has_dataset"] and m1["model"]["kind_label"] == "Non-repairable"
    h = m1["model"]["headline"]
    assert h["label"] == "B10" and h["confidence"] == 0.9 and h["bound"] == "lower"
    assert 0 < h["lower"] < h["value"] and "90% lower bound" in h["text"]
    # A model from parameters needs no data: where it came from, in words.
    assert m2["model"]["fitted_on"] is None and m2["model"]["basis_text"] == "From parameters"
    assert m2["model"]["headline"]["lower"] is None

    out = web.get(f"/api/libraries/{lid}").json()
    assert out["counts"] == {"data": 1, "model": 2, "total": 3}
    assert [e["type"] for e in out["entries"]] == ["data", "model", "model"]
    detail = web.get(f"/api/libraries/{lid}/entries/{data_entry['id']}").json()
    assert detail["data"]["preview"]["columns"] == ["time", "c"] and len(detail["data"]["preview"]["rows"]) == 10
    assert detail["data"]["reading"]["x"] == "time"
    mdetail = web.get(f"/api/libraries/{lid}/entries/{m1['id']}").json()
    assert [p["name"] for p in mdetail["model"]["params"]] == ["alpha", "beta"]

    # The Data and Models views gather entries across libraries.
    data_view = web.get("/api/libraries/entries?type=data").json()
    assert [e["id"] for e in data_view["entries"]] == [data_entry["id"]] and data_view["entries"][0]["library"]["id"] == lid
    models_view = web.get("/api/libraries/entries?type=model&q=fitted").json()
    assert [e["id"] for e in models_view["entries"]] == [m1["id"]]
    assert {c["id"] for c in models_view["builtin"]} == BUILTIN


def test_a_snapshot_is_kept_until_updated_from_the_original(web):
    lid = _library(web)["id"]
    ds = _dataset(web)
    fitted = _fitted(web, ds["id"])
    entry = web.post(f"/api/libraries/{lid}/entries", json={"model_id": fitted["id"]}).json()["entry"]
    dentry = web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]}).json()["entry"]
    # Edits in the workspace don't change the library.
    web.db.models.update_one({"_id": fitted["id"]}, {"$set": {"name": "Renamed", "results.params.0.value": 5.0}})
    web.db.datasets.update_one({"_id": ds["id"]}, {"$set": {"name": "Renamed data"}})
    got = web.get(f"/api/libraries/{lid}/entries/{entry['id']}").json()
    assert got["name"] == "Fitted pump" and got["model"]["params"][0]["value"] != 5.0
    # Update from the original takes a new snapshot, one version up.
    r = web.post(f"/api/libraries/{lid}/entries/{entry['id']}/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["version"] == 2 and r.json()["entry"]["name"] == "Renamed"
    assert web.get(f"/api/libraries/{lid}/entries/{entry['id']}").json()["model"]["params"][0]["value"] == 5.0
    r = web.post(f"/api/libraries/{lid}/entries/{dentry['id']}/refresh")
    assert r.json()["entry"]["version"] == 2 and r.json()["entry"]["name"] == "Renamed data"
    # The original deleted: the entry stays, and says so; refreshing explains why it can't.
    assert web.delete(f"/api/models/{fitted['id']}").status_code == 200
    out = web.get(f"/api/libraries/{lid}").json()
    gone = next(e for e in out["entries"] if e["id"] == entry["id"])
    assert gone["origin"]["exists"] is False
    r = web.post(f"/api/libraries/{lid}/entries/{entry['id']}/refresh")
    assert r.status_code == 422 and "deleted" in r.json()["detail"]
    # Remove and delete.
    assert web.delete(f"/api/libraries/{lid}/entries/{entry['id']}").json()["removed"] is True
    assert web.delete(f"/api/libraries/{lid}").json() == {"ok": True, "entries_removed": 1}
    assert web.get(f"/api/libraries/{lid}").status_code == 404


def test_visibility_private_workspaces_and_public(web):
    lib = _library(web)
    lid = lib["id"]
    ds = _dataset(web)
    entry = web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]}).json()["entry"]

    # Private: nobody else sees it, signed in or out.
    web.who["uid"] = OTHER
    assert web.get(f"/api/libraries/{lid}").status_code == 404
    assert lid not in {c["id"] for c in web.get("/api/libraries").json()["libraries"]}
    web.who["uid"] = None
    assert web.get(f"/api/libraries/{lid}").status_code == 404
    signed_out = web.get("/api/libraries").json()
    assert signed_out["signed_in"] is False and {c["id"] for c in signed_out["libraries"]} == BUILTIN

    # Shared with workspaces: an unknown ID is refused; a team's ID lets its members read it, read-only.
    web.who["uid"] = PRO
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "workspaces", "workspaces": ["nope"]})
    assert r.status_code == 422 and "No workspace has the ID" in r.json()["detail"]
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "workspaces", "workspaces": []})
    assert r.status_code == 422 and "at least one workspace" in r.json()["detail"]
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "workspaces", "workspaces": ["team1"]})
    assert r.status_code == 200 and r.json()["shared_with"] == ["team1"] and r.json()["visibility"] == "workspaces"
    web.who["uid"] = OTHER
    seen = web.get(f"/api/libraries/{lid}")
    assert seen.status_code == 200 and seen.json()["relation"] == "shared" and seen.json()["can_edit"] is False
    assert seen.json()["shared_with"] == [] and seen.json()["entries"][0].get("origin") is None
    # Read-only for them: no change of any kind.
    assert web.patch(f"/api/libraries/{lid}", json={"name": "Taken"}).status_code == 403
    assert web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]}).status_code == 403
    assert web.delete(f"/api/libraries/{lid}/entries/{entry['id']}").status_code == 403
    assert web.post(f"/api/libraries/{lid}/entries/{entry['id']}/refresh").status_code == 403
    assert web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "private"}).status_code == 403
    assert web.delete(f"/api/libraries/{lid}").status_code == 403
    web.who["uid"] = FREE
    assert web.get(f"/api/libraries/{lid}").status_code == 404
    # A personal workspace's ID (the user id) works too.
    web.who["uid"] = PRO
    assert web.get("/api/libraries").json()["workspace_id"] == PRO
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "workspaces", "workspaces": [FREE, "team:team1"]})
    assert r.json()["shared_with"] == [FREE, "team1"]
    web.who["uid"] = FREE
    assert web.get(f"/api/libraries/{lid}").status_code == 200

    # Public: needs a licence, a citation or source, and the tick, said in words.
    web.who["uid"] = PRO
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "public"})
    assert r.status_code == 422
    words = r.json()["detail"]
    assert "a licence" in words and "source or citation" in words and "right to publish" in words
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "public", "licence": "cc-by-4.0",
                                                        "citation": "Plant records", "rights_confirmed": False})
    assert r.status_code == 422 and "right to publish" in r.json()["detail"]
    r = web.put(f"/api/libraries/{lid}/visibility", json={"visibility": "public", "licence": "mit",
                                                        "citation": "x", "rights_confirmed": True})
    assert r.status_code == 422 and "licence is one of" in r.json()["detail"]
    pub = _make_public(web, lid)
    assert pub["indexable"] and pub["licence"] == {"id": "own-cc-by-4.0", "name": "Our own data, published under CC BY 4.0"}
    # A public library's citation can't be cleared while it's public.
    assert web.patch(f"/api/libraries/{lid}", json={"citation": ""}).status_code == 422

    # Anyone reads it, signed out included (the rows too), but can't use it without signing in.
    web.who["uid"] = None
    out = web.get(f"/api/libraries/{lid}")
    assert out.status_code == 200 and out.json()["relation"] == "public" and out.json()["can_edit"] is False
    assert out.headers["cache-control"] == "private, no-store"
    assert web.get(f"/api/libraries/{lid}/entries/{entry['id']}").json()["data"]["preview"]["rows"]
    assert lid in {c["id"] for c in web.get("/api/libraries").json()["libraries"]}
    assert web.post(f"/api/libraries/{lid}/entries/{entry['id']}/use", json={}).status_code == 401
    assert web.post("/api/libraries", json={"name": "x"}).status_code == 401
    web.who["uid"] = OTHER
    cards = web.get("/api/libraries").json()["libraries"]
    card = next(c for c in cards if c["id"] == lid)
    assert card["relation"] == "public" and card["counts"]["data"] == 1
    assert [c["builtin"] for c in cards][-3:] == [True, True, True]


def test_use_an_entry_copies_it_with_where_it_came_from(web):
    lid = _library(web)["id"]
    ds = _dataset(web)
    fitted = _fitted(web, ds["id"])
    dentry = web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]}).json()["entry"]
    mentry = web.post(f"/api/libraries/{lid}/entries", json={"model_id": fitted["id"]}).json()["entry"]
    _make_public(web, lid)

    web.who["uid"] = OTHER
    r = web.post(f"/api/libraries/{lid}/entries/{dentry['id']}/use", json={})
    assert r.status_code == 200, r.text
    copy = r.json()["dataset"]
    assert copy["reused"] is False and copy["url"] == f"/data/{copy['id']}" and r.json()["model"] is None
    got = web.get(f"/api/datasets/{copy['id']}").json()
    assert got["n_rows"] == 10 and got["read_only"] is False
    assert got["from_library"] == {"library_id": lid, "library_name": "Site pumps", "entry_id": dentry["id"], "version": 1}
    assert got["reading"]["x"] == "time"
    # The same data again comes back as the copy they already have.
    assert web.post(f"/api/libraries/{lid}/entries/{dentry['id']}/use", json={}).json()["dataset"]["reused"] is True

    # A model, with the dataset it was fitted on: both copied, the model linked to the new dataset.
    r = web.post(f"/api/libraries/{lid}/entries/{mentry['id']}/use", json={"with_dataset": True, "name": "My pump"})
    assert r.status_code == 200, r.text
    made = r.json()["model"]
    assert made["name"] == "My pump" and made["url"] == f"/models/m/{made['id']}"
    model = web.get(f"/api/models/{made['id']}").json()
    assert model["dataset_id"] == r.json()["dataset"]["id"] and model["from_library"]["entry_id"] == mentry["id"]
    assert model["results"]["params"][0]["value"] == pytest.approx(fitted["results"]["params"][0]["value"])
    # The copy is theirs to change; the library isn't.
    assert web.patch(f"/api/models/{made['id']}", json={"name": "Mine now"}).status_code in (200, 204)
    # Without the dataset: the model alone.
    alone = web.post(f"/api/libraries/{lid}/entries/{mentry['id']}/use", json={}).json()
    assert alone["dataset"] is None and web.get(f"/api/models/{alone['model']['id']}").json()["dataset_id"] == ""


def test_caps_a_library_is_one_item_and_a_copy_counts(web):
    web.who["uid"] = FREE
    lid = _library(web, "One")["id"]
    over = web.post("/api/libraries", json={"name": "Two"})
    assert over.status_code == 402 and over.json()["code"] == "cap" and "limit of 1 library" in over.json()["detail"]
    # Entries don't count toward the library cap.
    ds = _dataset(web)
    assert web.post(f"/api/libraries/{lid}/entries", json={"dataset_id": ds["id"]}).status_code == 200
    # Using a public entry counts as the copy it makes: at the datasets cap it's refused.
    web.who["uid"] = PRO
    plid = _library(web, "Public data")["id"]
    other = _dataset(web, CSV.replace("120,0", "121,0"), "other.csv")
    pentry = web.post(f"/api/libraries/{plid}/entries", json={"dataset_id": other["id"]}).json()["entry"]
    _make_public(web, plid)
    web.who["uid"] = FREE
    for i in range(2):
        _dataset(web, CSV.replace("120,0", f"{130 + i},0"), f"x{i}.csv")
    r = web.post(f"/api/libraries/{plid}/entries/{pentry['id']}/use", json={})
    assert r.status_code == 402 and r.json()["code"] == "cap" and "dataset" in r.json()["detail"]


def test_the_built_in_handbooks_are_read_only_public_libraries(web):
    cards = {c["id"]: c for c in web.get("/api/libraries").json()["libraries"] if c["builtin"]}
    assert set(cards) == BUILTIN
    assert all(c["visibility"] == "public" and not c["can_edit"] and c["counts"]["model"] > 0 for c in cards.values())
    one = web.get("/api/libraries/nswc-11").json()
    assert one["builtin"] and one["entries"] == [] and one["indexable"] and one["url"] == "/libraries/nswc-11"
    assert web.patch("/api/libraries/nswc-11", json={"name": "Mine"}).status_code == 403
    assert web.post("/api/libraries/nswc-11/entries", json={"dataset_id": "x"}).status_code == 403
    # Signed out too.
    web.who["uid"] = None
    assert web.get("/api/libraries/mil-hdbk-217f-n2").status_code == 200


def test_add_any_model_kind_and_a_published_source(web):
    lid = _library(web)["id"]
    plain = _params(web, "Handbook pump")
    r = web.post(f"/api/libraries/{lid}/entries", json={"model_id": plain["id"], "source": "Plant survey, 2020"})
    assert r.status_code == 200
    assert r.json()["entry"]["model"]["basis_text"] == "From a published source: Plant survey, 2020"
    assert web.post(f"/api/libraries/{lid}/entries", json={"model_id": plain["id"], "collection": "rbds"}).status_code == 422
    assert web.post(f"/api/libraries/{lid}/entries", json={}).status_code == 422
    assert web.post(f"/api/libraries/{lid}/entries", json={"model_id": "nope"}).status_code == 404
    # A model made from a handbook record says where it came from.
    rec = web.get("/api/library/search?source=nrc-inl-2020&kind=rate&page_size=1").json()["results"][0]
    made = web.post("/api/models/from-library", json={"record_id": rec["id"]})
    assert made.status_code == 200, made.text
    e = web.post(f"/api/libraries/{lid}/entries", json={"model_id": made.json()["id"]}).json()["entry"]
    assert e["model"]["basis_text"] == "From NRC/INL 2020"


def test_spa_root_and_signed_in_routes():
    from backend.main import SPA_ROOTS, is_spa_route

    assert "libraries" in SPA_ROOTS and is_spa_route("libraries/abc")


# ---- uploads straight into a library -----------------------------------------------------------

SITES = "site,time,c\n" + "\n".join(f"{s},{t},{k}" for s, t, k in [
    ("North", 120, 0), ("North", 340, 0), ("North", 510, 1), ("South", 700, 0), ("South", 980, 0),
    ("South", 1200, 1), ("East", 1500, 0), ("East", 1700, 0), ("East", 800, 1)])


def _upload(web, csv, **form):
    return web.post("/api/datasets", files={"file": ("sites.csv", csv.encode(), "text/csv")}, data=form)


def test_an_upload_split_into_datasets_goes_into_a_library_too(web):
    lid = _library(web)["id"]
    r = _upload(web, SITES, name="Pump sites", dataset_col="site", library_id=lid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["datasets"]) == 3
    assert out["library"]["id"] == lid and out["library"]["url"] == f"/libraries/{lid}"
    assert len(out["library"]["added"]) == 3 and out["library"]["already"] == []
    lib = web.get(f"/api/libraries/{lid}").json()
    assert lib["counts"] == {"data": 3, "model": 0, "total": 3}
    # Each entry is its own dataset's snapshot (the split column left out of each), never merged.
    assert sorted(e["name"] for e in lib["entries"]) == sorted(d["name"] for d in out["datasets"])
    assert all(e["data"]["columns"] == ["time", "c"] and e["data"]["n_rows"] == 3 for e in lib["entries"])
    # The same file again: the datasets come back as they are, already in the library, nothing doubled.
    again = _upload(web, SITES, name="Pump sites", dataset_col="site", library_id=lid).json()
    assert sorted(again["library"]["already"]) == sorted(d["name"] for d in out["datasets"])
    assert web.get(f"/api/libraries/{lid}").json()["counts"]["data"] == 3

    # One file, no split; and a paste.
    one = _upload(web, CSV, name="Bearings", library_id=lid).json()
    assert one["name"] == "Bearings" and len(one["library"]["added"]) == 1
    pasted = web.post("/api/datasets/paste", json={"name": "Seals", "content": CSV.replace("120,0", "125,0"),
                                                    "library_id": lid})
    assert pasted.status_code == 200 and len(pasted.json()["library"]["added"]) == 1
    assert web.get(f"/api/libraries/{lid}").json()["counts"]["data"] == 5


def test_an_upload_into_someone_elses_library_saves_nothing(web):
    lid = _library(web)["id"]
    _make_public(web, lid)
    web.who["uid"] = OTHER
    before = web.db.datasets.count_documents({"owner_id": OTHER})
    r = _upload(web, SITES, name="Theirs", dataset_col="site", library_id=lid)
    assert r.status_code == 403 and "owner" in r.json()["detail"]
    r = _upload(web, CSV, name="Theirs", library_id="no-such-library")
    assert r.status_code == 404
    assert web.db.datasets.count_documents({"owner_id": OTHER}) == before
    assert web.db.library_records.count_documents({"library_id": lid}) == 0


def test_an_upload_into_a_library_is_all_or_nothing(web, monkeypatch):
    from backend.library import entries

    lid = _library(web)["id"]
    monkeypatch.setattr(entries, "MAX_ENTRIES", 2)
    before = web.db.datasets.count_documents({"owner_id": PRO})
    r = _upload(web, SITES, name="Too many", dataset_col="site", library_id=lid)
    assert r.status_code == 422 and "room for 2 more" in r.json()["detail"] and "nothing was saved" in r.json()["detail"]
    assert web.db.datasets.count_documents({"owner_id": PRO}) == before
    assert web.db.library_records.count_documents({"library_id": lid}) == 0


def test_an_upload_into_a_library_keeps_the_free_cap(web):
    web.who["uid"] = FREE
    lid = _library(web, "One")["id"]
    _dataset(web)  # 1 of the 3 free datasets
    r = _upload(web, SITES, name="Sites", dataset_col="site", library_id=lid)
    assert r.status_code == 402 and r.json()["code"] == "cap"
    assert web.db.library_records.count_documents({"library_id": lid}) == 0
    # What fits goes in: two parts.
    two = "\n".join(line for line in SITES.splitlines() if not line.startswith("East"))
    r = _upload(web, two, name="Sites", dataset_col="site", library_id=lid)
    assert r.status_code == 200, r.text
    assert len(r.json()["library"]["added"]) == 2
