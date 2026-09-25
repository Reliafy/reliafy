""""Download as Python": the generated script must rebuild the diagram and
reproduce the app's own numbers when it is actually run.

Every script is executed in a fresh subprocess (the same interpreter, but no
PYTHONPATH — so it can't lean on the backend) and its results, saved via
``RELIAFY_RESULTS_JSON``, are compared with :mod:`rbd_analysis`.
"""

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export  # noqa: E402
from backend.services import samples  # noqa: E402
from backend.tests.test_public_links import A, B, client  # noqa: E402,F401 - fixture

WHEN = datetime(2026, 9, 26, tzinfo=timezone.utc)


def _sample(sample_id):
    s = next(s for s in samples.SAMPLE_RBDS if s["id"] == sample_id)
    return copy.deepcopy(s["graph"]), s["name"]


def _run(code, tmp_path, name="diagram.py", n_sims="60", expect_ok=True):
    """Run a generated script; return ``(results, completed_process)``."""
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    out = tmp_path / (path.stem + ".json")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(MPLBACKEND="Agg", RELIAFY_RESULTS_JSON=str(out),
               RELIAFY_N_SIMS=n_sims)
    proc = subprocess.run(
        [sys.executable, str(path)], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=300,
    )
    if expect_ok:
        assert proc.returncode == 0, proc.stderr[-3000:]
        return json.loads(out.read_text()), proc
    return None, proc


def _w(alpha, beta, **extra):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}],
            **extra}


def _node(nid, ntype, label, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0},
            "data": {"label": label, **data}}


def _chain(*ids):
    seq = ["input", *ids, "output"]
    return [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(zip(seq, seq[1:]))]


def _flat(code):
    """The script with implicitly concatenated message strings joined."""
    return code.replace('"\n    "', "")


def _io():
    return [_node("input", "input", "Input"), _node("output", "output", "Output")]


# ---------------------------------------------------------------------------
# The script reproduces the app's numbers
# ---------------------------------------------------------------------------
def test_instrument_air_design_matches_app(tmp_path):
    """2oo3 voting gate + cold-standby dryer + beta-factor CCF. The app's MTTF
    is the integral of R(t); the cold standby's R(t) is RePyability's
    deterministic numerical convolution (k=1), not Monte-Carlo, so the script
    reproduces it essentially exactly."""
    graph, name = _sample("sample-rbd-instrument-air-design")
    app = ra.analyze(graph)
    code = rbd_export.to_python(graph, name, exported_at=WHEN)
    res, proc = _run(code, tmp_path)

    assert res["mttf"] == pytest.approx(app["mttf"], rel=1e-9)
    assert res["t_max"] == pytest.approx(app["time"][-1], rel=1e-12)
    np.testing.assert_allclose(res["curve"]["sf"], app["system"]["sf"], atol=1e-9)
    assert res["b10"] == pytest.approx(app["blife"]["b10"], rel=1e-9)
    assert res["b50"] == pytest.approx(app["blife"]["b50"], rel=1e-9)

    # R(t) at the script's read-out times (round times near the MTTF) agrees
    # with the app's own RBD (the CCF-coupled one) at those times.
    rbd, *_ = ra._build_rbd(graph)
    assert len(res["reliability"]) == 5
    for t, r in res["reliability"].items():
        assert r == pytest.approx(float(rbd.sf(float(t))), abs=1e-12)
    t_mttf = float(f"{res['mttf']:.2g}")  # 9200 h
    assert 0.3 < res["reliability"][repr(t_mttf)] < 0.6
    # A fixed time on the app's own plotted grid (its second point).
    t_fixed = app["time"][1]
    assert np.interp(t_fixed, res["curve"]["t"], res["curve"]["sf"]) == pytest.approx(
        app["system"]["sf"][1], abs=1e-9)

    # Importance at the same representative time, same values (nan-aware).
    assert res["importance_time"] == pytest.approx(app["importance"]["time"])
    for key, app_key in (("Birnbaum", "birnbaum"), ("Fussell-Vesely", "fussell_vesely")):
        for node, value in app["importance"][app_key].items():
            got = res["importance"][key][node]
            if value is None:
                assert not np.isfinite(got)
            else:
                assert got == pytest.approx(value, abs=1e-9)
    assert "MTTF: 9,206.88 Hours" in proc.stdout


