"""Redundancy a train at a time (#227, RePyability 0.12's
``RepairableRBD.allocate_redundancy(trains=...)``): the cheapest design copies
a whole chain of blocks in series — a pump with its motor — alongside it into
the node it feeds, a vote there keeping the number it needs (2-out-of-3
becomes 2-out-of-4). Checked against the library directly, by brute force,
and by drawing the copies on the diagram and pricing it again.
"""

import itertools

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import RepairableRBD  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_costs, rbds as rbds_service  # noqa: E402
from backend.services.rbd_analysis import AnalysisError  # noqa: E402
from backend.tests.test_availability_paid import PRO, client  # noqa: E402,F401 - client is a fixture
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401 - env is a fixture

E = sv.Exponential.from_params
TEN_YEARS = 87600.0


def _exp(rate):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def _node(nid, x, y, label, **data):
    return {"id": nid, "type": "component", "position": {"x": x, "y": y}, "data": {"label": label, **data}}


def _station(trains=3, need=2, downtime=2000.0, header=False):
    """RePyability's docstring example: ``need`` of ``trains`` pump trains,
    each a pump and its motor, into a vote; optionally a priced header after
    the vote (a block copied on its own)."""
    nodes = [{"id": "input", "type": "input", "position": {"x": 0, "y": 110}, "data": {"label": "Input"}}]
    edges = []
    for i in range(1, trains + 1):
        y = (i - 1) * 110
        nodes.append(_node(f"pump{i}", 200, y, f"Pump {i}", model=_exp(1e-3), repair=_exp(0.1),
                           costs={"repair": 500, "acquisition": 20000}))
        nodes.append(_node(f"motor{i}", 420, y, f"Motor {i}", model=_exp(2e-4), repair=_exp(0.05),
                           costs={"acquisition": 10000}))
        edges += [{"source": "input", "target": f"pump{i}"}, {"source": f"pump{i}", "target": f"motor{i}"},
                  {"source": f"motor{i}", "target": "vote"}]
    nodes.append({"id": "vote", "type": "knode", "position": {"x": 640, "y": 110},
                  "data": {"label": "Vote", "n": need, "k": trains}})
    last = "vote"
    if header:
        nodes.append(_node("header", 860, 110, "Header", model=_exp(5e-5), repair=_exp(0.02),
                           costs={"acquisition": 4000}))
        edges.append({"source": "vote", "target": "header"})
        last = "header"
    nodes.append({"id": "output", "type": "output", "position": {"x": 1080, "y": 110}, "data": {"label": "Output"}})
    edges.append({"source": last, "target": "output"})
    return {"repairable": True, "unit": "hours", "nodes": nodes, "edges": edges,
            "costs": {"downtime_rate": downtime, "horizon": TEN_YEARS}}


def _library_station():
    pump = {"reliability": E([1e-3]), "repairability": E([0.1]), "repair_cost": 500.0, "acquisition_cost": 20000.0}
    motor = {"reliability": E([2e-4]), "repairability": E([0.05]), "acquisition_cost": 10000.0}
    ids = (1, 2, 3)
    return RepairableRBD(
        [("s", f"pump {i}") for i in ids] + [(f"pump {i}", f"motor {i}") for i in ids]
        + [(f"motor {i}", "t") for i in ids],
        {**{f"pump {i}": pump for i in ids}, **{f"motor {i}": motor for i in ids}},
        k={"t": 2}, downtime_cost_rate=2000.0)


def _priced(graph, horizon=TEN_YEARS):
    rbd = ra._build_repairable_rbd(graph)[0]
    return rbd.total_cost(horizon), rbd.mean_availability()


