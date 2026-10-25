"""uploads send_part: a file sent through the MCP connection itself, in base64
parts, for agents whose sandbox can't reach the upload URL (an egress proxy
refusing both hosts). The parts fill the same upload slot the HTTP PUT would,
so get kind upload and the import tools take the upload_id unchanged."""

import base64
import hashlib

import pytest

from backend.tests.test_mcp import _err, _ok, _run
from backend.tests.test_mcp_uploads import A, B, FMEA, FREE, GALILEO, _call, _http, _target, _upload, env, free_env  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _parts(env, link: dict, data: bytes, size: int, uid: str = A, sha: bool = True) -> dict:
    pieces = [data[i:i + size] for i in range(0, len(data), size)]
    out = None
    for i, piece in enumerate(pieces):
        last = i == len(pieces) - 1
        args = {"upload_id": link["upload_id"], "part_index": i, "data_base64": _b64(piece), "last": last}
        if last and sha:
            args["sha256"] = hashlib.sha256(data).hexdigest()
        out = _ok(_call(env.token[uid], "uploads", {"action": "send_part", **args}))
        assert out["done"] is last
    return out


def test_a_workbook_in_parts_imports_as_if_put(env):
    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "excel", "filename": "pump-fmea.xlsx"}))
    out = _parts(env, link, FMEA, 1000)
    assert out["size"] == len(FMEA) and out["sha256"] == hashlib.sha256(FMEA).hexdigest()
    assert out["detected_format"] == "xlsx" and "import_excel" in out["next"]
    assert out["parts_received"] == -(-len(FMEA) // 1000)

    seen = _ok(_call(env.token[A], "get", {"kind": "upload", "id": link["upload_id"]}))
    assert seen["sheets"][0]["looks_like"]["rcm"]["mode"] == "Failure mode"
    sheet = _ok(_call(env.token[A], "uploads", {"action": "import_excel", "upload_id": link["upload_id"],
                                                "target": "dataset"}))
    assert sheet["target"] == "dataset"
    assert env.db.uploads.count_documents({}) == 0 and env.db.upload_chunks.count_documents({}) == 0


def test_parts_can_arrive_out_of_order_and_be_resent(env):
    data = GALILEO.encode()
    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "rbd_import", "filename": "sys.dft"}))
    one, two, three = data[:50], data[50:100], data[100:]

    def send(i, piece, last=False):
        return _call(env.token[A], "uploads", {"action": "send_part", "upload_id": link["upload_id"], "part_index": i,
                                                        "data_base64": _b64(piece), "last": last})

    _ok(send(1, b"garbage that will be replaced"))
    _ok(send(1, two))  # sent again: replaces itself
    # The last part before all the others are in says which are missing.
    assert "Part 0 hasn't arrived" in _err(send(2, three, last=True))
    _ok(send(0, one))
    done = _ok(send(2, three, last=True))
    assert done["done"] and done["size"] == len(data) and done["detected_format"] == "galileo"
    from backend.services import uploads

    assert uploads.read(env.db, link["upload_id"], A)[1] == data
    out = _ok(_call(env.token[A], "uploads", {"action": "import_rbd", "upload_id": link["upload_id"], "save": False}))
    assert out["diagrams"][0]["name"].lower() == "sys"


def test_the_put_and_the_parts_cant_both_fill_one_upload(env):
    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "rbd_import", "filename": "sys.dft"}))
    _ok(_call(env.token[A], "uploads", {"action": "send_part", "upload_id": link["upload_id"], "part_index": 0,
                                                 "data_base64": _b64(b"toplevel"), "last": False}))
    r = _http().put(_target(link["url"]), content=GALILEO.encode())
    assert r.status_code == 409 and "already being sent" in r.json()["detail"]
    # And the other way round: an upload the PUT filled takes no parts.
    link2, _ = _upload(env, GALILEO.encode(), "sys.dft")
    msg = _err(_call(env.token[A], "uploads", {"action": "send_part", "upload_id": link2["upload_id"], "part_index": 0,
                                                        "data_base64": _b64(b"x"), "last": True}))
    assert "already complete" in msg
    # Waiting for the rest is said plainly to the import tools.
    assert "remaining parts with uploads send_part" in _err(_call(env.token[A], "uploads",
                                                                 {"action": "import_rbd",
                                                                  "upload_id": link["upload_id"]}))


