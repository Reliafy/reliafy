"""What to improve's other measures (#225), parameter uncertainty at several
targets (#325): each checked against RePyability called directly, through
the app (free vs Pro, the queue) and MCP."""

import json

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
import surpyval as surv

from backend.services import compute_core
from backend.services import rbd_analysis as ra
from backend.services import rbd_measures as rm
from backend.services.rbd_analysis import AnalysisError
from backend.tests.test_availability_paid import FREE, PRO, client  # noqa: F401 - fixture
from backend.tests.test_rbd_costs import _exp, _io, _ln, _node, _w

# A pump population fitted to a few failures (a wide covariance), and one
# fitted to many (a narrow one).
FIT = surv.Weibull.fit(np.array([900.0, 1100, 1200, 1300, 1400, 1550, 1700, 1900, 2000, 2300, 2600]))
FIT_TIGHT = surv.Weibull.fit(np.random.default_rng(4).weibull(3.0, 400) * 4000.0)


def _saved(model_id, fit, name="Pump fit"):
    alpha, beta = (float(v) for v in fit.params)
    return {"source": "saved", "kind": "distribution", "modelId": model_id, "name": name,
            "distribution_id": "weibull", "distribution": "Weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _resolver(models):
    return lambda model_id: {"model": models[model_id]} if model_id in models else None


def _train(a="m1", b="m1", motor="m2"):
    """Strainer, then two pumps in parallel (one saved fit), then a motor."""
    nodes = [
        _node("strainer", model=_exp(1e-4), repair=_ln(1.5, 0.5)),
        _node("pa", model=_saved(a, FIT), repair=_ln(2.0, 0.6)),
        _node("pb", model=_saved(b, FIT), repair=_ln(2.0, 0.6)),
        _node("motor", model=_saved(motor, FIT_TIGHT, "Motor fit"), repair=_ln(2.5, 0.5)),
    ]
    pairs = [("input", "strainer"), ("strainer", "pa"), ("strainer", "pb"), ("pa", "motor"), ("pb", "motor"),
             ("motor", "output")]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
            "edges": [{"source": s, "target": t} for s, t in pairs]}


MODELS = {"m1": FIT, "m2": FIT_TIGHT}


def _built(graph):
    rbd, labels, gates, working, broken = ra._build_repairable_rbd(graph)
    return rbd


# ---- Against RePyability -------------------------------------------------------------

def test_over_time_is_birnbaum_over_time():
    graph = _train()
    out = rm.analyze_measure(graph, measure="over_time", window=5000.0)
    rbd = _built(graph)
    grid = np.asarray(out["time"])
    assert grid[0] == 0 and grid[-1] == pytest.approx(5000.0)
    want = rbd.birnbaum_importance(x=grid)
    steady = rbd.birnbaum_importance()
    for s in out["series"]:
        assert s["values"] == pytest.approx(np.asarray(want[s["id"]]), rel=1e-9, abs=1e-12)
        assert s["long_run"] == pytest.approx(steady[s["id"]])
    assert out["series"][0]["long_run"] == max(steady.values())
    assert out["status"] == "ok" and out["answer"].startswith("In the long run") and out["leaders"]
    assert out["question"] == "Which blocks matter most, and when?"


@pytest.mark.parametrize("group_by", ["block", "kind"])
def test_shares_are_differential_importance(group_by):
    graph = _train()
    out = rm.analyze_measure(graph, measure="shares", group_by=group_by)
    rbd = _built(graph)
    singles = rbd.differential_importance(over="parameters", change="proportional", improving=True)
    total = {}
    for lever in rbd.levers():
        if lever.discrete:
            continue
        name = lever.key.title() if group_by == "block" else rm._kind(lever.name)
        total[name] = total.get(name, 0.0) + singles[(lever.key, lever.name)]
    got = {r["group"]: r["share"] for r in out["shares"]}
    assert set(got) == set(total)
    for name, share in total.items():
        assert got[name] == pytest.approx(share, rel=1e-6, abs=1e-12)
    assert sum(got.values()) == pytest.approx(1.0, abs=1e-9)
    if group_by == "kind":
        assert set(got) == {"Lives", "Repair times"}


