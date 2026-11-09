"""A functional failure caused by others: RESULTS_FROM (effect -> cause) between
functional failures, written by functional_failure.linked / .unlinked.

A cause must be on the same tree as the effect: on a position inside the
effect's (the usual case), beside it or on the same position. Only a failure
causing itself, directly or round a loop, is refused. A functional failure is
covered when its own failure modes are decided and the failures it results from
are covered in turn; a position is analysed when every functional failure on it
is covered. Deleting or retiring the cause, or moving either end to another
tree, drops the link (and says so) rather than being refused."""

import pytest

from backend.maintenance import service
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore, new_id

ORG = "user-a"
DECIDED = {"outcome": "rtf", "rtf_basis": "random"}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def _ff(m, position_id, fn_text, ff_text):
    fn = m.add_function(position_id, fn_text)
    return m.add_functional_failure(fn["id"], ff_text)


def _pool(m):
    """The pool: Swimming Pool › Circulation and treatment › Salt chlorinator ›
    Chlorinator cell, with Heating beside Circulation and treatment. One
    functional failure on each; the cell's has two failure modes (undecided),
    the salt chlorinator's one of its own (decided)."""
    pool = m.create_position("Swimming Pool")
    circ = m.create_position("Circulation and treatment", parent_id=pool["id"])
    salt = m.create_position("Salt chlorinator", parent_id=circ["id"])
    cell = m.create_position("Chlorinator cell", parent_id=salt["id"])
    heating = m.create_position("Heating", parent_id=pool["id"])
    p = {"pool": pool, "circ": circ, "salt": salt, "cell": cell, "heating": heating}
    p["pool_ff"] = _ff(m, pool["id"], "Sanitise the water", "Free chlorine below 1 ppm")
    p["circ_ff"] = _ff(m, circ["id"], "Keep the water sanitised", "Chlorinator fails to hold free chlorine")
    p["salt_ff"] = _ff(m, salt["id"], "Produce up to 25 g/h", "No output")
    p["cell_ff"] = _ff(m, cell["id"], "Produce chlorine", "Chlorine output reduced")
    p["heat_ff"] = _ff(m, heating["id"], "Lift the water to 26 °C", "Water stays cold")
    p["cell_modes"] = [m.add_failure_mode(cell["id"], t, functional_failure_id=p["cell_ff"]["id"])
                       for t in ("Plates scaled", "Coating worn")]
    p["salt_mode"] = m.add_failure_mode(salt["id"], "Power supply fails", functional_failure_id=p["salt_ff"]["id"])
    m.decide_failure_mode(p["salt_mode"]["id"], "operational", DECIDED)
    return p


def _link_chain(m, p):
    """The pool's failure caused by failures on all three levels below it, and each
    level by the one beneath (so the cell is reached by several paths)."""
    for effect, cause in (("pool_ff", "circ_ff"), ("pool_ff", "salt_ff"), ("pool_ff", "cell_ff"),
                          ("circ_ff", "salt_ff"), ("salt_ff", "cell_ff")):
        m.link_cause(p[effect]["id"], p[cause]["id"])


def _decide_cell(m, p):
    for mode in p["cell_modes"]:
        m.decide_failure_mode(mode["id"], "operational", DECIDED)


def _not_analysed(m):
    return {r["name"] for r in m.tree_rows()["positions"] if r.get("not_analysed")}


def _failure(m, position_id):
    """The first functional failure on a position, as the RCM read shows it."""
    return m.rcm_worksheet(position_id, "this")["positions"][0]["functions"][0]["failures"][0]


def _links(m):
    return sorted(m.s.pairs(ORG, "RESULTS_FROM"))


# ---- linking and unlinking --------------------------------------------------------

