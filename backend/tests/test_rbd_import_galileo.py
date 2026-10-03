"""Galileo DFT import (backend/services/rbd_import/galileo.py).

All fixtures are hand-written for these tests.
"""

import json
import math

import numpy as np
import pytest
from scipy import stats

from backend.services import rbd_analysis
from backend.services.rbd_graph import normalize_graph
from backend.services.rbd_import import galileo
from backend.services.rbd_import.types import RbdImportError


def load(text: str, filename: str = "model.dft"):
    (d,) = galileo.parse(text.encode(), filename)
    normalize_graph(d.graph)  # every import must be a valid compact graph
    return d


def by_label(graph, label):
    (node,) = [n for n in graph["nodes"] if n.get("label") == label]
    return node


def by_label_original(graph, label):
    """The block of an event drawn in several places (not its repeats)."""
    (node,) = [n for n in graph["nodes"] if n.get("label") == label and not n.get("repeat_of")]
    return node


def analyse(d, t_max=None):
    return rbd_analysis.analyze(normalize_graph(d.graph), t_max=t_max)


# ---------------------------------------------------------------------------
# Parsing and static gates
# ---------------------------------------------------------------------------


def test_sniff():
    assert galileo.sniff(b"anything", "x.dft")
    assert galileo.sniff(b'toplevel "T";\n"T" or "A";', "upload.txt")
    assert galileo.sniff(b'{"toplevel": "1", "nodes": []}', "x.json")
    assert not galileo.sniff(b"<opsa-mef/>", "x.xml")
    assert not galileo.sniff(b"a,b,c\n1,2,3", "x.csv")


def test_static_tree_matches_closed_form_reliability_and_mttf():
    d = load("""
        // a pump train: controller in series with a 2-of-3 voted sensor bank
        toplevel "Sys";
        "Sys" or "Ctrl" "Sensors";
        "Sensors" 2of3 "S1" "S2" "S3";   /* fails when 2 of 3 sensors fail */
        "Ctrl" lambda=1e-4;
        "S1" lambda = 1e-3;
        S2 lambda=1e-3;
        "S3" lambda=1e-3;
    """)
    assert d.warnings == [] and not d.graph.get("repairable")
    vote = [n for n in d.graph["nodes"] if n["type"] == "knode"]
    assert [(v["n"], v["k"]) for v in vote] == [(2, 3)]  # 2 of 3 must WORK
    res = analyse(d, t_max=3000)
    t = np.asarray(res["time"])
    r = np.exp(-1e-3 * t)
    expected = np.exp(-1e-4 * t) * (3 * r**2 - 2 * r**3)
    assert np.allclose(res["system"]["sf"], expected, rtol=1e-9, atol=1e-12)
    # MTTF = ∫ e^{-at}(3e^{-2bt} - 2e^{-3bt}) dt
    mttf = 3 / (1e-4 + 2e-3) - 2 / (1e-4 + 3e-3)
    assert res["mttf"] == pytest.approx(mttf, rel=1e-3)


def test_kofm_with_wrong_m_is_read_by_child_count_with_a_warning():
    d = load('toplevel "T"; "T" 2of4 "A" "B" "C"; "A" lambda=1; "B" lambda=1; "C" lambda=1;')
    assert any("2of4" in w and "2 of 3" in w for w in d.warnings)
    (v,) = [n for n in d.graph["nodes"] if n["type"] == "knode"]
    assert (v["n"], v["k"]) == (2, 3)


def test_erlang_phases_become_a_gamma_with_integer_shape():
    d = load('toplevel "A"; "A" lambda=0.5 phases=3;')
    node = by_label(d.graph, "A")
    assert node["model"]["distribution_id"] == "gamma"
    res = analyse(d, t_max=20)
    t = np.asarray(res["time"])
    assert np.allclose(res["system"]["sf"], stats.gamma.sf(t, a=3, scale=2.0), atol=1e-12)


def test_storm_weibull_and_lognormal_attributes():
    d = load('toplevel "T"; "T" or "W" "L"; "W" shape=2 rate=100; "L" mean=4 stddev=0.5;')
    w, ln = by_label(d.graph, "W")["model"], by_label(d.graph, "L")["model"]
    assert w == {"distribution_id": "weibull",
                 "params": [{"name": "alpha", "value": 100.0}, {"name": "beta", "value": 2.0}]}
    assert ln["distribution_id"] == "lognormal" and ln["params"][0]["value"] == 4.0


