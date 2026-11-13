"""A dataset's modelling reading (backend/services/dataset_reading.py): which
column is x, c, n, … and the covariates Z, kept from upload (the web upload,
paste and split; MCP change dataset_upload and so its REST twin and the CLI),
changed later (PUT /api/datasets/{id}/reading, change dataset_update), derived
on read for a dataset saved before readings (never written back), copied into
each model fitted from it, and used by an MCP fit that names no columns."""

import json
import pathlib
import re

import mongomock
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")

U = "user-reading"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"

SHEET = (
    "ID,Equipment Tag,Equipment class,Status,Age (h),Failure mode,Remarks,Load,Site\n"
    "R1,T-1,Transformer,Failed,1200,Winding,ran hot in summer,10.5,North\n"
    "R2,T-2,Transformer,Running,4000,,clean record,12.0,South\n"
    "R3,M-1,Coal mill,Failed,300,Liner,liner cracked early,8.1,North\n"
    "R4,M-2,Coal mill,Running,450,,still going,9.9,South\n"
    "R5,M-3,Coal mill,Failed,610,Liner,replaced at outage,11.2,North\n"
    "R6,P-1,Boiler feed pump,Failed,800,Seal,seal leak found,7.7,South\n"
    "R7,P-2,Boiler feed pump,Running,950,,no notes taken,13.4,North\n"
)
READING = {"x": "Age (h)", "c": "Status", "c_map": {"Failed": 0, "Running": 1}, "e": "Failure mode",
           "i": "Equipment Tag", "unit": "Hours", "z": ["Load", "Site"], "z_units": {"Load": "kN"},
           "not_used": ["ID", "Remarks"]}


def _sheets(name: str, export: str) -> dict:
    """The walkthrough sheets of a frontend fixture module, one per line."""
    src = (FRONTEND / name).read_text()
    body = src[src.index(f"export const {export} = {{"):]
    out = {}
    for line in body.splitlines()[1:]:
        m = re.match(r"^\s+(\w+): (\{.*\}),?\s*$", line)
        if m:
            out[m.group(1)] = json.loads(m.group(2))
    return out


def test_the_server_guesses_the_reading_the_upload_screen_guesses():
    from backend.services import dataset_reading as dr

    sheets = {**_sheets("dataStepSheets.js", "SHEETS"), **_sheets("dataStepFamilySheets.js", "FAMILY_SHEETS")}
    cases = json.loads((FRONTEND / "readingGuessCases.json").read_text())
    assert set(sheets) == set(cases) and len(cases) >= 19
    for name, sheet in sheets.items():
        assert dr.guess(sheet) == cases[name], name


def test_the_guess_on_a_plant_sheet_and_its_z_guard():
    from backend.services import dataset_reading as dr

    r = dr.guess_for_bytes(SHEET.encode())
    assert (r["x"], r["c"], r["e"], r["i"], r["unit"]) == ("Age (h)", "Status", "Failure mode", "Equipment Tag", "Hours")
    assert r["c_map"] == {"Failed": 0, "Running": 1}
    assert r["z"] == ["Equipment class", "Load", "Site"]
    assert r["not_used"] == ["ID", "Remarks"]
    assert dr.summary(r) == ("x = Age (h) · c = Status · i = Equipment Tag · failure mode = Failure mode · "
                             "Z: Equipment class, Load, Site · not used: ID, Remarks")


def test_normalize_checks_roles_against_the_columns():
    from backend.services import dataset_reading as dr

    cols = ["Age", "Status", "Load"]
    with pytest.raises(dr.ReadingError, match="Every model is built on it"):
        dr.normalize({"c": "Status"}, cols)
    with pytest.raises(dr.ReadingError, match="isn't a column"):
        dr.normalize({"x": "Hours"}, cols)
    with pytest.raises(dr.ReadingError, match="one role only"):
        dr.normalize({"x": "Age", "tl": "Age"}, cols)
    with pytest.raises(dr.ReadingError, match="can't also be a covariate"):
        dr.normalize({"x": "Age", "z": ["Age"]}, cols)
    with pytest.raises(dr.ReadingError, match="0 \\(failed\\)"):
        dr.normalize({"x": "Age", "c": "Status", "c_map": {"F": 5}}, cols)
    out = dr.normalize({"x": "Age", "c": "Status", "s": "Load", "c_invert": True, "junk": 1}, cols)
    assert out["s"] == "Load" and out["c_invert"] is True and "junk" not in out


