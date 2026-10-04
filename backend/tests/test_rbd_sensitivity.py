"""What to improve (#225): a repairable diagram's levers ranked from
RePyability 0.12's lever sensitivity (``parameter_sensitivity``).

Checked against RePyability directly (the same derivatives, its own
``unit_costs`` ranking), by a finite difference and the closed form of one
block, and through the app, the queue and MCP."""

import copy
import json
import math

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services import rbd_sensitivity as rs
from backend.services import samples
from backend.services.rbd_analysis import AnalysisError
from backend.tests.test_availability_paid import FREE, PRO, client  # noqa: F401 - fixture
from backend.tests.test_rbd_costs import _exp, _io, _ln, _node, _series, _w


def _priced():
    """A pump (Weibull life, lognormal repair) and a valve in series, priced."""
    return _series(_node("pump", model=_w(1000, 2), repair=_ln(2, 0.5), costs={"repair": 500}),
                   _node("valve", model=_exp(1e-4), repair=_ln(1, 0.5), costs={"repair": 200}),
                   costs={"downtime_rate": 100})


def _one():
    """One block: fails at 0.001 /h, repaired at 0.1 /h (MTTF 1000 h, MTTR 10 h)."""
    return _series(_node("pump", model=_exp(1e-3), repair=_exp(0.1)))


def _parallel(*nodes, **graph):
    edges = []
    for n in nodes:
        edges += [{"source": "input", "target": n["id"]}, {"source": n["id"], "target": "output"}]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes], "edges": edges, **graph}


def _crews():
    """Two wear-out pumps in parallel, one repair crew: no exact long run
    (RePyability's Markov chain needs exponential lives), so simulated."""
    return _parallel(_node("a", model=_w(1000, 2), repair=_ln(3, 0.5)),
                     _node("b", model=_w(800, 1.5), repair=_ln(3, 0.5)), repair_crews={"crews": 1})


def _maintained():
    """Age replacement and proof tests that take time: numerical."""
    return _series(
        _node("pump", model=_w(1000, 3), repair=_ln(2, 0.5),
              preventive={"policy": "age", "interval": 400, "duration": _ln(1, 0.3)}),
        _node("valve", model=_exp(1e-4), instant_repair=True, inspection={"interval": 720, "duration": _exp(1.0)}))


def _built(graph):
    rbd, labels, gates, working, broken = ra._build_repairable_rbd(graph)
    return rbd, working, broken


def _rows(result):
    return {row["id"]: row for row in result["levers"]}


def _key(row):
    return row["block_id"], row["lever"]


# ---- Against RePyability -----------------------------------------------------------

@pytest.mark.parametrize("make", [samples._instrument_air_availability_graph, _priced, _maintained],
                         ids=["sample", "priced", "maintained"])
def test_the_derivatives_are_repyabilitys(make):
    graph = make()
    out = rs.analyze_sensitivity(graph)
    rbd, working, broken = _built(graph)
    of = ("availability", "cost_rate") if out["priced"] else ("availability",)
    theirs = rbd.parameter_sensitivity(working, broken, of=of)
    assert out["status"] == "ok" and out["levers"]
    for row in out["levers"]:
        for q in of:
            assert row["derivative"][q] == theirs[q][row["block_id"]][row["lever"]], (row["id"], q)
    # Every lever RePyability has is here, once.
    expected = {(str(k), name) for k, levers in theirs["availability"].items() for name in levers}
    assert {_key(r) for r in out["levers"]} == expected
    assert out["basis"] == rbd.analysis_routes()["mean_availability"].route


