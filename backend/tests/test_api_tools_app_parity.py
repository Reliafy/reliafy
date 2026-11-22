"""Three things the app does that agents couldn't, now MCP actions with their
REST twins (backend/routers/api_tools.py makes those from the MCP tool):
fit and save a degradation model, add an RCM worksheet or task plan to a
position from CSV, and save an optimal-replacement analysis."""

import matplotlib

matplotlib.use("Agg")

import pytest

from backend.tests.test_api_tools import A, FREE, WEIBULL, env, maint  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("mcp_on")


def _readings() -> str:
    """Six liners wearing from 25 mm, each at its own steady rate, read every 500 hours."""
    rows = ["pump,hours,thickness_mm"]
    for k, rate in enumerate((0.0050, 0.0058, 0.0066, 0.0072, 0.0081, 0.0090)):
        for t in range(0, 2501, 500):
            rows.append(f"P{k + 1},{t},{25 - rate * t + 0.02 * ((t // 500 + k) % 3 - 1):.4f}")
    return "\n".join(rows) + "\n"


def test_fit_and_save_a_degradation_model(env):  # noqa: F811
    ds = env.post("/api/v1/change/dataset_upload", {"name": "Liner wear", "csv": _readings()})
    assert ds.status_code == 200, ds.text
    body = {"name": "Liner wear to 10 mm", "dataset_id": ds.json()["id"], "unit_id_column": "pump",
            "age_column": "hours", "value_column": "thickness_mm", "threshold": 10, "path": "linear",
            "unit": "hours", "measurement_unit": "mm"}
    preview = env.post("/api/v1/change/model_fit_degradation", {**body, "dry_run": True})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["saved"] is False and env.db.degradation_models.count_documents({}) == 0
    assert p["counts"]["n_units"] == 6 and p["counts"]["n_censored"] == 0  # every path reaches 10 mm (extrapolated)
    assert p["path_model"] and p["unit"].lower() == "hours" and p["threshold"] == 10
    # Each liner crosses where its own line reaches 10 mm: 15 mm worn at its rate.
    crossing = {c["unit_id"]: c["time"] for c in p["crossings"]}
    assert crossing["P1"] == pytest.approx(15 / 0.0050, rel=0.03)
    assert crossing["P6"] == pytest.approx(15 / 0.0090, rel=0.03)
    b10 = p["b_lives"]["B10"]
    assert b10["lower_90"] is not None and b10["lower_90"] < b10["value"] < p["b_lives"]["B50"]["value"]

    saved = env.post("/api/v1/change/model_fit_degradation", body).json()
    assert saved["saved"] is True and saved["url"].endswith(f"/models/degradation/{saved['id']}")
    assert saved["b_lives"]["B50"]["value"] == pytest.approx(p["b_lives"]["B50"]["value"])
    listed = env.post("/api/v1/list/models", {"model_type": "degradation"}).json()
    assert [m["id"] for m in listed["degradation_models"]] == [saved["id"]]
    got = env.post("/api/v1/get/model", {"id": saved["id"]}).json()
    assert got["model_type"] == "degradation" and got["counts"]["n_units"] == 6

    # Someone else's dataset isn't found; a bad column says which.
    other = env.post("/api/v1/change/model_fit_degradation", body, uid="user-b")
    assert other.status_code >= 400 and "Dataset not found" in other.text
    bad = env.post("/api/v1/change/model_fit_degradation", {**body, "value_column": "nope"})
    assert bad.status_code >= 400 and "nope" in bad.text


def test_degradation_fitting_is_pro_and_saving_a_replacement_analysis_is_not():
    from backend import mcp_server

    assert "change.model_fit_degradation" in mcp_server.PRO_ONLY_TOOLS
    assert "change.optimal_replacement_save" not in mcp_server.PRO_ONLY_TOOLS
    assert "change.import_rcm" not in mcp_server.PRO_ONLY_TOOLS


def test_save_an_optimal_replacement_analysis(env):  # noqa: F811
    inputs = {"distribution_id": "weibull", "params": WEIBULL, "planned_cost": 200, "unplanned_cost": 1500,
              "unit": "hours", "use_per_year": 4000}
    answer = env.post("/api/v1/analyse/optimal_replacement", inputs).json()
    r = env.post("/api/v1/change/optimal_replacement_save", {"name": "Pump bearings", **inputs})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["saved"] and out["kind"] == "optimal_replacement"
    assert out["results"]["optimal_time"] == pytest.approx(answer["optimal_time"])
    assert out["headline"].startswith("Replace at ~") and out["url"].endswith(f"/strategy/analyses/{out['id']}")
    doc = env.db.strategy_analyses.find_one({"_id": out["id"]})
    assert doc["owner_id"] == A and doc["inputs"]["planned_cost"] == 200
    # It reads back in the app like one saved from Strategy > Replacement.
    from backend.services import strategy_store

    assert strategy_store.get_analysis(env.db, out["id"], A).results["optimal_time"] == pytest.approx(
        answer["optimal_time"])
    # From a saved model: its name is kept for the analysis page.
    model = env.post("/api/v1/change/model_save", {"name": "Bearing life", "distribution": "weibull",
                                                   "params": WEIBULL, "unit": "hours"}).json()
    r = env.post("/api/v1/change/optimal_replacement_save", {"name": "From the model", "model_id": model["model_id"],
                                                             "planned_cost": 200, "unplanned_cost": 1500})
    assert r.status_code == 200, r.text
    assert env.db.strategy_analyses.find_one({"_id": r.json()["id"]})["inputs"]["model_name"] == "Bearing life"
    missing = env.post("/api/v1/change/optimal_replacement_save", {"name": "x", "planned_cost": 1,
                                                                   "unplanned_cost": 2})
    assert missing.status_code >= 400 and "model_id" in missing.text


SHEET = ("Function,Functional failure,Failure mode,Task type,Proposed task,Interval,Unit\n"
         "Move grain,Moves no grain,Belt torn,On-condition,Walk the belt,1,weeks\n"
         ",,Drive bearing seizes,Fixed interval,Replace bearings,12,months\n")


def test_import_an_rcm_worksheet_from_csv_text(maint):  # noqa: F811
    pid = maint.post("/api/v1/maintenance/positions.create", {"name": "Conveyor C-2"}).json()["id"]
    preview = maint.post("/api/v1/change/import_rcm", {"position_id": pid, "csv": SHEET, "dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json()["written"] is False and preview.json()["counts"]["modes"] == 2
    done = maint.post("/api/v1/change/import_rcm", {"position_id": pid, "csv": SHEET}).json()
    assert done["written"] and done["counts"]["modes"] == 2 and done["counts"]["tasks"] == 2
    again = maint.post("/api/v1/change/import_rcm", {"position_id": pid, "csv": SHEET}).json()
    assert again["counts"]["modes"] == 0 and again["counts"]["modes_existing"] == 2
    rcm = maint.post("/api/v1/maintenance/get.rcm", {"id": pid, "scope": "this"}).json()["positions"][0]
    assert [m["text"] for m in rcm["functions"][0]["failures"][0]["modes"]] == ["Belt torn", "Drive bearing seizes"]
    both = maint.post("/api/v1/change/import_rcm", {"position_id": pid})
    assert both.status_code >= 400 and "exactly one of upload_id" in both.text
    # Without Reliafy Maintenance there are no positions.
    other = maint.post("/api/v1/change/import_rcm", {"position_id": pid, "csv": SHEET}, uid="user-b")
    assert other.status_code >= 400 and "positions aren't available" in other.text
