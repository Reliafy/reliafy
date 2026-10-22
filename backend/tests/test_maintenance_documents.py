"""PDFs kept in Reliafy Maintenance: checked (a real PDF, within the size cap),
stored as they came, on an item, a position or a class; served back only to
their workspace, as application/pdf; read by agents through a short-lived
link; deleted with the document. Links (document.added) behave as before.

Every PDF here is a few hand-written bytes built in the test."""

import matplotlib

matplotlib.use("Agg")

import pytest

from backend.maintenance import documents
from backend.maintenance.service import PROJECTORS, Invalid, LimitReached, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_api_tools import A, B, _auth, env, maint  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("mcp_on")

UID = "user-d"


def pdf(text: str = "Pump manual") -> bytes:
    """A tiny, valid one-page PDF."""
    stream = f"BT /F1 12 Tf 20 50 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ---- the checks ------------------------------------------------------------------------

def test_only_a_pdf_within_the_cap_is_kept(monkeypatch):
    documents.check_pdf(pdf())
    for raw, words in ((b"", "empty"), (b"<html><script>alert(1)</script>", "isn't a PDF"),
                       (b"PK\x03\x04 a workbook", "isn't a PDF"), (b" %PDF-1.4 late", "isn't a PDF")):
        with pytest.raises(documents.BadDocument, match=words):
            documents.check_pdf(raw)
    monkeypatch.setattr(documents, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(documents.BadDocument, match="over 20 MB"):
        documents.check_pdf(pdf())


def test_file_names_are_cleaned_and_headers_are_safe():
    assert documents.file_name("C:\\Users\\me\\Pump manual.PDF") == "Pump manual.pdf"
    assert documents.file_name("../../etc/passwd") == "passwd.pdf"
    assert documents.file_name("") == "document.pdf"
    assert documents.file_name("a\r\nSet-Cookie: x.pdf") == "aSet-Cookie: x.pdf"
    assert len(documents.file_name("x" * 500)) == 120
    head = documents.disposition('evil"; filename="x.html\r\n.pdf', download=False)
    assert head.startswith("inline; filename=\"") and "\r" not in head and "\n" not in head
    assert head.count('"') == 2  # the quoted ASCII name can't be closed early
    assert documents.disposition("Übersicht.pdf", download=True) == (
        "attachment; filename=\"Ubersicht.pdf\"; filename*=UTF-8''%C3%9Cbersicht.pdf")
    h = documents.headers("a.pdf", False)
    assert h["X-Content-Type-Options"] == "nosniff" and h["Referrer-Policy"] == "no-referrer"


def test_the_stores_keep_and_delete_bytes(tmp_path, monkeypatch):
    import mongomock

    files = documents.FileDocumentStore(str(tmp_path))
    files.put("abc123", pdf())
    assert files.get("abc123") == pdf()
    files.delete("abc123")
    assert files.get("abc123") is None and files.get("../x") is None
    monkeypatch.setattr(documents, "CHUNK_BYTES", 100)  # several chunks
    mongo = documents.MongoDocumentStore(mongomock.MongoClient()["docs"])
    mongo.put("d1", pdf())
    assert mongo.get("d1") == pdf()
    mongo.put("d1", pdf("Shorter"))  # replaced, no chunks left behind
    assert mongo.get("d1") == pdf("Shorter")
    mongo.delete("d1")
    assert mongo.get("d1") is None


# ---- the graph -------------------------------------------------------------------------

def test_stored_pdfs_sit_beside_links_and_replay(monkeypatch):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID)
    pos = m.create_position("Pump A", position_class="Pump")
    link = m.add_document("https://example.com/manual.pdf", "", "manual", target_id=pos["id"])
    kept = m.add_stored_document("d" * 32, "Pump manual.pdf", 1234, "ab" * 32, "", "manual", target_id=pos["id"])
    assert kept["stored"] and kept["title"] == "Pump manual" and kept["file_name"] == "Pump manual.pdf"
    assert kept["url"] is None and kept["of"]["id"] == pos["id"] and kept["content_type"] == "application/pdf"
    on_class = m.add_stored_document("e" * 32, "sheet.pdf", 10, "cd" * 32, "Datasheet", "datasheet",
                                     position_class="Pump")
    assert on_class["of"]["kind"] == "PositionClass"
    listed = m.position(pos["id"])["documents"]
    assert [(d["title"], d["stored"]) for d in listed] == [("manual.pdf", False), ("Pump manual", True)]
    assert "file_name" not in listed[0] and listed[1]["size"] == 1234
    assert m.document(link["id"])["stored"] is False  # a link reads as it always did, plus stored: false

    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before

    m.remove_document("d" * 32)
    assert [d["title"] for d in m.position(pos["id"])["documents"]] == ["manual.pdf"]
    with pytest.raises(Invalid):
        m.remove_document("d" * 32)
    with pytest.raises(Invalid, match="kind"):
        m.check_stored_document(10, "poster", target_id=pos["id"])
    with pytest.raises(Invalid, match="Say what"):
        m.check_stored_document(10)