def test_joint_is_joint_importance():
    graph = _train()
    out = rm.analyze_measure(graph, measure="joint")
    want = _built(graph).joint_importance()
    got = {(r["a"], r["b"]): r["value"] for r in out["pairs"]}
    assert got == pytest.approx({k: float(v) for k, v in want.items()})
    pumps = next(r for r in out["pairs"] if {r["a"], r["b"]} == {"pa", "pb"})
    assert pumps["kind"] == "substitutes" and pumps["value"] < 0
    assert "complements" in out["answer"] and "substitutes" in out["answer"]


def test_rate_is_availability_rate_and_barlow_proschan():
    graph = _train()
    out = rm.analyze_measure(graph, measure="rate", window=3000.0)
    rbd = _built(graph)
    br = rbd.availability_rate(np.asarray(out["time"]))
    assert out["rate"] == pytest.approx(np.asarray(br.rate), rel=1e-9, abs=1e-15)
    for s in out["series"]:
        assert s["values"] == pytest.approx(np.asarray(br.node_rate[s["id"]]), rel=1e-9, abs=1e-15)
    bp = rbd.barlow_proschan_importance()
    assert {c["id"]: c["share"] for c in out["causes"]} == pytest.approx(bp)
    assert sum(c["share"] for c in out["causes"]) == pytest.approx(1.0)
    assert out["causes"][0]["share"] == max(bp.values()) and "of the system's failures" in out["answer"]


def test_a_refused_measure_says_why(monkeypatch):
    """A measure RePyability refuses comes back refused, with its reason in
    the blocks' names — never approximated."""
    graph = _train()

    def refuse(self, *a, **k):
        raise NotImplementedError("Component 'pa' can't be held apart from its group.")

    monkeypatch.setattr(type(_built(graph)), "joint_importance", refuse)
    out = rm.analyze_measure(graph, measure="joint")
    assert out["status"] == "refused" and "“Pa”" in out["message"] and "pairs" not in out


def test_options_are_checked():
    with pytest.raises(AnalysisError):
        rm.options(measure="gamma")
    with pytest.raises(AnalysisError):
        rm.options(measure="shares", group_by="colour")
    with pytest.raises(AnalysisError):
        rm.options(measure="uncertainty", method="bootstrap")
    with pytest.raises(AnalysisError):
        rm.options(measure="uncertainty", times=[1, 2, 3, 4, 5, 6, 7])
    with pytest.raises(AnalysisError):
        rm.options(measure="over_time", window=-1)
    assert rm.heavy(rm.options(measure="uncertainty", method="sobol"))
    assert rm.heavy(rm.options(measure="uncertainty", times=[100]))
    assert not rm.heavy(rm.options(measure="uncertainty"))
    with pytest.raises(AnalysisError):
        rm.analyze_measure({**_train(), "repairable": False}, measure="joint")


# ---- Uncertainty (vega) and several targets (#325) --------------------------------------

def _fitted(graph):
    """The diagram rebuilt as RePyability takes it: the saved fits in place."""
    fits, fixed = rm.fits_for(graph, _resolver(MODELS))
    rbd = _built(graph)
    return rm._with_fits(rbd, graph, fits, {})[:2], fits, fixed


