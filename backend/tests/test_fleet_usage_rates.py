"""Usage-rate estimation from timestamped API meter readings + rate_source."""

import matplotlib

matplotlib.use("Agg")

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.test_fleet_alerts import (  # noqa: F401  (fixture reuse)
    A, _alerts_url, _save_model, client, outbox,
)

MONTH = timedelta(days=30.4375)
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _fleet(client, label="months", rate_source="manual", items=None, periods=12):
    client.act_as(A)
    model = _save_model(client)
    fleet = client.post("/api/fleet/fleets", json={"name": "Trucks", "model_id": model["id"]}).json()
    r = client.put(f"/api/fleet/fleets/{fleet['id']}/items", json={
        "settings": {"periods": periods, "period_label": label, "default_rate": 20,
                     "method": "single", "rate_source": rate_source},
        "items": items or [{"name": "Truck 01", "current_use": 100}],
    })
    assert r.status_code == 200, r.text
    token = client.post("/api/tokens", json={"name": "cron"}).json()["token"]
    return fleet["id"], token


def _read(client, fid, token, rows, status=200):
    r = client.post(f"/api/ingest/fleets/{fid}/usage", json={"items": rows},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == status, r.text
    return r.json()


def _item(client, fid, name="Truck 01"):
    doc = client.db.fleets.find_one({"_id": fid})
    return next(it for it in doc["items"] if it["name"] == name)


# ---- pure estimator ---------------------------------------------------------------

def test_period_days_labels():
    from backend.services.fleet import period_days

    assert period_days("days") == period_days("Day") == 1.0
    assert period_days("weeks") == period_days("WEEK") == 7.0
    assert period_days("months") == period_days("Month") == 30.4375
    assert period_days("quarters") == period_days("quarter") == 91.3125
    assert period_days(" Years ") == period_days("year") == 365.25
    assert period_days("hours") is None and period_days("shifts") is None and period_days("") is None


def test_ewma_over_several_readings():
    from backend.services.ingest import apply_reading

    item = {"id": "i", "name": "x", "current_use": 0}
    assert apply_reading(item, 0, T0, 30.4375)
    assert "estimated_rate" not in item  # first reading is only a baseline
    apply_reading(item, 100, T0 + MONTH, 30.4375)
    assert item["estimated_rate"] == pytest.approx(100) and item["estimated_rate_n"] == 1
    apply_reading(item, 300, T0 + 2 * MONTH, 30.4375)          # interval 200/mo
    assert item["estimated_rate"] == pytest.approx(0.3 * 200 + 0.7 * 100)  # 130
    apply_reading(item, 350, T0 + 3 * MONTH, 30.4375)          # interval 50/mo
    assert item["estimated_rate"] == pytest.approx(0.3 * 50 + 0.7 * 130)   # 106
    assert item["estimated_rate_n"] == 3 and item["current_use"] == 350


@pytest.mark.parametrize("label,days,expected", [
    ("days", 14, 10.0),          # 140 over 14 days
    ("weeks", 14, 70.0),         # 2 weeks
    ("months", 30.4375, 140.0),
    ("quarters", 91.3125, 140.0),
    ("years", 365.25 / 2, 280.0),
])
def test_unit_conversion_for_each_label(client, label, days, expected):
    fid, token = _fleet(client, label=label)
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)}])
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 240,
                                 "read_at": _iso(T0 + timedelta(days=days))}])
    assert _item(client, fid)["estimated_rate"] == pytest.approx(expected)


def test_meter_reset_rebaselines_without_estimating():
    from backend.services.ingest import apply_reading

    item = {"id": "i", "name": "x", "current_use": 0}
    apply_reading(item, 1000, T0, 30.4375)
    apply_reading(item, 1100, T0 + MONTH, 30.4375)
    assert item["estimated_rate"] == pytest.approx(100)
    apply_reading(item, 20, T0 + 2 * MONTH, 30.4375)            # replaced unit
    assert item["estimated_rate"] == pytest.approx(100) and item["estimated_rate_n"] == 1
    assert item["last_reading_use"] == 20 and item["current_use"] == 20
    apply_reading(item, 70, T0 + 3 * MONTH, 30.4375)            # 50/mo from the new baseline
    assert item["estimated_rate"] == pytest.approx(0.3 * 50 + 0.7 * 100)
    assert item["estimated_rate_n"] == 2