def test_one_block_against_its_closed_form_and_a_finite_difference():
    """A = μ / (λ + μ): its derivatives, a central difference of the rebuilt
    diagram, and the exact effect of a 10% longer mean life."""
    lam, mu = 1e-3, 0.1
    out = rs.analyze_sensitivity(_one())
    rows = _rows(out)
    life, repair = rows["pump|reliability.failure_rate"], rows["pump|repairability.failure_rate"]
    assert out["availability"] == pytest.approx(mu / (lam + mu), rel=1e-12)
    assert life["derivative"]["availability"] == pytest.approx(-mu / (lam + mu) ** 2, rel=1e-6)
    assert repair["derivative"]["availability"] == pytest.approx(lam / (lam + mu) ** 2, rel=1e-6)
    # Per hour of mean life: dA/dMTTF = dA/dλ · dλ/dMTTF = dA/dλ · (−λ²).
    assert life["derivative_shown"]["availability"] == pytest.approx(
        -mu / (lam + mu) ** 2 * -lam ** 2, rel=1e-6)

    # A finite difference of our own, on the diagram rebuilt by hand.
    def availability(rate):
        g = _one()
        g["nodes"][2]["data"]["model"]["params"][0]["value"] = rate
        return _built(g)[0].mean_availability()

    h = lam * 1e-4
    fd = (availability(lam + h) - availability(lam - h)) / (2 * h)
    assert life["derivative"]["availability"] == pytest.approx(fd, rel=1e-6)

    # The step: a 10% longer mean life is λ / 1.1, exactly.
    assert life["change"] == "a 10% longer mean life" and life["direction"] == "increase"
    assert life["to"] == pytest.approx(lam / 1.1, rel=1e-15)
    assert life["shown_value"] == pytest.approx(1000.0) and life["shown_to"] == pytest.approx(1100.0)
    assert life["effect"]["availability"] == pytest.approx(
        mu / (lam / 1.1 + mu) - mu / (lam + mu), rel=1e-9)
    assert life["effect_basis"] == "exact"
    # A 10% shorter mean repair time: μ · 1/0.9.
    assert repair["change"] == "a 10% shorter mean repair time"
    assert repair["effect"]["availability"] == pytest.approx(
        (mu / 0.9) / (lam + mu / 0.9) - mu / (lam + mu), rel=1e-9)
    assert "points" in repair["plain"] and "(10 → 9 hours)" in repair["plain"]


def test_unit_costs_rank_as_repyabilitys():
    """A cost to make a lever's stated change is a cost per unit of the lever
    of cost / |step|: the per-unit-cost figure is RePyability's unit_costs
    ranking, to the last bit, and the ranking is by benefit per cost."""
    graph = _priced()
    costs = {"pump|repairability.mu": 2000.0, "valve|reliability.failure_rate": 50.0}
    out = rs.analyze_sensitivity(graph, costs=costs, order="benefit_per_cost")
    rows = _rows(out)
    rbd, working, broken = _built(graph)
    unit = {}
    for lever_id, cost in costs.items():
        row = rows[lever_id]
        unit[(row["block_id"], row["lever"])] = cost / abs(row["to"] - row["value"])
    theirs = rbd.parameter_sensitivity(working, broken, unit_costs=unit)
    for lever_id in costs:
        row = rows[lever_id]
        assert row["per_unit_cost"] == pytest.approx(theirs[row["block_id"]][row["lever"]], rel=1e-12)
        assert row["benefit_per_cost"] == pytest.approx(row["effect"]["availability"] / costs[lever_id])
    # The cheap valve change comes first, then the pump's; uncosted levers after.
    assert [r["id"] for r in out["levers"][:2]] == ["valve|reliability.failure_rate", "pump|repairability.mu"]
    assert all(r["cost_to_change"] is None for r in out["levers"][2:])
    assert "for every 1,000 spent" in out["levers"][0]["plain"]
    assert out["order"] == "benefit_per_cost" and out["top"].startswith("A 10% longer mean life for Valve")
    with pytest.raises(AnalysisError, match="not levers"):
        rs.analyze_sensitivity(graph, costs={"nope|x": 1})
    with pytest.raises(AnalysisError, match="order must be"):
        rs.analyze_sensitivity(graph, order="cheapest")


