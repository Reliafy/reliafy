"""Fault trees built by hand (backend/services/fault_trees.py and its router):
hand-checked probabilities, the same cut sets and importance as the RBD
fault-tree view of the RBD the tree converts to, the stored tree's round trip,
Open-PSA export and import, and the sample."""

import math

import mongomock
import pytest

from backend.services import fault_trees as F
from backend.services import rbd_fault_tree

USER = {"uid": "user-ft", "email": "ft@example.org", "name": "Tree Builder"}


def _ev(nid, p=None, rate=None, weibull=None, **extra):
    n = {"id": nid, "type": "event", "label": nid.upper(), **extra}
    if p is not None:
        n["probability"] = p
    if rate is not None:
        n["model"] = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}
    if weibull is not None:
        n["model"] = {"distribution_id": "weibull",
                      "params": [{"name": "alpha", "value": weibull[0]}, {"name": "beta", "value": weibull[1]}]}
    return n


def _gate(nid, kind, inputs, k=None, label=None):
    g = {"id": nid, "type": "gate", "gate": kind, "inputs": inputs, "label": label or nid}
    if k is not None:
        g["k"] = k
    return g


def _tree(*nodes, unit="hours"):
    return F.normalize_tree({"unit": unit, "top": nodes[0]["id"], "nodes": list(nodes)})


# ---- hand-checked ---------------------------------------------------------------


def test_or_of_two_independent_events():
    r = F.analyse(_tree(_gate("top", "or", ["a", "b"]), _ev("a", 0.1), _ev("b", 0.2)))
    assert r["top_event_probability"] == pytest.approx(0.28, abs=1e-12)  # 1 - 0.9 * 0.8
    assert r["kind"] == "probability" and r["t"] is None and r["curve"] is None


def test_and_of_two_independent_events():
    r = F.analyse(_tree(_gate("top", "and", ["a", "b"]), _ev("a", 0.1), _ev("b", 0.2)))
    assert r["top_event_probability"] == pytest.approx(0.02, abs=1e-12)
    assert [c["events"] for c in r["cut_sets"]["listed"]] == [["b", "a"]]


def test_two_of_three_vote():
    r = F.analyse(_tree(_gate("top", "vote", ["a", "b", "c"], k=2), _ev("a", 0.1), _ev("b", 0.1), _ev("c", 0.1)))
    # 3 * 0.1^2 * 0.9 + 0.1^3
    assert r["top_event_probability"] == pytest.approx(0.028, abs=1e-12)
    assert r["cut_sets"]["count"] == 3 and all(c["order"] == 2 for c in r["cut_sets"]["listed"])
    assert r["gates"][0]["node_id"] == "top" and r["gates"][0]["gate"] == "vote"


def test_repeated_event_is_counted_once():
    # (s OR a) AND (s OR b): 0.01 + 0.99 * 0.1^2, not the independent 0.0119.
    r = F.analyse(_tree(_gate("top", "and", ["ga", "gb"]), _gate("ga", "or", ["s", "a"]),
                        _gate("gb", "or", ["s", "b"]), _ev("s", 0.01), _ev("a", 0.1), _ev("b", 0.1)))
    assert r["top_event_probability"] == pytest.approx(0.01 + 0.99 * 0.01, abs=1e-12)
    assert next(e for e in r["events"] if e["id"] == "s")["repeated"] is True


def test_time_based_events_over_time():
    r = F.analyse(_tree(_gate("top", "or", ["a", "b"]), _ev("a", rate=1e-3), _ev("b", 0.05)), t=100.0)
    assert r["kind"] == "reliability" and r["t"] == 100.0 and r["unit"] == "hours"
    assert r["top_event_probability"] == pytest.approx(1 - math.exp(-0.1) * 0.95, rel=1e-12)
    assert len(r["curve"]["t"]) == len(r["curve"]["probability"]) > 10
    # The default time: top event about 10%.
    d = F.analyse(_tree(_gate("top", "or", ["a"]), _ev("a", rate=1e-3)))
    assert d["t"] == d["t_default"] and d["top_event_probability"] == pytest.approx(0.1, abs=0.01)


