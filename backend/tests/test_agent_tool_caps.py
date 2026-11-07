"""The in-app assistant's create tools obey the same Free-plan storage caps as
the web app and MCP: at the cap on Free the tool returns the refusal as a
result the assistant can relay (never an exception); Pro, operators and
shared samples are unaffected."""

from __future__ import annotations

import mongomock
import pytest

from backend import config
from backend.tests.test_reliability_agent import (
    _alt_csv, _csv, _degradation_csv, _recurrent_csv)

FREE, PRO, OP = "cap-free", "cap-pro", "cap-op"

RBD = {"name": "R", "stages": [{"label": "S", "components": [
    {"label": "A", "distribution": "weibull",
     "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]}]}]}


def _msg(n, kind):
    many = kind if n != 1 else kind + "s"
    return (f"You've reached the free-plan limit of {n} {kind}. Upgrade to Pro for unlimited "
            f"{many.removeprefix('saved ')}.")


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@example.org"})
    d = mongomock.MongoClient()["agent_caps"]
    d.users.insert_many([
        {"_id": FREE, "email": "free@example.org", "email_verified": True},
        {"_id": PRO, "email": "pro@example.org", "email_verified": True, "plan": "pro"},
        {"_id": OP, "email": "op@example.org", "email_verified": True},
    ])
    return d


def _fill(db, uid, coll, n):
    db[coll].insert_many([{"_id": f"{uid}-{coll}-{i}", "owner_id": uid} for i in range(n)])


def _run(db, uid, name, inp):
    from backend.services import reliability_agent as agent
    return agent._execute_tool(db, uid, name, inp)


def _dataset(db, uid, csv):
    return _run(db, uid, "create_dataset", {"name": "d", "csv": csv})["dataset_id"]


# (tool, collection filled, kind noun, cap, input builder)
def _inputs(ds_id):
    return {
        "create_life_model": {"name": "m", "dataset_id": ds_id, "distribution": "weibull",
                              "time_column": "hours"},
        "create_recurrent_model": {"name": "m", "dataset_id": ds_id, "system_column": "system",
                                   "time_column": "hours", "censored_column": "censored"},
        "create_alt_model": {"name": "m", "dataset_id": ds_id, "time_column": "minutes",
                             "stress_columns": ["kV"], "life_model": "inverse_power"},
        "create_degradation_model": {"name": "m", "dataset_id": ds_id, "item_column": "unit",
                                     "time_column": "hours", "measurement_column": "wear_mm",
                                     "threshold": 8.0, "path": "linear"},
    }


CSVS = {"create_life_model": _csv(), "create_recurrent_model": _recurrent_csv(),
        "create_alt_model": _alt_csv(), "create_degradation_model": _degradation_csv()}


def test_dataset_refused_at_cap_on_free(db):
    _fill(db, FREE, "datasets", config.FREE_MAX_DATASETS)
    res = _run(db, FREE, "create_dataset", {"name": "x", "csv": _csv()})
    assert res["error"].startswith(_msg(config.FREE_MAX_DATASETS, "saved datasets"))
    assert "/billing" in res["error"]
    assert db.datasets.count_documents({"owner_id": FREE}) == config.FREE_MAX_DATASETS


@pytest.mark.parametrize("tool", list(CSVS))
def test_model_tools_refused_at_cap_on_free_but_pro_allowed(db, tool):
    cap = config.FREE_MAX_MODELS
    ds = _dataset(db, FREE, CSVS[tool])  # below the dataset cap
    if tool == "create_degradation_model":
        coll, noun, cap = "degradation_models", "degradation model", config.FREE_MAX_DEGRADATION_MODELS
    else:
        coll, noun = "models", "saved models"
    _fill(db, FREE, coll, cap)
    res = _run(db, FREE, tool, _inputs(ds)[tool])
    assert res["error"].startswith(_msg(cap, noun)), res
    assert "/billing" in res["error"]

    pro_ds = _dataset(db, PRO, CSVS[tool])
    _fill(db, PRO, coll, cap + 5)
    ok = _run(db, PRO, tool, _inputs(pro_ds)[tool])
    assert ok.get("ok"), ok


def test_every_model_kind_counts_toward_the_one_models_cap(db):
    """Three saved models of other kinds fill the cap for the recurrent tool."""
    ds = _dataset(db, FREE, _recurrent_csv())
    _fill(db, FREE, "alt_models", 2)
    _fill(db, FREE, "recurrent_models", 1)
    res = _run(db, FREE, "create_recurrent_model", _inputs(ds)["create_recurrent_model"])
    assert res["error"].startswith(_msg(config.FREE_MAX_MODELS, "saved models"))


def test_rbd_refused_at_cap_on_free_but_pro_allowed(db):
    _fill(db, FREE, "rbds", config.FREE_MAX_RBDS)
    res = _run(db, FREE, "create_rbd", RBD)
    assert res["error"].startswith(_msg(config.FREE_MAX_RBDS, "saved RBD"))
    _fill(db, PRO, "rbds", config.FREE_MAX_RBDS + 3)
    assert _run(db, PRO, "create_rbd", RBD).get("ok")


def test_samples_never_count_and_operators_are_exempt(db):
    # Shared samples are owned by nobody: they don't use up the user's room.
    db.models.insert_many([{"_id": f"s{i}", "owner_id": None, "sample": True} for i in range(5)])
    db.rbds.insert_one({"_id": "sr", "owner_id": None, "sample": True})
    assert _run(db, FREE, "create_rbd", RBD).get("ok")
    # An operator past every cap is still allowed.
    _fill(db, OP, "rbds", config.FREE_MAX_RBDS + 2)
    assert _run(db, OP, "create_rbd", RBD).get("ok")


def test_billing_off_has_no_caps(db, monkeypatch):
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    _fill(db, FREE, "rbds", config.FREE_MAX_RBDS + 2)
    assert _run(db, FREE, "create_rbd", RBD).get("ok")
