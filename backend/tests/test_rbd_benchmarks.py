"""Reliafy's RBD analysis vs published fault-tree benchmark results.

Reference values come from FFORT, the "Fault tree FORest" benchmark suite
(https://dftbenchmarks.utwente.nl/ffort/). FFORT publishes no licence for its
model files, so none are copied here: the fixtures below are re-expressed by
hand from the systems described in the cited papers, and the reference
numbers (facts) are quoted with their source.

Each model goes through the real pipeline: Galileo import -> normalize_graph
-> the analysis entry point the API uses (``rbds.analyze_graph``: the
reliability path, or the availability path for repairable diagrams).

Static benchmark trees give every basic event a fixed probability ``p``.
Reliafy blocks need a life distribution, so the tests give each event an
exponential life with rate ``-ln(1 - p)``: its unreliability at ``t = 1`` is
exactly ``p``, and so the system unreliability at ``t = 1`` must equal the
published top-event probability.

The full FFORT sweep (every importable model with a reference value) runs
when ``RELIAFY_FFORT_DIR`` points at an FFORT checkout (the directory holding
``indexDFT.json`` and ``models/``); it is skipped otherwise.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pytest
from scipy.linalg import expm

from backend.services import rbd_analysis, rbds
from backend.services.rbd_graph import normalize_graph
from backend.services.rbd_import import galileo
from backend.services.rbd_import.types import RbdImportError


def probs_to_rates(text: str) -> str:
    """``prob=p`` -> ``lambda=-ln(1-p)`` so that F(1) = p exactly."""

    def rep(m):
        p = float(m.group(1))
        return f"lambda={-math.log1p(-p)!r}" if 0 < p < 1 else m.group(0)

    return re.sub(r"prob\s*=\s*([0-9.eE+-]+)", rep, text)


def import_graph(text: str, name: str = "model.dft") -> dict:
    (d,) = galileo.parse(text.encode(), name)
    return normalize_graph(d.graph)


def unreliability_at(graph: dict, t: float) -> float:
    g = {k: v for k, v in graph.items() if k != "repairable"}
    res = rbds.analyze_graph(None, g, "benchmark", t_max=t)
    assert res["time"][-1] == pytest.approx(t)
    return res["system"]["ff"][-1]


def rel_tol_for(value: float) -> float:
    """Reliafy reports F(t) as 1 - R(t); for tiny F the subtraction loses
    ~1e-16 / F of relative precision. Allow that (and never less than 1e-9)."""
    return max(1e-9, 50 * np.finfo(float).eps / value)


# ---------------------------------------------------------------------------
# Static trees (discrete probabilities)
# ---------------------------------------------------------------------------

# Pressure tank rupture — NASA Fault Tree Handbook with Aerospace Applications
# (Stamatelatos et al., 2002; a US Government work). FFORT "pt", DFTCalc (Exact):
# 3.5013348120867e-5.
PRESSURE_TANK = """
toplevel "Rupture";
"Rupture" or "TankRupture" "OverPressure";
"OverPressure" or "MotorRunsTooLong" "RelayK2Contacts";
"MotorRunsTooLong" and "SwitchS" "TimerCircuit";
"TimerCircuit" or "SwitchS1" "RelayK1Branch";
"RelayK1Branch" or "RelayK1Contacts" "TimerRelay";
"TankRupture" prob=5.0e-6;
"RelayK2Contacts" prob=3.0e-5;
"SwitchS" prob=1.0e-4;
"SwitchS1" prob=3.0e-5;
"RelayK1Contacts" prob=5.0e-6;
"TimerRelay" prob=1.0e-4;
"""

# Compression-seal design — NASA Fault Tree Handbook (2002). FFORT "csd",
# DFTCalc (Exact): 1.000000999999e-6.
SEALS = """
toplevel "Leak";
"Leak" or "CommonCause" "Independent";
"CommonCause" and "TapeContaminated" "CommonCauseEvent";
"Independent" and "MetalSeal" "CompressionSeals" "FusedPlug";
"CompressionSeals" and "Seal1" "Seal2";
"TapeContaminated" prob=1.0e-1;
"CommonCauseEvent" prob=1.0e-5;
"MetalSeal" prob=1.0e-3;
"FusedPlug" prob=1.0e-3;
"Seal1" prob=1.0e-3;
"Seal2" prob=1.0e-3;
"""

# Spread mooring system, alternative A1 — Mentes & Helvacioglu, "An
# application of fuzzy fault tree analysis for spread mooring systems",
# Ocean Engineering 2011 (doi:10.1016/j.oceaneng.2010.11.003). FFORT
# "SMS_A1", DFTCalc (Exact): 0.026246389824230341.
MOORING = """
toplevel "MooringFailure";
"MooringFailure" or "TopAnchor" "BottomAnchor" "MooringLine" "Buoy" "Human" "LoadHandling";
"TopAnchor" or "TopAnchorCable";
"BottomAnchor" or "BottomAnchorCable";
"MooringLine" or "MooringLineCable";
"Buoy" or "BuoyHook";
"Human" or "HumanShip" "HumanLand";
"BottomAnchorCable" or "North" "South" "East" "West";
"LoadHandling" prob=1.73e-5;
"TopAnchorCable" prob=4.20e-3;
"MooringLineCable" prob=9.31e-3;
"BuoyHook" prob=8.64e-3;
"HumanShip" prob=8.95e-6;
"HumanLand" prob=8.95e-6;
"North" prob=9.93e-5;
"South" prob=4.37e-5;
"East" prob=5.46e-8;
"West" prob=4.17e-3;
"""


def _or(*p):
    return 1 - math.prod(1 - x for x in p)


def _pressure_tank_exact():
    e5 = _or(5.0e-6, 1.0e-4)
    e4 = _or(3.0e-5, e5)
    return _or(5.0e-6, _or(1.0e-4 * e4, 3.0e-5))


STATIC_CASES = [
    # (id, model, published reference, independent closed form)
    ("pressure-tank", PRESSURE_TANK, 3.5013348120867e-5, _pressure_tank_exact()),
    ("compression-seals", SEALS, 1.000000999999e-6,
     _or(1e-1 * 1e-5, 1e-3 * 1e-3 * 1e-3 * 1e-3)),
    ("mooring-A1", MOORING, 0.026246389824230341,
     _or(1.73e-5, 4.20e-3, 9.31e-3, 8.64e-3, 8.95e-6, 8.95e-6, 9.93e-5, 4.37e-5, 5.46e-8, 4.17e-3)),
]


@pytest.mark.parametrize("name, model, reference, exact", STATIC_CASES, ids=[c[0] for c in STATIC_CASES])
def test_static_tree_unreliability_matches_published_value(name, model, reference, exact):
    graph = import_graph(probs_to_rates(model))
    value = unreliability_at(graph, 1.0)
    # Against the independent closed form: exact to floating point.
    assert value == pytest.approx(exact, rel=rel_tol_for(exact))
    # Against the published DFTCalc value. (For the pressure tank DFTCalc's
    # figure differs from the closed form in the 8th digit — 3.5013348e-5 vs
    # 3.50133492e-5 — so compare at 1e-7.)
    assert value == pytest.approx(reference, rel=1e-7)


def test_static_tree_import_refuses_plain_probabilities():
    with pytest.raises(RbdImportError, match="fixed failure probability"):
        import_graph(PRESSURE_TANK)


# ---------------------------------------------------------------------------
# Radio Block Centre (repairable)
# ---------------------------------------------------------------------------

# ERTMS/ETCS Radio Block Centre — Flammini, Mazzocca, Iacono & Marrone, "Using
# Repairable Fault Trees for the evaluation of design choices for critical
# repairable systems", HASE 2005 (doi:10.1109/HASE.2005.26); FFORT "rbc"
# (rates per hour; online repair only, each component repaired independently).
RBC = """
toplevel "RBC";
"RBC" or "Power" "WAN" "Bus" "GSMR" "TMR";
"Power" and "PSU1" "PSU2" "PSU3";
"WAN" and "WAN1" "WAN2";
"Bus" and "Bus1" "Bus2";
"GSMR" and "GSMR1" "GSMR2";
"TMR" or "CPUs" "Voter";
"CPUs" 2of3 "CPU1" "CPU2" "CPU3";
"Voter" and "FPGA1" "FPGA2";
"Bus1" lambda=4.4444e-6 repair=4;
"Bus2" lambda=4.4444e-6 repair=4;
"FPGA1" lambda=3.003e-9 repair=4;
"FPGA2" lambda=3.003e-9 repair=4;
"PSU1" lambda=1.8182e-5 repair=6;
"PSU2" lambda=1.8182e-5 repair=6;
"PSU3" lambda=1.8182e-5 repair=6;
"WAN1" lambda=2.5e-6 repair=6;
"WAN2" lambda=2.5e-6 repair=6;
"GSMR1" lambda=5.7078e-6 repair=6;
"GSMR2" lambda=5.7078e-6 repair=6;
"CPU1" lambda=7.4074e-6 repair=6;
"CPU2" lambda=7.4074e-6 repair=6;
"CPU3" lambda=7.4074e-6 repair=6;
"""
# Published (FFORT, DFTCalc Exact): steady-state unavailability
# 6.8855993019126e-12 and unreliability at t = 1 h of 2.231940944647528e-10.
# (FFORT also lists SHARPE results of 1.3e-6 .. 3.4e-6 from the paper; those
# include an off-line repair policy / limited repair crews that the .dft
# omits, so they don't describe this model.)
RBC_UNAVAILABILITY = 6.8855993019126e-12
RBC_UNRELIABILITY_1H = 2.231940944647528e-10

# RBC subsystems as (units, failed units that fail the subsystem, λ, μ).
RBC_SUBSYSTEMS = [(3, 3, 1.8182e-5, 6), (2, 2, 2.5e-6, 6), (2, 2, 4.4444e-6, 4),
                  (2, 2, 5.7078e-6, 6), (3, 2, 7.4074e-6, 6), (2, 2, 3.003e-9, 4)]


def _subsystem_ctmc(n, fail_at, lam, mu):
    """Generator of an n-unit subsystem (independent repair) with the
    failed state absorbing."""
    q = np.zeros((fail_at + 1, fail_at + 1))
    for i in range(fail_at):
        q[i, i + 1] = (n - i) * lam
        if i:
            q[i, i - 1] = i * mu
        q[i, i] = -q[i].sum()
    return q


def _rbc_oracle():
    """Independent exact figures for the RBC under independent repair."""
    unavail_parts, omega = [], 0.0
    for n, f, lam, mu in RBC_SUBSYSTEMS:
        qi = lam / (lam + mu)
        # P(subsystem down) = P(at least f of n failed), units independent.
        p_down = sum(math.comb(n, j) * qi**j * (1 - qi) ** (n - j) for j in range(f, n + 1))
        unavail_parts.append(p_down)
        # Its steady-state failure frequency: from exactly f-1 failed, one more fails.
        omega += math.comb(n, f - 1) * qi ** (f - 1) * (1 - qi) ** (n - f + 1) * (n - f + 1) * lam
    unavail = 1 - math.prod(1 - p for p in unavail_parts)
    mttff = 1 / sum(1 / _mttf(_subsystem_ctmc(n, f, lam, mu)) for n, f, lam, mu in RBC_SUBSYSTEMS)
    return unavail, omega, mttff


def _mttf(q):
    return float((-np.linalg.inv(q[:-1, :-1])).sum(axis=1)[0])


@pytest.fixture(scope="module")
def rbc_availability():
    graph = import_graph(RBC, "rbc.dft")
    assert graph["repairable"] is True
    old = rbd_analysis._AVAIL_SIMS
    rbd_analysis._AVAIL_SIMS = 50  # the Monte-Carlo part isn't compared; keep it quick
    try:
        return graph, rbds.analyze_graph(None, graph, "benchmark")
    finally:
        rbd_analysis._AVAIL_SIMS = old


def _voting_gate_standin():
    """Unavailability and failure frequency of the never-failing stand-in
    Reliafy uses for a k-of-n gate in availability analysis."""
    gate = rbd_analysis._always_up()
    return 1 - float(gate.mean_availability()), float(gate.failure_frequency())


def test_rbc_oracle_agrees_with_published_unavailability():
    unavail, _, _ = _rbc_oracle()
    assert unavail == pytest.approx(RBC_UNAVAILABILITY, rel=1e-6)


@pytest.mark.xfail(strict=True, reason=(
    "Reliafy discrepancy: in availability analysis each k-of-n gate is modelled as a component "
    "that 'never fails' (Weibull scale 1e12 h with a LogNormal(0.1, 0.1) repair), which is "
    "unavailable 1.1e-12 of the time and fails 1e-12 times per hour. RBC's 2-of-3 CPU gate "
    "sits in series, so Reliafy reports 7.9963e-12 instead of 6.8856e-12 (+16%)."))
def test_rbc_steady_state_unavailability(rbc_availability):
    _, res = rbc_availability
    assert res["unavailability"] == pytest.approx(RBC_UNAVAILABILITY, rel=1e-6)


@pytest.mark.xfail(strict=True, reason=(
    "Same voting-gate stand-in: its 1e-12/h failure frequency is added to the system's "
    "(7.77e-11/h), so the exact mean up time comes out 1.271e10 h instead of 1.287e10 h."))
def test_rbc_mean_up_time_against_markov_oracle(rbc_availability):
    _, res = rbc_availability
    _, omega, mttff = _rbc_oracle()
    assert res["figures_basis"]["mean_up_time"] == "exact"
    assert res["mean_up_time"] == pytest.approx((1 - RBC_UNAVAILABILITY) / omega, rel=1e-6)
    # For a system this available, MUT ≈ mean time to first failure.
    assert res["mean_up_time"] == pytest.approx(mttff, rel=1e-3)


def test_rbc_discrepancy_is_exactly_the_voting_gate_standin(rbc_availability):
    """Pins the diagnosis of the two xfails: removing the stand-in's
    contribution recovers the published / oracle values."""
    graph, res = rbc_availability
    gates = [n for n in graph["nodes"] if n["type"] == "knode"]
    assert len(gates) == 1  # only the 2-of-3 CPU vote (no junctions needed)
    q_gate, w_gate = _voting_gate_standin()
    # Series composition: A_sys = A_rest * A_gate.
    a_rest = (1 - res["unavailability"]) / (1 - q_gate)
    assert 1 - a_rest == pytest.approx(RBC_UNAVAILABILITY, rel=1e-4)
    _, omega, _ = _rbc_oracle()
    assert res["failure_frequency"] - w_gate * a_rest == pytest.approx(omega, rel=1e-4)


def test_rbc_unreliability_at_one_hour():
    """FFORT's DFTCalc unreliability at t = 1 h equals the *no-repair*
    unreliability (with repairs it would be ~6.4e-11 by the subsystem Markov
    chains). Reliafy's reliability analysis of the same diagram (repair
    ignored) reproduces it."""
    graph = import_graph(RBC, "rbc.dft")
    value = unreliability_at(graph, 1.0)
    assert value == pytest.approx(RBC_UNRELIABILITY_1H, rel=rel_tol_for(RBC_UNRELIABILITY_1H))
    with_repair = 1 - math.prod(
        1 - float(expm(_subsystem_ctmc(n, f, lam, mu))[0, -1]) for n, f, lam, mu in RBC_SUBSYSTEMS)
    assert with_repair < 0.3 * value


# ---------------------------------------------------------------------------
# Full FFORT sweep (opt-in: needs a local FFORT checkout)
# ---------------------------------------------------------------------------

FFORT_DIR = os.environ.get("RELIAFY_FFORT_DIR")
# Imports fine, but Reliafy's full analysis enumerates all minimal path sets
# (5,832 here) and converts them to cut sets, which doesn't finish in minutes;
# the reliability itself is checked on the same RBD object the analysis builds.
_SF_ONLY = {"wqdn/WQDN.dft"}


def _parse_reference(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    m = re.match(r"^([0-9.]*)\[([0-9.]+);\s*[0-9.]+\](.*)$", value)
    if m:  # DFTCalc interval notation "0.0262463898242303410[1; 2]"
        value = m.group(1) + m.group(2) + m.group(3)
    try:
        return float(value)
    except ValueError:
        return None


def _ffort_cases():
    if not FFORT_DIR:
        return []
    root = Path(FFORT_DIR)
    cases = []
    for family in json.loads((root / "indexDFT.json").read_text()):
        for model in family["models"]:
            rel = model["filename"].split("fault_trees/", 1)[1]
            for r in model.get("results") or []:
                ref = _parse_reference(r.get("value"))
                exact = "Exact" in (r.get("tool") or "")
                if ref is None or not exact or r["type"] != "Unreliability":
                    continue
                cases.append(pytest.param(rel, r.get("time"), ref, id=f"{rel}@{r.get('time')}"))
    return cases


@pytest.mark.skipif(not FFORT_DIR, reason="set RELIAFY_FFORT_DIR to an FFORT checkout to run the sweep")
@pytest.mark.parametrize("rel, time, reference", _ffort_cases() or [pytest.param(None, None, None, id="none")])
def test_ffort_sweep_unreliability(rel, time, reference):
    if rel == "rbc/rbc.dft":
        pytest.skip("covered by test_rbc_unreliability_at_one_hour")
    text = (Path(FFORT_DIR) / "models" / rel).read_text()
    discrete = "lambda" not in text
    try:
        graph = import_graph(probs_to_rates(text), os.path.basename(rel))
    except RbdImportError as exc:
        pytest.skip(f"not importable: {exc}")
    t = 1.0 if discrete else float(time or 1.0)
    if rel in _SF_ONLY:
        rbd = rbd_analysis._build_rbd({k: v for k, v in graph.items() if k != "repairable"})[0]
        value = 1 - float(rbd.sf(np.array([t]))[0])
    else:
        value = unreliability_at(graph, t)
    assert value == pytest.approx(reference, rel=max(1e-7, rel_tol_for(reference)))
