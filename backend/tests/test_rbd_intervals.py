"""Maintenance and proof-test intervals chosen together (#172, #228): the
diagram's repair crews (``assume_unlimited_crews``, then the plan simulated
with them) and staggered tests (``offsets="stagger"``) on RePyability 0.12's
``optimal_replacement_intervals`` / ``optimal_inspection_intervals``.

Checked against RePyability directly (the same choice and figures, its own
documented examples), the applied diagram against the plan (in the app's
analysis and in Download as Python), and through the app, the queue and MCP."""

import json
import math

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import BetaFactor, CCFGroup, RepairableRBD  # noqa: E402

from backend.services import compute_core, rbd_export  # noqa: E402
from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_intervals as ri  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_availability_paid import FREE, PRO, client  # noqa: E402,F401 - fixture
from backend.tests.test_rbd_costs import _exp, _io, _ln, _node, _series, _w  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

E = sv.Exponential.from_params
CAL = [730.0, 2190.0, 4380.0, 8760.0, 17520.0]
PAR = [("s", "v1"), ("s", "v2"), ("v1", "t"), ("v2", "t")]


def _parallel(*nodes, **graph):
    edges = []
    for n in nodes:
        edges += [{"source": "input", "target": n["id"]}, {"source": n["id"], "target": "output"}]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes], "edges": edges, **graph}


def _valve(nid, **test):
    """RePyability's shutdown valve: hidden failures at 2e-6 /h, a 500 test."""
    return _node(nid, model=_exp(2e-6), instant_repair=True, inspection={"interval": 8760, "cost": 500, **test})


def _valve_spec():
    return {"reliability": E([2e-6]), "repairability": "instant", "inspection": {"interval": 8760.0, "cost": 500.0}}


def _sif(beta=0.1, **graph):
    ccf = [{"id": "c", "members": ["v1", "v2"], "beta": beta}] if beta else []
    return _parallel(_valve("v1"), _valve("v2"), safety_function=True, ccf_groups=ccf, **graph)


def _direct_sif(**kw):
    return RepairableRBD(PAR, {"v1": _valve_spec(), "v2": _valve_spec()}, input_node="s", output_node="t",
                         ccf_groups=[CCFGroup(["v1", "v2"], BetaFactor(0.1))], **kw)


def _pump(nid, x=0):
    """RePyability's wear-out pump: Weibull(1000, 2.5), lognormal repairs,
    5000 a failure, age replacement at 1000 h for 1000 (Weibull(8, 3) h)."""
    return _node(nid, x, model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 5000},
                 preventive={"policy": "age", "interval": 1000, "cost": 1000, "duration": _w(8, 3)})


def _pump_spec():
    return {"reliability": sv.Weibull.from_params([1000, 2.5]), "repairability": sv.LogNormal.from_params([3.0, 0.5]),
            "replace_cost": 5000.0, "preventive": {"interval": 1000.0, "cost": 1000.0,
                                                   "duration": sv.Weibull.from_params([8, 3])}}


def _plant(**graph):
    """A pump alone in the line, then two in parallel; 500 an hour down."""
    nodes = [_pump("a", 200), _pump("b1", 400), _pump("b2", 400)]
    edges = [("input", "a"), ("a", "b1"), ("a", "b2"), ("b1", "output"), ("b2", "output")]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
            "edges": [{"source": s, "target": t} for s, t in edges], "costs": {"downtime_rate": 500}, **graph}


def _direct_plant(**kw):
    edges = [("s", "a"), ("a", "b1"), ("a", "b2"), ("b1", "t"), ("b2", "t")]
    return RepairableRBD(edges, {n: _pump_spec() for n in ("a", "b1", "b2")}, input_node="s", output_node="t",
                         downtime_cost_rate=500.0, **kw)


def _rows(out):
    return {r["id"]: r for r in out["blocks"]}


