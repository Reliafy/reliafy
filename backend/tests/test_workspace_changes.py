"""What changed in a workspace over a period (#41): every fact from stored
data — timestamps, the refit and forecast logs, alert firings and runs."""

import matplotlib

matplotlib.use("Agg")

import io
from datetime import datetime, timedelta, timezone

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval

from backend.config import SAMPLE_OWNER

A, B, C = "user-a", "user-b", "user-c"
USERS = {
    A: {"uid": A, "email": "a@x.com", "name": "Ann", "email_verified": True},
    B: {"uid": B, "email": "b@x.com", "name": "Bob", "email_verified": True},
    C: {"uid": C, "email": "c@x.com", "name": "Cy", "email_verified": True},
}
NOW = datetime.now(timezone.utc)


def ago(**kw):
    return NOW - timedelta(**kw)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_changes_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    tc = TestClient(app)
    tc.db = test_db

    def act_as(uid):
        app.dependency_overrides[get_current_user] = lambda: USERS[uid]

    tc.act_as = act_as
    act_as(A)
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def changes(client, **params):
    r = client.get("/api/changes", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def put(db, coll, _id, owner, created, updated=None, **extra):
    db[coll].insert_one({"_id": _id, "id": _id, "name": _id.replace("-", " ").title(), "owner_id": owner,
                         "created_at": created, "updated_at": updated or created, **extra})


WEIBULL_RESULTS = {"kind": "distribution", "distribution_id": "weibull", "distribution": "Weibull",
                   "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}], "n": 20,
                   "unit": "Hours"}


# ---- New and changed items --------------------------------------------------------------

def test_new_and_changed_items_are_the_workspaces_own(client):
    db = client.db
    put(db, "models", "pump-model", A, ago(days=5), results=WEIBULL_RESULTS)
    put(db, "rbds", "skid-diagram", A, ago(days=60), ago(days=3), updated_by={"uid": B, "name": "Bob"})
    put(db, "datasets", "old-data", A, ago(days=60))
    put(db, "rcm_studies", "old-study", A, ago(days=40), ago(days=40))
    put(db, "models", "someone-elses", C, ago(days=1))
    put(db, "models", "a-sample", SAMPLE_OWNER, ago(days=1))
    out = changes(client)
    assert [(r["collection"], r["id"], r["url"]) for r in out["new"]] == [
        ("models", "pump-model", "/models/m/pump-model")]
    assert [(r["id"], r.get("by")) for r in out["changed"]] == [("skid-diagram", "Bob")]
    assert out["counts"]["items"] == 4
    assert out["sentence"] == "In the last 30 days: 1 item was added and 1 changed."
    # A shorter period leaves the five-day-old model out.
    short = changes(client, days=4)
    assert short["new"] == [] and [r["id"] for r in short["changed"]] == ["skid-diagram"]
    assert short["sentence"] == "In the last 4 days: 1 item changed."


def test_a_condition_based_model_is_labelled_and_linked_as_one(client):
    # Joint models live in ``models`` with kind "joint": the feed must not call
    # them non-repairable models or link them to the life-model page (which can't open them).
    db = client.db
    put(db, "models", "pump-risk", A, ago(days=2), kind="joint")
    put(db, "models", "pump-life", A, ago(days=1), results=WEIBULL_RESULTS)
    out = changes(client)
    rows = {r["id"]: (r["type"], r["url"]) for r in out["new"]}
    assert rows["pump-risk"] == ("Condition and life model", "/models/joint/pump-risk")
    assert rows["pump-life"] == ("Non-repairable model", "/models/m/pump-life")


def test_an_empty_period_says_nothing_changed(client):
    put(client.db, "models", "old-model", A, ago(days=90), results=WEIBULL_RESULTS)
    out = changes(client)
    assert out["sentence"] == "Nothing changed in the last 30 days."
    assert out["counts"]["items"] == 1
    for key in ("new", "changed", "refits", "forecasts", "alerts", "rcm_evidence", "simulations"):
        assert out[key] == [], key
    # What can't be compared is said, whatever the period.
    assert any("Failures recorded against the forecast" == n["what"] for n in out["not_compared"])


def test_readings_on_tracked_items_change_their_fleet(client):
    db = client.db
    put(db, "tracked_fleets", "brake-fleet", A, ago(days=90), model_id="m")
    for i, at in enumerate((ago(days=2), ago(days=1), ago(days=50))):
        db.tracked_items.insert_one({"_id": f"t{i}", "fleet_id": "brake-fleet", "owner_id": A,
                                     "created_at": ago(days=90), "updated_at": at})
    (row,) = changes(client)["changed"]
    assert row["id"] == "brake-fleet" and row["detail"] == "new readings on 2 items"
    assert row["url"] == "/risk/brake-fleet"


# ---- Refits ----------------------------------------------------------------------------

def _csv(x) -> bytes:
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_a_refit_on_new_data_moves_b10_and_mttf_by_the_engines_numbers(client):
    from backend.services import datasets as datasets_service
    from backend.services import ingest
    from backend.services import models as models_service

    db = client.db
    rng = np.random.default_rng(3)
    first = np.round(1000 * rng.weibull(2.0, 30), 1)
    later = np.round(300 * rng.weibull(2.0, 30), 1)
    dataset = datasets_service.create_dataset(db, "Pump lives", _csv(first), A)
    model = models_service.save_model(db, "Pump life", dataset, "weibull", {"x": "t"}, [], None, "hours", A)
    db.models.update_one({"_id": model.id}, {"$set": {"created_at": ago(days=60), "updated_at": ago(days=60)}})
    db.datasets.update_one({"_id": dataset.id}, {"$set": {"created_at": ago(days=60)}})

    ingest.append_dataset_rows(db, dataset.id, A, pd.DataFrame({"t": later}))
    assert db.model_refits.count_documents({"model_id": model.id}) == 1

    out = changes(client)
    (refit,) = out["refits"]
    before, after = surpyval.Weibull.fit(first), surpyval.Weibull.fit(np.concatenate([first, later]))
    moved = {m["measure"]: m for m in refit["moved"]}
    assert moved["B10"]["before"] == pytest.approx(float(before.qf(0.1)), rel=1e-6)
    assert moved["B10"]["after"] == pytest.approx(float(after.qf(0.1)), rel=1e-6)
    assert moved["MTTF"]["before"] == pytest.approx(float(before.mean()), rel=1e-6)
    assert moved["MTTF"]["after"] == pytest.approx(float(after.mean()), rel=1e-6)
    assert moved["B10"]["change"] == pytest.approx(after.qf(0.1) / before.qf(0.1) - 1, rel=1e-6)
    assert refit["before"]["n"] == 30 and refit["after"]["n"] == 60
    assert refit["url"] == f"/models/m/{model.id}"
    # The appended dataset shows as changed; the refitted model is listed once, as a refit.
    assert [r["id"] for r in out["changed"]] == [dataset.id]
    assert out["counts"]["refits_moved"] == 1
    assert out["sentence"] == "In the last 30 days: 1 refit moved its answer and 1 item changed."


def test_a_refit_moves_only_past_the_threshold(client):
    from backend.services import workspace_changes as wc

    db = client.db
    for mid in ("held", "moved", "older"):
        put(db, "models", mid, A, ago(days=90), results=WEIBULL_RESULTS)

    def life(b10, mttf):
        return {**WEIBULL_RESULTS, "life": {"b_lives": [{"label": "B10", "value": b10}], "mttf": {"value": mttf}}}

    wc.record_refit(db, "held", A, life(1000, 2000), life(1050, 2100), now=ago(days=3))
    wc.record_refit(db, "moved", A, life(1000, 2000), life(1040, 2000), now=ago(days=9))
    wc.record_refit(db, "moved", A, life(1040, 2000), life(800, 1990), now=ago(days=2))
    wc.record_refit(db, "older", A, life(1000, 2000), life(500, 900), now=ago(days=45))
    refits = {r["id"]: r for r in changes(client)["refits"]}
    assert set(refits) == {"held", "moved"}
    assert refits["held"]["moved"] == [] and refits["held"]["comparable"]
    # Over the period: the first refit's before against the last one's after.
    assert [(m["measure"], m["before"], m["after"]) for m in refits["moved"]["moved"]] == [("B10", 1000, 800)]
    assert refits["moved"]["moved"][0]["change"] == pytest.approx(-0.2)
    assert refits["moved"]["refits"] == 2


# ---- Fleets ----------------------------------------------------------------------------

def _fleet(db, fid, owner, model_id="fleet-model"):
    from backend.services import fleet as fleet_service

    if db.models.find_one({"_id": model_id}) is None:
        put(db, "models", model_id, owner, ago(days=200), results=WEIBULL_RESULTS)
    fleet = fleet_service.create_fleet(db, fid, model_id, owner)
    fleet_service.replace_items(db, fleet.id, {"periods": 12, "period_label": "months", "default_rate": 50},
                                [{"name": f"Unit {i}", "current_use": 200.0 * i} for i in range(1, 6)], owner)
    db.fleets.update_one({"_id": fleet.id}, {"$set": {"created_at": ago(days=120), "updated_at": ago(days=120)}})
    return fleet.id


def test_a_fleets_expected_failures_against_the_forecast_recorded_before_the_period(client):
    from backend.db import from_doc
    from backend.schema import Fleet
    from backend.services import fleet as fleet_service

    db = client.db
    fid = _fleet(db, "trucks", A)
    _fleet(db, "loaders", A)  # nothing recorded before the period
    live = fleet_service.compute(db, from_doc(Fleet, db.fleets.find_one({"_id": fid})), [A, SAMPLE_OWNER])
    db.fleet_forecasts.insert_one({"_id": "f0", "fleet_id": fid, "owner_id": A, "at": ago(days=40),
                                   "expected": live["expected"] / 2, "periods": 12, "period_label": "months"})
    out = changes(client)
    (row,) = out["forecasts"]
    assert row["id"] == fid and row["moved"]
    assert row["after"]["expected"] == pytest.approx(live["expected"])
    assert row["change"] == pytest.approx(1.0)
    assert out["not_compared"][0]["what"] == "Expected failures of 1 fleet"
    assert "1 forecast moved its answer" in out["sentence"]
    # The forecast just computed was recorded.
    assert db.fleet_forecasts.count_documents({"fleet_id": fid}) == 2


def test_forecasts_are_logged_once_a_day_unless_they_change(client):
    from types import SimpleNamespace

    from backend.services import workspace_changes as wc

    db = client.db
    fleet = SimpleNamespace(id="f", owner_id=A, settings={"periods": 12, "period_label": "months"})
    ok = {"status": "ok", "expected": 3.0}
    wc.note_forecast(db, fleet, ok, now=ago(hours=30))
    wc.note_forecast(db, fleet, ok, now=ago(hours=29))
    assert db.fleet_forecasts.count_documents({}) == 1
    wc.note_forecast(db, fleet, {**ok, "expected": 3.5}, now=ago(hours=28))
    wc.note_forecast(db, fleet, {**ok, "expected": 3.5}, now=ago(hours=1))
    assert db.fleet_forecasts.count_documents({}) == 3
    wc.note_forecast(db, fleet, {"status": "stale"})
    wc.note_forecast(db, SimpleNamespace(id="s", owner_id=SAMPLE_OWNER, settings={}), ok)
    assert db.fleet_forecasts.count_documents({}) == 3


def test_opening_a_fleet_records_its_forecast(client):
    fid = _fleet(client.db, "trucks", A)
    assert client.get(f"/api/fleet/fleets/{fid}").status_code == 200
    assert client.db.fleet_forecasts.count_documents({"fleet_id": fid}) == 1


def test_fleet_alerts_that_fired_in_the_period(client):
    db = client.db
    fid = _fleet(db, "trucks", A)
    other = _fleet(db, "c-fleet", C, model_id="c-model")
    base = {"kind": "above", "threshold": 2.0, "previous_value": 1.5, "new_value": 2.4, "sent": True}
    db.fleet_alert_events.insert_many([
        {"_id": "e1", "fleet_id": fid, "created_at": ago(days=2), **base},
        {"_id": "e2", "fleet_id": fid, "created_at": ago(days=45), **base},
        {"_id": "e3", "fleet_id": other, "created_at": ago(days=2), **base},
    ])
    out = changes(client)
    (alert,) = out["alerts"]
    assert alert["fleet_id"] == fid and alert["emailed"]
    assert alert["text"] == "Expected failures for trucks rose above 2"
    assert "1 fleet alert fired" in out["sentence"]


# ---- RCM evidence ----------------------------------------------------------------------

def test_rcm_evidence_whose_model_was_refitted_shows_its_status_before_and_now(client):
    from backend.services import workspace_changes as wc

    db = client.db
    wear_out = {**WEIBULL_RESULTS, "randomness": {"verdict": "wear_out", "beta": 3.1, "beta_ci": [2.2, 4.4]}}
    random_ = {**WEIBULL_RESULTS, "randomness": {"verdict": "random", "beta": 1.1, "beta_ci": [0.7, 1.6]}}
    put(db, "models", "seal-model", A, ago(days=90), results=wear_out)
    put(db, "models", "other-model", A, ago(days=90), results=random_)
    tree = [{"id": "f1", "text": "Pump water", "failures": [{"id": "ff1", "text": "No flow", "modes": [
        {"id": "m1", "text": "Seal leak", "consequence": "operational",
         "decision": {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": "seal-model"}}},
        {"id": "m2", "text": "Bearing", "consequence": "operational",
         "decision": {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": "other-model"}}},
    ]}]}]
    put(db, "rcm_studies", "pump-study", A, ago(days=90), functions=tree)
    wc.record_refit(db, "seal-model", A, random_, wear_out, now=ago(days=4))
    out = changes(client)
    (row,) = out["rcm_evidence"]
    assert (row["mode"], row["status_before"], row["status"], row["status_changed"]) == (
        "Seal leak", "supported", "contradicted", True)
    assert row["url"] == "/maintenance/rcm/pump-study" and row["evidence_url"] == "/models/m/seal-model"
    # The refit itself reports the pattern it changed.
    (refit,) = out["refits"]
    assert {"measure": "Failure pattern", "before": "random", "after": "wear-out"} in refit["moved"]
    assert "evidence changed on 1 RCM decision" in out["sentence"]


# ---- Simulation runs -------------------------------------------------------------------

def _run(db, rid, rbd_id, finished, availability):
    db.rbd_jobs.insert_one({"_id": rid, "kind": "availability", "status": "done", "uid": A, "rbd_id": rbd_id,
                            "created_at": finished, "finished_at": finished,
                            "result": {"precision": {"window_availability": availability}}})


def test_availability_simulations_against_the_run_before_the_period(client):
    db = client.db
    put(db, "rbds", "line-1", A, ago(days=100))
    put(db, "rbds", "line-2", A, ago(days=100))
    _run(db, "r0", "line-1", ago(days=35), 0.95)
    _run(db, "r1", "line-1", ago(days=5), 0.93)
    _run(db, "r2", "line-1", ago(days=1), 0.90)
    _run(db, "r3", "line-2", ago(days=1), 0.99)
    sims = {s["id"]: s for s in changes(client)["simulations"]}
    assert sims["line-1"]["moved"] and sims["line-1"]["runs"] == 2
    assert sims["line-1"]["before"] == {"availability": 0.95, "at": sims["line-1"]["before"]["at"], "run_id": "r0"}
    assert sims["line-1"]["after"] == {"availability": 0.90} and sims["line-1"]["run_id"] == "r2"
    assert not sims["line-2"]["moved"] and sims["line-2"]["before"] is None


# ---- Team workspaces -------------------------------------------------------------------

def test_a_team_workspace_shows_the_teams_items_to_its_members_only(client):
    from backend.services import teams

    db = client.db
    team = teams.create_team(db, "Crew", USERS[A])
    db.teams.update_one({"_id": team["_id"]}, {"$push": {"members": {"uid": B, "email": "b@x.com",
                                                                      "name": "Bob", "role": "member"}}})
    put(db, "models", "team-model", f"team:{team['_id']}", ago(days=1), results=WEIBULL_RESULTS)
    put(db, "models", "ann-model", A, ago(days=1), results=WEIBULL_RESULTS)
    team_header = {"X-Workspace-Id": team["_id"]}

    client.act_as(B)
    assert changes(client)["counts"]["items"] == 0  # Bob's personal workspace is empty
    r = client.get("/api/changes", headers=team_header)
    assert [x["id"] for x in r.json()["new"]] == ["team-model"]
    client.act_as(A)
    assert [x["id"] for x in changes(client)["new"]] == ["ann-model"]
    client.act_as(C)
    assert client.get("/api/changes", headers=team_header).status_code == 403


# ---- The period ------------------------------------------------------------------------

def test_since_my_last_visit(client):
    from backend.auth import upsert_user

    db = client.db
    fallback = changes(client, since="last_visit")
    assert fallback["period"]["kind"] == "days" and "No earlier visit" in fallback["period"]["note"]

    db.users.insert_one({"_id": A, "last_login": ago(days=3)})
    upsert_user(db, USERS[A])
    visit = db.users.find_one({"_id": A})["previous_visit_at"]
    upsert_user(db, USERS[A])  # a reload minutes later is the same visit
    assert db.users.find_one({"_id": A})["previous_visit_at"] == visit
    put(db, "models", "since-visit", A, ago(days=2), results=WEIBULL_RESULTS)
    put(db, "models", "before-visit", A, ago(days=4), results=WEIBULL_RESULTS)
    out = changes(client, since="last_visit")
    assert out["period"]["kind"] == "last_visit"
    assert out["period"]["label"].startswith("since your last visit (")
    assert [r["id"] for r in out["new"]] == ["since-visit"]
    assert out["sentence"].startswith("Since your last visit (")


@pytest.mark.parametrize("params", [{"since": "soon"}, {"days": 0}, {"days": 400},
                                    {"since": (NOW + timedelta(days=2)).date().isoformat()}])
def test_a_bad_period_is_refused(client, params):
    r = client.get("/api/changes", params=params)
    assert r.status_code == 422 and r.json()["detail"]


def test_since_a_date(client):
    put(client.db, "models", "m", A, ago(days=10), results=WEIBULL_RESULTS)
    out = changes(client, since=ago(days=12).date().isoformat())
    assert out["period"]["kind"] == "date" and [r["id"] for r in out["new"]] == ["m"]


# ---- The in-app assistant ------------------------------------------------------------

def test_the_assistant_calls_the_tool_and_words_its_answer_from_the_computed_facts(client, monkeypatch):
    """The server owns the tool; the browser runs it against GET /api/changes
    (agent.js); the provider — stubbed here — only words the facts it gets back."""
    import json

    from backend.services import assistant as assistant_service
    from backend.services import assistant_spec

    tool = next(t for t in assistant_spec.TOOLS if t["name"] == "workspace_changes")
    assert set(tool["parameters"]["properties"]) == {"days", "since"}
    assert "workspace_changes" in assistant_spec.SYSTEM_PROMPT and "/changes" in assistant_spec.SYSTEM_PROMPT
    put(client.db, "models", "pump-model", A, ago(days=5), results=WEIBULL_RESULTS)

    seen = []

    def provider(system, messages, tools):
        seen.append(([t["name"] for t in tools], messages))
        usage = {"input_tokens": 10, "output_tokens": 10}
        last = messages[-1]["content"]
        if isinstance(last, str):  # the question: call the tool
            return {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "workspace_changes", "input": {"days": 30}}]},
                "stop_reason": "tool_use", "usage": usage}
        facts = json.loads(last[0]["content"])  # the tool result: word it from the facts alone
        first = facts["new"][0]
        text = f"{facts['sentence']} The new one is {first['name']} ({first['url']})."
        return {"message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                "stop_reason": "end_turn", "usage": usage}

    monkeypatch.setattr(assistant_service, "enabled", lambda: True)
    monkeypatch.setattr(assistant_service, "step", provider)
    question = {"role": "user", "content": "What changed since last month?"}
    r = client.post("/api/assistant/step", json={"messages": [question]})
    assert r.status_code == 200, r.text
    call = r.json()["message"]
    tool_use = call["content"][0]
    assert tool_use["name"] == "workspace_changes"

    facts = changes(client, **tool_use["input"])  # what the browser's executor fetches
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                           "content": json.dumps(facts)}]}
    r = client.post("/api/assistant/step", json={"messages": [question, call, result]})
    assert r.status_code == 200, r.text
    assert r.json()["message"]["content"][0]["text"] == (
        "In the last 30 days: 1 item was added. The new one is Pump Model (/models/m/pump-model).")
    assert all("workspace_changes" in names for names, _ in seen)


