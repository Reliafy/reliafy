"""A dataset's measurements part (docs/datasets.md): stored in the dataset's
own document, added, replaced and removed over the API and MCP; one long
table split into the two parts; a dataset of readings given its life data;
the size limits said in words; condition and life and degradation fits
reading the part; the migration of models saved with two datasets; the
feed-pumps sample."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.services import datasets as ds_service
from backend.tests.test_joint_models import LIFE_MAP, READ_MAP, fleet
from backend.tests.test_mcp import A as MCP_A
from backend.tests.test_mcp import _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp_uploads import _upload

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True}}


@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    from backend.services import samples

    samples.seed_samples(test_db)  # the snapshot (conftest): the shared samples, quickly
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False)


def _paste(client, df, name="Pump lives") -> str:
    r = client.post("/api/datasets/paste", json={"name": name, "content": _csv(df)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _put_file(client, path: str, df: pd.DataFrame, filename="readings.csv", **form):
    return client.put(path, files={"file": (filename, _csv(df).encode(), "text/csv")}, data=form)


def _combined(n=30) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """One long table: a reading per row, each unit's flag on its last row."""
    L, R = fleet(n=n)
    last = R.groupby("unit")["age"].transform("max")
    one = R.merge(L[["unit", "running", "load"]], on="unit")
    one["outcome"] = one["running"].where(one["age"] == last.reindex(one.index).values)
    return one[["unit", "age", "value", "outcome", "load"]], L, R


# ---- Storing the part --------------------------------------------------------------------


def test_measurements_are_stored_in_the_dataset_read_back_replaced_and_removed(client):
    L, R = fleet(n=20)
    ds = _paste(client, L)
    before = client.get(f"/api/datasets/{ds}").json()
    assert before["measurements"] is None and "Measurements" not in before["tags"]
    assert before["use_for"] == ["Non-repairable model with covariates",
                                 "Condition and life model (once measurements are added)"]

    r = _put_file(client, f"/api/datasets/{ds}/measurements", R)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["n_rows"] == len(L) and d["measurements"]["n_rows"] == len(R)
    assert d["measurements"]["preview_columns"] == ["unit", "age", "value"]
    assert len(d["measurements"]["preview"]) == 8 and d["measurements"]["dtypes"][0] in ("object", "str")
    assert d["tags"] == ["Non-repairable", "Covariates", "Measurements"]
    assert d["use_for"][0] == "Condition and life model" and "Degradation model" in d["use_for"]
    assert d["summary"].endswith(f" · {len(R):,} readings") and d["time_unit"] is None
    # One document, both tables in it; the life data is what every life fit reads.
    doc = client.db.datasets.find_one({"_id": ds})
    assert doc["measurements"]["n_rows"] == len(R) and doc["measurements"]["checksum"]
    saved = ds_service.get_dataset(client.db, ds)
    assert list(ds_service.load_dataframe(saved).columns) == ["unit", "age", "running", "load"]
    assert len(ds_service.load_measurements(saved)) == len(R)
    listed = next(x for x in client.get("/api/datasets").json()["datasets"] if x["id"] == ds)
    assert listed["measurements"] == {"n_rows": len(R), "columns": doc["measurements"]["columns"],
                                      "n_columns": 3, "checksum": doc["measurements"]["checksum"]}

    # Replaced from a paste (a sheet works the same way as for the dataset itself).
    fewer = R[R.age <= 50]
    r = client.put(f"/api/datasets/{ds}/measurements/paste", json={"content": _csv(fewer)})
    assert r.status_code == 200 and r.json()["measurements"]["n_rows"] == len(fewer)
    # Taken off: the life data stays.
    r = client.delete(f"/api/datasets/{ds}/measurements")
    assert r.status_code == 200 and r.json()["measurements"] is None and r.json()["n_rows"] == len(L)
    assert client.delete(f"/api/datasets/{ds}/measurements").status_code == 404
    assert "Measurements" not in client.get(f"/api/datasets/{ds}").json()["tags"]


