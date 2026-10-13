"""Reliafy Maintenance: structured fields instead of notes. Dates known only
roughly (and life data that treats them as ranges), replacement costs,
warranties, document links, and the trade a task or work order needs."""

from datetime import date, timedelta

import mongomock
import numpy as np
import pytest

from backend.maintenance import loop
from backend.maintenance.service import (
    PROJECTORS, Invalid, LimitReached, Maintenance, NotFound, date_range, date_text, dated,
)
from backend.maintenance.store import GraphStore

ORG = "org-f"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _item(m, pid):
    return m.position(pid)["fitted"]["item"]["id"]


# ---- dates with precision ---------------------------------------------------------------

def test_a_date_keeps_how_well_it_is_known():
    assert dated("2022") == ("2022-01-01", "year")
    assert dated("2022-03") == ("2022-03-01", "month")
    assert dated("2022-03-15") == ("2022-03-15", "exact")
    assert dated("2022-03-15", "month") == ("2022-03-01", "month")
    assert dated("2022-07-01", "year") == ("2022-01-01", "year")
    assert dated("2022-03", "estimated") == ("2022-03-15", "estimated")
    assert dated("2022-03-20", "estimated") == ("2022-03-20", "estimated")
    for bad, precision in (("2022", "exact"), ("2022-03", "exact"), ("2022", "estimated"), ("2022-13", None),
                           ("2022-03-15", "roughly"), ("sometime", None)):
        with pytest.raises(Invalid):
            dated(bad, precision)
    # Shown as it's known: never a made-up day.
    assert [date_text(*dated(v)) for v in ("2022", "2022-03", "2022-03-05")] == ["2022", "Mar 2022", "5 Mar 2022"]
    assert date_text("2022-03-20", "estimated") == "~Mar 2022"
    assert date_range("2022-01-01", "year") == (date(2022, 1, 1), date(2022, 12, 31))
    assert date_range("2024-02-01", "month") == (date(2024, 2, 1), date(2024, 2, 29))
    assert date_range("2022-03-20", "estimated") == (date(2021, 12, 20), date(2022, 6, 20))


def test_rough_fitment_dates_make_ranges_in_the_life_data(m):
    pid = m.create_position("Pump", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "Old pump"}, on="2022")
    fitted = m.position(pid)["fitted"]
    assert (fitted["from"], fitted["from_precision"]) == ("2022-01-01", "year")
    m.remove(pid, on="2024-03", reason="failure")
    m.fit(pid, new_item={"name": "New pump"}, on="2024-03-20")
    m.remove(pid, on="2025-06-01", reason="planned")
    m.fit(pid, new_item={"name": "Newer pump"}, on="2025-06-01", from_precision="estimated")
    failed, removed, fitted = m.life_data(pid)
    # Failed somewhere between 1 Mar 2024 − 31 Dec 2022 and 31 Mar 2024 − 1 Jan 2022.
    assert (failed["c"], failed["xl"], failed["xr"], failed["x"]) == (2, 426, 820, 623)
    assert (failed["from_precision"], failed["to_precision"]) == ("year", "month")
    # Exact dates: as they always were (no range).
    assert (removed["c"], removed["x"]) == (1, 438) and "xl" not in removed
    # Still fitted, started about 1 Jun 2025: censored at the shortest life it surely has.
    shortest = (date.today() - date(2025, 9, 1)).days
    assert (fitted["c"], fitted["x"], fitted["xl"]) == (1, shortest, shortest)
    pooled = m.class_life_data("Pool pump")
    assert (pooled["failures"], pooled["suspensions"], pooled["uncertain"]) == (1, 2, 2)
    assert m.position_classes()[0]["failures"] == 1


def test_removal_and_corrections_take_a_precision(m):
    pid = m.create_position("Fan")["id"]
    m.fit(pid, new_item={"name": "Fan"}, on="2021-06-10")
    fid = m.position(pid)["fitted"]["id"]
    # Removed "in 2021": could be after 10 June, so it's allowed; exactly earlier isn't.
    with pytest.raises(Invalid):
        m.remove(pid, on="2021-06-01")
    out = m.remove(pid, on="2021", to_precision="year")["fitments"][0]
    assert (out["to"], out["to_precision"]) == ("2021-01-01", "year")
    # A precision alone re-reads the date there; a corrected day is exact again.
    fixed = m.correct_fitment(fid, from_precision="month")
    assert (fixed["from"], fixed["from_precision"]) == ("2021-06-01", "month")
    fixed = m.correct_fitment(fid, end="2021-11-30")
    assert (fixed["to"], fixed["to_precision"]) == ("2021-11-30", "exact")
    with pytest.raises(Invalid):
        m.correct_fitment(fid, end="2021-04")  # ends before it can have started
    with pytest.raises(Invalid):
        m.correct_fitment(fid, from_precision="sometimes")