def test_pump_station_matches_app_including_importance(tmp_path):
    graph, name = _sample("sample-rbd-pump-station")
    app = ra.analyze(graph)
    res, _ = _run(rbd_export.to_python(graph, name, exported_at=WHEN), tmp_path)

    assert res["mttf"] == pytest.approx(app["mttf"], rel=1e-9)
    np.testing.assert_allclose(res["curve"]["sf"], app["system"]["sf"], atol=1e-12)
    assert res["importance_time"] == pytest.approx(app["importance"]["time"])
    pairs = {
        "Birnbaum": "birnbaum", "Fussell-Vesely": "fussell_vesely",
        "Criticality": "criticality", "RAW": "risk_achievement_worth",
        "RRW": "risk_reduction_worth", "Improvement": "improvement_potential",
    }
    for key, app_key in pairs.items():
        assert set(res["importance"][key]) == set(app["importance"][app_key])
        for node, value in app["importance"][app_key].items():
            assert res["importance"][key][node] == pytest.approx(value, rel=1e-9)


def test_instrument_air_availability_matches_app(tmp_path, monkeypatch):
    """Repairable: the steady-state availability, MUT, MDT and failure
    frequency are exact (no simulation), so they match to rounding."""
    monkeypatch.setattr(ra, "_AVAIL_SIMS", 20)  # the app's sim isn't compared
    graph, name = _sample("sample-rbd-instrument-air-availability")
    app = ra.analyze_availability(graph)
    code = rbd_export.to_python(graph, name, exported_at=WHEN)
    assert 'N_SIMS = int(os.environ.get("RELIAFY_N_SIMS", "2000"))' in code
    res, proc = _run(code, tmp_path, n_sims="40")

    assert res["steady_state_availability"] == pytest.approx(
        app["steady_state_availability"], rel=1e-12)
    for key in ("mean_up_time", "mean_down_time", "failure_frequency"):
        assert res[key] == pytest.approx(app[key], rel=1e-9)
    assert res["t_simulation"] == app["t_simulation"]
    assert res["n_simulations"] == 40  # RELIAFY_N_SIMS honoured
    assert all(np.isfinite(v) for v in res["simulated"].values())
    # Per-block steady-state figures line up with the app's importance table.
    for node, row in res["blocks"].items():
        assert row["availability"] == pytest.approx(app["importance"][node]["availability"], rel=1e-12)
        assert row["birnbaum"] == pytest.approx(app["importance"][node]["birnbaum"], rel=1e-9)
    assert "vote" not in res["blocks"] and "dvote" not in res["blocks"]
    assert "Steady-state availability: 0.999682" in proc.stdout


def _sub_graph():
    return {
        "nodes": [*_io(),
                  _node("n1", "component", "Sub pump", model=_w(800, 1.2)),
                  _node("n2", "component", "Sub valve", model=_w(3000, 1.0))],
        "edges": _chain("n1", "n2"),
    }


def _mixed_graph():
    """Series/parallel count blocks, hot standby (identical + mixed spares),
    cold standby with imperfect switching, a nested sub-system and a pinned
    block."""
    return {
        "unit": "hours",
        "nodes": [
            *_io(),
            _node("s1", "series", "Bearings", n=3, model=_w(5000, 2.0)),
            _node("p1", "parallel", "Fans", n=2, model=_w(700, 1.5)),
            _node("h1", "standby", "Hot pumps", spares=1, cold=False, model=_w(900, 1.4)),
            _node("h2", "standby", "Hot mixed", spares=2, cold=False, model=_w(900, 1.4),
                  standbyModel=_w(600, 1.1)),
            _node("c1", "standby", "Cold mixed", spares=1, cold=True, startProb=0.9,
                  model=_w(900, 1.4), standbyModel=_w(600, 1.1)),
            _node("sub", "subsystem", "Cooling", rbd={"id": "rbd-sub", "name": "Cooling loop"}),
            _node("pin", "component", "Pinned good", state="working", model=_w(100, 1.0)),
        ],
        "edges": _chain("s1", "p1", "h1", "h2", "c1", "sub", "pin"),
    }


