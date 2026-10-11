"""Reports (#30): composing saved items into one public share page, and
drafting its notes with the assistant (#41).

Access: a report is its owner's alone (others get 404 for every route); it
can hold only the owner's items and the samples; it is published with an
ordinary public link, so revoke, expiry and passphrase behave as for any
share; each section is checked again when the page is opened.
"""

import matplotlib

matplotlib.use("Agg")

import copy
import io
import json

import mongomock
import numpy as np
import pandas as pd
import pytest

A, B = "user-a", "user-b"
USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "Alice", "email_verified": True},
    B: {"uid": B, "email": "b@x.com", "name": "Bob", "email_verified": True},
}

# Every kind a report can hold, with the sample copied for the owner.
SAMPLES = {
    "models": "sample-model-bearings-weibull",
    "recurrent_models": "sample-rec-compressors",
    "degradation_models": "sample-deg-brake-wear",
    "rbds": "sample-rbd-pump-station",
    "strategy_analyses": "sample-strategy-bearing-replacement",
    "fleets": "sample-fleet-trucks",
    "rcm_studies": "sample-rcm-truck",
    "datasets": "sample-ds-bearings",
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)

    tc = TestClient(app)

    def act_as(uid):
        if uid is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: USERS[uid]
            test_db.users.update_one({"_id": uid}, {"$set": {"email": USERS[uid]["email"],
                                                             "name": USERS[uid]["name"]}}, upsert=True)

    tc.act_as = act_as
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _own_copy(db, collection, sample_id, owner=A, name=None):
    """A copy of a sample as ``owner``'s own item (references stay on the samples)."""
    doc = copy.deepcopy(db[collection].find_one({"_id": sample_id}))
    doc["_id"] = f"{owner}-{collection}"
    doc["owner_id"] = owner
    doc["name"] = name or doc["name"].replace(" (sample)", "")
    db[collection].insert_one(doc)
    return doc["_id"]


