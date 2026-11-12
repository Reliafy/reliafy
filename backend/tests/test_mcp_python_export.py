"""MCP's Download as Python: analyse model_export_python for a saved model of
any kind, and python=true on the test-planning actions, give the same script
as the app's download."""

import pytest

from backend.tests.python_scripts import close, run
from backend.tests.test_mcp import FLAGS, TIMES, A, B, _call, _err, _ok, env  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")


def test_a_saved_model_downloads_as_python_over_mcp(env, tmp_path):
    saved = _ok(_call(env.token[A], "change", {"action": "model_fit",
                                               "data": TIMES, "censored": FLAGS, "unit": "hours", "name": "Pumps"}))
    out = _ok(_call(env.token[A], "analyse", {"action": "model_export_python", "model_id": saved["model_id"]}))
    assert out["filename"] == "pumps.py" and "surpyval==" in out["run"]
    printed = run(out["script"], tmp_path)
    results = env.db.models.find_one({"_id": saved["model_id"]})["results"]
    for p in results["params"]:
        close(printed[p["name"]]["value"], p["value"])
    for b in results["life"]["b_lives"]:
        close(printed[b["label"]]["value"], b["value"])
        close(printed[b["label"]]["bound"], b["lower"])
    # Another account can't read it.
    msg = _err(_call(env.token[B], "analyse", {"action": "model_export_python", "model_id": saved["model_id"]}))
    assert "not found" in msg.lower()


def test_a_test_plan_comes_with_its_script_when_asked(env, tmp_path):
    args = {"action": "plan_life_test", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}],
            "units": 20, "censor_time": 800}
    plain = _ok(_call(env.token[A], "analyse", args))
    assert "script" not in plain
    out = _ok(_call(env.token[A], "analyse", {**args, "python": True}))
    assert out["script"]["filename"].endswith(".py")
    run(out["script"]["script"], tmp_path)


def test_a_comparison_plan_with_its_script(env, tmp_path):
    out = _ok(_call(env.token[A], "analyse", {"action": "plan_comparison", "kind": "logrank", "solve_for": "sample_size",
                                              "hazard_ratio": 2, "event_probability": 0.5, "python": True}))
    run(out["script"]["script"], tmp_path)
