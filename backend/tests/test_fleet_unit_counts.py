"""Fleet items that stand for many identical units (a ``count``), and the
model's running units taken in full: a warranty table of a few rows and a
count column gives every unit still in the field, never the first 500."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from scipy import stats  # noqa: E402

from backend.tests.test_fleet import client  # noqa: E402,F401 - a fixture
from backend.tests.test_mcp import _call, _ok, env  # noqa: E402,F401 - env is a fixture

A = "user-a"

# Warranty returns by age: (age in months, returned, still in the field). Six
# monthly shipments; the youngest has been out one month.
WARRANTY = [
    (1, 4, 0), (2, 7, 0), (3, 9, 0), (4, 10, 0), (5, 14, 0), (6, 12, 450),
    (1, 3, 0), (2, 6, 0), (3, 9, 0), (4, 12, 0), (5, 11, 470),
    (1, 5, 0), (2, 4, 0), (3, 7, 0), (4, 10, 460),
    (1, 3, 0), (2, 9, 0), (3, 11, 480),
    (1, 4, 0), (2, 5, 515),
    (1, 2, 497),
]
RUNNING = sum(r for *_x, r in WARRANTY)  # 2,872 units in the field


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _warranty_csv() -> bytes:
    rows = []
    for age, failed, running in WARRANTY:
        if failed:
            rows.append({"age_months": age, "status": 0, "count": failed})
        if running:
            rows.append({"age_months": age, "status": 1, "count": running})
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _warranty_fleet(db):
    from backend.services import datasets as ds
    from backend.services import fleet as fs
    from backend.services import models as ms

    dataset = ds.create_dataset(db, "warranty.csv", _warranty_csv(), A)
    model = ms.save_model(db, "Warranty", dataset, "weibull", {"x": "age_months", "c": "status", "n": "count"},
                          [], None, unit="months", owner_id=A)
    return model, fs.create_fleet(db, "Warranty", model.id, A)


def _by_hand(model, horizon=6.0) -> float:
    """Each unit in the field fails in the next months with its chance given it
    survived to its age: (F(a + h) - F(a)) / S(a), added up over the units."""
    params = {p["name"]: p["value"] for p in model.results["params"]}
    dist = stats.weibull_min(params["beta"], scale=params["alpha"])
    total = 0.0
    for age, _failed, running in WARRANTY:
        if running:
            total += running * (dist.cdf(age + horizon) - dist.cdf(age)) / dist.sf(age)
    return total


def test_every_running_unit_is_taken_with_its_count(session):
    from backend.services import fleet_items

    _model, fleet = _warranty_fleet(session)
    out = fleet_items.running_units(session, fleet, [A])
    assert RUNNING == 2872
    assert out["running"] == RUNNING
    assert len(out["items"]) == 6 and sum(it["count"] for it in out["items"]) == RUNNING
    assert "truncated" not in out and "grouped" not in out


@pytest.mark.parametrize("method", ["single", "renewals"])
def test_the_forecast_counts_all_2872_units(session, method):
    """The hand figure, from every unit in the field: about 720 returns in six
    months. Taking only the first 500 units read about 120-175."""
    from backend.services import fleet as fs
    from backend.services import fleet_items

    model, fleet = _warranty_fleet(session)
    units = fleet_items.running_units(session, fleet, [A])
    fleet = fs.replace_items(session, fleet.id, {"periods": 6, "default_rate": 1, "method": method},
                             units["items"], A)
    out = fs.compute(session, fleet, [A])
    hand = _by_hand(model)
    assert 650 < hand < 800
    assert out["n_items"] == RUNNING
    if method == "single":
        assert out["expected"] == pytest.approx(hand, rel=1e-6)
    else:
        # Renewals add the odd replacement failing again inside six months.
        assert hand * 0.98 < out["expected"] < hand * 1.06
    assert len(out["per_item"]) == 6
    assert sum(r["expected"] for r in out["per_item"]) == pytest.approx(out["expected"], rel=0.02)
    assert {r["count"] for r in out["per_item"]} == {450, 470, 460, 480, 515, 497}
    assert all(0 < r["prob_any"] < 1 for r in out["per_item"])  # one unit's chance


def test_a_count_is_the_same_as_that_many_rows(session):
    from backend.services import fleet as fs

    model, fleet = _warranty_fleet(session)
    settings = {"periods": 6, "default_rate": 1, "method": "single"}
    grouped = fs.replace_items(session, fleet.id, settings, [{"name": "Batch", "current_use": 3, "count": 40}], A)
    one = fs.compute(session, grouped, [A])["expected"]
    rows = fs.replace_items(session, fleet.id, settings,
                            [{"name": f"U{k}", "current_use": 3} for k in range(40)], A)
    assert fs.compute(session, rows, [A])["expected"] == pytest.approx(one, rel=1e-9)


def test_counts_are_checked(session):
    from backend.services import fleet as fs

    for bad in (0, 2.5, "two", -3):
        with pytest.raises(fs.FleetValidationError, match="number of units"):
            fs._clean_items([{"name": "A", "current_use": 1, "count": bad}])
    assert "count" not in fs._clean_items([{"name": "A", "current_use": 1, "count": 1}])[0]
    with pytest.raises(fs.FleetValidationError, match="20,000 units"):
        fs._clean_items([{"name": "A", "current_use": 1, "count": 20_001}])


def test_more_ages_than_rows_share_rows_and_keep_every_unit(session):
    """1,200 units each at its own age: more than 500 rows, so close ages share
    a row at their average age. Every unit is counted, and the page says so."""
    from backend.services import datasets as ds
    from backend.services import fleet as fs
    from backend.services import fleet_items
    from backend.services import models as ms

    rng = np.random.default_rng(7)
    ages = np.round(rng.uniform(1, 40, 1200), 3)
    failed = np.round(rng.weibull(2.0, 300) * 30, 3)
    df = pd.DataFrame({"hours": np.concatenate([failed, ages]), "c": [0] * 300 + [1] * 1200})
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    dataset = ds.create_dataset(session, "many.csv", buf.getvalue().encode(), A)
    model = ms.save_model(session, "Many", dataset, "weibull", {"x": "hours", "c": "c"}, [], None,
                          unit="hours", owner_id=A)
    fleet = fs.create_fleet(session, "Many", model.id, A)
    out = fleet_items.running_units(session, fleet, [A])
    assert out["running"] == 1200 and len(out["items"]) <= 500
    assert sum(it.get("count", 1) for it in out["items"]) == 1200
    assert "1,200 units" in out["grouped"] and "every unit is counted" in out["grouped"]
    settings = {"periods": 6, "default_rate": 1, "method": "single"}
    grouped = fs.compute(session, fs.replace_items(session, fleet.id, settings, out["items"], A), [A])
    each = [{"id": f"u{k}", "name": f"U{k}", "current_use": float(a), "rate": None} for k, a in enumerate(ages)]
    exact = fs.compute(session, fs.get_fleet(session, fleet.id, A).model_copy(update={"items": each}), [A])
    assert grouped["expected"] == pytest.approx(exact["expected"], rel=0.005)


def test_a_model_typed_from_parameters_has_no_running_units_and_no_error(client):
    client.act_as(A)
    res = client.post("/api/models/from-params", json={
        "name": "Seal", "distribution": "weibull", "unit": "hours",
        "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}]})
    assert res.status_code == 200, res.text
    fid = client.post("/api/fleet/fleets", json={"name": "F", "model_id": res.json()["id"]}).json()["id"]
    r = client.get(f"/api/fleet/fleets/{fid}/running-units")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] == 0 and body["items"] == [] and "parameters" in body["reason"]


def test_mcp_forecast_from_the_model_data_takes_every_unit(env):
    from backend.services import fleet as fs

    model, fleet = _warranty_fleet(env.db)
    fs.replace_items(env.db, fleet.id, {"periods": 6, "default_rate": 1, "method": "single"},
                     [{"name": "one", "current_use": 1}], A)
    out = _ok(_call(env.token[A], "analyse", {"action": "fleet_forecast", "fleet_id": fleet.id,
                                               "use_model_data": True}))
    assert out["items_source"]["n_items"] == RUNNING
    assert out["forecast"]["expected"] == pytest.approx(_by_hand(model), rel=1e-6)
