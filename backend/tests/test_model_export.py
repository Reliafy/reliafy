"""Download as Python for saved life models (non-repairable): the script runs
on its own and prints the same numbers the model page shows."""

import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest

from backend.tests.python_scripts import close, run

A, B = "user-a", "user-b"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}, B: {"uid": B, "email": "b@x.com", "name": "B"}}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    who = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: USERS[who["uid"]]
    tc = TestClient(app)
    tc.act_as = lambda uid: who.update(uid=uid)
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


PUMPS = "months,censored\n" + "".join(f"{v},0\n" for v in (4, 7, 9, 11, 13, 15, 16, 18, 19, 21, 23, 24, 26)) \
    + "36,1\n36,1\n36,1\n"
# Status words, one row in weeks among days.
STATUS = "hours,status\n" + "".join(
    f"{h},{s}\n" for h, s in [(1200, "F"), (1850, "F"), (2100, "S"), (2400, "F"), (3000, "F"), (3300, "S"),
                              (3900, "F"), (4400, "F"), (5000, "S"), (5200, "F"), (6100, "F"), (7000, "S")])
INSPECTIONS = "last_ok,found,status\n0,500,0\n500,1000,0\n500,1000,0\n1000,1500,0\n1000,1500,0\n1000,1500,0\n" \
              "1500,2000,0\n1500,2000,0\n2000,2500,0\n2000,,1\n2000,,1\n2500,3000,0\n"
SHOTS = "cycles,censored\n" + "".join(f"{v},0\n" for v in (2, 3, 3, 4, 5, 5, 6, 8, 10, 12)) + "12,1\n12,1\n"
MIXED = "hours\n" + "".join(f"{v}\n" for v in (
    312, 420, 506, 588, 655, 719, 773, 824, 889, 946, 998, 1051, 1104, 1158, 1203, 1259, 1312, 1366, 1421, 1485,
    1542, 1607, 1683, 1764, 1842, 1925, 2014, 2118, 2233, 2401))


def _save(client, csv: str, **form) -> dict:
    res = client.post("/api/models", data={"name": "Pumps", **form},
                      files={"file": ("data.csv", csv.encode(), "text/csv")})
    assert res.status_code == 200, res.text
    return res.json()


def _script(client, model_id: str) -> str:
    res = client.get(f"/api/models/{model_id}/export.py")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/x-python")
    assert "requirements: surpyval==" in res.text
    return res.text


def _check_params(printed, results, intervals=True):
    for p in results["params"]:
        got = printed[p["name"]]
        close(got["value"], p["value"])
        if intervals and p.get("ci"):
            close(got["low"], p["ci"][0])
            close(got["high"], p["ci"][1])


def _check_life(printed, results):
    life = results["life"]
    for b in life["b_lives"]:
        got = printed[b["label"]]
        close(got["value"], b["value"])
        close(got["bound"], b["lower"])
    close(printed["Mean life"]["value"], life["mttf"]["value"])
    close(printed["Mean life"]["bound"], life["mttf"]["lower"])


@pytest.mark.parametrize("form", [
    {"distribution": "weibull", "x": "months", "c": "censored", "unit": "months"},
    {"distribution": "lognormal", "x": "months", "c": "censored", "unit": "months"},
    {"distribution": "weibull", "x": "months", "c": "censored", "unit": "months", "offset": "true"},
    {"distribution": "weibull", "x": "months", "c": "censored", "unit": "months", "how": "MPP"},
    {"distribution": "weibull", "x": "months", "c": "censored", "unit": "months", "fixed": json.dumps({"beta": 2})},
    {"distribution": "weibull", "x": "months", "c": "censored", "unit": "months", "lfp": "true"},
    {"distribution": "best", "x": "months", "c": "censored", "unit": "months"},
], ids=["weibull", "lognormal", "offset", "mpp", "fixed", "lfp", "best"])
def test_a_fitted_distribution_prints_the_pages_numbers(client, tmp_path, form):
    model = _save(client, PUMPS, **form)
    printed = run(_script(client, model["id"]), tmp_path)
    results = model["results"]
    _check_params(printed, results)
    _check_life(printed, results)
    for extra in results.get("extra_params") or []:
        close(printed[extra["name"]]["value"], extra["value"])


def test_status_words_and_a_1_is_failed_column_are_read_as_the_app_read_them(client, tmp_path):
    words = _save(client, STATUS, distribution="weibull", x="hours", c="status", unit="hours",
                  c_map=json.dumps({"F": 0, "S": 1}))
    printed = run(_script(client, words["id"]), tmp_path)
    _check_params(printed, words["results"])
    _check_life(printed, words["results"])

    flipped = PUMPS.replace(",0\n", ",x\n").replace(",1\n", ",0\n").replace(",x\n", ",1\n")
    inverted = _save(client, flipped, distribution="weibull", x="months", c="censored", unit="months",
                     c_invert="true")
    source = _script(client, inverted["id"])
    assert "turned round" in source
    printed = run(source, tmp_path, "inverted.py")
    _check_params(printed, inverted["results"])
    _check_life(printed, inverted["results"])


