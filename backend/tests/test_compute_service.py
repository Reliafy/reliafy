"""The compute service and its queue (#146), and free quick simulations (#147).

* The compute app (``backend/compute_app.py``) via TestClient: the analysis,
  the Cloud Tasks target, its callback to the web app (and its retries), and
  that it never touches the database.
* Same seed, same result: a simulation run on compute gives the in-process
  result to the last bit — RePyability 0.12's plain simulation, its stopping
  rule, the exact window mean and its basis, costs, crews, a safety function,
  common cause, a current state — through the whole app (task, callback,
  stored job, composed payload).
* The queue client: the Cloud Tasks body (task named after the job, OIDC
  token for the compute URL), dedupe on a double enqueue, failures.
* The web side: jobs (with the exact figures straight away), queue position,
  owner-only polling, the authenticated and idempotent callback, failures,
  and the in-process path when no queue is configured.
* Free quick simulations: the time cap, reproducibility (a quick run is the
  fixed run of its replications), the daily cap (at enqueue time too), the
  quick flag on saved results, entitled users unaffected, MCP Free/Agent
  still refused unless MCP_FREE_QUICK_SIMS.

Nothing leaves the process: Cloud Tasks and Google's token endpoints are
faked; a fake queue hands tasks to the compute app's TestClient, whose
callback is posted to the web app's TestClient.
"""

import base64
import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pytest
from fastapi.testclient import TestClient

from backend.tests.test_availability_paid import (  # noqa: F401 - fixtures
    ADMIN, BUYER, FREE, PRO, USERS, client, _analyze, _save, _with_param,
)
from backend.tests.test_public_rbd_links import _rbd_graph

QUEUE = "projects/reliafy-test/locations/australia-southeast1/queues/reliafy-compute"
COMPUTE_URL = "https://reliafy-compute-test.a.run.app"
CALLBACK_URL = "https://reliafy-test.a.run.app/internal/compute/callback"
WEB_SA = "web@reliafy-test.iam.gserviceaccount.com"
COMPUTE_SA = "reliafy-compute@reliafy-test.iam.gserviceaccount.com"
REPO = Path(__file__).resolve().parents[2]


def _graph():
    return _rbd_graph(repairable=True)


def _rich_graph():
    """A repairable diagram with the diagram-level settings the compute
    request must carry: a safety function with staggered proof tests, a
    common-cause group, a standby bank, condition-based replacement, costs
    (on blocks and the diagram's downtime rate)."""
    from backend.tests.test_rbd_crews_maintenance import _export_graph

    return _export_graph()


def _crew_graph():
    """Limited repair crews (#156) and block costs."""
    from backend.tests.test_rbd_costs import _exp, _io, _node

    nodes = [_node(f"p{i}", model=_exp(0.01), repair=_exp(0.1), costs={"repair": 100, "downtime": 5})
             for i in (1, 2, 3)]
    edges = []
    for n in nodes:
        edges += [{"id": f"i-{n['id']}", "source": "input", "target": n["id"]},
                  {"id": f"o-{n['id']}", "source": n["id"], "target": "output"}]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes], "edges": edges,
            "repair_crews": {"crews": 1}}


# ---- Fixtures ---------------------------------------------------------------------

def _configure(monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "COMPUTE_URL", COMPUTE_URL)
    monkeypatch.setattr(config, "COMPUTE_QUEUE", QUEUE)
    monkeypatch.setattr(config, "COMPUTE_CALLBACK_URL", CALLBACK_URL)
    monkeypatch.setattr(config, "COMPUTE_INVOKER_SA", WEB_SA)
    monkeypatch.setattr(config, "COMPUTE_SA", COMPUTE_SA)


def _fake_verify(token, audience):
    """Stands in for google.oauth2.id_token.verify_oauth2_token."""
    assert audience == CALLBACK_URL
    if token == "compute-token":
        return {"email": COMPUTE_SA, "email_verified": True, "aud": audience}
    if token == "someone-else":
        return {"email": "intruder@example.org", "email_verified": True, "aud": audience}
    raise ValueError("Could not verify token signature.")


@pytest.fixture()
def queue(client, monkeypatch):
    """The queue configured, with Cloud Tasks faked: tasks wait in a list
    until ``dispatch()`` hands them to the compute app, whose callback goes to
    the web app with the compute service's (fake) ID token."""
    from backend import compute_app
    from backend.services import compute_queue

    _configure(monkeypatch)
    tasks: list[dict] = []
    names: set[str] = set()

    def enqueue(job_id, kind, request):
        compute_queue.task_body(job_id, kind, request)  # the real body builds
        if job_id in names:
            return False
        names.add(job_id)
        # What Cloud Tasks carries: JSON, exactly.
        tasks.append(json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request})))
        return True

    monkeypatch.setattr(compute_queue, "enqueue", enqueue)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)

    callbacks: list[dict] = []

    def post(url, payload, timeout):
        assert url == CALLBACK_URL
        callbacks.append(payload)
        return client.post("/internal/compute/callback", json=payload,
                           headers={"Authorization": "Bearer compute-token"}).status_code

    monkeypatch.setattr(compute_app, "_post", post)
    compute = TestClient(compute_app.app)

    def dispatch():
        answers = []
        while tasks:
            task = tasks.pop(0)
            answers.append(compute.post("/compute/run", json={**task, "callback_url": CALLBACK_URL}))
        return answers

    class Q:
        pass

    Q.tasks, Q.callbacks, Q.dispatch, Q.compute = tasks, callbacks, dispatch, compute
    return Q


