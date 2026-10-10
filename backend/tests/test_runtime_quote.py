"""The runtime quote (#286): a log-normal AFT on replications, events per
replication and blocks, from the quote bench's pilot.

* The coefficients JSON is what SurPyval's LogNormalAFT gives on the pilot
  data (the bench's script reproduces it), and a quote's median and 90th
  percentile are that fitted model's own quantiles.
* The features are the bench's own (the same diagram gives the same n, e, b).
* The plan: fixed runs aren't capped, quick runs stop at their seconds, a
  run to the precision target at its time budget (a chosen window past it
  at the longer limit).
* "Every figure or none": no quote where a block's mean life isn't known.
* Calibration: the machine factor scales the quote, and its refit is
  SurPyval's log-normal on the logged ratios.
"""

import json
import math
from pathlib import Path

import mongomock
import numpy as np
import pytest
import surpyval as sv

from backend.services import runtime_quote as rq

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / "tools" / "quote_bench" / "data" / "pilot-dev-laptop.jsonl"
needs_pilot = pytest.mark.skipif(not PILOT.exists(), reason="the quote bench's pilot data isn't checked out")


def _graph(n_blocks=3, rate=0.001, repair=0.1):
    nodes = [{"id": "input", "type": "input", "data": {"label": "In"}},
             {"id": "output", "type": "output", "data": {"label": "Out"}}]
    edges = []
    prev = "input"
    for i in range(n_blocks):
        nid = f"b{i}"
        nodes.append({"id": nid, "type": "component", "data": {
            "label": nid,
            "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]},
            "repair": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": repair}]}}})
        edges.append({"source": prev, "target": nid})
        prev = nid
    edges.append({"source": prev, "target": "output"})
    return {"repairable": True, "unit": "hours", "nodes": nodes, "edges": edges}


@needs_pilot
def test_coefficients_are_the_pilot_fit():
    from tools.quote_bench import coefficients

    fitted = coefficients.fit(str(PILOT))
    c = rq.coefficients()
    assert fitted["intercept"] == c["intercept"] and fitted["sigma"] == c["sigma"]
    assert fitted["coefficients"] == c["coefficients"]
    assert c["coefficients"] == {"log_replications": 0.58, "log1p_events_per_replication": 0.571,
                                 "log_blocks": 0.245}
    assert c["fitted_on"]["points"] == 800 and c["fitted_on"]["censored"] == 4
    assert c["machine_factors"] == {"compute": 1.0, "web": 1.0}


@needs_pilot
def test_quote_is_surpyvals_lognormal_aft_quantiles():
    """The quote's median and 90th percentile are those of SurPyval's
    LogNormalAFT fitted to the pilot (the JSON's coefficients are it,
    rounded), for a fixed run of any size."""
    from tools.quote_bench import coefficients

    keep, x, c, Z = coefficients.load(str(PILOT))
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sv.LogNormalAFT.fit(x=x, Z=Z, c=c)
    for n, blocks in ((200, 3), (5000, 12), (40000, 40)):
        g = _graph(blocks)
        q = rq.quote_runtime(g, {"n_simulations": n, "t_simulation": 5000.0})
        f = rq.features(g, {"t_simulation": 5000.0})
        z = np.array([[math.log(n), math.log1p(f["events_per_replication"]), math.log(f["blocks"])]])
        med = float(np.asarray(model.qf(0.5, z)).reshape(-1)[0])
        p90 = float(np.asarray(model.qf(0.9, z)).reshape(-1)[0])
        assert q["mode"] == "fixed" and q["cap_s"] is None and q["replications"] == n
        assert q["median_s"] == pytest.approx(med, rel=0.02)
        assert q["p90_s"] == pytest.approx(p90, rel=0.02)
        # And exactly SurPyval's LogNormal at the linear predictor.
        d = sv.LogNormal.from_params([rq.log_median(n, f["events_per_replication"], f["blocks"]),
                                      rq.coefficients()["sigma"]])
        assert q["median_s"] == pytest.approx(float(d.qf(0.5)), rel=1e-12)
        assert q["p90_s"] == pytest.approx(float(d.qf(0.9)), rel=1e-12)


@needs_pilot
def test_features_are_the_benchs():
    from tools.quote_bench.generate import design

    rows = [json.loads(line) for line in PILOT.read_text().splitlines()[:25]]
    for r in rows:
        d = design(r["index"])
        f = rq.features(d["graph"], {"t_simulation": d["options"]["t_simulation"]})
        assert f["available"] and f["chosen_window"]
        assert f["blocks"] == r["features"]["n_blocks"]
        assert f["events_per_replication"] == pytest.approx(r["features"]["events_per_rep"], rel=1e-9)


def test_parallel_units_and_standby_spares_count():
    g = _graph(1)
    g["nodes"][2]["type"] = "parallel"
    g["nodes"][2]["data"]["n"] = 3
    one = rq.features(_graph(1), {"t_simulation": 1000.0})["events_per_replication"]
    assert rq.features(g, {"t_simulation": 1000.0})["events_per_replication"] == pytest.approx(3 * one)
    g["nodes"][2]["type"] = "standby"
    g["nodes"][2]["data"]["spares"] = 2
    assert rq.features(g, {"t_simulation": 1000.0})["events_per_replication"] == pytest.approx(3 * one)


def test_the_plan_caps_runs_at_their_time_limits(monkeypatch):
    from backend.services import rbd_analysis as ra

    g = _graph(5)
    quick = rq.quote_runtime(g, {"time_budget_s": 3.0, "max_replications": 2000})
    assert quick["mode"] == "quick" and quick["cap_s"] == 3.0 and quick["replications"] == 2000
    assert quick["p90_s"] <= 3.0
    full = rq.quote_runtime(g, {})
    assert full["mode"] == "tolerance" and full["replications"] == ra._AVAIL_SIMS
    assert full["cap_s"] == ra._AVAIL_TIME_BUDGET and full["p90_s"] <= ra._AVAIL_TIME_BUDGET
    # A huge chosen window: the floor of replications past the budget, up to the longer limit.
    huge = rq.quote_runtime(_graph(60, rate=0.05), {"t_simulation": 1e6})
    assert huge["replications"] == ra._AVAIL_MIN_SIMS and huge["cap_s"] == ra._AVAIL_USER_TIME_LIMIT
    assert ra._AVAIL_TIME_BUDGET < huge["median_s"] <= huge["p90_s"] <= ra._AVAIL_USER_TIME_LIMIT
    capped = rq.quote_runtime(_graph(60, rate=0.05), {"t_simulation": 1e6}, factor=50.0)
    assert capped["capped"] is True and capped["median_s"] == ra._AVAIL_USER_TIME_LIMIT
    assert capped["text"] == "about 3 minutes (its time limit)"


def test_every_figure_or_none():
    g = _graph(2)
    g["nodes"].append({"id": "s", "type": "subsystem", "data": {"label": "S", "rbd_id": "x"}})
    assert rq.quote_runtime(g)["available"] is False
    g = _graph(2)
    g["nodes"][2]["data"]["model"] = {"kind": "regression", "model_id": "m1"}
    out = rq.quote_runtime(g)
    assert out == {"available": False, "reason": rq.UNAVAILABLE_MEAN}
    assert rq.quote_runtime({"repairable": True, "nodes": [], "edges": []})["available"] is False


@pytest.mark.parametrize("median, p90, capped, text", [
    (0.4, 0.9, False, "under a second"),
    (0.4, 1.6, False, "under a second, up to 2 s"),
    (14.6, 40.2, False, "about 15 s, up to 40 s"),
    (70, 200, False, "about a minute, up to 3 minutes"),
    (20, 20, True, "about 20 s (its time limit)"),
    (5400, 9000, False, "about 1.5 hours, up to 2.5 hours"),
])
def test_quote_text(median, p90, capped, text):
    assert rq.quote_text(median, p90, capped) == text


def test_machine_factor_scales_the_quote_and_a_stored_refit_wins():
    db = mongomock.MongoClient()["rq"]
    g = _graph(4)
    base = rq.quote_runtime(g, {"n_simulations": 1000, "t_simulation": 2000.0})
    slow = rq.quote_runtime(g, {"n_simulations": 1000, "t_simulation": 2000.0}, factor=2.5)
    assert slow["median_s"] == pytest.approx(2.5 * base["median_s"])
    assert slow["p90_s"] == pytest.approx(2.5 * base["p90_s"])
    assert rq.current_factor(db, "compute") == 1.0
    db.runtime_quote_factors.insert_one({"_id": "compute", "factor": 1.7})
    assert rq.current_factor(db, "compute") == 1.7 and rq.current_factor(db, "web") == 1.0


def test_refit_is_surpyvals_lognormal_on_the_logged_ratios():
    db = mongomock.MongoClient()["rq"]
    g = _graph(4)
    opts = {"t_simulation": 2000.0}
    rng = np.random.default_rng(3)
    for i in range(6):
        assert rq.log_run(db, machine="compute", graph=g, options=opts, replications=1000, actual_s=1.0,
                          quote=None)
    few = rq.refit_factor(db, "compute")
    assert few["refitted"] is False and "at least 10" in few["reason"]
    db.rbd_runtime_log.delete_many({})
    reps = [500, 1000, 2000, 4000, 8000] * 6
    ratios = np.exp(math.log(2.0) + 0.5 * rng.standard_normal(len(reps)))
    for n, ratio in zip(reps, ratios):
        base = math.exp(rq.log_median(n, rq.features(g, opts)["events_per_replication"], 4))
        rq.log_run(db, machine="compute", graph=g, options=opts, replications=n, actual_s=base * ratio, quote=None)
    # One run cut off (right-censored) counts too.
    rq.log_run(db, machine="compute", graph=g, options=opts, replications=1000, actual_s=50.0, quote=None,
               censored=True)
    rows = list(db.rbd_runtime_log.find({}))
    x = np.array([r["actual_s"] / math.exp(r["log_median"]) for r in rows])
    c = np.array([1 if r["censored"] else 0 for r in rows])
    direct = sv.LogNormal.fit(x=x, c=c, fixed={"sigma": rq.coefficients()["sigma"]})
    out = rq.refit_factor(db, "compute")
    assert out["refitted"] and not out["applied"] and out["observed"] == 30
    assert out["factor"] == pytest.approx(float(direct.qf(0.5)), rel=1e-9)
    assert 1.5 < out["factor"] < 2.8
    assert rq.current_factor(db, "compute") == 1.0
    applied = rq.refit_factor(db, "compute", apply=True)
    assert applied["applied"] and rq.current_factor(db, "compute") == pytest.approx(out["factor"])
    # Nothing that identifies a user is logged.
    assert not {"uid", "rbd_id", "job_id", "graph"} & set(rows[0])


def test_refit_script(monkeypatch, capsys):
    from backend import db as db_module
    from backend.scripts import refit_runtime_factor

    db = mongomock.MongoClient()["rq_script"]
    monkeypatch.setattr(db_module, "_db", db)
    monkeypatch.setattr(db_module, "_simulated", True)
    assert refit_runtime_factor.main([]) == 0 and "No logged runs" in capsys.readouterr().out
    g = _graph(3)
    for i, n in enumerate([500, 1000, 2000, 4000] * 3):
        base = math.exp(rq.log_median(n, rq.features(g, {"t_simulation": 2000.0})["events_per_replication"], 3))
        ratio = 1.3 * (1.1 if i % 2 else 1 / 1.1)
        rq.log_run(db, machine="compute", graph=g, options={"t_simulation": 2000.0}, replications=n,
                   actual_s=ratio * base, quote={"median_s": base, "p90_s": 3 * base, "factor": 1.0})
    assert refit_runtime_factor.main([]) == 0
    out = capsys.readouterr().out
    assert "compute: 12 runs (12 observed), factor now 1" in out and "refit: 1.3 (dry run" in out
    assert "within the quoted ceiling 100%" in out
    assert refit_runtime_factor.main(["--apply"]) == 0 and "(stored)" in capsys.readouterr().out
    assert rq.current_factor(db, "compute") == pytest.approx(1.3)
