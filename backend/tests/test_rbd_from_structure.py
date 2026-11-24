"""An RBD made from a product's (or an asset's) structure (Nov 2026).

"Make an RBD from this structure" used to give every block its class's model or a placeholder
of 1,000 days, and wired two look-alike pump sets in series. It now builds as Build from what's
inside does (each position's model in use, its class's, its parts-count rate, or a sub-system
of what's inside it), and asks how look-alike positions work together instead of assuming
every one is needed.

The skid: Pump set 1 and Pump set 2 (each exponential, 1e-4 per hour) and an Inlet filter
(5e-5 per hour), all models linked to the positions, in hours. At t = 5,000 h, by hand:

* in series (as it was wired):   exp(-(2λ + μ) t)               = exp(-1.25)            = 0.28650
* parallel, either will do:      (2 e^-λt - e^-2λt) e^-μt       = (1.21306 - 0.36788) × 0.77880 = 0.65823
* duty and standby (cold):       e^-λt (1 + λt) e^-μt           = 0.60653 × 1.5 × 0.77880 = 0.70855
"""

import math

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance import rbd_derive
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import models as models_service
from backend.services import rbds as rbds_service

ORG = "org-structure"
OWNERS = [ORG]
LAM, MU, T = 1e-4, 5e-5, 5000.0


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    return mongomock.MongoClient()["rbd_from_structure"]


def _exp(db, name, rate):
    return models_service.import_model(db, ORG, name, "exponential", unit="hours",
                                       params=[{"name": "failure_rate", "value": rate}]).id


def _skid(m, db):
    top = m.create_position("FT-90 skid")["id"]
    ids = {"top": top}
    for name, rate in (("Pump set 1", LAM), ("Pump set 2", LAM), ("Inlet filter", MU)):
        ids[name] = m.create_position(name, parent_id=top)["id"]
        pm.link_saved(m, db, OWNERS, set(), ids[name], "model", _exp(db, f"{name} life", rate))
    return ids


def _sf(db, rbd_id):
    rbd = rbds_service.get_rbd(db, rbd_id, ORG)
    got = rbds_service.analyze_graph(db, rbd.graph, ORG, at_times=[T])
    return got["at"]["sf"][0], rbd.graph


def test_it_asks_about_the_pump_sets_first_and_saves_nothing(m, db):
    ids = _skid(m, db)
    asked = rbd_derive.save(m, db, ids["top"], OWNERS, check=True)
    assert asked == {"ask": [{"position_ids": [ids["Pump set 1"], ids["Pump set 2"]],
                              "names": ["Pump set 1", "Pump set 2"]}]}
    assert db.rbds.count_documents({}) == 0
    assert pm.build_rbd(m, db, OWNERS, set(), ids["top"], ORG, check=True)["ask"] == asked["ask"]


def test_linked_models_are_used_not_placeholders(m, db):
    ids = _skid(m, db)
    out = rbd_derive.save(m, db, ids["top"], OWNERS, arrangements=[
        {"position_ids": [ids["Pump set 1"], ids["Pump set 2"]], "how": "series"}])
    assert out["placeholders"] == [] and out["unit"] == "Hours" and out["ask"] == []
    sf, graph = _sf(db, out["rbd_id"])
    assert graph["unit"] == "Hours"
    assert not any((n.get("model") or {}).get("placeholder") for n in graph["nodes"])
    # Said to be all needed: series, and no note saying they look redundant.
    assert sf == pytest.approx(math.exp(-(2 * LAM + MU) * T), rel=1e-6)  # 0.28650
    assert not any("look like units of one job" in n for n in out["notes"])


def test_either_pump_set_will_do_is_parallel(m, db):
    ids = _skid(m, db)
    out = rbd_derive.save(m, db, ids["top"], OWNERS, arrangements=[
        {"position_ids": [ids["Pump set 1"], ids["Pump set 2"]], "how": "parallel"}])
    sf, graph = _sf(db, out["rbd_id"])
    want = (2 * math.exp(-LAM * T) - math.exp(-2 * LAM * T)) * math.exp(-MU * T)
    assert sf == pytest.approx(want, rel=1e-4) and round(want, 5) == 0.65823
    assert any(n["type"] == "knode" for n in graph["nodes"])
    # The answer is on the tree: a redundancy set, used by every rebuild, and not asked again.
    [g] = m.groups_of(ids["Pump set 1"])
    assert (g["mode"], g["k"], g["n"]) == ("active", 1, 2)
    again = rbd_derive.save(m, db, ids["top"], OWNERS, check=True)
    assert again["ask"] == [] and again["existing"]["rbd_id"] == out["rbd_id"]


