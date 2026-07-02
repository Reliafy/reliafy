import io

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest

OWNER = "user-a"  # data is scoped per owner; tests use one owner unless noted


@pytest.fixture()
def session(monkeypatch):
    # Use a fresh in-memory MongoDB simulator as the database, and point the
    # module-level handle at it so re-fit-on-demand (which calls get_db()) hits
    # the same instance.
    import mongomock

    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _covariate_csv() -> bytes:
    from surpyval import Weibull

    rng = np.random.default_rng(5)
    n = 120
    age = rng.normal(50, 10, n)
    sex = rng.choice(["M", "F"], n)
    beta = 0.04 * (age - 50) + np.where(sex == "M", 0.5, 0.0)
    x = Weibull.random(n, 12, 2.0) * np.exp(-beta / 2)
    df = pd.DataFrame(
        {"time": np.round(x, 3), "age": np.round(age, 1), "sex": sex,
         "censored": np.zeros(n, dtype=int)}
    )
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_dataset_dedup_by_checksum(session):
    from backend.services import datasets as ds

    data = _covariate_csv()
    d1 = ds.create_dataset(session, "a.csv", data, OWNER)
    d2 = ds.create_dataset(session, "b.csv", data, OWNER)
    assert d1.id == d2.id  # same content + owner -> same dataset
    assert d1.n_rows == 120


def test_save_list_reopen_distribution(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "data.csv", _covariate_csv(), OWNER)
    model = ms.save_model(session, "W", d, "weibull", {"x": "time"}, [], None, owner_id=OWNER)

    assert model.kind == "distribution"
    assert [m.id for m in ms.list_models(session, OWNER)] == [model.id]

    reopened = ms.get_model(session, model.id, OWNER)
    results = ms.public_results(reopened)
    assert {p["name"] for p in results["params"]} == {"alpha", "beta"}
    assert "plot" in results


def test_unit_and_surpyval_version_saved(session):
    from backend.routers.models import _model_detail
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "data.csv", _covariate_csv(), OWNER)
    model = ms.save_model(
        session, "W", d, "weibull", {"x": "time"}, [], None, "Cycles", owner_id=OWNER
    )
    # Persisted on the row and in the spec/results.
    assert model.surpyval_version  # e.g. "0.11.1"
    assert model.spec["unit"] == "Cycles"
    assert model.results["unit"] == "Cycles"
    # And surfaced by the API shaping.
    detail = _model_detail(model)
    assert detail["unit"] == "Cycles"
    assert detail["surpyval_version"] == model.surpyval_version


def test_save_and_evaluate_regression(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "data.csv", _covariate_csv(), OWNER)
    model = ms.save_model(
        session, "PH", d, "weibull_ph", {"x": "time", "c": "censored"}, [], "age + sex",
        owner_id=OWNER,
    )
    assert model.kind == "regression"

    results = ms.public_results(model)
    assert results["functions"]["evaluate_path"].endswith(f"/{model.id}/evaluate")

    # Re-fit-on-demand evaluation reflects the covariate values.
    mid = 150
    high = ms.evaluate(session, model.id, {"age": 70, "sex": "M"}, OWNER)["curves"]["sf"]
    low = ms.evaluate(session, model.id, {"age": 30, "sex": "F"}, OWNER)["curves"]["sf"]
    assert high[mid] < low[mid]


def test_rename_and_delete(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "data.csv", _covariate_csv(), OWNER)
    model = ms.save_model(session, "old", d, "weibull", {"x": "time"}, [], None, owner_id=OWNER)

    renamed = ms.rename_model(session, model.id, "new", OWNER)
    assert renamed.name == "new"

    ms.delete_model(session, model.id, OWNER)
    assert ms.get_model(session, model.id, OWNER) is None
    with pytest.raises(ms.ModelNotFound):
        ms.rename_model(session, model.id, "x", OWNER)
