"""The offline-device routes over HTTP (routers/maintenance_sync.py): the batch
push and the queued photo, gated as the rest of /api/v1, in the spec for
Reliafy Maintenance's users only."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.test_api_tools import A, B, _auth, _jpeg, env, maint  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("mcp_on")

PUSH, PHOTO = "/api/v1/maintenance/sync/push", "/api/v1/maintenance/sync/photo"


def _now(minutes=-2):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _op(command, args, seq=1, **more):
    return {"op_id": str(uuid.uuid4()), "device_seq": seq, "command": command, "args": args,
            "device_time": _now(), **more}


def _job(maint):
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump A"}).json()
    wo = maint.post("/api/v1/maintenance/work_orders.open", {"position_id": pos["id"], "title": "Leak at the gland"})
    assert wo.status_code == 200, wo.text
    return pos, wo.json()


def test_push_applies_once_and_is_gated_like_the_rest(maint, monkeypatch):
    _pos, wo = _job(maint)
    ops = [_op("work_orders.status", {"work_order_id": wo["id"], "status": "in_progress"}, 1),
           _op("work_orders.update", {"work_order_id": wo["id"], "append_note": "Repacked the gland"}, 2),
           _op("work_orders.close", {"work_order_id": wo["id"], "actions": [{"kind": "repair"}]}, 3,
               expects={"work_order_status": ["open", "in_progress"]})]
    body = {"device_id": "phone-1", "device_tz": "Australia/Brisbane", "ops": ops}
    r = maint.post(PUSH, body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [o["status"] for o in out["ops"]] == ["applied"] * 3
    assert out["work_orders"][wo["id"]]["status"] == "closed" and out["server_time"].endswith("Z")
    again = maint.post(PUSH, body).json()
    assert [o["status"] for o in again["ops"]] == ["duplicate"] * 3
    view = maint.post("/api/v1/maintenance/get.work_order", {"id": wo["id"]}).json()
    assert view["notes"].count("Repacked the gland") == 1 and len(view["actions"]) == 1

    assert maint.post(PUSH, {"ops": [{}] * 51}).status_code == 422
    assert maint.post(PUSH, {"nothing": True}).status_code == 422
    assert maint.client.post(PUSH, json=body).status_code == 401
    assert maint.post(PUSH, body, uid=B).status_code == 404                   # not a Maintenance user
    assert maint.post(PUSH, body, token=maint.read_only).status_code == 403


def test_a_queued_photo_sent_twice_is_one_photo(maint):
    from backend.routers.maintenance import get_photo_store

    _pos, wo = _job(maint)
    op = _op("photos.add", {"target_id": wo["id"], "caption": "Gland, before"}, device_id="phone-1")
    hdr = {**_auth(maint.token[A]), "Content-Type": "image/jpeg"}
    url = f"{PHOTO}?op={json.dumps(op)}"
    r = maint.client.post(PHOTO, params={"op": json.dumps(op)}, content=_jpeg(), headers=hdr)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["op"]["status"] == "applied" and first["photo"]["caption"] == "Gland, before"
    assert first["op"]["work_order_id"] == wo["id"] and wo["id"] in first["work_orders"]
    photo_id = first["photo"]["id"]
    assert get_photo_store().get(photo_id, "thumb")
    # The answer was lost: the phone sends the same op and image again (and once more with no body).
    for content in (_jpeg(), b""):
        r = maint.client.post(PHOTO, params={"op": json.dumps(op)}, content=content, headers=hdr)
        assert r.status_code == 200, r.text
        assert r.json()["op"]["status"] == "duplicate" and r.json()["photo"]["id"] == photo_id
    photos = maint.post("/api/v1/maintenance/list.photos", {"target_id": wo["id"]}).json()["photos"]
    assert [p["id"] for p in photos] == [photo_id]
    assert url  # (the op travels as a query parameter)

    # As multipart, as a phone's FormData sends it.
    op2 = _op("photos.add", {"target_id": wo["id"]}, 2)
    r = maint.client.post(PHOTO, params={"op": json.dumps(op2)}, files={"file": ("p.jpg", _jpeg(), "image/jpeg")},
                          headers=_auth(maint.token[A]))
    assert r.status_code == 200 and r.json()["op"]["status"] == "applied"

    # A photo of something that has gone: a decision, and no bytes kept.
    op3 = _op("photos.add", {"target_id": "no-such-thing"}, 3)
    r = maint.client.post(PHOTO, params={"op": json.dumps(op3)}, content=_jpeg(), headers=hdr)
    assert r.status_code == 200 and r.json()["op"]["reason"] == "not_found" and r.json()["photo"] is None
    # Not an image, no op, the wrong command.
    op4 = _op("photos.add", {"target_id": wo["id"]}, 4)
    assert maint.client.post(PHOTO, params={"op": json.dumps(op4)}, content=b"%PDF nope", headers=hdr).status_code == 422
    assert maint.client.post(PHOTO, content=_jpeg(), headers=hdr).status_code == 422
    wrong = _op("work_orders.update", {"work_order_id": wo["id"], "append_note": "x"}, 5)
    assert maint.client.post(PHOTO, params={"op": json.dumps(wrong)}, content=_jpeg(), headers=hdr).status_code == 422
    assert maint.client.post(PHOTO, params={"op": json.dumps(op4)}, content=_jpeg(),
                             headers={**_auth(maint.token[B]), "Content-Type": "image/jpeg"}).status_code == 404


def test_the_routes_are_in_the_spec_and_listing_for_maintenance_users_only(maint):
    spec_a = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    spec_b = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[B])).json()
    assert spec_a["paths"][PUSH]["post"]["x-reliafy-rest-only"] is True and PHOTO in spec_a["paths"]
    assert PUSH not in spec_b["paths"] and PHOTO not in spec_b["paths"]
    names = lambda token: {r["name"] for r in maint.client.get("/api/v1/tools", headers=_auth(token)).json()["rest_only"]}
    assert {"maintenance_sync.push", "maintenance_sync.photo", "maintenance_sync.pack"} <= names(maint.token[A])
    assert not any(n.startswith("maintenance_sync") for n in names(maint.token[B]))
    assert all("maintenance" not in r for r in
               maint.client.get("/api/v1/tools", headers=_auth(maint.token[A])).json()["rest_only"])


def test_a_pack_is_the_open_work_orders_in_full_in_one_answer(maint):
    PACK = "/api/v1/maintenance/sync/pack"
    pos, wo = _job(maint)
    point = maint.post("/api/v1/maintenance/measurements.add_point",
                       {"position_id": pos["id"], "name": "Run hours", "kind": "counter", "unit": "hours"})
    assert point.status_code == 200, point.text
    maint.post("/api/v1/maintenance/measurements.record", {"point_id": point.json()["id"], "value": 120})
    done = maint.post("/api/v1/maintenance/work_orders.open", {"position_id": pos["id"], "title": "Old job"}).json()
    maint.post("/api/v1/maintenance/work_orders.close", {"work_order_id": done["id"], "actions": [{"kind": "repair"}]})
    maint.post("/api/v1/maintenance/parts.create", {"part_number": "GP-12", "name": "Gland packing"})

    r = maint.post(PACK, {})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["unchanged"] is False and out["more"] is False and out["gone"] == []
    assert [b["id"] for b in out["briefs"]] == [wo["id"]] == [w["id"] for w in out["work_orders"]]
    full = out["work_orders"][0]
    assert full["position"]["id"] == pos["id"] and "checklist" in full and "failure_modes" in full
    assert [(p["name"], p["reading"]) for p in full["measurements"]] == [("Run hours", 120)]
    assert [p["part_number"] for p in out["parts"]] == ["GP-12"]
    assert out["today"] and out["server_time"].endswith("Z") and isinstance(out["mark"], int)

    # Nothing has changed: a cheap answer. Anything changes: the pack again.
    assert maint.post(PACK, {"if_mark": out["mark"]}).json() == {
        "unchanged": True, **{k: maint.post(PACK, {"if_mark": out["mark"]}).json()[k]
                              for k in ("mark", "server_time", "today", "time_zone")}}
    maint.post("/api/v1/maintenance/work_orders.update", {"work_order_id": wo["id"], "append_note": "Hello"})
    again = maint.post(PACK, {"if_mark": out["mark"]}).json()
    assert again["unchanged"] is False and again["mark"] > out["mark"]
    assert again["work_orders"][0]["notes"].endswith("Hello")

    # Named jobs: a closed one comes too (the phone shows that it was closed); an unknown one is "gone".
    named = maint.post(PACK, {"work_order_ids": [done["id"], "nope", wo["id"]]}).json()
    assert [w["status"] for w in named["work_orders"]] == ["closed", "open"] and named["gone"] == ["nope"]
    assert [b["id"] for b in named["briefs"]] == [wo["id"]]

    assert maint.post(PACK, {"work_order_ids": "all"}).status_code == 422
    assert maint.client.post(PACK, json={}).status_code == 401
    assert maint.post(PACK, {}, uid=B).status_code == 404
    assert maint.post(PACK, {}, token=maint.read_only).status_code == 200     # a read