def test_link_writes_the_edge_and_one_event_and_unlink_takes_it_away(m):
    p = _pool(m)
    out = m.link_cause(p["pool_ff"]["id"], p["salt_ff"]["id"])
    assert _links(m) == [(p["pool_ff"]["id"], p["salt_ff"]["id"])]
    [event] = _events(m, "functional_failure.linked")
    assert event["payload"] == {"id": p["pool_ff"]["id"], "cause_id": p["salt_ff"]["id"],
                                "position_id": p["pool"]["id"], "cause_position_id": p["salt"]["id"],
                                "on": m.today()}
    assert [c["id"] for c in out["causes"]] == [p["salt_ff"]["id"]]
    assert out["causes"][0]["position"] == {"id": p["salt"]["id"], "name": "Salt chlorinator"}
    assert out["position"]["id"] == p["pool"]["id"] and out["effects"] == []
    # From the other end: the salt chlorinator's failure causes the pool's.
    below = m.functional_failure(p["salt_ff"]["id"])
    assert [e["id"] for e in below["effects"]] == [p["pool_ff"]["id"]]

    m.link_cause(p["pool_ff"]["id"], p["salt_ff"]["id"])  # again: nothing new
    assert len(_events(m, "functional_failure.linked")) == 1
    _rebuilds_the_same(m)

    out = m.unlink_cause(p["pool_ff"]["id"], p["salt_ff"]["id"])
    assert out["causes"] == [] and _links(m) == []
    [event] = _events(m, "functional_failure.unlinked")
    assert event["payload"]["id"] == p["pool_ff"]["id"] and event["payload"]["cause_id"] == p["salt_ff"]["id"]
    m.unlink_cause(p["pool_ff"]["id"], p["salt_ff"]["id"])  # not linked: nothing
    assert len(_events(m, "functional_failure.unlinked")) == 1
    _rebuilds_the_same(m)


def test_every_refusal_says_what_to_do(m):
    p = _pool(m)
    pool_ff, circ_ff, salt_ff, heat_ff = (p[k]["id"] for k in ("pool_ff", "circ_ff", "salt_ff", "heat_ff"))
    with pytest.raises(Invalid, match="cause_id"):
        m.link_cause(pool_ff, "")
    with pytest.raises(Invalid, match="can't cause itself"):
        m.link_cause(pool_ff, pool_ff)
    # Another tree.
    shed = m.create_position("Pump shed")
    shed_ff = _ff(m, shed["id"], "House the pumps", "Roof leaks")
    with pytest.raises(Invalid, match="Pump shed is on another tree: pick a functional failure on the same tree as "
                                      "Circulation and treatment"):
        m.link_cause(circ_ff, shed_ff["id"])
    # A loop, from either end.
    m.link_cause(pool_ff, salt_ff)
    with pytest.raises(Invalid, match="go round in a circle.*Unlink that first, or swap them"):
        m.link_cause(salt_ff, pool_ff)
    m.link_cause(salt_ff, heat_ff)
    with pytest.raises(Invalid, match="go round in a circle"):
        m.link_cause(heat_ff, pool_ff)  # pool <- salt <- heating <- pool
    m.unlink_cause(salt_ff, heat_ff)
    m.unlink_cause(pool_ff, salt_ff)
    assert _links(m) == []
    with pytest.raises(NotFound):
        m.link_cause(pool_ff, "no-such-id")
    # Removed failures and functions.
    gone = _ff(m, p["cell"]["id"], "Seal the cell", "Leaks")
    m.remove_functional_failure(gone["id"])
    with pytest.raises(Invalid, match="functional failure was deleted"):
        m.link_cause(pool_ff, gone["id"])
    fn = m.add_function(p["cell"]["id"], "Report its state")
    orphan = m.add_functional_failure(fn["id"], "No reading")
    m.remove_function(fn["id"])
    with pytest.raises(Invalid, match="deleted"):
        m.link_cause(pool_ff, orphan["id"])
    # A retired position.
    spare = m.create_position("Old pump", parent_id=p["pool"]["id"])
    spare_ff = _ff(m, spare["id"], "Pump", "No flow")
    m.retire_position(spare["id"])
    with pytest.raises(Invalid, match="Old pump has been retired: pick a position that's still in use"):
        m.link_cause(pool_ff, spare_ff["id"])
    # Another workspace's failure is simply not found.
    other = Maintenance(m.s, "user-b", "someone")
    with pytest.raises(NotFound):
        other.link_cause(pool_ff, salt_ff)
    theirs = other.create_position("Their pool")
    with pytest.raises(NotFound):
        m.link_cause(pool_ff, _ff(other, theirs["id"], "Hold water", "Leaks")["id"])
    assert _links(m) == []