def _poll(client, job_id):
    r = client.get(f"/api/rbd-jobs/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _job_id(r):
    assert r.status_code == 202, r.text
    return r.json()["job"]["job_id"]


# ---- The compute app ----------------------------------------------------------------

def test_compute_app_health_and_availability():
    from backend import compute_app
    from backend.services import compute_core

    tc = TestClient(compute_app.app)
    health = tc.get("/health").json()
    assert health["ok"] is True and health["repyability_version"].startswith("0.12")
    # /healthz (Cloud Run reserves paths ending in "z") stays, for local use.
    assert tc.get("/healthz").json() == health

    request = compute_core.availability_request(_graph(), n_simulations=20)
    r = tc.post("/compute/availability", json=request)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "repairable" and body["n_simulations"] == 20 and body["quick"] is False
    assert 0.9 < body["steady_state_availability"] < 1.0
    assert body["precision"]["half_width"] > 0 and body["precision"]["mode"] == "fixed"
    # 0.12: the window mean is the exact one where RePyability works it out,
    # its basis said, the simulation's own kept beside it.
    assert body["precision"]["window_availability_basis"] in ("exact", "numerical")
    assert body["precision"]["simulated_window_availability"] is not None

    # A diagram that can't be analysed: 422 with the reason; a bad option: 400.
    broken = copy.deepcopy(request)
    del broken["graph"]["nodes"][2]["data"]["repair"]
    r = tc.post("/compute/availability", json=broken)
    assert r.status_code == 422 and "repair" in r.json()["detail"]
    r = tc.post("/compute/availability", json={**request, "options": {"n_simulations": -3}})
    assert r.status_code == 400
    r = tc.post("/compute/availability", json={**request, "options": {"rm": "-rf"}})
    assert r.status_code == 400 and "Unknown options" in r.json()["detail"]
    # A current state is checked against the diagram (the user's input: 422).
    r = tc.post("/compute/availability", json={**request, "options": {"state": {"nope": {"age": 1}}}})
    assert r.status_code == 422 and "nope" in r.json()["detail"]


def test_compute_app_never_imports_the_database_layer():
    code = (
        "import sys, backend.compute_app\n"
        "bad = [m for m in sys.modules if m in ('backend.db', 'pymongo', 'mongomock', "
        "'backend.services.models', 'backend.services.rbds', 'backend.services.access', 'backend.main')]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                         env={"PATH": "", "PYTHONPATH": str(REPO), "MPLBACKEND": "Agg"}, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""


def test_request_is_self_contained_and_runs_without_a_database(monkeypatch):
    from backend import db
    from backend.services import compute_core

    graph = _rich_graph()
    graph["viewport"] = {"zoom": 2}
    request = compute_core.availability_request(graph, n_simulations=10, seed=7)
    blob = json.dumps(request)
    assert "position" not in blob and "viewport" not in blob
    assert request["options"] == {"n_simulations": 10, "seed": 7}
    # Every diagram-level setting travels (the analysis reads them all).
    for key in ("ccf_groups", "costs", "safety_function", "target_sil"):
        assert request["graph"][key] == graph[key]
    assert compute_core.availability_request(_crew_graph())["graph"]["repair_crews"] == {"crews": 1}
    # A saved model's id stays on its block (never resolved: no database).
    assert "model-ctrl" in json.dumps(compute_core.availability_request(_graph()))

    class Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"the compute path touched the database ({name})")

    monkeypatch.setattr(db, "_db", Exploding())
    monkeypatch.setattr(db, "get_db", lambda: Exploding().anything)
    result = compute_core.run("availability", request)
    assert result["n_simulations"] == 10 and result["seed"] == 7
    assert result["safety"] and result["costs"]

    # Blocks backed by a re-fit of saved data can't travel: computed locally.
    base = _graph()
    ph = copy.deepcopy(base)
    ph["nodes"][3]["data"]["model"] = {"kind": "regression", "modelId": "ph-1", "distribution": "Weibull PH"}
    assert compute_core.needs_saved_models(ph) == ["Pump A"]
    assert compute_core.availability_request(ph) is None
    nonpar = copy.deepcopy(base)
    nonpar["nodes"][4]["data"]["repair"] = {"kind": "nonparametric", "modelId": "km-1"}
    assert compute_core.availability_request(nonpar) is None


def test_job_kinds_are_a_registry():
    from backend.services import compute_core

    assert compute_core.KINDS == ("availability",) and set(compute_core.RUNNERS) == {"availability"}
    with pytest.raises(compute_core.InvalidRequest, match="Unknown kind"):
        compute_core.run("next_failure", {"graph": _graph()})


def test_run_reports_running_then_result_and_retries_a_failed_callback(monkeypatch):
    from backend import compute_app, config
    from backend.services import compute_core

    monkeypatch.setattr(config, "COMPUTE_CALLBACK_URL", None)
    sent, answer = [], {"status": 200}

    def post(url, payload, timeout):
        sent.append((url, payload))
        return answer["status"]

    monkeypatch.setattr(compute_app, "_post", post)
    tc = TestClient(compute_app.app)
    request = compute_core.availability_request(_graph(), n_simulations=10)
    body = {"job_id": "job1", "kind": "availability", "request": request, "callback_url": CALLBACK_URL}

    r = tc.post("/compute/run", json=body)
    assert r.status_code == 200, r.text
    assert [p["status"] for _, p in sent] == ["running", "done"]
    assert all(url == CALLBACK_URL for url, _ in sent)
    final = sent[-1][1]
    assert final["job_id"] == "job1" and final["result"]["n_simulations"] == 10
    assert final["timings"]["compute_s"] >= 0 and final["repyability_version"].startswith("0.12")

    # The web app didn't take the result: 5xx so Cloud Tasks retries.
    answer["status"] = 503
    assert tc.post("/compute/run", json=body).status_code == 502

    # A diagram that can't be analysed is reported (not retried).
    answer["status"] = 200
    sent.clear()
    bad = copy.deepcopy(body)
    del bad["request"]["graph"]["nodes"][3]["data"]["repair"]
    assert tc.post("/compute/run", json=bad).status_code == 200
    assert sent[-1][1]["status"] == "failed" and "repair" in sent[-1][1]["error"]


def test_callback_id_token_is_fetched_for_the_callback_url_and_cached(monkeypatch):
    import google.auth.jwt
    import google.oauth2.id_token

    from backend import compute_app

    compute_app._token_cache.clear()
    fetched = []

    def fetch(request, audience):
        fetched.append(audience)
        return f"token-{len(fetched)}"

    exp = {"exp": datetime.now(timezone.utc).timestamp() + 3600}
    monkeypatch.setattr(google.oauth2.id_token, "fetch_id_token", fetch)
    monkeypatch.setattr(google.auth.jwt, "decode", lambda token, verify=False: exp)
    assert compute_app._id_token(CALLBACK_URL) == "token-1"
    assert compute_app._id_token(CALLBACK_URL) == "token-1"
    assert fetched == [CALLBACK_URL]
    exp["exp"] = datetime.now(timezone.utc).timestamp() + 60  # inside the refresh margin
    compute_app._token_cache.clear()
    compute_app._id_token(CALLBACK_URL)
    assert compute_app._id_token(CALLBACK_URL) == "token-3"
    compute_app._token_cache.clear()


# ---- Same seed, same result ------------------------------------------------------------

def _same(a: dict, b: dict):
    """Two availability payloads equal but for when/where they were made."""
    drop = {"cached", "computed_at", "job", "free_sims"}
    a = {k: v for k, v in a.items() if k not in drop}
    b = {k: v for k, v in b.items() if k not in drop}
    for d in (a, b):
        if isinstance(d.get("exact"), dict):
            d["exact"] = {k: v for k, v in d["exact"].items() if k != "cached"}
    assert a.keys() == b.keys()
    for key in a:
        assert a[key] == b[key], key


@pytest.mark.parametrize("make", [_graph, _rich_graph, _crew_graph], ids=["plain", "rich", "crews"])
def test_compute_gives_the_in_process_result_for_the_same_seed(make):
    """compute_core.run on the JSON a task carries == the in-process analysis
    of the original graph, to the last bit (fixed runs, quick runs, from a
    current state, another seed)."""
    from backend.services import compute_core, rbd_analysis

    graph = make()
    graph["nodes"][-1]["position"] = {"x": 5, "y": 5}
    first = next(n["id"] for n in graph["nodes"] if n["type"] == "component" and not n["data"].get("state"))
    for options in ({"n_simulations": 40},
                    {"n_simulations": 40, "seed": 12345},
                    {"n_simulations": 40, "t_simulation": 3000.0},
                    {"n_simulations": 40, "state": {first: {"age": 50.0}}}):
        request = json.loads(json.dumps(compute_core.availability_request(graph, **options)))
        remote = compute_core.run("availability", request)
        local = compute_core.to_wire(rbd_analysis.analyze_availability(graph, **options))
        assert remote == local, options
        assert remote["n_simulations"] == 40
        # From a current state the availability job carries the time to the
        # next system failure (#240): it runs on compute with the rest.
        assert ("next_failure" in remote) == ("state" in options), options


def test_quick_run_on_compute_is_the_in_process_quick_run(monkeypatch):
    from backend.services import compute_core, rbd_analysis

    def fake_clock():
        ticks = iter(range(10_000))
        monkeypatch.setattr(rbd_analysis, "_clock", lambda: next(ticks))

    graph = _graph()
    fake_clock()
    request = json.loads(json.dumps(compute_core.availability_request(graph, time_budget_s=4.0, max_replications=2000)))
    remote = compute_core.run("availability", request)
    fake_clock()
    local = compute_core.to_wire(rbd_analysis.analyze_availability(graph, time_budget_s=4.0, max_replications=2000))
    assert remote == local and remote["quick"] is True and remote["replications"] == 150


def test_next_failure_from_now_on_compute_is_the_in_process_one(monkeypatch):
    """#240's next failure from the current state is part of the availability
    job: compute gives the in-process histories, causes and mean, for a fixed
    run and for a quick run (whose histories are its replications)."""
    from backend.services import compute_core, rbd_analysis

    graph = _graph()
    first = next(n["id"] for n in graph["nodes"] if n["type"] == "component" and not n["data"].get("state"))
    state = {first: {"age": 50.0}}
    request = json.loads(json.dumps(compute_core.availability_request(graph, n_simulations=60, state=state)))
    remote = compute_core.run("availability", request)
    local = compute_core.to_wire(rbd_analysis.analyze_availability(graph, n_simulations=60, state=state))
    assert remote["next_failure"] == local["next_failure"] and remote == local
    assert remote["next_failure"]["n_simulations"] == 60

    def fake_clock():
        ticks = iter(range(10_000))
        monkeypatch.setattr(rbd_analysis, "_clock", lambda: next(ticks))

    options = {"time_budget_s": 4.0, "max_replications": 2000, "state": state}
    fake_clock()
    request = json.loads(json.dumps(compute_core.availability_request(graph, **options)))
    remote = compute_core.run("availability", request)
    fake_clock()
    local = compute_core.to_wire(rbd_analysis.analyze_availability(graph, **options))
    assert remote == local and remote["quick"] is True
    assert remote["next_failure"]["n_simulations"] == remote["replications"] == 150


@pytest.mark.parametrize("queued", [False, True], ids=["no-queue", "queue"])
def test_next_failure_from_now_with_and_without_the_queue(client, monkeypatch, queued):
    """From a current state the app's answer carries the next failure whether
    COMPUTE_QUEUE is unset (in-process) or set (a job on compute), and the two
    are the same."""
    from backend.services import compute_queue

    client.act_as(PRO)
    graph = _graph()
    first = next(n["id"] for n in graph["nodes"] if n["type"] == "component" and not n["data"].get("state"))
    body = {"graph": graph, "force": True, "current_state": {first: {"age": 50.0}}}
    local = client.post("/api/rbds/analyze", json=body)
    assert local.status_code == 200, local.text
    local = local.json()
    assert local["current_state"] and local["next_failure"]["mean"] > 0
    if not queued:
        assert client.db.rbd_jobs.count_documents({}) == 0
        return

    from backend import compute_app

    _configure(monkeypatch)
    tasks = []
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: tasks.append(
        json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request}))) or True)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)
    monkeypatch.setattr(compute_app, "_post", lambda url, payload, timeout: client.post(
        "/internal/compute/callback", json=payload, headers={"Authorization": "Bearer compute-token"}).status_code)
    job_id = _job_id(client.post("/api/rbds/analyze", json=body))
    assert tasks[-1]["request"]["options"]["state"]
    compute = TestClient(compute_app.app)
    assert compute.post("/compute/run", json={**tasks.pop(), "callback_url": CALLBACK_URL}).status_code == 200
    view = _poll(client, job_id)
    assert view["status"] == "done"
    assert view["result"]["next_failure"] == local["next_failure"]
    _same(view["result"], local)


