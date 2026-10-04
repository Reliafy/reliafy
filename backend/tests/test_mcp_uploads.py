"""MCP file uploads and imports (#141): create_upload -> PUT /api/uploads/{id}
-> inspect_upload -> import_rbd / import_excel / upload_dataset /
upload_outage_log, with the upload link's security properties (single-use,
expiring, owner-only, size-capped, rate-limited, never logged).

Every file here is built in the test (hand-written Open-PSA and Galileo text,
openpyxl workbooks, Reliafy's own RBD template); no vendor fixtures.
"""

import io
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp import GRAPH as MCP_GRAPH
from backend.tests.test_mcp import _err, _ok, _run
from backend.tests.test_outage_logs import GRAPH as OUTAGE_GRAPH
from backend.tests.test_outage_logs import LOG

A, B = "user-a", "user-b"
FREE = "free-user"

GALILEO = """
toplevel "Sys";
"Sys" or "Ctrl" "Sensors";
"Sensors" 2of3 "S1" "S2" "S3";
"Ctrl" lambda=1e-4;
"S1" lambda=1e-3;
"S2" lambda=1e-3;
"S3" lambda=1e-3;
"""


def _ft(name: str, a: str, b: str) -> str:
    return f"""<define-fault-tree name="{name}">
    <define-gate name="{name}Top"><and><basic-event name="{a}"/><basic-event name="{b}"/></and></define-gate>
  </define-fault-tree>"""


def _event(name: str, rate: float) -> str:
    return (f'<define-basic-event name="{name}"><exponential><float value="{rate}"/>'
            f'<system-mission-time/></exponential></define-basic-event>')


# Two fault trees -> two diagrams.
OPENPSA = f"""<?xml version="1.0"?>
<opsa-mef name="plant">
  {_ft("Cooling", "PumpA", "PumpB")}
  {_ft("Power", "GenA", "GenB")}
  <model-data>
    {_event("PumpA", 1e-4)}{_event("PumpB", 1e-4)}{_event("GenA", 2e-4)}{_event("GenB", 2e-4)}
  </model-data>
</opsa-mef>
"""


def _workbook(sheets: dict) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


LIVES = _workbook({
    "Notes": [["Bearing failures from the 2024 overhaul campaign"], ["Hours are run hours"]],
    "Lives": [["Unit", "Run hours", "Failed?"], *[[f"B{i}", 100 * i + 37, i % 3 == 0] for i in range(1, 13)]],
})

FMEA = _workbook({"FMEA": [
    ["Function", "Functional failure", "Failure mode", "Effect", "Consequence", "Severity"],
    ["Pump water at 50 l/s", "Fails to pump", "Bearing seizes", "Pump stops", "Operational", 7],
    [None, None, "Impeller worn", "Low flow", "Operational", 5],
    [None, "Leaks", "Seal fails", "Water on floor", "Safety", 8],
]})


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://reliafy.example")
    test_db = mongomock.MongoClient()["reliafy_mcp_uploads"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    for uid in (A, B):
        test_db.users.insert_one({"_id": uid, "email": f"{uid}@example.org", "name": uid})

    class Env:
        db = test_db
        token = {uid: tokens.create_token(test_db, uid, "mcp")["token"] for uid in (A, B)}

    return Env


def _call(token, name, args=None):
    async def fn(client):
        return await client.call_tool(name, args or {})

    return _run(token, fn)


def _http():
    from backend.main import app

    return TestClient(app)


def _target(url: str) -> str:
    """The path + query of an upload URL, for the in-process client."""
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


def _upload(env, data: bytes, filename: str, purpose: str = "rbd_import", uid: str = A, method: str = "PUT"):
    link = _ok(_call(env.token[uid], "create_upload", {"purpose": purpose, "filename": filename}))
    r = _http().request(method, _target(link["url"]), content=data,
                        headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    return link, r.json()


def _no_uploads_left(db) -> bool:
    return db.uploads.count_documents({}) == 0 and db.upload_chunks.count_documents({}) == 0


# ---- the link ----------------------------------------------------------------------------

def test_create_upload_gives_a_single_use_link_and_stores_only_a_hash(env):
    from backend.services import uploads

    link = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "plant.rsgz"}))
    assert set(link) >= {"upload_id", "url", "method", "headers", "max_bytes", "expires_at", "curl", "note"}
    assert link["method"] == "PUT" and link["headers"] == {"Content-Type": "application/octet-stream"}
    assert link["url"].startswith(f"https://reliafy.example/api/uploads/{link['upload_id']}?t=")
    token = link["url"].split("?t=", 1)[1]
    assert len(token) >= 43  # 32 random bytes, urlsafe base64
    assert link["curl"] == (f'curl -sS -X PUT --data-binary @plant.rsgz -H "Content-Type: application/octet-stream" '
                            f'"{link["url"]}"')
    assert "single-use and expires in 15 minutes" in link["note"]
    assert "Don't paste the file's contents" in link["note"]
    # 30 MB: under Cloud Run's 32 MiB request limit, below the importer's own 50 MB.
    assert link["max_bytes"] == uploads.HARD_MAX_BYTES == 30 * 1024 * 1024
    expires = datetime.fromisoformat(link["expires_at"])
    assert timedelta(minutes=14) < expires - datetime.now(timezone.utc) <= timedelta(minutes=15)

    doc = env.db.uploads.find_one({"_id": link["upload_id"]})
    assert doc["uid"] == A and doc["purpose"] == "rbd_import" and doc["status"] == "pending"
    assert doc["token_hash"] == uploads.hash_token(token)
    assert token not in str(doc)  # only the hash is stored

    # Limits per purpose: CSV datasets keep the dataset limit; workbooks the Excel one (capped).
    from backend import config

    csv = _ok(_call(env.token[A], "create_upload", {"purpose": "dataset", "filename": "lives.csv"}))
    assert csv["max_bytes"] == config.MAX_UPLOAD_BYTES
    xlsx = _ok(_call(env.token[A], "create_upload", {"purpose": "dataset", "filename": "lives.xlsx"}))
    assert xlsx["max_bytes"] == 30 * 1024 * 1024
    # A declared size over the limit is refused at once.
    msg = _err(_call(env.token[A], "create_upload", {"purpose": "excel", "filename": "big.xlsx",
                                                      "size_bytes": 40 * 1024 * 1024}))
    assert "limited to 30 MB" in msg
    assert _call(env.token[A], "create_upload", {"purpose": "photos", "filename": "x.jpg"}).is_error


