"""#104: the availability simulation runs to a precision target (antithetic
pairs, bounded by the time budget), and two repairable designs can be compared
with common random numbers."""

import copy
import json

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services import rbd_compare
from backend.tests.test_availability_paid import BUYER, FREE, PRO, client  # noqa: F401 - fixture
from backend.tests.test_rbd_analysis import (
    _edge, _io_nodes, _repairable_component, _series_repairable_graph,
)


def _pumps(mttr_mu_b: float = 2.0):
    """A controller in series with two redundant pumps; ``mttr_mu_b`` is the
    lognormal mu of pump B's repair time."""
    return {
        "unit": "hours",
        "repairable": True,
        "nodes": _io_nodes() + [
            _repairable_component("ctrl", "Controller", 2000, 1.6, 2.0),
            _repairable_component("pumpA", "Pump A", 900, 1.4, 2.3),
            _repairable_component("pumpB", "Pump B", 900, 1.4, mttr_mu_b),
        ],
        "edges": [_edge("input", "ctrl"), _edge("ctrl", "pumpA"), _edge("ctrl", "pumpB"),
                  _edge("pumpA", "output"), _edge("pumpB", "output")],
    }


# ---- tolerance --------------------------------------------------------------

def test_tolerance_is_relative_to_the_unavailability():
    assert ra._availability_tolerance(1e-4) == pytest.approx(5e-6)
    assert ra._availability_tolerance(0.01) == pytest.approx(5e-4)
    # Never looser than 0.1 percentage point...
    assert ra._availability_tolerance(0.3) == pytest.approx(1e-3)
    # ...and for a system that is mostly down, relative to its availability.
    assert ra._availability_tolerance(0.99995) == pytest.approx(0.05 * 5e-5)
    # A system that never goes down meets any positive target at once.
    assert 0 < ra._availability_tolerance(0.0) <= 1e-12
    assert ra._availability_tolerance(float("nan")) == ra._AVAIL_MAX_TOLERANCE


def test_plan_turns_the_budget_into_whole_batches(monkeypatch):
    monkeypatch.setattr(ra, "_AVAIL_BATCH", 100)
    monkeypatch.setattr(ra, "_AVAIL_TIME_BUDGET", 10.0)
    # 1 ms per replication: 10 000 fit, capped at n_max, in whole batches.
    assert ra._plan_simulation(1e-3, 20_000, 50.0, False) == (100, 10_000, 50.0, False)
    assert ra._plan_simulation(1e-3, 2_550, 50.0, False) == (100, 2_500, 50.0, False)
    # Slow: fewer than a batch fit — the limit is the batch.
    assert ra._plan_simulation(0.05, 20_000, 50.0, False) == (100, 200, 50.0, False)
    # Even the floor won't fit: a default horizon shortens, a chosen one doesn't.
    batch, max_n, t, short = ra._plan_simulation(1.0, 20_000, 50.0, False)
    assert (batch, max_n, short) == (100, 100, True) and t == pytest.approx(5.0)
    assert ra._plan_simulation(1.0, 20_000, 50.0, True) == (100, 100, 50.0, False)


# ---- the availability simulation -------------------------------------------

def test_run_reaches_the_precision_target_and_reports_it():
    res = ra.analyze_availability(_series_repairable_graph())
    prec = res["precision"]
    assert prec["mode"] == "tolerance" and prec["antithetic"] is True
    assert prec["reached"] is True
    assert prec["tolerance"] == pytest.approx(ra._availability_tolerance(res["unavailability"]))
    assert prec["half_width"] <= prec["tolerance"]
    assert prec["lower"] <= prec["window_availability"] <= prec["upper"]
    assert prec["n_simulations"] == res["n_simulations"]
    assert res["n_simulations"] % ra._AVAIL_BATCH == 0  # whole batches
    # The window starts all-up, so its mean is close to (a touch above) the
    # long-run availability.
    assert prec["window_availability"] == pytest.approx(res["steady_state_availability"], abs=5e-3)
    json.dumps(res)


