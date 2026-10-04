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


def test_a_file_without_a_time_unit_says_so_and_one_that_states_it_keeps_it(client):
    """#187: the web import and import_rbd settle the unit the same way
    (rbd_import.apply_time_unit) — never a silent blank."""
    dft = b'toplevel "S"; "S" or "A" "B"; "A" lambda=1e-4; "B" lambda=2e-4;'
    (d,) = _post(client, dft, "plant.dft").json()["diagrams"]
    assert d["graph"]["unit"] == ""
    assert d["warnings"][0] == rbd_import.UNIT_MISSING

    xml = (b'<opsa-mef><define-gate name="T"><or><basic-event name="A"/><basic-event name="B"/></or>'
           b'</define-gate><define-parameter name="lam" unit="hours-1"><float value="1e-4"/></define-parameter>'
           + b"".join(f'<define-basic-event name="{n}"><exponential><parameter name="lam"/>'
                      f'<system-mission-time/></exponential></define-basic-event>'.encode() for n in "AB")
           + b"</opsa-mef>")
    (d,) = _post(client, xml, "plant.xml").json()["diagrams"]
    assert d["graph"]["unit"] == "hours"
    assert not any("time unit" in w for w in d["warnings"])


def test_apply_time_unit_prefers_the_file_then_the_caller():
    def diagram(unit):
        return ImportedDiagram("D", {"nodes": [], "edges": [], "unit": unit})

    stated, given, neither = diagram("Cycles"), diagram(""), diagram("")
    rbd_import.apply_time_unit([stated], "Hours")
    rbd_import.apply_time_unit([given], " Hours ")
    rbd_import.apply_time_unit([neither], None)
    assert stated.graph["unit"] == "Cycles" and "“Hours” was ignored" in stated.warnings[0]
    assert given.graph["unit"] == "Hours" and "read as per Hours" in given.warnings[0]
    assert neither.graph["unit"] == "" and neither.warnings == [rbd_import.UNIT_MISSING]
