"""The working behind a performance standard. It had its own section on a
function (``standard_basis``, Markdown); since Nov 2026 it is part of the
function's notes and rationale. Old events still replay to the same node; the
read merges a separate working into the notes (merged_notes); the first save
of the notes, or the one-off migration (merge_workings), records the merge
with function.working_merged; standard_basis on writes is a deprecated alias
that adds to the notes. PDFs of it are documents on the function (at most 5,
removed with it, moved with it)."""

import matplotlib

matplotlib.use("Agg")

import pytest

from backend.maintenance.service import (BASIS_PREVIEW, BASIS_TEXT, FUNCTION_NOTES, MAX_BASIS_DOCUMENTS, PROJECTORS,
                                         Invalid, LimitReached, Maintenance, NotFound, basis_preview, merged_notes)
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


def _legacy(m, pid, text="Keep the water sanitised", working=WORKING, notes=""):
    """A function as the app wrote it before Nov 2026: its working on function.added."""
    fid = new_id()
    m._emit("function.added", {"id": fid, "position_id": pid, "text": text, "standard": "Free chlorine 1-3 ppm",
                               "order": 0, "standard_basis": working, "on": "2026-10-01"})
    if notes:
        m._emit("function.notes_set", {"id": fid, "notes": notes})
    return fid


def _types(m):
    return [e["type"] for e in m.s.log.since(0, 10_000)]


def test_the_merge_helper():
    assert merged_notes("", "") == "" and merged_notes("Why", "") == "Why"
    assert merged_notes("", " W ") == "W"
    assert merged_notes("Why", "W") == "Why\n\nWorking\n\nW"
    assert merged_notes("Why\n\nWorking\n\nW", "W") == "Why\n\nWorking\n\nW"  # already in: once
    assert merged_notes("Why", "Why\n\nWorking\n\nW") == "Why\n\nWorking\n\nW"  # the merged text sent back


def test_a_new_function_has_no_separate_working_the_alias_writes_notes(m):
    pid, plain = _fn(m)
    assert plain["notes"] == "" and plain["has_basis"] is False and plain["standard_basis"] == ""
    with_it = m.add_function(pid, "Keep the water clear", standard_basis=f"\r\n  {WORKING}  \r\n", notes="Why")
    added = [e for e in m.s.log.since(0, 1000) if e["type"] == "function.added"][-1]["payload"]
    assert "standard_basis" not in added  # never on new events
    assert with_it["notes"] == f"Why\n\nWorking\n\n{WORKING}" and with_it["standard_basis"] == with_it["notes"]
    assert with_it["has_basis"] and with_it["basis_on"] is None
    assert not m.s.node(ORG, with_it["id"]).get("standard_basis")

    count = len(m.s.log.since(0, 1000))
    m.update_function(with_it["id"], standard_basis=WORKING)  # already in the notes: nothing to do
    m.update_function(with_it["id"], text="Keep the water clear")
    assert len(m.s.log.since(0, 1000)) == count
    m.update_function(plain["id"], standard_basis="35 kL / 6 h")
    assert m.function(plain["id"])["notes"] == "35 kL / 6 h" and _types(m)[-1] == "function.notes_set"
    m.update_function(plain["id"], notes="")
    assert m.function(plain["id"])["has_basis"] is False


def test_the_caps(m):
    pid, fn = _fn(m)
    m.update_function(fn["id"], notes="x" * FUNCTION_NOTES)  # a function's notes hold a working: room for it
    with pytest.raises(Invalid, match="at most 25000"):
        m.update_function(fn["id"], notes="y" * (FUNCTION_NOTES + 1))
    with pytest.raises(Invalid) as err:
        m.update_function(fn["id"], standard_basis="y" * (BASIS_TEXT + 1))
    assert "at most 20,000 characters" in str(err.value)
    with pytest.raises(Invalid, match="control character"):
        m.update_function(fn["id"], standard_basis="a\x00b")
    assert m.function(fn["id"])["notes"] == "x" * FUNCTION_NOTES  # refused: nothing changed
    std = m.add_standard(fn["id"], "pH 7.2-7.8")
    with pytest.raises(Invalid, match="at most 4000"):  # other rows keep LONG_TEXT
        m.update_standard(std["id"], notes="z" * 4001)