def test_run_stops_at_the_limit_when_the_target_is_out_of_reach(monkeypatch):
    monkeypatch.setattr(ra, "_AVAIL_BATCH", 40)
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 120)
    monkeypatch.setattr(ra, "_AVAIL_REL_TOLERANCE", 1e-6)  # unreachable
    res = ra.analyze_availability(_series_repairable_graph())
    prec = res["precision"]
    assert res["n_simulations"] == prec["max_simulations"] == 120
    assert prec["reached"] is False and prec["half_width"] > prec["tolerance"]


def test_stopped_run_equals_a_fixed_run_of_that_many():
    """RePyability: without n_jobs, a run that stops after n simulations gives
    the result of a run of mc_samples=n — so the budget-derived limit never changes a
    result that reached its target."""
    graph = _series_repairable_graph()
    run = ra.analyze_availability(graph)
    fixed = ra.analyze_availability(graph, n_simulations=run["n_simulations"])
    for key in ("window_availability", "lower", "upper", "standard_error"):
        assert fixed["precision"][key] == run["precision"][key]
    assert fixed["simulated"] == run["simulated"]
    assert fixed["curve"] == run["curve"]


def test_same_graph_same_result():
    graph = _series_repairable_graph()
    one, two = ra.analyze_availability(graph), ra.analyze_availability(copy.deepcopy(graph))
    # The limit comes from a timing; everything else is seeded.
    one["precision"].pop("max_simulations")
    two["precision"].pop("max_simulations")
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


def test_a_first_batch_without_downtime_is_not_taken_as_precise(monkeypatch):
    """A highly available system whose first batch never goes down has a
    zero-width interval; that's no evidence, so the run carries on to its
    limit (and doesn't claim the target unless it then sees downtime)."""
    monkeypatch.setattr(ra, "_AVAIL_BATCH", 20)
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 60)
    graph = _series_repairable_graph()
    res = ra.analyze_availability(graph, t_simulation=1.0)  # far too short to fail
    prec = res["precision"]
    assert res["n_simulations"] == 60
    assert prec["standard_error"] == 0.0 and prec["reached"] is False


def test_fixed_count_reports_precision_without_a_limit():
    res = ra.analyze_availability(_series_repairable_graph(), n_simulations=40)
    prec = res["precision"]
    assert res["n_simulations"] == 40
    assert prec["mode"] == "fixed" and prec["max_simulations"] is None
    assert prec["antithetic"] is True


# ---- comparing two designs ---------------------------------------------------

def test_faster_repair_is_more_available_with_a_tight_interval():
    """Two designs that differ only in pump B's repair time: B (faster repair)
    is more available; the simulated difference has the exact difference's
    sign and its interval excludes zero."""
    slow, fast = _pumps(3.0), _pumps(1.0)
    res = rbd_compare.compare_availability(slow, fast)
    d = res["differences"]["availability"]
    assert res["common_random_numbers"] is True and res["shared_blocks"] == 3
    assert d["exact"] > 0
    assert d["estimate"] > 0 and d["lower"] > 0
    assert d["verdict"] == "b_higher"
    assert d["lower"] <= d["estimate"] <= d["upper"]
    assert res["designs"]["b"]["steady_state_availability"] > res["designs"]["a"]["steady_state_availability"]
    # Swapped, the sign flips.
    back = rbd_compare.compare_availability(fast, slow)["differences"]["availability"]
    assert back["verdict"] == "a_higher" and back["upper"] < 0
    json.dumps(res)


def test_common_random_numbers_beat_independent_runs():
    slow, fast = _pumps(3.0), _pumps(1.0)
    a, b = rbd_compare._design(slow, None), rbd_compare._design(fast, None)
    t = ra._availability_horizon(slow)
    paired = rbd_compare._difference(*rbd_compare._batch(a, b, t, 200, 0, True), True)
    indep = rbd_compare._difference(*rbd_compare._batch(a, b, t, 200, 0, False), False)
    assert paired[1] < indep[1] / 2


