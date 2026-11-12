"""One sheet saved as several datasets, split by a column (``dataset_col``):
the web upload (POST /api/datasets) and MCP change dataset_upload (and so its
REST twin and the CLI). Each value becomes its own dataset named by the value,
with its own rows; blank values are left out; the plan's storage cap counts
every new dataset, and is checked before anything is saved."""

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_mcp_account_bounds_data import FREE, plans  # noqa: F401 - plans is a fixture

# MCP switched on (on the cloud it is off by default).
pytestmark = pytest.mark.usefixtures("mcp_on")

U = "user-a"

SHEET = (
    "Unit,Equipment,Hours,Status\n"
    "T-1,Transformer,1200,Failed\n"
    "M-1,Coal mill,300,Failed\n"
    "T-2,Transformer,4000,Running\n"
    "P-1,Boiler feed pump,800,Failed\n"
    "M-2,Coal mill,450,Running\n"
    "X-1,,900,Failed\n"
    "M-3,Coal mill,610,Failed\n"
    ",,,\n"
    "X-2,  ,100,Running\n"
)


@pytest.fixture()
def web(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 5)
    test_db = mongomock.MongoClient()["reliafy_split_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": U, "email": "a@example.org", "name": "A", "email_verified": True}
    try:
        yield TestClient(app), test_db
    finally:
        app.dependency_overrides.clear()


def _upload(client, data, sheet=SHEET, filename="plant.csv"):
    return client.post("/api/datasets", files={"file": (filename, sheet.encode(), "text/csv")}, data=data)


def _rows(db, name):
    from backend.db import from_doc
    from backend.schema import Dataset
    from backend.services import datasets as datasets_service

    doc = db.datasets.find_one({"name": name, "owner_id": U})
    return datasets_service.load_dataframe(from_doc(Dataset, doc))


def test_split_service_groups_rows_in_order_and_counts_blanks():
    from backend.services import datasets as datasets_service

    parts, blank = datasets_service.split_by_column(SHEET.encode(), "Equipment")
    assert [v for v, _ in parts] == ["Transformer", "Coal mill", "Boiler feed pump"]
    assert blank == 2  # X-1 and the whitespace-only X-2; the wholly blank row isn't a row
    coal = parts[1][1].decode()
    assert coal == "Unit,Hours,Status\nM-1,300,Failed\nM-2,450,Running\nM-3,610,Failed\n"
    with pytest.raises(Exception, match="no column “Site”"):
        datasets_service.split_by_column(SHEET.encode(), "Site")


def test_split_names_add_the_file_when_taken():
    from backend.services import datasets as datasets_service

    names = datasets_service.split_names(["Transformer", "Coal mill", "Pump"], {"transformer", "Pump – plant",
                                                                                "Pump"}, "plant")
    assert names == ["Transformer – plant", "Coal mill", "Pump – plant (2)"]


def test_upload_with_dataset_col_makes_one_dataset_per_value(web):
    client, db = web
    db.datasets.insert_one({"_id": "old", "name": "Transformer", "owner_id": U, "checksum": "x"})
    r = _upload(client, {"name": "plant", "dataset_col": "Equipment"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [d["name"] for d in out["datasets"]] == ["Transformer – plant", "Coal mill", "Boiler feed pump"]
    assert [d["n_rows"] for d in out["datasets"]] == [2, 3, 1]
    assert out["left_out"] == 2
    coal = _rows(db, "Coal mill")
    assert list(coal.columns) == ["Unit", "Hours", "Status"]  # the dataset column is left out
    assert list(coal["Unit"]) == ["M-1", "M-2", "M-3"]
    assert list(coal["Hours"]) == [300, 450, 610]
    # Each stands alone, stored as its rows: no column reading is kept (that's
    # chosen when fitting), so a fit from it starts from a fresh guess.
    detail = client.get(f"/api/datasets/{out['datasets'][1]['id']}").json()
    assert detail["last_mapping"] is None and detail["last_recurrent_mapping"] is None
    doc = db.datasets.find_one({"name": "Coal mill"})
    assert "reading" not in doc and "dataset" not in str(doc.keys())


def test_without_dataset_col_nothing_changes(web):
    client, db = web
    r = _upload(client, {"name": "plant"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "plant" and body["n_rows"] == 8
    assert "datasets" not in body and body["last_mapping"] is None
    assert db.datasets.count_documents({"owner_id": U}) == 1
    # An empty dataset_col is no split either.
    r = _upload(client, {"name": "again", "dataset_col": " "}, sheet=SHEET + "Y-1,Pump,5,Failed\n")
    assert r.status_code == 200 and r.json()["name"] == "again"


def test_split_past_the_cap_saves_nothing_and_says_how_many_fit(web):
    client, db = web
    for i in range(3):
        db.datasets.insert_one({"_id": f"d{i}", "name": f"d{i}", "owner_id": U, "checksum": f"c{i}"})
    r = _upload(client, {"name": "plant", "dataset_col": "Equipment"})
    assert r.status_code == 402
    body = r.json()
    assert body["code"] == "cap"
    assert "This would save 3 datasets" in body["detail"] and "only 2 more fit" in body["detail"]
    assert db.datasets.count_documents({"owner_id": U}) == 3
    # Room for all three: saved. Again: the same data comes back, and costs no room.
    db.datasets.delete_one({"_id": "d0"})
    assert _upload(client, {"name": "plant", "dataset_col": "Equipment"}).status_code == 200
    again = _upload(client, {"name": "plant", "dataset_col": "Equipment"})
    assert again.status_code == 200
    assert all(d.get("reused") for d in again.json()["datasets"])
    assert db.datasets.count_documents({"owner_id": U}) == 5


def test_split_on_a_missing_column_is_refused(web):
    client, _ = web
    r = _upload(client, {"name": "plant", "dataset_col": "Site"})
    assert r.status_code == 422
    assert "no column “Site”" in r.json()["detail"]


def test_mcp_dataset_upload_takes_dataset_col(env):
    out = _ok(_call(env.token[A], "change", {"action": "dataset_upload", "name": "plant", "csv": SHEET,
                                             "dataset_col": "Equipment"}))
    assert [(d["name"], d["n_rows"]) for d in out["datasets"]] == [
        ("Transformer", 2), ("Coal mill", 3), ("Boiler feed pump", 1)]
    assert out["columns"] == ["Unit", "Hours", "Status"]
    assert out["left_out"] == "2 rows with no Equipment left out."
    # Without it, one dataset as before.
    one = _ok(_call(env.token[A], "change", {"action": "dataset_upload", "name": "plant", "csv": SHEET}))
    assert one["name"] == "plant" and "datasets" not in one
    bad = _err(_call(env.token[A], "change", {"action": "dataset_upload", "name": "p", "csv": SHEET,
                                              "dataset_col": "Site"}))
    assert "no column “Site”" in bad


def test_mcp_split_respects_the_cap(plans, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 2)
    msg = _err(_call(plans.oauth[FREE], "change", {"action": "dataset_upload", "name": "plant", "csv": SHEET,
                                                   "dataset_col": "Equipment"}))
    assert "would save 3" in msg and "nothing was saved" in msg
    assert plans.db.datasets.count_documents({"owner_id": FREE}) == 0
