"""POST /api/rbds/import: parse only (nothing saved), user-facing errors as 422,
never a 500 on a malformed file, and graphs come back builder-ready."""

import mongomock
import pytest

from backend.services import rbd_import
from backend.services.rbd_import import ImportedDiagram, RbdImportError

USER = {"uid": "user-import", "email": "import@example.org", "name": "Importer"}

COMPACT = {
    "nodes": [
        {"id": "input", "type": "input"},
        {"id": "a", "type": "component", "label": "Pump A",
         "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]}},
        {"id": "b", "type": "component", "label": "Pump B",
         "model": {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]}},
        {"id": "output", "type": "output"},
    ],
    "edges": [
        {"source": "input", "target": "a"}, {"source": "input", "target": "b"},
        {"source": "a", "target": "output"}, {"source": "b", "target": "output"},
    ],
    "unit": "Hours",
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USER
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _post(client, data=b"x", name="plant.dft"):
    return client.post("/api/rbds/import", files={"file": (name, data, "application/octet-stream")})


def test_import_returns_normalized_graph_and_saves_nothing(client, monkeypatch):
    monkeypatch.setattr(
        rbd_import, "import_file",
        lambda data, filename: [ImportedDiagram("Plant", COMPACT, ["note"], "Galileo DFT")],
    )
    r = _post(client)
    assert r.status_code == 200
    (d,) = r.json()["diagrams"]
    assert d["name"] == "Plant" and d["source_format"] == "Galileo DFT"
    assert d["warnings"] == ["note"]
    assert d["n_nodes"] == 4 and d["n_edges"] == 4
    nodes = {n["id"]: n for n in d["graph"]["nodes"]}
    assert nodes["a"]["data"]["model"]["distribution"] == "Exponential"
    assert all("position" in n for n in d["graph"]["nodes"])
    assert client.db.rbds.count_documents({}) == 0


def test_import_error_is_422_with_message(client, monkeypatch):
    def refuse(data, filename):
        raise RbdImportError("PAND gates have no block-diagram equivalent.")

    monkeypatch.setattr(rbd_import, "import_file", refuse)
    r = _post(client)
    assert r.status_code == 422
    assert "PAND" in r.json()["detail"]


def test_unexpected_parser_crash_is_422_not_500(client, monkeypatch):
    def boom(data, filename):
        raise KeyError("bsFolioRBD")

    monkeypatch.setattr(rbd_import, "import_file", boom)
    r = _post(client)
    assert r.status_code == 422
    assert "Couldn't read this file" in r.json()["detail"]


def test_bad_graph_is_reported_per_diagram(client, monkeypatch):
    bad = {"nodes": [{"id": "x", "type": "gizmo"}], "edges": []}
    monkeypatch.setattr(
        rbd_import, "import_file",
        lambda data, filename: [ImportedDiagram("Good", COMPACT), ImportedDiagram("Bad", bad)],
    )
    r = _post(client)
    assert r.status_code == 200
    good, badd = r.json()["diagrams"]
    assert "graph" in good
    assert "graph" not in badd and "type must be one of" in badd["error"]


def test_unrecognised_file_is_rejected(client):
    r = _post(client, b"hello, not a diagram", "notes.txt")
    assert r.status_code == 422
    assert "Unrecognised file" in r.json()["detail"]


def test_empty_file_is_rejected(client):
    r = _post(client, b"", "empty.dft")
    assert r.status_code == 422
    assert "empty" in r.json()["detail"]