def test_create_upload_says_what_to_do_when_the_put_cant_get_through(env):
    """#191: a sandboxed agent's proxy may refuse the PUT. The link, the tool
    description and the server instructions all point at the existing paths:
    paste small text, or the user uploads in the app."""
    from backend import mcp_server

    link = _ok(_call(env.token[A], "create_upload", {"purpose": "dataset", "filename": "lives.csv"}))
    fallback = link["fallback"]
    assert "proxy 403" in fallback and "don't retry" in fallback
    assert "upload_dataset csv" in fallback and "import_rbd content" in fallback and "200 KB" in fallback
    assert fallback.endswith("(Datasets: https://reliafy.example/datasets/list).")
    rbd = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "plant.rsgz"}))
    assert "RBDs › Import: https://reliafy.example/rbds/list" in rbd["fallback"]

    async def tools(client):
        return {t.name: t for t in (await client.list_tools()).tools}

    from backend.tests.test_mcp import _run

    desc = _run(env.token[A], tools)["create_upload"].description
    assert "can't reach" in desc and "upload_dataset / upload_outage_log csv" in desc
    assert "create_upload's fallback" in mcp_server.INSTRUCTIONS


def test_put_stores_the_file_in_chunks_and_reports_its_format(env, monkeypatch):
    import hashlib

    from backend.services import uploads

    monkeypatch.setattr(uploads, "CHUNK_BYTES", 1000)  # several chunks from a small file
    data = OPENPSA.encode() * 3
    link, out = _upload(env, data, "plant.xml")
    assert out["upload_id"] == link["upload_id"] and out["size"] == len(data)
    assert out["sha256"] == hashlib.sha256(data).hexdigest()
    assert out["detected_format"] == "xml" and "import_rbd" in out["next"]
    assert env.db.upload_chunks.count_documents({"upload_id": link["upload_id"]}) == -(-len(data) // 1000)
    doc, back = uploads.read(env.db, link["upload_id"], A)
    assert back == data and doc["status"] == "ready"


@pytest.mark.parametrize("head, fmt", [
    (b"PK\x03\x04....[Content_Types].xml....xl/workbook.xml", "xlsx"),
    (b"\x1f\x8b\x08\x00rest", "rsgz"),
    (b"\x00\x01\x00\x00Standard Jet DB\x00", "rsr"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "xls"),
    (b'<?xml version="1.0"?><opsa-mef/>', "xml"),
    (b'toplevel "T";\n"T" or "A" "B";', "galileo"),
    (b"time,censored\n1,0\n", "csv"),
    (b"just some words", "text"),
    (b"\x00\x00\x00binary", "binary"),
])
def test_detect_format_by_magic_bytes(head, fmt):
    from backend.services import uploads

    assert uploads.detect_format(head) == fmt


# ---- end to end: every diagram format available ------------------------------------------

def test_galileo_upload_inspect_import_then_cleanup(env):
    link, _ = _upload(env, GALILEO.encode(), "sensors.dft")
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    assert seen["kind"] == "diagram_file" and seen["detected_format"] == "galileo"
    assert seen["n_diagrams"] == 1 and seen["diagrams"][0]["n_blocks"] >= 4

    out = _ok(_call(env.token[A], "import_rbd", {"upload_id": link["upload_id"], "name": "Sensor train"}))
    assert out["saved"] is True
    (d,) = out["diagrams"]
    assert d["name"] == "Sensor train" and d["source_format"] == "Galileo DFT"
    assert d["url"].endswith(f"/rbds/b/{d['id']}")
    assert {"S1", "S2", "S3", "Ctrl"} <= {n["label"] for n in d["nodes"]}
    assert "graph" not in d  # lean: never the whole graph
    assert env.db.rbds.find_one({"_id": d["id"], "owner_id": A}) is not None
    assert _no_uploads_left(env.db)  # deleted once imported
    assert "Upload not found" in _err(_call(env.token[A], "import_rbd", {"upload_id": link["upload_id"]}))


def test_open_psa_via_post_preview_then_pick_one(env):
    link, put = _upload(env, OPENPSA.encode(), "plant.xml", method="POST")  # clients that can't PUT
    assert put["detected_format"] == "xml"
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    assert seen["n_diagrams"] == 2

    preview = _ok(_call(env.token[A], "import_rbd", {"upload_id": link["upload_id"], "save": False}))
    assert preview["saved"] is False and len(preview["diagrams"]) == 2 and "Preview only" in preview["note"]
    assert env.db.rbds.count_documents({}) == 0 and env.db.uploads.count_documents({}) == 1  # kept

    names = [d["name"] for d in preview["diagrams"]]
    out = _ok(_call(env.token[A], "import_rbd", {"upload_id": link["upload_id"], "only": [names[1]],
                                                 "format": "openpsa"}))
    assert [d["name"] for d in out["diagrams"]] == [names[1]]
    assert env.db.rbds.count_documents({"owner_id": A}) == 1
    assert _no_uploads_left(env.db)


def test_excel_rbd_template_through_import_excel_and_import_rbd(env):
    from backend.services.rbd_import import excel as rbd_excel

    template = rbd_excel.build_template()
    link, put = _upload(env, template, "skid.xlsx", purpose="excel")
    assert put["detected_format"] == "xlsx"
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    assert seen["kind"] == "workbook"
    sheets = {s["name"]: s for s in seen["sheets"]}
    assert set(sheets) == {"README", "Blocks", "Connections"}
    assert sheets["Blocks"]["columns"][:4] == ["ID", "Name", "Type", "Distribution"]
    assert sheets["Blocks"]["data_rows"] == len(rbd_excel.TEMPLATE_BLOCKS)
    assert "rbd_blocks" in sheets["Blocks"]["looks_like"]
    assert seen["rbd_template"]["n_diagrams"] == 1

    out = _ok(_call(env.token[A], "import_excel", {"upload_id": link["upload_id"], "target": "rbd_template",
                                                   "name": "Pump skid"}))
    assert out["target"] == "rbd_template" and out["saved"] is True
    (d,) = out["diagrams"]
    assert d["name"] == "Pump skid" and "Pump A" in {n["label"] for n in d["nodes"]}
    assert _no_uploads_left(env.db)

    # import_rbd takes a template workbook too.
    link2, _ = _upload(env, template, "skid.xlsx", purpose="rbd_import")
    again = _ok(_call(env.token[A], "import_rbd", {"upload_id": link2["upload_id"]}))
    assert again["diagrams"][0]["source_format"] == "Excel"
    assert env.db.rbds.count_documents({"owner_id": A}) == 2


def test_import_excel_with_rbd_id_saves_a_copy_unless_replace(env):
    """import_excel with rbd_id used to overwrite that diagram. It now saves
    a new copy (the original unchanged), as the app's import always opens a
    new diagram; replace=true overwrites, and the result says which."""
    from backend.services import rbds as rbds_service
    from backend.services.rbd_import import excel as rbd_excel

    template = rbd_excel.build_template()
    mine = {"id": rbds_service.save_rbd(env.db, "Skid", MCP_GRAPH, A).id}
    before = env.db.rbds.find_one({"_id": mine["id"]})
    n0 = env.db.rbds.count_documents({"owner_id": A})

    link, _ = _upload(env, template, "skid.xlsx", purpose="excel")
    out = _ok(_call(env.token[A], "import_excel", {"upload_id": link["upload_id"], "target": "rbd_template",
                                                   "rbd_id": mine["id"]}))
    assert out["action"] == "copied" and out["copy_of"] == mine["id"] and out["id"] != mine["id"]
    assert "replaced" not in out and "unchanged" in out["note"] and "replace=true" in out["note"]
    (d,) = out["diagrams"]
    assert d["id"] == out["id"] and d["name"] == "Skid (copy)"
    assert env.db.rbds.count_documents({"owner_id": A}) == n0 + 1
    assert env.db.rbds.find_one({"_id": mine["id"]})["graph"] == before["graph"]  # untouched

    link2, _ = _upload(env, template, "skid.xlsx", purpose="excel")
    out = _ok(_call(env.token[A], "import_excel", {"upload_id": link2["upload_id"], "target": "rbd_template",
                                                   "rbd_id": mine["id"], "replace": True}))
    assert out["action"] == "replaced" and out["replaced"] == out["id"] == mine["id"]
    assert out["diagrams"][0]["id"] == mine["id"] and out["diagrams"][0]["name"] == "Skid"
    assert env.db.rbds.count_documents({"owner_id": A}) == n0 + 1
    assert env.db.rbds.find_one({"_id": mine["id"]})["graph"] != before["graph"]

    link3, _ = _upload(env, template, "skid.xlsx", purpose="excel")
    assert "replace applies with rbd_id" in _err(_call(env.token[A], "import_excel", {
        "upload_id": link3["upload_id"], "target": "rbd_template", "replace": True}))


@pytest.mark.parametrize("name, fmt", [("blocksim_example1_V20.rsgz20", "rsgz"),
                                       ("blocksim_example1_V9.rsr9", "rsr")])
def test_blocksim_project_end_to_end(env, name, fmt):
    """ReliaSoft's public example (gitignored; skipped when absent — see
    backend/scripts/fetch_rbd_import_fixtures.py)."""
    from backend.tests.test_rbd_import_blocksim import EXT

    path = EXT / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    link, put = _upload(env, path.read_bytes(), name)
    assert put["detected_format"] == fmt
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    assert "Storage Cluster System" in [d["name"] for d in seen["diagrams"]]
    out = _ok(_call(env.token[A], "import_rbd", {"upload_id": link["upload_id"], "only": ["Storage Cluster System"]}))
    (d,) = out["diagrams"]
    assert d["source_format"] == "ReliaSoft BlockSim" and d["n_blocks"] == 10
    assert _no_uploads_left(env.db)


def test_import_rbd_explains_an_unrecognised_workbook(env):
    link, _ = _upload(env, LIVES, "lives.xlsx", purpose="excel")
    msg = _err(_call(env.token[A], "import_rbd", {"upload_id": link["upload_id"]}))
    assert "target=rbd_template" in msg and "“Lives”" in msg and "Run hours" in msg
    assert env.db.uploads.count_documents({}) == 1  # a failed import keeps the upload


# ---- inline content ------------------------------------------------------------------------

def test_inline_content_for_small_text_formats(env):
    out = _ok(_call(env.token[A], "import_rbd", {"content": GALILEO}))
    assert out["saved"] and out["diagrams"][0]["source_format"] == "Galileo DFT"
    out = _ok(_call(env.token[A], "import_rbd", {"content": OPENPSA, "format": "openpsa", "save": False}))
    assert len(out["diagrams"]) == 2 and not out["saved"]

    big = GALILEO + "// padding\n" * 20_000
    assert len(big.encode()) > 200 * 1024
    msg = _err(_call(env.token[A], "import_rbd", {"content": big}))
    assert "limited to 200 KB" in msg and "create_upload" in msg
    assert "binary" in _err(_call(env.token[A], "import_rbd", {"content": "x", "format": "blocksim"}))
    assert "exactly one" in _err(_call(env.token[A], "import_rbd", {}))
    assert "Unrecognised file" in _err(_call(env.token[A], "import_rbd", {"content": "hello world"}))


PUMPS_DFT = """
toplevel "System";
"System" or "Pumps" "MCC" "Valve";
"Pumps" and "PA" "PB";
"PA" lambda=1e-4; "PB" lambda=1e-4; "MCC" lambda=1e-5; "Valve" lambda=2e-5;
"""


def test_import_preview_shows_the_structure_and_asks_for_the_unit(env):
    """#187: a preview is enough to check the conversion (structure, edges,
    minimal cut sets), and a file with no unit is flagged, not left blank."""
    preview = _ok(_call(env.token[A], "import_rbd", {"content": PUMPS_DFT, "save": False}))
    (d,) = preview["diagrams"]
    assert d["structure"] == "(PA ∥ PB) → MCC → Valve"
    assert d["minimal_cut_sets"] == [["MCC"], ["Valve"], ["PA", "PB"]] and d["n_cut_sets"] == 3
    assert "input -> PA" in d["edges"] and len(d["edges"]) == 6
    assert d["unit"] == "" and "Ask the user" in d["unit_warning"] and "time_unit" in d["unit_warning"]
    assert "doesn't state a time unit" in d["import_notes"][0]

    out = _ok(_call(env.token[A], "import_rbd", {"content": PUMPS_DFT, "time_unit": "Hours"}))
    (d,) = out["diagrams"]
    assert d["unit"] == "Hours" and "unit_warning" not in d
    assert d["structure"] == "(PA ∥ PB) → MCC → Valve"
    assert "edges" not in d and "minimal_cut_sets" not in d  # the saved answer stays lean
    assert "read as per Hours" in d["import_notes"][0]
    assert env.db.rbds.find_one({"_id": d["id"]})["graph"]["unit"] == "Hours"


def test_open_psa_fixed_probability_events_import_as_blocks_needing_a_model(env):
    """#188: a fixed-probability basic event no longer rejects the file. It
    becomes a block with no life model, listed in needs_model; the rest of
    the tree imports as usual and nothing is invented."""
    xml = ('<opsa-mef><define-gate name="Top"><or><gate name="Pumps"/><basic-event name="MCC"/></or>'
           '</define-gate><define-gate name="Pumps"><and><basic-event name="PA"/><basic-event name="PB"/>'
           '</and></define-gate><define-basic-event name="MCC"><float value="0.01"/></define-basic-event>'
           + _event("PA", 1e-4) + _event("PB", 1e-4) + "</opsa-mef>")
    out = _ok(_call(env.token[A], "import_rbd", {"content": xml, "format": "openpsa", "time_unit": "Hours"}))
    assert out["saved"] is True
    (d,) = out["diagrams"]
    assert d["analysable"] is False and d["needs_model"] == ["MCC"] and "Don't invent" in d["needs_model_note"]
    assert any("fixed probability" in n and "“MCC” (p = 0.01)" in n for n in d["import_notes"])
    assert d["structure"] == "(PA ∥ PB) → MCC"
    saved = env.db.rbds.find_one({"_id": d["id"]})["graph"]
    (mcc,) = [n for n in saved["nodes"] if n["data"].get("label") == "MCC"]
    assert "model" not in mcc["data"]


def test_galileo_prob_events_import_as_blocks_needing_a_model(env):
    """Galileo ``prob=`` events get the same treatment as Open-PSA's: saved as
    a block with no life model, listed in needs_model; nothing invented."""
    dft = PUMPS_DFT.replace('"MCC" lambda=1e-5;', '"MCC" prob=0.01;')
    out = _ok(_call(env.token[A], "import_rbd", {"content": dft, "format": "galileo", "time_unit": "Hours"}))
    assert out["saved"] is True
    (d,) = out["diagrams"]
    assert d["analysable"] is False and d["needs_model"] == ["MCC"] and "Don't invent" in d["needs_model_note"]
    assert any("fixed probability" in n and "“MCC” (p = 0.01)" in n for n in d["import_notes"])
    assert d["structure"] == "(PA ∥ PB) → MCC → Valve"
    saved = env.db.rbds.find_one({"_id": d["id"]})["graph"]
    (mcc,) = [n for n in saved["nodes"] if n["data"].get("label") == "MCC"]
    assert "model" not in mcc["data"]
    assert "isn't between 0 and 1" in _err(_call(env.token[A], "import_rbd", {
        "content": dft.replace("prob=0.01", "prob=1.01"), "format": "galileo"}))


# ---- Excel targets -------------------------------------------------------------------------

def test_excel_dataset_needs_a_sheet_then_maps_columns(env):
    link, _ = _upload(env, LIVES, "bearings.xlsx", purpose="excel")
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    lives = next(s for s in seen["sheets"] if s["name"] == "Lives")
    assert lives["columns"] == ["Unit", "Run hours", "Failed?"] and lives["data_rows"] == 12
    assert len(lives["sample_rows"]) == 3

    msg = _err(_call(env.token[A], "import_excel", {"upload_id": link["upload_id"], "target": "dataset"}))
    assert "several sheets" in msg and "“Lives” (13 rows: Unit, Run hours, Failed?)" in msg
    msg = _err(_call(env.token[A], "import_excel", {"upload_id": link["upload_id"], "target": "dataset",
                                                    "sheet": "Lives", "mapping": {"time": "Hours"}}))
    assert "no column “Hours”" in msg and "Run hours" in msg

    out = _ok(_call(env.token[A], "import_excel", {
        "upload_id": link["upload_id"], "target": "dataset", "sheet": "Lives",
        "mapping": {"time": "Run hours", "failed": "Failed?"}}))
    assert out["target"] == "dataset" and out["sheet"] == "Lives"
    assert out["columns"] == ["time", "failed"] and out["n_rows"] == 12
    assert out["name"] == "bearings - Lives" and out["url"].endswith(f"/datasets/d/{out['id']}")
    assert set(out) >= {"id", "name", "n_rows", "columns", "preview", "url"}  # as upload_dataset
    assert _no_uploads_left(env.db)


def test_excel_rcm_worksheet_into_a_new_then_an_existing_study(env):
    link, _ = _upload(env, FMEA, "pump-fmea.xlsx", purpose="excel")
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    assert seen["sheets"][0]["looks_like"]["rcm"]["mode"] == "Failure mode"

    out = _ok(_call(env.token[A], "import_excel", {"upload_id": link["upload_id"], "target": "rcm",
                                                   "name": "Cooling water pump"}))
    assert out["target"] == "rcm" and out["appended"] is False
    assert out["counts"]["functions"] == 1 and out["counts"]["failures"] == 2 and out["counts"]["modes"] == 3
    assert out["mapping"]["mode"] == "Failure mode" and "Severity" in out["extra_columns"]
    assert out["url"].endswith(f"/rcm/studies/{out['study_id']}")
    study = env.db.rcm_studies.find_one({"_id": out["study_id"]})
    assert study["owner_id"] == A and study["name"] == "Cooling water pump"
    assert _no_uploads_left(env.db)

    # Into the existing study (appended), with an explicit mapping.
    link2, _ = _upload(env, FMEA, "pump-fmea.xlsx", purpose="excel")
    out2 = _ok(_call(env.token[A], "import_excel", {
        "upload_id": link2["upload_id"], "target": "rcm", "study_id": out["study_id"],
        "mapping": {"mode": "Failure mode", "effects": "Effect"}}))
    assert out2["appended"] is True and out2["study_id"] == out["study_id"]
    assert len(env.db.rcm_studies.find_one({"_id": out["study_id"]})["functions"]) == 2
    assert env.db.rcm_studies.count_documents({}) == 1

    # A worksheet with no failure-mode column asks for a mapping.
    link3, _ = _upload(env, LIVES, "x.xlsx", purpose="excel")
    msg = _err(_call(env.token[A], "import_excel", {"upload_id": link3["upload_id"], "target": "rcm",
                                                    "sheet": "Lives"}))
    assert "failure modes" in msg and "Run hours" in msg
    # Another user's study can't be imported into.
    link4, _ = _upload(env, FMEA, "f.xlsx", purpose="excel", uid=B)
    assert "not found" in _err(_call(env.token[B], "import_excel", {
        "upload_id": link4["upload_id"], "target": "rcm", "study_id": out["study_id"]}))


def test_import_excel_refuses_non_workbooks_and_misplaced_ids(env):
    link, _ = _upload(env, b"time,c\n1,0\n2,0\n", "x.csv", purpose="dataset")
    assert "isn't an Excel workbook" in _err(_call(env.token[A], "import_excel", {
        "upload_id": link["upload_id"], "target": "dataset"}))
    link2, _ = _upload(env, FMEA, "f.xlsx", purpose="excel")
    assert "study_id applies to target rcm" in _err(_call(env.token[A], "import_excel", {
        "upload_id": link2["upload_id"], "target": "dataset", "study_id": "x"}))


# ---- upload_dataset / upload_outage_log ---------------------------------------------------

def test_upload_dataset_from_a_csv_or_workbook_upload(env):
    csv = "time,censored\n120,0\n340,0\n510,1\n700,0\n"
    link, put = _upload(env, csv.encode(), "lives.csv", purpose="dataset")
    assert put["detected_format"] == "csv"
    seen = _ok(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))
    assert seen["kind"] == "table" and seen["columns"] == ["time", "censored"] and seen["rows"] == 4

    out = _ok(_call(env.token[A], "upload_dataset", {"name": "Bearings", "upload_id": link["upload_id"]}))
    assert out["columns"] == ["time", "censored"] and out["n_rows"] == 4
    assert _no_uploads_left(env.db)

    link2, _ = _upload(env, LIVES, "lives.xlsx", purpose="dataset")
    assert "several sheets" in _err(_call(env.token[A], "upload_dataset", {"name": "x",
                                                                            "upload_id": link2["upload_id"]}))
    out = _ok(_call(env.token[A], "upload_dataset", {"name": "Bearings 2", "upload_id": link2["upload_id"],
                                                     "sheet": "Lives"}))
    assert out["columns"] == ["Unit", "Run hours", "Failed?"] and out["n_rows"] == 12

    # Same validation as pasted CSV.
    link3, _ = _upload(env, b"just one column\n1\n2\n", "bad.csv", purpose="dataset")
    assert "Only one column" in _err(_call(env.token[A], "upload_dataset", {"name": "x",
                                                                             "upload_id": link3["upload_id"]}))
    assert "exactly one" in _err(_call(env.token[A], "upload_dataset", {"name": "x", "csv": csv,
                                                                         "upload_id": link3["upload_id"]}))
    link4, _ = _upload(env, GALILEO.encode(), "s.dft", purpose="dataset")
    assert "not a table" in _err(_call(env.token[A], "upload_dataset", {"name": "x",
                                                                         "upload_id": link4["upload_id"]}))


