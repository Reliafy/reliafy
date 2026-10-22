"""Condition monitoring: joint models of readings and failures (SurPyval's
``JointPH``), saved as models of kind ``joint``, fitted as a compute job,
and used as non-repairable RBD blocks (RePyability's ``JointNode``).

The synthetic fleet is drawn from the joint model itself: each unit's
reading follows its own straight line, and its failure time solves
``H(T) = E`` for the Weibull proportional hazards in the reading's current
value (and a covariate), so the fit should recover the parameters.
"""

import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import joint

TRUE = dict(a=2.0, b=0.02, sd_a=0.3, sd_b=0.004, sd_noise=0.15, alpha=150.0, beta=2.0, zeta=0.8, ref=2.0,
            load=0.5)
LIFE_MAP = {"id": "unit", "x": "age", "c": "running"}
READ_MAP = {"id": "unit", "age": "age", "value": "value"}


def fleet(n=150, seed=7, stop=120.0, every=10.0):
    """``(lifetimes, readings)``: ``n`` units observed to ``stop`` days,
    read every ``every`` days; half carry load 1."""
    rng = np.random.default_rng(seed)
    grid = np.linspace(0, 1000, 20001)
    life, reads = [], []
    for k in range(n):
        load = k % 2
        a, b = rng.normal(TRUE["a"], TRUE["sd_a"]), rng.normal(TRUE["b"], TRUE["sd_b"])
        h = (TRUE["beta"] / TRUE["alpha"] * (np.maximum(grid, 1e-12) / TRUE["alpha"]) ** (TRUE["beta"] - 1)
             * np.exp(TRUE["zeta"] * (a + b * grid - TRUE["ref"]) + TRUE["load"] * load))
        H = np.concatenate([[0], np.cumsum((h[1:] + h[:-1]) / 2 * np.diff(grid))])
        T = float(np.interp(rng.exponential(), H, grid))
        end = min(T, stop)
        ages = np.arange(0.0, end, every)
        y = a + b * ages + rng.normal(0, TRUE["sd_noise"], ages.size)
        uid = f"U{k:03d}"
        life.append({"unit": uid, "age": round(end, 4), "running": int(T >= stop), "load": load})
        reads += [{"unit": uid, "age": float(t), "value": round(float(v), 5)} for t, v in zip(ages, y)]
    return pd.DataFrame(life), pd.DataFrame(reads)


@pytest.fixture(scope="module")
def fitted():
    """One fit of the 150-unit fleet, shared by the module."""
    L, R = fleet()
    items, summary = joint.build_items(L, R, LIFE_MAP, READ_MAP, ["load"])
    request = joint.fit_request(items, ["load"], path_model="linear", hazard_covariates=["load"],
                                path_covariates=[], unit="Days", marker="vibration", summary=summary)
    out = joint.run_fit(request)
    return {"items": items, "summary": summary, "out": out, "model": joint.restore(out["model"]), "L": L, "R": R}


# ---- The fit ---------------------------------------------------------------------------


def test_the_fit_recovers_the_fleets_parameters(fitted):
    rows = {r["name"]: r for r in fitted["out"]["results"]["params"]}
    truth = {"a": TRUE["a"], "b": TRUE["b"], "sd_a": TRUE["sd_a"], "sd_b": TRUE["sd_b"],
             "sd_noise": TRUE["sd_noise"], "beta": TRUE["beta"], "load": TRUE["load"],
             "marker_effect": TRUE["zeta"]}
    for name, value in truth.items():
        r = rows[name]
        assert abs(r["value"] - value) <= 3 * r["se"], (name, r["value"], value, r["se"])
    # alpha is reported at the mean reading: the true scale moved there.
    r = rows["alpha"]
    ref = fitted["model"].marker_reference
    alpha_at_ref = TRUE["alpha"] * np.exp(-TRUE["zeta"] * (ref - TRUE["ref"]) / TRUE["beta"])
    assert r["lower"] < alpha_at_ref < r["upper"]
    results = fitted["out"]["results"]
    assert results["fit_ok"] and results["maximum"] == "verified"
    assert results["path_covariates"] == {"a": [], "b": []} and results["hazard_covariates"] == ["load"]