def test_sub_day_readings_accumulate_on_the_old_baseline():
    from backend.services.ingest import apply_reading

    item = {"id": "i", "name": "x", "current_use": 0}
    apply_reading(item, 0, T0, 1.0)
    for h in range(1, 24):
        apply_reading(item, h, T0 + timedelta(hours=h), 1.0)
    assert "estimated_rate" not in item and item["last_reading_at"] == T0.isoformat()
    apply_reading(item, 30, T0 + timedelta(hours=30), 1.0)
    assert item["estimated_rate"] == pytest.approx(24.0)  # 30 per 1.25 days


def test_out_of_order_reading_is_ignored(client):
    fid, token = _fleet(client)
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)}])
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 200, "read_at": _iso(T0 + MONTH)}])
    before = dict(_item(client, fid))
    body = _read(client, fid, token, [{"name": "Truck 01", "current_use": 150, "rate": 5,
                                        "read_at": _iso(T0 + MONTH / 2)}])
    assert body["ignored_readings"] == 1 and body["updated_items"] == 0
    after = _item(client, fid)
    assert after == before  # current_use, manual rate and estimate untouched


def test_batch_is_applied_in_time_order(client):
    fid, token = _fleet(client)
    body = _read(client, fid, token, [
        {"name": "Truck 01", "current_use": 300, "read_at": _iso(T0 + 2 * MONTH)},
        {"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)},
        {"name": "Truck 01", "current_use": 200, "read_at": _iso(T0 + MONTH)},
    ])
    item = _item(client, fid)
    assert body["updated_items"] == 1 and "ignored_readings" not in body
    assert item["current_use"] == 300 and item["estimated_rate_n"] == 2
    assert item["estimated_rate"] == pytest.approx(100)


def test_unknown_label_gives_no_estimate(client):
    fid, token = _fleet(client, label="shifts")
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)}])
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 900, "read_at": _iso(T0 + MONTH)}])
    item = _item(client, fid)
    assert item["current_use"] == 900 and "estimated_rate" not in item


def test_read_at_validation_and_default(client):
    fid, token = _fleet(client)
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 1, "read_at": "last tuesday"}], status=422)
    future = datetime.now(timezone.utc) + timedelta(days=2)
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 1, "read_at": _iso(future)}], status=422)
    # Omitted → request time; naive → UTC.
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 110}])
    stamp = datetime.fromisoformat(_item(client, fid)["latest_read_at"])
    assert abs((datetime.now(timezone.utc) - stamp).total_seconds()) < 60
    fid2, token2 = _fleet(client)
    _read(client, fid2, token2, [{"name": "Truck 01", "current_use": 1, "read_at": "2026-01-01T00:00:00"}])
    assert _item(client, fid2)["latest_read_at"] == T0.isoformat()


# ---- rate_source ------------------------------------------------------------------

def test_rate_source_validation_and_estimates_survive_ui_save(client):
    fid, token = _fleet(client)
    fleet = client.get(f"/api/fleet/fleets/{fid}").json()
    assert fleet["settings"]["rate_source"] == "manual"
    r = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {**fleet["settings"], "rate_source": "guess"}, "items": fleet["items"]})
    assert r.status_code == 422

    _read(client, fid, token, [{"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)}])
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 190, "read_at": _iso(T0 + MONTH)}])
    fleet = client.get(f"/api/fleet/fleets/{fid}").json()
    # A client can't forge estimator state; a UI save keeps the server's.
    items = [{**it, "estimated_rate": 1e6, "notes": "checked"} for it in fleet["items"]]
    saved = client.put(f"/api/fleet/fleets/{fid}/items", json={"settings": fleet["settings"], "items": items}).json()
    assert saved["items"][0]["estimated_rate"] == pytest.approx(90)
    assert saved["items"][0]["estimated_rate_n"] == 1


