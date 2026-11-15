"""Standby as plants run it (#363): two or more units running with warm
spares, units that differ, and what RePyability can and can't work out —
exact or numerical (free), or a plain refusal with the offer to simulate it
(Pro), carried through every export and import."""

import json
import math
import os
import subprocess
import sys

import numpy as np
import pytest
import surpyval as sp
from repyability.rbd.standby_node import StandbyModel

from backend.services import rbd_analysis as ra
from backend.services import rbd_graph, rbd_standby
from backend.tests.test_availability_paid import FREE, PRO, client  # noqa: F401 - the fixture


def E(rate):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


def W(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _graph(**data):
    block = {"id": "s", "type": "standby", "label": "Pumps", "model": E(1e-3), "spares": 1, **data}
    nodes = [{"id": "input", "type": "input"}, block, {"id": "output", "type": "output"}]
    return rbd_graph.normalize_graph({"nodes": nodes, "edges": [{"source": "input", "target": "s"},
                                                                 {"source": "s", "target": "output"}],
                                      "unit": "Hours"})


def _data(graph):
    return next(n for n in graph["nodes"] if n["id"] == "s")["data"]


TIMES = [200.0, 700.0, 1500.0, 3000.0]


# ---------------------------------------------------------------------------
# Exact: constant-rate units, any k, cold/warm/hot, start chance
# ---------------------------------------------------------------------------
def test_two_running_one_warm_spare_matches_the_closed_form():
    # 2 running, 1 spare ageing at 30%: two exponential stages, rates
    # lam*(2 + 0.3) (three alive) then lam*2 (two alive): a hypoexponential.
    lam, d = 1e-3, 0.3
    out = ra.analyze(_graph(k=2, dormancy=d), at_times=TIMES)
    a, b = lam * (2 + d), lam * 2
    closed = [(b * math.exp(-a * t) - a * math.exp(-b * t)) / (b - a) for t in TIMES]
    assert out["at"]["sf"] == pytest.approx(closed, rel=1e-9)
    direct = StandbyModel([sp.Exponential.from_params([lam])] * 3, k=2, dormancy_factor=d)
    assert out["at"]["sf"] == pytest.approx(list(direct.sf(np.array(TIMES))), rel=1e-9)
    assert "simulated" not in out
    route = rbd_standby.route_of({"type": "standby", "data": _data(_graph(k=2, dormancy=d))})
    assert route["route"] == "exact"
    assert route["words"] == "2 running, 1 warm spare ageing at 30% while waiting"


@pytest.mark.parametrize("k,spares,dormancy,start", [(3, 2, 0.5, 1.0), (2, 2, 0.2, 0.9), (2, 1, 1.0, 0.95),
                                                    (3, 1, 0.0, 0.9)])
def test_constant_rate_units_are_exact_for_any_arrangement(k, spares, dormancy, start):
    g = _graph(k=k, spares=spares, dormancy=dormancy, startProb=start, runningModels=[E(2e-3)])
    out = ra.analyze(g, at_times=TIMES)
    units = [sp.Exponential.from_params([2e-3])] + [sp.Exponential.from_params([1e-3])] * (k - 1 + spares)
    direct = StandbyModel(units, k=k, dormancy_factor=dormancy, start_probability=start)
    assert not direct.is_simulated
    assert out["at"]["sf"] == pytest.approx(list(direct.sf(np.array(TIMES))), rel=1e-6)
    assert rbd_standby.route_of({"type": "standby", "data": _data(g)})["route"] == "exact"


# ---------------------------------------------------------------------------
# Units that differ
# ---------------------------------------------------------------------------
def test_spares_with_models_of_their_own():
    # One running Weibull, two cold spares: the first smaller (its own model),
    # the second the running units' model. Numerical (a convolution).
    g = _graph(model=W(1000, 2), spares=2, dormancy=0, cold=True, spareModels=[W(500, 1.5), None])
    out = ra.analyze(g, at_times=TIMES)
    p, s1 = sp.Weibull.from_params([1000, 2]), sp.Weibull.from_params([500, 1.5])
    direct = StandbyModel([p, s1, p])
    assert out["at"]["sf"] == pytest.approx(list(direct.sf(np.array(TIMES))), abs=1e-6)
    route = rbd_standby.route_of({"type": "standby", "data": _data(g)})
    assert route["route"] == "numerical"
    assert route["words"].endswith("spare 1 has its own model")


def test_every_spares_model_now_works_warm_too():
    g = _graph(model=W(1000, 2), standbyModel=W(800, 2), spares=1, dormancy=0.3)
    out = ra.analyze(g, at_times=TIMES)
    direct = StandbyModel([sp.Weibull.from_params([1000, 2]), sp.Weibull.from_params([800, 2])],
                          dormancy_factor=0.3)
    assert out["at"]["sf"] == pytest.approx(list(direct.sf(np.array(TIMES))), abs=1e-5)


def test_unit_lists_are_checked():
    v = ra.validate_graph(_graph(k=2, spares=1, runningModels=[None, None, E(1e-3)]))
    assert not v["valid"] and any("3 running units' models given" in e for e in v["errors"])
    big = ra.validate_graph(_graph(k=10, spares=5, spareModels=[E(1e-3)]))
    assert any("at most 12 units" in e for e in big["errors"])


def test_repairable_groups_refuse_units_that_differ():
    from backend.services import rbd_policies

    errs = rbd_policies.standby_errors({"spares": 1, "spareModels": [E(2e-3)], "model": E(1e-3)}, "Pumps")
    assert any("identical" in e for e in errs)


# ---------------------------------------------------------------------------
# What the library can't do: refused plainly, simulated when asked (Pro)
# ---------------------------------------------------------------------------
WARM_WEIBULL = dict(model=W(1000, 2), k=2, spares=1, dormancy=0.3)


def test_warm_weibull_with_two_running_is_refused_with_the_offer():
    v = ra.validate_graph(_graph(**WARM_WEIBULL))
    assert not v["valid"]
    msg = v["errors"][0]
    assert "warm standby with 2 units running can be worked out exactly only when every unit has a constant" in msg
    assert "Simulate this block" in msg and "Pro" in msg
    route = rbd_standby.route_of({"type": "standby", "data": _data(_graph(**WARM_WEIBULL))})
    assert route["route"] == "simulated" and route["pro"] is True
    assert "RePyability" not in route["reason"]  # plain words, not the library's internals


def test_a_block_set_to_be_simulated_validates_and_needs_the_leave_to_run():
    g = _graph(simulate=True, **WARM_WEIBULL)
    v = ra.validate_graph(g)
    assert v["valid"] and v["simulated_blocks"] == ["Pumps"]
    assert v["analytic"] is False and "simulated" in v["non_analytic_nodes"]["Pumps"]
    with pytest.raises(rbd_standby.SimulationNeedsPro):
        ra.analyze(g)
    with rbd_standby.simulation("run"):
        out = ra.analyze(g, at_times=TIMES)
    sim = out["simulated"]
    assert sim["blocks"][0]["label"] == "Pumps" and sim["blocks"][0]["lives"] == rbd_standby.SIM_LIVES
    assert sim["blocks"][0]["half_width"] == pytest.approx(rbd_standby.dkw_half_width(rbd_standby.SIM_LIVES), abs=1e-4)
    assert any("simulated" in w for w in out["warnings"])
    # The library's own simulation of the same arrangement agrees within the band.
    units = [sp.Weibull.from_params([1000, 2])] * 3
    model = StandbyModel(units, k=2, dormancy_factor=0.3)
    lives = np.sort(model.random(200_000, seed=7))
    emp = 1.0 - np.searchsorted(lives, TIMES, side="right") / lives.size
    assert out["at"]["sf"] == pytest.approx(list(emp), abs=0.01)
    # Same seed every time: the same figures.
    with rbd_standby.simulation("run"):
        again = ra.analyze(g, at_times=TIMES)
    assert again["at"]["sf"] == out["at"]["sf"]


def test_simulated_blocks_skip_the_parameter_band():
    with rbd_standby.simulation("run"):
        out = ra.analyze(_graph(simulate=True, **WARM_WEIBULL), band={"level": 0.9})
    assert "band" not in out
    assert any("confidence band" in w for w in out["warnings"])


def test_the_route_asks_pro_to_simulate(client):  # noqa: F811
    graph = _graph(simulate=True, **WARM_WEIBULL)
    client.act_as(FREE)
    r = client.post("/api/rbds/analyze", json={"graph": graph})
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["code"] == "pro_required" and body["upgrade"] is True and body["simulated_block"] is True
    assert body["detail"].startswith("“Pumps”: warm standby with 2 units running")
    assert "part of Pro" in body["detail"]
    client.act_as(PRO)
    r = client.post("/api/rbds/analyze", json={"graph": graph})
    assert r.status_code == 200, r.text
    assert r.json()["simulated"]["blocks"][0]["label"] == "Pumps"
    # Exact blocks are free for everyone.
    client.act_as(FREE)
    r = client.post("/api/rbds/analyze", json={"graph": _graph(k=2, dormancy=0.3)})
    assert r.status_code == 200 and "simulated" not in r.json()
    # The dialog's route check: free and quick.
    r = client.post("/api/rbds/standby-route", json={"node": {"type": "standby", "data": _data(graph)}})
    assert r.status_code == 200 and r.json()["route"] == "simulated"


# ---------------------------------------------------------------------------
# Compact graphs (MCP, REST, CLI) and exports/imports carry the settings
# ---------------------------------------------------------------------------
def test_compact_graph_round_trip():
    g = _graph(k=2, spares=2, dormancy=0.3, startProb=0.95, runningModels=[None, E(2e-3)],
               spareModels=[W(500, 1.5)], simulate=True)
    compact = rbd_graph.compact_graph(g)
    node = next(n for n in compact["nodes"] if n["id"] == "s")
    assert node["runningModels"][0] is None and node["runningModels"][1]["distribution_id"] == "exponential"
    assert node["spareModels"][0]["distribution_id"] == "weibull" and node["simulate"] is True
    again = rbd_graph.normalize_graph(compact)
    d = _data(again)
    assert d["k"] == 2 and d["startProb"] == 0.95 and d["simulate"] is True
    assert d["runningModels"][1]["params"] == _data(g)["runningModels"][1]["params"]


def test_mcp_node_schema_takes_the_settings():
    from backend.mcp_server import RbdNode

    n = RbdNode(id="s", type="standby", k=2, spares=2, dormancy=0.3, startProb=0.9,
                runningModels=[None, {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 2e-3}]}],
                spareModels=[{"distribution_id": "weibull", "params": [{"name": "alpha", "value": 500}, {"name": "beta", "value": 1.5}]}],
                simulate=True, model={"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]})
    raw = n.model_dump(exclude_none=True)
    assert raw["runningModels"][0] is None and raw["simulate"] is True
    g = rbd_graph.normalize_graph({"nodes": [{"id": "input", "type": "input"}, raw, {"id": "output", "type": "output"}],
                                   "edges": [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]})
    assert _data(g)["runningModels"][1]["distribution_id"] == "exponential"


def test_saved_models_on_units_are_referenced():
    from backend.services import access

    g = {"nodes": [{"id": "s", "type": "standby", "data": {"label": "Pumps", "model": E(1e-3), "spares": 2,
                                                            "spareModels": [None, {"source": "saved",
                                                                                   "modelId": "m-spare"}]}}]}
    assert ("models", "m-spare") in access.graph_refs(g)


def _run_script(source: str, tmp_path) -> dict:
    path = tmp_path / "rbd.py"
    path.write_text(source)
    out = tmp_path / "results.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(RELIAFY_RESULTS_JSON=str(out), MPLBACKEND="Agg")
    proc = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, env=env, timeout=300,
                          cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(out.read_text())


@pytest.mark.parametrize("data", [
    dict(model=W(1000, 2), spares=2, dormancy=0, cold=True, spareModels=[W(500, 1.5), None]),
    dict(model=E(1e-3), k=2, spares=1, dormancy=0.3, runningModels=[E(2e-3)], startProb=0.95),
    dict(simulate=True, **WARM_WEIBULL),
], ids=["differing-cold", "exact-warm-k2", "simulated"])
def test_download_as_python_runs_and_matches(data, tmp_path):
    from backend.services import rbd_export

    g = _graph(**data)
    source = rbd_export.to_python(g, "Standby", None, None)
    if data.get("simulate"):
        assert "SimulatedLives(" in source and "StandbyModel(" in source
    results = _run_script(source, tmp_path)
    with rbd_standby.simulation("run"):
        app = ra.analyze(g)
    assert results["mttf"] == pytest.approx(app["mttf"], rel=2e-3)


@pytest.mark.parametrize("plain", [False, True], ids=["reliafy-json", "repyability-only"])
def test_json_round_trip_carries_the_units(plain):
    from backend.services import rbd_import, rbd_json

    g = _graph(model=W(1000, 2), k=2, spares=2, dormancy=0, cold=True, runningModels=[None, W(900, 2)],
               spareModels=[W(500, 1.5), None])
    doc = rbd_json.to_document(g, "Standby")
    if plain:  # RePyability's part alone: the units read back from its StandbyModel
        doc.pop(rbd_json.EXTENSION_KEY)
    graph = rbd_import.import_file(rbd_json.to_json(doc).encode(), "standby.json")[0].graph
    d = next(n["data"] for n in graph["nodes"] if n["type"] == "standby")
    assert d.get("k") == 2
    assert d["runningModels"][1] is not None and d["spareModels"][0] is not None
    assert ra.analyze(graph, at_times=TIMES)["at"]["sf"] == pytest.approx(
        ra.analyze(g, at_times=TIMES)["at"]["sf"], abs=1e-6)


def test_simulated_block_exports_to_json_as_the_library_takes_it():
    from backend.services import rbd_json

    doc = rbd_json.to_document(_graph(simulate=True, **WARM_WEIBULL), "Standby")
    core = json.loads(rbd_json.to_json(doc))
    block = next(r["model"] for r in core["reliabilities"] if r["node"] == "s")
    assert block["kind"] == "standby" and len(block["reliabilities"]) == 3
    # Not set to be simulated: refused, with the offer, as the analysis refuses it.
    with pytest.raises(rbd_json.ExportError, match="Simulate this block"):
        rbd_json.to_document(_graph(**WARM_WEIBULL), "Standby")


def test_excel_import_reads_running_and_spare_model():
    from backend.services.rbd_import import excel

    node = {}
    rec = {"running": 2, "spares": 1, "spare_distribution": "Weibull", "spare_alpha": 500, "spare_beta": 1.5}
    model = excel._model(rec, "Block “Pumps”", prefix="spare_")
    assert model == {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 500.0},
                                                              {"name": "beta", "value": 1.5}]}
    assert node == {}


def test_own_from_units():
    a, b, c = {"m": 1}, {"m": 2}, {"m": 3}
    assert rbd_standby.own_from_units([a, a, a], 1) == {"model": a}
    assert rbd_standby.own_from_units([a, a, b, b], 2) == {"model": a, "standbyModel": b}
    assert rbd_standby.own_from_units([a, c, b, a], 2) == {"model": a, "runningModels": [None, c],
                                                          "spareModels": [b, None]}