def test_an_old_working_reads_as_the_notes_and_the_first_save_absorbs_it(m):
    pid = m.create_position("Pool")["id"]
    alone = _legacy(m, pid, "Keep it clean")
    both = _legacy(m, pid, "Keep it clear", working="35 kL / 6 h", notes="Turnover matters")
    assert m.s.node(ORG, alone)["standard_basis"] == WORKING
    one = m.function(alone)
    assert one["notes"] == WORKING and one["standard_basis"] == WORKING and one["basis_on"] == "2026-10-01"
    two = m.function(both)
    assert two["notes"] == "Turnover matters\n\nWorking\n\n35 kL / 6 h"
    bulk = {f["id"]: f for f in m.rcm_all()["positions"][0]["functions"]}
    assert bulk[both]["notes"] == two["notes"] and bulk[both]["has_basis"]
    assert bulk[both]["basis_preview"].startswith("Turnover matters Working")

    count = len(m.s.log.since(0, 1000))
    m.set_rcm_notes("function", both, two["notes"])  # saved as read: nothing to do
    assert len(m.s.log.since(0, 1000)) == count
    edited = m.set_rcm_notes("function", both, two["notes"] + "\nChecked 2026.")
    assert _types(m)[-1] == "function.working_merged"
    assert edited["notes"].endswith("Checked 2026.") and edited["basis_on"] is None
    assert m.s.node(ORG, both)["standard_basis"] == "" and m.s.node(ORG, both)["working_merged"] is True
    # From now on it's plain notes.
    m.set_rcm_notes("function", both, "Just this")
    assert _types(m)[-1] == "function.notes_set" and m.function(both)["notes"] == "Just this"
    # The alias on an old working replaces it.
    m.update_function(alone, standard_basis="New working")
    assert m.function(alone)["notes"] == "New working" and _types(m)[-1] == "function.working_merged"
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_migration_dry_run_then_apply(m):
    pid = m.create_position("Pool")["id"]
    alone = _legacy(m, pid, "Keep it clean")
    both = _legacy(m, pid, "Keep it clear", working="35 kL / 6 h", notes="Turnover matters")
    gone = _legacy(m, pid, "Old one")
    m.remove_function(gone)
    m.add_function(pid, "Plain", notes="Nothing to merge")
    reads = {f: m.function(f)["notes"] for f in (alone, both)}
    count = len(m.s.log.since(0, 1000))

    dry = m.merge_workings()
    assert dry["dry_run"] is True and dry["functions"] == 2
    assert {r["id"] for r in dry["merged"]} == {alone, both}
    row = next(r for r in dry["merged"] if r["id"] == both)
    assert row == {"id": both, "text": "Keep it clear", "notes_chars": 16, "working_chars": 11,
                   "merged_chars": len(reads[both])}
    assert len(m.s.log.since(0, 1000)) == count  # a dry run writes nothing

    done = m.merge_workings(dry_run=False)
    assert done["functions"] == 2 and _types(m)[-2:] == ["function.working_merged"] * 2
    assert {f: m.function(f)["notes"] for f in (alone, both)} == reads  # nothing a user sees changed
    assert all(m.s.node(ORG, f)["standard_basis"] == "" for f in (alone, both))
    assert m.merge_workings(dry_run=False)["functions"] == 0  # twice: nothing more
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_migration_script_per_organisation():
    from backend.scripts.merge_function_workings import merge

    store = GraphStore(":memory:", PROJECTORS)
    for org in ("org-a", "org-b"):
        mm = Maintenance(store, org, "tester")
        pid = mm.create_position("Pool")["id"]
        if org == "org-a":
            _legacy(mm, pid)
        else:
            mm.add_function(pid, "Plain")
    dry = merge(store)
    assert dry["dry_run"] and dry["functions"] == 1 and list(dry["orgs"]) == ["org-a"]
    assert merge(store, "org-a", apply=True)["functions"] == 1
    assert merge(store)["functions"] == 0