def test_whole_payload_through_the_queue_matches_in_process(client, monkeypatch):
    """The app's answer from a job (task → compute → callback → stored job →
    composed view) equals its in-process answer: the simulation, the exact
    figures beside it, the simulation status, the common-cause note."""
    from backend.services import compute_queue

    client.act_as(PRO)
    graph = _rich_graph()
    local = _analyze(client, graph)
    assert local.status_code == 200, local.text
    assert local.json()["has_simulation"] is True and local.json()["common_cause"]

    # Now through the queue.
    from backend import compute_app

    _configure(monkeypatch)
    tasks = []
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: tasks.append(
        json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request}))) or True)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)
    monkeypatch.setattr(compute_app, "_post", lambda url, payload, timeout: client.post(
        "/internal/compute/callback", json=payload, headers={"Authorization": "Bearer compute-token"}).status_code)
    r = client.post("/api/rbds/analyze", json={"graph": graph, "force": True})
    job_id = _job_id(r)
    compute = TestClient(compute_app.app)
    assert compute.post("/compute/run", json={**tasks.pop(), "callback_url": CALLBACK_URL}).status_code == 200
    view = _poll(client, job_id)
    assert view["status"] == "done"
    _same(view["result"], local.json())


# ---- The queue client -------------------------------------------------------------------

