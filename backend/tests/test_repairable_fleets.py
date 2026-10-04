"""Fleet forecasts for repairable equipment (#235): a fleet running on a
saved recurrent-event model counts every failure of each system —
Λ(a + u) − Λ(a) per item, Poisson for the fleet — checked against
SurPyval 0.23's ``forecast``; alerts, sharing and the MCP read it as they
read a life-model fleet."""

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import surpyval  # noqa: E402
from scipy.stats import poisson  # noqa: E402
from surpyval.recurrent import CrowAMSAA  # noqa: E402

from backend.tests import test_mcp as tm  # noqa: E402
from backend.tests.test_fleet import client  # noqa: E402,F401 - a fixture
from backend.tests.test_mcp import env  # noqa: E402,F401 - a fixture

A, B = "user-a", "user-b"
ALPHA, BETA = 50.0, 1.3


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _recurrent(db, owner=A, alpha=ALPHA, beta=BETA):
    from backend.services import recurrent as recurrent_service

    return recurrent_service.save_from_params(
        db, "Pumps", "crow_amsaa", [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}], 1000,
        "hours", owner)


def _fleet(db, items, settings=None, owner=A):
    from backend.services import fleet as fs

    model = _recurrent(db, owner)
    fleet = fs.create_fleet(db, "Pumps", model.id, owner, "recurrent")
    return fs.replace_items(db, fleet.id, settings or {"periods": 4, "default_rate": 25}, items, owner), model


def test_equal_rates_match_surpyval_forecast(session):
    from backend.services import fleet as fs

    ages = [200.0, 500.0, 900.0]
    fleet, model = _fleet(session, [{"name": f"P{k}", "current_use": a} for k, a in enumerate(ages)])
    out = fs.compute(session, fleet, [A])
    assert out["status"] == "ok" and out["method"] == "repairable" and out["model_kind"] == "recurrent"
    ref = surpyval.forecast(CrowAMSAA.from_params([ALPHA, BETA]), age=ages, horizon=[25, 50, 75, 100],
                            alpha_ci=0.2)
    assert out["expected"] == pytest.approx(float(ref.expected[-1]), rel=1e-12)
    assert out["interval"] == [float(ref.lower[-1]), float(ref.upper[-1])]  # Poisson P10–P90
    assert out["per_period"] == pytest.approx(list(ref.period_expected), rel=1e-12)
    assert out["per_period_interval"] == [[float(lo), float(hi)]
                                          for lo, hi in zip(ref.period_lower, ref.period_upper)]
    per_item = [r["expected"] for r in out["per_item"]]
    assert per_item == pytest.approx(list(ref.per_unit[:, -1]), rel=1e-12)
    assert [r["prob_any"] for r in out["per_item"]] == pytest.approx(list(ref.probability[:, -1]), rel=1e-12)
    assert sum(out["per_period"]) == pytest.approx(out["expected"])
    assert "minimal repair" in out["note"] and out["unit"] == "hours"


def test_per_item_rates_next_service_and_idle_items(session):
    from backend.services import fleet as fs

    lam = CrowAMSAA.from_params([ALPHA, BETA]).cif
    items = [{"name": "fast", "current_use": 300, "rate": 40, "next_service_at": 350},
             {"name": "slow", "current_use": 100, "rate": 5},
             {"name": "idle", "current_use": 800, "rate": 0},
             {"name": "late", "current_use": 600, "next_service_at": 550}]
    fleet, _ = _fleet(session, items, {"periods": 3, "default_rate": 25})
    out = fs.compute(session, fleet, [A])
    fast, slow, idle, late = out["per_item"]
    assert fast["expected"] == pytest.approx(float(lam(300 + 120) - lam(300)), rel=1e-12)
    assert slow["expected"] == pytest.approx(float(lam(100 + 15) - lam(100)), rel=1e-12)
    assert idle["expected"] == 0.0 and idle["prob_any"] == 0.0
    assert late["expected"] == pytest.approx(float(lam(600 + 75) - lam(600)), rel=1e-12)
    m_s = float(lam(350) - lam(300))
    assert fast["expected_before_service"] == pytest.approx(m_s, rel=1e-12)
    assert fast["prob_before_service"] == pytest.approx(1 - np.exp(-m_s), rel=1e-12)
    assert late["service_overdue"] is True and late["prob_before_service"] is None
    assert "next_service_at" not in slow
    total = fast["expected"] + slow["expected"] + late["expected"]
    assert out["expected"] == pytest.approx(total, rel=1e-12)
    assert out["interval"] == [float(poisson.ppf(0.1, total)), float(poisson.ppf(0.9, total))]
    # Each period's mean is that period's slice of every item's use.
    p2 = sum(float(lam(a + 2 * r) - lam(a + r)) for a, r in ((300, 40), (100, 5), (600, 25)))
    assert out["per_period"][1] == pytest.approx(p2, rel=1e-12)
    assert [r["rate_basis"] for r in out["per_item"]] == ["manual", "manual", "manual", "default"]


