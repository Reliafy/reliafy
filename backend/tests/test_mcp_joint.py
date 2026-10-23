"""Condition monitoring over MCP: life_data_analysis fit_joint / predict_joint,
models fit_joint, list / get of joint models, the fit's job, and a joint
block in an RBD built with the rbd tool. The fits are the app's
(backend.joint, checked in test_joint_models). The helpers and ``env``
fixture come from test_mcp."""

import json

import pytest

from backend.tests.test_joint_models import fleet
from backend.tests.test_mcp import A, B, _call, _err, _ok, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")

COLUMNS = {"unit_id_column": "unit", "age_column": "age", "censor_column": "running",
           "reading_age_column": "age", "reading_value_column": "value"}


def _datasets(token, n=60):
    L, R = fleet(n=n)
    life = _ok(_call(token, "datasets", {"action": "upload", "name": "Pump lives", "csv": L.to_csv(index=False)}))
    reads = _ok(_call(token, "datasets", {"action": "upload", "name": "Pump vibration",
                                          "csv": R.to_csv(index=False)}))
    return {"lifetimes_dataset_id": life["id"], "readings_dataset_id": reads["id"], **COLUMNS,
            "hazard_covariates": ["load"], "unit": "Days", "marker": "vibration"}


def test_fit_joint_reports_and_models_fit_joint_saves(env):
    a = env.token[A]
    args = _datasets(a)
    report = _ok(_call(a, "life_data_analysis", {"action": "fit_joint", **args}))
    assert "model_id" not in report and report["fit_ok"] is True and report["unit"] == "Days"
    assert {h["name"] for h in report["hazard_ratios"]} == {"load", "marker_effect"}
    assert all(h["lower"] < h["hr"] < h["upper"] for h in report["hazard_ratios"])
    assert report["risk_horizons"] == ["30 days", "90 days", "365 days"]
    assert env.db.models.count_documents({"kind": "joint"}) == 0  # saves nothing

    saved = _ok(_call(a, "models", {"action": "fit_joint", "name": "Pumps", **args}))
    mid = saved["model_id"]
    assert saved["url"].endswith(f"/models/joint/{mid}")
    assert [p["value"] for p in saved["parameters"]] == pytest.approx([p["value"] for p in report["parameters"]])

    listed = _ok(_call(a, "list", {"kind": "models", "model_type": "joint"}))
    assert [m["id"] for m in listed["joint_models"]] == [mid] and "life_models" not in listed
    assert mid not in [m["id"] for m in _ok(_call(a, "list", {"kind": "models", "model_type": "life"}))["life_models"]]
    got = _ok(_call(a, "get", {"kind": "model", "id": mid}))
    assert got["model_type"] == "joint" and got["riskiest_running_units"]

    uid = got["running_units"][0]
    one = _ok(_call(a, "life_data_analysis", {"action": "predict_joint", "model_id": mid, "unit_id": uid}))
    assert one["unit_id"] == uid and set(one["survival"]) == {"30 days", "90 days", "365 days"}
    assert one["median_remaining_life"] == "not reached" or one["median_remaining_life"] > 0
    entered = _ok(_call(a, "life_data_analysis", {"action": "predict_joint", "model_id": mid, "age_now": 50,
                                                  "readings": [[0, 2.0], [40, 3.1]],
                                                  "unit_covariates": {"load": 1}}))
    assert entered["age_now"] == 50 and entered["n_readings"] == 2
    assert "not both" in _err(_call(a, "life_data_analysis", {"action": "predict_joint", "model_id": mid,
                                                             "unit_id": uid, "age_now": 3}))
    # Another user can't read it.
    assert "joint" in _err(_call(env.token[B], "life_data_analysis", {"action": "predict_joint", "model_id": mid,
                                                                      "unit_id": uid}))


def test_an_rbd_built_over_mcp_takes_a_joint_block(env):
    a = env.token[A]
    mid = _ok(_call(a, "models", {"action": "fit_joint", "name": "Pumps", **_datasets(a)}))["model_id"]
    unit = _ok(_call(a, "get", {"kind": "model", "id": mid}))["running_units"][0]
    nodes = [{"id": "input", "type": "input"},
             {"id": "a", "type": "component", "label": "Pump A",
              "model": {"saved_model_id": mid, "joint_unit": {"id": unit}}},
             {"id": "b", "type": "component", "label": "Pump B",
              "model": {"saved_model_id": mid, "joint_unit": {"age": 40, "readings": [[0, 2.0], [40, 2.6]],
                                                              "covariates": {"load": 0}}}},
             {"id": "output", "type": "output"}]
    edges = [{"source": "input", "target": "a"}, {"source": "input", "target": "b"},
             {"source": "a", "target": "output"}, {"source": "b", "target": "output"}]
    rbd = _ok(_call(a, "rbd", {"action": "create", "name": "Pumps", "unit": "Days", "nodes": nodes,
                               "edges": edges}))
    saved = env.db.rbds.find_one({"_id": rbd["id"]})
    model = next(n for n in saved["graph"]["nodes"] if n["id"] == "a")["data"]["model"]
    assert model["kind"] == "joint" and model["joint_unit"] == {"id": unit}
    out = _ok(_call(a, "rbd_analysis", {"action": "analyze", "rbd_id": rbd["id"], "times": [10]}))
    assert 0 < out["reliability_at"][0]["reliability"] < 1
    # A joint model with no unit is refused, saying how to give one.
    nodes[1]["model"] = {"saved_model_id": mid}
    assert "joint_unit" in _err(_call(a, "rbd", {"action": "create", "name": "x", "unit": "Days",
                                                 "nodes": nodes, "edges": edges}))


def test_the_fit_job_reads_back_through_get_kind_job(env, monkeypatch):
    from backend import mcp_server
    from backend.services import compute_core, compute_queue, rbd_jobs

    queued = []
    monkeypatch.setattr(compute_queue, "configured", lambda: True)
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: queued.append((job_id, kind, request)))
    monkeypatch.setattr(mcp_server, "_JOINT_WAIT_S", 0.0)
    a = env.token[A]
    pending = _ok(_call(a, "models", {"action": "fit_joint", "name": "Pumps", **_datasets(a, n=50)}))
    job_id = pending["job"]["job_id"]
    assert _ok(_call(a, "get", {"kind": "job", "id": job_id}))["available"] is False
    _, kind, request = queued[0]
    result = compute_core.run(kind, json.loads(json.dumps(request)))
    rbd_jobs.apply_callback(env.db, {"job_id": job_id, "status": "done", "result": result})
    done = _ok(_call(a, "get", {"kind": "job", "id": job_id}))
    assert done["available"] is True and done["model_id"] and done["hazard_ratios"]


def test_fit_joint_is_pro_and_heavy_and_says_how_to_fit_locally():
    from backend import mcp_server

    for call in ("life_data_analysis.fit_joint", "models.fit_joint"):
        assert call in mcp_server.PRO_ONLY_TOOLS and call in mcp_server.HEAVY_TOOLS
        assert "WeibullJointPH.fit_from_df" in mcp_server._pro_only_message(call)
    assert "life_data_analysis.predict_joint" not in mcp_server.PRO_ONLY_TOOLS