def test_upload_outage_log_from_an_upload(env):
    from backend.services import rbds as rbds_service

    rbd = rbds_service.save_rbd(env.db, "Plant", OUTAGE_GRAPH, A)
    rows = [line.split(",") for line in LOG.strip().splitlines()]
    book = _workbook({"Cover": [["Outage log, site 4"]], "Outages": rows})
    link, _ = _upload(env, book, "outages.xlsx", purpose="outage_log")
    out = _ok(_call(env.token[A], "upload_outage_log", {
        "rbd_id": rbd.id, "upload_id": link["upload_id"], "sheet": "Outages",
        "window_start": "0", "window_end": "1000"}))
    assert out["n_outages"] == 9 and out["history"]["kpis"]["availability"] == pytest.approx(0.91)
    assert _no_uploads_left(env.db)

    link2, _ = _upload(env, LOG.encode(), "outages.csv", purpose="outage_log")
    out = _ok(_call(env.token[A], "upload_outage_log", {"rbd_id": rbd.id, "upload_id": link2["upload_id"],
                                                        "window_start": "0", "window_end": "1000"}))
    assert out["n_outages"] == 9
    assert "exactly one" in _err(_call(env.token[A], "upload_outage_log", {"rbd_id": rbd.id}))


# ---- the link's security ------------------------------------------------------------------