def test_at_most_max_causes(m, monkeypatch):
    p = _pool(m)
    monkeypatch.setattr(service, "MAX_CAUSES", 2)
    m.link_cause(p["pool_ff"]["id"], p["circ_ff"]["id"])
    m.link_cause(p["pool_ff"]["id"], p["salt_ff"]["id"])
    with pytest.raises(Invalid, match="at most 2 causes: unlink one first"):
        m.link_cause(p["pool_ff"]["id"], p["cell_ff"]["id"])


def test_a_loop_is_refused_and_a_loop_already_there_never_hangs_a_read(m):
    p = _pool(m)
    pool_ff, circ_ff = p["pool_ff"]["id"], p["circ_ff"]["id"]
    # Two processes linking at the same moment could leave the reverse link in
    # place; write it straight to the log as they would have.
    m._link_event("functional_failure.linked", circ_ff, pool_ff)
    with pytest.raises(Invalid, match="go round in a circle: Chlorinator fails to hold free chlorine already "
                                      "results from Free chlorine below 1 ppm"):
        m.link_cause(pool_ff, circ_ff)
    # Both directions in place: reads finish, the reverse link doesn't count.
    m._link_event("functional_failure.linked", pool_ff, circ_ff)
    m.link_cause(circ_ff, p["salt_ff"]["id"])
    _decide_cell(m, p)
    m.link_cause(p["salt_ff"]["id"], p["cell_ff"]["id"])
    assert _failure(m, p["pool"]["id"])["covered"] is True
    reverse = _failure(m, p["circ"]["id"])
    # Both ends are on the pool's tree, so both links count now; the read finishes
    # (whether a loop member reads as covered depends on where the walk starts).
    assert isinstance(reverse["covered"], bool)
    assert [(e["id"], e["inside"]) for e in reverse["effects"]] == [(pool_ff, True)]
    assert {c["id"]: c["inside"] for c in reverse["causes"]} == {pool_ff: True, p["salt_ff"]["id"]: True}
    assert "Swimming Pool" not in _not_analysed(m)
    m.rcm_all()
    _rebuilds_the_same(m)


def test_a_cause_beside_it_or_on_the_same_position(m):
    """The pool water's 'no free chlorine' from the salt chlorinator beside it, and
    a structure failure from a function on the same position: both link and count."""
    pool = m.create_position("Pool")
    water = m.create_position("Pool water", parent_id=pool["id"])
    chlor = m.create_position("Salt chlorinator", parent_id=pool["id"])
    chlorine = _ff(m, water["id"], "Hold free chlorine at 1-3 ppm", "Free chlorine below 1 ppm")
    output = _ff(m, chlor["id"], "Produce up to 25 g/h", "No output")
    mode = m.add_failure_mode(chlor["id"], "Cell scaled", functional_failure_id=output["id"])
    out = m.link_cause(chlorine["id"], output["id"])  # a sibling
    assert out["changed"] is True
    assert [(c["position"]["name"], c["inside"], c["covered"]) for c in out["causes"]] == [
        ("Salt chlorinator", True, False)]
    assert "Pool water" in _not_analysed(m)
    m.decide_failure_mode(mode["id"], "operational", DECIDED)
    assert "Pool water" not in _not_analysed(m)
    assert _failure(m, water["id"])["explained_below"] is True
    # The effect end, from the chlorinator: names the pool water.
    assert [(e["position"]["name"], e["inside"]) for e in m.functional_failure(output["id"])["effects"]] == [
        ("Pool water", True)]
    # The same position: a structure failure from a function on the pool itself.
    shell = _ff(m, pool["id"], "Hold the water", "Shell cracks")
    ground = m.add_functional_failure(m.add_function(pool["id"], "Sit on stable ground")["id"], "Ground heaves")
    m.decide_failure_mode(m.add_failure_mode(pool["id"], "Groundwater rises",
                                             functional_failure_id=ground["id"])["id"], "operational", DECIDED)
    out = m.link_cause(shell["id"], ground["id"])
    assert [(c["position"]["name"], c["inside"], c["covered"]) for c in out["causes"]] == [("Pool", True, True)]
    assert out["covered"] is True
    # A cause above its effect counts too (the link isn't refused for its direction).
    m.link_cause(output["id"], ground["id"])
    assert {c["id"] for c in m.functional_failure(output["id"])["causes"] if c["inside"]} == {ground["id"]}
    _rebuilds_the_same(m)