def test_inspection_data_fits_on_intervals(client, tmp_path):
    model = _save(client, INSPECTIONS, distribution="weibull", xl="last_ok", xr="found", c="status", unit="hours")
    printed = run(_script(client, model["id"]), tmp_path)
    _check_params(printed, model["results"])
    _check_life(printed, model["results"])


def test_a_mixture_prints_each_component_and_its_lives(client, tmp_path):
    model = _save(client, MIXED, distribution="mixture", x="hours", unit="hours", mixture="2",
                  mixture_distribution="weibull")
    printed = run(_script(client, model["id"]), tmp_path)
    _check_params(printed, model["results"], intervals=False)
    _check_life(printed, model["results"])


@pytest.mark.parametrize("estimator", ["kaplan_meier", "nelson_aalen"])
def test_a_non_parametric_estimate_prints_its_b_lives_and_mean(client, tmp_path, estimator):
    model = _save(client, PUMPS, distribution=estimator, x="months", c="censored", unit="months")
    printed = run(_script(client, model["id"]), tmp_path)
    _check_life(printed, model["results"])


def test_a_discrete_fit_prints_its_parameters_and_metrics(client, tmp_path):
    model = _save(client, SHOTS, distribution="geometric", x="cycles", c="censored")
    printed = run(_script(client, model["id"]), tmp_path)
    results = model["results"]
    _check_params(printed, results)
    close(printed["Median"]["value"], results["metrics"]["median"])
    close(printed["B10"]["value"], results["metrics"]["b10"])
    close(printed["Mean life"]["value"], results["metrics"]["mttf"])


def test_a_model_from_parameters_and_a_per_demand_model(client, tmp_path):
    res = client.post("/api/models/from-params", json={"name": "Vendor", "distribution": "weibull",
                                                       "params": [{"name": "alpha", "value": 5000}, {"name": "beta", "value": 1.8}], "unit": "hours"})
    assert res.status_code == 200, res.text
    model = res.json()
    printed = run(_script(client, model["id"]), tmp_path)
    _check_params(printed, model["results"], intervals=False)
    _check_life(printed, model["results"])

    res = client.post("/api/models/per-demand", json={"name": "Valve", "demands": 400, "failures": 3})
    assert res.status_code == 200, res.text
    model = res.json()
    printed = run(_script(client, model["id"]), tmp_path, "valve.py")
    d = model["results"]["per_demand"]
    got = printed["Failure probability per demand"]
    close(got["value"], d["p"])
    close(got["bound"], d["p_upper"])
    rel = printed["Reliability per demand"]
    close(rel["value"], d["reliability"])
    close(rel["bound"], d["reliability_lower"])


def test_only_viewers_can_download(client):
    model = _save(client, PUMPS, distribution="weibull", x="months", c="censored", unit="months")
    client.act_as(B)
    assert client.get(f"/api/models/{model['id']}/export.py").status_code == 404


def test_a_turnbull_estimate_of_inspection_data_gives_each_b_life_as_an_interval(client, tmp_path):
    model = _save(client, INSPECTIONS, distribution="turnbull", xl="last_ok", xr="found", c="status",
                  unit="hours")
    printed = run(_script(client, model["id"]), tmp_path)
    life = model["results"]["life"]
    # Each B-life is the inspection interval it falls in (this was lost when the
    # app stopped importing warnings there: the B-lives fell back to bare times).
    assert any(b.get("between") for b in life["b_lives"])
    for b in life["b_lives"]:
        got = printed[b["label"]]
        close(got["value"], b["value"])
        close(got["bound"], b["lower"])
        if b.get("between"):
            assert f"{b['label']} between: {b['between'][0]:.6g} and {b['between'][1]:.6g}" in printed["_stdout"]
    close(printed["Mean life"]["value"], life["mttf"]["value"])
    close(printed["Mean life"]["bound"], life["mttf"]["lower"])


def test_a_publicly_shared_model_downloads_as_python_too(client, tmp_path):
    model = _save(client, PUMPS, distribution="weibull", x="months", c="censored", unit="months")
    r = client.post("/api/public-links", json={"collection": "models", "artifact_id": model["id"]})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    res = client.get(f"/api/public/{token}/export.py")
    assert res.status_code == 200, res.text
    printed = run(res.text, tmp_path)
    _check_params(printed, model["results"])
    # A revoked link downloads nothing.
    assert client.delete(f"/api/public-links/{token}").status_code == 200
    assert client.get(f"/api/public/{token}/export.py").status_code == 404
