"""Where a safety function's PFDavg comes from (#298): each element's share
of the PFDavg and of the dangerous failures, and the common-cause group's.

Checked against RePyability called directly on the same diagram: the shares
are its ``fussell_vesely`` and ``barlow_proschan_importance``.
"""

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import BetaFactor, CCFGroup, RepairableRBD  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_safety_shares  # noqa: E402
from backend.tests.test_mcp import A, REPAIRABLE_STAGES, _call, _ok, env  # noqa: E402,F401 - env is a fixture
from backend.tests.test_rbd_costs import _exp, _io, _node  # noqa: E402

E = sv.Exponential.from_params
EDGES = [("input", "pt1"), ("input", "pt2"), ("pt1", "ls"), ("pt2", "ls"), ("ls", "valve"), ("valve", "output")]
RATES = {"pt1": 1e-6, "pt2": 1e-6, "ls": 5e-8, "valve": 2e-7}


def _sif(beta=0.05):
    """1oo2 transmitters -> logic solver -> trip valve, each proof-tested yearly."""
    nodes = [_node(n, model=_exp(r), instant_repair=True, inspection={"interval": 8760}) for n, r in RATES.items()]
    g = {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
         "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(EDGES)],
         "safety_function": True, "target_sil": 2}
    if beta:
        g["ccf_groups"] = [{"id": "c1", "members": ["pt1", "pt2"], "beta": beta}]
    return g


def _direct(beta=0.05):
    specs = {n: {"reliability": E([r]), "repairability": "instant", "inspection": {"interval": 8760.0}}
             for n, r in RATES.items()}
    edges = [("s" if a == "input" else a, "t" if b == "output" else b) for a, b in EDGES]
    groups = [CCFGroup(["pt1", "pt2"], BetaFactor(beta))] if beta else None
    return RepairableRBD(edges, specs, input_node="s", output_node="t", ccf_groups=groups)


def _rows(shares):
    return {r["id"]: r for r in shares["elements"]}


def test_the_shares_are_repyabilitys_fussell_vesely_and_barlow_proschan():
    out = ra.analyze_availability(_sif(), simulate=False)
    safety = out["safety"]
    direct = _direct()
    assert safety["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    shares = safety["shares"]
    rows = _rows(shares)
    fv, bp = direct.fussell_vesely(), direct.barlow_proschan_importance()
    for nid in RATES:
        assert rows[nid]["pfd_share"] == pytest.approx(fv[nid], rel=1e-9)
        assert rows[nid]["failure_share"] == pytest.approx(bp[nid], rel=1e-9)
    # The common cause is its own row of the dangerous failures, and those add up to 1.
    (group,) = shares["common_cause"]
    assert group["members"] == ["pt1", "pt2"] and group["pfd_share"] is None
    assert group["failure_share"] == pytest.approx(bp[("pt1", "pt2")], rel=1e-9)
    total = sum(r["failure_share"] for r in shares["elements"]) + group["failure_share"]
    assert total == pytest.approx(1.0, rel=1e-9)
    assert "isn't split out" in shares["common_cause_note"]
    # Largest share of the PFDavg first: the single trip valve.
    assert shares["elements"][0]["id"] == "valve"


def test_without_common_cause_there_is_no_group_row():
    shares = ra.analyze_availability(_sif(beta=0), simulate=False)["safety"]["shares"]
    direct = _direct(beta=0)
    assert shares["common_cause"] == [] and "common_cause_note" not in shares
    assert _rows(shares)["ls"]["pfd_share"] == pytest.approx(direct.fussell_vesely()["ls"], rel=1e-9)


def test_a_diagram_that_is_not_a_safety_function_has_no_shares():
    g = _sif()
    g.pop("safety_function")
    assert "safety" not in ra.analyze_availability(g, simulate=False)


def test_a_measure_repyability_refuses_is_left_out_with_its_reason():
    class Refuses:
        components = {"pt1": None}

        def fussell_vesely(self, **_):
            raise NotImplementedError("not with these blocks")

        def barlow_proschan_importance(self, **_):
            return {"pt1": 1.0}

    out = rbd_safety_shares.pfd_shares(Refuses(), _sif())
    assert out["pfd_share_reason"] == "not with these blocks"
    assert out["elements"] == [{"id": "pt1", "label": "Pt1", "pfd_share": None, "failure_share": 1.0}]


def test_agents_get_the_shares_from_analyze_rbd(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "SIF", "repairable": True,
                                                 "stages": REPAIRABLE_STAGES}))["id"]
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": _sif()}})
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))
    shares = out["safety"]["shares"]
    assert {r["id"] for r in shares["elements"]} == set(RATES)
    assert shares["common_cause"][0]["failure_share"] > 0


def test_a_named_2oo3_vote_exports_and_runs(tmp_path):
    """What the builder now writes — a named MooN voting node, every block
    repaired instantly, models from a mean — still makes a "Download as
    Python" script that runs and gives the app's PFDavg."""
    from datetime import datetime, timezone

    from backend.services import rbd_block_inputs, rbd_export
    from backend.tests.test_rbd_export import _run

    rate = rbd_block_inputs.from_mean("exponential", 1 / 3e-7)["params"]
    tx = [_node(f"t{i}", model={"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
                                "params": rate}, instant_repair=True, inspection={"interval": 8760})
          for i in (1, 2, 3)]
    vote = {"id": "v", "type": "knode", "position": {"x": 0, "y": 0}, "data": {"label": "Transmitter vote", "n": 2, "k": 3}}
    valve = _node("valve", model=_exp(1e-6), instant_repair=True, inspection={"interval": 8760})
    edges = [("input", "t1"), ("input", "t2"), ("input", "t3"), ("t1", "v"), ("t2", "v"), ("t3", "v"),
             ("v", "valve"), ("valve", "output")]
    g = {"repairable": True, "unit": "hours", "nodes": [*_io(), *tx, vote, valve],
         "edges": [{"source": a, "target": b} for a, b in edges], "safety_function": True, "target_sil": 2}
    app = ra.analyze_availability(g, simulate=False)
    assert {r["id"] for r in app["safety"]["shares"]["elements"]} == {"t1", "t2", "t3", "valve"}
    code = rbd_export.to_python(g, "SIF 2oo3", exported_at=datetime(2026, 10, 10, tzinfo=timezone.utc))
    res, _ = _run(code, tmp_path, n_sims="60")
    assert res["safety"]["pfd_avg"] == pytest.approx(app["safety"]["pfd_avg"], rel=1e-12)