def test_the_size_limits_are_said_in_words(client, monkeypatch):
    from backend import config

    L, R = fleet(n=20)
    ds = _paste(client, L)
    monkeypatch.setattr(config, "MAX_DATASET_BYTES", 2000)
    r = _put_file(client, f"/api/datasets/{ds}/measurements", R)
    assert r.status_code == 422 and "too large for one dataset" in r.json()["detail"]
    monkeypatch.setattr(config, "MAX_DATASET_BYTES", 12 * 1024 * 1024)
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 500)
    r = client.put(f"/api/datasets/{ds}/measurements/paste", json={"content": _csv(R)})
    assert r.status_code == 422 and "too much data to paste" in r.json()["detail"]
    assert client.get(f"/api/datasets/{ds}").json()["measurements"] is None
    # A table that doesn't read is refused as the dataset's own would be.
    r = client.put(f"/api/datasets/{ds}/measurements/paste", json={"content": "just one column\n1\n2\n"})
    assert r.status_code == 422 and "one column" in r.json()["detail"]


def test_samples_and_other_peoples_datasets_take_no_measurements(client):
    L, R = fleet(n=10)
    r = _put_file(client, "/api/datasets/sample-ds-pumps/measurements", R)
    assert r.status_code in (403, 409), r.text
    assert client.db.datasets.find_one({"_id": "sample-ds-pumps"}).get("measurements") is None
    assert _put_file(client, "/api/datasets/nope/measurements", R).status_code == 404


def test_measurements_a_model_reads_are_kept(client):
    L, R = fleet(n=40)
    ds = _paste(client, L)
    assert _put_file(client, f"/api/datasets/{ds}/measurements", R).status_code == 200
    body = {"name": "Pumps", "dataset_id": ds, "mapping": LIFE_MAP, "readings_mapping": READ_MAP,
            "covariates": ["load"], "unit": "Days", "marker": "vibration"}
    r = client.post("/api/joint/models", json=body)
    assert r.status_code == 200, r.text
    mid = r.json()["model_id"]
    for attempt in (client.delete(f"/api/datasets/{ds}/measurements"),
                    _put_file(client, f"/api/datasets/{ds}/measurements", R[R.age < 30]),
                    client.delete(f"/api/datasets/{ds}")):
        assert attempt.status_code == 409 and "Pumps" in attempt.json()["detail"], attempt.text
    assert "condition and life model" in client.delete(f"/api/datasets/{ds}").json()["detail"]
    # The dataset page lists the model as one of its own, by kind.
    page = client.get(f"/api/datasets/{ds}").json()
    assert [m["kind"] for m in page["models"] if m["id"] == mid] == ["joint"]
    assert client.delete(f"/api/joint/models/{mid}").status_code == 200
    assert client.delete(f"/api/datasets/{ds}/measurements").status_code == 200


# ---- One table, split ---------------------------------------------------------------------


def test_one_table_of_life_data_and_readings_is_offered_a_split_and_splits(client):
    from backend.services import joint as joint_service

    one, L, R = _combined(n=30)
    ds = _paste(client, one, name="Pumps in one")
    page = client.get(f"/api/datasets/{ds}").json()
    assert page["tags"] == ["Non-repairable", "Covariates", "Measurements"]
    plan = page["profile"]["split"]
    assert plan == {"unit": "unit", "age": "age", "censor": "outcome", "life_columns": ["load"],
                    "measurement_columns": ["value"], "n_units": 30, "n_readings": len(one), "n_without_outcome": 0}
    # Fitted as one table (the flagged rows are the lifetimes, every row a reading) …
    spec = {"dataset_id": ds, "mapping": {"id": "unit", "x": "age", "c": "outcome"}, "readings_mapping": READ_MAP,
            "covariates": ["load"]}
    items_before, _ = joint_service.items_for(client.db, spec, A)
    r = client.post("/api/datasets/{}/split".format(ds), json={})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["split"] == plan
    assert d["n_rows"] == 30 and d["preview_columns"] == ["unit", "age", "outcome", "load"]
    assert d["measurements"]["n_rows"] == len(one) and d["measurements"]["preview_columns"] == ["unit", "age", "value"]
    assert d["profile"]["split"] is None and d["tags"] == ["Non-repairable", "Covariates", "Measurements"]
    # … reads exactly the same units and readings from the two parts.
    items_after, _ = joint_service.items_for(client.db, spec, A)
    assert items_after == items_before
    assert client.post("/api/datasets/{}/split".format(ds), json={}).status_code == 422
    # Columns can be chosen: a covariate taken as a reading column goes to the measurements.
    ds2 = _paste(client, one, name="Pumps in one again")
    r = client.post(f"/api/datasets/{ds2}/split", json={"life_columns": [], "measurement_columns": ["value", "load"]})
    assert r.status_code == 200 and r.json()["measurements"]["preview_columns"] == ["unit", "age", "value", "load"]