def test_a_fourth_pump_train_is_the_librarys_answer():
    out = rbd_costs.cheapest_design(_station(), trains=[{"name": "Pump train", "blocks": ["motor1", "pump1"]}],
                                    blocks=[])
    lib = _library_station().allocate_redundancy(TEN_YEARS, trains={"train 1": ["pump 1", "motor 1"]})
    assert lib.units == {"train 1": 2}
    (train,) = out["design"]["trains"]
    # The blocks come back in chain order whatever order they were picked in.
    assert train["name"] == "Pump train" and [b["id"] for b in train["blocks"]] == ["pump1", "motor1"]
    assert train["copies"] == 2 and train["price"] == 30000
    assert out["design"]["units"] == {} and out["design"]["blocks"] == []
    assert out["design"]["total_cost"] == pytest.approx(lib.total_cost, rel=1e-12)
    assert out["design"]["availability"] == pytest.approx(lib.availability, rel=1e-12)
    assert round(out["current"]["total_cost"]) == 319927 and round(out["design"]["total_cost"]) == 295306
    assert out["changed"] and out["saving"] > 0


def test_the_drawn_fourth_train_joins_the_vote_and_prices_the_same():
    out = rbd_costs.cheapest_design(_station(), trains={"Pump train": ["pump1", "motor1"]}, blocks=[])
    drawn = out["graph"]
    ids = {n["id"] for n in drawn["nodes"]}
    assert {"pump1t1", "motor1t1"} <= ids
    vote = next(n for n in drawn["nodes"] if n["id"] == "vote")
    assert vote["data"]["n"] == 2 and vote["data"]["k"] == 4  # 2-out-of-4
    into_vote = sorted(e["source"] for e in drawn["edges"] if e["target"] == "vote")
    assert into_vote == ["motor1", "motor1t1", "motor2", "motor3"]
    assert {"source": "input", "target": "pump1t1"}.items() <= next(
        e for e in drawn["edges"] if e["target"] == "pump1t1").items()
    copy = next(n for n in drawn["nodes"] if n["id"] == "pump1t1")
    assert copy["data"]["label"] == "Pump 1 (2)" and copy["data"]["costs"]["acquisition"] == 20000
    # Drawn below the trains already there.
    assert copy["position"]["y"] > max(n["position"]["y"] for n in _station()["nodes"] if n["id"].startswith("pump"))
    total, avail = _priced(drawn)
    assert total == pytest.approx(out["design"]["total_cost"], rel=1e-12)
    assert avail == pytest.approx(out["design"]["availability"], rel=1e-12)
    # The builder's checks pass on it (the vote's count of branches matches).
    validation = ra.validate_graph(drawn)
    assert validation["valid"] and not validation["errors"], validation


def test_trains_and_single_blocks_together_match_brute_force():
    g = _station(header=True)
    # By default every priced block outside the trains is copied one at a time too.
    every = rbd_costs.cheapest_design(g, trains=[{"name": "Pump train", "blocks": ["pump1", "motor1"]}])
    assert [b["id"] for b in every["design"]["blocks"]] == ["pump2", "motor2", "pump3", "motor3", "header"]
    out = rbd_costs.cheapest_design(g, trains=[{"name": "Pump train", "blocks": ["pump1", "motor1"]}],
                                    blocks=["header"])
    assert every["design"]["total_cost"] <= out["design"]["total_cost"] * (1 + 1e-12)
    best = None
    for n_train, n_header in itertools.product(range(1, 5), range(1, 4)):
        drawn = rbd_costs.apply_copies(
            rbd_costs.apply_train_copies(g, [{"blocks": ["pump1", "motor1"], "copies": n_train}]),
            {"header": n_header})
        total, _ = _priced(drawn)
        if best is None or total < best[0]:
            best = (total, n_train, n_header)
    assert (out["design"]["trains"][0]["copies"], out["design"]["blocks"][0]["copies"]) == best[1:]
    assert out["design"]["total_cost"] == pytest.approx(best[0], rel=1e-9)
    assert _priced(out["graph"])[0] == pytest.approx(out["design"]["total_cost"], rel=1e-9)


def test_a_train_that_does_not_pay_stays_as_drawn():
    out = rbd_costs.cheapest_design(_station(downtime=10.0), trains={"T": ["pump1", "motor1"]}, blocks=[])
    assert out["design"]["trains"][0]["copies"] == 1 and not out["changed"] and out["graph"] is None


