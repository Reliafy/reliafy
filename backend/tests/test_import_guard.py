"""One import at a time per user, within a time budget."""

import mongomock
import pytest

from backend.services import import_guard
from backend.services.rbd_import import galileo
from backend.tests.test_excel_limits import _sheet
from backend.tests.test_fault_tree_size import _doubling_galileo
from backend.tests.test_rbd_analysis import _edge, _io_nodes


def _elsewhere(db, uid):
    """Try the guard from another request (thread): what it raised, or None."""
    import threading

    out = []

    def run():
        try:
            with import_guard.guard(db, uid, wait=0):
                pass
            out.append(None)
        except Exception as exc:  # noqa: BLE001
            out.append(exc)

    t = threading.Thread(target=run)
    t.start()
    t.join()
    return out[0]


def test_import_guard_allows_one_import_per_user():
    db = mongomock.MongoClient()["guard"]
    with import_guard.guard(db, "u1"):
        assert isinstance(_elsewhere(db, "u1"), import_guard.ImportBusy)
        assert _elsewhere(db, "u2") is None
        with import_guard.guard(db, "u1", wait=0):  # re-entrant in the same call
            pass
    with import_guard.guard(db, "u1", wait=0):  # released
        pass
    assert db.import_locks.count_documents({}) == 0


def test_import_guard_takes_over_an_expired_lease():
    from datetime import datetime, timedelta, timezone

    db = mongomock.MongoClient()["guard"]
    db.import_locks.insert_one({"_id": "u1", "nonce": "old",
                                "until": datetime.now(timezone.utc) - timedelta(seconds=1)})
    with import_guard.guard(db, "u1", wait=0):
        assert db.import_locks.find_one({"_id": "u1"})["nonce"] != "old"


def test_import_guard_budget_stops_parsing():
    db = mongomock.MongoClient()["guard"]
    import_guard.check()  # no budget outside a guard
    with pytest.raises(import_guard.ImportBudgetExceeded):
        with import_guard.guard(db, "u1", budget=0):
            galileo.parse(_doubling_galileo(3), "x.dft")
    import_guard.check()
    assert db.import_locks.count_documents({}) == 0


@pytest.fixture()
def web(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_limits"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(import_guard, "WAIT_SECONDS", 0.0)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "web-user", "email": "w@example.org",
                                                          "name": "W"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _galileo_text() -> bytes:
    return b'toplevel "S";\n"S" or "A" "B";\n"A" lambda=1e-3;\n"B" lambda=2e-3;\n'


def test_web_import_waits_its_turn(web):
    from datetime import datetime, timedelta, timezone

    files = {"file": ("plant.dft", _galileo_text(), "application/octet-stream")}
    assert web.post("/api/rbds/import", files=files).status_code == 200
    web.db.import_locks.insert_one({"_id": "web-user", "nonce": "busy",
                                    "until": datetime.now(timezone.utc) + timedelta(minutes=1)})
    r = web.post("/api/rbds/import", files=files)
    assert r.status_code == 429 and "Another import" in r.json()["detail"]
    r = web.post("/api/excel/inspect", files={"file": ("a.xlsx", _sheet(3), "application/octet-stream")})
    assert r.status_code == 429


def test_web_import_over_budget_is_refused(web, monkeypatch):
    monkeypatch.setattr(import_guard, "BUDGET_SECONDS", 0.0)
    r = web.post("/api/rbds/import", files={"file": ("plant.dft", _galileo_text(), "application/octet-stream")})
    assert r.status_code == 422 and "too long to read" in r.json()["detail"]
    assert web.db.import_locks.count_documents({}) == 0


def test_saving_over_the_limits_is_refused_on_the_web(web):
    graph = {"nodes": _io_nodes() + [{"id": "a", "type": "series", "data": {"label": "A", "n": 10 ** 9}}],
             "edges": [_edge("input", "a"), _edge("a", "output")]}
    r = web.post("/api/rbds", json={"name": "D", "graph": graph})
    assert r.status_code == 422 and "from 1 to 1,000" in r.json()["detail"]