def test_a_split_is_refused_under_a_life_fit_and_for_plain_life_data(client):
    one, L, R = _combined(n=20)
    plain = _paste(client, L, name="Plain lives")
    r = client.post(f"/api/datasets/{plain}/split", json={})
    assert r.status_code == 422 and "doesn't look like life data and readings in one" in r.json()["detail"]
    ds = _paste(client, one, name="In one")
    fit = client.post("/api/models", data={"name": "Wrong", "distribution": "weibull", "dataset_id": ds, "x": "value"})
    assert fit.status_code == 200, fit.text
    r = client.post(f"/api/datasets/{ds}/split", json={})
    assert r.status_code == 422 and "read this table as life data" in r.json()["detail"]


def test_readings_alone_take_their_life_data_later(client):
    L, R = fleet(n=20)
    ds = _paste(client, R, name="Vibration only")
    page = client.get(f"/api/datasets/{ds}").json()
    assert page["tags"] == ["Measurements"]
    assert page["use_for"] == ["Degradation model", "Condition and life model (once life data is added)"]
    # A degradation model fitted to the readings …
    form = {"name": "Vibration to 4", "i": "unit", "x": "age", "y": "value", "threshold": "4.0", "path": "linear",
            "dataset_id": ds}
    r = client.post("/api/degradation/models", data=form)
    assert r.status_code == 200, r.text
    deg = r.json()["id"]
    # … keeps reading them after the life data comes: the readings become the measurements.
    r = _put_file(client, f"/api/datasets/{ds}/life", L, filename="lives.csv")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["preview_columns"] == ["unit", "age", "running", "load"] and d["n_rows"] == len(L)
    assert d["measurements"]["preview_columns"] == ["unit", "age", "value"] and d["measurements"]["n_rows"] == len(R)
    assert d["tags"] == ["Non-repairable", "Covariates", "Measurements"]
    assert client.get(f"/api/degradation/models/{deg}/reliability?confidence=0.8").status_code == 200
    r = client.put(f"/api/datasets/{ds}/life/paste", json={"content": _csv(L)})
    assert r.status_code == 422 and "already has life data and measurements" in r.json()["detail"]
    # Under a life fit the table can't be swapped out.
    L2, _ = fleet(n=15, seed=3)
    ds2 = _paste(client, L2, name="Lives")
    fit = client.post("/api/models", data={"name": "Lives", "distribution": "weibull", "dataset_id": ds2,
                                           "x": "age", "c": "running"})
    assert fit.status_code == 200, fit.text
    r = client.put(f"/api/datasets/{ds2}/life/paste", json={"content": _csv(L)})
    assert r.status_code == 422 and "can't be replaced" in r.json()["detail"]


def test_degradation_fits_read_the_measurements_part(client):
    L, R = fleet(n=20)
    ds = _paste(client, L)
    assert _put_file(client, f"/api/datasets/{ds}/measurements", R).status_code == 200
    form = {"i": "unit", "x": "age", "y": "value", "threshold": "4.0", "path": "linear", "dataset_id": ds}
    r = client.post("/api/degradation/fit", data=form)
    assert r.status_code == 200, r.text
    assert r.json()["results"]["n_units"] == R["unit"].nunique()
    r = client.post("/api/degradation/models", data={**form, "name": "Vibration to 4"})
    assert r.status_code == 200, r.text
    assert client.delete(f"/api/datasets/{ds}/measurements").status_code == 409  # the model reads them


# ---- Over MCP ------------------------------------------------------------------------------