def test_old_events_project_as_before(m):
    """Events written before precisions existed carry none: the graph is unchanged."""
    m.s.apply(ORG, "position.created", {"id": "p1", "name": "Pump", "on": "2024-01-01"})
    m.s.apply(ORG, "item.created", {"id": "i1", "name": "Pump", "on": "2024-01-01"})
    m.s.apply(ORG, "item.fitted", {"fitment_id": "f1", "item_id": "i1", "position_id": "p1", "on": "2024-01-01"})
    m.s.apply(ORG, "item.removed", {"fitment_id": "f1", "on": "2024-07-01", "reason": "failure"})
    m.s.apply(ORG, "fitment.corrected", {"id": "f1", "from": "2024-01-02"})
    node = m.s.node(ORG, "f1")
    assert {k: node[k] for k in node if k not in ("id", "label")} == {
        "from": "2024-01-02", "to": "2024-07-01", "end_reason": "failure", "failure_mode_id": None}
    m.s.apply(ORG, "task.added", {"id": "t1", "position_id": "p1", "name": "Check", "interval": 1,
                                  "unit": "months", "start": "2024-01-01"})
    m.s.apply(ORG, "work_order.opened", {"id": "w1", "number": 1, "title": "Check", "type": "preventive",
                                         "position_id": "p1", "task_id": "t1", "on": "2024-02-01"})
    assert "trade" not in m.s.node(ORG, "w1")
    assert m.life_data("p1")[0]["x"] == 181 and "xl" not in m.life_data("p1")[0]


def test_a_class_model_fits_interval_data_end_to_end(m):
    """Failures whose start is known only to the year are fitted as intervals; the
    result matches SurPyval fitting the same intervals directly."""
    from surpyval import Weibull

    db = mongomock.MongoClient()["fields"]
    lives = [700, 760, 820, 690, 840, 780, 730, 800]
    for i, life in enumerate(lives):
        pid = m.create_position(f"Pump {i}", position_class="Pump")["id"]
        start = date(2015, 1, 1) + timedelta(days=37 * i)
        rough = i % 2 == 0
        m.fit(pid, new_item={"name": f"P{i}"}, on=str(start.year) if rough else start.isoformat())
        m.remove(pid, on=(start + timedelta(days=life)).isoformat(), reason="failure")
        m.fit(pid, new_item={"name": f"P{i}b"}, on=(start + timedelta(days=life)).isoformat())
        m.remove(pid, on=(start + timedelta(days=life + 400)).isoformat(), reason="planned")
    data = m.class_life_data("Pump")
    assert data["uncertain"] == 4 and data["failures"] == 8
    out = loop.fit_class_model(m, db, "Pump")
    assert out["uncertain"] == 4 and out["model"]["failures"] == 8 and out["model"]["suspensions"] == 8
    model = db.models.find_one({"_id": out["model"]["model_id"]})
    assert model["spec"]["mapping"] == {"xl": "shortest", "xr": "longest", "c": "censored"}

    rows = loop._interval_rows([r for r in data["rows"]])
    xl, xr, c = (np.array(col, float) for col in zip(*rows))
    expected = Weibull.fit(xl=xl, xr=xr, c=c.astype(int))
    got = {p["name"]: p["value"] for p in out["model"]["params"]}
    assert got["alpha"] == pytest.approx(expected.alpha, rel=1e-3)
    assert got["beta"] == pytest.approx(expected.beta, rel=1e-3)
    # The intervals are honest: every rough failure's range holds its true life.
    for r in data["rows"]:
        if r["c"] != 1:
            life = lives[int(r["position"].split()[-1])]
            assert r["xl"] <= life <= r["xr"] if r["c"] == 2 else r["x"] == life