# ---------------------------------------------------------------------------
# Staggered proof tests (#228): RePyability's own 1oo2 with a 10% common cause
# ---------------------------------------------------------------------------
def test_staggered_tests_match_repyability_and_halve_the_cost():
    out = ri.optimise(_sif(), max_pfd=5e-4, allowed=CAL, stagger=True)
    direct = _direct_sif()
    staggered = direct.optimal_inspection_intervals(allowed=CAL, min_availability=1 - 5e-4, offsets="stagger")
    together = direct.optimal_inspection_intervals(allowed=CAL, min_availability=1 - 5e-4, offsets=[0.0])
    rows = _rows(out)
    assert {n: rows[n]["interval"] for n in rows} == staggered.intervals == {"v1": 8760.0, "v2": 8760.0}
    assert {n: rows[n]["offset"] for n in rows} == staggered.offsets == {"v1": 0.0, "v2": 4380.0}
    assert out["plan"]["pfd_avg"] == pytest.approx(1 - staggered.availability, rel=1e-12)
    assert out["plan"]["pfd_avg"] == pytest.approx(0.0004925, abs=5e-8)
    assert out["plan"]["cost_rate"] == pytest.approx(staggered.cost_rate, rel=1e-12)
    assert out["plan"]["sil"] == 3 and out["plan"]["meets_target"] is True
    # The best with both tested at once: one valve twice a year, and a third
    # dearer. The valves are identical, so which one is a tie that the
    # platform's floating point breaks (v2 on macOS, v1 on Linux CI).
    t = out["together"]
    assert t["met"] is True and {r["id"]: r["interval"] for r in t["blocks"]} == together.intervals
    assert sorted(together.intervals.values()) == [4380.0, 8760.0]
    assert t["cost_rate"] == pytest.approx(together.cost_rate, rel=1e-12)
    assert out["plan"]["cost_rate"] < 0.7 * t["cost_rate"]
    # As drawn (yearly, together) misses the target; the groups are in the PFDavg.
    assert out["current"]["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    assert out["current"]["meets_target"] is False
    assert out["common_cause"] == {"groups": 1, "included": True, "note": None}
    assert out["stagger"] is True and out["changed"] is True and out["basis"] == "exact"


def test_tests_together_by_default_keep_their_offsets():
    out = ri.optimise(_sif(), max_pfd=5e-4, allowed=CAL)
    direct = _direct_sif().optimal_inspection_intervals(allowed=CAL, min_availability=1 - 5e-4)
    assert {r["id"]: r["interval"] for r in out["blocks"]} == direct.intervals
    assert all(r["offset"] == 0.0 for r in out["blocks"]) and out["together"] is None
    # A first test already staggered keeps its share of the interval.
    g = _sif()
    g["nodes"][3]["data"]["inspection"]["offset"] = 4380
    out = ri.optimise(g, allowed=CAL)
    v2 = _rows(out)["v2"]
    assert v2["offset"] == pytest.approx(v2["interval"] / 2)


def test_target_sil_and_the_default_calendar():
    out = ri.optimise(_sif(), target_sil=3)
    assert out["target"] == {"type": "target_sil", "sil": 3, "max_pfd": 1e-3}
    assert out["plan"]["pfd_avg"] < 1e-3 and out["plan"]["sil"] >= 3
    # Monthly to four-yearly in hours, plus each block's own interval.
    assert out["allowed"]["v1"] == [730.0, 2190.0, 4380.0, 8760.0, 17520.0, 26280.0, 35040.0]
    assert ri.calendar({"unit": "days"})[3] == 365.0 and ri.calendar({"unit": "cycles"}) is None


def test_staggering_can_be_the_only_way_to_the_target():
    """Yearly tests only: half a year apart they reach a PFDavg that at the
    same time they can't. The result says so."""
    allowed = [8760.0]
    direct = _direct_sif()
    staggered = direct.optimal_inspection_intervals(allowed=allowed, offsets="stagger")
    assert staggered.offsets == {"v1": 0.0, "v2": 4380.0}  # same cost: the most available
    target = ((1 - staggered.availability) + direct.mean_unavailability()) / 2
    with pytest.raises(ValueError, match="cannot be met"):
        direct.optimal_inspection_intervals(allowed=allowed, min_availability=1 - target, offsets=[0.0])
    out = ri.optimise(_sif(), max_pfd=target, allowed=allowed, stagger=True)
    assert out["plan"]["meets_target"] is True
    assert out["plan"]["pfd_avg"] == pytest.approx(1 - staggered.availability, rel=1e-12)
    assert out["together"]["met"] is False and "PFDavg of at most" in out["together"]["message"]
    assert "stagger the tests" in out["together"]["message"]


def test_common_cause_left_out_when_the_chain_cannot_take_it():
    g = _sif()
    for n in g["nodes"][2:]:
        n["data"]["model"] = _w(500000, 1.5)
    out = ri.optimise(g, allowed=CAL)
    assert out["common_cause"]["included"] is False and "exponential" in out["common_cause"]["note"]
    # Not a safety function: the groups are in the long run the intervals are
    # chosen by all the same (#226).
    out = ri.optimise({**_sif(), "safety_function": False}, allowed=CAL)
    assert out["common_cause"] == {"groups": 1, "included": True, "note": None}
    assert "pfd_avg" not in out["plan"]
    assert out["plan"]["availability"] == pytest.approx(
        _direct_sif().with_intervals(out["intervals"] if "intervals" in out else
                                     {r["id"]: r["interval"] for r in out["blocks"]}).mean_availability(),
        rel=1e-12)


# ---------------------------------------------------------------------------
# Replacement intervals, and limited repair crews (#228)
# ---------------------------------------------------------------------------
def test_replacement_intervals_match_repyability():
    out = ri.optimise(_plant())
    plan = _direct_plant().optimal_replacement_intervals()
    rows = _rows(out)
    for node, t in plan.intervals.items():
        assert rows[node]["interval"] == float(f"{t:.4g}")  # four significant figures on the canvas
    assert {n: round(r["interval"]) for n, r in rows.items()} == {"a": 590, "b1": 497, "b2": 497}
    # The figures are the rounded plan's, exactly; the rounding costs next to nothing.
    rounded = _direct_plant().with_intervals({n: r["interval"] for n, r in rows.items()})
    assert out["plan"]["cost_rate"] == pytest.approx(rounded.expected_cost_rate(), rel=1e-12)
    assert out["plan"]["availability"] == pytest.approx(rounded.mean_availability(), rel=1e-12)
    assert out["plan"]["cost_rate"] == pytest.approx(plan.cost_rate, rel=1e-5)
    assert out["current"]["cost_rate"] > out["plan"]["cost_rate"]
    assert out["schedule"] == "replacement" and out["basis"] == "numerical" and out["crews"] is None


def test_limited_crews_need_the_assumption_and_say_so():
    g = _plant(repair_crews={"crews": 1})
    out = ri.optimise(g)
    assert out["status"] == "crews_limited" and out["crews"]["waits"] is True
    assert "assume_unlimited_crews" in out["message"] and "1 repair crew for 3 repair jobs" in out["message"]
    with pytest.raises(NotImplementedError, match="assume_unlimited_crews"):
        _direct_plant(repair_crews=1).optimal_replacement_intervals()
    out = ri.optimise(g, assume_unlimited_crews=True)
    plan = _direct_plant(repair_crews=1).optimal_replacement_intervals(assume_unlimited_crews=True)
    assert {n: r["interval"] for n, r in _rows(out).items()} == {n: float(f"{t:.4g}") for n, t in plan.intervals.items()}
    assert out["crews"]["assumed_unlimited"] is True and out["crews"]["crews"] == 1
    # As drawn and the plan, both as if no repair waits.
    assert out["current"]["cost_rate"] == pytest.approx(_direct_plant().expected_cost_rate(), rel=1e-12)
    # Enough crews: nothing waits, nothing to assume.
    assert ri.optimise(_plant(repair_crews={"crews": 3}))["crews"]["waits"] is False


def test_the_plan_with_the_crews_is_simulated_on_the_applied_diagram():
    """What the waiting costs: the diagram with the plan on it, simulated with
    its one crew, against RePyability's with_intervals on the same seed."""
    g = _plant(repair_crews={"crews": 1})
    out = ri.optimise(g, assume_unlimited_crews=True)
    applied = ri.apply_plan(g, out["blocks"])
    sim = ra.analyze_availability(applied, n_simulations=200)
    assert sim["steady_state_availability"] is None  # no exact long run with crews and maintenance
    assert sim["precision"]["window_availability"] < 1
    rbd = ra._build_repairable_rbd(applied)[0]
    direct = _direct_plant(repair_crews=1).with_intervals({n: r["interval"] for n, r in _rows(out).items()})
    assert rbd.repair_crews == 1
    for node in ("a", "b1", "b2"):
        assert rbd._preventive[node].interval == direct._preventive[node].interval


def test_apply_plan_writes_intervals_offsets_and_never():
    g = _sif()
    out = ri.optimise(g, max_pfd=5e-4, allowed=CAL, stagger=True)
    applied = ri.apply_plan(g, out["blocks"])
    tests = {n["id"]: n["data"]["inspection"] for n in applied["nodes"] if n["type"] == "component"}
    assert tests["v1"] == {"interval": 8760.0, "cost": 500}
    assert tests["v2"] == {"interval": 8760.0, "cost": 500, "offset": 4380.0}
    assert g["nodes"][3]["data"]["inspection"] == {"interval": 8760, "cost": 500}  # unchanged
    rows = [{"id": "a", "never": True, "interval": None, "changed": True}]
    assert "preventive" not in next(n for n in ri.apply_plan(_plant(), rows)["nodes"] if n["id"] == "a")["data"]


def test_the_applied_diagram_and_its_python_export_give_the_plans_figures(tmp_path):
    g = _sif()
    out = ri.optimise(g, max_pfd=5e-4, allowed=CAL, stagger=True)
    applied = ri.apply_plan(g, out["blocks"])
    app = ra.analyze_availability(applied, n_simulations=60)
    assert app["safety"]["pfd_avg"] == pytest.approx(out["plan"]["pfd_avg"], rel=1e-12)
    assert app["costs"]["cost_rate"] == pytest.approx(out["plan"]["cost_rate"], rel=1e-12)
    code = rbd_export.to_python(applied, "SIF", exported_at=WHEN)
    res, _ = _run(code, tmp_path, n_sims="60")
    assert res["safety"]["pfd_avg"] == pytest.approx(out["plan"]["pfd_avg"], rel=1e-12)
    assert res["costs"]["cost_rate"] == pytest.approx(out["plan"]["cost_rate"], rel=1e-12)
    # And the replacement plan: the export's exact figures are the plan's.
    plant = ri.optimise(_plant())
    applied = ri.apply_plan(_plant(), plant["blocks"])
    res, _ = _run(rbd_export.to_python(applied, "Plant", exported_at=WHEN), tmp_path, name="plant.py", n_sims="60")
    assert res["steady_state_availability"] == pytest.approx(plant["plan"]["availability"], rel=1e-12)
    assert res["costs"]["cost_rate"] == pytest.approx(plant["plan"]["cost_rate"], rel=1e-12)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("graph, kw, needle", [
    ({**_plant(), "repairable": False}, {}, "repairable"),
    (_series(_node("p", model=_exp(1e-3), repair=_exp(0.1))), {}, "No block has scheduled replacement"),
    (_plant(), {"min_availability": 0.9, "max_cost_rate": 10}, "Give one target"),
    (_plant(), {"target_sil": 5}, "1, 2, 3 or 4"),
    (_plant(), {"schedule": "proof_test"}, "No block has proof tests"),
    (_plant(), {"blocks": ["zz"]}, "aren't under age replacement"),
    (_sif(), {"max_pfd": 1e-7, "allowed": CAL}, "lowest they give is"),
    (_sif(), {"allowed": [-1]}, "positive"),
    ({**_sif(), "unit": "cycles"}, {}, "Give the intervals to choose from"),
    (_parallel(_node("v1", model=_exp(2e-6), instant_repair=True, inspection={"interval": 8760}),
               _node("v2", model=_exp(2e-6), instant_repair=True, inspection={"interval": 8760})),
     {}, "Nothing is priced"),
])
def test_errors_are_plain(graph, kw, needle):
    with pytest.raises(AnalysisError, match=needle):
        ri.optimise(graph, **kw)


def test_size_limits_and_both_schedules(monkeypatch):
    g = _plant()
    g["nodes"].append(_valve("v"))
    g["edges"] += [{"source": "input", "target": "v"}, {"source": "v", "target": "output"}]
    with pytest.raises(AnalysisError, match="say which"):
        ri.optimise(g)
    assert ri.optimise(g, schedule="replacement")["schedule"] == "replacement"
    monkeypatch.setattr(ri, "MAX_REPLACED", 2)
    with pytest.raises(AnalysisError, match="at most 2 blocks"):
        ri.optimise(_plant())
    with pytest.raises(AnalysisError, match="at most 8 intervals"):
        ri.options(allowed=list(range(1, 10)))


def test_plan_says_when_a_search_is_a_job():
    two = ri.plan(_sif(), stagger=True, allowed=CAL)
    assert two["inline"] is True and two["evaluations"] == 25 * 2 + 25
    nodes = [_valve(f"v{i}") for i in range(4)]
    four = ri.plan(_parallel(*nodes), stagger=True)
    assert four["inline"] is False and four["n_blocks"] == 4
    assert ri.plan(_plant())["inline"] is True


# ---------------------------------------------------------------------------
# The compute service, the app and MCP
# ---------------------------------------------------------------------------
def test_the_compute_service_gives_the_in_process_answer():
    graph = _sif()
    graph["nodes"][-1]["position"] = {"x": 5, "y": 5}
    opts = {"max_pfd": 5e-4, "allowed": CAL, "stagger": True}
    request = json.loads(json.dumps(compute_core.intervals_request(graph, **opts)))
    remote = compute_core.run("intervals", request)
    local = compute_core.to_wire(ri.optimise(graph, **opts))
    assert remote == local and remote["plan"]["pfd_avg"] == pytest.approx(0.0004925, abs=5e-8)
    assert "intervals" in compute_core.KINDS
    with pytest.raises(compute_core.InvalidRequest, match="Unknown options"):
        compute_core.run_intervals({**request, "options": {"bogus": 1}})


def _post(client, graph, **body):
    return client.post("/api/rbds/intervals", json={"graph": graph, **body})


def test_app_is_free_and_answers_at_once(client):
    client.act_as(FREE)
    r = _post(client, _sif(), schedule="proof_test", max_pfd=5e-4, allowed=CAL, stagger=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["plan"]["pfd_avg"] == pytest.approx(0.0004925, abs=5e-8)
    assert body["together"]["met"] is True
    r = _post(client, _plant(repair_crews={"crews": 1}))
    assert r.status_code == 200 and r.json()["status"] == "crews_limited"
    r = _post(client, _plant(repair_crews={"crews": 1}), assume_unlimited_crews=True)
    assert r.status_code == 200 and r.json()["crews"]["assumed_unlimited"] is True
    assert _post(client, _plant(), target_sil=9).status_code == 422
    assert _post(client, {**_plant(), "repairable": False}).status_code == 422


def test_app_large_search_runs_as_a_job(client, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import compute_app
    from backend.services import compute_queue
    from backend.tests.test_compute_service import CALLBACK_URL, _configure, _fake_verify

    client.act_as(FREE)
    monkeypatch.setattr(ri, "INLINE_EVALUATIONS", 10)
    local = _post(client, _sif(), max_pfd=5e-4, allowed=CAL, stagger=True).json()  # no queue: in-process
    assert local["status"] == "ok"

    _configure(monkeypatch)
    tasks = []
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: tasks.append(
        json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request}))) or True)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)
    monkeypatch.setattr(compute_app, "_post", lambda url, payload, timeout: client.post(
        "/internal/compute/callback", json=payload, headers={"Authorization": "Bearer compute-token"}).status_code)
    rbd_id = client.post("/api/rbds", json={"name": "SIF", "graph": _sif()}).json()["id"]
    r = _post(client, _sif(), rbd_id=rbd_id, max_pfd=5e-4, allowed=CAL, stagger=True)
    assert r.status_code == 202, r.text
    body = r.json()
    job_id = body["job"]["job_id"]
    assert body["status"] == "pending" and body["evaluations"] > 10 and tasks[0]["kind"] == "intervals"
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}").json()["job"] is None
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}&kind=intervals").json()["job"]["job_id"] == job_id
    compute = TestClient(compute_app.app)
    assert compute.post("/compute/run", json={**tasks.pop(), "callback_url": CALLBACK_URL}).status_code == 200
    view = client.get(f"/api/rbd-jobs/{job_id}").json()
    assert view["status"] == "done" and view["kind"] == "intervals"
    result = view["result"]
    result.pop("job_id")
    assert result == local
    again = _post(client, _sif(), rbd_id=rbd_id, max_pfd=5e-4, allowed=CAL, stagger=True)
    assert again.status_code == 200 and again.json()["job_id"] == job_id and not tasks
    assert not client.db.rbds.find_one({"_id": rbd_id}).get("availability_cache")


