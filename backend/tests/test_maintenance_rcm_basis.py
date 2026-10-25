"""The working behind a performance standard: ``standard_basis`` on a Function
(Markdown text, at most BASIS_TEXT characters), additive in function.added /
function.updated, replayed the same and harmless to the code before it; read in
full per position and per function, as a short preview in the bulk read; and
PDFs of it as documents on the function (at most 5, removed with it, moved
with it)."""

import matplotlib

matplotlib.use("Agg")

import pytest

from backend.maintenance.service import (BASIS_PREVIEW, BASIS_TEXT, MAX_BASIS_DOCUMENTS, PROJECTORS, Invalid,
                                         LimitReached, Maintenance, NotFound, basis_preview)
from backend.maintenance.store import GraphStore, new_id
from backend.tests.test_api_tools import A, B, _auth, env, maint  # noqa: F401 - fixtures
from backend.tests.test_maintenance_documents import app, pdf  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("mcp_on")

ORG = "user-basis"
WORKING = """## Chlorine demand

| Source | ppm/day |
|---|---|
| UV | 2.1 |
| **Swimmers** | 0.4 |

```
150 g / 35,000 L = 4.3 ppm/day
```

- See [the method](https://example.com/method)."""


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _fn(m, basis=""):
    pid = m.create_position("Pool", operating_context="35 kL, outdoors")["id"]
    return pid, m.add_function(pid, "Keep the water sanitised", "Free chlorine 1-3 ppm", standard_basis=basis)


def test_added_changed_cleared_and_unchanged_emits_nothing(m):
    pid, plain = _fn(m)
    assert plain["standard_basis"] == "" and plain["has_basis"] is False and plain["basis_on"] is None
    added = [e for e in m.s.log.since(0, 1000) if e["type"] == "function.added"][-1]["payload"]
    assert "standard_basis" not in added and "on" not in added  # never stored empty: old events replay as before
    assert "standard_basis" not in m.s.node(ORG, plain["id"])

    with_it = m.add_function(pid, "Keep the water clear", standard_basis=f"\r\n  {WORKING}  \r\n")
    assert with_it["standard_basis"] == WORKING and with_it["has_basis"] and with_it["basis_on"] == m.today()

    count = len(m.s.log.since(0, 1000))
    m.update_function(with_it["id"], standard_basis=WORKING)  # the same text: no event
    m.update_function(with_it["id"], text="Keep the water clear")
    assert len(m.s.log.since(0, 1000)) == count
    changed = m.update_function(with_it["id"], standard_basis="Line one  \r\nLine two\rLine three")
    assert changed["standard_basis"] == "Line one\nLine two\nLine three"
    event = m.s.log.since(0, 1000)[-1]
    assert event["type"] == "function.updated" and event["payload"]["on"] == m.today()
    m.update_function(with_it["id"], standard="Free chlorine 2-4 ppm")  # other changes leave it alone
    assert m.function(with_it["id"])["standard_basis"].startswith("Line one")
    cleared = m.update_function(with_it["id"], standard_basis="")
    assert cleared["standard_basis"] == "" and not cleared["has_basis"] and cleared["basis_on"] is None
    assert cleared["standard"] == "Free chlorine 2-4 ppm"


def test_the_cap_and_plain_text(m):
    pid, fn = _fn(m)
    m.update_function(fn["id"], standard_basis="x" * BASIS_TEXT)
    with pytest.raises(Invalid) as err:
        m.update_function(fn["id"], standard_basis="y" * (BASIS_TEXT + 1))
    assert str(err.value) == ("The working behind the standard is at most 20,000 characters; this one is 20,001. "
                              "Shorten it, or attach it as a PDF.")
    with pytest.raises(Invalid, match="at most 20,000"):
        m.add_function(pid, "Another", standard_basis="z" * (BASIS_TEXT + 1))
    with pytest.raises(Invalid, match="control character"):
        m.update_function(fn["id"], standard_basis="a\x00b")
    assert m.function(fn["id"])["standard_basis"] == "x" * BASIS_TEXT  # refused: nothing changed
    m.update_function(fn["id"], standard_basis="tabs\tare fine\n\nand blank lines")