def test_the_results_say_the_hazard_ratios_plainly_and_list_the_running_units(fitted):
    r = fitted["out"]["results"]
    hr = {h["name"]: h for h in r["hazard_ratios"]}
    assert hr["marker_effect"]["hr"] == pytest.approx(np.exp(next(
        p["value"] for p in r["params"] if p["name"] == "marker_effect")))
    assert hr["marker_effect"]["text"].startswith("Each 1 unit higher vibration multiplies the failure rate by")
    assert "at the same vibration" in hr["load"]["text"] and "95% CI" in hr["load"]["text"]
    assert r["horizons"]["labels"] == ["30 days", "90 days", "365 days"]
    running = fitted["L"][fitted["L"].running == 1]
    assert r["n_running"] == len(running) == len(r["risk"]) == len(fitted["out"]["units"])
    risks = [u["risk"][1] for u in r["risk"]]
    assert risks == sorted(risks, reverse=True)
    for u in r["risk"]:
        pred = joint.predict(fitted["model"], u["covariates"], fitted["out"]["units"][u["id"]]["markers"],
                             u["age"])
        assert u["survival"][0] == pytest.approx(float(pred.sf(u["age"] + 30.0)), rel=1e-9)
        assert u["median_reached"] == np.isfinite(pred.remaining_life(0.5))
    json.dumps(fitted["out"], allow_nan=False)  # strict JSON: it crosses the wire and into Mongo


def test_the_data_checks_say_what_to_fix():
    L, R = fleet(n=20)
    bad = R.copy()
    bad.loc[0, "age"] = 999.0
    with pytest.raises(joint.FitError, match="reading after their age"):
        joint.build_items(L, bad, LIFE_MAP, READ_MAP)
    twice = pd.concat([L, L.iloc[[0]]])
    with pytest.raises(joint.FitError, match="appears more than once"):
        joint.build_items(twice, R, LIFE_MAP, READ_MAP)
    with pytest.raises(joint.FitError, match="censoring column"):
        joint.build_items(L, R, {"id": "unit", "x": "age"}, READ_MAP)
    extra = pd.concat([R, pd.DataFrame([{"unit": "ghost", "age": 1.0, "value": 2.0}])])
    _, summary = joint.build_items(L, extra, LIFE_MAP, READ_MAP)
    assert summary["unmatched_ids"] == ["ghost"] and "aren't in the lifetimes table" in summary["notes"][0]
    # c_invert flips 0 and 1: every unit's flag is then the other way round.
    flipped = L.assign(running=1 - L.running)
    items, _ = joint.build_items(flipped, R, LIFE_MAP, READ_MAP, c_invert=True)
    assert [it["c"] for it in items] == L.running.tolist()


def test_a_saved_fit_round_trips(fitted):
    m = fitted["model"]
    back = joint.restore(json.loads(json.dumps(m.to_dict())))
    uid, inp = next(iter(fitted["out"]["units"].items()))
    t = inp["age"] + np.array([5.0, 20.0, 60.0])
    a = joint.predict(m, inp["covariates"], inp["markers"], inp["age"])
    b = joint.predict(back, inp["covariates"], inp["markers"], inp["age"])
    assert np.allclose(a.sf(t), b.sf(t), rtol=1e-12)
    assert list(back.params) == pytest.approx(list(m.params))


def test_download_as_python_refits_with_fit_from_df(fitted, tmp_path):
    src = joint.python_script("Pumps", fitted["items"], ["load"], path_model="linear",
                              hazard_covariates=["load"], path_covariates=[], unit="Days", marker="vibration",
                              horizon=90)
    assert "fit_from_df(" in src and 'c_col="censored"' in src and 'markers_col="readings"' in src
    compile(src, "pumps.py", "exec")
    ns: dict = {"__name__": "exported"}
    exec(compile(src, "pumps.py", "exec"), ns)  # runs the refit (prints the model)
    assert list(ns["model"].params) == pytest.approx(list(fitted["model"].params), rel=1e-6)