# ---- the analysed rule --------------------------------------------------------------

def test_the_pool_is_analysed_once_everything_below_is_decided(m):
    p = _pool(m)
    # Before any link the pool's failure has no failure modes: not analysed.
    assert {"Swimming Pool", "Circulation and treatment"} <= _not_analysed(m)
    _link_chain(m, p)
    # One undecided mode three levels down keeps every level above it unanalysed.
    assert {"Swimming Pool", "Circulation and treatment", "Salt chlorinator", "Chlorinator cell"} <= _not_analysed(m)
    top = _failure(m, p["pool"]["id"])
    assert top["covered"] is False and top["explained_below"] is True and top["modes"] == []
    m.decide_failure_mode(p["cell_modes"][0]["id"], "operational", DECIDED)
    assert "Swimming Pool" in _not_analysed(m)
    m.decide_failure_mode(p["cell_modes"][1]["id"], "operational", DECIDED)
    assert not {"Swimming Pool", "Circulation and treatment", "Salt chlorinator",
                "Chlorinator cell"} & _not_analysed(m)
    assert "Heating" in _not_analysed(m)  # its failure has neither modes nor causes
    top = _failure(m, p["pool"]["id"])
    assert top["covered"] is True and top["explained_below"] is True
    # In tree order: Circulation and treatment, then the salt chlorinator, then its cell.
    assert [c["position"]["name"] for c in top["causes"]] == [
        "Circulation and treatment", "Salt chlorinator", "Chlorinator cell"]
    assert all(c["inside"] and c["covered"] for c in top["causes"])
    # The cell is reached by three paths but its modes are counted once: 2 + the salt chlorinator's 1.
    assert top["below"]["modes"] == 3 and top["below"]["undecided"] == 0
    assert sorted(top["below"]["mode_ids"]) == sorted(
        [x["id"] for x in p["cell_modes"]] + [p["salt_mode"]["id"]])
    assert top["causes"][0]["chain"]["modes"] == 3  # Circulation and treatment's chain
    salt = _failure(m, p["salt"]["id"])
    assert salt["explained_below"] is False  # it has a mode of its own as well
    assert [e["position"]["name"] for e in salt["effects"]] == ["Swimming Pool", "Circulation and treatment"]
    # rcm_all and the worksheet say the same.
    by_id = {x["id"]: x for x in m.rcm_all()["positions"]}
    assert by_id[p["pool"]["id"]]["analysed"] is True
    _rebuilds_the_same(m)


def test_own_modes_and_causes_together(m):
    p = _pool(m)
    _decide_cell(m, p)
    m.link_cause(p["pool_ff"]["id"], p["cell_ff"]["id"])
    assert "Swimming Pool" not in _not_analysed(m)
    own = m.add_failure_mode(p["pool"]["id"], "Stabiliser too low", functional_failure_id=p["pool_ff"]["id"])
    top = _failure(m, p["pool"]["id"])
    assert top["covered"] is False and top["explained_below"] is False
    assert "Swimming Pool" in _not_analysed(m)
    m.decide_failure_mode(own["id"], "operational", DECIDED)
    assert _failure(m, p["pool"]["id"])["covered"] is True
    # A position's own counts stay its own: the pool has one failure mode.
    assert len(m.rcm_worksheet(p["pool"]["id"], "this")["positions"][0]["functions"][0]["failures"][0]["modes"]) == 1


def test_a_cause_shared_by_two_effects(m):
    p = _pool(m)
    flow = m.add_functional_failure(m.add_function(p["circ"]["id"], "Turn the water over")["id"], "Flow reduced")
    m.link_cause(p["circ_ff"]["id"], p["cell_ff"]["id"])
    m.link_cause(flow["id"], p["cell_ff"]["id"])
    cell = _failure(m, p["cell"]["id"])
    assert len(cell["effects"]) == 2
    assert "Circulation and treatment" in _not_analysed(m)
    _decide_cell(m, p)
    assert "Circulation and treatment" not in _not_analysed(m)