class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def test_enqueue_builds_a_named_authenticated_task_and_dedupes(monkeypatch):
    from backend.services import compute_queue

    _configure(monkeypatch)
    posted, status = [], {"code": 200}

    class Session:
        def post(self, url, json, timeout):
            posted.append((url, json))
            return _Resp(status["code"], "boom")

    monkeypatch.setattr(compute_queue, "_authorized_session", lambda: Session())
    request = {"graph": {"nodes": []}, "options": {"seed": 1}}
    assert compute_queue.enqueue("abc123", "availability", request) is True
    url, body = posted[0]
    assert url == f"https://cloudtasks.googleapis.com/v2/{QUEUE}/tasks"
    task = body["task"]
    assert task["name"] == f"{QUEUE}/tasks/abc123"
    http = task["httpRequest"]
    assert http["url"] == f"{COMPUTE_URL}/compute/run" and http["httpMethod"] == "POST"
    assert http["oidcToken"] == {"serviceAccountEmail": WEB_SA, "audience": COMPUTE_URL}
    assert task["dispatchDeadline"].endswith("s")
    payload = json.loads(base64.b64decode(http["body"]))
    assert payload == {"job_id": "abc123", "kind": "availability", "request": request,
                       "callback_url": CALLBACK_URL}

    status["code"] = 409  # ALREADY_EXISTS: the same job enqueued twice
    assert compute_queue.enqueue("abc123", "availability", request) is False
    status["code"] = 500
    with pytest.raises(compute_queue.QueueError):
        compute_queue.enqueue("abc124", "availability", request)
    with pytest.raises(compute_queue.QueueError, match="too large"):
        compute_queue.task_body("big", "availability", {"graph": {"x": "y" * 1_000_000}})

    from backend import config

    monkeypatch.setattr(config, "COMPUTE_INVOKER_SA", None)
    with pytest.raises(compute_queue.QueueError):
        compute_queue.enqueue("abc125", "availability", request)


def test_verify_callback_requires_the_compute_service_token(monkeypatch):
    from backend.services import compute_queue

    _configure(monkeypatch)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)
    assert compute_queue.verify_callback("Bearer compute-token")["email"] == COMPUTE_SA
    for header in (None, "", "Basic abc", "Bearer ", "Bearer forged", "Bearer someone-else"):
        with pytest.raises(compute_queue.CallbackRejected):
            compute_queue.verify_callback(header)


# ---- In-process when no queue is configured ------------------------------------------------

def test_no_queue_runs_in_process_exactly_as_before(client, monkeypatch):
    from backend.services import compute_queue

    monkeypatch.setattr(compute_queue, "enqueue", lambda *a: pytest.fail("enqueued without a queue"))
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cached"] is False and body["quick"] is False and body["n_simulations"] == 20
    assert body["has_simulation"] is True and body["simulation_status"] == {"state": "done"}
    assert "job" not in body and client.db.rbd_jobs.count_documents({}) == 0


# ---- Through the queue ------------------------------------------------------------------