@pytest.mark.parametrize("rank_by", ["availability", "cost"])
def test_a_costed_lever_never_outranks_a_better_one_when_ranking_by_benefit(rank_by):
    """Ranking by benefit (the default) ignores the costs: a costed lever with
    a smaller benefit stays below an uncosted one with a larger benefit, and
    the top sentence follows the ranking shown. Ranking by benefit per cost
    puts the costed levers first."""
    graph = _priced()
    plain = rs.analyze_sensitivity(graph, rank_by=rank_by)
    best, small = plain["levers"][0], plain["levers"][-1]
    assert best["benefit"] > small["benefit"] and best["cost_to_change"] is None
    costs = {small["id"]: 1.0, plain["levers"][1]["id"]: 5.0}
    by_benefit = rs.analyze_sensitivity(graph, rank_by=rank_by, costs=costs)
    assert by_benefit["order"] == "benefit"
    # The same order as with no costs at all, and the benefits descending.
    assert [r["id"] for r in by_benefit["levers"]] == [r["id"] for r in plain["levers"]]
    benefits = [r["benefit"] for r in by_benefit["levers"]]
    assert benefits == sorted(benefits, reverse=True)
    ids = [r["id"] for r in by_benefit["levers"]]
    assert ids.index(best["id"]) < ids.index(small["id"])
    assert by_benefit["top"] == plain["top"]
    # Each costed row still carries its benefit per cost.
    assert _rows(by_benefit)[small["id"]]["benefit_per_cost"] == pytest.approx(small["benefit"] / 1.0)
    per_cost = rs.analyze_sensitivity(graph, rank_by=rank_by, costs=costs, order="benefit_per_cost")
    assert {r["id"] for r in per_cost["levers"][:2]} == set(costs)
    rest = [r["benefit"] for r in per_cost["levers"][2:]]
    assert rest == sorted(rest, reverse=True)
    first = per_cost["levers"][0]
    assert per_cost["top"].startswith(first["change"][0].upper() + first["change"][1:] + " for " + first["block"])


def test_ranked_by_benefit_with_plain_words():
    out = rs.analyze_sensitivity(_priced())
    benefits = [r["benefit"] for r in out["levers"]]
    assert benefits == sorted(benefits, reverse=True)
    top = out["levers"][0]
    assert top["rank"] == 1 and top["id"] == "pump|repairability.mu"
    assert out["top"].startswith("A 10% shorter mean repair time for Pump (8.37 → 7.54 hours) raises "
                                 "availability by 0.093 points and cuts the running cost by")
    assert "per hour" in out["top"] and "Next:" in out["top"]
    # Ranked by cost the step goes the way that cuts it.
    by_cost = rs.analyze_sensitivity(_priced(), rank_by="cost")
    assert all((r["effect"]["cost_rate"] or 0) <= 0 for r in by_cost["levers"] if r.get("effect"))
    with pytest.raises(AnalysisError, match="no costs"):
        rs.analyze_sensitivity(_one(), rank_by="cost")


def test_a_bigger_step_and_counts():
    """A 50% step (halving the mean repair time is 50% shorter); one more
    repair crew is RePyability's change for one more."""
    g = _parallel(_node("a", model=_exp(1e-3), repair=_exp(0.05)), _node("b", model=_exp(2e-3), repair=_exp(0.05)),
                  repair_crews={"crews": 1})
    out = rs.analyze_sensitivity(g, step=0.5)
    rows = _rows(out)
    assert rows["a|repairability.failure_rate"]["change"] == "a 50% shorter mean repair time"
    crews = rows["repair_crews"]
    rbd, working, broken = _built(g)
    one_more = rbd.parameter_sensitivity(working, broken)[None]["repair_crews"]
    assert crews["change"] == "one more repair crew" and crews["effect"]["availability"] == one_more
    assert crews["plain"].startswith("One more repair crew raises availability by")
    assert rs.parse_step("25") == 0.25
    with pytest.raises(AnalysisError):
        rs.parse_step(0.95)