# ---- RBD blocks ------------------------------------------------------------------------


def _graph(fitted, parallel=False, repairable=False):
    units = list(fitted["out"]["units"])
    a = {"kind": "joint", "modelId": "jm", "unit": "Days", "joint_unit": {"id": units[0]}}
    b = {"kind": "joint", "modelId": "jm", "unit": "Days",
         "joint_unit": {"age": 60.0, "markers": [[0, 2.1], [30, 2.6], [60, 3.2]], "covariates": {"load": 1}}}
    nodes = [{"id": "input", "type": "input", "data": {}},
             {"id": "a", "type": "component", "data": {"label": "Pump A", "model": a}},
             {"id": "b", "type": "component", "data": {"label": "Pump B", "model": b}},
             {"id": "output", "type": "output", "data": {}}]
    if parallel:
        edges = [("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")]
    else:
        edges = [("input", "a"), ("a", "b"), ("b", "output")]
    g = {"unit": "Days", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}
    if repairable:
        g["repairable"] = True
    return g


def _resolver(fitted):
    entry = {"kind": "joint", "model": fitted["model"], "units": fitted["out"]["units"], "name": "Pumps"}
    return lambda mid: entry if mid == "jm" else None


@pytest.mark.parametrize("parallel", [False, True])
def test_an_rbd_of_joint_blocks_is_the_product_of_their_predictions(fitted, parallel):
    from backend.services import rbd_analysis

    t = np.array([5.0, 15.0, 40.0])
    out = rbd_analysis.analyze(_graph(fitted, parallel), resolve_model=_resolver(fitted), at_times=t.tolist(),
                               t_max=60.0)
    inp = fitted["out"]["units"][list(fitted["out"]["units"])[0]]
    pa = joint.predict(fitted["model"], inp["covariates"], inp["markers"], inp["age"])
    pb = joint.predict(fitted["model"], {"load": 1}, [[0, 2.1], [30, 2.6], [60, 3.2]], 60.0)
    ra, rb = pa.sf(pa.age + t), pb.sf(pb.age + t)
    expect = 1 - (1 - ra) * (1 - rb) if parallel else ra * rb
    assert out["at"]["sf"] == pytest.approx(expect.tolist(), rel=1e-9, abs=1e-12)
    ages = {n["id"]: n.get("joint_age") for n in out["nodes"]}
    assert ages == {"a": inp["age"], "b": 60.0}


def test_repairable_diagrams_and_several_unit_blocks_refuse_joint_blocks(fitted):
    from backend.services import rbd_analysis

    with pytest.raises(rbd_analysis.AnalysisError, match="repairable diagram replaces a failed unit"):
        rbd_analysis.analyze_availability(_graph(fitted, repairable=True), resolve_model=_resolver(fitted),
                                          simulate=False)
    g = _graph(fitted)
    g["nodes"][1]["type"] = "parallel"
    g["nodes"][1]["data"]["n"] = 2
    with pytest.raises(rbd_analysis.AnalysisError, match="single component block"):
        rbd_analysis.analyze(g, resolve_model=_resolver(fitted), t_max=60.0)
    # As of now: the block is already as of now; another age is refused.
    with pytest.raises(rbd_analysis.AnalysisError, match="already as of now"):
        rbd_analysis.analyze(_graph(fitted), resolve_model=_resolver(fitted), current_state={"a": {"age": 10}})