def test_series_parallel_standby_subsystem_graph_matches_app(tmp_path):
    graph = _mixed_graph()
    resolve_sub = {"rbd-sub": _sub_graph()}.get
    code = rbd_export.to_python(graph, "Mixed", resolve_subsystem=resolve_sub,
                                exported_at=WHEN)
    assert 'RepeatedNode(bearings_unit, 3, "series")' in code
    assert "StandbyModel(" in code and "switching_probability=0.9" in code
    assert "WORKING_NODES = {\"pin\"}" in code
    res, _ = _run(code, tmp_path)

    rbd, *_ = ra._build_rbd(graph, resolve_sub)
    overrides = {"working_nodes": {"pin"}, "broken_nodes": set()}
    t = np.array(res["curve"]["t"])
    np.testing.assert_allclose(res["curve"]["sf"], rbd.sf(t, **overrides), atol=1e-12)
    assert res["mttf"] == pytest.approx(ra._mttf(rbd, float(t[-1]), 0.0, **overrides), rel=1e-9)
    assert 0 < res["mttf"] < 1000


def test_tiny_series_parallel_graph_is_analytic(tmp_path):
    """input -> A -> {B | C} -> output with exponentials: R(t) in closed form."""
    lam = {"a": 1e-3, "b": 2e-3, "c": 4e-3}
    exp = lambda r: {"distribution_id": "exponential", "distribution": "Exponential",
                     "params": [{"name": "failure_rate", "value": r}]}
    graph = {
        "unit": "h",
        "nodes": [*_io(), *(_node(k, "component", k.upper(), model=exp(v)) for k, v in lam.items())],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "b"},
                  {"source": "a", "target": "c"}, {"source": "b", "target": "output"},
                  {"source": "c", "target": "output"}],
    }
    res, _ = _run(rbd_export.to_python(graph, "Tiny", exported_at=WHEN), tmp_path)
    for t, r in res["reliability"].items():
        t = float(t)
        exact = np.exp(-lam["a"] * t) * (1 - (1 - np.exp(-lam["b"] * t)) * (1 - np.exp(-lam["c"] * t)))
        assert r == pytest.approx(exact, rel=1e-12, abs=1e-15)
    app = ra.analyze(graph)
    assert res["mttf"] == pytest.approx(app["mttf"], rel=1e-9)


# ---------------------------------------------------------------------------
# Saved models and placeholders
# ---------------------------------------------------------------------------
def _saved_graph(extra_nodes=(), chain=("saved",)):
    return {
        "unit": "hours",
        "nodes": [*_io(),
                  _node("saved", "component", "Bearing",
                        model={"source": "saved", "modelId": "m-1", "kind": "distribution"}),
                  *extra_nodes],
        "edges": _chain(*chain),
    }


def test_saved_model_parameters_are_inlined_via_resolver(tmp_path):
    summary = {"name": "Bearing life (lognormal)", "kind": "distribution",
               "distribution_id": "lognormal", "distribution": "Lognormal",
               "params": [{"name": "sigma", "value": 0.5}, {"name": "mu", "value": 8.0}]}
    calls = []

    def resolve_model(model_id):
        calls.append(model_id)
        return summary if model_id == "m-1" else None

    code = rbd_export.to_python(_saved_graph(), "Saved", resolve_model=resolve_model,
                                exported_at=WHEN)
    assert calls and set(calls) == {"m-1"}
    # Parameters reordered to SurPyval's (mu, sigma), exactly as the app does.
    assert "bearing = surv.LogNormal.from_params([8.0, 0.5])" in code
    assert 'saved model "Bearing life (lognormal)"' in code
    assert "m-1" not in code  # no saved-artifact ids in the script
    res, _ = _run(code, tmp_path)
    import surpyval as surv

    for t, r in res["reliability"].items():
        assert r == pytest.approx(float(surv.LogNormal.from_params([8.0, 0.5]).sf(float(t))), rel=1e-12)


def test_block_parameters_win_over_resolver():
    """The app analyses the parameters stored on the block, so those are what
    the script uses even when the saved model could be read."""
    graph = _saved_graph()
    graph["nodes"][2]["data"]["model"].update(
        name="Stored", distribution_id="weibull",
        params=[{"name": "beta", "value": 1.5}, {"name": "alpha", "value": 1000}])
    code = rbd_export.to_python(
        graph, "Stored", exported_at=WHEN,
        resolve_model=lambda mid: {"kind": "distribution", "distribution_id": "exponential",
                                   "params": [{"name": "failure_rate", "value": 1.0}]})
    assert "bearing = surv.Weibull.from_params([1000.0, 1.5])" in code
    assert "Exponential" not in code