def test_exact_data_fits_exactly_as_before(m):
    db = mongomock.MongoClient()["fields-exact"]
    for i, life in enumerate([700, 760, 820]):
        pid = m.create_position(f"Pump {i}", position_class="Exact pump")["id"]
        m.fit(pid, new_item={"name": f"P{i}"}, on=_ago(2000))
        m.remove(pid, on=_ago(2000 - life), reason="failure")
    out = loop.fit_class_model(m, db, "Exact pump")
    assert out["uncertain"] == 0
    model = db.models.find_one({"_id": out["model"]["model_id"]})
    assert model["spec"]["mapping"] == {"x": "days", "c": "censored"}


def test_a_failure_that_may_have_been_at_once_is_left_censored():
    rows = [{"c": 2, "xl": 0, "xr": 300, "x": 150}, {"c": 2, "xl": 10, "xr": 40, "x": 25},
            {"c": 1, "x": 90}, {"c": 0, "x": 70}]
    assert loop._interval_rows(rows) == [(300, 300, -1), (10, 40, 2), (90, 90, 1), (70, 70, 0)]


# ---- item dates, replacement cost and warranty ------------------------------------------------

def test_item_dates_with_precision_and_source(m):
    pid = m.create_position("Hot water")["id"]
    m.fit(pid, new_item={"name": "Rheem", "purchase_date": {"date": "2022", "source": "receipt"}}, on="2022-02-01")
    iid = _item(m, pid)
    item = m.update_item(iid, in_service_date="2022-02", manufacture_date={
        "date": "2021-11-20", "precision": "estimated", "source": "serial date code"})
    assert item["purchase_date"] == {"date": "2022-01-01", "precision": "year", "source": "receipt", "display": "2022"}
    assert item["in_service_date"]["display"] == "Feb 2022"
    assert item["manufacture_date"]["display"] == "~Nov 2021"
    assert m.update_item(iid, purchase_date=None)["purchase_date"] is None
    for bad in ({"precision": "year"}, {"date": "2999"}, {"date": "2022", "precision": "exact"}, 12,
                {"date": "2022", "source": "x" * 201}):
        with pytest.raises(Invalid):
            m.update_item(iid, purchase_date=bad)
    with pytest.raises(Invalid):  # checked before the item is made
        m.create_item("Bad", purchase_date={"date": "tomorrow"})
    assert len(m.items()) == 1


def test_replacement_cost_on_items_and_classes(m):
    pid = m.create_position("Pump A", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "Astral"}, on=_ago(10))
    iid = _item(m, pid)
    assert m.item(iid)["class_replacement_cost"] is None
    cls = m.set_class_replacement_cost("pool pump", {"amount": 900, "currency": "aud", "source": "list price"})
    assert cls["replacement_cost"] == {"amount": 900.0, "currency": "AUD", "source": "list price",
                                       "as_of": date.today().isoformat()}
    item = m.item(iid)
    assert item["replacement_cost"] is None and item["class_replacement_cost"]["position_class"] == "Pool pump"
    item = m.update_item(iid, replacement_cost={"amount": "1150.5", "currency": "AUD", "source": "supplier quote",
                                                "as_of": "2026-09-01"})
    assert item["replacement_cost"]["amount"] == 1150.5 and item["replacement_cost"]["as_of"] == "2026-09-01"
    for bad in ({"currency": "AUD"}, {"amount": -1}, {"amount": 5, "currency": "dollars"},
                {"amount": 5, "as_of": "2999-01-01"}, {"amount": float("nan")}, [1]):
        with pytest.raises(Invalid):
            m.update_item(iid, replacement_cost=bad)
    assert m.set_class_replacement_cost("Pool pump", None)["replacement_cost"] is None
    with pytest.raises(NotFound):
        m.set_class_replacement_cost("No such class", {"amount": 1})