def test_queued_job_runs_on_compute_and_stores_the_result(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)

    r = _analyze(client, graph, rbd_id)
    job_id = _job_id(r)
    accepted = r.json()
    assert accepted["job"]["status"] == "queued" and accepted["job"]["queue_position"] == 0
    # The exact figures come straight away; the simulation is on its way.
    assert accepted["has_simulation"] is False and accepted["exact"]["status"] == "ok"
    assert accepted["simulation_status"] == {"state": "queued", "job_id": job_id}
    assert client.sims["n"] == 0  # nothing simulated on the web side

    # Asking again while it is queued shares the job (no second task).
    again = _analyze(client, graph, rbd_id).json()
    assert again["job"]["job_id"] == job_id and len(queue.tasks) == 1
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}").json()["job"]["job_id"] == job_id

    task = queue.tasks[0]
    assert task["job_id"] == job_id and "position" not in json.dumps(task["request"])
    [answer] = queue.dispatch()
    assert answer.status_code == 200, answer.text
    assert [c["status"] for c in queue.callbacks] == ["running", "done"]

    view = _poll(client, job_id)
    assert view["status"] == "done" and view["queue_position"] is None
    assert view["started_at"] and view["finished_at"]
    result = view["result"]
    assert result["cached"] is False and result["can_recompute"] is True and result["computed_at"]
    assert result["n_simulations"] == 20 and result["quick"] is False
    assert result["has_simulation"] is True and result["simulation_status"] == {"state": "done"}
    assert result["exact"]["status"] == "ok"
    assert result["precision"]["window_availability_basis"] in ("exact", "numerical")

    # Saved on the diagram as before: the next ask is the cached result.
    cached = _analyze(client, graph, rbd_id).json()
    assert cached["cached"] is True and cached["steady_state_availability"] == result["steady_state_availability"]
    assert cached["precision"] == result["precision"]
    assert client.get(f"/api/rbds/{rbd_id}/analyze").json()["cached"] is True
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}").json()["job"] is None
    assert client.sims["n"] == 1


def test_a_run_from_now_is_its_own_job_and_never_stored(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    now = {"pumpA": {"down": True, "since": 1.0}}
    body = {"graph": graph, "rbd_id": rbd_id, "current_state": now}
    job_id = _job_id(client.post("/api/rbds/analyze", json=body))
    new_id = _job_id(_analyze(client, graph, rbd_id))
    assert new_id != job_id and len(queue.tasks) == 2
    assert queue.tasks[0]["request"]["options"]["state"] == {"pumpA": {"down": True, "since": 1.0}}
    queue.dispatch()
    view = _poll(client, job_id)["result"]
    assert view["current_state"] == now and view["has_simulation"] is True
    stored = client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]
    assert stored["result"]["current_state"] is None  # the from-new run's


def test_unsaved_graph_reuses_a_finished_identical_job(client, queue):
    client.act_as(PRO)
    what_if = _with_param(_graph(), 1500)
    job_id = _job_id(_analyze(client, what_if))
    queue.dispatch()
    assert _poll(client, job_id)["status"] == "done"
    again = _analyze(client, what_if)
    assert again.status_code == 200 and again.json()["cached"] is False
    assert again.json()["has_simulation"] is True
    assert not queue.tasks
    # force re-runs.
    forced = client.post("/api/rbds/analyze", json={"graph": what_if, "force": True})
    assert _job_id(forced) != job_id


def test_callback_is_authenticated_and_idempotent(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    job_id = _job_id(_analyze(client, graph, rbd_id))
    done = {"job_id": job_id, "status": "done", "result": {"kind": "repairable", "steady_state_availability": 0.5,
                                                           "quick": False}}

    for headers in ({}, {"Authorization": "Bearer forged"}, {"Authorization": "Bearer someone-else"}):
        r = client.post("/internal/compute/callback", json=done, headers=headers)
        assert r.status_code == 401
    assert _poll(client, job_id)["status"] == "queued"

    auth = {"Authorization": "Bearer compute-token"}
    r = client.post("/internal/compute/callback", json=done, headers=auth)
    assert r.status_code == 200 and r.json()["applied"] is True
    stored = client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]
    assert stored["result"]["steady_state_availability"] == 0.5

    # A retried task delivers the result again — and a late "running": no change.
    again = {**done, "result": {**done["result"], "steady_state_availability": 0.25}}
    r = client.post("/internal/compute/callback", json=again, headers=auth)
    assert r.status_code == 200 and r.json()["applied"] is False
    r = client.post("/internal/compute/callback", json={"job_id": job_id, "status": "running"}, headers=auth)
    assert r.json()["applied"] is False
    assert _poll(client, job_id)["result"]["steady_state_availability"] == 0.5
    assert client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]["computed_at"] == stored["computed_at"]

    # An unknown job is acknowledged (nothing to retry); a bad status is a 400.
    r = client.post("/internal/compute/callback", json={"job_id": "nope", "status": "done"}, headers=auth)
    assert r.status_code == 200 and r.json()["applied"] is False
    r = client.post("/internal/compute/callback", json={"job_id": job_id, "status": "exploded"}, headers=auth)
    assert r.status_code == 400


def test_compute_failure_marks_the_job_failed_with_the_reason(client, queue, monkeypatch):
    from backend.services import rbd_analysis

    client.act_as(PRO)
    job_id = _job_id(_analyze(client, _graph()))

    def broken(*args, **kwargs):
        raise rbd_analysis.AnalysisError("Pump B: the repair model can't be simulated.")

    monkeypatch.setattr(rbd_analysis, "analyze_availability", broken)
    queue.dispatch()
    view = _poll(client, job_id)
    assert view["status"] == "failed" and "Pump B" in view["error"] and "result" not in view