def test_mcp_adds_reads_removes_and_splits_measurements(env):
    a = env.token[MCP_A]
    L, R = fleet(n=20)
    life = _ok(_call(a, "datasets", {"action": "upload", "name": "Pump lives", "csv": _csv(L)}))
    ds = life["id"]
    assert "one way" in _err(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds}))
    assert "one way" in _err(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds, "csv": _csv(R),
                                                   "upload_id": "x"}))
    added = _ok(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds, "csv": _csv(R)}))
    assert added["added"] and added["measurements"]["columns"] == ["unit", "age", "value"]
    assert added["measurements"]["n_rows"] == len(R) and added["tags"][-1] == "Measurements"
    assert len(added["measurements"]["preview"]["preview"]) == 5
    # Read back: the list says it has them; get kind dataset pages either part.
    listed = next(d for d in _ok(_call(a, "list", {"kind": "datasets"}))["datasets"] if d["id"] == ds)
    assert listed["measurements"] == {"n_rows": len(R), "columns": ["unit", "age", "value"]}
    got = _ok(_call(a, "get", {"kind": "dataset", "id": ds, "limit": 2}))
    assert got["part"] == "life" and got["row_count"] == len(L) and got["measurements"]["n_rows"] == len(R)
    part = _ok(_call(a, "get", {"kind": "dataset", "id": ds, "part": "measurements", "limit": 3}))
    assert part["part"] == "measurements" and part["row_count"] == len(R) and len(part["rows"]) == 3
    assert [c["name"] for c in part["columns"]] == ["unit", "age", "value"]
    # From a file sent through uploads create, and from another dataset's table.
    link, _ = _upload(env, _csv(R[R.age < 60]).encode(), "readings.csv", purpose="dataset", uid=MCP_A)
    added = _ok(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds, "upload_id": link["upload_id"]}))
    assert added["measurements"]["n_rows"] == int((R.age < 60).sum())
    other = _ok(_call(a, "datasets", {"action": "upload", "name": "Vibration", "csv": _csv(R)}))
    added = _ok(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds,
                                      "from_dataset_id": other["id"]}))
    assert added["measurements"]["n_rows"] == len(R)
    assert env.db.datasets.find_one({"_id": other["id"]})["n_rows"] == len(R)  # the source is left as it is
    assert "itself" in _err(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds,
                                                  "from_dataset_id": ds}))
    # The part is the model's while one reads it.
    mid = _ok(_call(a, "models", {"action": "fit_joint", "name": "Pumps", "dataset_id": ds,
                                  "unit_id_column": "unit", "age_column": "age", "censor_column": "running",
                                  "reading_age_column": "age", "reading_value_column": "value",
                                  "unit": "Days"}))["model_id"]
    assert "Pumps" in _err(_call(a, "datasets", {"action": "remove_measurements", "dataset_id": ds}))
    assert "Pumps" in _err(_call(a, "datasets", {"action": "add_measurements", "dataset_id": ds, "csv": _csv(R)}))
    _ok(_call(a, "models", {"action": "delete", "model_id": mid}))
    removed = _ok(_call(a, "datasets", {"action": "remove_measurements", "dataset_id": ds}))
    assert removed["removed"] and "measurements" not in removed
    assert "no measurements" in _err(_call(a, "datasets", {"action": "remove_measurements", "dataset_id": ds}))
    assert "no measurements" in _err(_call(a, "get", {"kind": "dataset", "id": ds, "part": "measurements"}))
    # Samples are nobody's to change.
    from backend.services import samples

    samples.seed_samples(env.db)
    assert "sample" in _err(_call(a, "datasets", {"action": "add_measurements", "dataset_id": "sample-ds-pumps",
                                                  "csv": _csv(R)}))
    # One table, split.
    one, _, _ = _combined(n=20)
    ds2 = _ok(_call(a, "datasets", {"action": "upload", "name": "In one", "csv": _csv(one)}))["id"]
    out = _ok(_call(a, "datasets", {"action": "split", "dataset_id": ds2}))
    assert out["split"]["unit"] == "unit" and out["split"]["measurement_columns"] == ["value"]
    assert out["n_rows"] == 20 and out["measurements"]["n_rows"] == len(one)
    assert "doesn't look like" in _err(_call(a, "datasets", {"action": "split", "dataset_id": ds}))


# ---- Models saved with two datasets ------------------------------------------------------