def test_token_is_single_use_and_checked(env):
    link = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "s.dft"}))
    upload_id, token = link["upload_id"], link["url"].split("?t=", 1)[1]
    client = _http()
    wrong = client.put(f"/api/uploads/{upload_id}?t={token[:-2]}xx", content=b"x")
    missing = client.put(f"/api/uploads/{upload_id}", content=b"x")
    nobody = client.put(f"/api/uploads/not-an-upload?t={token}", content=b"x")
    assert wrong.status_code == missing.status_code == nobody.status_code == 404
    assert wrong.json() == nobody.json()  # a wrong token and a missing upload look the same
    assert env.db.uploads.find_one({"_id": upload_id})["status"] == "pending"

    assert client.put(_target(link["url"]), content=GALILEO.encode()).status_code == 200
    again = client.put(_target(link["url"]), content=b"other bytes")
    assert again.status_code == 409 and "already been used" in again.json()["detail"]
    assert client.post(_target(link["url"]), content=b"other bytes").status_code == 409
    assert "no-store" in again.headers["cache-control"]


def test_expired_link_is_refused(env):
    link = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "s.dft"}))
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    env.db.uploads.update_one({"_id": link["upload_id"]}, {"$set": {"expires_at": past}})
    r = _http().put(_target(link["url"]), content=GALILEO.encode())
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert "before its link expired" in _err(_call(env.token[A], "inspect_upload",
                                                   {"upload_id": link["upload_id"]}))