def test_identical_designs_show_no_difference():
    res = rbd_compare.compare_availability(_pumps(), _pumps())
    d = res["differences"]["availability"]
    assert d["estimate"] == 0.0 and d["exact"] == 0.0
    assert d["verdict"] == "no_detectable_difference" and d["reached"] is True


def test_paired_run_is_repyabilitys_compare():
    """Our paired run (which honours pins) is RePyability's compare when
    nothing is pinned — guards the private API it leans on."""
    a = rbd_compare._design(_pumps(3.0), None)
    b = rbd_compare._design(_pumps(1.0), None)
    t = 5000.0
    key = rbd_compare._key(7)
    widths = rbd_compare._common_widths(b, a, t)
    ours = np.mean(rbd_compare._paired_fractions(b, t, 60, key, widths)
                   - rbd_compare._paired_fractions(a, t, 60, key, widths))
    theirs = b["rbd"].compare(a["rbd"], t, mc_samples=60, seed=7)
    assert ours == pytest.approx(theirs.estimate, abs=1e-12)


def test_compare_is_deterministic_and_honours_a_fixed_count():
    one = rbd_compare.compare_availability(_pumps(3.0), _pumps(1.0), n_simulations=40)
    two = rbd_compare.compare_availability(_pumps(3.0), _pumps(1.0), n_simulations=40)
    assert one["n_simulations"] == 40 and one["max_simulations"] is None
    assert one["differences"] == two["differences"]


def test_compare_refuses_non_repairable_diagrams():
    other = _pumps()
    other["repairable"] = False
    with pytest.raises(ra.AnalysisError):
        rbd_compare.compare_availability(_pumps(), other)


# ---- the endpoint ------------------------------------------------------------

def test_compare_endpoint_with_a_saved_diagram(client):
    client.act_as(PRO)
    saved = client.post("/api/rbds", json={"name": "Slow repair", "graph": _pumps(3.0)}).json()
    res = client.post("/api/rbds/compare", json={
        "graph": _pumps(1.0), "name": "Fast repair", "other_id": saved["id"],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["designs"]["a"]["name"] == "Fast repair"
    assert body["designs"]["b"]["name"] == "Slow repair"
    d = body["differences"]["availability"]
    assert d["exact"] < 0 and d["lower"] <= d["estimate"] <= d["upper"]
    # The picker lists which saved diagrams are repairable.
    listed = {r["id"]: r for r in client.get("/api/rbds").json()["rbds"]}
    assert listed[saved["id"]]["repairable"] is True

    missing = client.post("/api/rbds/compare", json={"graph": _pumps(), "other_id": "nope"})
    assert missing.status_code == 404
    nothing = client.post("/api/rbds/compare", json={"graph": _pumps()})
    assert nothing.status_code == 422
    # Someone else's diagram can't be read, so it can't be compared with.
    client.act_as(BUYER)
    other = client.post("/api/rbds/compare", json={"graph": _pumps(), "other_id": saved["id"]})
    assert other.status_code == 404


def test_sample_result_saved_before_the_precision_report_is_reseeded(client):
    """Saved results keep their cache key (they're still valid estimates), but
    the showcase sample is re-seeded once to show the precision report."""
    from backend.services import samples

    samples.seed_samples(client.db)
    assert client.sims["n"] == 1
    sample_id = "sample-rbd-instrument-air-availability"
    assert "precision" in client.db.rbds.find_one({"_id": sample_id})["availability_cache"]["result"]
    client.db.rbds.update_one({"_id": sample_id}, {"$unset": {"availability_cache.result.precision": ""}})
    samples.seed_samples(client.db)
    assert client.sims["n"] == 2
    assert "precision" in client.db.rbds.find_one({"_id": sample_id})["availability_cache"]["result"]
    samples.seed_samples(client.db)
    assert client.sims["n"] == 2


def test_compare_endpoint_is_paid(client):
    client.act_as(FREE)
    res = client.post("/api/rbds/compare", json={"graph": _pumps(), "other_graph": _pumps(1.0)})
    assert res.status_code == 402 and res.json()["code"] == "pro_required"
