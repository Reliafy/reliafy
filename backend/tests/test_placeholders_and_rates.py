"""One part, one rate; placeholders counted through every level (W2, W3, W4: the persona review of
19 Nov 2026 on a survey quadcopter).

* An RBD built from the tree counts its placeholders inside every sub-system: six positions
  inside, 11 leaves with no model, says "11 of 11 basic blocks are placeholders", never "1".
* A mission never treats a sub-system whose blocks are all placeholders as a block with a model:
  no "from the blocks with models alone" figure, and no weakest block picked from them.
* A leaf with no model but a parts-count rate becomes an exponential block at that rate, said to
  be from the parts count; the FME(C)A's criticality uses the same rate, and says where it came from.
* A parts count that left lines out says so in its headline, and its figures round once.
"""

import math

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance import rcm_graph
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import rbd_missions as rm

ORG = "org-rates"
OWNERS = [ORG, "__samples__"]
MOTOR_RATE = 30.0  # per million hours, the parts count's


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["placeholders_rates"]
    samples.seed_samples(d)
    return d


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _quad(m):
    """A small quadcopter: Comms (a leaf), Propulsion (2 motors, 2 propellers) and Power (battery,
    BMS) inside; nothing has a model."""
    top = m.create_position("Survey quadcopter")["id"]
    ids = {"top": top, "Comms": m.create_position("Comms", parent_id=top)["id"]}
    for group, kids in (("Propulsion", ["Motor 1", "Motor 2", "Propeller 1", "Propeller 2"]),
                        ("Power", ["Battery pack", "BMS"])):
        ids[group] = m.create_position(group, parent_id=top)["id"]
        for k in kids:
            ids[k] = m.create_position(k, parent_id=ids[group])["id"]
    return ids


def _parts_count(m, db, ids):
    """Each motor and propeller on its position's parts list; a parts count on the top with the
    motor at 30 per million hours and the propeller left out as not electronic."""
    motor = m.create_part("MOT-2210", "Brushless motor 2210")["id"]
    prop = m.create_part("PROP-10", "Propeller 10x4.5")["id"]
    for k in ("Motor 1", "Motor 2"):
        m.add_position_part(ids[k], motor, role="replacement", quantity=1)
    for k in ("Propeller 1", "Propeller 2"):
        m.add_position_part(ids[k], prop, role="replacement", quantity=1)
    assign = {"MOT-2210": {"rate_per_million_hours": MOTOR_RATE}, "PROP-10": {"excluded": True}}
    return pm.predict_position(m, db, OWNERS, set(), ids["top"], assign=assign, save=True)


def test_placeholders_are_counted_through_every_sub_system(m, db):
    ids = _quad(m)
    link = pm.build_rbd(m, db, OWNERS, set(), ids["top"])
    [row] = [r for r in pm.describe(m, db, OWNERS, set(), m.position_models(ids["top"])) if r["id"] == link["id"]]
    # 7 basic blocks (Comms, 4 in Propulsion, 2 in Power), every one a placeholder: never "1 placeholder".
    assert row["source_text"] == "Built from 3 positions inside · 7 of 7 basic blocks are placeholders"
    counts = row["model"]["counts"]
    assert (counts["blocks"], counts["basic_blocks"], counts["basic_placeholders"], counts["nested"]) == (3, 7, 7, True)
    assert row["model"]["quality"]["word"] == "7 of 7 placeholders"
    assert row["model"]["quality"]["tone"] == "danger"  # most of the answer rests on placeholders
    assert row["model"]["placeholder_blocks"]["mostly"] is True
    assert "Propulsion › Motor 1" in row["model"]["placeholders"]
    # The panel: a sub-system of placeholders is a placeholder too, with how many inside.
    full = pm.detail(m, db, OWNERS, set(), link["id"])
    blocks = {b["label"]: b for b in full["blocks"]}
    assert blocks["Propulsion"]["placeholder"] is True and blocks["Propulsion"]["inside"] == {"basic": 4, "placeholders": 4}
    assert blocks["Comms"]["placeholder"] is True and "inside" not in blocks["Comms"]
    # The diagram's check carries the count too (the RBD Calculator's note reads it).
    from backend.services import rbds as rbds_service

    check = rbds_service.validate_graph(db, db.rbds.find_one({"_id": link["model_id"]})["graph"], OWNERS)
    assert check["placeholder_blocks"]["words"] == "7 of 7 basic blocks are placeholders"
    _same_after_rebuild(m)