def test_the_workspace_limits_are_kept(monkeypatch):
    from backend import config
    from backend.maintenance import service

    m = Maintenance(GraphStore(":memory:", PROJECTORS), UID)
    pos = m.create_position("Pump A")
    monkeypatch.setattr(config, "MAINTENANCE_DOCUMENT_BYTES", 3 * 1024 * 1024)
    m.add_stored_document("a" * 32, "a.pdf", 2 * 1024 * 1024, "0" * 64, target_id=pos["id"])
    with pytest.raises(LimitReached, match="at most 3 MB of PDFs and has 1.0 MB left"):
        m.check_stored_document(2 * 1024 * 1024, target_id=pos["id"])
    monkeypatch.setattr(service, "MAX_STORED_DOCUMENTS", 1)
    with pytest.raises(LimitReached, match="at most 1 PDFs"):
        m.check_stored_document(10, target_id=pos["id"])
    unlimited = Maintenance(m.s, UID, limited=False)
    unlimited.check_stored_document(10 ** 9, target_id=pos["id"])


# ---- the app's routes ------------------------------------------------------------------

@pytest.fixture()
def app(maint, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend.auth import get_current_user
    from backend.main import app as fastapi_app
    from backend.routers import maintenance as router

    monkeypatch.setattr(router, "_document_store", documents.FileDocumentStore(str(tmp_path / "docs")))
    who = {"uid": A}

    def user():
        return {"uid": who["uid"], "email": maint.db.users.find_one({"_id": who["uid"]})["email"],
                "email_verified": True}

    fastapi_app.dependency_overrides[get_current_user] = user
    try:
        yield maint, TestClient(fastapi_app), who
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)


def test_upload_open_download_and_remove_in_the_app(app, monkeypatch):
    from backend.routers import maintenance as router

    maint, client, who = app
    pid = client.post("/api/maintenance/positions", json={"name": "Pool pump"}).json()["id"]
    up = client.post(f"/api/maintenance/documents/upload?target_id={pid}&kind=manual&filename=Pool%20pump.pdf",
                     content=pdf(), headers={"Content-Type": "application/pdf"})
    assert up.status_code == 200, up.text
    doc = up.json()
    assert doc["stored"] and doc["title"] == "Pool pump" and doc["size"] == len(pdf())
    assert client.get(f"/api/maintenance/positions/{pid}").json()["documents"][0]["id"] == doc["id"]

    opened = client.get(f"/api/maintenance/documents/{doc['id']}/file")
    assert opened.status_code == 200 and opened.content == pdf()
    assert opened.headers["content-type"] == "application/pdf"
    assert opened.headers["x-content-type-options"] == "nosniff"
    assert opened.headers["content-disposition"].startswith('inline; filename="Pool pump.pdf"')
    saved = client.get(f"/api/maintenance/documents/{doc['id']}/file?download=1")
    assert saved.headers["content-disposition"].startswith("attachment;")

    # Not a PDF, too big, nothing said about what it's for: refused with what to do.
    html = client.post(f"/api/maintenance/documents/upload?target_id={pid}", content=b"<html>hi</html>")
    assert html.status_code == 422 and "isn't a PDF" in html.json()["detail"]
    assert client.post("/api/maintenance/documents/upload", content=pdf()).status_code == 422
    monkeypatch.setattr(documents, "MAX_UPLOAD_BYTES", 50)
    big = client.post(f"/api/maintenance/documents/upload?target_id={pid}", content=pdf())
    assert big.status_code == 413 and "Make it smaller" in big.json()["detail"]
    monkeypatch.setattr(documents, "MAX_UPLOAD_BYTES", 20 * 1024 * 1024)

    # Another account (with Maintenance) can't see it: the same "not found" as a missing one.
    maint.db.users.update_one({"_id": B}, {"$set": {"email": "b@example.org"}})
    from backend import config

    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@example.org", "b@example.org"})
    who["uid"] = B
    assert client.get(f"/api/maintenance/documents/{doc['id']}/file").status_code == 404
    assert client.delete(f"/api/maintenance/documents/{doc['id']}").status_code == 404
    who["uid"] = A

    assert client.delete(f"/api/maintenance/documents/{doc['id']}").status_code == 200
    assert router.get_document_store().get(doc["id"]) is None  # the bytes are gone
    assert client.get(f"/api/maintenance/documents/{doc['id']}/file").status_code == 404
    assert client.get(f"/api/maintenance/positions/{pid}").json()["documents"] == []