def test_queue_position_counts_jobs_ahead_and_drops_abandoned_ones(client, queue):
    from backend import config

    client.act_as(PRO)
    ids = [_job_id(_analyze(client, _with_param(_graph(), 1000 + i))) for i in range(3)]
    assert [_poll(client, j)["queue_position"] for j in ids] == [0, 1, 2]

    auth = {"Authorization": "Bearer compute-token"}
    client.post("/internal/compute/callback", json={"job_id": ids[0], "status": "running"}, headers=auth)
    assert _poll(client, ids[0])["status"] == "running"
    assert [_poll(client, j)["queue_position"] for j in ids] == [None, 1, 2]  # a running job is ahead too

    # The queue gave up on the first (retries spent): reported failed, not ahead.
    old = datetime.now(timezone.utc) - timedelta(seconds=config.RBD_JOB_STALE_S + 60)
    client.db.rbd_jobs.update_one({"_id": ids[0]}, {"$set": {"created_at": old}})
    assert _poll(client, ids[1])["queue_position"] == 0
    stale = _poll(client, ids[0])
    assert stale["status"] == "failed" and "run it again" in stale["error"]


def test_jobs_are_owner_only(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    job_id = _job_id(_analyze(client, graph, rbd_id))
    client.act_as(ADMIN)
    assert client.get(f"/api/rbd-jobs/{job_id}").status_code == 404
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}").json()["job"] is None
    client.act_as(None)
    assert client.get(f"/api/rbd-jobs/{job_id}").status_code in (401, 403)
    client.act_as(PRO)
    assert client.get("/api/rbd-jobs/does-not-exist").status_code == 404


def test_queue_down_answers_503_and_gives_back_the_free_run(client, queue, monkeypatch):
    from backend.services import compute_queue, free_sims

    def down(*args):
        raise compute_queue.QueueError("Couldn't reach the calculation queue.")

    monkeypatch.setattr(compute_queue, "enqueue", down)
    client.act_as(FREE)
    r = client.post("/api/rbds/analyze", json={"graph": _graph(), "quick": True})
    assert r.status_code == 503
    assert r.json() == {"detail": "Couldn't start the calculation — try again in a moment.",
                        "code": "compute_unavailable"}
    assert free_sims.used_today(client.db, FREE) == 0
    assert client.db.rbd_jobs.find_one({})["status"] == "failed"


# ---- Free quick simulations ------------------------------------------------------------------

def _ticking(monkeypatch):
    """One fake "second" per clock reading: the pilot block takes 1 s."""
    from backend.services import rbd_analysis

    ticks = iter(range(10_000))
    monkeypatch.setattr(rbd_analysis, "_clock", lambda: next(ticks))


