"""Cancelling a long job: the owner cancels a queued or running simulation;
a cancelled job never shows (or stores) a result, a task not yet started is
skipped by the compute service, and runs in the web process can be cancelled
by their run token."""

from __future__ import annotations

import pytest

from backend.tests.test_compute_service import (  # noqa: F401 - fixtures
    ADMIN, CALLBACK_URL, PRO, _analyze, _graph, _job_id, _poll, _save, client, queue,
)

pytestmark = pytest.mark.usefixtures("mcp_on")

AUTH = {"Authorization": "Bearer compute-token"}


def _cancel(client, job_id):
    return client.post(f"/api/rbd-jobs/{job_id}/cancel")


def _runs(client, rbd_id):
    r = client.get(f"/api/rbd-runs?rbd_id={rbd_id}")
    assert r.status_code == 200, r.text
    return r.json()["runs"]


def test_cancel_a_queued_job_skips_the_calculation(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    job_id = _job_id(_analyze(client, graph, rbd_id))

    r = _cancel(client, job_id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["error"] == "Cancelled."
    view = _poll(client, job_id)
    assert view["status"] == "cancelled" and "result" not in view and view["queue_position"] is None
    # No longer the diagram's in-flight job.
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}").json()["job"] is None

    # The task still reaches the compute service: its "running" report is
    # refused, so it skips the calculation and the task is done (not retried).
    [answer] = queue.dispatch()
    assert answer.status_code == 200, answer.text
    assert [c["status"] for c in queue.callbacks] == ["running"]
    assert _poll(client, job_id)["status"] == "cancelled"

    # Nothing stored on the diagram; the run history says it was cancelled.
    assert "availability_cache" not in (client.db.rbds.find_one({"_id": rbd_id}) or {}) or not \
        client.db.rbds.find_one({"_id": rbd_id}).get("availability_cache")
    [run] = _runs(client, rbd_id)
    assert run["status"] == "cancelled" and run["availability"] is None and run["error"] == "Cancelled."

    # Asking again starts a new job (the cancelled one isn't reused).
    assert _job_id(_analyze(client, graph, rbd_id)) != job_id


def test_cancel_a_running_job_discards_its_result(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    job_id = _job_id(_analyze(client, graph, rbd_id))
    started = client.post("/internal/compute/callback", headers=AUTH,
                          json={"job_id": job_id, "status": "running"})
    assert started.status_code == 200 and _poll(client, job_id)["status"] == "running"

    assert _cancel(client, job_id).json()["status"] == "cancelled"
    # The compute service finishes anyway: its result is acknowledged and dropped.
    done = client.post("/internal/compute/callback", headers=AUTH, json={
        "job_id": job_id, "status": "done", "result": {"steady_state_availability": 0.9, "n_simulations": 20}})
    assert done.status_code == 200 and done.json()["applied"] is False
    view = _poll(client, job_id)
    assert view["status"] == "cancelled" and "result" not in view
    assert client.db.rbd_jobs.find_one({"_id": job_id}).get("result") is None
    assert not (client.db.rbds.find_one({"_id": rbd_id}) or {}).get("availability_cache")

    # Cancelling again (or a finished job) changes nothing.
    assert _cancel(client, job_id).json()["status"] == "cancelled"


def test_only_the_owner_can_cancel(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    job_id = _job_id(_analyze(client, graph, rbd_id))
    client.act_as(ADMIN)
    assert _cancel(client, job_id).status_code == 404
    client.act_as(None)
    assert _cancel(client, job_id).status_code in (401, 403)
    client.act_as(PRO)
    assert _poll(client, job_id)["status"] == "queued"


def test_a_finished_job_is_not_cancelled(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    job_id = _job_id(_analyze(client, graph, rbd_id))
    queue.dispatch()
    assert _poll(client, job_id)["status"] == "done"
    r = _cancel(client, job_id)
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["result"]


def test_cancel_an_in_process_run_by_its_token(client):
    """No queue: the run answers in the request. Cancelling its token (sent
    while it computes) keeps nothing and records the run as cancelled."""
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    assert _cancel(client, "tok-1").json()["status"] == "cancelled"
    r = client.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "run_token": "tok-1"})
    assert r.status_code == 200, r.text
    assert r.json().get("cancelled") is True
    assert not (client.db.rbds.find_one({"_id": rbd_id}) or {}).get("availability_cache")
    [run] = _runs(client, rbd_id)
    assert run["status"] == "cancelled"

    # Another token (or another user's cancel of this one) doesn't touch a run.
    client.act_as(ADMIN)
    _cancel(client, "tok-2")
    client.act_as(PRO)
    r = client.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "run_token": "tok-2"})
    assert r.status_code == 200 and not r.json().get("cancelled")
    assert client.db.rbds.find_one({"_id": rbd_id}).get("availability_cache")


def test_an_overlong_token_is_not_stored(client):
    """Only a token of the app's size is kept (anything else is ignored)."""
    client.act_as(PRO)
    assert _cancel(client, "x" * 65).json()["status"] == "cancelled"
    assert client.db.rbd_job_cancels.count_documents({}) == 0
    assert _cancel(client, "x" * 32).status_code == 200
    assert client.db.rbd_job_cancels.count_documents({}) == 1


def test_compute_app_skips_a_job_cancelled_before_it_started(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import compute_app, config
    from backend.services import compute_core

    monkeypatch.setattr(config, "COMPUTE_CALLBACK_URL", CALLBACK_URL)
    sent = []

    def post(url, payload, timeout):
        sent.append(payload["status"])
        return 409 if payload["status"] == "running" else 200

    monkeypatch.setattr(compute_app, "_post", post)
    monkeypatch.setattr(compute_app, "execute", lambda *a: pytest.fail("ran a cancelled job"))
    request = compute_core.availability_request(_graph(), n_simulations=10)
    r = TestClient(compute_app.app).post("/compute/run", json={
        "job_id": "j1", "kind": "availability", "request": request, "callback_url": CALLBACK_URL})
    assert r.status_code == 200 and sent == ["running"]