def test_rate_source_switch_changes_the_forecast(client):
    fid, token = _fleet(client)
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)}])
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 200, "read_at": _iso(T0 + MONTH)}])
    manual = client.get(f"/api/fleet/fleets/{fid}").json()
    assert manual["forecast"]["per_item"][0]["rate_used"] == 20
    assert manual["forecast"]["per_item"][0]["rate_basis"] == "default"

    fleet = manual
    est = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {**fleet["settings"], "rate_source": "estimated"}, "items": fleet["items"]}).json()
    row = est["forecast"]["per_item"][0]
    assert row["rate_used"] == pytest.approx(100) and row["rate_basis"] == "estimated"
    assert est["forecast"]["rate_source"] == "estimated"
    assert est["forecast"]["expected"] > manual["forecast"]["expected"]

    # Estimated falls back to the item's manual rate, then the default.
    client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": est["settings"],
        "items": [*est["items"], {"name": "Truck 02", "current_use": 0, "rate": 7}, {"name": "Truck 03", "current_use": 0}],
    })
    rows = client.get(f"/api/fleet/fleets/{fid}").json()["forecast"]["per_item"]
    assert [(r["rate_basis"], r["rate_used"]) for r in rows] == [
        ("estimated", pytest.approx(100)), ("manual", 7), ("default", 20)]


def test_manual_default_forecast_is_byte_identical(client):
    """Readings that leave current_use where it was don't move a 'manual' forecast."""
    fid, token = _fleet(client, items=[{"name": "Truck 01", "current_use": 100, "rate": 15},
                                       {"name": "Truck 02", "current_use": 300}])
    before = client.get(f"/api/fleet/fleets/{fid}").json()["forecast"]
    for name, use in (("Truck 01", 100), ("Truck 02", 300)):
        _read(client, fid, token, [{"name": name, "current_use": use / 2, "read_at": _iso(T0)}])
        _read(client, fid, token, [{"name": name, "current_use": use, "read_at": _iso(T0 + MONTH)}])
    assert _item(client, fid, "Truck 02")["estimated_rate_n"] == 1
    after = client.get(f"/api/fleet/fleets/{fid}").json()["forecast"]
    assert json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)


# ---- a 'within' alert driven by an estimated rate --------------------------------

def test_within_alert_fires_on_estimated_rate_increase(client, outbox):
    from backend.db import from_doc
    from backend.schema import Fleet
    from backend.services import fleet as fleet_service
    from backend.services.fleet_alerts import window_value

    fid, token = _fleet(client, rate_source="estimated")
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 100, "read_at": _iso(T0)}])
    _read(client, fid, token, [{"name": "Truck 01", "current_use": 150, "read_at": _iso(T0 + MONTH)}])
    assert _item(client, fid)["estimated_rate"] == pytest.approx(50)

    # What the 3-month window will read after a heavy month (rate → 0.3·300 + 0.7·50).
    doc = client.db.fleets.find_one({"_id": fid})
    hypo = from_doc(Fleet, doc)
    hypo.items = [{**hypo.items[0], "current_use": 450, "estimated_rate": 125.0}]
    high = window_value(fleet_service.compute(client.db, hypo, [A])["per_period"], 3)[0]

    rule = client.post(_alerts_url(fid), json={"kind": "within", "x": 1, "y_periods": 3}).json()
    low = rule["last_value"]
    assert high > low
    x = round((low + high) / 2, 4)
    client.patch(f"{_alerts_url(fid)}/{rule['id']}", json={"x": x})

    body = _read(client, fid, token, [{"name": "Truck 01", "current_use": 450, "read_at": _iso(T0 + 2 * MONTH)}])
    assert _item(client, fid)["estimated_rate"] == pytest.approx(125)
    assert body["alerts_fired"] == 1
    assert "failures now expected within 3 months" in outbox[0]["subject"]
    event = client.db.fleet_alert_events.find_one({})
    assert event["new_value"] == pytest.approx(high) and event["previous_value"] == pytest.approx(low)