def test_ph_block_raises_with_helpful_message(tmp_path):
    ph = _node("ph", "component", "Valve seal",
               model={"source": "saved", "modelId": "m-ph", "kind": "regression",
                      "distribution": "Weibull PH"})
    graph = {"nodes": [*_io(), _node("ok", "component", "Pump", model=_w(900, 1.4)), ph],
             "edges": _chain("ok", "ph")}
    code = rbd_export.to_python(graph, "PH", exported_at=WHEN,
                                resolve_model=lambda mid: None)
    assert "TODO: placeholder" in code and "Valve seal" in code.split('"""')[1]
    _, proc = _run(code, tmp_path, expect_ok=False)
    assert proc.returncode != 0
    last = proc.stderr.strip().splitlines()[-1]
    assert last.startswith("NotImplementedError: Block 'Valve seal' uses a fitted proportional-hazards")
    assert "Set its parameters here" in last


def test_other_unexportable_blocks_are_marked_placeholders():
    graph = {
        "nodes": [
            *_io(),
            _node("np", "component", "KM", model={"source": "saved", "modelId": "x", "kind": "nonparametric"}),
            _node("ls", "loadshare", "Shared", model={"source": "saved", "modelId": "aft"}, load=5, units=3, k=2),
            _node("sub", "subsystem", "Nested", rbd={"id": "gone", "name": "Elsewhere"}),
            _node("none", "component", "Empty"),
            _node("pf", "component", "Pinned PH", state="failed",
                  model={"source": "saved", "modelId": "m", "kind": "regression"}),
            _node("ph2", "component", "Illustrative", model=_w(100, 1, placeholder=True)),
        ],
        "edges": _chain("np", "ls", "sub", "none", "pf", "ph2"),
    }
    code = rbd_export.to_python(graph, "Holes", exported_at=WHEN)
    compile(code, "holes.py", "exec")
    code = _flat(code)
    assert code.count("= missing_model(") == 4
    assert "non-parametric model" in code
    assert "LoadSharingModel" in code  # the how-to-rebuild hint
    assert "couldn't be included in this export" in code
    assert "has no life model in Reliafy" in code
    # A pinned block the script can't model stands in (like the app) instead
    # of stopping the script; it's forced failed via BROKEN_NODES.
    assert "pinned_ph = PerfectReliability" in code
    assert 'BROKEN_NODES = {"pf"}' in code
    assert "# NOTE: placeholder parameters" in code


def test_subsystem_cycle_becomes_placeholder():
    graph = {"nodes": [*_io(), _node("s", "subsystem", "Self", rbd={"id": "me", "name": "Me"})],
             "edges": _chain("s")}
    code = rbd_export.to_python(graph, "Loop", resolve_subsystem=lambda sid: graph,
                                exported_at=WHEN)
    assert "refers to itself (a cycle)" in _flat(code)


def test_repairable_pins_and_unsupported_blocks(tmp_path):
    rep = {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 1.0},
                                                      {"name": "sigma", "value": 0.4}]}
    graph = {
        "repairable": True, "unit": "hours",
        "nodes": [*_io(),
                  _node("a", "component", "Pump A", model=_w(900, 1.4), repair=rep),
                  _node("b", "component", "Pump B", model=_w(900, 1.4), repair=rep),
                  _node("g", "knode", "1oo2", n=1),
                  _node("pin", "component", "Spare line", state="working")],
        "edges": [{"source": "input", "target": "a"}, {"source": "input", "target": "b"},
                  {"source": "a", "target": "g"}, {"source": "b", "target": "g"},
                  {"source": "g", "target": "pin"}, {"source": "pin", "target": "output"}],
    }
    code = rbd_export.to_python(graph, "Rep", exported_at=WHEN)
    assert "spare_line = voting_gate()" in code and 'WORKING_NODES = {"pin"}' in code
    res, _ = _run(code, tmp_path, n_sims="20")
    rbd, _, _, working, broken = ra._build_repairable_rbd(graph)
    assert working == {"pin"} and not broken
    assert res["steady_state_availability"] == pytest.approx(
        rbd.mean_availability(working_nodes=working, broken_nodes=broken), rel=1e-12)

    # A block type availability mode doesn't support is a placeholder (the
    # app refuses to calculate it).
    graph["nodes"].append(_node("sb", "standby", "Dryers", model=_w(1, 1)))
    code = rbd_export.to_python(graph, "Rep", exported_at=WHEN)
    assert "dryers = missing_model(" in code and "'standby' block" in code