def test_the_floor_and_discounting_reach_the_trains():
    lib = _library_station()
    floor = 0.99999
    out = rbd_costs.cheapest_design(_station(), trains={"T": ["pump1", "motor1"]}, blocks=[],
                                    min_availability=floor, discount_rate=15)
    r = out["discount_rate_per_unit"]
    want = lib.allocate_redundancy(TEN_YEARS, trains={"T": ["pump 1", "motor 1"]}, min_availability=floor,
                                   discount_rate=r, max_units=rbd_costs.MAX_COPIES)
    assert out["design"]["trains"][0]["copies"] == want.units["T"]
    assert out["design"]["total_cost"] == pytest.approx(want.total_cost, rel=1e-12)
    assert out["design"]["availability"] >= floor


@pytest.mark.parametrize("trains, blocks, match", [
    ({"T": ["pump1", "pump2"]}, [], "chain of blocks in series"),
    ({"T": ["pump1", "motor1"], "U": ["motor1"]}, [], "in one train at most"),
    ({"T": ["pump1", "nope"]}, [], "isn't a component block"),
    ({"T": ["vote"]}, [], "isn't a component block"),
    ({"T": ["motor1"]}, None, None),  # a one-block train is fine
    ({"T": ["pump1", "motor1"]}, ["pump1"], "copy it with its train or alone"),
    ({"T": []}, [], "needs at least one block"),
    ({f"T{i}": [f"pump{i}"] for i in range(1, 8)}, [], "up to 6 trains"),
])
def test_trains_are_checked_in_the_users_words(trains, blocks, match):
    if match is None:
        rbd_costs.cheapest_design(_station(), trains=trains, blocks=blocks)
        return
    with pytest.raises(AnalysisError, match=match):
        rbd_costs.cheapest_design(_station(), trains=trains, blocks=blocks)


def test_a_train_needs_a_priced_block_and_a_single_exit():
    g = _station()
    for n in g["nodes"]:
        if n["id"] in ("pump1", "motor1"):
            n["data"]["costs"].pop("acquisition", None)
    with pytest.raises(AnalysisError, match="Give a block of train “T” a purchase price"):
        rbd_costs.cheapest_design(g, trains={"T": ["pump1", "motor1"]}, blocks=[])
    # A train whose last block feeds two nodes has no one node for its copies to join.
    g = _station(header=True)
    g["edges"].append({"source": "motor1", "target": "header"})
    with pytest.raises(AnalysisError, match="must end at a block feeding one node"):
        rbd_costs.cheapest_design(g, trains={"T": ["pump1", "motor1"]}, blocks=[])


def test_the_endpoint_takes_trains(client):
    client.act_as(PRO)
    res = client.post("/api/rbds/design/cheapest", json={
        "graph": _station(), "trains": [{"name": "Pump train", "blocks": ["pump1", "motor1"]}], "blocks": []})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["design"]["trains"][0]["copies"] == 2 and body["design"]["blocks"] == []
    assert body["graph"] is not None
    bad = client.post("/api/rbds/design/cheapest", json={
        "graph": _station(), "trains": [{"name": "T", "blocks": ["pump1", "pump2"]}]})
    assert bad.status_code == 422 and "chain of blocks" in bad.json()["detail"]


def test_mcp_cheapest_design_takes_trains(env, monkeypatch):
    from backend.services import billing

    rbd = rbds_service.save_rbd(env.db, "Pump station", _station(), A)
    out = _ok(_call(env.token[A], "cheapest_design", {
        "rbd_id": rbd.id, "trains": {"Pump train": ["pump1", "motor1"]}, "blocks": []}))
    assert out["available"] and out["changed"]
    (train,) = out["design"]["trains"]
    assert train["copies"] == 2 and [b["label"] for b in train["blocks"]] == ["Pump 1", "Motor 1"]
    assert round(out["design"]["total_cost"]) == 295306
    # Errors are the app's, and the tool stays Pro.
    assert "chain of blocks" in _err(_call(env.token[A], "cheapest_design", {
        "rbd_id": rbd.id, "trains": {"T": ["pump1", "pump2"]}}))
    monkeypatch.setattr(billing, "premium_compute_allowed", lambda db, user: False)
    assert _ok(_call(env.token[A], "cheapest_design", {
        "rbd_id": rbd.id, "trains": {"T": ["pump1", "motor1"]}}))["code"] == "pro_required"