def test_duty_and_standby_is_one_standby_block(m, db):
    ids = _skid(m, db)
    out = pm.build_rbd(m, db, OWNERS, set(), ids["top"], ORG, arrangements=[
        {"position_ids": [ids["Pump set 1"], ids["Pump set 2"]], "how": "standby"}])
    sf, graph = _sf(db, out["model_id"])
    want = math.exp(-LAM * T) * (1 + LAM * T) * math.exp(-MU * T)
    assert sf == pytest.approx(want, rel=2e-3) and round(want, 5) == 0.70855
    assert any(n["type"] == "standby" for n in graph["nodes"])


def test_unanswered_look_alikes_are_said_to_be_in_series(m, db):
    ids = _skid(m, db)
    out = rbd_derive.save(m, db, ids["top"], OWNERS)
    assert out["ask"][0]["names"] == ["Pump set 1", "Pump set 2"]
    assert any("Pump set 1 and Pump set 2 look like units of one job" in n and "drawn in series" in n
               for n in out["notes"])


def test_a_coupling_inside_a_pump_set_keeps_its_model_and_only_nothing_is_a_placeholder(m, db):
    top = m.create_position("Skid")["id"]
    pump_set = m.create_position("Pump set", parent_id=top)["id"]
    coupling = m.create_position("Flexible coupling", parent_id=pump_set)["id"]
    pm.link_saved(m, db, OWNERS, set(), coupling, "model", _exp(db, "Coupling CE-42", LAM))
    m.create_position("Control panel", parent_id=top)  # nothing to go on: the one placeholder
    out = rbd_derive.save(m, db, top, OWNERS)
    assert out["placeholders"] == ["Control panel"]
    graph = rbds_service.get_rbd(db, out["rbd_id"], ORG).graph
    by = {(n.get("data") or {}).get("label") or n.get("label"): n for n in graph["nodes"]}
    assert by["Pump set"]["type"] == "subsystem"
    assert by["Control panel"]["data"]["model_source"].startswith("No life model yet")
    assert not by["Control panel"].get("data", {}).get("model")  # no life invented for it
    sub = rbds_service.get_rbd(db, by["Pump set"]["data"]["rbd"]["id"], ORG).graph
    [block] = [n for n in sub["nodes"] if ((n.get("data") or {}).get("label") or n.get("label")) == "Flexible coupling"]
    assert not (block.get("model") or {}).get("placeholder")


def test_arrangements_are_checked(m, db):
    ids = _skid(m, db)
    with pytest.raises(Invalid, match="how is parallel"):
        rbd_derive.save(m, db, ids["top"], OWNERS, arrangements=[
            {"position_ids": [ids["Pump set 1"], ids["Pump set 2"]], "how": "both"}])
    with pytest.raises(Invalid, match="two or more"):
        rbd_derive.save(m, db, ids["top"], OWNERS, arrangements=[
            {"position_ids": [ids["Pump set 1"], "elsewhere"], "how": "parallel"}])


def test_a_products_look_alike_parts_are_asked_about(m):
    """A product's design positions are each a class of their own: the free-text class is compared."""
    prod = m.create_product("FT-90 skid", "FT-90")["id"]
    for name in ("Pump set 1", "Pump set 2", "Inlet filter"):
        m.create_position(name, parent_id=prod)
    assert [x["names"] for x in rbd_derive.ask(m, prod)] == [["Pump set 1", "Pump set 2"]]


def test_different_classes_or_no_unit_suffix_are_not_asked_about(m):
    top = m.create_position("Plant")["id"]
    m.create_position("Pump 1", parent_id=top, position_class="Centrifugal pump")
    m.create_position("Pump 2", parent_id=top, position_class="Dosing pump")
    m.create_position("Motor", parent_id=top)
    m.create_position("Gearbox", parent_id=top)
    assert rbd_derive.ask(m, top) == []