def test_many_rates_vectorised_path_matches_surpyval():
    from backend.services import fleet as fs

    rng = np.random.default_rng(4)
    model = CrowAMSAA.from_params([ALPHA, BETA])
    ages = rng.uniform(0, 2000, 60)
    rates = np.round(rng.uniform(1, 80, 60), 3)
    rates[:3] = 0.0
    items = [{"id": str(k)} for k in range(60)]
    assert np.unique(rates[rates > 0]).size > fs._FORECAST_GROUPS
    out = fs.forecast_repairable(model, ages, rates, 6, items)
    for k in (3, 30, 59):
        ref = surpyval.forecast(model, age=[ages[k]], horizon=rates[k] * np.arange(1, 7), alpha_ci=0.2)
        assert out["per_item"][k]["expected"] == pytest.approx(float(ref.per_unit[0, -1]), rel=1e-12)
    assert all(out["per_item"][k]["expected"] == 0.0 for k in range(3))
    # The grouped path gives the same numbers.
    few = fs.forecast_repairable(model, ages[:10], rates[:10], 6, items[:10])
    many = fs.forecast_repairable(model, ages, rates, 6, items)
    assert [r["expected"] for r in few["per_item"]] == pytest.approx(
        [r["expected"] for r in many["per_item"][:10]], rel=1e-12)


def test_bad_next_service_and_unknown_kind(session):
    from backend.services import fleet as fs

    model = _recurrent(session)
    fleet = fs.create_fleet(session, "F", model.id, A, "recurrent")
    with pytest.raises(fs.FleetValidationError, match="next service"):
        fs.replace_items(session, fleet.id, {}, [{"name": "x", "next_service_at": -1}], A)
    with pytest.raises(fs.FleetValidationError, match="next service"):
        fs.replace_items(session, fleet.id, {}, [{"name": "x", "next_service_at": "soon"}], A)
    with pytest.raises(fs.FleetValidationError, match="Unknown model kind"):
        fs.create_fleet(session, "F", model.id, A, "degradation")
    with pytest.raises(fs.FleetValidationError, match="Recurrent model not found"):
        fs.create_fleet(session, "F", "nope", A, "recurrent")
    # A life-model id isn't a recurrent model, and vice versa.
    with pytest.raises(fs.FleetValidationError, match="Life model not found"):
        fs.create_fleet(session, "F", model.id, A)


def test_stale_when_the_recurrent_model_is_deleted(session):
    from backend.services import fleet as fs
    from backend.services import recurrent as recurrent_service

    fleet, model = _fleet(session, [{"name": "P", "current_use": 10}])
    recurrent_service.delete_model(session, model.id, A)
    out = fs.compute(session, fleet, [A])
    assert out["status"] == "stale" and "no longer exists" in out["reason"]


def test_empty_fleet(session):
    from backend.services import fleet as fs

    fleet, _ = _fleet(session, [])
    out = fs.compute(session, fleet, [A])
    assert out["expected"] == 0.0 and out["per_period"] == [0.0] * 4 and out["per_item"] == []


