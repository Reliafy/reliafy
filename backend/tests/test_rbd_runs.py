"""Simulation run history (#112) and the runtime quote in the app (#286).

* Every availability simulation is a run: in-process ones are recorded done
  at once, queued ones are the compute service's job records. Each new one
  keeps who ran it and from where, the machine, the quote made before it
  ran, its runtime and the engine versions, and logs its time against the
  quote's model.
* The runs list (filter by diagram), a run in full (results with their
  bands, inputs, engines, precision), CSV/JSON export, re-run and compare.
* Old records (from before these fields) read gracefully.
* Owner-only, as jobs are.
* The quote before a run, in the queued job's status, and over MCP; the
  operators' calibration endpoints.
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.test_availability_paid import (  # noqa: F401 - fixtures
    ADMIN, FREE, PRO, client, _analyze, _save,
)
from backend.tests.test_compute_service import _graph, _job_id, _poll, queue  # noqa: F401 - fixtures


def _runs(client, **params):
    r = client.get("/api/rbd-runs", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_an_in_process_run_is_in_the_history_with_what_it_ran_on(client):
    import surpyval

    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph, "Cooling loop")
    r = _analyze(client, graph, rbd_id)
    assert r.status_code == 200 and r.json()["has_simulation"] is True

    out = _runs(client)
    assert out["kept_days"] == 7 and out["more"] is False
    [row] = out["runs"]
    assert row["rbd_id"] == rbd_id and row["rbd_name"] == "Cooling loop" and row["status"] == "done"
    assert row["by"] == {"you": True, "name": None} and row["via"]["label"] == "App"
    assert row["method"] == {"key": "tolerance", "label": "Full", "from_now": False}
    assert row["where"] == "In the app" and row["runtime_s"] > 0 and row["replications"] == 20
    a = row["availability"]
    assert a["lower"] <= a["value"] <= a["upper"] and a["confidence"] == 0.95
    assert row["quote"]["text"] and row["quote"]["median_s"] > 0

    detail = client.get(f"/api/rbd-runs/{row['run_id']}").json()
    result = detail["result"]
    curve = result["curve"]
    assert len(curve["t"]) == len(curve["lower"]) == len(curve["upper"]) > 0
    assert result["has_simulation"] is True and result["exact"]["status"] == "ok"
    assert detail["precision"]["half_width"] > 0 and "reached" in detail["precision"]
    assert detail["engines"] == {"repyability": result["repyability_version"], "surpyval": surpyval.__version__}
    inputs = detail["inputs"]
    assert inputs["blocks"] == 3 and inputs["unit"] == "hours" and inputs["window"] > 0
    assert inputs["window_chosen"] is False and inputs["diagram_changed_since"] is False
    # Edited since: the run still shows what it ran on.
    edited = dict(graph, nodes=[*graph["nodes"]])
    edited["nodes"][2] = {**edited["nodes"][2], "data": {**edited["nodes"][2]["data"], "label": "PLC"}}
    client.db.rbds.update_one({"_id": rbd_id}, {"$set": {"graph": edited}})
    assert client.get(f"/api/rbd-runs/{row['run_id']}").json()["inputs"]["diagram_changed_since"] is True
    assert inputs["seed"] is not None and inputs["replications"] == 20
    # Logged against the quote's model, for the machine factor.
    [log] = client.db.rbd_runtime_log.find({})
    assert log["machine"] == "web" and log["replications"] == 20 and log["actual_s"] == row["runtime_s"]

    # Kept for the run TTL from when it finished.
    job = client.db.rbd_jobs.find_one({"_id": row["run_id"]})
    finished = job["finished_at"].replace(tzinfo=timezone.utc)
    expires = job["expires_at"].replace(tzinfo=timezone.utc)
    assert timedelta(days=6.9) < expires - finished < timedelta(days=7.1)


def test_run_ttl_is_configurable(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "RBD_RUN_TTL_DAYS", 90)
    client.act_as(PRO)
    graph = _graph()
    _analyze(client, graph, _save(client, graph))
    job = client.db.rbd_jobs.find_one({})
    left = job["expires_at"].replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(days=89) < left <= timedelta(days=90)
    assert _runs(client)["kept_days"] == 90


def test_a_queued_run_carries_its_quote_runtime_and_engines(client, queue):
    import surpyval

    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    r = _analyze(client, graph, rbd_id)
    job_id = _job_id(r)
    accepted = r.json()["job"]
    job = client.db.rbd_jobs.find_one({"_id": job_id})
    assert job["machine"] == "compute" and job["quote"]["text"] and job["quote"]["mode"] == "tolerance"
    assert job["run_by"] == {"uid": PRO, "name": "Pro"} and job["trigger"] == {"surface": "app"}
    # The job's status says how long it should take.
    view = _poll(client, job_id)
    assert view["quote"]["text"] == job["quote"]["text"] and view["wait_s"] == 0.0
    assert accepted["queue_position"] == 0

    row = _runs(client, rbd_id=rbd_id)["runs"][0]
    assert row["status"] == "queued" and row["availability"] is None and row["runtime_s"] is None

    queue.dispatch()
    row = _runs(client, rbd_id=rbd_id)["runs"][0]
    assert row["status"] == "done" and row["where"] == "Calculation service" and row["runtime_s"] >= 0
    job = client.db.rbd_jobs.find_one({"_id": job_id})
    assert job["runtime_s"] == job["timings"]["compute_s"]
    assert job["engines"]["surpyval"] == surpyval.__version__ and job["engines"]["repyability"]
    assert client.db.rbd_runtime_log.count_documents({"machine": "compute"}) == 1


def test_jobs_ahead_give_a_wait_estimate(client, queue, monkeypatch):
    from backend import config
    from backend.services import runtime_quote as rq

    monkeypatch.setattr(config, "COMPUTE_PARALLEL_JOBS", 1)
    client.act_as(PRO)
    first = _job_id(_analyze(client, _graph()))
    other = _graph()
    other["nodes"][2]["data"]["label"] = "PLC"
    second = _job_id(_analyze(client, other))
    view = _poll(client, second)
    ahead = client.db.rbd_jobs.find_one({"_id": first})["quote"]["median_s"]
    assert view["queue_position"] == 1 and view["wait_s"] == pytest.approx(ahead)
    assert view["wait_text"] == rq.wait_text(ahead) and view["wait_text"] in (
        "under a second", f"about {rq.seconds_words(ahead)}")


def test_old_records_read_gracefully(client):
    """A job record from before #112: no run_by, trigger, machine, quote,
    runtime_s or engines."""
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    _analyze(client, graph, rbd_id)
    new = client.db.rbd_jobs.find_one({})
    old = {k: v for k, v in new.items()
           if k not in ("run_by", "trigger", "machine", "quote", "runtime_s", "engines", "in_process")}
    old["_id"] = "old-job"
    old["timings"] = {"compute_s": 1.25}
    client.db.rbd_jobs.insert_one(old)
    row = next(r for r in _runs(client)["runs"] if r["run_id"] == "old-job")
    assert row["via"] == {"surface": None, "client": None, "label": None}
    assert row["quote"] is None and row["runtime_s"] == 1.25 and row["where"] == "Calculation service"
    assert row["by"]["you"] is True
    detail = client.get("/api/rbd-runs/old-job").json()
    assert detail["engines"]["repyability"] == new["result"]["repyability_version"]
    assert detail["engines"]["surpyval"] is None and detail["quote_full"] is None
    assert detail["result"]["has_simulation"] is True


def test_runs_are_owner_only_and_filter_by_diagram(client):
    client.act_as(PRO)
    graph = _graph()
    a = _save(client, graph, "A")
    b = _save(client, graph, "B")
    _analyze(client, graph, a)
    _analyze(client, graph, b, force=True)
    assert len(_runs(client)["runs"]) == 2
    [only] = _runs(client, rbd_id=a)["runs"]
    assert only["rbd_id"] == a
    names = client.get("/api/rbd-runs/diagrams").json()["diagrams"]
    assert {d["name"] for d in names} == {"A", "B"}

    client.act_as(ADMIN)
    assert _runs(client)["runs"] == [] and _runs(client, rbd_id=a)["runs"] == []
    assert client.get(f"/api/rbd-runs/{only['run_id']}").status_code == 404
    assert client.get(f"/api/rbd-runs/{only['run_id']}/export").status_code == 404
    assert client.post(f"/api/rbd-runs/{only['run_id']}/rerun").status_code == 404


def test_export_csv_and_json(client):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph, "Cooling loop")
    _analyze(client, graph, rbd_id)
    run_id = _runs(client)["runs"][0]["run_id"]
    detail = client.get(f"/api/rbd-runs/{run_id}").json()

    r = client.get(f"/api/rbd-runs/{run_id}/export", params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="cooling-loop-run-' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    head = rows[0]
    assert head["quantity"] == "window_availability"
    assert float(head["value"]) == detail["precision"]["window_availability"]
    curve = [x for x in rows if x["quantity"] == "availability_at_t"]
    assert len(curve) == len(detail["result"]["curve"]["t"])
    assert float(curve[-1]["lower"]) <= float(curve[-1]["value"]) <= float(curve[-1]["upper"])
    assert {x["block"] for x in rows if x["quantity"] == "downtime_share"} <= {"Controller", "Pump A", "Pump B"}

    j = client.get(f"/api/rbd-runs/{run_id}/export", params={"format": "json"})
    body = json.loads(j.text)
    assert body["run_id"] == run_id and body["inputs"]["graph"]["nodes"] and body["result"]["curve"]
    assert body["inputs"]["options"] is not None
    assert client.get(f"/api/rbd-runs/{run_id}/export", params={"format": "xml"}).status_code == 422


def test_rerun_runs_the_same_inputs_again(client):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    _analyze(client, graph, rbd_id)
    first = _runs(client)["runs"][0]
    r = client.post(f"/api/rbd-runs/{first['run_id']}/rerun")
    assert r.status_code == 200, r.text
    new_id = r.json()["run_id"]
    assert new_id != first["run_id"] and r.json()["status"] == "done"
    runs = _runs(client, rbd_id=rbd_id)["runs"]
    assert [x["run_id"] for x in runs] == [new_id, first["run_id"]]
    # Same seed, same inputs: the same answer.
    assert runs[0]["availability"] == runs[1]["availability"]
    old, new = (client.db.rbd_jobs.find_one({"_id": i}) for i in (first["run_id"], new_id))
    assert old["request"]["graph"] == new["request"]["graph"]


def test_rerun_through_the_queue_and_without_pro(client, queue):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    first = _job_id(_analyze(client, graph, rbd_id))
    queue.dispatch()
    r = client.post(f"/api/rbd-runs/{first}/rerun")
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["run_id"] != first


def test_compare_overlays_finished_runs(client):
    client.act_as(PRO)
    graph = _graph()
    rbd_id = _save(client, graph)
    _analyze(client, graph, rbd_id)
    longer = client.post("/api/rbds/analyze", json={"graph": graph, "rbd_id": rbd_id, "t_max": 5000.0,
                                                    "simulate": True})
    assert longer.status_code == 200
    ids = [r["run_id"] for r in _runs(client)["runs"]]
    out = client.get("/api/rbd-runs/compare", params={"ids": ",".join([*ids, "nope"])}).json()
    assert [r["run_id"] for r in out["runs"]] == ids and out["missing"] == ["nope"]
    for r in out["runs"]:
        assert len(r["curve"]["t"]) == len(r["curve"]["lower"]) and r["steady_state_availability"]
    assert out["runs"][0]["window"] != out["runs"][1]["window"]
    assert client.get("/api/rbd-runs/compare", params={"ids": ids[0]}).status_code == 422


def test_quote_endpoint(client):
    client.act_as(PRO)
    graph = _graph()
    q = client.post("/api/rbds/quote", json={"graph": graph}).json()
    assert q["available"] is True and q["machine"] == "web" and q["mode"] == "tolerance"
    assert q["text"].startswith(("about", "under")) and q["median_s"] <= q["p90_s"]
    quick = client.post("/api/rbds/quote", json={"graph": graph, "quick": True}).json()
    assert quick["mode"] == "quick" and quick["cap_s"] == 3.0
    chosen = client.post("/api/rbds/quote", json={"graph": graph, "t_max": 500.0}).json()
    assert chosen["window"] == 500.0
    now = client.post("/api/rbds/quote", json={"graph": graph, "current_state": {"pumpA": {"down": True}}})
    assert now.status_code == 200 and now.json()["available"] is True
    flat = dict(graph, repairable=False)
    assert client.post("/api/rbds/quote", json={"graph": flat}).json()["available"] is False


def test_quote_runs_on_the_compute_machine_when_queued(client, queue):
    client.act_as(PRO)
    assert client.post("/api/rbds/quote", json={"graph": _graph()}).json()["machine"] == "compute"


def test_admin_calibration_endpoints(client):
    client.act_as(PRO)
    assert client.get("/api/admin/runtime-quote").status_code == 403
    assert client.post("/api/admin/runtime-quote/refit", json={"machine": "web"}).status_code == 403
    graph = _graph()
    _analyze(client, graph, _save(client, graph))
    client.act_as(ADMIN)
    out = client.get("/api/admin/runtime-quote").json()
    web = next(m for m in out["machines"] if m["machine"] == "web")
    assert web["runs"] == 1 and web["factor"] == 1.0 and out["min_runs"] == 10
    assert out["model"]["coefficients"]["log_replications"] == 0.58
    refit = client.post("/api/admin/runtime-quote/refit", json={"machine": "web", "apply": True}).json()
    assert refit["refitted"] is False and refit["observed"] == 1


# ---- MCP -------------------------------------------------------------------------------------

from backend.tests.test_mcp import _err, _ok  # noqa: E402
from backend.tests.test_mcp_plans import AGENT, _call, _repairable, env  # noqa: E402,F401
from backend.tests.test_mcp_plans import PRO as MCP_PRO  # noqa: E402


def test_mcp_quote_list_and_get_runs(env):
    rid = _repairable(env, MCP_PRO, "Pumps")
    token = env.oauth[MCP_PRO]
    quote = _ok(_call(token, "quote_rbd_simulation", {"rbd_id": rid}))
    assert quote["available"] is True and quote["estimate"] and quote["median_s"] <= quote["p90_s"]
    assert "jobs_in_queue" not in quote  # no queue configured: runs in-process
    assert env.simulations["n"] == 0  # a quote runs nothing

    _ok(_call(token, "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    runs = _ok(_call(token, "list_rbd_runs", {"rbd_id": rid}))
    [row] = runs["runs"]
    assert row["ran_by"] == "you" and row["via"] == "Claude (MCP)" and row["status"] == "done"
    assert row["method"] == "Full" and row["availability"]["value"] > 0.9 and row["quoted"]

    run = _ok(_call(token, "get_rbd_run", {"run_id": row["run_id"], "include_curve": True}))
    assert run["result"]["n_simulations"] == 20 and run["result"]["precision"]
    assert run["engines"]["repyability"] and run["engines"]["surpyval"]
    assert run["inputs"]["blocks"] > 0 and len(run["curve"]["t"]) == len(run["curve"]["upper"])
    assert run["url"].endswith(f"/rbds/runs/{row['run_id']}")
    # Someone else's run doesn't exist for them.
    assert "Run not found" in _err(_call(env.oauth[AGENT], "get_rbd_run", {"run_id": row["run_id"]}))
    assert _ok(_call(env.oauth[AGENT], "list_rbd_runs", {}))["runs"] == []


def test_mcp_pending_job_carries_the_estimate(env, monkeypatch):
    from backend import config
    from backend.tests.test_compute_service import _mcp_queue

    monkeypatch.setattr(config, "MCP_JOB_WAIT_S", 0.1)
    tasks, dispatch = _mcp_queue(env, monkeypatch)
    rid = _repairable(env, MCP_PRO, "Pumps")
    token = env.oauth[MCP_PRO]
    quote = _ok(_call(token, "quote_rbd_simulation", {"rbd_id": rid}))
    assert quote["jobs_in_queue"] == 0
    out = _ok(_call(token, "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    sim = out["simulation"]
    assert sim["status"] == "queued" and sim["estimate"] == quote["estimate"]
    pending = _ok(_call(token, "get_job", {"job_id": sim["job_id"]}))
    assert pending["estimate"] == quote["estimate"]
    dispatch()
    run = _ok(_call(token, "get_rbd_run", {"run_id": sim["job_id"]}))
    assert run["status"] == "done" and run["via"] == "Claude (MCP)" and run["runtime_s"] >= 0