def test_upload_is_private_to_its_creator(env):
    link, _ = _upload(env, GALILEO.encode(), "s.dft")
    for tool, args in [("inspect_upload", {}), ("import_rbd", {}), ("upload_dataset", {"name": "x"}),
                       ("import_excel", {"target": "dataset"})]:
        msg = _err(_call(env.token[B], tool, {"upload_id": link["upload_id"], **args}))
        assert "Upload not found" in msg, tool
    assert env.db.rbds.count_documents({}) == 0 and env.db.uploads.count_documents({}) == 1
    # Not yet sent: the tools say what to do.
    pending = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "s.dft"}))
    assert "hasn't arrived yet" in _err(_call(env.token[A], "import_rbd", {"upload_id": pending["upload_id"]}))


def test_size_cap_413_declared_and_streamed_then_retry(env):
    link = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "s.dft"}))
    env.db.uploads.update_one({"_id": link["upload_id"]}, {"$set": {"max_bytes": 1000}})
    client = _http()
    declared = client.put(_target(link["url"]), content=b"x" * 1001)
    assert declared.status_code == 413 and declared.json()["max_bytes"] == 1000

    def chunks():  # no Content-Length: counted as it streams
        yield b"y" * 600
        yield b"y" * 600

    streamed = client.put(_target(link["url"]), content=chunks())
    assert streamed.status_code == 413
    assert env.db.upload_chunks.count_documents({}) == 0  # what arrived is dropped
    assert env.db.uploads.find_one({"_id": link["upload_id"]})["status"] == "pending"
    assert client.put(_target(link["url"]), content=b"").status_code == 400  # empty
    ok = client.put(_target(link["url"]), content=GALILEO.encode())  # the link still works
    assert ok.status_code == 200 and ok.json()["size"] == len(GALILEO.encode())