def test_a_mission_never_counts_an_all_placeholder_sub_system_as_a_block_with_a_model(m, db):
    from backend.services import models as models_service

    ids = _quad(m)
    # Comms has a real model; the sub-systems are placeholders all through.
    seal = models_service.import_model(db, ORG, "Radio", "exponential", unit="hours",
                                       params=[{"name": "failure_rate", "value": 1e-4}])
    pm.link_saved(m, db, OWNERS, set(), ids["Comms"], "model", seal.id)
    pm.build_rbd(m, db, OWNERS, set(), ids["top"])  # Propulsion and Power get RBDs of their own (in use)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), ids["top"], ORG, "Sortie")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, mission = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Sortie", "duration": 25}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert sorted(p["label"] for p in got["placeholders"]) == ["Power", "Propulsion"]
    assert got["placeholder_blocks"]["basic"] == 7 and got["placeholder_blocks"]["placeholders"] == 6
    assert got["placeholder_blocks"]["nested"] is True and got["placeholder_blocks"]["mostly"] is True
    # "From the blocks with models alone" is Comms alone: exp(-25e-4).
    assert got["without_placeholders"]["reliability"] == pytest.approx(math.exp(-25e-4), rel=1e-9)
    # The weakest block is never a sub-system of placeholders.
    for row in got["phases"]:
        assert (row.get("weakest") or {}).get("label") in (None, "Comms")
    # The pane's grid flags the sub-systems as placeholders too.
    flags = {b["label"]: b["placeholder"] for b in rm.detail(db, OWNERS, g, mission)["blocks"]}
    assert flags == {"Comms": False, "Power": True, "Propulsion": True}
    from backend.services import rbd_phases

    assert rbd_phases.agent_summary(got)["notes"][0].startswith("6 of 7 basic blocks are placeholders.")


def test_a_mission_with_every_block_a_placeholder_gives_no_figure_without_them(m, db):
    ids = _quad(m)
    pm.build_rbd(m, db, OWNERS, set(), ids["top"])  # Propulsion and Power get RBDs of their own (in use)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), ids["top"], ORG, "Sortie")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, _ = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Sortie", "duration": 25}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert sorted(p["label"] for p in got["placeholders"]) == ["Comms", "Power", "Propulsion"]
    assert got["without_placeholders"] is None  # nothing left with a model: no "52.2% without them"
    assert all(not row.get("weakest") for row in got["phases"])  # no "weakest with a model"


def test_a_partly_placeholder_sub_system_is_said_and_gives_no_clean_figure(m, db):
    from backend.services import models as models_service

    ids = _quad(m)
    motor = models_service.import_model(db, ORG, "Motor", "exponential", unit="hours",
                                        params=[{"name": "failure_rate", "value": 3e-5}])
    pm.link_saved(m, db, OWNERS, set(), ids["Motor 1"], "model", motor.id)
    pm.build_rbd(m, db, OWNERS, set(), ids["top"])  # Propulsion and Power get RBDs of their own (in use)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), ids["top"], ORG, "Sortie")
    graph = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    g, _ = rm.save(graph, rm.LEGACY_ID, phases=[{"name": "Sortie", "duration": 25}])
    got = rm.analyze(db, OWNERS, g, g["phases"])
    assert [p["label"] for p in got["partly_placeholders"]] == ["Propulsion"]
    assert got["partly_placeholders"][0]["placeholders"] == 3 and got["partly_placeholders"][0]["basic"] == 4
    assert got["without_placeholders"] is None  # still carries invented lives inside Propulsion