def test_a_failure_mode_retired_or_merged_below_leaves_the_link(m):
    p = _pool(m)
    _decide_cell(m, p)
    m.link_cause(p["pool_ff"]["id"], p["cell_ff"]["id"])
    m.merge_failure_mode(p["cell_modes"][1]["id"], p["cell_modes"][0]["id"])
    assert _links(m) and _failure(m, p["pool"]["id"])["covered"] is True
    m.retire_failure_mode(p["cell_modes"][0]["id"])
    assert _links(m)  # the link stays; the cell's failure now has nothing under it
    assert _failure(m, p["pool"]["id"])["covered"] is False
    assert "Swimming Pool" in _not_analysed(m)


# ---- what other operations do to links ----------------------------------------------

def test_deleting_the_lower_end_drops_its_links(m):
    p = _pool(m)
    _decide_cell(m, p)
    _link_chain(m, p)
    assert "Swimming Pool" not in _not_analysed(m)
    out = m.remove_functional_failure(p["cell_ff"]["id"])
    assert out["links_removed"] == 2
    assert p["cell_ff"]["id"] not in {c for _, c in _links(m)}
    # The salt chlorinator's own decided mode still covers it, and through it the pool.
    assert "Swimming Pool" not in _not_analysed(m)

    fn_id = m.s.inn(ORG, p["salt_ff"]["id"], "FAILS_AS")[0]["id"]
    out = m.remove_function(fn_id)
    assert out["links_removed"] == 2  # to the pool's failure and to Circulation and treatment's
    assert _links(m) == [(p["pool_ff"]["id"], p["circ_ff"]["id"])]
    # Circulation and treatment's failure now has nothing under it: the pool flips.
    assert {"Swimming Pool", "Circulation and treatment"} <= _not_analysed(m)
    _rebuilds_the_same(m)


def test_deleting_the_higher_end_drops_its_links(m):
    p = _pool(m)
    _link_chain(m, p)
    out = m.remove_functional_failure(p["pool_ff"]["id"])
    assert out["links_removed"] == 3
    assert p["pool_ff"]["id"] not in {e for e, _ in _links(m)}


def test_retiring_the_cause_position_drops_the_links_above(m):
    p = _pool(m)
    _decide_cell(m, p)
    _link_chain(m, p)
    out = m.retire_position(p["cell"]["id"])
    assert out == {"retired": p["cell"]["id"], "links_removed": 2}
    assert p["cell_ff"]["id"] not in {c for _, c in _links(m)}
    _rebuilds_the_same(m)


def test_a_position_moved_to_another_tree_drops_the_links_across(m):
    p = _pool(m)
    _link_chain(m, p)
    every = _links(m)
    # The salt chlorinator (with its cell) moves out of Circulation and treatment, still in the pool: all stay.
    out = m.update_position(p["salt"]["id"], parent_id=p["pool"]["id"])
    assert "links_removed" not in out and _links(m) == every
    # To the top level, a tree of its own: the links to the pool's tree go, the one inside it stays.
    out = m.update_position(p["salt"]["id"], parent_id=None)
    assert out["links_removed"] == 3 and "no longer on the same tree" in out["note"]
    assert _links(m) == sorted([(p["pool_ff"]["id"], p["circ_ff"]["id"]), (p["salt_ff"]["id"], p["cell_ff"]["id"])])
    # An effect moving away drops its links as well.
    m.link_cause(p["heat_ff"]["id"], p["circ_ff"]["id"])
    out = m.update_position(p["heating"]["id"], parent_id=p["salt"]["id"])
    assert out["links_removed"] == 1 and (p["heat_ff"]["id"], p["circ_ff"]["id"]) not in _links(m)
    assert "links_removed" not in m.update_position(p["salt"]["id"], name="Salt chlorinator 2")
    _rebuilds_the_same(m)