def test_a_copy_carries_it_a_move_keeps_it_and_the_log_replays_the_same(m):
    pid, fn = _fn(m, WORKING)
    other = m.create_position("Spa")["id"]
    copy = m.copy_position(pid, "Pool 2")
    copied = m.rcm_worksheet(copy["id"], "this")["positions"][0]["functions"][0]
    assert copied["standard_basis"] == WORKING and copied["basis_on"] == fn["basis_on"] and copied["id"] != fn["id"]
    m.move_function(fn["id"], other)
    assert m.function(fn["id"])["standard_basis"] == WORKING and m.function(fn["id"])["position"]["id"] == other
    m.update_function(fn["id"], standard_basis="Changed")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_full_text_per_position_and_function_a_preview_in_bulk(m):
    pid, fn = _fn(m, WORKING)
    sheet = m.rcm_worksheet(pid)["positions"][0]["functions"][0]
    assert sheet["standard_basis"] == WORKING and "basis_preview" not in sheet
    one = m.function(fn["id"])
    assert one["standard_basis"] == WORKING and one["position"] == {"id": pid, "name": "Pool"}
    assert one["documents"] == [] and one["failures"] == []
    bulk = m.rcm_all()["positions"][0]["functions"][0]
    assert "standard_basis" not in bulk and bulk["has_basis"] is True
    assert bulk["basis_preview"] == ("Chlorine demand Source · ppm/day UV · 2.1 Swimmers · 0.4 "
                                     "150 g / 35,000 L = 4.3 ppm/day See the method.")
    m.update_function(fn["id"], standard_basis="word " * 4000)
    bulk = m.rcm_all()["positions"][0]["functions"][0]
    assert len(bulk["basis_preview"]) <= BASIS_PREVIEW and bulk["basis_preview"].endswith("…")
    assert len(str(m.rcm_all())) < 2000  # 20,000 characters on the function, a few hundred in the bulk read
    with pytest.raises(NotFound):
        m.function("nope")
    m.remove_function(fn["id"])
    with pytest.raises(Invalid, match="deleted"):
        m.function(fn["id"])


def test_the_preview_helper():
    assert basis_preview("") == ""
    assert basis_preview("# Title\n\n> quoted *text* and `code`\n\n1. one\n2. two\n---\n![img](x.png)") == \
        "Title quoted text and code one two img"


def test_the_tree_says_which_positions_have_an_operating_context(m):
    pid, _ = _fn(m)
    bare = m.create_position("Shed")["id"]
    rows = {r["id"]: r for r in m.tree_rows()["positions"]}
    assert rows[pid]["context"] is True and "context" not in rows[bare]


# The projectors as they were before the field (the live code until this ships).
def _old_function_added(s, org, p):
    s.put_node(org, p["id"], "Function", {
        "text": p["text"], "standard": p.get("standard", ""), "order": p.get("order", 0),
        "rcm_function_id": p.get("rcm_function_id"), "study_id": p.get("study_id"),
    })
    s.put_edge(org, "PERFORMS", p["position_id"], p["id"])


def _old_patch(s, org, p):
    changes = {k: v for k, v in p["changes"].items() if k != "parent_id"}
    if changes:
        s.patch_node(org, p["id"], changes)


def test_the_code_before_the_field_replays_the_new_events_harmlessly(m):
    pid, fn = _fn(m, WORKING)
    other = m.add_function(pid, "Circulate the water", "Turnover in 6 h")
    m.update_function(other["id"], standard_basis="35 kL / 6 h = 5.8 kL/h")
    m.add_stored_document("d" * 32, "Working.pdf", 1234, "ab" * 32, target_id=fn["id"])

    old = GraphStore(":memory:", {**PROJECTORS, "function.added": _old_function_added,
                                  "function.updated": _old_patch})
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert "standard_basis" not in old.node(ORG, fn["id"])  # an unknown key on add: ignored
    # On update, the old projector patches every key in changes: stored, unused; the top-level on is ignored.
    assert old.node(ORG, other["id"])["standard_basis"] == "35 kL / 6 h = 5.8 kL/h"
    assert "basis_on" not in old.node(ORG, other["id"])
    # The PDF's OF edge points at the function; the position's documents never list it.
    assert old.out(ORG, "d" * 32, "OF")[0]["id"] == fn["id"]
    assert Maintenance(old, ORG, "tester").position(pid)["documents"] == []
    assert [f["text"] for f in Maintenance(old, ORG, "tester").rcm_worksheet(pid)["positions"][0]["functions"]] == \
        ["Keep the water sanitised", "Circulate the water"]


# ---- PDFs of the working: documents on the function -----------------------------------