def test_over_a_window_the_derivatives_are_repyabilitys():
    graph = _priced()
    out = rs.analyze_sensitivity(graph, window=2000.0)
    rbd, working, broken = _built(graph)
    theirs = rbd.parameter_sensitivity(working, broken, window=2000.0)
    assert out["of"] == "window" and out["basis"] == "numerical"
    # Availability only over a window (its cost is 14× slower to difference).
    assert out["priced"] is False and any("long run ranks" in n for n in out["notes"])
    with pytest.raises(AnalysisError, match="long run ranks"):
        rs.analyze_sensitivity(graph, window=2000.0, rank_by="cost")
    for row in out["levers"]:
        assert row["derivative"]["availability"] == theirs[row["block_id"]][row["lever"]]
        # The step's effect is the derivative times the step there.
        assert row["effect_basis"] == "linear"
        assert row["effect"]["availability"] == pytest.approx(
            row["derivative"]["availability"] * (row["to"] - row["value"]), rel=1e-12)
    assert "about" in out["top"]


def test_pinned_blocks_are_left_out():
    graph = _priced()
    graph["nodes"][3]["data"]["state"] = "working"  # the valve
    out = rs.analyze_sensitivity(graph)
    assert {r["block_id"] for r in out["levers"]} == {"pump"} and out["pinned"] == ["Valve"]


def test_too_large_and_plan(monkeypatch):
    plan = rs.plan(_priced())
    assert plan == {**plan, "basis": "exact", "inline": True, "too_large": False}
    assert rs.plan(_maintained())["inline"] is False and rs.plan(_maintained())["basis"] == "numerical"
    assert rs.plan(_priced(), window=100.0)["inline"] is False
    crews = rs.plan(_crews())
    assert crews["basis"] == "simulation" and "repair crew" in crews["reason"]
    monkeypatch.setattr(rs, "NUMERICAL_MAX_BLOCKS", 1)
    assert rs.plan(_maintained())["too_large"] and not rs.plan(_priced())["too_large"]
    with pytest.raises(AnalysisError, match="numerical.*for up to 1"):
        rs.analyze_sensitivity(_maintained())
    monkeypatch.setattr(rs, "WINDOW_MAX_BLOCKS", 1)
    with pytest.raises(AnalysisError, match="over a window for up to 1.*rank the long run"):
        rs.analyze_sensitivity(_priced(), window=100.0)
    monkeypatch.setattr(rs, "MAX_BLOCKS", 1)
    with pytest.raises(AnalysisError, match="Download it as Python"):
        rs.analyze_sensitivity(_priced())


# ---- The simulated route --------------------------------------------------------------

def test_the_simulated_route_and_the_compute_service_agree():
    """No exact long run: each step simulated against the diagram with common
    random numbers. The compute service's answer to the JSON a task carries
    is the in-process one, to the last bit, for a fixed size."""
    from backend.services import compute_core

    graph = _crews()
    graph["nodes"][-1]["position"] = {"x": 5, "y": 5}
    request = json.loads(json.dumps(compute_core.sensitivity_request(graph, n_simulations=60)))
    remote = compute_core.run("sensitivity", request)
    local = compute_core.to_wire(rs.analyze_sensitivity(graph, n_simulations=60))
    remote.pop("compute_seconds"), local.pop("compute_seconds")
    assert remote == local
    assert remote["basis"] == "simulation" and remote["n_simulations"] == 60
    assert remote["common_random_numbers"] is True
    rows = _rows(remote)
    assert rows["a|reliability.alpha"]["change"] == "a 10% longer mean life"
    assert rows["repair_crews"]["change"] == "one more repair crew"
    assert all("interval" in r for r in remote["levers"] if r.get("effect_basis") == "simulation")
    assert any("Shape parameters aren't simulated" in n for n in remote["notes"])
    assert compute_core.KINDS == ("availability", "sensitivity", "intervals")
    assert rs.analyze_sensitivity(graph, simulate=False)["status"] == "needs_simulation"


def test_simulated_effects_agree_with_the_exact_ones():
    """On a diagram with an exact long run, the simulated route's effects (over
    a long window) fall within their intervals of the exact ones."""
    graph = _parallel(_node("a", model=_exp(1e-2), repair=_exp(0.1)), _node("b", model=_exp(2e-2), repair=_exp(0.2)))
    exact = _rows(rs.analyze_sensitivity(graph))
    rbd, working, broken = _built(graph)
    found = rs._levers(rbd, {"a": "A", "b": "B"}, "hours", set(), set())
    sim = rs._simulated(graph, rbd, found, {"working_nodes": working, "broken_nodes": broken}, 20000.0, 0.1,
                        "availability", ("availability",), 400, None)
    for row in sim["rows"]:
        lo, hi = row["interval"]["availability"]
        want = exact[row["id"]]["effect"]["availability"]
        half = (hi - lo) / 2
        assert abs(row["effect"]["availability"] - want) <= 2 * half + 1e-12, row["id"]


