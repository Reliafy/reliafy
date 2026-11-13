"""Fault trees over MCP (and so over REST and the CLI, which run the same
actions): list / get kind fault_tree(s), change fault_tree_save /
fault_tree_delete, analyse fault_tree, import_rbd as_fault_tree."""

import pytest

from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")

NODES = [
    {"id": "top", "type": "gate", "gate": "or", "label": "No flow", "inputs": ["pumps", "power"]},
    {"id": "pumps", "type": "gate", "gate": "and", "label": "Both pumps fail", "inputs": ["p1", "p2"]},
    {"id": "p1", "type": "event", "label": "Pump A fails", "probability": 0.1},
    {"id": "p2", "type": "event", "label": "Pump B fails", "probability": 0.2},
    {"id": "power", "type": "event", "label": "Power lost",
     "model": {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-4}]},
     "placeholder": True},
]


@pytest.fixture()
def seeded(env):
    from backend.services import samples

    samples.seed_samples(env.db)
    return env


def _save(env, **args):
    return _call(env.token[A], "change", {"action": "fault_tree_save", "args": args})


def test_save_get_analyse_delete(env):
    saved = _ok(_save(env, name="Water supply", nodes=NODES, top="top", unit="hours"))
    tid = saved["id"]
    assert saved["n_gates"] == 2 and saved["n_events"] == 3 and saved["placeholders"] == ["Power lost"]
    assert saved["url"].endswith(f"/systems/fault-trees/{tid}")
    listed = _ok(_call(env.token[A], "list", {"kind": "fault_trees"}))
    assert tid in {t["id"] for t in listed["fault_trees"]} and "data_notice" in listed
    got = _ok(_call(env.token[A], "get", {"kind": "fault_tree", "args": {"id": tid}}))
    assert got["tree"]["top"] == "top" and got["no_data"] == []
    res = _ok(_call(env.token[A], "analyse", {"action": "fault_tree", "args": {
        "fault_tree_id": tid, "t": 1000.0, "include_gates": True, "export_openpsa": True}}))
    q_power = 1 - 2.718281828459045 ** -0.1
    assert res["top_event_probability"] == pytest.approx(1 - (1 - q_power) * (1 - 0.02), rel=1e-9)
    assert res["warning"] and res["placeholders"] == ["Power lost"]
    assert {tuple(c["events"]) for c in res["cut_sets"]["listed"]} == {("Power lost",), ("Pump B fails",
                                                                                          "Pump A fails")}
    assert {g["name"] for g in res["gates"]} == {"No flow", "Both pumps fail"}
    assert "<opsa-mef>" in res["openpsa_xml"]
    gone = _ok(_call(env.token[A], "change", {"action": "fault_tree_delete", "args": {"fault_tree_id": tid}}))
    assert gone["deleted"]
    assert "not found" in _err(_call(env.token[A], "get", {"kind": "fault_tree", "args": {"id": tid}}))


def test_unfinished_tree_saves_and_says_what_it_needs(env):
    nodes = [NODES[0], {"id": "pumps", "type": "event", "label": "Pumps"}, NODES[4]]
    saved = _ok(_save(env, name="Draft", nodes=nodes))
    assert saved["no_data"] == ["Pumps"]
    msg = _err(_call(env.token[A], "analyse", {"action": "fault_tree", "args": {"fault_tree_id": saved["id"]}}))
    assert "“Pumps” has no failure data" in msg


def test_refusals(seeded):
    env = seeded
    msg = _err(_save(env, name="Bad", nodes=[{"id": "top", "type": "gate", "gate": "xor", "inputs": ["a"]},
                                             {"id": "a", "type": "event", "probability": 0.1}]))
    assert "XOR gate" in msg
    assert "give name and nodes" in _err(_save(env, name="Nothing"))
    gone = "sample-fault-tree-quadcopter"  # withdrawn (Nov 2026)
    assert "not found" in _err(_call(env.token[A], "change", {"action": "fault_tree_delete",
                                                                "args": {"fault_tree_id": gone}})).lower()


def test_make_rbd_and_update(env):
    saved = _ok(_save(env, name="Water supply", nodes=NODES, make_rbd=True))
    assert saved["rbd"]["rbd_id"]
    rbd = _ok(_call(env.token[A], "get", {"kind": "rbd", "args": {"id": saved["rbd"]["rbd_id"]}}))
    assert rbd["name"] == "Water supply (from fault tree)"
    assert any("fixed probability" in n for n in saved["rbd"]["notes"])
    renamed = _ok(_save(env, fault_tree_id=saved["id"], unit="Hours"))
    assert renamed["unit"] == "Hours" and renamed["n_events"] == 3


def test_import_as_fault_tree(env):
    dft = 'toplevel "T";\n"T" or "G" "C";\n"G" 2of3 "A" "B" "D";\n"A" lambda=0.001;\n"B" lambda=0.001;\n' \
          '"D" lambda=0.001;\n"C" prob=0.01;\n'
    out = _ok(_call(env.token[A], "change", {"action": "import_rbd", "args": {
        "content": dft, "format": "galileo", "as_fault_tree": True, "time_unit": "Hours", "name": "Plant"}}))
    row = out["fault_trees"][0]
    assert out["saved"] and row["fault_tree_id"] and row["n_gates"] == 2 and row["unit"] == "Hours"