def test_the_sentence_puts_alerts_and_moved_answers_first():
    from backend.services.workspace_changes import _sentence

    counts = {"alerts": 1, "refits_moved": 2, "forecasts_moved": 1, "runs_moved": 1, "rcm_evidence": 1,
              "new": 2, "changed": 1}
    assert _sentence("in the last 30 days", counts) == (
        "In the last 30 days: 1 fleet alert fired, 4 answers moved (2 refits, 1 forecast, 1 simulation), "
        "evidence changed on 1 RCM decision, 2 items were added and 1 changed.")


def test_a_since_date_and_the_labels_are_in_the_workspaces_time_zone():
    from zoneinfo import ZoneInfo

    from backend.services import workspace_changes

    db = mongomock.MongoClient()["changes_tz"]
    now = datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc)
    bne = workspace_changes.resolve_period(db, A, since="2026-09-01", now=now, tz=ZoneInfo("Australia/Brisbane"))
    assert bne["since"] == datetime(2026, 8, 31, 14, tzinfo=timezone.utc) and bne["label"] == "since 1 Sep 2026"
    utc = workspace_changes.resolve_period(db, A, since="2026-09-01", now=now)
    assert utc["since"] == datetime(2026, 9, 1, tzinfo=timezone.utc) and utc["label"] == "since 1 Sep 2026"
    db.users.insert_one({"_id": A, "previous_visit_at": datetime(2026, 10, 13, 22, tzinfo=timezone.utc)})
    visit = workspace_changes.resolve_period(db, A, since="last_visit", now=now, tz=ZoneInfo("Australia/Brisbane"))
    assert visit["label"] == "since your last visit (14 Oct 2026)"