def test_placeholders_are_flagged_never_silent():
    r = F.analyse(_tree(_gate("top", "or", ["a", "b"]), _ev("a", 0.1, placeholder=True), _ev("b", 0.2)))
    assert r["placeholders"] == ["A"] and "Placeholder" in r["notes"][0]
    assert next(e for e in r["events"] if e["id"] == "a")["placeholder"] is True


def test_incomplete_tree_saves_but_does_not_analyse():
    tree = _tree(_gate("top", "or", ["a", "g"]), {"id": "a", "type": "event", "label": "Pump"},
                 _gate("g", "vote", ["b"], k=2), _ev("b", 0.1))
    with pytest.raises(F.FaultTreeError) as err:
        F.analyse(tree)
    assert "“Pump” has no failure data" in str(err.value) and "needs 2 of its inputs but has 1" in str(err.value)


@pytest.mark.parametrize("kind", ["not", "xor", "inhibit", "pand", "spare"])
def test_non_coherent_and_dynamic_gates_refused(kind):
    with pytest.raises(F.FaultTreeError, match="AND, OR and k-of-n vote gates"):
        _tree(_gate("top", kind, ["a"]), _ev("a", 0.1))


def test_shape_errors():
    with pytest.raises(F.FaultTreeError, match="loop"):
        F.normalize_tree({"top": "top", "nodes": [_gate("top", "or", ["g"]), _gate("g", "or", ["h"]),
                                                  _gate("h", "or", ["g"])]})
    with pytest.raises(F.FaultTreeError, match="under the top event"):
        _tree(_gate("top", "or", ["a"]), _ev("a", 0.1), _ev("b", 0.1))
    with pytest.raises(F.FaultTreeError, match="between 0 and 1"):
        _tree(_gate("top", "or", ["a"]), _ev("a", 1.5))
    with pytest.raises(F.FaultTreeError, match=f"up to {F.MAX_NODES}"):
        _tree(_gate("top", "or", [f"e{i}" for i in range(F.MAX_NODES)]),
              *[_ev(f"e{i}", 0.01) for i in range(F.MAX_NODES)])


# ---- the same engine as the RBD fault-tree view ------------------------------------


def _equivalent(tree, t):
    """The stored tree's results and the RBD view's for the RBD it converts to."""
    mine = F.analyse(tree, t=t)
    graph, _ = F.to_rbd_graph(tree)
    theirs = rbd_fault_tree.fault_tree(graph, t=t)
    return mine, theirs


def _cut_labels(result):
    labels = {e["id"]: e["label"] for e in result["events"]}
    return sorted((tuple(sorted(labels[e] for e in c["events"])), c["probability"])
                  for c in result["cut_sets"]["listed"])


@pytest.mark.parametrize("t", [50.0, 400.0])
def test_matches_the_rbd_fault_tree_view(t):
    tree = _tree(
        _gate("top", "or", ["pumps", "power", "valves"]),
        _gate("pumps", "and", ["p1", "p2"]),
        _gate("valves", "vote", ["v1", "v2", "v3"], k=2),
        _ev("p1", weibull=(900, 1.5)), _ev("p2", weibull=(1200, 1.5)),
        _ev("power", rate=1e-4),
        _ev("v1", rate=4e-4), _ev("v2", rate=5e-4), _ev("v3", rate=6e-4),
    )
    mine, theirs = _equivalent(tree, t)
    assert mine["top_event_probability"] == pytest.approx(theirs["top_event_probability"], rel=1e-12)
    assert len(_cut_labels(mine)) == len(_cut_labels(theirs))
    for (a, pa), (b, pb) in zip(_cut_labels(mine), _cut_labels(theirs)):
        assert a == b and pa == pytest.approx(pb, rel=1e-12)
    assert mine["cut_sets"]["count"] == theirs["cut_sets"]["count"]
    imp_mine = {e["label"]: e["importance"] for e in mine["events"]}
    imp_theirs = {e["label"]: e["importance"] for e in theirs["events"]}
    assert set(imp_mine) == set(imp_theirs)
    for label, measures in imp_mine.items():
        for k, v in measures.items():
            assert v == pytest.approx(imp_theirs[label][k], rel=1e-9, abs=1e-15), (label, k)


