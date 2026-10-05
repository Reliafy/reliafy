"""Results say how they were computed with a stable, generic label (the fit
method, or "simulation"), never with an internal solver or engine identifier.

Here every SurPyval fit reports an arbitrary solver identifier, ``SOLVER``
(and the Weibull fit warns with it), and RePyability's ``analysis_routes()``
names ``ENGINE`` as the simulation engine of every route. Neither may reach
any response.
"""

import copy
import dataclasses
import json
import warnings

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.services import method_labels  # noqa: E402
from backend.services import rbd_analysis as ra  # noqa: E402
from backend.tests.test_availability_paid import PRO, _analyze, _save, client  # noqa: E402,F401 - fixture
from backend.tests.test_compute_service import _mcp_queue  # noqa: E402
from backend.tests.test_mcp import _ok  # noqa: E402
from backend.tests.test_mcp_plans import _call, _repairable, env  # noqa: E402,F401 - fixture
from backend.tests.test_mcp_plans import PRO as MCP_PRO  # noqa: E402
from backend.tests.test_public_rbd_links import _rbd_graph  # noqa: E402

SOLVER = "custom-solver (X)"
ENGINE = "custom"
TIMES = [120, 340, 510, 700, 980, 1200, 1500, 1800, 2100, 2600]
FLAGS = [0, 0, 1, 0, 0, 1, 0, 1, 0, 0]


def _text(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _csv() -> bytes:
    return ("t,c\n" + "".join(f"{t},{c}\n" for t, c in zip(TIMES, FLAGS))).encode()


# ---- Fits ------------------------------------------------------------------------

@pytest.fixture()
def custom_solver(monkeypatch):
    """Every distribution's fit reports ``SOLVER`` as its solver; the Weibull
    fit also warns that it stalled, naming it."""
    from backend import fitting

    done = set()
    for entry in fitting.DISTRIBUTIONS.values():
        dist = entry["dist"]
        if id(dist) in done:
            continue
        done.add(id(dist))

        def fit(*args, _real=dist.fit, _warn=dist is fitting.DISTRIBUTIONS["weibull"]["dist"], **kwargs):
            model = _real(*args, **kwargs)
            model.optimizer = SOLVER
            if _warn:
                warnings.warn(f"The fit did not reach a verified maximum of the likelihood: the search "
                              f"may have stalled ({SOLVER} stopped early).", UserWarning)
            return model

        monkeypatch.setattr(dist, "fit", fit)


@pytest.mark.parametrize("how, label", [(None, "MLE"), ("MPP", "MPP")])
def test_a_fit_reports_its_method_not_its_solver(custom_solver, how, label):
    from backend import fitting

    df = pd.DataFrame({"x": TIMES, "c": FLAGS})
    out = fitting.fit("weibull", df, {"x": "x", "c": "c"}, options={"how": how} if how else None)
    assert SOLVER not in _text(out)
    # The warning still says what happened, with the method in the solver's place.
    assert f"({label} stopped early)" in out["fit_warning"] and out["fit_ok"] is False
    # The live model (evaluated and saved later) carries the generic label too.
    live = fitting._MODEL_STORE[out["functions"]["model_id"]]["model"]
    assert live.optimizer == label


def test_best_fit_names_no_solver(custom_solver):
    from backend import fitting

    out = fitting.fit(fitting.BEST_ID, pd.DataFrame({"x": TIMES, "c": FLAGS}), {"x": "x", "c": "c"})
    assert out.get("selection") or out.get("candidates")
    assert SOLVER not in _text(out)


def test_the_app_fit_saved_model_and_share_page_name_no_solver(custom_solver, client):
    client.act_as(PRO)
    fit = client.post("/api/fit/weibull", data={"x": "t", "c": "c"}, files={"file": ("d.csv", _csv(), "text/csv")})
    assert fit.status_code == 200, fit.text
    saved = client.post("/api/models", data={"name": "Bearings", "distribution": "weibull", "x": "t", "c": "c"},
                        files={"file": ("d.csv", _csv(), "text/csv")})
    assert saved.status_code == 200, saved.text
    model_id = saved.json()["id"]
    got = client.get(f"/api/models/{model_id}")
    assert got.status_code == 200, got.text
    token = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id}).json()["token"]
    client.act_as(None)
    public = client.get(f"/api/public/{token}")
    assert public.status_code == 200, public.text
    for body in (fit.text, saved.text, got.text, public.text, _text(client.db.models.find_one({"_id": model_id}))):
        assert SOLVER not in body


def test_mcp_fit_tools_name_no_solver(custom_solver, env):
    token = env.oauth[MCP_PRO]
    fitted = _ok(_call(token, "fit_distribution", {"data": TIMES, "censored": FLAGS}))
    saved = _ok(_call(token, "fit_and_save_model", {"data": TIMES, "censored": FLAGS, "name": "Bearings"}))
    got = _ok(_call(token, "get_model", {"model_id": saved["model_id"]}))
    for out in (fitted, saved, got):
        assert SOLVER not in _text(out)


