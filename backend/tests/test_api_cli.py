"""The Python client and the ``reliafy`` command (python/reliafy) against a
real local server: the app on a free port in a thread, auth on, API tokens."""

import matplotlib

matplotlib.use("Agg")

import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import mongomock
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python"))

from reliafy import Client, ServerTooOld, cli  # noqa: E402

UID, OTHER = "user-cli", "user-other"
WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]

pytestmark = pytest.mark.usefixtures("mcp_on")


@pytest.fixture()
def server(monkeypatch, tmp_path):
    import uvicorn

    from backend import config, db
    from backend.main import app
    from backend.maintenance import documents, mcp_tools, photos
    from backend.maintenance.service import PROJECTORS
    from backend.maintenance.store import GraphStore
    from backend.routers import ingest as ingest_router
    from backend.routers import maintenance as router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"cli@example.org"})
    test_db = mongomock.MongoClient()["reliafy_cli"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path / "photos")))
    monkeypatch.setattr(router, "_document_store", documents.FileDocumentStore(str(tmp_path / "documents")))
    ingest_router._hits.clear()
    test_db.users.insert_one({"_id": UID, "email": "cli@example.org", "name": "CLI", "email_verified": True})
    test_db.users.insert_one({"_id": OTHER, "email": "o@example.org", "name": "O", "email_verified": True})
    token = tokens.create_token(test_db, UID, "cli")["token"]
    mcp_tools.register()

    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not srv.started:
        assert time.monotonic() < deadline, "the server didn't start"
        time.sleep(0.05)
    port = srv.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", base)
    monkeypatch.setenv("RELIAFY_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("RELIAFY_BASE_URL", base)
    monkeypatch.setenv("RELIAFY_TOKEN", token)
    try:
        yield {"base": base, "token": token, "db": test_db, "tmp": tmp_path}
    finally:
        srv.should_exit = True
        thread.join(timeout=10)
        mcp_tools.unregister()


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_client_calls_any_tool(server):
    rf = Client()
    assert rf.base_url == server["base"]
    saved = rf.call("models", "save", name="Handbook", distribution="weibull", params=WEIBULL)
    assert saved["saved"] and saved["model_id"]
    at = rf.reliability(saved["model_id"], [500])
    assert at["model_id"] == saved["model_id"]
    fit = rf.fit([120, 340, 510, 700, 980], censored=[0, 0, 1, 0, 0], distribution="weibull")
    assert fit["distribution_id"] == "weibull" and not fit["saved"]
    assert {t["name"] for t in rf.tools()["tools"]} >= {"life_data_analysis", "maintenance_positions"}
    assert "/api/v1/list/models" in rf.spec()["paths"]
    with pytest.raises(Exception) as err:
        rf.call("get", "model", id="nope")
    assert err.value.status == 404 and err.value.detail == "Model not found."


def test_0_2_functions_still_work(server):
    import reliafy

    reliafy.configure(token=server["token"], base_url=server["base"])
    url = reliafy.push_params("weibull", [1200.0, 2.5], name="From a report", unit="hours")
    assert url.startswith(server["base"] + "/models/m/")
    assert any(m["name"] == "From a report" for m in reliafy.models.list())
    ds = reliafy.data.upload("Bearings", csv="hours,failed\n120,1\n340,1\n510,0\n700,1")
    assert ds["n_rows"] == 4
    plan = reliafy.strategy.optimal_replacement("weibull", [1200, 2.5], planned_cost=100, unplanned_cost=1000)
    assert plan["optimal_time"] > 0
    assert reliafy.call("list", "models")["life_models"]


def test_cli_login_tools_and_generic_commands(server, capsys, monkeypatch):
    monkeypatch.delenv("RELIAFY_TOKEN")
    code, out, _ = run(capsys, "login", "--token", server["token"])
    assert code == 0 and "Signed in" in out
    cfg = json.load(open(os.path.join(os.environ["RELIAFY_CONFIG_DIR"], "config.json")))
    assert cfg["token"] == server["token"]
    assert oct(os.stat(os.path.join(os.environ["RELIAFY_CONFIG_DIR"], "config.json")).st_mode)[-3:] == "600"

    code, out, _ = run(capsys, "tools")
    assert code == 0 and "life_data_analysis" in out and "fit(" in out and "API/CLI only" in out
    code, out, _ = run(capsys, "strategy", "optimal_replacement", "--distribution-id", "weibull",
                       "--params", json.dumps(WEIBULL), "--planned-cost", "100", "--unplanned-cost", "1000",
                       "--json")
    assert code == 0 and json.loads(out)["optimal_time"] > 0
    code, out, _ = run(capsys, "life_data_analysis", "fit", "--data", "120,340,510,700,980",
                       "--censored", "0,0,1,0,0")
    assert code == 0 and "distribution: " in out
    code, out, _ = run(capsys, "guide", "--topic", "units")
    assert code == 0 and "unit" in out
    code, out, _ = run(capsys, "models", "list")
    assert code == 0
    with pytest.raises(SystemExit):
        run(capsys, "strategy", "optimal_replacement", "--help")
    assert "--planned-cost" in capsys.readouterr().out
    code, _, err = run(capsys, "get", "model", "--id", "nope")
    assert code == 1 and "Model not found" in err
    code, _, err = run(capsys, "nosuch")
    assert code == 2 and "reliafy tools" in err
    code, out, _ = run(capsys, "logout")
    assert code == 0 and not os.path.exists(os.path.join(os.environ["RELIAFY_CONFIG_DIR"], "config.json"))


def test_cli_fit_upload_import_push_ingest(server, capsys):
    tmp = server["tmp"]
    data = tmp / "bearings.csv"
    data.write_text("hours,failed\n120,1\n340,1\n510,0\n700,1\n980,1\n")
    code, _, err = run(capsys, "fit", str(data), "--dist", "weibull")
    assert code == 1 and "--censor-column failed" in err  # never guesses a flag's meaning
    code, out, _ = run(capsys, "fit", str(data), "--dist", "weibull", "--censor-column", "failed", "--c-invert",
                       "--json")
    assert code == 0 and json.loads(out)["censoring"]["n_failed"] == 4

    code, out, _ = run(capsys, "upload", str(data), "--name", "Bearings", "--json")
    assert code == 0 and json.loads(out)["n_rows"] == 5

    dft = tmp / "sys.dft"
    dft.write_text('toplevel "Sys";\n"Sys" and "A" "B";\n"A" lambda=0.001;\n"B" lambda=0.002;\n')
    code, out, _ = run(capsys, "import", "rbd", str(dft), "--name", "From DFT", "--json")
    assert code == 0 and json.loads(out)["diagrams"][0]["name"] == "From DFT"

    model = tmp / "model.json"
    model.write_text(json.dumps({"distribution": "weibull", "params": [{"value": 1200}, {"value": 2.5}]}))
    code, out, _ = run(capsys, "push", str(model), "--name", "Pushed", "--json")
    assert code == 0 and json.loads(out)["url"].startswith(server["base"])

    readings = tmp / "readings.csv"
    readings.write_text("tag,value\nPT-1,3.2\n")
    code, out, _ = run(capsys, "ingest", "readings", str(readings), "--json")
    assert code == 0 and json.loads(out)["unknown_tags"] == {"PT-1": 1}
    code, _, err = run(capsys, "ingest", "usage", str(readings))
    assert code == 1 and "--fleet" in err


def _jpeg() -> bytes:
    img = Image.new("RGB", (64, 48), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "PhoneCo"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_cli_photo_add(server, capsys):
    tmp = server["tmp"]
    rf = Client()
    pid = rf.call("maintenance_positions", "create", name="Pump A")["id"]
    (tmp / "a.jpg").write_bytes(_jpeg())
    (tmp / "b.jpg").write_bytes(_jpeg())
    buf = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buf, "PNG")
    (tmp / "c.png").write_bytes(buf.getvalue())
    code, out, _ = run(capsys, "photo", "add", str(tmp / "*.jpg"), str(tmp / "c.png"), "--to", pid,
                       "--caption", "Front")
    assert code == 0 and "3 of 3 added" in out, out
    (tmp / "bad.jpg").write_bytes(b"not an image")
    code, out, _ = run(capsys, "photo", "add", str(tmp / "a.jpg"), str(tmp / "bad.jpg"), "--to", pid, "--json")
    rows = json.loads(out)
    assert code == 1 and [r["ok"] for r in rows] == [True, False] and "photo" in rows[1]["detail"]
    detail = rf.call("maintenance_get", "position", id=pid)
    assert len(detail["photos"]) == 4


def test_cli_photo_heic_link_and_move(server, capsys):
    import pillow_heif

    tmp = server["tmp"]
    rf = Client()
    a = rf.call("maintenance_positions", "create", name="Pump A")["id"]
    b = rf.call("maintenance_positions", "create", name="Pump B")["id"]
    buf = io.BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (64, 48), (10, 120, 200))).save(buf, quality=80)
    (tmp / "IMG_0001.HEIC").write_bytes(buf.getvalue())
    code, out, _ = run(capsys, "photo", "add", str(tmp / "IMG_0001.HEIC"), "--to", a, "--json")
    assert code == 0, out
    photo_id = json.loads(out)[0]["photo_id"]
    code, out, _ = run(capsys, "photo", "link", photo_id, "--to", b, "--json")
    assert code == 0 and json.loads(out)[0]["on"] == "Pump A, Pump B"
    code, out, _ = run(capsys, "photo", "unlink", photo_id, "--from", a, "--json")
    assert code == 0 and json.loads(out)[0]["on"] == "Pump B"
    code, out, err = run(capsys, "photo", "unlink", photo_id, "--from", b)
    assert code == 1 and "only place" in err
    code, out, _ = run(capsys, "photo", "move", photo_id, "--to", a)
    assert code == 0 and "Pump A" in out
    assert rf.call("maintenance_get", "position", id=b)["photos"] == []
    code, _, err = run(capsys, "photo", "link", photo_id)
    assert code == 1 and "--to" in err