def test_repeated_event_matches_the_rbd_too():
    tree = _tree(_gate("top", "and", ["ga", "gb"]), _gate("ga", "or", ["s", "a"]),
                 _gate("gb", "or", ["s", "b"]), _ev("s", rate=1e-5), _ev("a", rate=1e-3), _ev("b", rate=2e-3))
    mine, theirs = _equivalent(tree, 300.0)
    assert mine["top_event_probability"] == pytest.approx(theirs["top_event_probability"], rel=1e-12)
    assert [c[0] for c in _cut_labels(mine)] == [c[0] for c in _cut_labels(theirs)]


def test_rbd_conversion_notes_fixed_probabilities():
    graph, notes = F.to_rbd_graph(_tree(_gate("top", "or", ["a", "b"]), _ev("a", 0.1), _ev("b", rate=1e-3)))
    blocks = {n["data"]["label"]: n for n in graph["nodes"] if n["type"] == "component"}
    assert "model" not in blocks["A"]["data"] and "WITHOUT a non-repairable model" in notes[0]


# ---- round trips ---------------------------------------------------------------


def test_stored_tree_round_trip_is_stable():
    raw = {"unit": "hours", "top": "top", "nodes": [
        _gate("top", "or", ["a", "g"], label="  Loss   of  flow "), _ev("a", rate=1e-3, note="Pump"),
        _gate("g", "atleast", ["b", "c", "d"], k=2), _ev("b", 0.1), _ev("c", 0.1, placeholder=True),
        {"id": "d", "type": "event", "label": "D",
         "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 2e-3}],
                   "placeholder": True}}]}
    once = F.normalize_tree(raw)
    assert F.normalize_tree(once) == once
    by_id = {n["id"]: n for n in once["nodes"]}
    assert by_id["top"]["label"] == "Loss of flow" and by_id["g"]["gate"] == "vote"
    assert by_id["d"]["placeholder"] is True and "placeholder" not in by_id["d"]["model"]


def test_openpsa_export_imports_back_to_the_same_answer():
    from backend.services.rbd_import import openpsa

    tree = _tree(_gate("top", "or", ["g", "c"]), _gate("g", "vote", ["a", "b", "d"], k=2),
                 _ev("a", rate=1e-3), _ev("b", weibull=(800, 2.0)), _ev("d", 0.05), _ev("c", rate=1e-5))
    xml, notes = F.to_openpsa("Plant", tree, t=200.0)
    assert notes == []
    diagrams = openpsa.parse(xml.encode(), "plant.xml")
    gate_tree, fixed, _ = diagrams[0].fault_tree
    back, _ = F.from_imported(gate_tree, fixed, "hours")
    back = F.normalize_tree(back)
    assert F.analyse(back, t=200.0)["top_event_probability"] == pytest.approx(
        F.analyse(tree, t=200.0)["top_event_probability"], rel=1e-12)


def test_openpsa_export_writes_other_models_as_their_probability():
    tree = _tree(_gate("top", "or", ["a"]), {"id": "a", "type": "event", "label": "A", "model": {
        "distribution_id": "lognormal", "params": [{"name": "mu", "value": 6.0}, {"name": "sigma", "value": 0.5}]}})
    xml, notes = F.to_openpsa("x", tree, t=300.0)
    assert "<float value=" in xml and "“A” uses a model Open-PSA" in notes[0] and "<!--" in xml


def test_galileo_spare_gate_refused_as_a_fault_tree():
    from backend.services.rbd_import import galileo

    dft = b'toplevel "T";\n"T" or "S" "C";\n"S" csp "P" "Q";\n"P" lambda=0.001;\n"Q" lambda=0.001;\n"C" lambda=0.0001;\n'
    gate_tree, fixed, _ = galileo.parse(dft, "x.dft")[0].fault_tree
    with pytest.raises(F.FaultTreeError, match="spare"):
        F.from_imported(gate_tree, fixed, "")


# ---- the API ---------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)
    app.dependency_overrides[get_current_user] = lambda: USER
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


SIMPLE = {"unit": "hours", "top": "top", "nodes": [_gate("top", "or", ["a", "b"]), _ev("a", 0.1), _ev("b", 0.2)]}