def test_a_leaf_with_a_parts_count_rate_is_an_exponential_block_at_that_rate(m, db):
    ids = _quad(m)
    _parts_count(m, db, ids)
    link = pm.build_rbd(m, db, OWNERS, set(), ids["Propulsion"])
    rbd = db.rbds.find_one({"_id": link["model_id"]})
    blocks = {n["data"]["label"]: n["data"] for n in rbd["graph"]["nodes"] if n["type"] == "component"}
    motor = blocks["Motor 1"]
    assert motor["model"].get("placeholder") is not True
    assert motor["model"]["distribution_id"] == "exponential"
    [rate] = [p["value"] for p in motor["model"]["params"] if p["name"] == "failure_rate"]
    assert rate == pytest.approx(MOTOR_RATE / 1e6)  # 30 per million hours, not a 1,000-hour placeholder
    assert motor["model_source"].startswith("From the parts count: 30 per million hours")
    assert motor["rate_source"] == "parts count"
    # A propeller (left out of the parts count as not electronic) has no rate: still a placeholder.
    assert blocks["Propeller 1"]["model"]["placeholder"] is True
    assert sorted(link["placeholders"]) == ["Propeller 1", "Propeller 2"]
    _same_after_rebuild(m)


def test_the_fmeca_uses_the_parts_count_rate_and_says_so(m, db):
    ids = _quad(m)
    _parts_count(m, db, ids)
    untyped = m.add_failure_mode(ids["Motor 1"], "Bearing seizure")["id"]
    m.score_failure_mode(untyped, {"mode_ratio": 0.5, "loss_probability": 1, "operating_time": 150})
    typed = m.add_failure_mode(ids["Motor 1"], "Winding breaks down")["id"]
    m.score_failure_mode(typed, {"mode_ratio": 0.3, "loss_probability": 1, "operating_time": 150,
                                 "failure_rate": 8e-5, "rate_source": "entered"})
    sheet = rcm_graph.resolve(db, m.rcm_worksheet(ids["Motor 1"], "this"), OWNERS, m=m)
    [p] = sheet["positions"]
    assert p["rate"]["source"] == "parts count" and p["rate"]["per_million_hours"] == pytest.approx(MOTOR_RATE)
    modes = {md["text"]: md for md in p["unassigned"]}
    a = modes["Bearing seizure"]
    assert a["failure_rate"] is None  # nothing stored
    assert a["rate_from"]["source"] == "parts count" and a["rate_from"]["value"] == pytest.approx(3e-5)
    assert a["rate_from"]["text"].startswith("From the parts count: 30 per million hours")
    assert a["cm"] == pytest.approx(1 * 0.5 * 3e-5 * 150)
    # A typed rate stays: an override, with the position's beside it.
    b = modes["Winding breaks down"]
    assert b["rate_from"]["source"] == "typed" and b["rate_from"]["value"] == 8e-5
    assert b["rate_from"]["position_rate"] == pytest.approx(3e-5)
    assert b["cm"] == pytest.approx(1 * 0.3 * 8e-5 * 150)
    assert p["fmea"]["cr"] == pytest.approx(a["cm"] + b["cm"])
    # Without the reader's Maintenance, the read is as it was (nothing added).
    plain = rcm_graph.resolve(db, m.rcm_worksheet(ids["Motor 1"], "this"), OWNERS)
    assert "rate_from" not in plain["positions"][0]["unassigned"][0]
    _same_after_rebuild(m)


def test_the_parts_count_headline_says_what_it_leaves_out(m, db):
    ids = _quad(m)
    link = _parts_count(m, db, ids)
    [row] = pm.describe(m, db, OWNERS, set(), [x for x in m.position_models(ids["top"]) if x["id"] == link["id"]])
    covers = row["model"]["covers"]
    assert covers["short"] == "electronics only: 2 lines left out"
    assert covers["words"] == "Electronics only: 2 lines left out (Propeller 10x4.5; Propeller 10x4.5)"
    # Rounded once, as the parts count's own page rounds it: 2 motors at 30 → 16,666.7 h → "16,700 hours".
    mtbf = next(n for n in row["model"]["numbers"] if n["id"] in ("mtbf", "mean"))
    assert mtbf["text"] == "16,700 hours" and mtbf["value"] == pytest.approx(1e6 / 60)


