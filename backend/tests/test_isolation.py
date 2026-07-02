"""Per-user data isolation: one user must never see/touch another's data."""

import io

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def session(monkeypatch):
    import mongomock

    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _csv() -> bytes:
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"time": np.round(rng.weibull(2.0, 80) * 100, 2)})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


A = "user-a"
B = "user-b"


def test_datasets_and_models_are_owner_scoped(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "a.csv", _csv(), A)
    model = ms.save_model(session, "A's model", d, "weibull", {"x": "time"}, [], None, owner_id=A)

    # user-b sees nothing and can't fetch user-a's records.
    assert ds.list_datasets(session, B) == []
    assert ms.list_models(session, B) == []
    assert ds.get_dataset(session, d.id, B) is None
    assert ms.get_model(session, model.id, B) is None

    # ...nor mutate them.
    with pytest.raises(ms.ModelNotFound):
        ms.rename_model(session, model.id, "hijacked", B)
    with pytest.raises(ms.ModelNotFound):
        ms.delete_model(session, model.id, B)
    assert ds.delete_dataset(session, d.id, B) is False

    # user-a still has everything intact.
    assert [m.id for m in ms.list_models(session, A)] == [model.id]
    assert ds.get_dataset(session, d.id, A) is not None


def test_dataset_dedup_is_per_owner(session):
    from backend.services import datasets as ds

    data = _csv()
    da = ds.create_dataset(session, "shared.csv", data, A)
    db_ = ds.create_dataset(session, "shared.csv", data, B)
    # Same bytes, different owners -> separate datasets.
    assert da.id != db_.id
    assert da.owner_id == A and db_.owner_id == B


def test_rbd_cannot_embed_another_users_model(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "a.csv", _csv(), A)
    model = ms.save_model(session, "A's model", d, "weibull", {"x": "time"}, [], None, owner_id=A)

    # user-b resolving user-a's model id must get nothing (node treated as
    # missing) — it returns None *before* reaching the re-fit path, so a foreign
    # id can never surface another user's data.
    assert ms.get_live_model(session, model.id, B) is None


def test_api_requires_auth_and_isolates(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)

    # No credentials -> 401 (so the SPA redirects to /login).
    assert client.get("/api/models").status_code == 401
    assert client.get("/api/datasets").status_code == 401
    assert client.get("/api/rbds").status_code == 401
    # Public endpoints stay open.
    assert client.get("/api/health").status_code == 200

    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": "user-a", "email": "a", "name": "A"}
        r = client.post("/api/datasets", files={"file": ("d.csv", _csv(), "text/csv")}, data={"name": "d.csv"})
        assert r.status_code == 200
        assert len(client.get("/api/datasets").json()["datasets"]) == 1

        app.dependency_overrides[get_current_user] = lambda: {"uid": "user-b", "email": "b", "name": "B"}
        assert client.get("/api/datasets").json()["datasets"] == []
        assert client.get("/api/models").json()["models"] == []
    finally:
        app.dependency_overrides.clear()


def test_auth_disabled_returns_dev_user(monkeypatch):
    from backend import auth, config

    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    user = auth.get_current_user(authorization=None)
    assert user["uid"] == config.DEV_USER_ID


def test_missing_token_is_401(monkeypatch):
    from fastapi import HTTPException

    from backend import auth, config

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(authorization=None)
    assert exc.value.status_code == 401
