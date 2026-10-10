"""The interval optimiser: which blocks to choose for (#257) and proof tests
that miss some failures (coverage below 1, #323, RePyability 0.13). Checked
against RePyability directly, the applied plan in the analysis and in
Download as Python, and through the app and MCP."""

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import RepairableRBD  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export  # noqa: E402
from backend.services import rbd_intervals as ri  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_availability_paid import FREE, client  # noqa: E402,F401 - fixture
from backend.tests.test_rbd_costs import _exp, _io, _node  # noqa: E402
from backend.tests.test_rbd_export import WHEN, _run  # noqa: E402

E = sv.Exponential.from_params
CAL = [730.0, 2190.0, 4380.0, 8760.0, 17520.0]


def _sif():
    """A transmitter, a 1oo2 pair of shutdown valves — one whose tests find
    90% of failures, a full test every five years — and a logic solver."""
    def unit(nid, rate, **test):
        return _node(nid, model=_exp(rate), instant_repair=True, inspection={"cost": 500, **test})

    nodes = [unit("tx", 1e-6, interval=8760), unit("v1", 2e-6, interval=8760),
             unit("v2", 2e-6, interval=8760, coverage=0.9, full_test=43800), unit("ls", 5e-7, interval=17520)]
    pairs = [("input", "tx"), ("tx", "v1"), ("tx", "v2"), ("v1", "ls"), ("v2", "ls"), ("ls", "output")]
    return {"repairable": True, "unit": "hours", "safety_function": True, "nodes": [*_io(), *nodes],
            "edges": [{"source": s, "target": t} for s, t in pairs]}


def _direct():
    def spec(rate, interval, **test):
        return {"reliability": E([rate]), "repairability": "instant",
                "inspection": {"interval": float(interval), "cost": 500.0, **test}}

    return RepairableRBD(
        [("s", "tx"), ("tx", "v1"), ("tx", "v2"), ("v1", "ls"), ("v2", "ls"), ("ls", "t")],
        {"tx": spec(1e-6, 8760), "v1": spec(2e-6, 8760), "v2": spec(2e-6, 8760, coverage=0.9, full_test=43800.0),
         "ls": spec(5e-7, 17520)}, input_node="s", output_node="t")


def test_a_partly_covering_block_is_chosen_among_divisors():
    g = _sif()
    found = ri.maintained(g)
    assert [r["id"] for r in found["proof_test"]] == ["tx", "v1", "v2", "ls"]
    assert [r["id"] for r in found["partial"]] == ["v2"]
    out = ri.optimise(g, blocks=["v1", "v2"], allowed=CAL + [43800.0, 21900.0])
    # The partly-covering valve chooses only among intervals dividing its full test's.
    assert out["allowed"]["v2"] == [730.0, 2190.0, 4380.0, 8760.0, 21900.0, 43800.0]
    assert 17520.0 in out["allowed"]["v1"]
    direct = _direct().optimal_inspection_intervals(["v1", "v2"], allowed=out["allowed"])
    got = {r["id"]: r["interval"] for r in out["blocks"]}
    assert got == pytest.approx(direct.intervals)
    assert out["plan"]["cost_rate"] == pytest.approx(direct.cost_rate)
    assert out["plan"]["pfd_avg"] == pytest.approx(1 - direct.availability)
    v2 = next(r for r in out["blocks"] if r["id"] == "v2")
    assert v2["coverage"] == 0.9 and v2["full_test"] == 43800.0
    assert 43800.0 % v2["interval"] == 0
    assert any("finds the rest" in n for n in out["notes"])


def test_the_calendar_keeps_the_divisors():
    out = ri.optimise(_sif(), blocks=["v2"])
    # 8760 hours a year: monthly, quarterly, half-yearly and yearly divide five years; the rest don't.
    assert out["allowed"]["v2"] == [730.0, 2190.0, 4380.0, 8760.0]