def test_a_wrong_checksum_drops_the_parts_so_they_can_be_sent_again(env):
    data = GALILEO.encode()
    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "rbd_import", "filename": "sys.dft"}))
    msg = _err(_call(env.token[A], "uploads", {"action": "send_part",
        "upload_id": link["upload_id"], "part_index": 0, "data_base64": _b64(data), "last": True,
        "sha256": hashlib.sha256(b"something else").hexdigest()}))
    assert "don't match the sha256" in msg
    assert env.db.upload_chunks.count_documents({}) == 0
    assert env.db.uploads.find_one({"_id": link["upload_id"]})["status"] == "pending"
    assert _parts(env, link, data, 40)["done"]


def test_parts_are_private_capped_and_checked(env, monkeypatch):
    from backend.services import uploads

    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "rbd_import", "filename": "sys.dft"}))
    part = {"upload_id": link["upload_id"], "part_index": 0, "data_base64": _b64(b"abc"), "last": False}
    # Someone else's upload is "not found".
    assert "not found" in _err(_call(env.token[B], "uploads", {"action": "send_part", **part}))
    assert "not found" in _err(_call(env.token[A], "uploads", {"action": "send_part", **part, "upload_id": "nope"}))
    # Not base64.
    assert "isn't valid base64" in _err(_call(env.token[A], "uploads", {"action": "send_part", **part,
                                                                        "data_base64": "%%%"}))
    # URL-safe base64, line breaks and missing padding are all fine.
    raw = bytes(range(256)) * 3
    loose = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert uploads.decode_part(loose[:40] + "\n" + loose[40:]) == raw
    # The part and the file size caps.
    monkeypatch.setattr(uploads, "PART_MAX_BYTES", 10)
    assert "at most 0 KB" in _err(_call(env.token[A], "uploads", {"action": "send_part", **part,
                                                                  "data_base64": _b64(b"x" * 11)}))
    monkeypatch.setattr(uploads, "PART_MAX_BYTES", 1024)
    env.db.uploads.update_one({"_id": link["upload_id"]}, {"$set": {"max_bytes": 100}})
    _ok(_call(env.token[A], "uploads", {"action": "send_part", **part, "data_base64": _b64(b"x" * 60)}))
    msg = _err(_call(env.token[A], "uploads", {"action": "send_part", **part, "part_index": 1,
                                               "data_base64": _b64(b"x" * 60)}))
    assert "larger than this upload allows" in msg
    assert env.db.upload_chunks.count_documents({}) == 0  # dropped; the slot can be used again
    # A part index past the last part: and last=true must be on the highest part.
    _ok(_call(env.token[A], "uploads", {"action": "send_part", **part, "part_index": 3}))
    assert "can't be the last" in _err(_call(env.token[A], "uploads", {"action": "send_part", **part, "last": True}))


def test_the_first_part_must_arrive_while_the_link_lasts(env):
    from datetime import datetime, timedelta, timezone

    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "rbd_import", "filename": "sys.dft"}))
    env.db.uploads.update_one({"_id": link["upload_id"]},
                              {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert "expired before any of the file arrived" in _err(_call(env.token[A], "uploads", {"action": "send_part",
        "upload_id": link["upload_id"], "part_index": 0, "data_base64": _b64(b"abc"), "last": True}))


def test_parts_dont_count_against_the_free_allowance(free_env):
    env = free_env
    link = _ok(_call(env.token[FREE], "uploads", {"action": "create", "purpose": "rbd_import", "filename": "sys.dft"}))
    before = _ok(_call(env.token[FREE], "get", {"kind": "account"}))["tool_calls"]["used"]
    assert before == 1  # uploads create counted
    _parts(env, link, GALILEO.encode(), 30, uid=FREE)
    assert _ok(_call(env.token[FREE], "get", {"kind": "account"}))["tool_calls"]["used"] == before


def test_the_fallback_and_guide_name_the_in_connection_route(env):
    from backend import mcp_guide

    link = _ok(_call(env.token[A], "uploads", {"action": "create", "purpose": "excel", "filename": "fmea.xlsx"}))
    assert "uploads send_part" in link["fallback"] and "target rcm" in link["fallback"]
    guide = mcp_guide.TOPICS["uploads"][1]
    assert "uploads send_part" in guide and "target rcm" in guide

    async def tools(client):
        return {t.name: t for t in (await client.list_tools()).tools}

    listed = _run(env.token[A], tools)
    assert "send_part(" in listed["uploads"].description
    # Each part fits well inside one MCP request.
    from backend import config
    from backend.services import uploads

    schema = listed["uploads"].input_schema["properties"]["data_base64"]["anyOf"][0]  # or null
    assert uploads.PART_MAX_BYTES * 4 // 3 < schema["maxLength"] < config.MAX_REQUEST_BYTES // 4