def test_documents_on_a_function_limit_move_and_removal(m):
    pid, fn = _fn(m, WORKING)
    for n in range(MAX_BASIS_DOCUMENTS):
        doc = m.add_stored_document(f"{n:032d}", f"Working {n}.pdf", 100 + n, "ab" * 32, target_id=fn["id"])
    assert doc["of"] == {"id": fn["id"], "kind": "Function", "name": "Keep the water sanitised"}
    with pytest.raises(LimitReached, match="At most 5 documents on one function"):
        m.add_stored_document("f" * 32, "One more.pdf", 10, "ab" * 32, target_id=fn["id"])
    with pytest.raises(LimitReached):
        m.add_document("https://example.com/w.pdf", target_id=fn["id"])
    assert m.position(pid)["documents"] == []  # the position's own documents don't list the function's
    assert [d["title"] for d in m.function(fn["id"])["documents"]] == [f"Working {n}" for n in range(5)]
    assert m.rcm_all()["positions"][0]["functions"][0]["documents"][0] == {
        "id": f"{0:032d}", "title": "Working 0", "size": 100}
    assert m.rcm_worksheet(pid)["positions"][0]["functions"][0]["documents"][0]["file_name"] == "Working 0.pdf"

    spa = m.create_position("Spa")["id"]
    m.move_function(fn["id"], spa)
    assert len(m.function(fn["id"])["documents"]) == 5  # they're on the node: they move with it
    assert len(m.rcm_worksheet(spa)["positions"][0]["functions"][0]["documents"]) == 5
    copy = m.copy_position(spa, "Spa 2")
    assert m.rcm_worksheet(copy["id"])["positions"][0]["functions"][0]["documents"] == []  # never copied

    m.remove_document(f"{0:032d}")
    gone = m.remove_function(fn["id"])
    assert gone["documents_removed"] == [f"{n:032d}" for n in range(1, 5)]
    assert all(m.document(f"{n:032d}")["removed"] for n in range(5))
    with pytest.raises(Invalid, match="deleted"):
        m.add_document("https://example.com/w.pdf", target_id=fn["id"])
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_routes_attach_read_and_remove_a_functions_pdf(app):
    from backend.routers import maintenance as router

    maint, client, _ = app
    M = "/api/maintenance"
    pid = client.post(f"{M}/positions", json={"name": "Pool"}).json()["id"]
    fn = client.post(f"{M}/positions/{pid}/functions",
                     json={"text": "Keep the water sanitised", "standard": "1-3 ppm", "standard_basis": WORKING})
    assert fn.status_code == 200 and fn.json()["standard_basis"] == WORKING
    fid = fn.json()["id"]
    up = client.post(f"{M}/documents/upload?target_id={fid}&filename=Working.pdf", content=pdf(),
                     headers={"Content-Type": "application/pdf"})
    assert up.status_code == 200, up.text
    doc = up.json()
    got = client.get(f"{M}/functions/{fid}").json()
    assert got["standard_basis"] == WORKING and got["documents"][0]["id"] == doc["id"]
    assert client.get(f"{M}/documents/{doc['id']}/file").content == pdf()
    bulk = client.get(f"{M}/rcm").json()["positions"][0]["functions"][0]
    assert bulk["has_basis"] and "standard_basis" not in bulk and bulk["documents"][0]["id"] == doc["id"]

    r = client.patch(f"{M}/functions/{fid}", json={"standard_basis": "x" * (BASIS_TEXT + 1)})
    assert r.status_code == 422 and "attach it as a PDF" in r.json()["detail"]
    assert client.patch(f"{M}/functions/{fid}", json={"standard_basis": ""}).json()["has_basis"] is False
    assert client.get(f"{M}/functions/nope").status_code == 404

    gone = client.delete(f"{M}/functions/{fid}")
    assert gone.status_code == 200 and gone.json()["documents_removed"] == [doc["id"]]
    assert router.get_document_store().get(doc["id"]) is None  # the bytes are gone with it
    assert client.get(f"{M}/documents/{doc['id']}/file").status_code == 404


def test_the_rest_api_and_agents(maint):
    pid = maint.post("/api/v1/maintenance_positions/create", {"name": "Pool"}).json()["id"]
    fn = maint.post("/api/v1/maintenance_failure_modes/add_function",
                    {"position_id": pid, "text": "Keep the water sanitised", "standard_basis": WORKING})
    assert fn.status_code == 200, fn.text
    fid = fn.json()["id"]
    assert fn.json()["standard_basis"] == WORKING
    r = maint.post("/api/v1/maintenance_failure_modes/update_function",
                   {"function_id": fid, "standard_basis": "35 kL / 6 h"})
    assert r.json()["standard_basis"] == "35 kL / 6 h"
    read = maint.post("/api/v1/maintenance_get/function", {"id": fid}).json()
    assert read["standard_basis"] == "35 kL / 6 h" and read["position"]["id"] == pid
    sheet = maint.post("/api/v1/maintenance_get/rcm", {"id": pid}).json()
    assert sheet["positions"][0]["functions"][0]["standard_basis"] == "35 kL / 6 h"
    linked = maint.post("/api/v1/maintenance_attachments/add_document",
                        {"url": "https://example.com/working.pdf", "target_id": fid}).json()
    assert linked["of"]["kind"] == "Function"
    gone = maint.post("/api/v1/maintenance_failure_modes/remove_function", {"function_id": fid}).json()
    assert gone["documents_removed"] == [linked["id"]]
    tools = {t["name"]: t for t in maint.client.get("/api/v1/tools", headers=_auth(maint.token[A])).json()["tools"]}
    assert "standard_basis" in str(tools["maintenance_failure_modes"])