def test_warranty_shows_on_the_item_and_flags_work_orders(m):
    pid = m.create_position("Heat pump")["id"]
    m.fit(pid, new_item={"name": "Daikin"}, on=_ago(100))
    iid = _item(m, pid)
    ends, register_by = _ago(-600), _ago(-20)
    item = m.update_item(iid, warranty={"ends_on": ends, "terms": "5 years parts and labour",
                                        "coverage": "compressor, fan motor", "register_by": register_by})
    w = item["warranty"]
    assert w["in_warranty"] and w["registration_required"] and w["registration_due"] == register_by
    assert w["summary"].startswith("In warranty until ") and "registration due by" in w["summary"]
    wo = m.open_work_order(pid, "Not heating")
    assert wo["warranty"]["item"]["id"] == iid and wo["warranty"]["coverage"] == "compressor, fan motor"
    assert m.work_orders("open")[0]["under_warranty"] is True
    # Registered: nothing due. Past the end: not flagged.
    assert m.update_item(iid, warranty={**{k: w[k] for k in ("ends_on", "terms", "coverage")},
                                        "registration_required": True, "registered": True}
                         )["warranty"]["registration_due"] is None
    m.update_item(iid, warranty={"ends_on": _ago(5)})
    assert m.item(iid)["warranty"]["summary"].startswith("Warranty ended")
    assert m.open_work_order(pid, "Noisy")["warranty"] is None
    for bad in ({"terms": "x"}, {"ends_on": "soon"}, {"ends_on": ends, "registered": "maybe"}):
        with pytest.raises(Invalid):
            m.update_item(iid, warranty=bad)
    assert m.update_item(iid, warranty=None)["warranty"] is None


def test_a_closed_work_order_keeps_the_warranty_of_the_item_it_was_raised_for(m):
    pid = m.create_position("Pump")["id"]
    m.fit(pid, new_item={"name": "Old"}, on=_ago(300))
    old = _item(m, pid)
    m.update_item(old, warranty={"ends_on": _ago(-30)})
    wo = m.open_work_order(pid, "Seized")
    m.close_work_order(wo["id"], [{"kind": "replace", "new_item": {"name": "New"}}])
    assert m.work_order(wo["id"])["warranty"]["item"]["id"] == old


# ---- documents -------------------------------------------------------------------------------

def test_documents_on_items_positions_and_classes(m):
    pid = m.create_position("Pump", position_class="Pool pump")["id"]
    m.fit(pid, new_item={"name": "Astral"}, on=_ago(10))
    iid = _item(m, pid)
    manual = m.add_document("https://example.com/docs/ctx-manual.pdf", kind="manual", target_id=iid)
    assert manual["title"] == "ctx-manual.pdf" and manual["of"]["kind"] == "Item"
    m.add_document("http://example.com/inv/42", "Invoice 42", "invoice", target_id=iid)
    m.add_document("https://example.com/pid.pdf", "P&ID", "drawing", target_id=pid)
    sheet = m.add_document("https://example.com/sheet", "CTX datasheet", "datasheet", position_class="pool pump")
    assert sheet["of"]["kind"] == "PositionClass"
    assert [d["kind"] for d in m.item(iid)["documents"]] == ["manual", "invoice"]
    assert [d["title"] for d in m.position(pid)["documents"]] == ["P&ID"]
    assert [d["title"] for d in m.position_class("Pool pump")["documents"]] == ["CTX datasheet"]
    m.remove_document(manual["id"])
    assert [d["kind"] for d in m.item(iid)["documents"]] == ["invoice"]
    with pytest.raises(Invalid):
        m.remove_document(manual["id"])
    with pytest.raises(NotFound):
        m.add_document("https://example.com/x", target_id="nope")
    with pytest.raises(NotFound):
        m.add_document("https://example.com/x", position_class="No class")
    with pytest.raises(Invalid):
        m.add_document("https://example.com/x")  # for what?
    with pytest.raises(Invalid):
        m.add_document("https://example.com/x", kind="brochure", target_id=iid)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "JavaScript:alert(1)", " javascript:alert(1)", "data:text/html,<b>x</b>",
    "vbscript:msgbox(1)", "file:///etc/passwd", "ftp://example.com/a", "//example.com/a", "example.com/manual",
    "https://", "https://user:pw@example.com/", "https://example.com/a b", "https://exa\nmple.com/",
    "https://example.com/\x00", "", "https://example.com/" + "a" * 2000,
])
def test_only_web_links_are_kept(m, url):
    pid = m.create_position("P")["id"]
    with pytest.raises(Invalid):
        m.add_document(url, target_id=pid)


def test_documents_per_target_are_limited(m, monkeypatch):
    from backend.maintenance import service

    monkeypatch.setattr(service, "MAX_DOCUMENTS_EACH", 2)
    pid = m.create_position("P")["id"]
    m.add_document("https://example.com/1", target_id=pid)
    m.add_document("https://example.com/2", target_id=pid)
    with pytest.raises(LimitReached):
        m.add_document("https://example.com/3", target_id=pid)