def test_no_mean_life_for_a_unit_whose_reading_falls_away(fitted):
    """A falling reading leaves a chance of never failing: no MTTF, and the
    axis runs far enough to show the curve level off."""
    from backend.services import rbd_analysis

    g = _graph(fitted)
    g["nodes"] = [g["nodes"][0], g["nodes"][2], g["nodes"][3]]
    g["nodes"][1]["data"]["model"]["joint_unit"] = {"age": 80.0, "markers": [[0, 2.0], [40, 1.0], [80, 0.0]],
                                                    "covariates": {"load": 0}}
    g["edges"] = [{"source": "input", "target": "b"}, {"source": "b", "target": "output"}]
    out = rbd_analysis.analyze(g, resolve_model=_resolver(fitted))
    assert out["mttf"] is None and any("No mean life is shown" in w for w in out["warnings"])
    assert out["system"]["sf"][-1] > 0.01


# ---- The API: Pro gating, the job, the saved model ------------------------------------

FREE, PRO = "user-free", "user-pro"
USERS = {FREE: {"uid": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
         PRO: {"uid": PRO, "email": "pro@example.org", "name": "Pro", "email_verified": True}}


@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import billing

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    for uid, user in USERS.items():
        test_db.users.update_one({"_id": uid}, {"$set": {"email": user["email"], "email_lc": user["email"],
                                                         "email_verified": True, "name": user["name"]}},
                                 upsert=True)
    billing.set_plan(test_db, PRO, "pro")
    tc = TestClient(app)
    tc.act_as = lambda uid: app.dependency_overrides.__setitem__(get_current_user, lambda: USERS[uid])
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _body(client, n=60):
    L, R = fleet(n=n)

    def paste(df, name):
        r = client.post("/api/datasets/paste", json={"name": name, "content": df.to_csv(index=False)})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    return {"name": "Pumps", "lifetimes_dataset_id": paste(L, "Pump lives"),
            "readings_dataset_id": paste(R, "Pump vibration"), "mapping": LIFE_MAP, "readings_mapping": READ_MAP,
            "covariates": ["load"], "unit": "Days", "marker": "vibration", "marker_unit": "mm/s"}


def test_fitting_is_pro_and_the_saved_model_reads_back(client):
    client.act_as(FREE)
    body = _body(client)
    r = client.post("/api/joint/models", json=body)
    assert r.status_code == 402 and r.json()["code"] == "pro_required" and r.json()["upgrade"] is True
    assert client.post("/api/joint/check", json=body).json()["n_units"] == 60  # checking the data is free

    client.act_as(PRO)
    body = _body(client)
    r = client.post("/api/joint/models", json=body)
    assert r.status_code == 200, r.text
    mid = r.json()["model_id"]
    detail = client.get(f"/api/joint/models/{mid}").json()
    assert detail["kind"] == "joint" and detail["results"]["unit"] == "Days"
    assert [m["id"] for m in client.get("/api/joint/models").json()["models"]] == [mid]
    # Kept out of the life-model list (and every picker built on it).
    assert mid not in [m["id"] for m in client.get("/api/models").json()["models"]]
    uid = detail["running_units"][0]["id"]
    unit = client.get(f"/api/joint/models/{mid}/units/{uid}").json()
    assert unit["unit_id"] == uid and unit["prediction"]["x"][0] == unit["age"]
    entered = client.post(f"/api/joint/models/{mid}/predict",
                          json={"age": 50, "markers": [[0, 2.0], [40, 3.1]], "covariates": {"load": 1}})
    assert entered.status_code == 200 and entered.json()["age"] == 50
    bad = client.post(f"/api/joint/models/{mid}/predict", json={"age": 50, "markers": [[0, 2.0]]})
    assert bad.status_code == 422 and "load" in bad.json()["detail"]
    py = client.get(f"/api/joint/models/{mid}/export.py")
    assert py.status_code == 200 and "fit_from_df(" in py.text
    # Both datasets are the model's: neither deletes while it stands.
    for key in ("lifetimes_dataset_id", "readings_dataset_id"):
        assert client.delete(f"/api/datasets/{body[key]}").status_code == 409
    # Rehydrated through models_service.get_live_model, as an RBD resolves it.
    from backend.services import models as models_service

    entry = models_service.get_live_model(client.db, mid, [PRO])
    assert entry["kind"] == "joint" and uid in entry["units"]
    # Another user can't read it.
    client.act_as(FREE)
    assert client.get(f"/api/joint/models/{mid}").status_code == 404


def test_the_fit_runs_as_a_compute_job_and_saves_when_it_finishes(client, monkeypatch):
    from backend.services import compute_core, compute_queue, rbd_jobs

    queued = []
    monkeypatch.setattr(compute_queue, "configured", lambda: True)
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: queued.append((job_id, kind, request)))
    client.act_as(PRO)
    r = client.post("/api/joint/models", json=_body(client, n=50))
    assert r.status_code == 202 and r.json()["job"]["kind"] == "joint_fit"
    job_id, kind, request = queued[0]
    assert kind == "joint_fit" and client.db.models.count_documents({"kind": "joint"}) == 0
    # The compute service runs it and calls back; the web saves the model.
    result = compute_core.run(kind, json.loads(json.dumps(request)))
    assert rbd_jobs.apply_callback(client.db, {"job_id": job_id, "status": "done", "result": result})
    view = client.get(f"/api/rbd-jobs/{job_id}").json()
    assert view["status"] == "done" and view["result"]["model_id"]
    assert client.get(f"/api/joint/models/{view['result']['model_id']}").status_code == 200
    # A repeated callback saves nothing more.
    assert not rbd_jobs.apply_callback(client.db, {"job_id": job_id, "status": "done", "result": result})
    assert client.db.models.count_documents({"kind": "joint"}) == 1