def test_uncertainty_is_repyabilitys():
    graph = _train()
    out = rm.analyze_measure(graph, _resolver(MODELS), measure="uncertainty")
    (fitted, uncertainty), fits, fixed = _fitted(graph)
    assert set(fits) == {"m1", "m2"}
    # The two pumps share one saved model: one input, drawn together.
    assert set(uncertainty) == {("pa", "pb"), "motor"}
    built = fitted._init_args["components"]
    assert built["pa"]["reliability"] is built["pb"]["reliability"]
    want = fitted.mean_availability_uncertainty(uncertainty, n_draws=rm.N_DRAWS, seed=rm.SEED, sampling="sobol")
    lo, hi = want.interval(0.95)
    a = out["availability"]
    assert a["nominal"] == pytest.approx(want.nominal) and a["lower"] == pytest.approx(lo)
    assert a["upper"] == pytest.approx(hi)
    assert a["nominal"] == pytest.approx(_built(graph).mean_availability())
    parts = fitted.uncertainty_importance(None, uncertainty)
    got = {r["id"]: r["first_order"] for r in out["shares"]}
    assert got == pytest.approx({"pa+pb": parts.first_order[("pa", "pb")], "motor": parts.first_order["motor"]})
    assert sum(got.values()) == pytest.approx(1.0)
    assert out["shares"][0]["first_order"] == max(got.values())
    assert [f["id"] for f in out["fixed"]] == ["strainer"]
    assert out["fixed"][0]["reason"] == "hand-entered parameters"
    assert out["answer"].startswith("The long-run availability is")


def test_uncertainty_sobol_and_several_times():
    graph = _train()
    out = rm.analyze_measure(graph, _resolver(MODELS), measure="uncertainty", method="sobol", times=[500, 5000])
    (fitted, uncertainty), _, _ = _fitted(graph)
    parts = fitted.uncertainty_importance(None, uncertainty, method="sobol", n_draws=rm.N_DRAWS_SOBOL, seed=rm.SEED,
                                          sampling="sobol")
    got = {r["id"]: (r["first_order"], r["total"]) for r in out["shares"]}
    assert got["motor"] == pytest.approx((parts.first_order["motor"], parts.total["motor"]))
    x = np.array([500.0, 5000.0])
    point = fitted.point_availability_uncertainty(x, uncertainty, n_draws=rm.N_DRAWS_OVER_TIME, seed=rm.SEED,
                                                  sampling="sobol")
    mission = fitted.mission_availability_uncertainty(x, uncertainty, n_draws=rm.N_DRAWS_OVER_TIME, seed=rm.SEED,
                                                      sampling="sobol")
    p_lo, p_hi = point.interval(0.95)
    m_lo, m_hi = mission.interval(0.95)
    for i, row in enumerate(out["at_times"]):
        assert row["t"] == x[i]
        assert row["availability"]["nominal"] == pytest.approx(point.nominal[i])
        assert (row["availability"]["lower"], row["availability"]["upper"]) == pytest.approx((p_lo[i], p_hi[i]))
        assert (row["mean_availability"]["lower"], row["mean_availability"]["upper"]) == pytest.approx(
            (m_lo[i], m_hi[i]))


def test_no_fitted_blocks_say_so():
    graph = _train()
    out = rm.analyze_measure(graph, None, measure="uncertainty")
    assert out["status"] == "no_uncertainty" and {f["id"] for f in out["fixed"]} == {"strainer", "pa", "pb", "motor"}
    # A block whose parameters no longer match its saved fit stays fixed.
    stale = _train()
    stale["nodes"][3]["data"]["model"]["params"][0]["value"] *= 1.1
    out = rm.analyze_measure(stale, _resolver(MODELS), measure="uncertainty")
    assert any(f["id"] == "pa" and "re-pick" in f["reason"] for f in out["fixed"])


def test_the_compute_request_carries_the_fits():
    graph = _train()
    opts = rm.options(measure="uncertainty", method="sobol")
    fits, fixed = rm.fits_for(graph, _resolver(MODELS))
    request = compute_core.measures_request(graph, fits, fixed, **opts)
    assert json.loads(json.dumps(request)) == request
    remote = compute_core.run("measures", request)
    local = rm.analyze_measure(graph, _resolver(MODELS), **opts)
    for out in (remote, local):
        out.pop("compute_seconds")
    assert remote == json.loads(json.dumps(local))


# ---- The app -------------------------------------------------------------------------------

def _post(client, graph, **body):
    return client.post("/api/rbds/measures", json={"graph": graph, **body})


