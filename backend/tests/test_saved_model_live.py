"""A saved model's calculator answers from the fit that was just saved.

Straight after a save, the calculator's first requests (a curve at the
covariates typed, its bounds, a time at a reliability) arrive together. Each
used to fit the model again from its dataset before answering, so the page
showed the earlier curve beside the new covariate values for as long as that
took. The save's own fit is now the saved model's live one, and a model that
does need bringing back is brought back once.
"""

import io
import threading

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.services import datasets as datasets_service
from backend.services import models as models_service

OWNER = "user-a"


def _csv():
    rng = np.random.default_rng(7)
    temp = np.repeat([60.0, 80.0, 100.0], 12)
    load = np.tile([0.5, 0.7, 0.9], 12)
    hours = 4000 * np.exp(-0.04 * (temp - 60) - 2.0 * (load - 0.5)) * rng.weibull(2.5, size=36)
    df = pd.DataFrame({"hours": hours.round(1), "censored": 0, "temp_C": temp, "load": load})
    return df.to_csv(index=False).encode()


@pytest.fixture()
def saved(monkeypatch):
    from backend import db as db_module

    db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db_module, "_db", db)
    monkeypatch.setattr(db_module, "_simulated", True)
    dataset = datasets_service.create_dataset(db, "seals.csv", _csv(), OWNER)
    model = models_service.save_model(db, "Seals", dataset, "weibull_ph", {"x": "hours", "c": "censored"},
                                      ["temp_C", "load"], None, "hours", owner_id=OWNER)
    return db, model


def test_the_saved_fit_is_the_live_model(saved, monkeypatch):
    db, model = saved
    refits = []
    monkeypatch.setattr(models_service, "_refit", lambda m: refits.append(m.id) or pytest.fail("fitted again"))
    at = models_service.evaluate(db, model.id, {"temp_C": "80", "load": "0.5"}, OWNER)
    default = models_service.evaluate(db, model.id, {}, OWNER)
    assert refits == []
    # The curve follows the covariates given, typed as text or as numbers.
    assert at["curves"]["sf"] != default["curves"]["sf"]
    assert at["curves"]["sf"] == models_service.evaluate(db, model.id, {"temp_C": 80, "load": 0.5}, OWNER)["curves"]["sf"]


def test_a_model_is_brought_back_once_for_requests_that_arrive_together(saved, monkeypatch):
    db, model = saved
    models_service._LIVE.pop(model.id, None)  # as after a restart
    real, calls, gate = models_service._refit, [], threading.Event()

    def slow_refit(m):
        calls.append(m.id)
        gate.wait(5)
        return real(m)

    monkeypatch.setattr(models_service, "_refit", slow_refit)
    out = []
    threads = [threading.Thread(target=lambda: out.append(models_service._live_cache_id(db, model.id, OWNER)))
               for _ in range(4)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(30)
    assert len(calls) == 1
    assert len(set(out)) == 1 and out[0] in fitting._MODEL_STORE