def test_constant_events_fold_away():
    d = load("""toplevel "T";
        "T" or "A" "G";
        "G" and "B" "Never" "Always";
        "A" lambda=1e-3; "B" lambda=1e-3;
        "Never" prob=0; "Always" prob=1; "Z" lambda=0;""")
    labels = {n.get("label") for n in d.graph["nodes"]}
    assert "Never" not in labels and "Always" not in labels
    # G = AND(B, never) can't fail, so the system is just A.
    assert labels == {"Input", "Output", "A"}


@pytest.mark.parametrize("attrs, match", [
    ("prob=0.3", "fixed failure probability"),
    ("lambda=1e-3 prob=0.5", "only with probability"),
    ("lambda=1e-3 cov=0.9", "coverage"),
    ("lambda=1e-3 repl=2", "replicated"),
    ("mu=3 sigma=1", r"mu=, sigma="),
    ("lambda=x", "isn't a number"),
    ("lambda=-1", "non-negative"),
    ("lambda=1 phases=2.5", "whole number"),
])
def test_unsupported_event_attributes_are_refused(attrs, match):
    with pytest.raises(RbdImportError, match=match):
        load(f'toplevel "T"; "T" or "A" "B"; "A" {attrs}; "B" lambda=1;')


def test_restoration_factor_thins_the_rate():
    d = load('toplevel "A"; "A" lambda=0.01 res=0.25;')
    assert by_label(d.graph, "A")["model"]["params"][0]["value"] == pytest.approx(0.0075)
    assert any("res=0.25" in w for w in d.warnings)


@pytest.mark.parametrize("gate", ["pand", "seq", "fdep", "mutex", "por"])
def test_dynamic_gates_are_refused_by_name(gate):
    with pytest.raises(RbdImportError, match=rf"“G”.*\({gate}\)"):
        load(f'toplevel "T"; "T" or "G" "C"; "G" {gate} "A" "B"; "A" lambda=1; "B" lambda=1; "C" lambda=1;')


def test_fdep_outside_the_tree_is_still_refused():
    # FFORT allows FDEPs as separate roots; they still change the semantics.
    with pytest.raises(RbdImportError, match="functional dependency"):
        load('toplevel "T"; "T" and "A" "B"; "D" fdep "Trig" "A"; '
             '"A" lambda=1; "B" lambda=1; "Trig" lambda=1;')


def test_inspection_modules_are_refused():
    with pytest.raises(RbdImportError, match="inspection"):
        load('toplevel "T"; "T" or "A"; "I" 2insp4 "A"; "A" lambda=1 phases=2 interval=1;')


def test_structural_errors():
    with pytest.raises(RbdImportError, match="toplevel"):
        load('"T" or "A"; "A" lambda=1;')
    with pytest.raises(RbdImportError, match="isn't defined"):
        load('toplevel "T"; "T" or "A" "Missing"; "A" lambda=1;')
    with pytest.raises(RbdImportError, match="defined twice"):
        load('toplevel "T"; "T" or "A"; "A" lambda=1; "A" lambda=2;')
    with pytest.raises(RbdImportError, match="unknown gate type"):
        load('toplevel "T"; "T" nor "A" "B"; "A" lambda=1; "B" lambda=1;')
    with pytest.raises(RbdImportError, match="parametric"):
        load('param x; toplevel "T"; "T" or "A"; "A" lambda=x;')


def test_repeated_event_is_a_repeated_block_and_exact():
    # A shared support event A under both trains: T fails if A and B fail, or
    # A and C fail — i.e. A fails and (B or C) fails.
    d = load('toplevel "T"; "T" or "G1" "G2"; "G1" and "A" "B"; "G2" and "A" "C"; '
             '"A" lambda=1; "B" lambda=2; "C" lambda=3;')
    (copy,) = [n for n in d.graph["nodes"] if n.get("repeat_of")]
    assert copy["repeat_of"] == by_label_original(d.graph, "A")["id"]
    assert any("repeated block" in w for w in d.warnings)
    res = analyse(d, t_max=1.0)
    t = np.asarray(res["time"])
    qa, qb, qc = (1 - np.exp(-r * t) for r in (1, 2, 3))
    expected = 1 - qa * (1 - (1 - qb) * (1 - qc))
    assert np.allclose(res["system"]["sf"], expected, rtol=1e-9, atol=1e-12)
    # One importance row per component (A, B, C), not per drawn block.
    assert len(res["importance"]["birnbaum"]) == 3


def test_repeated_events_drop_repair_rates():
    d = load('toplevel "T"; "T" or "G1" "G2"; "G1" and "A" "B"; "G2" and "A" "C"; '
             '"A" lambda=1 repair=5; "B" lambda=1 repair=5; "C" lambda=1 repair=5;')
    assert not d.graph.get("repairable")
    assert any("non-repairable" in w for w in d.warnings)