def test_alerts_read_the_counts_unchanged(session):
    from backend.services import fleet_alerts as alerts

    fleet, _ = _fleet(session, [{"name": "P", "current_use": 400}], {"periods": 6, "default_rate": 30})
    forecast = alerts.current_forecast(session, fleet, [A])
    assert alerts.current_value(session, fleet, [A]) == pytest.approx(forecast["expected"])
    value, _ = alerts.window_value(forecast["per_period"], 2.5)
    pp = forecast["per_period"]
    assert value == pytest.approx(pp[0] + pp[1] + 0.5 * pp[2])
    doc = alerts.create_alert(session, fleet, A, [A], kind="within", x=1, y_periods=2)
    assert doc["kind"] == "within"


def test_api_create_share_and_isolation(client):
    client.act_as(B)
    client.act_as(A)
    r = client.post("/api/recurrent/from-params", data={
        "name": "Pumps", "model": "crow_amsaa", "alpha": ALPHA, "beta": BETA, "horizon": 1000, "unit": "hours"})
    mid = r.json()["id"]
    r = client.post("/api/fleet/fleets", json={"name": "Pump fleet", "model_id": mid, "model_kind": "recurrent"})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert r.json()["model_kind"] == "recurrent"
    # A recurrent id isn't a life model.
    assert client.post("/api/fleet/fleets", json={"name": "x", "model_id": mid}).status_code == 422

    r = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {"periods": 12, "period_label": "months", "default_rate": 20},
        "items": [{"name": "P1", "current_use": 300, "next_service_at": 400}, {"name": "P2", "current_use": 50}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forecast"]["status"] == "ok" and body["forecast"]["model_name"] == "Pumps"
    assert body["items"][0]["next_service_at"] == 400.0
    assert body["forecast"]["per_item"][0]["prob_before_service"] > 0
    assert "failures expected over 12 months" in body["headline"]
    listed = client.get("/api/fleet/fleets").json()["fleets"]
    assert listed[0]["model_kind"] == "recurrent" and listed[0]["expected"] == pytest.approx(
        body["forecast"]["expected"])

    assert client.post("/api/shares", json={"collection": "fleets", "artifact_id": fid,
                                            "email": "b@x.com"}).status_code == 200
    client.act_as(B)
    got = client.get(f"/api/fleet/fleets/{fid}")
    assert got.status_code == 200 and got.json()["forecast"]["status"] == "ok"
    # Transitive: the recurrent model opens for the recipient.
    assert client.get(f"/api/recurrent/models/{mid}").status_code == 200


# ---- MCP ----------------------------------------------------------------------------

def test_mcp_fleet_forecast_and_delete_guard(env):
    from backend.services import fleet as fs

    model = _recurrent(env.db, tm.A)
    fleet = fs.create_fleet(env.db, "Pumps", model.id, tm.A, "recurrent")
    fs.replace_items(env.db, fleet.id, {"periods": 4, "default_rate": 25},
                     [{"name": "P1", "current_use": 200, "next_service_at": 260}], tm.A)
    listed = tm._ok(tm._call(env.token[tm.A], "list_fleets"))["fleets"]
    assert listed[0]["model_kind"] == "recurrent"
    out = tm._ok(tm._call(env.token[tm.A], "fleet_forecast", {"fleet_id": fleet.id}))
    assert out["fleet"]["model_kind"] == "recurrent" and out["forecast"]["method"] == "repairable"
    lam = CrowAMSAA.from_params([ALPHA, BETA]).cif
    assert out["forecast"]["expected"] == pytest.approx(float(lam(300) - lam(200)), rel=1e-12)
    assert out["forecast"]["per_item"][0]["prob_before_service"] == pytest.approx(
        1 - np.exp(-float(lam(260) - lam(200))), rel=1e-12)
    msg = tm._err(tm._call(env.token[tm.A], "delete_model", {"model_id": model.id}))
    assert "can't be deleted" in msg and "Pumps" in msg
    assert env.db.recurrent_models.find_one({"_id": model.id}) is not None