@pytest.fixture
def mcp(monkeypatch):
    import mongomock

    from backend import config, db
    from backend.services import tokens
    from backend.tests.test_mcp import A

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 40)
    test_db = mongomock.MongoClient()["reliafy_mcp_intervals"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    return test_db, tokens.create_token(test_db, A, "mcp")["token"]


def test_mcp_optimise_maintenance_intervals(mcp):
    from backend.services import rbds as rbds_service
    from backend.tests.test_mcp import A, _call, _ok

    test_db, token = mcp
    sif = rbds_service.save_rbd(test_db, "SIF", _sif(), A)
    out = _ok(_call(token, "optimise_maintenance_intervals", {
        "rbd_id": sif.id, "max_pfd": 5e-4, "allowed_intervals": CAL, "stagger_tests": True}))
    assert out["available"] is True and out["schedule"] == "proof_test"
    assert out["plan"]["pfd_avg"] == pytest.approx(0.0004925, abs=5e-8) and out["plan"]["sil"] == 3
    assert out["tested_together"]["cost_rate"] > out["plan"]["cost_rate"]
    assert out["as_drawn"]["meets_target"] is False
    ops = out["edit_rbd_ops"]
    assert {"op": "update_node", "id": "v2", "inspection": {"interval": 8760.0, "cost": 500, "offset": 4380.0}} in ops
    # The ops apply with edit_rbd and give the plan.
    _ok(_call(token, "edit_rbd", {"rbd_id": sif.id, "ops": ops}))
    again = _ok(_call(token, "optimise_maintenance_intervals", {
        "rbd_id": sif.id, "max_pfd": 5e-4, "allowed_intervals": CAL, "stagger_tests": True}))
    assert again["changed"] is False
    assert again["as_drawn"]["pfd_avg"] == pytest.approx(out["plan"]["pfd_avg"], rel=1e-12)


def test_mcp_limited_crews_and_the_simulation_with_them(mcp):
    from backend.services import rbds as rbds_service
    from backend.tests.test_mcp import A, _call, _ok

    test_db, token = mcp
    plant = rbds_service.save_rbd(test_db, "Plant", _plant(repair_crews={"crews": 1}), A)
    out = _ok(_call(token, "optimise_maintenance_intervals", {"rbd_id": plant.id}))
    assert out["available"] is False and out["code"] == "crews_limited"
    assert "assume_unlimited_crews=true" in out["message"]
    out = _ok(_call(token, "optimise_maintenance_intervals", {"rbd_id": plant.id, "assume_unlimited_crews": True}))
    assert out["available"] is True and out["crews"]["assumed_unlimited"] is True
    assert out["with_crews"]["available"] is False and "simulate_with_crews" in out["with_crews"]["note"]
    # Replacements that take a modelled time: edit_rbd can't carry the model, so the app applies them.
    assert out["edit_rbd_ops"] == [] and "duration is a model" in out["edit_rbd_note"]
    out = _ok(_call(token, "optimise_maintenance_intervals", {
        "rbd_id": plant.id, "assume_unlimited_crews": True, "simulate_with_crews": True}))
    crews = out["with_crews"]
    assert crews["available"] is True and crews["basis"] == "simulation"
    assert 0 < crews["availability"] < 1 and crews["cost_rate"] > 0
    nr = rbds_service.save_rbd(test_db, "Plain", {**_plant(), "repairable": False}, A)
    err = _call(token, "optimise_maintenance_intervals", {"rbd_id": nr.id})
    assert err.is_error and "non-repairable" in err.content[0].text