def test_a_link_across_trees_reads_as_not_counting(m):
    """A link whose cause is on another tree (written by a concurrent write, or by
    code that didn't drop it) is shown with inside false and doesn't count."""
    p = _pool(m)
    shed = m.create_position("Pump shed")
    shed_ff = _ff(m, shed["id"], "House the pumps", "Roof leaks")
    m.decide_failure_mode(m.add_failure_mode(shed["id"], "Sheet rusts", functional_failure_id=shed_ff["id"])["id"],
                          "operational", DECIDED)
    m._link_event("functional_failure.linked", p["circ_ff"]["id"], shed_ff["id"])
    circ = _failure(m, p["circ"]["id"])
    assert [(c["id"], c["inside"], c["covered"]) for c in circ["causes"]] == [(shed_ff["id"], False, False)]
    assert circ["covered"] is False and circ["explained_below"] is False and circ["below"] is None
    m.unlink_cause(p["circ_ff"]["id"], shed_ff["id"])  # removable all the same
    assert _links(m) == []


def test_moving_a_function_keeps_links_on_the_same_tree(m):
    p = _pool(m)
    _link_chain(m, p)
    every = _links(m)
    cell_fn = m.s.inn(ORG, p["cell_ff"]["id"], "FAILS_AS")[0]["id"]
    out = m.move_function(cell_fn, p["heating"]["id"])  # beside, on the same tree: nothing goes
    assert out["links_removed"] == 0 and "note" not in out and _links(m) == every
    pool_fn = m.s.inn(ORG, p["pool_ff"]["id"], "FAILS_AS")[0]["id"]
    out = m.move_function(pool_fn, p["circ"]["id"])  # down onto a position it was linked to: still counts
    assert out["links_removed"] == 0 and _links(m) == every
    assert all(c["inside"] for c in m.functional_failure(p["pool_ff"]["id"])["causes"])
    # To another tree: every link across goes.
    shed = m.create_position("Pump shed")
    out = m.move_function(cell_fn, shed["id"])
    assert out["links_removed"] == 2 and "no longer on the same tree" in out["note"]
    assert p["cell_ff"]["id"] not in {c for _, c in _links(m)}
    _rebuilds_the_same(m)


def test_moving_a_functional_failure_to_another_tree_drops_its_links(m):
    p = _pool(m)
    _link_chain(m, p)
    shed = m.create_position("Pump shed")
    shed_fn = m.add_function(shed["id"], "House the pumps")
    near = m.add_function(p["heating"]["id"], "Keep warm")
    assert m.move_functional_failure(p["salt_ff"]["id"], near["id"])["links_removed"] == 0
    out = m.move_functional_failure(p["salt_ff"]["id"], shed_fn["id"])
    assert out["links_removed"] == 3  # the pool's, Circulation and treatment's and the cell's
    assert not [x for x in _links(m) if p["salt_ff"]["id"] in x]
    _rebuilds_the_same(m)


def test_copying_a_branch_copies_its_links(m):
    p = _pool(m)
    _link_chain(m, p)
    # A second Circulation and treatment inside the pool: links inside the branch
    # are made between the copies, and the pool's links reach the copies too.
    copy = m.copy_position(p["circ"]["id"], "Circulation and treatment 2", parent_id=p["pool"]["id"])
    assert "links_skipped" not in copy
    links = _links(m)
    assert len(links) == 5 + 5  # the copy's two inside links and the pool's three to it
    pool_causes = [c for e, c in links if e == p["pool_ff"]["id"]]
    assert len(pool_causes) == 6
    # Copied to the top level, the pool's links can't follow.
    top = m.copy_position(p["circ"]["id"], "Elsewhere")
    assert top["links_skipped"] == 3
    assert len(_links(m)) == 10 + 2
    _rebuilds_the_same(m)


# ---- older code -------------------------------------------------------------------

def test_code_from_before_the_links_passes_the_events_over(m):
    p = _pool(m)
    _decide_cell(m, p)
    _link_chain(m, p)
    m.unlink_cause(p["pool_ff"]["id"], p["circ_ff"]["id"])
    old_projectors = {k: v for k, v in PROJECTORS.items()
                      if k not in ("functional_failure.linked", "functional_failure.unlinked")}
    old = GraphStore(":memory:", old_projectors)
    for e in m.s.log.since(0, 10_000):
        old.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                        "payload": e["payload"]})
    old.sync()
    assert old.pairs(ORG, "RESULTS_FROM") == []
    assert len(old.skipped()) == 6
    # Without the links the pool's failure has nothing under it there.
    rows = Maintenance(old, ORG, "tester").tree_rows()["positions"]
    assert next(r for r in rows if r["name"] == "Swimming Pool").get("not_analysed") is True
