"""The MongoDB connection should use a reachable cluster, and otherwise fall
back to the in-memory simulator."""

import pytest


@pytest.fixture(autouse=True)
def _reset_db(monkeypatch):
    from backend import db

    monkeypatch.setattr(db, "_db", None)
    monkeypatch.setattr(db, "_simulated", False)
    yield
    db._db = None
    db._simulated = False


def test_uses_real_client_when_reachable(monkeypatch):
    import pymongo

    from backend import config, db

    class _Admin:
        def command(self, *a, **k):
            return {"ok": 1}

    class _Client:
        def __init__(self, uri, **kw):
            self.admin = _Admin()

        def __getitem__(self, name):
            return {"_name": name}

    monkeypatch.setattr(pymongo, "MongoClient", _Client)
    monkeypatch.setattr(config, "MONGODB_URI", "mongodb+srv://u:p@reachable.example/db")

    handle = db.get_db()
    assert db.is_simulated() is False
    assert handle == {"_name": config.MONGODB_DB}


def test_refuses_simulator_when_uri_unreachable(monkeypatch):
    """With MONGODB_URI configured, an unreachable cluster is FATAL — silently
    serving an empty in-memory database would look like data loss."""
    import pymongo
    import pytest

    from backend import config, db

    class _Client:
        def __init__(self, uri, **kw):
            pass

        @property
        def admin(self):
            raise pymongo.errors.ServerSelectionTimeoutError("unreachable")

    monkeypatch.setattr(pymongo, "MongoClient", _Client)
    monkeypatch.setattr(config, "MONGODB_URI", "mongodb+srv://u:p@nope.example/db")

    with pytest.raises(RuntimeError, match="unreachable"):
        db.get_db()


def test_falls_back_to_simulator_when_no_uri(monkeypatch):
    import mongomock

    from backend import config, db

    monkeypatch.setattr(config, "MONGODB_URI", None)
    handle = db.get_db()
    assert db.is_simulated() is True
    assert isinstance(handle, mongomock.database.Database)
