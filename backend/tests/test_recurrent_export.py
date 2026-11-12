"""Download as Python for repairable models: every saved kind's script runs
on its own and prints the numbers the model page shows."""

import json

import mongomock
import pytest

from backend.tests import python_scripts
from backend.tests.test_recurrent import A, _client, _events_csv

B = "user-b"
PUMP_FORM = {"i": "pump", "x": "hours", "tr": "observed_to", "unit": "hours"}
FLEET_FORM = {"i": "system", "x": "time", "t": "obs_end", "unit": "hours"}


@pytest.fixture()
def api(monkeypatch):
    from backend.auth import get_current_user

    client, app = _client(monkeypatch, mongomock.MongoClient()["reliafy_test"])
    who = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: {"uid": who["uid"], "email": "x@x.com", "name": "X"}
    client.who = who
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _save(client, form, csv, name="M"):
    files = {"file": ("e.csv", csv, "text/csv")} if csv is not None else None
    r = client.post("/api/recurrent/models", data={**form, "name": name}, files=files)
    assert r.status_code == 200, r.text
    return client.get(f"/api/recurrent/models/{r.json()['id']}").json()


def _script(client, mid):
    r = client.get(f"/api/recurrent/models/{mid}/export.py")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/x-python")
    assert "requirements: surpyval==" in r.text
    return r.text


def _check_params(out, res, skip=()):
    for p in res["params"]:
        if p["name"] in skip:
            continue
        row = out[f"Parameter {p['name']}"]
        python_scripts.close(row["value"], p["value"])
        ci = p.get("ci")
        python_scripts.close(row["low"], ci[0] if ci else None)
        python_scripts.close(row["high"], ci[1] if ci else None)


def _check_interval(row, value, ci):
    python_scripts.close(row["value"], value)
    python_scripts.close(row["low"], ci[0] if ci else None)
    python_scripts.close(row["high"], ci[1] if ci else None)


def _check_nhpp(out, res):
    _check_params(out, res)
    if res["model"]["id"] in ("crow_amsaa", "duane"):
        _check_interval(out["Growth shape (beta)"], res["beta"], res["beta_ci"])
    if res.get("growth"):
        assert f"Trend: {res['growth']}" in out["_stdout"]
    python_scripts.close(out["End of observation"]["value"], res["end_of_observation"])
    _check_interval(out["ROCOF at end"], res["rocof"], res.get("rocof_ci"))
    _check_interval(out["MTBF at end"], res["mtbf"], res.get("mtbf_ci"))
    demo = res.get("demonstrated_mtbf")
    if demo:
        python_scripts.close(out["Demonstrated MTBF"]["value"], demo["mtbf"])
        python_scripts.close(out["Demonstrated MTBF"]["bound"], demo["lower"])
        assert f"Bounds method: {res['bounds_method']}" in out["_stdout"]
    labels = {"laplace": "Laplace", "mil_hdbk_189c": "MIL-HDBK-189C"}
    for t in res["trend_tests"]:
        python_scripts.close(out[f"{labels[t['id']]} trend test p-value"]["value"], t["p_value"])


@pytest.mark.parametrize("model", ["crow_amsaa", "duane", "hpp", "cox_lewis"])
def test_minimal_repair_scripts_print_the_page_numbers(api, tmp_path, model):
    detail = _save(api, {**FLEET_FORM, "model": model}, _events_csv())
    out = python_scripts.run(_script(api, detail["id"]), tmp_path)
    _check_nhpp(out, detail["results"])


def test_crow_amsaa_with_observation_gaps(api, tmp_path):
    from backend.services.samples import _PUMP_REPAIRS_CSV

    windows = json.dumps({"P-01": [[0, 4000], [5000, 8760]]})
    detail = _save(api, {**PUMP_FORM, "model": "crow_amsaa", "windows": windows}, _PUMP_REPAIRS_CSV)
    assert detail["results"].get("windows")
    source = _script(api, detail["id"])
    assert "WINDOWS = " in source
    _check_nhpp(python_scripts.run(source, tmp_path), detail["results"])


@pytest.mark.parametrize("baseline", ["crow_amsaa", "duane"])
def test_proportional_intensity_script(api, tmp_path, baseline):
    from backend.services.samples import _PUMP_REPAIRS_CSV

    detail = _save(api, {**PUMP_FORM, "model": "pi_nhpp", "z": ["site", "duty_pct"], "baseline": baseline},
                   _PUMP_REPAIRS_CSV)
    res = detail["results"]
    out = python_scripts.run(_script(api, detail["id"]), tmp_path)
    _check_params(out, res)
    for c in res["coefficients"]:
        label = c["name"].replace(":", " =")
        _check_interval(out[f"Coefficient {label}"], c["coef"], c["coef_ci"])
        _check_interval(out[f"Rate ratio {label}"], c["ratio"], c["ratio_ci"])
    _check_interval(out["ROCOF at end (average system)"], res["rocof"], res["rocof_ci"])
    _check_interval(out["MTBF at end (average system)"], res["mtbf"], res["mtbf_ci"])
    assert res["rates_by_group"]
    for g in res["rates_by_group"]:
        _check_interval(out[f"MTBF at end, {g['label']}"], g["mtbf"], g["mtbf_ci"])
        if g["mtbf_lower"]:
            python_scripts.close(out[f"MTBF at end at least, {g['label']}"]["bound"], g["mtbf_lower"])


@pytest.mark.parametrize("model,extra", [("grp_i", {}), ("grp_ii", {}), ("ara", {"m": "2"}),
                                         ("ari", {"m": "1"}), ("g1", {})])
def test_imperfect_repair_scripts(api, tmp_path, model, extra):
    detail = _save(api, {**FLEET_FORM, "model": model, **extra}, _events_csv())
    res = detail["results"]
    out = python_scripts.run(_script(api, detail["id"]), tmp_path)
    _check_params(out, res)
    rest = res["restoration"]
    if model == "g1":
        _check_interval(out["Gap ratio (each gap / the one before)"], rest["ratio"], rest["ratio_ci"])
    else:
        _check_interval(out["Share restored by each repair"], rest["effectiveness"], rest["effectiveness_ci"])


@pytest.mark.parametrize("model", ["crow_amsaa", "duane"])
def test_a_model_from_parameters_is_rebuilt_from_them(api, tmp_path, model):
    r = api.post("/api/recurrent/from-params",
                 data={"name": "Typed", "model": model, "alpha": 500, "beta": 1.4, "horizon": 2000, "unit": "hours"})
    assert r.status_code == 200, r.text
    res = api.get(f"/api/recurrent/models/{r.json()['id']}").json()["results"]
    out = python_scripts.run(_script(api, r.json()["id"]), tmp_path)
    for p in res["params"]:
        python_scripts.close(out[f"Parameter {p['name']}"]["value"], p["value"])
    python_scripts.close(out["ROCOF at horizon"]["value"], res["rocof"])
    python_scripts.close(out["MTBF at horizon"]["value"], res["mtbf"])


def test_another_users_model_is_not_found(api):
    detail = _save(api, {**FLEET_FORM, "model": "crow_amsaa"}, _events_csv())
    api.who["uid"] = B
    assert api.get(f"/api/recurrent/models/{detail['id']}/export.py").status_code == 404
