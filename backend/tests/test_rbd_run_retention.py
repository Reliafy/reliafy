"""How long run history is kept (#282): 7 days on the free plan, 90 on Pro or
a team's diagram, set on each run from its owner's plan when it starts.

* A free run and a Pro run get their periods, from when they finish.
* The period is the plan's when the run started: a plan that lapses while a
  run is queued doesn't shorten it.
* Records from before keep their expiry (a finished one is never touched; an
  in-flight one finishes with the free period, as before).
* Other kinds of job keep the job TTL.
* A team's diagram whose owner is on Pro keeps runs for the Pro period.
* The runs list says how long, in one line.
"""

from datetime import datetime, timedelta, timezone

from backend.tests.test_availability_paid import (  # noqa: F401 - fixtures
    FREE, PRO, USERS, client, _analyze, _save,
)
from backend.tests.test_compute_service import _graph, _job_id, queue  # noqa: F401 - fixtures

FREE_LINE = "Runs are kept for 7 days on the free plan. Pro keeps them for 90 days."


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _kept_after_finish(job) -> float:
    return (_aware(job["expires_at"]) - _aware(job["finished_at"])).total_seconds() / 86400


def _runs(client):
    r = client.get("/api/rbd-runs")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_free_run_is_kept_7_days_and_the_list_says_pro_keeps_90(client):
    client.act_as(FREE)
    r = client.post("/api/rbds/analyze", json={"graph": _graph(), "quick": True})
    assert r.status_code == 200, r.text
    job = client.db.rbd_jobs.find_one({"uid": FREE})
    assert job["status"] == "done" and job["kept_days"] == 7
    assert 6.99 < _kept_after_finish(job) < 7.01
    out = _runs(client)
    assert out["kept_days"] == 7
    assert out["retention"] == {"days": 7, "plan": "free", "free_days": 7, "pro_days": 90, "text": FREE_LINE}


def test_a_pro_run_is_kept_90_days(client):
    client.act_as(PRO)
    graph = _graph()
    _analyze(client, graph, _save(client, graph))
    job = client.db.rbd_jobs.find_one({"uid": PRO})
    assert job["kept_days"] == 90 and 89.99 < _kept_after_finish(job) < 90.01
    out = _runs(client)
    assert out["retention"]["plan"] == "pro" and out["retention"]["text"] == "Runs are kept for 90 days."


def test_the_period_is_the_plan_when_the_run_started(client, queue):
    from backend.services import billing, usage

    client.act_as(PRO)
    job_id = _job_id(_analyze(client, _graph()))
    job = client.db.rbd_jobs.find_one({"_id": job_id})
    # Set when it was created, with an expiry from then.
    left = _aware(job["expires_at"]) - datetime.now(timezone.utc)
    assert job["kept_days"] == 90 and timedelta(days=89.9) < left <= timedelta(days=90)
    # Pro lapses while it waits: the run keeps its 90 days.
    billing.set_plan(client.db, PRO, "free")
    usage.forget_plan(PRO)
    queue.dispatch()
    job = client.db.rbd_jobs.find_one({"_id": job_id})
    assert job["status"] == "done" and 89.99 < _kept_after_finish(job) < 90.01
    assert _runs(client)["retention"]["plan"] == "free"


def test_existing_records_keep_their_expiry(client, queue):
    from backend.services import rbd_jobs

    old_expiry = datetime(2026, 10, 12, tzinfo=timezone.utc)
    # A finished run from before: listing and reading it changes nothing.
    client.db.rbd_jobs.insert_one({
        "_id": "old-done", "uid": PRO, "kind": "availability", "rbd_id": None, "status": "done",
        "created_at": datetime(2026, 10, 5, tzinfo=timezone.utc), "finished_at": datetime(2026, 10, 5, tzinfo=timezone.utc),
        "expires_at": old_expiry, "request": {"graph": _graph(), "options": {}}, "result": {},
    })
    client.act_as(PRO)
    assert [r["run_id"] for r in _runs(client)["runs"]] == ["old-done"]
    assert client.get("/api/rbd-runs/old-done").status_code == 200
    assert _aware(client.db.rbd_jobs.find_one({"_id": "old-done"})["expires_at"]) == old_expiry
    assert "kept_days" not in client.db.rbd_jobs.find_one({"_id": "old-done"})

    # One still in flight from before finishes with the free period, as it would have.
    now = datetime.now(timezone.utc)
    client.db.rbd_jobs.insert_one({
        "_id": "old-queued", "uid": PRO, "kind": "availability", "rbd_id": None, "status": "running",
        "created_at": now, "started_at": now, "finished_at": None, "expires_at": now + timedelta(days=7),
        "request": {"graph": _graph(), "options": {}}, "quick": False, "store": False,
    })
    assert rbd_jobs.finish(client.db, "old-queued", "done", result={"steady_state_availability": 0.99})
    assert 6.99 < _kept_after_finish(client.db.rbd_jobs.find_one({"_id": "old-queued"})) < 7.01


def test_other_jobs_keep_the_job_ttl(client):
    from backend.services import rbd_jobs

    job = rbd_jobs.create(client.db, uid=PRO, kind="sensitivity", request={}, cache_key="k", rbd_id=None,
                          quick=False, store=False)
    assert "kept_days" not in job
    rbd_jobs.finish(client.db, job["_id"], "done", result={})
    assert 6.99 < _kept_after_finish(client.db.rbd_jobs.find_one({"_id": job["_id"]})) < 7.01


def test_a_team_on_pro_keeps_runs_90_days(client):
    from backend.services import billing, rbd_runs, usage

    client.db.teams.insert_one({"_id": "t1", "owner_uid": PRO, "name": "Ops",
                                "members": [{"uid": PRO}, {"uid": FREE}]})
    free_user = USERS[FREE]
    assert rbd_runs.kept_days_for(client.db, free_user) == 7
    assert rbd_runs.kept_days_for(client.db, free_user, "team:t1") == 90
    # The owner's Pro lapses: the team is frozen, and new runs get 7 days.
    billing.set_plan(client.db, PRO, "free")
    usage.forget_plan(PRO)
    assert rbd_runs.kept_days_for(client.db, free_user, "team:t1") == 7


def test_the_line_in_words():
    from backend.services.rbd_runs import retention_text

    assert retention_text({"plan": "free", "days": 7, "free_days": 7, "pro_days": 90}) == FREE_LINE
    assert retention_text({"plan": "pro", "days": 90, "free_days": 7, "pro_days": 90}) == "Runs are kept for 90 days."
    assert retention_text({"plan": "pro", "days": 1, "free_days": 1, "pro_days": 1}) == "Runs are kept for 1 day."