def test_spare_gate_under_two_gates_is_refused():
    with pytest.raises(RbdImportError, match="“P”.*more than one gate"):
        load('toplevel "T"; "T" or "G1" "G2"; "G1" and "P" "B"; "G2" and "P" "C"; '
             '"P" csp "P1" "P2"; "P1" lambda=1; "P2" lambda=1; "B" lambda=1; "C" lambda=1;')


# ---------------------------------------------------------------------------
# Spare gates -> standby blocks
# ---------------------------------------------------------------------------


def test_cold_spare_is_an_exact_erlang_standby():
    lam = 1e-3
    d = load(f'toplevel "P"; "P" csp "A" "S1" "S2"; "A" lambda={lam}; "S1" lambda={lam}; "S2" lambda={lam};')
    node = by_label(d.graph, "P")
    assert (node["type"], node["spares"], node["cold"]) == ("standby", 2, True)
    res = analyse(d, t_max=5000)
    t = np.asarray(res["time"])
    assert np.allclose(res["system"]["sf"], stats.gamma.sf(t, a=3, scale=1 / lam), atol=1e-9)
    assert res["mttf"] == pytest.approx(3 / lam, rel=1e-3)


def test_hot_spare_is_active_parallel():
    lam = 1e-3
    d = load(f'toplevel "P"; "P" hsp "A" "S"; "A" lambda={lam}; "S" lambda={lam};')
    node = by_label(d.graph, "P")
    assert node["cold"] is False
    res = analyse(d)
    assert res["mttf"] == pytest.approx(1.5 / lam, rel=1e-3)


def test_warm_spare_is_imported_as_warm_standby_and_matches_the_closed_form():
    d = load('toplevel "P"; "P" wsp "A" "S"; "A" lambda=1; "S" lambda=1 dorm=0.3;')
    node = by_label(d.graph, "P")
    assert node["dormancy"] == 0.3 and node["cold"] is False and not d.warnings
    # One active + one warm spare, both exponential(1), dormancy 0.3: the first
    # failure comes at rate 1.3 (active + idle spare), then rate 1 — a
    # hypoexponential life, R(t) = (a e^{-bt} - b e^{-at}) / (a - b).
    res = rbd_analysis.analyze(normalize_graph(d.graph), t_max=4.0)
    t = np.asarray(res["time"])
    a, b = 1.3, 1.0
    exact = (a * np.exp(-b * t) - b * np.exp(-a * t)) / (a - b)
    assert np.asarray(res["system"]["sf"]) == pytest.approx(exact, abs=1e-9)
    # Explicit dormancy 0 on a wsp is a cold spare; 1 is hot.
    cold = by_label(load('toplevel "P"; "P" wsp "A" "S"; "A" lambda=1; "S" lambda=1 dorm=0;').graph, "P")
    assert cold["cold"] is True and cold["dormancy"] == 0
    hot = by_label(load('toplevel "P"; "P" csp "A" "S"; "A" lambda=1; "S" lambda=1 dorm=1;').graph, "P")
    assert hot["cold"] is False and hot["dormancy"] == 1


def test_spares_with_different_dormancy_use_the_highest_with_a_warning():
    d = load('toplevel "P"; "P" wsp "A" "S" "T"; "A" lambda=1; "S" lambda=1 dorm=0.2; "T" lambda=1 dorm=0.5;')
    assert by_label(d.graph, "P")["dormancy"] == 0.5
    assert any("different dormancy" in w and "conservative" in w for w in d.warnings)


def test_spare_with_a_different_distribution_uses_standby_model():
    d = load('toplevel "P"; "P" csp "A" "S"; "A" lambda=0.01; "S" lambda=0.02;')
    g = normalize_graph(d.graph)
    (node,) = [n for n in g["nodes"] if n["type"] == "standby"]
    assert node["data"]["standbyModel"]["params"][0]["value"] == 0.02
    res = rbd_analysis.analyze(g)
    assert res["mttf"] == pytest.approx(1 / 0.01 + 1 / 0.02, rel=1e-3)