# ---------------------------------------------------------------------------
# Script hygiene
# ---------------------------------------------------------------------------
def test_output_is_deterministic_and_self_describing():
    graph, name = _sample("sample-rbd-instrument-air-design")
    a = rbd_export.to_python(graph, name, exported_at=WHEN)
    b = rbd_export.to_python(copy.deepcopy(graph), name, exported_at=WHEN)
    assert a == b
    compile(a, "x.py", "exec")
    head = a.split('"""')[1]
    assert head.startswith(name)
    assert "Exported from Reliafy <https://reliafy.com>".lower() in head.lower().replace("\n", " ")
    assert "on 2026-09-26 (UTC)" in head
    assert "SurPyval.git@v0.20.0" in head and "RePyability.git@v0.8.0" in head
    assert "--no-deps" in head and "surpyval==0.20.0" in head
    assert "python instrument_air_2oo3_compressors_cold_standby_dryer_ccf.py" in head
    # One commented variable per block, with its label.
    assert "# Compressor A: Weibull(alpha=12000 Hours, beta=1.6)" in a
    assert "compressor_a = surv.Weibull.from_params([12000.0, 1.6])" in a
    assert "CCFGroup(" in a and "BetaFactor(0.1)" in a
    assert '"vote": PerfectReliability,  # voting gate: 2 of its inputs must work' in a
    assert "K = {\"vote\": 2}" in a
    assert max(len(line) for line in a.splitlines()) <= 79


def test_imports_only_what_is_used():
    graph, name = _sample("sample-rbd-pump-station")
    code = rbd_export.to_python(graph, name, exported_at=WHEN)
    assert "from repyability import NonRepairableRBD\n" in code
    for unused in ("StandbyModel", "CCFGroup", "RepeatedNode", "missing_model", "voting_gate"):
        assert unused not in code


def test_versions_come_from_the_build_pins():
    assert rbd_export.detect_versions() == {"surpyval": "0.20.0", "repyability": "0.8.0"}


def test_names_are_safe_identifiers_and_unique():
    graph = {
        "nodes": [*_io(),
                  _node("a", "component", "Filter", model=_w(10, 1)),
                  _node("b", "component", "filter", model=_w(10, 1)),
                  _node("c", "component", "2nd stage \"quoted\" \\ label", model=_w(10, 1)),
                  _node("d", "component", "rbd", model=_w(10, 1))],
        "edges": _chain("a", "b", "c", "d"),
    }
    code = rbd_export.to_python(graph, 'Evil """ name \\', exported_at=WHEN)
    compile(code, "x.py", "exec")
    assert "filter_block = " in code and "filter_block_2 = " in code
    assert "block_2nd_stage_quoted_label = " in code
    assert "rbd_2 = " in code
    assert rbd_export.slugify('Evil """ name \\') == "evil_name"
    assert rbd_export.slugify("   ") == "reliability_block_diagram"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def _save(client, name="Cooling loop", graph=None):
    graph = graph or {
        "unit": "hours", "repairable": False, "ccf_groups": [],
        "nodes": [*_io(),
                  _node("ctrl", "component", "Controller",
                        model={**_w(2000, 1.6), "source": "saved", "modelId": "model-ctrl"}),
                  _node("pump", "component", "Pump", model=_w(900, 1.4))],
        "edges": _chain("ctrl", "pump"),
    }
    r = client.post("/api/rbds", json={"name": name, "graph": graph})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _assert_script(r, filename):
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/x-python")
    assert r.headers["content-disposition"] == f'attachment; filename="{filename}"'
    compile(r.text, filename, "exec")
    return r.text


def test_owner_downloads_and_non_owner_gets_404(client):
    client.act_as(B)  # register B
    client.act_as(A)
    rbd_id = _save(client)
    code = _assert_script(client.get(f"/api/rbds/{rbd_id}/export.py"), "cooling_loop.py")
    assert "controller = surv.Weibull.from_params([2000.0, 1.6])" in code
    assert "model-ctrl" not in code and A not in code

    client.act_as(B)
    assert client.get(f"/api/rbds/{rbd_id}/export.py").status_code == 404
    client.act_as(None)
    assert client.get(f"/api/rbds/{rbd_id}/export.py").status_code in (401, 403)