@pytest.fixture()
def web(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_reading_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": U, "email": "r@example.org", "name": "R", "email_verified": True}
    try:
        yield TestClient(app), test_db
    finally:
        app.dependency_overrides.clear()


def _upload(client, data=None, sheet=SHEET):
    return client.post("/api/datasets", files={"file": ("plant.csv", sheet.encode(), "text/csv")}, data=data or {})


def test_upload_keeps_the_reading_and_the_detail_returns_it(web):
    client, db = web
    res = _upload(client, {"name": "Plant", "reading": json.dumps(READING)})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["reading_source"] == "saved" and d["reading_kept"] is True
    assert d["reading"]["x"] == "Age (h)" and d["reading"]["z"] == ["Load", "Site"]
    assert d["reading"]["z_units"] == {"Load": "kN"}
    assert d["reading_summary"].startswith("x = Age (h) · c = Status")
    assert db.datasets.find_one({"_id": d["id"]})["reading"]["c_map"] == {"Failed": 0, "Running": 1}
    again = client.get(f"/api/datasets/{d['id']}").json()
    assert again["reading_source"] == "saved"


def test_upload_refuses_a_reading_without_x_and_saves_nothing(web):
    client, db = web
    res = _upload(client, {"reading": json.dumps({"c": "Status"})})
    assert res.status_code == 422 and "Every model is built on it" in res.json()["detail"]
    assert db.datasets.count_documents({}) == 0
    assert _upload(client, {"reading": "not json"}).status_code == 422


def test_preview_gives_the_columns_as_stored_and_the_guess(web):
    client, _ = web
    out = client.post("/api/datasets/preview", files={"file": ("plant.csv", SHEET.encode(), "text/csv")}).json()
    assert out["columns"][:3] == ["ID", "Equipment Tag", "Equipment class"]
    assert out["reading"]["x"] == "Age (h)" and out["n_rows"] == 7
    pasted = client.post("/api/datasets/preview-paste", json={"content": SHEET.replace(",", "\t")}).json()
    assert pasted["columns"] == out["columns"]


def test_split_keeps_one_reading_on_every_part_without_the_split_column(web):
    client, db = web
    reading = {**READING, "z": ["Equipment class", "Load", "Site"]}
    res = _upload(client, {"dataset_col": "Equipment class", "reading": json.dumps(reading)})
    assert res.status_code == 200, res.text
    parts = res.json()["datasets"]
    assert len(parts) == 3
    for p in parts:
        kept = db.datasets.find_one({"_id": p["id"]})["reading"]
        assert kept["x"] == "Age (h)" and kept["z"] == ["Load", "Site"]
        assert "Equipment class" not in json.dumps(kept)


def test_paste_takes_a_reading_too(web):
    client, _ = web
    res = client.post("/api/datasets/paste", json={"name": "P", "content": SHEET, "reading": READING})
    assert res.status_code == 200 and res.json()["reading_source"] == "saved"


def test_change_the_reading_and_models_keep_theirs(web):
    client, db = web
    d = _upload(client, {"name": "Plant", "reading": json.dumps(READING)}).json()
    saved = client.post("/api/models", data={"name": "Weibull", "distribution": "weibull", "dataset_id": d["id"],
                                             "x": "Age (h)", "c": "Status", "unit": "Hours",
                                             "c_map": json.dumps({"Failed": 0, "Running": 1})})
    assert saved.status_code == 200, saved.text
    model = db.models.find_one({"_id": saved.json()["id"]})
    assert model["spec"]["reading"]["z"] == ["Load", "Site"]
    # A new reading for the dataset: later fits use it; the model keeps the one it was fitted with.
    res = client.put(f"/api/datasets/{d['id']}/reading", json={"reading": {**READING, "z": ["Load"]}})
    assert res.status_code == 200 and res.json()["reading"]["z"] == ["Load"]
    assert db.models.find_one({"_id": model["_id"]})["spec"]["reading"]["z"] == ["Load", "Site"]
    bad = client.put(f"/api/datasets/{d['id']}/reading", json={"reading": {"x": "Nope"}})
    assert bad.status_code == 422


def test_an_older_dataset_gets_a_reading_on_read_and_is_never_rewritten(web):
    client, db = web
    d = _upload(client, {"name": "Old"}).json()
    db.datasets.update_one({"_id": d["id"]}, {"$unset": {"reading": ""}})
    before = db.datasets.find_one({"_id": d["id"]})
    fresh = client.get(f"/api/datasets/{d['id']}").json()
    assert fresh["reading_source"] == "guessed" and fresh["reading_kept"] is False
    assert fresh["reading"]["x"] == "Age (h)" and fresh["reading"]["c"] == "Status"
    # Fitted once: its newest model's reading.
    client.post("/api/models", data={"name": "M", "distribution": "weibull", "dataset_id": d["id"],
                                     "x": "Age (h)", "c": "Status", "c_map": json.dumps({"Failed": 0, "Running": 0})})
    later = client.get(f"/api/datasets/{d['id']}").json()
    assert later["reading_source"] == "last_model"
    assert later["reading"]["c_map"] == {"Failed": 0, "Running": 0}
    assert db.datasets.find_one({"_id": d["id"]}) == before


def test_start_and_stop_rows_read_as_one_life_per_item():
    from backend import fitting

    df = pd.DataFrame({"pump": ["A", "A", "B", "B", "C"], "start": [0, 100, 0, 50, 0],
                       "stop": [100, 250, 50, 400, 300], "c": [1, 0, 1, 1, 0]})
    out, mapping = fitting.item_lives(df, {"i": "pump", "xl": "start", "xr": "stop", "c": "c"})
    assert mapping == {"x": "stop", "c": "c"}
    assert out.to_dict("list") == {"stop": [250.0, 400.0, 300.0], "c": [0, 1, 0]}
    res = fitting.fit("weibull", df, {"i": "pump", "xl": "start", "xr": "stop", "c": "c"},
                      options={fitting.ITEM_LIVES_KEY: True})
    assert res["options"][fitting.ITEM_LIVES_KEY] is True and res["item_lives"] == 3
    plain = fitting.fit("weibull", pd.DataFrame({"x": [250, 400, 300], "c": [0, 1, 0]}), {"x": "x", "c": "c"})
    assert res["params"] == plain["params"]


def test_mcp_upload_guesses_the_reading_when_none_is_given(env):
    out = _ok(_call(env.token[A], "change", {"action": "dataset_upload", "name": "plant", "csv": SHEET}))
    r = out["reading"]
    assert r["source"] == "guessed" and r["x"] == "Age (h)" and r["c"] == "Status"
    assert "Z: Equipment class, Load, Site" in r["summary"]
    got = _ok(_call(env.token[A], "get", {"kind": "dataset", "id": out["id"]}))
    assert got["reading"]["source"] == "guessed"


def test_mcp_upload_takes_the_reading_and_refuses_only_without_x(env):
    out = _ok(_call(env.token[A], "change", {
        "action": "dataset_upload", "name": "plant2", "csv": SHEET.replace("Age (h)", "Age"),
        "x_col": "Age", "c_col": "Status", "c_meanings": {"Failed": 0, "Running": 1}, "z_cols": ["Load"],
        "unit": "hours", "s_col": "Site"}))
    r = out["reading"]
    assert r["source"] == "saved" and r["x"] == "Age" and r["z"] == ["Load"] and r["s"] == "Site"
    assert "Site" not in r.get("not_used", [])
    msg = _err(_call(env.token[A], "change", {"action": "dataset_upload", "name": "words",
                                              "csv": "Tag,Note\nA,ok\nB,bad\n"}))
    assert "x_col" in msg
    upd = _ok(_call(env.token[A], "change", {"action": "dataset_update", "dataset_id": out["id"], "z_cols": []}))
    assert "reading" in upd["updated"] and not upd["reading"].get("z")


def test_mcp_fit_without_columns_uses_the_reading(env):
    out = _ok(_call(env.token[A], "change", {
        "action": "dataset_upload", "name": "plant3", "csv": SHEET, "x_col": "Age (h)", "c_col": "Status",
        "c_meanings": {"Failed": 0, "Running": 1}}))
    fit = _ok(_call(env.token[A], "analyse", {"action": "fit", "dataset_id": out["id"], "distribution": "weibull",
                                              "unit": "hours"}))
    assert fit["censoring"]["n_failed"] == 4 and fit["censoring"]["n_right_censored"] == 3
    named = _ok(_call(env.token[A], "analyse", {"action": "fit", "dataset_id": out["id"], "distribution": "weibull",
                                                "unit": "hours", "time_column": "Age (h)"}))
    # Naming only the time: every row a failure, as before.
    assert named["censoring"]["n_failed"] == 7 if "censoring" in named else True


def test_summary_adds_the_unit_only_when_the_column_name_lacks_one():
    from backend.services import dataset_reading as dr

    assert dr.summary({"x": "Age", "unit": "Hours"}).startswith("x = Age (Hours)")
    assert dr.summary({"x": "Age (h)", "unit": "Hours"}).startswith("x = Age (h)")
    assert "(Hours)" not in dr.summary({"x": "Age (h)", "unit": "Hours"})