def test_what_the_untested_fraction_costs():
    g = _sif()
    out = ri.optimise(g, blocks=["v1", "v2"])
    (u,) = out["untested"]
    assert u["id"] == "v2" and u["coverage"] == 0.9
    # The plan with v2's tests finding every failure, by RePyability's coverage lever.
    planned = _direct().with_intervals({r["id"]: r["interval"] for r in out["blocks"]},
                                       offsets={r["id"]: r["offset"] for r in out["blocks"]})
    lever = next(lv for lv in planned.levers() if lv.key == "v2" and lv.name == "inspection.coverage")
    full = planned.with_levers({lever: 1.0})
    assert u["with_full_coverage"]["pfd_avg"] == pytest.approx(1 - full.mean_availability(), rel=1e-9)
    assert u["pfd_cost"] == pytest.approx(full.mean_availability() - planned.mean_availability(), rel=1e-9)
    assert u["pfd_cost"] > 0


def test_unchosen_blocks_are_kept_as_drawn():
    out = ri.optimise(_sif(), blocks=["v1", "v2"])
    assert [r["id"] for r in out["blocks"]] == ["v1", "v2"]
    assert out["fixed"] == [{"id": "tx", "label": "Tx", "interval": 8760.0, "offset": 0.0},
                            {"id": "ls", "label": "Ls", "interval": 17520.0, "offset": 0.0}]
    every = ri.optimise(_sif())
    assert every["fixed"] == []


def test_given_intervals_that_dont_divide_are_refused():
    with pytest.raises(AnalysisError, match="must divide its full test"):
        ri.optimise(_sif(), blocks=["v2"], allowed=[17520.0, 26280.0])


def test_the_applied_plan_and_its_export_keep_the_full_test(tmp_path):
    g = _sif()
    out = ri.optimise(g, blocks=["v1", "v2"], stagger=True)
    applied = ri.apply_plan(g, out["blocks"])
    v2 = next(n for n in applied["nodes"] if n["id"] == "v2")["data"]["inspection"]
    assert v2["coverage"] == 0.9 and v2["full_test"] == 43800
    app = ra.analyze_availability(applied, n_simulations=40)
    assert app["safety"]["pfd_avg"] == pytest.approx(out["plan"]["pfd_avg"], rel=1e-9)
    res, _ = _run(rbd_export.to_python(applied, "SIF", exported_at=WHEN), tmp_path, n_sims="40")
    assert res["safety"]["pfd_avg"] == pytest.approx(out["plan"]["pfd_avg"], rel=1e-9)


def test_app_passes_blocks(client):
    client.act_as(FREE)
    r = client.post("/api/rbds/intervals", json={"graph": _sif(), "blocks": ["v2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["id"] for b in body["blocks"]] == ["v2"] and {f["id"] for f in body["fixed"]} == {"tx", "v1", "ls"}
    assert body["untested"][0]["id"] == "v2"


def test_mcp_intervals_report_coverage(monkeypatch):
    import mongomock

    from backend import config, db
    from backend.services import rbds as rbds_service
    from backend.services import tokens
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_cov"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]
    rbd = rbds_service.save_rbd(test_db, "SIF", _sif(), A)
    out = _ok(_call(token, "optimise_maintenance_intervals", {"rbd_id": rbd.id, "blocks": ["v1", "v2"]}))
    assert {b["id"] for b in out["fixed_blocks"]} == {"tx", "ls"}
    assert out["untested"][0]["id"] == "v2" and out["untested"][0]["pfd_cost"] > 0
    v2 = next(b for b in out["blocks"] if b["id"] == "v2")
    assert v2["coverage"] == 0.9 and v2["full_test"] == 43800.0
    for op in out.get("edit_rbd_ops") or []:
        if op["id"] == "v2":
            assert op["inspection"]["coverage"] == 0.9 and op["inspection"]["full_test"] == 43800