def test_share_recipient_can_download(client):
    client.act_as(B)
    client.act_as(A)
    rbd_id = _save(client, name="Shared plant")
    r = client.post("/api/shares", json={"collection": "rbds", "artifact_id": rbd_id,
                                         "email": "b@x.com"})
    assert r.status_code == 200, r.text
    client.act_as(B)
    _assert_script(client.get(f"/api/rbds/{rbd_id}/export.py"), "shared_plant.py")


def test_public_link_download(client):
    client.act_as(A)
    rbd_id = _save(client, name="Public plant")
    token = client.post("/api/public-links",
                        json={"collection": "rbds", "artifact_id": rbd_id}).json()["token"]
    client.act_as(None)
    code = _assert_script(client.get(f"/api/public/{token}/export.py"), "public_plant.py")
    assert "model-ctrl" not in code and A not in code and "Alice" not in code
    assert client.get("/api/public/not-a-token/export.py").status_code == 404

    # Revoked -> 404.
    client.act_as(A)
    client.delete(f"/api/public-links/{token}")
    client.act_as(None)
    assert client.get(f"/api/public/{token}/export.py").status_code == 404


def test_public_link_to_non_rbd_is_404(client):
    from backend.tests.test_public_links import _save_model

    client.act_as(A)
    model_id = _save_model(client)
    token = client.post("/api/public-links",
                        json={"collection": "models", "artifact_id": model_id}).json()["token"]
    client.act_as(None)
    assert client.get(f"/api/public/{token}/export.py").status_code == 404


def test_sample_download(client):
    from backend.services import samples as samples_service

    client.act_as(A)
    samples_service.seed_samples(client.db)
    _assert_script(client.get("/api/rbds/sample-rbd-instrument-air-availability/export.py"),
                   "instrument_air_availability_with_repair_times_sample.py")


def test_subsystem_resolves_in_the_viewers_scope(client):
    """A nested sub-system the owner saved is inlined; one pointing at another
    user's diagram is not (it becomes a placeholder)."""
    client.act_as(B)
    other = _save(client, name="Bs secret")
    client.act_as(A)
    inner = _save(client, name="Inner")
    graph = {
        "unit": "hours",
        "nodes": [*_io(),
                  _node("s1", "subsystem", "Mine", rbd={"id": inner, "name": "Inner"}),
                  _node("s2", "subsystem", "Theirs", rbd={"id": other, "name": "Theirs"})],
        "edges": _chain("s1", "s2"),
    }
    outer = _save(client, name="Outer", graph=graph)
    code = _assert_script(client.get(f"/api/rbds/{outer}/export.py"), "outer.py")
    assert "--- Sub-system 'Inner'" in code
    assert "Block 'Theirs' is a nested sub-system ('Theirs') that" in _flat(code)


def test_public_download_does_not_reveal_nested_subsystems(client):
    """The public page shows a nested sub-system only by name; its download
    must not inline the sub-system's blocks either (the owner's own export
    does)."""
    client.act_as(A)
    inner_graph = {
        "unit": "hours", "repairable": False, "ccf_groups": [],
        "nodes": [*_io(), _node("secret", "component", "Proprietary valve", model=_w(4321, 2.2))],
        "edges": _chain("secret"),
    }
    inner = _save(client, name="Inner", graph=inner_graph)
    outer_graph = {
        "unit": "hours", "repairable": False, "ccf_groups": [],
        "nodes": [*_io(), _node("s1", "subsystem", "Skid", rbd={"id": inner, "name": "Inner"})],
        "edges": _chain("s1"),
    }
    outer = _save(client, name="Outer public", graph=outer_graph)
    own = _assert_script(client.get(f"/api/rbds/{outer}/export.py"), "outer_public.py")
    assert "Proprietary valve" in own  # the owner gets the full diagram

    token = client.post("/api/public-links",
                        json={"collection": "rbds", "artifact_id": outer}).json()["token"]
    client.act_as(None)
    pub = _assert_script(client.get(f"/api/public/{token}/export.py"), "outer_public.py")
    assert "Proprietary valve" not in pub and "4321" not in pub and inner not in pub
    assert "Skid" in pub  # the block is still there, as an explained placeholder