def test_cli_document_add_and_get(server, capsys):
    from backend.tests.test_maintenance_documents import pdf

    tmp = server["tmp"]
    rf = Client()
    pid = rf.call("maintenance_positions", "create", name="Pump A", position_class="Pump")["id"]
    (tmp / "Pump manual.pdf").write_bytes(pdf())
    (tmp / "notes.pdf").write_bytes(b"<html>not a pdf</html>")
    code, out, _ = run(capsys, "document", "add", str(tmp / "Pump manual.pdf"), str(tmp / "notes.pdf"),
                       "--to", pid, "--kind", "manual", "--json")
    rows = json.loads(out)
    assert code == 1 and [r["ok"] for r in rows] == [True, False] and "isn't a PDF" in rows[1]["detail"]
    code, out, _ = run(capsys, "document", "add", str(tmp / "Pump manual.pdf"), "--class", "Pump",
                       "--title", "Pump datasheet", "--kind", "datasheet")
    assert code == 0 and "1 of 1 added" in out, out
    docs = rf.call("maintenance_get", "position", id=pid)["documents"]
    assert [(d["title"], d["kind"], d["stored"]) for d in docs] == [("Pump manual", "manual", True)]

    code, out, _ = run(capsys, "document", "get", docs[0]["id"], "-o", str(tmp / "copy.pdf"), "--json")
    assert code == 0 and json.loads(out)["saved_to"] == str(tmp / "copy.pdf")
    assert (tmp / "copy.pdf").read_bytes() == pdf()
    code, _, err = run(capsys, "document", "add", str(tmp / "Pump manual.pdf"))
    assert code == 1 and "--to" in err
    linked = rf.call("maintenance_attachments", "add_document", url="https://example.com/a.pdf", target_id=pid)
    code, _, err = run(capsys, "document", "get", linked["id"])
    assert code == 1 and "a link" in err


class _OldServer(BaseHTTPRequestHandler):
    """A Reliafy server from before the tools API: FastAPI's plain 404."""

    def _answer(self):
        body = b'{"detail":"Not Found"}'
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args):
        pass


def test_an_older_server_is_said_plainly(capsys, monkeypatch, tmp_path):
    httpd = HTTPServer(("127.0.0.1", 0), _OldServer)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setenv("RELIAFY_CONFIG_DIR", str(tmp_path))
    try:
        with pytest.raises(ServerTooOld) as err:
            Client(token="rlf_x", base_url=base).call("list", "models")
        assert "tools API" in str(err.value) and "0.2 functions" in str(err.value)
        code, _, out = run(capsys, "--base-url", base, "--token", "rlf_x", "tools")
        assert code == 1 and "tools API" in out
    finally:
        httpd.shutdown()