def test_a_built_items_copy_of_a_parts_count_reads_as_one():
    """A built item's copy of its design's parts count (role design) is still a parts count."""
    copy = {"role": "design", "source": {"design_position_id": "d1", "design_role": "prediction"}}
    assert pm.is_prediction(copy) and pm.is_prediction({"role": "prediction"})
    assert not pm.is_prediction({"role": "design", "source": {"design_role": "fitted"}})
    assert pm.source_text(copy) == "From the product's design: its parts count"
    none_left = pm.prediction_covers({"excluded": [], "unassigned": []})
    assert none_left is None


def test_the_criticality_column_against_a_hand_calculation(m, db):
    """Cm = β × α × λ × t with the position's one rate, in the mode's time unit; no number where a
    figure is missing, and a reason where the rate can't be put in the mode's time unit."""
    ids = _quad(m)
    _parts_count(m, db, ids)
    # Hand calculation: the motor's parts count is 30 per million hours = 3e-5 per hour.
    # In days that is 3e-5 × 24 = 7.2e-4 per day; over t = 10 days with α = 0.4 and β = 0.5:
    # Cm = 0.5 × 0.4 × 7.2e-4 × 10 = 1.44e-3.
    days = m.add_failure_mode(ids["Motor 1"], "Shaft bearing wears")["id"]
    m.score_failure_mode(days, {"mode_ratio": 0.4, "loss_probability": 0.5, "operating_time": 10, "time_unit": "days"})
    # In hours: β 1 × α 0.25 × 3e-5 × 200 h = 1.5e-3.
    hours = m.add_failure_mode(ids["Motor 1"], "Magnet loosens")["id"]
    m.score_failure_mode(hours, {"mode_ratio": 0.25, "loss_probability": 1, "operating_time": 200})
    # No operating time: no Cm, nothing made up.
    no_t = m.add_failure_mode(ids["Motor 1"], "Connector corrodes")["id"]
    m.score_failure_mode(no_t, {"mode_ratio": 0.2, "loss_probability": 1})
    # A unit the hourly rate can't be put in: no Cm, and why.
    flights = m.add_failure_mode(ids["Motor 1"], "Prop nut backs off")["id"]
    m.score_failure_mode(flights, {"mode_ratio": 0.1, "loss_probability": 1, "operating_time": 50, "time_unit": "flights"})
    # A propeller has no rate (left out of the parts count): no Cm.
    prop = m.add_failure_mode(ids["Propeller 1"], "Blade chips")["id"]
    m.score_failure_mode(prop, {"mode_ratio": 1, "loss_probability": 1, "operating_time": 100})

    sheet = rcm_graph.resolve(db, m.rcm_worksheet(ids["Propulsion"], "below"), OWNERS, m=m)
    modes = {md["text"]: md for p in sheet["positions"] for md in p["unassigned"]}
    assert modes["Shaft bearing wears"]["rate_from"]["value"] == pytest.approx(7.2e-4)
    assert modes["Shaft bearing wears"]["cm"] == pytest.approx(1.44e-3)
    assert modes["Magnet loosens"]["cm"] == pytest.approx(1.5e-3)
    assert modes["Connector corrodes"]["cm"] is None
    assert modes["Prop nut backs off"]["cm"] is None
    assert '"flights"' in modes["Prop nut backs off"]["cm_note"]
    assert modes["Blade chips"]["cm"] is None and "rate_from" not in modes["Blade chips"]
    [motor] = [p for p in sheet["positions"] if p["id"] == ids["Motor 1"]]
    assert motor["fmea"]["cr"] == pytest.approx(1.44e-3 + 1.5e-3)
    _same_after_rebuild(m)