def test_free_user_runs_a_quick_simulation_in_process(client, monkeypatch):
    _ticking(monkeypatch)
    client.act_as(FREE)
    graph = _graph()
    rbd_id = _save(client, graph)

    # The exact figures, free, with the quick run offered beside them.
    first = _analyze(client, graph, rbd_id)
    assert first.status_code == 200, first.text
    status = first.json()["simulation_status"]
    assert status["state"] == "pro_required" and first.json()["has_simulation"] is False
    offer = status["quick"]
    assert offer["seconds"] == 3.0 and offer["per_day"] == 50 and offer["remaining_today"] == 50

    r = client.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "quick": True})
    assert r.status_code == 200, r.text
    body = r.json()
    # 3 s budget, a 1 s pilot block: two blocks of 50 fit the rest.
    assert body["quick"] is True and body["batches"] == 2 and body["replications"] == 100
    assert body["n_simulations"] == 100 and body["time_budget_s"] == 3.0
    assert body["has_simulation"] is True and body["simulation_status"] == {"state": "done"}
    assert body["exact"]["status"] == "ok"
    assert body["precision"]["half_width"] > 0 and body["precision"]["confidence"] == 0.95
    assert body["precision"]["mode"] == "quick"
    assert body["can_recompute"] is False and body["free_sims"]["remaining_today"] == 49

    # Saved on the diagram, flagged quick — what public links show.
    entry = client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]
    assert entry["result"]["quick"] is True and entry["result"]["replications"] == 100
    again = _analyze(client, graph, rbd_id).json()
    assert again["cached"] is True and again["quick"] is True and again["simulation_status"]["state"] == "saved"
    r = client.post("/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id})
    token = r.json()["token"]
    client.act_as(None)
    public = client.get(f"/api/public/{token}").json()["artifact"]["analysis"]
    assert public["quick"] is True and public["cached"] is True


def test_simulation_only_diagram_paywall_offers_the_quick_run(client):
    from backend.tests.test_availability_paid import PRO_PAYLOAD

    client.act_as(FREE)
    graph = _graph()
    graph["repair_crews"] = {"crews": 1}  # wear-out lives + limited crews: no exact figures
    r = _analyze(client, graph)
    assert r.status_code == 402
    body = r.json()
    assert {k: body[k] for k in PRO_PAYLOAD} == PRO_PAYLOAD and body["quick"]["remaining_today"] == 50
    r = client.post("/api/rbds/analyze", json={"graph": graph, "quick": True})
    assert r.status_code == 200 and r.json()["quick"] is True and r.json()["has_simulation"] is True


def test_quick_runs_are_time_capped_reproducible_and_the_fixed_run_of_their_count(monkeypatch):
    from backend.services import rbd_analysis

    graph = _graph()

    def run(budget, seed=1, cap=None):
        _ticking(monkeypatch)
        return rbd_analysis.analyze_availability(graph, time_budget_s=budget, seed=seed, max_replications=cap)

    three, three_again, five = run(3), run(3), run(5)
    assert (three["batches"], three["replications"]) == (2, 100) and five["replications"] == 200
    assert three["precision"] == three_again["precision"] and three["per_node"] == three_again["per_node"]
    assert three["curve"] == three_again["curve"]
    # RePyability 0.12: simulation r draws the same whatever the run's size, so
    # a quick run of n replications is the fixed run of n.
    fixed = rbd_analysis.analyze_availability(graph, n_simulations=100)
    for key in ("precision", "per_node", "curve", "simulated", "criticality"):
        expected = dict(fixed[key], mode="quick") if key == "precision" else fixed[key]
        assert three[key] == expected, key
    assert run(3, seed=99)["precision"] != three["precision"]
    assert five["precision"]["half_width"] != three["precision"]["half_width"]
    capped = run(100, cap=120)
    assert capped["replications"] == 120 and capped["batches"] == 3
    assert run(1)["replications"] == rbd_analysis._QUICK_BLOCK  # the pilot alone

    # A real (tiny) budget: the pilot block alone.
    monkeypatch.setattr(rbd_analysis, "_clock", __import__("time").perf_counter)
    tiny = rbd_analysis.analyze_availability(graph, time_budget_s=1e-6)
    assert tiny["batches"] == 1 and tiny["replications"] == rbd_analysis._QUICK_BLOCK


def test_free_daily_cap(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "FREE_SIMS_PER_DAY", 2)
    monkeypatch.setattr(config, "FREE_SIM_SECONDS", 0.05)
    client.act_as(FREE)
    graph = _graph()
    for left in (1, 0):
        r = client.post("/api/rbds/analyze", json={"graph": graph, "quick": True})
        assert r.status_code == 200 and r.json()["free_sims"]["remaining_today"] == left
    r = client.post("/api/rbds/analyze", json={"graph": graph, "quick": True})
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "free_sim_cap" and body["upgrade"] is True
    assert "00:00 UTC" in body["detail"] and "Pro" in body["detail"]
    assert body["quick"]["remaining_today"] == 0
    assert client.sims["n"] == 2
    # Without asking for a run: the exact figures, the offer at zero.
    plain = _analyze(client, graph).json()
    assert plain["simulation_status"]["quick"]["remaining_today"] == 0

    # A diagram that can't be analysed doesn't use up a run.
    monkeypatch.setattr(config, "FREE_SIMS_PER_DAY", 3)
    broken = copy.deepcopy(graph)
    del broken["nodes"][2]["data"]["repair"]
    assert client.post("/api/rbds/analyze", json={"graph": broken, "quick": True}).status_code == 422
    assert client.post("/api/rbds/analyze", json={"graph": graph, "quick": True}).status_code == 200


def test_free_cap_is_taken_at_enqueue_and_shared_jobs_count_once(client, queue, monkeypatch):
    from backend import config
    from backend.services import free_sims

    monkeypatch.setattr(config, "FREE_SIMS_PER_DAY", 2)
    client.act_as(FREE)
    graph = _graph()
    first = client.post("/api/rbds/analyze", json={"graph": graph, "quick": True})
    job_id = _job_id(first)
    assert first.json()["job"]["quick"] is True and first.json()["free_sims"]["remaining_today"] == 1
    assert first.json()["exact"]["status"] == "ok"
    # Same request while it's queued: the same job, not another run.
    assert _job_id(client.post("/api/rbds/analyze", json={"graph": graph, "quick": True})) == job_id
    assert free_sims.used_today(client.db, FREE) == 1
    assert client.post("/api/rbds/analyze", json={"graph": _with_param(graph, 1700), "quick": True}).status_code == 202
    capped = client.post("/api/rbds/analyze", json={"graph": _with_param(graph, 1800), "quick": True})
    assert capped.status_code == 429 and len(queue.tasks) == 2

    queue.dispatch()
    view = _poll(client, job_id)
    assert view["status"] == "done" and view["result"]["quick"] is True
    assert view["result"]["can_recompute"] is False and view["result"]["can_simulate"] is False


def test_quick_result_never_replaces_a_full_one(client):
    from backend.services import rbds as rbds_service

    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    key = rbds_service.availability_cache_key(graph)
    full = {"kind": "repairable", "quick": False, "steady_state_availability": 0.9}
    assert rbds_service.save_availability_result(client.db, rbd_id, key, full, PRO)
    quick = {"kind": "repairable", "quick": True, "steady_state_availability": 0.8}
    assert rbds_service.save_availability_result(client.db, rbd_id, key, quick, FREE) is None
    assert client.db.rbds.find_one({"_id": rbd_id})["availability_cache"]["result"]["quick"] is False


def test_what_if_run_never_replaces_a_saved_result_keyed_on_a_model(client):
    """#92 + #149: for a diagram whose block references a saved model by id,
    the saved key includes that model's fit. The store guard rebuilds it in
    the run's scope, so an unsaved what-if run (in-process or a queued job)
    can't pass for the diagram as saved and overwrite its current result."""
    from backend.services import rbd_jobs
    from backend.services import rbds as rbds_service
    from backend.tests.test_availability_paid import _graph_with_ph_block

    db = client.db
    graph, _ = _graph_with_ph_block(db, PRO)
    client.act_as(PRO)
    rbd_id = _save(client, graph)
    owners = [PRO]
    saved_key = rbds_service.availability_cache_key(
        graph, models=rbds_service.model_fingerprints(db, graph, owners))
    saved = {"kind": "repairable", "quick": False, "steady_state_availability": 0.95}
    assert rbds_service.save_availability_result(db, rbd_id, saved_key, saved, PRO, owners)

    what_if = _with_param(graph, 1700)
    key = rbds_service.availability_cache_key(
        what_if, models=rbds_service.model_fingerprints(db, what_if, owners))
    doc = db.rbds.find_one({"_id": rbd_id})
    # Without the scope the saved key misses the fingerprints, the current
    # result looks stale, and the what-if would have replaced it.
    assert rbds_service.should_store_availability(doc, key)
    assert not rbds_service.should_store_availability(doc, key, db, owners)

    other = {"kind": "repairable", "quick": False, "steady_state_availability": 0.5}
    assert rbds_service.save_availability_result(db, rbd_id, key, other, PRO, owners) is None
    # A queued job carries the scope it was keyed in, for the same guard.
    job = rbd_jobs.create(db, uid=PRO, kind=rbd_jobs.KIND_AVAILABILITY, request={}, cache_key=key,
                          rbd_id=rbd_id, quick=False, store=True, owners=owners)
    assert job["owners"] == owners
    assert rbd_jobs._store_result(db, job, other) is None
    entry = db.rbds.find_one({"_id": rbd_id})["availability_cache"]
    assert entry["key"] == saved_key and entry["result"]["steady_state_availability"] == 0.95

    # A run for the diagram as saved still replaces it.
    rerun = {**saved, "steady_state_availability": 0.96}
    assert rbds_service.save_availability_result(db, rbd_id, saved_key, rerun, PRO, owners)


@pytest.mark.parametrize("who", [PRO, BUYER, ADMIN])
def test_entitled_users_keep_full_runs(client, who):
    client.act_as(who)
    graph = _graph()
    # quick=True from an entitled user is ignored: the full run, no cap used.
    r = client.post("/api/rbds/analyze", json={"graph": graph, "quick": True})
    assert r.status_code == 200
    body = r.json()
    assert body["quick"] is False and body["n_simulations"] == 20 and body["can_recompute"] is True
    assert "free_sims" not in body and "quick" not in body["simulation_status"]
    assert client.db.free_sim_usage.count_documents({}) == 0


# ---- MCP -------------------------------------------------------------------------------------

from backend.tests.test_mcp import _err, _ok  # noqa: E402
from backend.tests.test_mcp_plans import AGENT, _call, _repairable, env  # noqa: E402,F401
from backend.tests.test_mcp_plans import FREE as MCP_FREE  # noqa: E402
from backend.tests.test_mcp_plans import PRO as MCP_PRO  # noqa: E402


@pytest.mark.parametrize("uid", [MCP_FREE, AGENT])
def test_mcp_free_and_agent_still_get_no_simulations(env, uid):
    rid = _repairable(env, uid, "Pumps")
    out = _ok(_call(env.oauth[uid], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is True and out["has_simulation"] is False  # the exact figures
    assert out["simulation"]["available"] is False and out["simulation"]["code"] == "pro_required"
    assert env.simulations["n"] == 0 and env.db.free_sim_usage.count_documents({}) == 0


def test_mcp_free_quick_sims_flag_switches_them_on(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_FREE_QUICK_SIMS", True)
    monkeypatch.setattr(config, "FREE_SIM_SECONDS", 0.05)
    rid = _repairable(env, MCP_FREE, "Pumps")
    out = _ok(_call(env.oauth[MCP_FREE], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] is True and out["quick"] is True and out["precision"]["half_width"] > 0
    assert out["simulation"]["available"] is True


def _mcp_queue(env, monkeypatch):
    """Queue configured for the MCP env; tasks wait until dispatched."""
    from backend import compute_app
    from backend.services import compute_queue, rbd_jobs

    _configure(monkeypatch)
    tasks = []
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: tasks.append(
        json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request}))) or True)

    def post(url, payload, timeout):  # the callback, applied straight to the job store
        rbd_jobs.apply_callback(env.db, payload)
        return 200

    monkeypatch.setattr(compute_app, "_post", post)
    compute = TestClient(compute_app.app)

    def dispatch():
        while tasks:
            assert compute.post("/compute/run", json={**tasks.pop(0), "callback_url": CALLBACK_URL}).status_code == 200

    return tasks, dispatch


def test_mcp_analyze_waits_then_hands_back_a_job_and_get_job_finishes_it(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_JOB_WAIT_S", 0.2)
    tasks, dispatch = _mcp_queue(env, monkeypatch)
    rid = _repairable(env, MCP_PRO, "Pumps")
    out = _ok(_call(env.oauth[MCP_PRO], "analyze_rbd", {"rbd_id": rid}))
    # The exact figures now; the simulation as a job to fetch.
    assert out["available"] is True and out["exact"]["status"] == "ok"
    sim = out["simulation"]
    assert sim["available"] is False and sim["status"] == "queued" and sim["queue_position"] == 0
    assert "get_job" in sim["note"] and len(tasks) == 1
    job_id = sim["job_id"]

    pending = _ok(_call(env.oauth[MCP_PRO], "get_job", {"job_id": job_id}))
    assert pending["status"] == "queued" and pending["rbd_id"] == rid
    # Someone else's job doesn't exist for them.
    assert "Job not found" in _err(_call(env.oauth[AGENT], "get_job", {"job_id": job_id}))

    dispatch()
    done = _ok(_call(env.oauth[MCP_PRO], "get_job", {"job_id": job_id}))
    assert done["status"] == "done" and done["available"] is True and done["simulation"]["available"] is True
    assert 0.9 < done["steady_state_availability"] < 1.0 and done["n_simulations"] == 20
    assert done["exact"]["status"] == "ok"

    # Now saved on the diagram: analyze_rbd answers straight away.
    again = _ok(_call(env.oauth[MCP_PRO], "analyze_rbd", {"rbd_id": rid}))
    assert again["available"] is True and again["cached"] is True


def test_mcp_analyze_returns_the_result_when_the_job_finishes_in_time(env, monkeypatch):
    import threading

    from backend import config

    monkeypatch.setattr(config, "MCP_JOB_WAIT_S", 20.0)
    tasks, dispatch = _mcp_queue(env, monkeypatch)
    rid = _repairable(env, MCP_PRO, "Pumps")
    stop = threading.Event()

    def worker():  # the compute service picking the task up while MCP waits
        while not stop.is_set():
            if tasks:
                dispatch()
            stop.wait(0.05)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        out = _ok(_call(env.oauth[MCP_PRO], "analyze_rbd", {"rbd_id": rid}))
    finally:
        stop.set()
        t.join(5)
    assert out["available"] is True and out["cached"] is False and out["n_simulations"] == 20
    assert out["simulation"]["available"] is True