# ---- The app ---------------------------------------------------------------------------

def _post(client, graph, **body):
    return client.post("/api/rbds/sensitivity", json={"graph": graph, **body})


def test_app_exact_is_free_and_answers_at_once(client):
    client.act_as(FREE)
    r = _post(client, samples._instrument_air_availability_graph())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["basis"] == "exact" and body["levers"] and body["top"]
    assert body["can_simulate"] is False
    r = _post(client, _priced(), costs={"valve|repairability.mu": 1000}, rank_by="cost", step=0.25,
              order="benefit_per_cost")
    assert r.status_code == 200 and r.json()["levers"][0]["id"] == "valve|repairability.mu"
    r = _post(client, _priced(), costs={"valve|repairability.mu": 1000}, rank_by="cost", step=0.25)
    assert r.status_code == 200 and r.json()["levers"][0]["id"] != "valve|repairability.mu"
    assert _post(client, _priced(), order="cheapest").status_code == 422
    assert _post(client, _priced(), step=0).status_code == 422
    nr = _priced()
    nr["repairable"] = False
    assert _post(client, nr).status_code == 422


def test_app_simulated_route_is_pro(client, monkeypatch):
    monkeypatch.setattr(rs, "SIM_TIME_BUDGET_S", 0.5)
    monkeypatch.setattr(rs, "SIM_MIN_N", 20)
    client.act_as(FREE)
    body = _post(client, _crews(), simulate=True).json()
    assert body["status"] == "pro_required" and body["basis"] == "simulation" and body["upgrade"] is True
    client.act_as(PRO)
    body = _post(client, _crews()).json()
    assert body["status"] == "needs_simulation" and body["can_simulate"] is True
    r = _post(client, _crews(), simulate=True)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok" and r.json()["basis"] == "simulation"


def test_app_numerical_route_runs_as_a_job(client, monkeypatch):
    """Through the queue: a job, the compute service's result, polled; the
    same inputs again are served the finished job."""


    from fastapi.testclient import TestClient

    from backend import compute_app
    from backend.services import compute_queue
    from backend.tests.test_compute_service import CALLBACK_URL, _configure, _fake_verify

    client.act_as(FREE)
    local = _post(client, _maintained()).json()  # no queue: in-process
    assert local["status"] == "ok" and local["basis"] == "numerical"

    _configure(monkeypatch)
    tasks = []
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: tasks.append(
        json.loads(json.dumps({"job_id": job_id, "kind": kind, "request": request}))) or True)
    monkeypatch.setattr(compute_queue, "_verify_token", _fake_verify)
    monkeypatch.setattr(compute_app, "_post", lambda url, payload, timeout: client.post(
        "/internal/compute/callback", json=payload, headers={"Authorization": "Bearer compute-token"}).status_code)
    rbd_id = client.post("/api/rbds", json={"name": "Maintained", "graph": _maintained()}).json()["id"]
    r = _post(client, _maintained(), rbd_id=rbd_id)
    assert r.status_code == 202, r.text
    job_id = r.json()["job"]["job_id"]
    assert r.json()["basis"] == "numerical" and tasks[0]["kind"] == "sensitivity"
    # The availability tab doesn't pick it up; the panel does.
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}").json()["job"] is None
    assert client.get(f"/api/rbd-jobs?rbd_id={rbd_id}&kind=sensitivity").json()["job"]["job_id"] == job_id
    compute = TestClient(compute_app.app)
    assert compute.post("/compute/run", json={**tasks.pop(), "callback_url": CALLBACK_URL}).status_code == 200
    view = client.get(f"/api/rbd-jobs/{job_id}").json()
    assert view["status"] == "done" and view["kind"] == "sensitivity"
    result = view["result"]
    for key in ("compute_seconds", "can_simulate", "job_id"):
        result.pop(key, None), local.pop(key, None)
    assert result == local
    again = _post(client, _maintained(), rbd_id=rbd_id)
    assert again.status_code == 200 and again.json()["job_id"] == job_id and not tasks
    # Never stored on the diagram as an availability result.
    doc = client.db.rbds.find_one({"_id": rbd_id})
    assert not doc.get("availability_cache")