def test_a_copy_carries_the_notes_a_move_keeps_them_and_the_log_replays_the_same(m):
    pid = m.create_position("Pool")["id"]
    old = _legacy(m, pid, notes="Why")
    other = m.create_position("Spa")["id"]
    copy = m.copy_position(pid, "Pool 2")
    copied = m.rcm_worksheet(copy["id"], "this")["positions"][0]["functions"][0]
    assert copied["notes"] == f"Why\n\nWorking\n\n{WORKING}" and copied["id"] != old
    assert not m.s.node(ORG, copied["id"]).get("standard_basis")  # the copy's notes hold it
    m.move_function(old, other)
    assert m.function(old)["notes"] == copied["notes"] and m.function(old)["position"]["id"] == other
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_reads_per_position_function_and_bulk(m):
    pid, fn = _fn(m, WORKING)
    sheet = m.rcm_worksheet(pid)["positions"][0]["functions"][0]
    assert sheet["notes"] == WORKING and sheet["standard_basis"] == WORKING and "basis_preview" not in sheet
    one = m.function(fn["id"])
    assert one["notes"] == WORKING and one["position"] == {"id": pid, "name": "Pool"}
    assert one["documents"] == [] and one["failures"] == []
    bulk = m.rcm_all()["positions"][0]["functions"][0]
    assert "standard_basis" not in bulk and bulk["has_basis"] is True and bulk["notes"] == WORKING
    assert bulk["basis_preview"] == ("Chlorine demand Source · ppm/day UV · 2.1 Swimmers · 0.4 "
                                     "150 g / 35,000 L = 4.3 ppm/day See the method.")
    m.update_function(fn["id"], notes="word " * 4000)
    bulk = m.rcm_all()["positions"][0]["functions"][0]
    assert len(bulk["basis_preview"]) <= BASIS_PREVIEW and bulk["basis_preview"].endswith("…")
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


# The projector as it was before function.working_merged: an unknown event type is skipped.
def test_the_code_before_the_merge_replays_the_new_events_harmlessly(m):
    pid = m.create_position("Pool")["id"]
    fid = _legacy(m, pid, notes="Why")
    m.merge_workings(dry_run=False)
    old = GraphStore(":memory:", {k: v for k, v in PROJECTORS.items() if k != "function.working_merged"})
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert old.node(ORG, fid)["standard_basis"] == WORKING and old.node(ORG, fid)["notes"] == "Why"


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
    saved = client.patch(f"{M}/functions/{fid}", json={"notes": "Why\n\n" + WORKING}).json()
    assert saved["notes"] == "Why\n\n" + WORKING
    assert client.patch(f"{M}/functions/{fid}", json={"notes": ""}).json()["has_basis"] is False
    assert client.get(f"{M}/functions/nope").status_code == 404

    gone = client.delete(f"{M}/functions/{fid}")
    assert gone.status_code == 200 and gone.json()["documents_removed"] == [doc["id"]]
    assert router.get_document_store().get(doc["id"]) is None  # the bytes are gone with it
    assert client.get(f"{M}/documents/{doc['id']}/file").status_code == 404


def test_the_rest_api_and_agents(maint):
    pid = maint.post("/api/v1/maintenance/positions.create", {"name": "Pool"}).json()["id"]
    fn = maint.post("/api/v1/maintenance/failure_modes.add_function",
                    {"position_id": pid, "text": "Keep the water sanitised", "standard_basis": WORKING})
    assert fn.status_code == 200, fn.text
    fid = fn.json()["id"]
    assert fn.json()["standard_basis"] == WORKING and fn.json()["notes"] == WORKING  # the alias writes the notes
    r = maint.post("/api/v1/maintenance/failure_modes.update_function",
                   {"function_id": fid, "notes": "35 kL / 6 h"})
    assert r.json()["notes"] == "35 kL / 6 h" and r.json()["standard_basis"] == "35 kL / 6 h"
    read = maint.post("/api/v1/maintenance/get.function", {"id": fid}).json()
    assert read["notes"] == "35 kL / 6 h" and read["position"]["id"] == pid
    sheet = maint.post("/api/v1/maintenance/get.rcm", {"id": pid}).json()
    assert sheet["positions"][0]["functions"][0]["notes"] == "35 kL / 6 h"
    linked = maint.post("/api/v1/maintenance/attachments.add_document",
                        {"url": "https://example.com/working.pdf", "target_id": fid}).json()
    assert linked["of"]["kind"] == "Function"
    gone = maint.post("/api/v1/maintenance/failure_modes.remove_function", {"function_id": fid}).json()
    assert gone["documents_removed"] == [linked["id"]]
    spec = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    assert "Deprecated" in str(spec["paths"]["/api/v1/maintenance/failure_modes.add_function"])
