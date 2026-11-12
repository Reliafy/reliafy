"""Fleet forecasts in bulk: items from the model's own data (the units still
running), a copy of a forecast for another scenario, and years and costs on
every kind of forecast (first failures and repairable as well as renewals)."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.tests.test_fleet import client  # noqa: E402,F401 - a fixture
from backend.tests.test_mcp import _call, _err, _ok, env  # noqa: E402,F401 - env is a fixture

A, B = "user-a", "user-b"


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _seal_csv(flag_failed_as_one=False) -> bytes:
    """20 seals: 12 failed, 8 still running, each with a pump name."""
    rng = np.random.default_rng(3)
    times = np.round(rng.weibull(2.5, 20) * 900, 1)
    failed = np.array([1] * 12 + [0] * 8)
    c = failed if flag_failed_as_one else 1 - failed
    df = pd.DataFrame({"Pump ID": [f"PU-{k:02d}" for k in range(20)], "Hours": times, "Status": c})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode(), times, failed


def _life_model(db, owner=A, options=None, flag_failed_as_one=False):
    from backend.services import datasets as ds
    from backend.services import models as ms

    data, times, failed = _seal_csv(flag_failed_as_one)
    dataset = ds.create_dataset(db, "seals.csv", data, owner)
    model = ms.save_model(db, "Seals", dataset, "weibull", {"x": "Hours", "c": "Status"}, [], None,
                          unit="hours", owner_id=owner, options=options)
    return model, times, failed


# ---- Items from the model's data --------------------------------------------------

def test_running_units_are_the_suspensions_with_their_names(session):
    from backend.services import fleet as fs
    from backend.services import fleet_items

    model, times, failed = _life_model(session)
    fleet = fs.create_fleet(session, "Seals", model.id, A)
    out = fleet_items.running_units(session, fleet, [A])
    running = np.flatnonzero(failed == 0)
    assert out["running"] == 8 and out["kind"] == "running" and out["unit"] == "Hours"
    assert [it["name"] for it in out["items"]] == [f"PU-{k:02d}" for k in running]
    assert [it["current_use"] for it in out["items"]] == pytest.approx(times[running])
    assert out["name_column"] == "Pump ID" and not out["skipped"]


def test_running_units_follow_the_fits_censor_reading(session):
    """A 1 = failed column, inverted at fit time, gives the same running units."""
    from backend.services import fleet as fs
    from backend.services import fleet_items

    model, times, failed = _life_model(session, options={"c_invert": True}, flag_failed_as_one=True)
    out = fleet_items.running_units(session, fs.create_fleet(session, "S", model.id, A), [A])
    assert out["running"] == 8
    assert [it["current_use"] for it in out["items"]] == pytest.approx(times[failed == 0])


def test_running_units_of_a_repairable_model_are_its_systems_at_their_record_end(session):
    from backend.services import datasets as ds
    from backend.services import fleet as fs
    from backend.services import fleet_items
    from backend.services import recurrent as rs

    df = pd.DataFrame({"truck": ["HT-1"] * 3 + ["HT-2"] * 2, "hours": [100, 250, 400, 80, 300],
                       "end": [500, 500, 500, 420, 420]})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    dataset = ds.create_dataset(session, "trucks.csv", buf.getvalue().encode(), A)
    doc = rs.save_model(session, "Trucks", dataset,
                        {"mapping": {"i": "truck", "x": "hours", "tr": "end"}, "model_id": "crow_amsaa",
                         "unit": "hours"}, A)
    fleet = fs.create_fleet(session, "Trucks", doc.id, A, "recurrent")
    out = fleet_items.running_units(session, fleet, [A])
    assert out["kind"] == "systems"
    assert {it["name"]: it["current_use"] for it in out["items"]} == {"HT-1": 500.0, "HT-2": 420.0}


def test_running_units_api_and_reasons(client):
    client.act_as(A)
    data, _times, _failed = _seal_csv()
    mid = client.post("/api/models", data={"name": "M", "distribution": "weibull", "x": "Hours", "c": "Status"},
                      files={"file": ("d.csv", data, "text/csv")}).json()["id"]
    fid = client.post("/api/fleet/fleets", json={"name": "F", "model_id": mid}).json()["id"]
    r = client.get(f"/api/fleet/fleets/{fid}/running-units")
    assert r.status_code == 200 and r.json()["running"] == 8
    # A model with no censoring column: nothing running, and it says why.
    plain = client.post("/api/models", data={"name": "P", "distribution": "weibull", "x": "Hours"},
                        files={"file": ("d.csv", data, "text/csv")}).json()["id"]
    pid = client.post("/api/fleet/fleets", json={"name": "P", "model_id": plain}).json()["id"]
    body = client.get(f"/api/fleet/fleets/{pid}/running-units").json()
    assert body["items"] == [] and "no censoring column" in body["reason"]
    client.act_as(B)
    assert client.get(f"/api/fleet/fleets/{fid}/running-units").status_code == 404


def test_mcp_forecast_from_the_model_data(env):
    model, _times, _failed = _life_model(env.db)
    from backend.services import fleet as fs

    fleet = fs.create_fleet(env.db, "Seals", model.id, A)
    fs.replace_items(env.db, fleet.id, {"periods": 12, "default_rate": 60, "method": "single"},
                     [{"name": "one", "current_use": 10}], A)
    out = _ok(_call(env.token[A], "analyse", {"action": "fleet_forecast", "fleet_id": fleet.id,
                                               "use_model_data": True, "include_items": True}))
    assert out["items_source"] == {"items": "model_data", "n_items": 8}
    assert len(out["forecast"]["per_item"]) == 8
    # Nothing saved: the fleet still has its one item.
    assert len(fs.get_fleet(env.db, fleet.id).items) == 1


# ---- Duplicate ----------------------------------------------------------------------

def test_duplicate_copies_items_and_settings_with_new_ids(client, monkeypatch):
    from backend import config

    client.act_as(A)
    data, _times, _failed = _seal_csv()
    mid = client.post("/api/models", data={"name": "M", "distribution": "weibull", "x": "Hours", "c": "Status"},
                      files={"file": ("d.csv", data, "text/csv")}).json()["id"]
    fid = client.post("/api/fleet/fleets", json={"name": "Seals", "model_id": mid}).json()["id"]
    settings = {"periods": 12, "default_rate": 60, "method": "renewals",
                "spares": {"lead_time": 2, "service_level": 0.95}}
    first = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": settings, "items": [{"name": "P1", "current_use": 100}, {"name": "P2", "current_use": 300}],
    }).json()
    r = client.post(f"/api/fleet/fleets/{fid}/duplicate", json={})
    assert r.status_code == 200, r.json()
    copy = client.get(f"/api/fleet/fleets/{r.json()['id']}").json()
    assert copy["name"] == "Seals (copy)" and copy["settings"] == first["settings"]
    assert [it["name"] for it in copy["items"]] == ["P1", "P2"]
    assert not {it["id"] for it in copy["items"]} & {it["id"] for it in first["items"]}
    assert copy["forecast"]["expected"] == pytest.approx(first["forecast"]["expected"])
    named = client.post(f"/api/fleet/fleets/{fid}/duplicate", json={"name": "Lead time 4"}).json()
    assert named["name"] == "Lead time 4"
    # The free plan's cap counts copies.
    monkeypatch.setattr(config, "FREE_MAX_FLEETS", 3)
    client.db.users.update_one({"_id": A}, {"$set": {"plan": "free"}})
    capped = client.post(f"/api/fleet/fleets/{fid}/duplicate", json={})
    assert capped.status_code == 402 and capped.json()["code"] == "cap"
    # Someone else's forecast can't be copied.
    client.act_as(B)
    assert client.post(f"/api/fleet/fleets/{fid}/duplicate", json={}).status_code == 404


# ---- Years and cost on every forecast -----------------------------------------------

def _single_fleet(db, periods, failure_cost=None):
    from backend.services import fleet as fs

    model, _t, _f = _life_model(db)
    fleet = fs.create_fleet(db, "S", model.id, A)
    settings = {"periods": periods, "period_label": "months", "default_rate": 40, "method": "single"}
    if failure_cost is not None:
        settings["failure_cost"] = failure_cost
    return fs.replace_items(db, fleet.id, settings,
                            [{"name": f"P{k}", "current_use": 50 * k} for k in range(15)], A)


def test_first_failures_years_are_exact_and_add_up(session):
    from backend.services import fleet as fs

    one = fs.compute(session, _single_fleet(session, 12), [A])
    st = one["strategy"]
    assert st["kind"] == "first_failures" and len(st["yearly"]) == 1
    # One year is the whole horizon: the same exact (Poisson-binomial) range.
    assert st["yearly"][0]["failures"]["interval"] == one["interval"]
    assert st["yearly"][0]["failures"]["expected"] == pytest.approx(one["expected"])

    two = fs.compute(session, _single_fleet(session, 30, failure_cost=2500), [A])
    years = two["strategy"]["yearly"]
    assert [(y["from_period"], y["to_period"], y["complete"]) for y in years] == [
        (1, 12, True), (13, 24, True), (25, 30, False)]
    assert sum(y["failures"]["expected"] for y in years) == pytest.approx(two["expected"])
    for y in years:
        lo, hi = y["failures"]["interval"]
        assert lo <= y["failures"]["expected"] <= hi
        assert y["cost"]["expected"] == pytest.approx(2500 * y["failures"]["expected"])
        assert y["cost"]["interval"] == [2500 * lo, 2500 * hi]
    assert two["strategy"]["total"]["cost"]["expected"] == pytest.approx(2500 * two["expected"])


def test_repairable_forecast_has_years_and_cost(session):
    from backend.services import fleet as fs
    from backend.services import recurrent as rs

    doc = rs.save_from_params(session, "Pumps", "crow_amsaa",
                              [{"name": "alpha", "value": 50}, {"name": "beta", "value": 1.3}], 1000, "hours", A)
    fleet = fs.create_fleet(session, "Pumps", doc.id, A, "recurrent")
    fleet = fs.replace_items(session, fleet.id, {"periods": 24, "period_label": "months", "default_rate": 25,
                                                 "failure_cost": 800},
                             [{"name": "P1", "current_use": 200}, {"name": "P2", "current_use": 600}], A)
    out = fs.compute(session, fleet, [A])
    st = out["strategy"]
    assert st["kind"] == "repairable" and len(st["yearly"]) == 2
    assert sum(y["failures"]["expected"] for y in st["yearly"]) == pytest.approx(out["expected"])
    from scipy.stats import poisson

    mu = sum(out["per_period"][:12])
    assert st["yearly"][0]["failures"]["interval"] == [float(poisson.ppf(0.05, mu)), float(poisson.ppf(0.95, mu))]
    assert st["yearly"][1]["cost"]["expected"] == pytest.approx(800 * sum(out["per_period"][12:]))


def test_periods_that_are_not_time_have_no_years(session):
    from backend.services import fleet as fs

    fleet = _single_fleet(session, 12)
    fleet = fs.replace_items(session, fleet.id, {**fleet.settings, "period_label": "shifts"}, fleet.items, A)
    st = fs.compute(session, fleet, [A])["strategy"]
    assert st["yearly"] is None and st["total"]["failures"]["expected"] > 0