def test_the_migration_script_moves_two_dataset_models_onto_one(client, capsys):
    from backend.scripts import migrate_joint_datasets as script
    from backend.services import joint as joint_service

    L, R = fleet(n=40)
    life, reads = _paste(client, L), _paste(client, R, name="Pump vibration")
    base = {"mapping": LIFE_MAP, "readings_mapping": READ_MAP, "covariates": ["load"], "unit": "Days"}
    two = client.post("/api/joint/models", json={**base, "name": "Two datasets", "lifetimes_dataset_id": life,
                                                 "readings_dataset_id": reads}).json()["model_id"]
    one, _, _ = _combined(n=20)
    combined = _paste(client, one, name="In one")
    same = client.post("/api/joint/models", json={**base, "name": "Same twice", "lifetimes_dataset_id": combined,
                                                  "readings_dataset_id": combined,
                                                  "mapping": {"id": "unit", "x": "age", "c": "outcome"}}).json()
    assert "model_id" in same, same
    same = same["model_id"]
    # The service folds the same id twice into one dataset on save; make it the old shape for the test.
    client.db.models.update_one({"_id": same}, {"$set": {"spec.lifetimes_dataset_id": combined,
                                                         "spec.readings_dataset_id": combined},
                                                "$unset": {"spec.dataset_id": ""}})
    gone = client.db.models.find_one({"_id": two})
    gone.update(_id="gone", spec={**gone["spec"], "readings_dataset_id": "missing"})
    client.db.models.insert_one(gone)
    before = {m: joint_service.items_for(client.db, client.db.models.find_one({"_id": m})["spec"], A)[0]
              for m in (two, same)}

    rows = script.plan(client.db)
    assert {r["model_id"]: r["action"] for r in rows} == {two: "copy_readings", same: "set_id", "gone": "skip"}
    assert script.main([]) == 0
    text = capsys.readouterr().out
    assert text.startswith("DRY RUN") and "readings dataset is missing" in text
    assert client.db.datasets.find_one({"_id": life}).get("measurements") is None  # nothing written

    assert script.main(["--apply"]) == 0
    assert "Moved 2 model(s)" in capsys.readouterr().out
    moved = client.db.models.find_one({"_id": two})["spec"]
    assert moved["dataset_id"] == life and "lifetimes_dataset_id" not in moved and "readings_dataset_id" not in moved
    assert client.db.models.find_one({"_id": same})["spec"]["dataset_id"] == combined
    assert client.db.models.find_one({"_id": "gone"})["spec"].get("dataset_id") is None
    assert client.db.datasets.find_one({"_id": life})["measurements"]["n_rows"] == len(R)
    # They refit from exactly the rows they read before, and open as before.
    for m in (two, same):
        spec = client.db.models.find_one({"_id": m})["spec"]
        assert joint_service.items_for(client.db, spec, A)[0] == before[m]
        assert client.get(f"/api/joint/models/{m}").json()["spec"]["dataset_id"]
        assert client.get(f"/api/joint/models/{m}/export.py").status_code == 200
    # The readings dataset is no longer the model's: it can go.
    assert client.delete(f"/api/datasets/{reads}").status_code == 200
    assert script.plan(client.db) == [{"model_id": "gone", "name": "Two datasets", "owner_id": A,
                                      "lifetimes_dataset_id": life, "readings_dataset_id": "missing",
                                      "action": "skip", "why": "the readings dataset is missing"}]


def test_dataset_keys_fold_the_same_id_twice_into_one():
    from backend.services.joint import dataset_keys, spec_from

    assert dataset_keys({"dataset_id": "d"}) == {"dataset_id": "d"}
    assert dataset_keys({"lifetimes_dataset_id": "d", "readings_dataset_id": "d"}) == {"dataset_id": "d"}
    assert dataset_keys({"lifetimes_dataset_id": "a", "readings_dataset_id": "b"}) == {
        "lifetimes_dataset_id": "a", "readings_dataset_id": "b"}
    assert dataset_keys({}) == {"lifetimes_dataset_id": None, "readings_dataset_id": None}
    spec = spec_from({"dataset_id": "d", "lifetimes_dataset_id": "a", "readings_dataset_id": "b"})
    assert spec["dataset_id"] == "d" and "lifetimes_dataset_id" not in spec


# ---- The sample ---------------------------------------------------------------------------


def test_the_feed_pumps_sample_holds_both_parts_and_a_fitted_model(client):
    d = client.get("/api/datasets/sample-ds-feed-pumps").json()
    assert d["is_sample"] and d["read_only"]
    assert d["preview_columns"] == ["pump", "age_days", "running", "load"] and d["n_rows"] == 40
    assert d["measurements"]["preview_columns"] == ["pump", "age_days", "vibration_mm_s"]
    assert d["measurements"]["n_rows"] > 200
    assert d["tags"] == ["Non-repairable", "Covariates", "Measurements"] and d["time_unit"] == "day"
    assert d["summary"] == f"40 pumps · 35 failed · {d['measurements']['n_rows']:,} readings"
    assert [m["kind"] for m in d["models"]] == ["joint"]
    m = client.get("/api/joint/models/sample-joint-feed-pumps").json()
    assert m["is_sample"] and m["results"]["fit_ok"] and m["results"]["n_running"] == 5
    assert m["spec"]["dataset_id"] == "sample-ds-feed-pumps"
    assert client.get("/api/joint/models/sample-joint-feed-pumps/units/P-02").status_code in (200, 422)
    assert [x["id"] for x in client.get("/api/joint/models").json()["models"]] == ["sample-joint-feed-pumps"]