def _fit_model(client, name="Pump bearings"):
    rng = np.random.default_rng(7)
    csv = io.BytesIO(pd.DataFrame({"hours": rng.weibull(2.0, 40) * 1000}).to_csv(index=False).encode())
    r = client.post("/api/models", data={"name": name, "distribution": "weibull", "x": "hours", "unit": "hours"},
                    files={"file": ("data.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _report(client, sections, **extra):
    body = {"title": "Pump reliability review", "author": "Alice, Acme Mining",
            "introduction": "Quarterly review.", "sections": sections, **extra}
    return client.post("/api/reports", json=body)


def _link(client, report_id, **extra):
    r = client.post("/api/public-links", json={"collection": "reports", "artifact_id": report_id, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _view(client, token, unlock=None):
    client.act_as(None)
    headers = {"X-Share-Unlock": unlock} if unlock else {}
    return client.get(f"/api/public/{token}", headers=headers)


def _strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


# ---- composing ------------------------------------------------------------------

def test_owner_composes_saves_and_edits_a_report(client):
    client.act_as(A)
    model_id = _fit_model(client)
    r = _report(client, [{"collection": "models", "artifact_id": model_id, "note": "The main finding."},
                         {"collection": "strategy_analyses", "artifact_id": SAMPLES["strategy_analyses"]}])
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["title"] == "Pump reliability review" and rep["author"] == "Alice, Acme Mining"
    assert [s["name"] for s in rep["sections"]] == ["Pump bearings", "Bearing preventive replacement (sample)"]
    assert rep["sections"][0]["note"] == "The main finding." and rep["sections"][0]["kind"] == "Life model"

    # Saving publishes nothing.
    assert client.db.public_links.count_documents({}) == 0

    r = client.put(f"/api/reports/{rep['id']}", json={
        "title": "Renamed", "sections": [{"collection": "models", "artifact_id": model_id}]})
    assert r.status_code == 200 and r.json()["title"] == "Renamed" and len(r.json()["sections"]) == 1
    assert [x["id"] for x in client.get("/api/reports").json()["reports"]] == [rep["id"]]


def test_composer_validates_its_input(client):
    client.act_as(A)
    model_id = _fit_model(client)
    sec = {"collection": "models", "artifact_id": model_id}
    assert _report(client, []).status_code == 400
    assert _report(client, [sec], title="  ").status_code == 400
    assert _report(client, [sec, sec]).status_code == 400  # each item once
    assert _report(client, [{"collection": "users", "artifact_id": A}]).status_code == 400
    assert _report(client, [{"collection": "reports", "artifact_id": "x"}]).status_code == 400
    assert _report(client, [sec] * 13).status_code == 400
    assert _report(client, [{**sec, "note": "x" * 3001}]).status_code == 400


def test_items_picker_lists_own_items_first_then_samples(client):
    client.act_as(A)
    model_id = _fit_model(client)
    client.act_as(B)
    _fit_model(client, "Bob's model")
    client.act_as(A)
    client.db.users.update_one({"_id": A}, {"$set": {"hidden_samples": [SAMPLES["fleets"]]}})
    items = client.get("/api/reports/items").json()["items"]
    own = [i for i in items if not i["is_sample"]]
    assert {(i["collection"], i["name"]) for i in own} == {("models", "Pump bearings"), ("datasets", "data.csv")}
    assert model_id in {i["artifact_id"] for i in own}
    assert items[:len(own)] == own  # own items first, then the samples
    assert "Bob's model" not in {i["name"] for i in items}
    assert SAMPLES["fleets"] not in {i["artifact_id"] for i in items}  # hidden
    assert {i["collection"] for i in items} == set(SAMPLES) - {"fleets"}  # its one sample is hidden


# ---- access ---------------------------------------------------------------------

def test_a_report_is_its_owner_s_alone(client):
    client.act_as(A)
    model_id = _fit_model(client)
    rep = _report(client, [{"collection": "models", "artifact_id": model_id}]).json()

    client.act_as(B)
    assert client.get(f"/api/reports/{rep['id']}").status_code == 404
    assert client.put(f"/api/reports/{rep['id']}", json={
        "title": "x", "sections": [{"collection": "models", "artifact_id": model_id}]}).status_code in (404, 400)
    assert client.delete(f"/api/reports/{rep['id']}").status_code == 404
    assert client.get("/api/reports").json()["reports"] == []
    r = client.post("/api/public-links", json={"collection": "reports", "artifact_id": rep["id"]})
    assert r.status_code == 404
    # Nor can B put A's model in a report of B's own.
    assert _report(client, [{"collection": "models", "artifact_id": model_id}]).status_code == 404

    client.act_as(A)
    assert client.get(f"/api/reports/{rep['id']}").json()["title"] == "Pump reliability review"


def test_team_items_cant_go_in_a_report(client):
    client.act_as(A)
    _own_copy(client.db, "models", SAMPLES["models"], owner="team:t1")
    r = _report(client, [{"collection": "models", "artifact_id": "team:t1-models"}])
    assert r.status_code == 400 and "Team" in r.json()["detail"]


def test_public_report_page_and_revoked_link(client):
    client.act_as(A)
    model_id = _fit_model(client)
    rep = _report(client, [{"collection": "models", "artifact_id": model_id, "note": "Fitted to 40 failures."},
                           {"collection": "strategy_analyses", "artifact_id": SAMPLES["strategy_analyses"]}]).json()
    link = _link(client, rep["id"])
    assert link["path"] == f"/p/{link['token']}" and link["collection"] == "reports"

    r = _view(client, link["token"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["collection"] == "reports" and data["shared_by"] == "Alice"
    page = data["artifact"]
    assert page["name"] == "Pump reliability review" and page["author"] == "Alice, Acme Mining"
    assert page["introduction"] == "Quarterly review." and page["date"]
    first, second = page["sections"]
    assert first["note"] == "Fitted to 40 failures." and first["artifact"]["results"]["distribution"] == "Weibull"
    assert second["artifact"]["kind"] == "optimal_replacement"
    assert "owner_id" not in set(_strings(page))

    # The owner revokes it: gone at once.
    client.act_as(A)
    assert client.delete(f"/api/public-links/{link['token']}").status_code == 200
    assert _view(client, link["token"]).status_code == 404


def test_passphrase_protected_report(client):
    client.act_as(A)
    model_id = _fit_model(client)
    rep = _report(client, [{"collection": "models", "artifact_id": model_id}]).json()
    link = _link(client, rep["id"], generate_password=True)
    assert link["protected"] and link["passphrase"]

    r = _view(client, link["token"])
    assert r.status_code == 401 and r.json() == {"password_required": True}  # nothing about the report
    assert client.post(f"/api/public/{link['token']}/unlock", json={"password": "wrong-guess"}).status_code == 401
    unlock = client.post(f"/api/public/{link['token']}/unlock", json={"password": link["passphrase"]})
    assert unlock.status_code == 200
    r = _view(client, link["token"], unlock.json()["unlock_token"])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["artifact"]["name"] == "Pump reliability review"


def test_sections_are_checked_again_when_the_page_opens(client):
    """A deleted item, or one that left the owner, shows as unavailable —
    never someone else's data — and the rest of the report still renders."""
    client.act_as(A)
    m1, m2, m3 = (_fit_model(client, n) for n in ("Kept", "Deleted", "Moved"))
    rep = _report(client, [{"collection": "models", "artifact_id": m} for m in (m1, m2, m3)]).json()
    link = _link(client, rep["id"])
    client.db.models.delete_one({"_id": m2})
    client.db.models.update_one({"_id": m3}, {"$set": {"owner_id": B}})

    sections = _view(client, link["token"]).json()["artifact"]["sections"]
    assert sections[0]["artifact"]["name"] == "Kept" and sections[0]["unavailable"] is None
    for s in sections[1:]:
        assert s["artifact"] is None and s["name"] is None
        assert s["unavailable"] == "This item is no longer available."


def test_deleting_a_report_ends_its_links(client):
    client.act_as(A)
    rep = _report(client, [{"collection": "models", "artifact_id": _fit_model(client)}]).json()
    link = _link(client, rep["id"])
    assert client.delete(f"/api/reports/{rep['id']}").status_code == 200
    assert client.db.public_links.count_documents({"artifact_id": rep["id"]}) == 0
    assert _view(client, link["token"]).status_code == 404


# ---- rendering every item type ------------------------------------------------------

def test_every_item_kind_renders_in_a_report(client):
    """Each section carries exactly the payload the item's own share page
    gets: compared field by field with a single-item link to the same item."""
    from backend.services import reports

    assert set(SAMPLES) == set(reports.ITEM_KINDS)
    client.act_as(A)
    ids = {coll: _own_copy(client.db, coll, sid) for coll, sid in SAMPLES.items()}
    rep = _report(client, [{"collection": c, "artifact_id": i} for c, i in ids.items()]).json()
    page = _view(client, _link(client, rep["id"])["token"]).json()["artifact"]

    assert [s["collection"] for s in page["sections"]] == list(SAMPLES)
    by_coll = {s["collection"]: s for s in page["sections"]}
    for coll, item_id in ids.items():
        section = by_coll[coll]
        assert section["unavailable"] is None and section["artifact"], coll
        client.act_as(A)
        single = client.post("/api/public-links", json={"collection": coll, "artifact_id": item_id}).json()
        alone = _view(client, single["token"]).json()["artifact"]
        assert json.dumps(section["artifact"], sort_keys=True) == json.dumps(alone, sort_keys=True), coll

    # What each kind's page needs is there.
    assert by_coll["models"]["artifact"]["results"]["params"]
    assert by_coll["rbds"]["artifact"]["analysis"]["mttf"] > 0
    assert by_coll["fleets"]["artifact"]["forecast"]["status"] == "ok"
    assert by_coll["strategy_analyses"]["artifact"]["results"]["optimal_time"] > 0
    assert by_coll["recurrent_models"]["artifact"]["results"]["mtbf"] > 0
    assert by_coll["degradation_models"]["artifact"]["results"]["threshold"] == 8.0
    assert by_coll["rcm_studies"]["artifact"]["functions"]
    assert by_coll["datasets"]["artifact"]["preview"]


def test_a_repairable_diagram_in_a_report_shows_only_the_saved_result(client):
    """As on its own share page: the owner's saved result, or a plain note
    when there is none — never a simulation run for an anonymous viewer."""
    from backend.services import rbds

    client.act_as(A)
    saved = _own_copy(client.db, "rbds", "sample-rbd-instrument-air-availability")
    client.db.rbds.insert_one({**client.db.rbds.find_one({"_id": saved}), "_id": "not-run", "name": "Not run",
                               "availability_cache": None, "exact_cache": None})
    rbds.clear_exact_lru()
    rep = _report(client, [{"collection": "rbds", "artifact_id": saved},
                           {"collection": "rbds", "artifact_id": "not-run"}]).json()
    with_result, without = _view(client, _link(client, rep["id"])["token"]).json()["artifact"]["sections"]
    assert with_result["artifact"]["analysis"]["has_simulation"] is True
    assert without["artifact"]["analysis"] is None
    assert without["artifact"]["analysis_note"] == "The owner hasn't run the availability simulation for this diagram yet."


# ---- drafting the notes (#41) -----------------------------------------------------

def _tool_reply(intro, notes):
    def step(system, messages, tools):
        step.calls.append({"system": system, "messages": messages, "tools": tools})
        return {
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "write_report_notes",
                 "input": {"introduction": intro, "notes": notes}}]},
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1000, "output_tokens": 300},
        }

    step.calls = []
    return step


@pytest.fixture()
def ai(monkeypatch):
    from backend.services import assistant as assistant_service

    monkeypatch.setattr(assistant_service, "enabled", lambda: True)
    return assistant_service


def test_draft_words_the_stored_figures_and_flags_any_other(client, ai, monkeypatch):
    client.act_as(A)
    sections = [{"collection": "models", "artifact_id": SAMPLES["models"]},
                {"collection": "strategy_analyses", "artifact_id": SAMPLES["strategy_analyses"]}]
    step = _tool_reply("Bearings wear out, with a mean life of 1,270 hours.",
                       ["Fitted to 30 failures; B10 life is 582 hours.", "Replacing at 580 hours saves 73%."])
    monkeypatch.setattr(ai, "step", step)
    r = client.post("/api/reports/draft", json={"title": "Bearings", "sections": sections})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["introduction"].startswith("Bearings wear out")
    assert out["notes"] == ["Fitted to 30 failures; B10 life is 582 hours.", "Replacing at 580 hours saves 73%."]
    assert out["unverified"] == ["73"]  # the stored saving is 50%; nothing else is invented

    # The model was given the stored figures, and only them, with its own tool.
    call = step.calls[0]
    prompt = call["messages"][0]["content"]
    assert "MTTF (mean life): 1,270 hours" in prompt and "B10 life (10% failed): 582 hours" in prompt
    assert "Replace at: 580 hours" in prompt and "Saving against run-to-failure: 50%" in prompt
    assert [t["name"] for t in call["tools"]] == ["write_report_notes"]
    assert "Copy every figure exactly" in call["system"]
    # Nothing saved or published.
    assert client.db.reports.count_documents({}) == 0 and client.db.public_links.count_documents({}) == 0


def test_draft_accepts_a_plain_text_or_openai_reply(client, ai, monkeypatch):
    from backend.services import report_draft

    client.act_as(A)
    monkeypatch.setattr(ai, "step", lambda *a, **k: {
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Just text."}]},
        "usage": {"input_tokens": 10, "output_tokens": 10}})
    r = client.post("/api/reports/draft", json={"sections": [{"collection": "models",
                                                               "artifact_id": SAMPLES["models"]}]})
    assert r.json()["introduction"] == "Just text." and r.json()["notes"] == [""]

    openai_msg = [{"type": "reasoning"}, {"type": "function_call", "name": "write_report_notes",
                                          "arguments": json.dumps({"introduction": "Hi.", "notes": ["a", "b"]})}]
    assert report_draft.parse(openai_msg, 1) == {"introduction": "Hi.", "notes": ["a"]}


def test_draft_is_gated_like_the_assistant(client, monkeypatch):
    from backend import config
    from backend.services import assistant as assistant_service
    from backend.services import billing

    client.act_as(A)
    body = {"sections": [{"collection": "models", "artifact_id": SAMPLES["models"]}]}
    calls = []
    monkeypatch.setattr(assistant_service, "step", lambda *a, **k: calls.append(1))

    monkeypatch.setattr(assistant_service, "enabled", lambda: False)
    assert client.post("/api/reports/draft", json=body).status_code == 503

    monkeypatch.setattr(assistant_service, "enabled", lambda: True)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    client.db.users.update_one({"_id": A}, {"$set": {"credit_millicents": 0}})
    assert billing.account(client.db, A)["credit_cents"] == 0
    r = client.post("/api/reports/draft", json=body)
    assert r.status_code == 402 and r.json()["code"] == "no_credits"
    assert calls == []

    # Another user's item can't be drafted from either.
    client.act_as(B)
    other = _own_copy(client.db, "models", SAMPLES["models"], owner=A)
    r = client.post("/api/reports/draft", json={"sections": [{"collection": "models", "artifact_id": other}]})
    assert r.status_code == 404


def test_draft_is_metered_like_an_assistant_step(client, ai, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "AI_MODEL", "m")
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    monkeypatch.setattr(config, "AI_MARKUP", 1.0)
    client.act_as(A)
    billing.grant_credits(client.db, A, 500, "test")
    before = billing.account(client.db, A)["credit_millicents"]
    monkeypatch.setattr(ai, "step", _tool_reply("Intro.", ["Note."]))
    r = client.post("/api/reports/draft", json={"sections": [{"collection": "models",
                                                               "artifact_id": SAMPLES["models"]}]})
    assert r.status_code == 200
    # 1,000 in at $3/M + 300 out at $15/M = 7.5 millicents... charged exactly, hold released.
    spent = before - billing.account(client.db, A)["credit_millicents"]
    assert spent == billing.ai_cost_millicents("m", 1000, 300, 0)
    assert r.json()["credit_cents"] == billing.account(client.db, A)["credit_cents"]


# ---- facts --------------------------------------------------------------------------

def test_facts_round_to_three_significant_figures():
    from backend.services.report_facts import num, pct, unverified_numbers

    assert num(1273.228) == "1,270" and num(0.58371) == "0.584" and num(580.279) == "580"
    assert num(2.4952) == "2.5" and num(40.285) == "40.3" and num(1.2e-5) == "1.20e-05"
    assert num(None) is None and num(float("nan")) is None and num(True) is None
    assert pct(0.50453, 2) == "50%" and pct(0.99) == "99%"
    assert unverified_numbers("MTTF is 1,270 hours, about 2 years, 99.5% up", ["MTTF: 1,270 hours"]) == ["99.5"]