def test_app_measures_are_free(client):
    client.act_as(FREE)
    for measure in ("over_time", "shares", "joint", "rate", "uncertainty"):
        r = _post(client, _train(), measure=measure)
        assert r.status_code == 200, r.text
        assert r.json()["measure"] == measure and r.json()["status"] in ("ok", "no_uncertainty")
    assert _post(client, _train(), measure="nope").status_code == 422
    assert _post(client, {**_train(), "repairable": False}, measure="joint").status_code == 422


def test_app_heavy_uncertainty_is_pro(client):
    client.act_as(FREE)
    body = _post(client, _train(), measure="uncertainty", method="sobol").json()
    assert body["status"] == "pro_required" and body["upgrade"] is True
    body = _post(client, _train(), measure="uncertainty", times=[100]).json()
    assert body["status"] == "pro_required"
    client.act_as(PRO)
    r = _post(client, _train(), measure="uncertainty", method="sobol")
    assert r.status_code == 200, r.text  # no queue configured: in-process
    assert r.json()["status"] == "no_uncertainty"  # hand-entered for this user: nothing saved


def test_app_heavy_uncertainty_runs_as_a_job(client, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import compute_app
    from backend.services import compute_queue
    from backend.services import models as models_service
    from backend.tests.test_compute_service import CALLBACK_URL, _configure, _fake_verify

    client.act_as(PRO)
    monkeypatch.setattr(models_service, "get_live_model", lambda session, mid, owners: {"model": MODELS[mid]})
    graph = _train()
    local = _post(client, graph, measure="uncertainty", method="sobol").json()  # no queue: in-process
    assert local["status"] == "ok"
    _configure(monkeypatch)
    tasks = []
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: tasks.append(
        json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request}))) or True)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)
    monkeypatch.setattr(compute_app, "_post", lambda url, payload, timeout: client.post(
        "/internal/compute/callback", json=payload, headers={"Authorization": "Bearer compute-token"}).status_code)
    r = _post(client, graph, measure="uncertainty", method="sobol")
    assert r.status_code == 202, r.text
    job_id = r.json()["job"]["job_id"]
    assert tasks[0]["kind"] == "measures" and set(tasks[0]["request"]["fits"]) == {"m1", "m2"}
    compute = TestClient(compute_app.app)
    assert compute.post("/compute/run", json={**tasks.pop(), "callback_url": CALLBACK_URL}).status_code == 200
    view = client.get(f"/api/rbd-jobs/{job_id}").json()
    assert view["status"] == "done" and view["kind"] == "measures"
    result = view["result"]
    for key in ("compute_seconds", "job_id"):
        result.pop(key, None), local.pop(key, None)
    assert result == local


# ---- MCP -----------------------------------------------------------------------------------

def test_mcp_rbd_sensitivity_measures(monkeypatch):
    import mongomock

    from backend import config, db
    from backend.services import rbds as rbds_service
    from backend.services import tokens
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_measures"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]
    rbd = rbds_service.save_rbd(test_db, "Train", _train(), A)
    for measure in ("over_time", "shares", "joint", "rate"):
        out = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "measure": measure}))
        assert out["available"] is True and out["measure"] == measure and out["answer"] and out["question"]
    over = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "measure": "over_time"}))
    assert len(over["time"]) <= 15 and all(len(s["values"]) == len(over["time"]) for s in over["series"])
    shares = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "measure": "shares", "group_by": "kind"}))
    assert {s["group"] for s in shares["shares"]} == {"Lives", "Repair times"}
    unc = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "measure": "uncertainty"}))
    assert unc["available"] is False and unc["code"] == "no_uncertainty" and unc["fixed_blocks"]
    # Lever limits through MCP (#324).
    limited = _ok(_call(token, "rbd_sensitivity", {
        "rbd_id": rbd.id, "lever_limits": {"motor|repairability.mu": {"min": 13.0}}, "limit": 30}))
    row = next(r for r in limited["levers"] if r["id"] == "motor|repairability.mu")
    assert row["limit"] == {"min": 13.0} and row["limited"] == "yours" and row["shown_to"] == pytest.approx(13.0)
    err = _call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "lever_limits": {"nope|x": {"min": 1}}})
    assert err.is_error and "not levers" in err.content[0].text