# ---- trade -----------------------------------------------------------------------------------

def test_a_task_s_trade_goes_onto_its_work_orders(m):
    pid = m.create_position("Switchboard")["id"]
    m.s.apply(ORG, "task.added", {"id": "t1", "position_id": pid, "name": "Test RCDs", "interval": 6,
                                  "unit": "months", "start": _ago(400)})
    task = m.update_task("t1", trade="Licensed electrician")
    assert task["trade"] == "Licensed electrician"
    [wo] = m.generate_work_orders(30)
    assert wo["trade"] == "Licensed electrician"
    assert m.work_orders("open")[0]["trade"] == "Licensed electrician"
    assert m.update_work_order(wo["id"], trade="Electrical apprentice, supervised")["trade"] == \
        "Electrical apprentice, supervised"
    assert m.update_work_order(wo["id"], trade="")["trade"] == ""
    other = m.open_work_order(pid, "Replace RCD", task_id="t1", trade="A-grade electrician")
    assert other["trade"] == "A-grade electrician"
    assert m.open_work_order(pid, "Clean")["trade"] == ""
    with pytest.raises(Invalid):
        m.update_task("t1", trade="x" * 201)
    assert m.update_task("t1", trade="")["trade"] == ""


# ---- through the API and MCP -------------------------------------------------------------------

@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.maintenance import photos
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"f@example.org"})
    test_db = mongomock.MongoClient()["maint_fields_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    user = {"uid": "user-f", "email": "f@example.org", "name": "F", "email_verified": True}
    test_db.users.insert_one({"_id": "user-f", "email": "f@example.org", "name": "F", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_fields_through_the_api(api):
    base = "/api/maintenance"
    pid = api.post(f"{base}/positions", json={"name": "Pump", "position_class": "Pool pump"}).json()["id"]
    pos = api.post(f"{base}/positions/{pid}/fit", json={"new_item": {"name": "Astral"}, "on": "2022"}).json()
    assert pos["fitted"]["from_precision"] == "year"
    iid = pos["fitted"]["item"]["id"]
    item = api.patch(f"{base}/items/{iid}", json={
        "purchase_date": {"date": "2021-12", "source": "receipt"}, "warranty": {"ends_on": "2030-01-01"},
        "replacement_cost": {"amount": 800, "currency": "AUD"}}).json()
    assert item["purchase_date"]["display"] == "Dec 2021" and item["warranty"]["in_warranty"]
    assert api.patch(f"{base}/items/{iid}", json={"warranty": None}).json()["warranty"] is None
    assert api.patch(f"{base}/items/{iid}", json={"replacement_cost": {"amount": -5}}).status_code == 422
    doc = api.post(f"{base}/documents", json={"target_id": iid, "url": "https://example.com/m.pdf",
                                               "kind": "manual"}).json()
    assert api.post(f"{base}/documents", json={"target_id": iid, "url": "javascript:alert(1)"}).status_code == 422
    assert api.get(f"{base}/items/{iid}").json()["documents"][0]["id"] == doc["id"]
    assert api.delete(f"{base}/documents/{doc['id']}").json() == {"removed": doc["id"]}
    cls = api.put(f"{base}/classes/replacement-cost", json={"position_class": "Pool pump",
                                                           "replacement_cost": {"amount": 700}}).json()
    assert cls["replacement_cost"]["amount"] == 700
    fid = pos["fitted"]["id"]
    fixed = api.patch(f"{base}/fitments/{fid}", json={"start": "2022-05", "from_precision": "month"}).json()
    assert (fixed["from"], fixed["from_precision"]) == ("2022-05-01", "month")
    out = api.post(f"{base}/positions/{pid}/remove", json={"on": "2025", "to_precision": "year"}).json()
    assert out["fitments"][0]["to_precision"] == "year"
    wo = api.post(f"{base}/work-orders", json={"position_id": pid, "title": "Rewire", "trade": "Electrician"}).json()
    assert wo["trade"] == "Electrician"
    assert api.patch(f"{base}/work-orders/{wo['id']}", json={"trade": "Gas fitter"}).json()["trade"] == "Gas fitter"