def test_note_fit_labels_a_models_parts_too():
    class Part:
        method, optimizer = "MLE", SOLVER

    class Mixture:
        method, optimizer = "EM", "another-solver"

        def __init__(self):
            self.models = [Part(), Part()]

    names = {}
    token = method_labels._seen.set(names)
    try:
        model = method_labels.note_fit(Mixture())
    finally:
        method_labels._seen.reset(token)
    assert model.optimizer == "EM" and [m.optimizer for m in model.models] == ["MLE", "MLE"]
    assert names == {"another-solver": "EM", SOLVER: "MLE"}
    # Numbers are untouched; only text and the internal fields change.
    assert method_labels.scrub({"a": [1.5, f"by {SOLVER}"], "optimizer": SOLVER}, names, {"optimizer": None}) \
        == {"a": [1.5, "by MLE"]}


# ---- Simulation engines -----------------------------------------------------------

@pytest.fixture()
def custom_engine(monkeypatch):
    """Every route of a repairable diagram names ``ENGINE`` as its engine, in
    the route and in its reason."""
    from repyability.rbd.repairable_rbd import RepairableRBD

    real = RepairableRBD.analysis_routes

    def analysis_routes(self, *args, **kwargs):
        return {key: dataclasses.replace(r, engine=ENGINE, engine_reason=f"the {ENGINE} engine is fastest",
                                         reason=f"{r.reason} Simulated on the {ENGINE} engine.")
                for key, r in real(self, *args, **kwargs).items()}

    monkeypatch.setattr(RepairableRBD, "analysis_routes", analysis_routes)


def test_the_route_report_reaches_the_analysis_without_its_engine(custom_engine):
    graph = _rbd_graph(repairable=True)
    rbd, *_ = ra._build_repairable_rbd(graph)
    assert ENGINE in str(rbd.analysis_routes()["availability"])  # the stand-in is in place
    exact = ra.exact_availability(graph)
    assert exact["routes"] and ENGINE not in _text(exact)
    assert "Simulated on the simulation engine." in _text(exact)
    assert ENGINE not in _text(ra._availability_routes(graph))
    full = ra.analyze_availability(copy.deepcopy(graph), n_simulations=20)
    assert ENGINE not in _text(full)


def test_the_app_analysis_and_share_page_name_no_engine(custom_engine, client):
    client.act_as(PRO)
    graph = _rbd_graph(repairable=True)
    rbd_id = _save(client, graph)
    r = _analyze(client, graph, rbd_id=rbd_id)
    assert r.status_code == 200, r.text
    assert r.json()["has_simulation"] is True and r.json()["exact"]["routes"]
    token = client.post("/api/public-links", json={"collection": "rbds", "artifact_id": rbd_id}).json()["token"]
    client.act_as(None)
    public = client.get(f"/api/public/{token}")
    assert public.status_code == 200 and public.json()["artifact"]["analysis"]
    for body in (r.text, public.text):
        assert ENGINE not in body


def test_mcp_analyze_rbd_and_get_job_name_no_engine(custom_engine, env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MCP_JOB_WAIT_S", 0.2)
    tasks, dispatch = _mcp_queue(env, monkeypatch)
    token = env.oauth[MCP_PRO]
    rid = _repairable(env, MCP_PRO, "Pumps")
    # Every figure here is exact: the simulation runs on request (#262).
    queued = _ok(_call(token, "analyze_rbd", {"rbd_id": rid, "simulate": True}))
    job_id = queued["simulation"]["job_id"]
    assert len(tasks) == 1 and ENGINE not in _text(tasks)  # what goes to the compute service
    dispatch()
    done = _ok(_call(token, "get_job", {"job_id": job_id}))
    assert done["status"] == "done" and done["simulation"]["available"] is True
    stored = env.db.rbd_jobs.find_one({"_id": job_id})
    again = _ok(_call(token, "analyze_rbd", {"rbd_id": rid}))
    for out in (queued, done, stored, again):
        assert ENGINE not in _text(out)


def test_engine_fields_and_registered_engine_names_are_made_generic(monkeypatch):
    from repyability.rbd import engines

    monkeypatch.setattr(engines, "registered", lambda: {"turbo-x": object()})
    assert ra.plain_reason("Runs on turbo-x, like Python.") == "Runs on simulation, like Python."
    saved = {"exact": {"routes": {"availability": {"route": "simulated", "reason": "turbo-x it is.",
                                                   "engine": "turbo-x", "engine_reason": "fastest"}}},
             "precision": {"engine": "turbo-x", "n_simulations": 20}}
    out = ra.plain_reasons(saved)
    assert out["exact"]["routes"]["availability"] == {"route": "simulated", "reason": "simulation it is.",
                                                      "engine": "simulation"}
    assert out["precision"] == {"engine": "simulation", "n_simulations": 20}
    # The plain engine's name is an ordinary word: left alone in text.
    assert method_labels.hide_engine_names("Download as Python.", "python") == "Download as Python."
