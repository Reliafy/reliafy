"""The dataset page's "Show all rows": a window of a saved dataset's rows."""

import mongomock
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "rows-owner", "email": "o@x.org", "name": "o"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _upload(client, n=25):
    lines = ["tag,hours,status,note"] + [f"SP-{100 + i},{1000 + 10 * i},{'Failed' if i % 2 else 'Running'},{'' if i % 3 else 'x'}"
                                         for i in range(n)]
    res = client.post("/api/datasets", files={"file": ("seals.csv", ("\n".join(lines) + "\n").encode(), "text/csv")},
                      data={"name": "Seals"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_rows_come_in_windows_with_the_row_count(client):
    ds = _upload(client, 25)
    first = client.get(f"/api/datasets/{ds}/rows?limit=10").json()
    assert first["columns"] == ["tag", "hours", "status", "note"]
    assert first["n_rows"] == 25 and first["offset"] == 0 and len(first["rows"]) == 10
    assert first["rows"][0][:3] == ["SP-100", 1000, "Running"]
    second = client.get(f"/api/datasets/{ds}/rows?offset=10&limit=10").json()
    assert second["rows"][0][0] == "SP-110"
    last = client.get(f"/api/datasets/{ds}/rows?offset=20&limit=10").json()
    assert len(last["rows"]) == 5 and last["rows"][-1][0] == "SP-124"


def test_blank_cells_are_null_and_a_window_past_the_end_is_empty(client):
    ds = _upload(client, 6)
    rows = client.get(f"/api/datasets/{ds}/rows").json()["rows"]
    assert rows[1][3] is None  # a blank note
    assert client.get(f"/api/datasets/{ds}/rows?offset=50").json()["rows"] == []


def test_rows_refuse_a_bad_window_and_an_unknown_dataset(client):
    ds = _upload(client, 3)
    assert client.get(f"/api/datasets/{ds}/rows?limit=0").status_code == 422
    assert client.get(f"/api/datasets/{ds}/rows?limit=5000").status_code == 422
    assert client.get(f"/api/datasets/{ds}/rows?offset=-1").status_code == 422
    assert client.get("/api/datasets/nope/rows").status_code == 404


def test_the_measurements_part_asked_for_but_absent_gives_the_one_table(client):
    ds = _upload(client, 4)
    out = client.get(f"/api/datasets/{ds}/rows?part=measurements").json()
    assert out["part"] == "life" and out["n_rows"] == 4