# ---- agents: uploads create -> PUT -> add_document -> get kind document ----------------

def test_agents_upload_attach_read_and_remove(app):
    maint, client, _ = app
    pid = maint.post("/api/v1/maintenance_positions/create", {"name": "Pump A"}).json()["id"]
    link = maint.post("/api/v1/uploads/create", {"purpose": "document", "filename": "manual.pdf"}).json()
    assert link["max_bytes"] == 20 * 1024 * 1024
    put = client.put(link["url"].split("testserver", 1)[-1], content=pdf())
    assert put.status_code == 200 and put.json()["detected_format"] == "pdf"
    assert "add_document" in put.json()["next"]
    seen = maint.post("/api/v1/get/upload", {"id": link["upload_id"]}).json()
    assert seen["kind"] == "pdf"

    both = maint.post("/api/v1/maintenance_attachments/add_document",
                      {"upload_id": link["upload_id"], "url": "https://example.com/a.pdf", "target_id": pid})
    assert both.status_code == 422 and "exactly one" in both.json()["detail"]
    added = maint.post("/api/v1/maintenance_attachments/add_document",
                       {"upload_id": link["upload_id"], "target_id": pid, "kind": "manual"})
    assert added.status_code == 200, added.text
    doc = added.json()
    assert doc["stored"] and doc["title"] == "manual"
    again = maint.post("/api/v1/maintenance_attachments/add_document", {"upload_id": link["upload_id"],
                                                                          "target_id": pid})
    assert again.status_code in (404, 422)  # the upload is used up once kept

    read = maint.post("/api/v1/maintenance_get/document", {"id": doc["id"]}).json()
    opened = client.get(read["open_url"].split("testserver", 1)[-1], headers={"Authorization": ""})
    assert opened.status_code == 200 and opened.content == pdf()
    assert opened.headers["content-type"] == "application/pdf" and opened.headers["cache-control"] == "no-store"
    assert opened.headers["content-disposition"].startswith("inline;")
    got = client.get(read["download_url"].split("testserver", 1)[-1])
    assert got.headers["content-disposition"].startswith("attachment;")
    wrong = read["open_url"].split("testserver", 1)[-1].replace("t=", "t=x")
    assert client.get(wrong).status_code == 404

    gone = maint.post("/api/v1/maintenance_attachments/remove_document", {"document_id": doc["id"]})
    assert gone.status_code == 200
    assert client.get(read["open_url"].split("testserver", 1)[-1]).status_code == 404
    assert maint.post("/api/v1/maintenance_get/document", {"id": doc["id"]}).json()["removed"] is True

    # A link still works as before.
    linked = maint.post("/api/v1/maintenance_attachments/add_document",
                        {"url": "https://example.com/manual.pdf", "target_id": pid}).json()
    assert linked["url"] == "https://example.com/manual.pdf" and linked["stored"] is False


def test_document_uploads_are_only_for_maintenance_users(maint):
    r = maint.post("/api/v1/uploads/create", {"purpose": "document", "filename": "a.pdf"}, uid=B)
    assert r.status_code == 404 and "isn't available" in r.json()["detail"]
    big = maint.post("/api/v1/uploads/create", {"purpose": "document", "filename": "a.pdf",
                                                "size_bytes": 25 * 1024 * 1024})
    assert big.status_code == 422 and "limited to 20 MB" in big.json()["detail"]


def test_a_link_expires(app, monkeypatch):
    from datetime import datetime, timedelta, timezone

    maint, client, _ = app
    pid = maint.post("/api/v1/maintenance_positions/create", {"name": "Pump A"}).json()["id"]
    doc = client.post(f"/api/maintenance/documents/upload?target_id={pid}", content=pdf()).json()
    read = maint.post("/api/v1/maintenance_get/document", {"id": doc["id"]}).json()
    later = datetime.now(timezone.utc) + timedelta(minutes=documents.LINK_MINUTES + 1)
    monkeypatch.setattr(documents, "_now", lambda: later)
    assert client.get(read["open_url"].split("testserver", 1)[-1]).status_code == 404
