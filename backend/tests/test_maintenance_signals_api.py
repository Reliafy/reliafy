"""Signal channels over the ingest API, the app's routes and the maintenance MCP tool."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.tests.test_maintenance_mcp import UID, _do, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import UID as API_UID
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")


def _when(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def _maintenance(org):
    from backend.maintenance.service import Maintenance
    from backend.routers import maintenance as router

    return Maintenance(router._store, org)


def test_the_ingest_api_stores_snapshots_and_reports_repeats(env):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import tokens

    m = _maintenance(UID)
    pos = m.create_position("Pool pump")
    ch = m.add_signal_channel(pos["id"], None, "Pump", "g", sample_rate=3200, axes=["X", "Y", "Z"], tag="pump.vib")
    m.add_signal_band(ch["id"], "1x", 45, 55, axis="X")
    t = np.arange(8300) / 3200
    body = {"tag": "pump.vib", "time": _when(1), "running": True,
            "axes": {a: (0.5 * np.sin(2 * np.pi * 50 * t) + 0.01 * i).round(5).tolist() for i, a in enumerate("XYZ")}}
    token = tokens.create_token(env["db"], UID, "gateway", scopes=["ingest"])["token"]
    auth = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)
    r = client.post("/api/ingest/maintenance/snapshots", json=body, headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["stored"] == 1 and out["results"][0]["derived"][0]["value"] == pytest.approx(0.5 / np.sqrt(2), rel=0.01)
    again = client.post("/api/ingest/maintenance/snapshots", json={"snapshots": [body]}, headers=auth).json()
    assert again["stored"] == 0 and again["duplicates"] == 1
    bad = client.post("/api/ingest/maintenance/snapshots", json={**body, "time": "2026-11-03T10:00:00"},
                      headers=auth).json()
    assert bad["errors"] == 1 and "time zone" in bad["results"][0]["error"]
    big = {**body, "time": _when(2), "axes": {a: [0.1] * 200_000 for a in "XYZ"}}
    too_big = client.post("/api/ingest/maintenance/snapshots", json=big, headers=auth)
    assert too_big.status_code in (200, 413)
    if too_big.status_code == 200:
        assert too_big.json()["errors"] == 1 and "5 MB" in str(too_big.json()["results"][0]["error"]) or \
            "500,000" in str(too_big.json()["results"][0]["error"])


def test_the_apps_routes_serve_the_signals_tab(api):
    m = _maintenance(API_UID)
    pos = m.create_position("Pool pump")
    made = api.post("/api/maintenance/signals/channels",
                    json={"position_id": pos["id"], "name": "Pump", "unit": "g", "sample_rate": 3200,
                          "axes": ["X"], "rpm": 2980})
    assert made.status_code == 200, made.text
    cid = made.json()["id"]
    t = np.arange(4096) / 3200
    for hours in (3, 2, 1):
        m.add_signal_snapshot(_when(hours), cid, axes={"X": (0.4 * np.sin(2 * np.pi * 50 * t)).tolist()})
    listing = api.get("/api/maintenance/signals/channels", params={"position_id": pos["id"]}).json()
    assert [c["id"] for c in listing["channels"]] == [cid] and listing["channels"][0]["snapshots"]["count"] == 3
    view = api.get(f"/api/maintenance/signals/channels/{cid}").json()
    ids = [s["id"] for s in view["snapshots"]["index"]]
    assert len(ids) == 3
    spectra = api.get(f"/api/maintenance/signals/channels/{cid}/spectra",
                      params={"ids": ",".join(ids[:2]), "axis": "X", "max_points": 300}).json()
    assert len(spectra["spectra"]) == 2 and len(spectra["spectra"][0]["spectrum"]["freqs"]) <= 300
    prev = api.get(f"/api/maintenance/signals/channels/{cid}/band-preview", params={"low": 45, "high": 55}).json()
    assert len(prev["series"]) == 3
    band = api.post(f"/api/maintenance/signals/channels/{cid}/bands", json={"name": "1x", "low": 45, "high": 55}).json()
    assert band["history_written"] == 3
    assert api.get(f"/api/maintenance/signals/channels/{cid}").json()["bands"][0]["series"]
    assert api.post(f"/api/maintenance/signals/bands/{band['point_id']}/remove").status_code == 200
    assert api.get("/api/maintenance/signals/snapshots/nope").status_code in (404, 422)


def test_the_maintenance_tool_adds_channels_and_snapshots(env):
    m = _maintenance(UID)
    pos = m.create_position("Pool pump")

    async def go(client):
        ch = _ok(await _do(client, "maintenance", "signals.add_channel", position_id=pos["id"], name="Discharge",
                           unit="kPa", tag="p"))
        level = _ok(await _do(client, "maintenance", "signals.add_level", channel_id=ch["id"], name="Pressure",
                              stat="value"))
        snap = _ok(await _do(client, "maintenance", "signals.add_snapshot", tag="p", time=_when(1), value=190))
        again = _ok(await _do(client, "maintenance", "signals.add_snapshot", tag="p", time=snap["t"], value=190))
        read = _ok(await _do(client, "maintenance", "signal_data.channels", position_id=pos["id"]))
        point = _ok(await client.call_tool("maintenance", {"action": "get.measurement_point",
                                                           "id": level["point_id"]}))
        refused = await _do(client, "maintenance", "signals.add_snapshot", tag="p", time="2026-11-03T10:00:00",
                            value=1)
        batch = await client.call_tool("maintenance", {"action": "apply", "dry_run": True, "operations": [
            {"do": "signals.add_snapshot", "args": {"tag": "p", "time": _when(2), "value": 1}}]})
        return snap, again, read, point, refused, batch

    snap, again, read, point, refused, batch = _session(env["token"], go)
    assert snap["stored"] and again["duplicate"]
    assert read["channels"][0]["snapshots"]["count"] == 1
    assert point["reading"] == 190 and point["unit"] == "kPa"
    assert refused.is_error and "time zone" in refused.content[0].text
    assert batch.is_error or "can't" in str(batch.structured_content).lower() or "batch" in str(batch.content).lower()


def test_the_apps_routes_edit_bands_and_report_storage(api):
    m = _maintenance(API_UID)
    pos = m.create_position("Fan")
    cid = api.post("/api/maintenance/signals/channels",
                   json={"position_id": pos["id"], "name": "Casing", "unit": "g", "sample_rate": 3200,
                         "axes": ["X"], "rpm": 3000}).json()["id"]
    speed = api.post("/api/maintenance/signals/channels",
                     json={"position_id": pos["id"], "name": "Speed", "unit": "rpm"}).json()["id"]
    t = np.arange(4096) / 3200
    m.add_signal_snapshot(_when(2), cid, axes={"X": (0.4 * np.sin(2 * np.pi * 50 * t)).tolist()})
    band = api.post(f"/api/maintenance/signals/channels/{cid}/bands",
                    json={"name": "1x", "low": 45, "high": 55, "warn_above": 0.1, "alarm_above": 0.5}).json()
    assert band["band"]["warn_above"] == 0.1
    same = api.patch(f"/api/maintenance/signals/bands/{band['point_id']}", json={"name": "Running speed",
                                                                                 "warn_above": 0.2}).json()
    assert not same["new_version"] and same["band"]["name"] == "Running speed" and same["band"]["warn_above"] == 0.2
    moved = api.patch(f"/api/maintenance/signals/bands/{band['point_id']}", json={"low": 90, "high": 110}).json()
    assert moved["new_version"] and moved["band"]["alarm_above"] == 0.5 and moved["band"]["warn_above"] == 0.2
    view = api.get(f"/api/maintenance/signals/channels/{cid}").json()
    assert len(view["bands"]) == 1 and len(view["bands"][0]["versions"]) == 2
    bad = api.patch(f"/api/maintenance/signals/bands/{moved['point_id']}", json={"low": 200, "high": 100})
    assert bad.status_code == 422 and "above" in bad.text
    st = api.get("/api/maintenance/signals/storage").json()
    assert st["snapshots"] == 1 and st["cap_mb"] is None
    assert api.put("/api/maintenance/signals/storage-cap", json={"cap_mb": 50}).json()["cap_mb"] == 50
    assert api.patch(f"/api/maintenance/signals/channels/{cid}", json={"speed_channel_id": speed}).json()[
        "speed_channel_id"] == speed


def test_the_maintenance_tool_edits_bands_and_sets_the_storage_cap(env):
    m = _maintenance(UID)
    pos = m.create_position("Pool pump")

    async def go(client):
        ch = _ok(await _do(client, "maintenance", "signals.add_channel", position_id=pos["id"], name="Vib", unit="g",
                           axes=["X"], sample_rate=3200))
        band = _ok(await _do(client, "maintenance", "signals.add_band", channel_id=ch["id"], name="1x", low=45,
                             high=55, alarm_above=0.5))
        edited = _ok(await _do(client, "maintenance", "signals.update_band", point_id=band["point_id"],
                               warn_above=0.3, clear_limits=["alarm_above"]))
        cap = _ok(await _do(client, "maintenance", "signals.set_storage_cap", cap_mb=10))
        storage = _ok(await _do(client, "maintenance", "signal_data.storage"))
        return edited, cap, storage

    edited, cap, storage = _session(env["token"], go)
    assert edited["band"]["warn_above"] == 0.3 and edited["band"]["alarm_above"] is None
    assert cap["cap_mb"] == 10 and storage["cap_mb"] == 10 and storage["snapshots"] == 0