def test_an_rbd_with_a_saved_joint_model_analyses_and_refuses_exports(client):
    client.act_as(PRO)
    mid = client.post("/api/joint/models", json=_body(client)).json()["model_id"]
    detail = client.get(f"/api/joint/models/{mid}").json()
    uid = detail["running_units"][0]["id"]
    model = {"source": "joint", "kind": "joint", "modelId": mid, "name": "Pumps", "unit": "Days",
             "joint_unit": {"id": uid}}
    graph = {"unit": "Days", "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "a", "type": "component", "data": {"label": "Pump A", "model": model}},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    r = client.post("/api/rbds/analyze", json={"graph": graph, "t_max": 30})
    assert r.status_code == 200, r.text
    assert r.json()["nodes"][0]["joint_age"] == detail["running_units"][0]["age"]
    r = client.post("/api/rbds/analyze", json={"graph": {**graph, "repairable": True}})
    assert r.status_code == 422 and "condition-based block" in r.json()["detail"]
    rid = client.post("/api/rbds", json={"name": "Pump", "graph": graph}).json()["id"]
    js = client.get(f"/api/rbds/{rid}/export.json")
    assert js.status_code == 422 and "condition-based (joint) model" in js.json()["detail"]
    py = client.get(f"/api/rbds/{rid}/export.py")
    assert py.status_code == 200 and "condition-based block" in py.text and "JointNode" in py.text


def test_one_table_of_readings_and_outcomes_is_both_inputs(client):
    client.act_as(PRO)
    L, R = fleet(n=40)
    last = R.groupby("unit")["age"].transform("max")
    one = R.merge(L[["unit", "running"]], on="unit")
    one["outcome"] = one["running"].where(one["age"] == last.reindex(one.index).values)
    one = one[["unit", "age", "value", "outcome"]]
    pasted = client.post("/api/datasets/paste", json={"name": "Pumps in one", "content": one.to_csv(index=False)})
    assert pasted.status_code == 200, pasted.text
    ds = pasted.json()["id"]
    r = client.post("/api/joint/check", json={
        "lifetimes_dataset_id": ds, "readings_dataset_id": ds, "mapping": {"id": "unit", "x": "age", "c": "outcome"},
        "readings_mapping": READ_MAP})
    assert r.status_code == 200, r.text
    assert r.json()["n_units"] == one["unit"].nunique()