def test_rate_limited_per_upload_and_per_ip(env, monkeypatch):
    from backend.services import uploads

    monkeypatch.setattr(uploads, "UPLOAD_ATTEMPTS", 3)
    link = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "s.dft"}))
    client = _http()
    bad = f"/api/uploads/{link['upload_id']}?t=wrong"
    assert [client.put(bad, content=b"x").status_code for _ in range(3)] == [404] * 3
    r = client.put(_target(link["url"]), content=GALILEO.encode())  # even the right token now waits
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0

    monkeypatch.setattr(uploads, "IP_ATTEMPTS", 4)  # this client has used 4 already
    other = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "s.dft"}))
    assert client.put(_target(other["url"]), content=GALILEO.encode()).status_code == 429


def test_token_never_reaches_usage_events_or_access_log(env, monkeypatch, caplog):
    import logging

    from backend import config
    from backend.main import _RedactUploadTokens

    monkeypatch.setattr(config, "USAGE_LOGGING", True)
    link, _ = _upload(env, GALILEO.encode(), "s.dft")
    token = link["url"].split("?t=", 1)[1]
    events = list(env.db.usage_events.find({}, {"_id": 0}))
    put = [e for e in events if e["feature"] == "upload_put"]
    assert len(put) == 1 and put[0]["uid"] == A and put[0]["channel"] == "mcp" and put[0]["outcome"] == "ok"
    assert {"create_upload"} <= {e["feature"] for e in events}
    assert token not in str(events) and link["upload_id"] not in str(events)

    # uvicorn's access log line for the PUT has the token redacted.
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "PUT", _target(link["url"]), "1.1", 200), None)
    assert _RedactUploadTokens().filter(record) is True
    line = record.getMessage()
    assert token not in line and "?t=[redacted]" in line and link["upload_id"] in line
    assert any(isinstance(f, _RedactUploadTokens) for f in logging.getLogger("uvicorn.access").filters)
    # Nor in the app's own log lines (the test's HTTP client logs its own requests; that's not ours).
    with caplog.at_level(logging.DEBUG):
        _upload(env, GALILEO.encode(), "s2.dft")
    ours = [r.getMessage() for r in caplog.records if r.name.startswith(("backend", "uvicorn", "mcp"))]
    assert any("received" in m for m in ours)
    assert not any("?t=" in m for m in ours)