# ---- MCP ----------------------------------------------------------------------------------

def test_mcp_rbd_sensitivity(monkeypatch):
    from backend.services import rbds as rbds_service
    from backend.tests.test_mcp import A, _call, _ok

    import mongomock

    from backend import config, db
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_sens"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]
    rbd = rbds_service.save_rbd(test_db, "Pump and valve", _priced(), A)

    out = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "limit": 3}))
    assert out["available"] is True and out["basis"] == "exact" and len(out["levers"]) == 3
    assert out["n_levers"] == 7 and out["top"].startswith("A 10% shorter mean repair time for Pump")
    first = out["levers"][0]
    assert first["id"] == "pump|repairability.mu" and first["availability_points"] == pytest.approx(0.0928, rel=1e-2)
    assert first["derivative"]["availability"] < 0  # per unit of the lognormal μ: a longer repair is worse
    assert "points" in first["plain"] and out["units_note"]
    costed = {"valve|reliability.failure_rate": 10}
    priced = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "rank_by": "cost", "costs_to_change": costed,
                                                  "order": "benefit_per_cost"}))
    assert priced["order"] == "benefit_per_cost"
    assert priced["levers"][0]["id"] == "valve|reliability.failure_rate"
    assert priced["levers"][0]["benefit_per_cost"] is not None
    # Ranked by benefit (the default) the costed valve stays below the pump.
    by_benefit = _ok(_call(token, "rbd_sensitivity", {"rbd_id": rbd.id, "rank_by": "cost",
                                                      "costs_to_change": costed, "limit": 7}))
    ids = [r["id"] for r in by_benefit["levers"]]
    assert by_benefit["order"] == "benefit" and ids[0].startswith("pump|")
    assert ids.index("pump|reliability.alpha") < ids.index("valve|reliability.failure_rate")
    assert by_benefit["top"].startswith("A 10% longer mean life for Pump")
    nr = rbds_service.save_rbd(test_db, "Plain", {**_priced(), "repairable": False}, A)
    err = _call(token, "rbd_sensitivity", {"rbd_id": nr.id})
    assert err.is_error and "non-repairable" in err.content[0].text


# ---- Download as Python ---------------------------------------------------------------------

@pytest.mark.parametrize("make", [samples._instrument_air_availability_graph, _priced, _maintained],
                         ids=["sample", "priced", "maintained"])
def test_the_exported_script_ranks_as_the_app(make, tmp_path):
    """The script's what_to_improve (the generated file, run on its own) gives
    the app's levers, steps and effects in the app's order."""
    from backend.services import rbd_export
    from backend.tests.test_rbd_export import _run

    graph = make()
    app = rs.analyze_sensitivity(graph)
    code = rbd_export.to_python(graph, "Improve")
    assert "def what_to_improve(" in code
    res, proc = _run(code, tmp_path, n_sims="20")
    rows = res["what_to_improve"]
    ids = ["repair_crews" if r["block"] is None else f"{r['block']}|{r['lever']}" for r in rows]
    ranked = [r for r in app["levers"] if r.get("effect")]
    assert ids == [r["id"] for r in ranked]
    for mine, theirs in zip(rows, ranked):
        assert mine["to"] == pytest.approx(theirs["to"], rel=1e-12)
        assert mine["effect"] == pytest.approx(theirs["effect"]["availability"], rel=1e-9, abs=1e-15)
        assert mine["derivative"] == pytest.approx(theirs["derivative"]["availability"], rel=1e-12)
    assert "What to improve (long run" in proc.stdout