def test_save_get_list_rename_delete(client):
    r = client.post("/api/fault-trees", json={"name": "Pumps", "tree": SIMPLE})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    assert r.json()["n_gates"] == 1 and r.json()["n_events"] == 2
    got = client.get(f"/api/fault-trees/{tid}").json()
    assert got["tree"] == F.normalize_tree(SIMPLE) and not got["read_only"]
    listed = client.get("/api/fault-trees").json()["fault_trees"]
    assert {t["id"] for t in listed} >= {tid, "sample-fault-tree-quadcopter"}
    assert client.patch(f"/api/fault-trees/{tid}", json={"name": "Pump set"}).json()["name"] == "Pump set"
    assert client.delete(f"/api/fault-trees/{tid}").json() == {"ok": True}
    assert client.get(f"/api/fault-trees/{tid}").status_code == 404


def test_save_refuses_a_bad_tree_plainly(client):
    bad = {"top": "top", "nodes": [_gate("top", "xor", ["a"]), _ev("a", 0.1)]}
    r = client.post("/api/fault-trees", json={"name": "Bad", "tree": bad})
    assert r.status_code == 422 and "XOR gate" in r.json()["detail"]


def test_analyse_endpoint_and_open_as_rbd(client):
    r = client.post("/api/fault-trees/analyse", json={"tree": SIMPLE})
    assert r.status_code == 200 and r.json()["top_event_probability"] == pytest.approx(0.28)
    tid = client.post("/api/fault-trees", json={"name": "Pumps", "tree": {
        **SIMPLE, "nodes": [_gate("top", "or", ["a", "b"]), _ev("a", rate=1e-3), _ev("b", 0.2)]}}).json()["id"]
    made = client.post(f"/api/fault-trees/{tid}/rbd")
    assert made.status_code == 200, made.text
    rbd = client.get(f"/api/rbds/{made.json()['rbd_id']}").json()
    assert rbd["name"] == "Pumps (from fault tree)" and made.json()["notes"]
    assert client.get(f"/api/fault-trees/{tid}").json()["rbd_id"] == made.json()["rbd_id"]


def test_export_endpoint(client):
    r = client.post("/api/fault-trees/export/openpsa", json={"tree": SIMPLE, "name": "Pumps"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert b"<define-fault-tree" in r.content


def test_import_endpoint_lands_trees(client):
    dft = b'toplevel "T";\n"T" 2of3 "A" "B" "C";\n"A" lambda=0.001;\n"B" lambda=0.001;\n"C" prob=0.01;\n'
    r = client.post("/api/fault-trees/import", files={"file": ("plant.dft", dft, "application/octet-stream")})
    assert r.status_code == 200, r.text
    out = r.json()["trees"][0]
    assert out["n_gates"] == 1 and out["n_events"] == 3
    gate = next(n for n in out["tree"]["nodes"] if n["type"] == "gate")
    assert gate["gate"] == "vote" and gate["k"] == 2
    assert next(n for n in out["tree"]["nodes"] if n["id"] == "C")["probability"] == 0.01
    refused = client.post("/api/fault-trees/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert refused.status_code == 422 and "Open-PSA" in refused.json()["detail"]


def test_the_sample_reads_honestly(client):
    sample = client.get("/api/fault-trees/sample-fault-tree-quadcopter").json()
    assert sample["is_sample"] and sample["read_only"]
    r = client.post("/api/fault-trees/analyse", json={"tree": sample["tree"], "t": 100.0}).json()
    assert r["placeholders"] == [] and r["unit"] == "Hours"
    # Any one arm down brings a quadcopter down: each motor and speed
    # controller is a cut set of its own; the two IMUs only together (1-of-2).
    singles = {c["events"][0] for c in r["cut_sets"]["listed"] if c["order"] == 1}
    assert {f"motor{i}" for i in range(1, 5)} | {f"esc{i}" for i in range(1, 5)} <= singles
    assert {"imu_1", "imu_2"}.isdisjoint(singles)
    assert {("imu_1", "imu_2")} <= {tuple(sorted(c["events"])) for c in r["cut_sets"]["listed"] if c["order"] == 2}
    assert 0.0 < r["top_event_probability"] < 0.2
    # A sample is hidden, not deleted.
    assert client.delete("/api/fault-trees/sample-fault-tree-quadcopter").json() == {"ok": True}
    assert client.db.fault_trees.find_one({"_id": "sample-fault-tree-quadcopter"}) is not None