def test_ttl_indexes_exist(env):
    from backend.db import init_db

    init_db()
    for coll in ("uploads", "upload_chunks"):
        info = env.db[coll].index_information()
        ttl = [i for i in info.values() if i.get("key") == [("delete_at", 1)]]
        assert ttl and ttl[0]["expireAfterSeconds"] == 0, coll
    link, _ = _upload(env, GALILEO.encode(), "s.dft")
    doc = env.db.uploads.find_one({"_id": link["upload_id"]})
    left = doc["delete_at"].replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(minutes=59) < left <= timedelta(hours=1)  # an hour after it arrived
    chunk = env.db.upload_chunks.find_one({"upload_id": link["upload_id"]})
    assert chunk["delete_at"] is not None
    # Past delete_at (before Mongo's TTL monitor runs) it's already gone for the tools.
    env.db.uploads.update_one({"_id": link["upload_id"]},
                              {"$set": {"delete_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert "Upload not found" in _err(_call(env.token[A], "inspect_upload", {"upload_id": link["upload_id"]}))


def test_privacy_page_states_the_upload_retention():
    """The privacy policy states the upload store's real retention: the link
    works 15 minutes, a file is deleted once imported or an hour after it
    arrived. Change the TTLs and this fails until the policy says so too."""
    from pathlib import Path

    from backend.services import uploads

    assert uploads.TOKEN_TTL == timedelta(minutes=15)
    assert uploads.KEEP_AFTER_UPLOAD == timedelta(hours=1)
    page = (Path(__file__).resolve().parents[2] / "frontend/src/views/PrivacyPage.jsx").read_text()
    text = " ".join(page.split())
    assert "Files you upload to import:</strong> used only to import them." in text
    assert "(which works for 15 minutes)" in text
    assert "deleted as soon as it's imported, or automatically an hour after it arrived" in text
    assert "read during the import and not stored" in text


# ---- the RBD cap: all or nothing --------------------------------------------------------------

@pytest.fixture()
def free_env(env, monkeypatch):
    """Billing on, and a Free user signed in through OAuth (as Claude's connector)."""
    from backend import config
    from backend.services import oauth as oauth_service

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    env.db.users.insert_one({"_id": FREE, "email": "free@example.org", "name": "Free"})
    env.token[FREE] = oauth_service._issue(
        env.db, family_id="fam-free", uid=FREE, client_id="https://claude.ai/test", client_name="Claude",
        scopes=["mcp"], res=oauth_service.resource(), grant_created_at=datetime.now(timezone.utc))["access_token"]
    return env


def test_rbd_cap_is_all_or_nothing(free_env, monkeypatch):
    from backend import config
    from backend.services import rbds as rbds_service

    env = free_env
    monkeypatch.setattr(config, "FREE_MAX_RBDS", 2)
    rbds_service.save_rbd(env.db, "Existing", MCP_GRAPH, FREE)
    link, _ = _upload(env, OPENPSA.encode(), "plant.xml", uid=FREE)  # two diagrams, room for one
    result = _call(env.token[FREE], "import_rbd", {"upload_id": link["upload_id"]})
    msg = _err(result)
    assert "would save 2 RBDs" in msg and "allows 2 and you have 1" in msg and "nothing was saved" in msg
    assert env.db.rbds.count_documents({"owner_id": FREE}) == 1
    assert env.db.uploads.count_documents({"_id": link["upload_id"]}) == 1  # kept, to retry with only=

    names = [d["name"] for d in _ok(_call(env.token[FREE], "import_rbd", {
        "upload_id": link["upload_id"], "save": False}))["diagrams"]]
    out = _ok(_call(env.token[FREE], "import_rbd", {"upload_id": link["upload_id"], "only": names[:1]}))
    assert len(out["diagrams"]) == 1 and env.db.rbds.count_documents({"owner_id": FREE}) == 2



def test_upload_links_can_point_straight_at_cloud_run(env, monkeypatch):
    """UPLOAD_BASE_URL sends the PUT around the Firebase Hosting proxy."""
    from backend import config
    monkeypatch.setattr(config, "UPLOAD_BASE_URL", "https://reliafy-123.australia-southeast1.run.app")
    out = _ok(_call(env.token[A], "create_upload", {"purpose": "rbd_import", "filename": "x.xml"}))
    assert out["url"].startswith("https://reliafy-123.australia-southeast1.run.app/api/uploads/")
    assert out["url"] in out["curl"]