def test_spare_gate_restrictions():
    with pytest.raises(RbdImportError, match="shares “S”"):
        load('toplevel "T"; "T" and "P1" "P2"; "P1" csp "A" "S"; "P2" csp "B" "S"; '
             '"A" lambda=1; "B" lambda=1; "S" lambda=1;')
    with pytest.raises(RbdImportError, match="spare module"):
        load('toplevel "P"; "P" csp "A" "M"; "M" and "B" "C"; "A" lambda=1; "B" lambda=1; "C" lambda=1;')
    with pytest.raises(RbdImportError, match="different failure distributions"):
        load('toplevel "P"; "P" csp "A" "S1" "S2"; "A" lambda=1; "S1" lambda=1; "S2" lambda=2;')


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def test_repair_on_every_event_makes_a_repairable_diagram():
    d = load('toplevel "T"; "T" or "A" "V"; "V" 2of3 "B1" "B2" "B3"; '
             '"A" lambda=1e-3 repair=0.5; "B1" lambda=1e-2 repair=1; '
             '"B2" lambda=1e-2 repair=1; "B3" lambda=1e-2 repair=1;')
    g = d.graph
    assert g["repairable"] is True
    assert by_label(g, "A")["repair"] == {"distribution_id": "exponential",
                                          "params": [{"name": "failure_rate", "value": 0.5}]}
    assert rbd_analysis.validate_graph(normalize_graph(g))["valid"]


def test_partial_repair_or_spares_drop_repair_with_a_warning():
    d = load('toplevel "T"; "T" or "A" "B"; "A" lambda=1 repair=2; "B" lambda=1;')
    assert not d.graph.get("repairable") and "repair" not in by_label(d.graph, "A")
    assert any("not every basic event" in w for w in d.warnings)
    d = load('toplevel "T"; "T" or "A" "P"; "P" csp "B" "S"; '
             '"A" lambda=1 repair=2; "B" lambda=1 repair=2; "S" lambda=1 repair=2;')
    assert not d.graph.get("repairable")
    assert any("spare gates" in w for w in d.warnings)


# ---------------------------------------------------------------------------
# Storm JSON
# ---------------------------------------------------------------------------


def _json_model():
    def node(i, **data):
        return {"data": {"id": str(i), **data}, "position": {"x": 0, "y": 0}, "group": "nodes"}

    return {
        "toplevel": "0",
        "nodes": [
            node(0, name="Top", type="or", children=["1", "2", "7"]),
            node(1, name="Vote", type="vot", voting="2", children=["3", "4", "5"]),
            node(2, name="Spare", type="spare", children=["6", "8"]),
            node(3, name="C1", type="be_exp", distribution="exponential", rate="0.001", dorm="1"),
            node(4, name="C2", type="be_exp", distribution="exponential", rate="0.001", dorm="1"),
            node(5, name="C3", type="be_exp", distribution="exponential", rate="0.001", dorm="1"),
            node(6, name="Main", type="be", distribution="erlang", rate="0.01", phases=2, dorm="0"),
            node(8, name="Backup", type="be", distribution="erlang", rate="0.01", phases=2, dorm="0"),
            node(7, name="Never", type="be", distribution="const", failed=False),
        ],
    }


def test_storm_json_variant():
    d = load(json.dumps(_json_model()), "model.json")
    g = d.graph
    v = by_label(g, "Vote")
    assert (v["type"], v["n"], v["k"]) == ("knode", 2, 3)
    s = by_label(g, "Spare")
    assert (s["type"], s["cold"]) == ("standby", True)
    assert s["model"]["distribution_id"] == "gamma"
    assert "Never" not in {n.get("label") for n in g["nodes"]}


def test_storm_json_rejects_probability_events_and_dynamic_gates():
    m = _json_model()
    m["nodes"][-1]["data"].update(distribution="probability", prob="0.2")
    with pytest.raises(RbdImportError, match="fixed failure probability"):
        load(json.dumps(m), "m.json")
    m = _json_model()
    m["nodes"][1]["data"]["type"] = "pand"
    with pytest.raises(RbdImportError, match="priority-AND"):
        load(json.dumps(m), "m.json")
    with pytest.raises(RbdImportError, match="valid JSON"):
        load("{nope", "m.json")


def test_dispatcher_routes_dft_files(monkeypatch):
    import backend.services.rbd_import as rbd_import

    # Only the formats this change adds (the BlockSim module lands separately).
    monkeypatch.setattr(rbd_import, "FORMATS", {"openpsa": "Open-PSA MEF", "galileo": "Galileo DFT"})
    (d,) = rbd_import.import_file(b'toplevel "A"; "A" lambda=1;', "a.dft")
    assert d.source_format == "Galileo DFT" and d.name == "a"


def test_mttf_of_exponential_series_is_exact():
    d = load('toplevel "T"; "T" or "A" "B"; "A" lambda=0.002; "B" lambda=0.003;')
    assert analyse(d)["mttf"] == pytest.approx(1 / 0.005, rel=1e-3)
    assert math.isclose(1 / 0.005, 200.0)
