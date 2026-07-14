"""Shared sample content: visible to everyone, "deletable" per-user only."""

import matplotlib

matplotlib.use("Agg")

import pytest


@pytest.fixture()
def session(monkeypatch):
    import mongomock

    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


A = "user-a"
B = "user-b"


def test_seed_is_idempotent_and_shared(session):
    from backend.services import datasets as ds
    from backend.services import models as ms
    from backend.services import samples

    samples.seed_samples(session)
    samples.seed_samples(session)  # second run must not duplicate

    assert session.datasets.count_documents({}) == len(samples.SAMPLE_DATASETS)
    assert session.models.count_documents({}) == len(samples.SAMPLE_MODELS)
    assert session.rbds.count_documents({}) == len(samples.SAMPLE_RBDS)

    # Every user sees the same samples without anything copied per-user.
    assert {d.id for d in ds.list_datasets(session, A)} == {
        s["id"] for s in samples.SAMPLE_DATASETS
    }
    assert {m.id for m in ms.list_models(session, B)} == {
        s["id"] for s in samples.SAMPLE_MODELS
    }
    # They carry the shared owner, not the requesting user.
    assert all(samples.is_sample(d.owner_id) for d in ds.list_datasets(session, A))


def test_remove_all_then_restore_all(session):
    from backend.services import datasets as ds
    from backend.services import models as ms
    from backend.services import samples

    samples.seed_samples(session)

    # Remove-all hides every sample across collections for A only.
    n = samples.hide_all_samples(session, A)
    assert n == len(samples.all_sample_ids(session)) > 0
    hidden_a = samples.hidden_sample_ids(session, A)
    assert ds.list_datasets(session, A, hidden_a) == []
    assert ms.list_models(session, A, hidden_a) == []
    # B is untouched — still sees all samples.
    assert len(ms.list_models(session, B)) == len(samples.SAMPLE_MODELS)

    # Restore clears the hide list, bringing them all back for A.
    session.users.update_one({"_id": A}, {"$set": {"hidden_samples": []}})
    hidden_a = samples.hidden_sample_ids(session, A)
    assert len(ds.list_datasets(session, A, hidden_a)) == len(samples.SAMPLE_DATASETS)


def test_hiding_a_sample_is_per_user(session):
    from backend.services import datasets as ds
    from backend.services import models as ms
    from backend.services import samples

    samples.seed_samples(session)
    sample_model = samples.SAMPLE_MODELS[0]["id"]
    sample_dataset = samples.SAMPLE_DATASETS[1]["id"]

    samples.hide_sample(session, A, sample_model)
    samples.hide_sample(session, A, sample_dataset)
    hidden_a = samples.hidden_sample_ids(session, A)

    # Gone for A...
    assert sample_model not in {m.id for m in ms.list_models(session, A, hidden_a)}
    assert sample_dataset not in {d.id for d in ds.list_datasets(session, A, hidden_a)}
    # ...still there for B, and the shared docs are untouched.
    assert sample_model in {m.id for m in ms.list_models(session, B)}
    assert sample_dataset in {d.id for d in ds.list_datasets(session, B)}
    assert session.models.find_one({"_id": sample_model}) is not None


def test_sample_rbd_is_shared_analysable_and_hideable(session):
    from backend.services import rbds as rs
    from backend.services import samples

    samples.seed_samples(session)
    sample_rbd = samples.SAMPLE_RBDS[0]["id"]

    # Stored once, shared with every user, and a valid/analysable diagram.
    assert session.rbds.count_documents({}) == 1
    assert sample_rbd in {r.id for r in rs.list_rbds(session, A)}
    assert sample_rbd in {r.id for r in rs.list_rbds(session, B)}
    assert rs.validate_rbd(session, sample_rbd, A)["valid"] is True
    assert rs.analyze_rbd(session, sample_rbd, A)["mttf"] > 0

    # Hiding it for A leaves B (and the shared doc) untouched.
    samples.hide_sample(session, A, sample_rbd)
    hidden_a = samples.hidden_sample_ids(session, A)
    assert sample_rbd not in {r.id for r in rs.list_rbds(session, A, hidden_a)}
    assert sample_rbd in {r.id for r in rs.list_rbds(session, B)}
    assert session.rbds.find_one({"_id": sample_rbd}) is not None


def test_samples_are_read_only(session):
    from backend.services import models as ms
    from backend.services import samples

    samples.seed_samples(session)
    sid = samples.SAMPLE_MODELS[0]["id"]

    # A user can fetch a sample but can neither rename nor hard-delete it.
    assert ms.get_model(session, sid, A) is not None
    with pytest.raises(ms.ModelNotFound):
        ms.rename_model(session, sid, "mine now", A)
    with pytest.raises(ms.ModelNotFound):
        ms.delete_model(session, sid, A)
    assert session.models.find_one({"_id": sid}) is not None


def test_api_serves_and_hides_samples(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)

    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a", "name": "A"}
        models = client.get("/api/models").json()["models"]
        assert len(models) == len(samples.SAMPLE_MODELS)
        assert all(m["is_sample"] for m in models)

        victim = models[0]["id"]
        # "Delete" hides it for A but leaves the shared doc in place.
        assert client.delete(f"/api/models/{victim}").status_code == 200
        assert victim not in {m["id"] for m in client.get("/api/models").json()["models"]}
        assert test_db.models.find_one({"_id": victim}) is not None

        # Renaming a sample is refused.
        survivor = models[1]["id"]
        assert client.patch(f"/api/models/{survivor}", json={"name": "x"}).status_code == 403

        # RBDs follow the same rules: served with a flag, "delete" hides.
        rbds = client.get("/api/rbds").json()["rbds"]
        assert len(rbds) == len(samples.SAMPLE_RBDS)
        assert all(r["is_sample"] for r in rbds)
        rbd_id = rbds[0]["id"]
        assert client.delete(f"/api/rbds/{rbd_id}").status_code == 200
        assert rbd_id not in {r["id"] for r in client.get("/api/rbds").json()["rbds"]}
        assert test_db.rbds.find_one({"_id": rbd_id}) is not None

        # User B still sees every sample, including the ones A hid.
        app.dependency_overrides[get_current_user] = lambda: {"uid": B, "email": "b", "name": "B"}
        b_models = {m["id"] for m in client.get("/api/models").json()["models"]}
        assert victim in b_models
        assert len(b_models) == len(samples.SAMPLE_MODELS)
        b_rbds = {r["id"] for r in client.get("/api/rbds").json()["rbds"]}
        assert rbd_id in b_rbds
    finally:
        app.dependency_overrides.clear()
