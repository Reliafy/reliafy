"""The Survey quadcopter: "Add the Survey quadcopter" on Products (and "Open the Survey
quadcopter" on the Explorer) adds an invented inspection quadcopter's design, the one
ready-made product for the RCM and FME(C)A tabs: a complete RCM study for its mission (the
operating context on the top position; functions with performance standards on every
position; functional failures breaching them, the higher ones explained by the lower;
failure modes scored and decided, some decisions linked to evidence; the decisions'
tasks as the maintenance programme), its part with a bill of materials, three items
built from it, a replaced motor, two failure reports and a flight-critical RBD with
placeholder failure rates, through the ordinary service methods (events), once unless
asked again; over the app's route, MCP (maintenance products.add_sample) and the CLI.
Products' trees stay off the Assets list.

Once added it reads as a product of the workspace's own: nothing on it or inside it says
"sample", a copy is known by a mark (design.template_marked) and not by its name, and the
life models and analyses it stands on are saved in the workspace as its own records. A
copy added before Nov 2026 ("Survey quadcopter") is still known by that name,
and make_sample_own brings it to the same in place."""

import contextlib
import hashlib
import json

import mongomock
import pytest

from backend.maintenance import rcm_graph, templates
from backend.maintenance.service import PROJECTORS, Maintenance, _subject
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _ok, _session
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG, OTHER = "user-a", "user-b"


@pytest.fixture()
def store():
    return GraphStore(":memory:", PROJECTORS)


@pytest.fixture()
def db():
    return mongomock.MongoClient()["sample_product"]


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


@pytest.fixture()
def seeded(db):
    """The database with the shared library in it, as every deployment has."""
    from backend.services import samples

    samples.seed_samples(db)
    return db


# What a copy added before Nov 2026 was described as.
EARLIER_DESCRIPTION = (
    "A sample product: a small inspection quadcopter's design with a complete RCM study on it and every "
    'failure mode scored as an FME(C)A. The mission it is designed for (invented, like everything here): '
    'routine corridor inspection of a 12 km rural 11 kV distribution feeder, flown monthly in sorties of '
    'up to 25 minutes, 30 m above the conductors at 5 m/s, with a 4K camera and a thermal imager on a '
    'gimbal; about 150 flight hours a year per aircraft. Each position carries its functions with their '
    'performance standards (numbers from the mission), the ways each fails, the failure modes that cause '
    'them, and a decision for each: the checks before every flight, the flight log review, the 25-hour, '
    '100-hour and annual inspections, the monthly failsafe function tests, the three-monthly battery '
    'storage check, the propeller and battery limits, and the things to redesign, run to failure or '
    'accept. Each programme task has its LSA record (labour, tools, spares, method). Some decisions link '
    'the analysis or model behind them: the legacy run-to-failure plan on the motor bearings is '
    "contradicted on purpose (their life model shows wear-out), the battery retirement can't be checked "
    'until its units agree, and two failure modes still need a decision. The motors, propellers, battery '
    'pack and radio carry sample life models. With its part and bill of materials, three items built from'
    ' it (the first with its calendar tasks in a monthly work package), a replaced motor and two failure '
    'reports. Entirely invented: no real product, company or operator.'
)


@contextlib.contextmanager
def _as_before(monkeypatch):
    """The add as it was before Nov 2026, so a test has a copy like the ones already in
    workspaces: named "Survey quadcopter (sample)" ("… (sample 2)" for a second), with
    the earlier description, RBD name and life-model link names and notes, linked to
    the shared library's records, and with no mark (the log holds only the events an
    earlier add wrote)."""
    old = "Survey quadcopter (sample)"

    def numbered(m, base):
        taken = {p["name"] for p in m.s.nodes(m.org, "Position") if not p.get("retired")}
        name, n = base, 2
        while name in taken:
            name, n = base.replace("(sample)", f"(sample {n})"), n + 1
        return name

    with monkeypatch.context() as mp:
        mp.setattr(templates, "SAMPLE_PRODUCT_NAME", old)
        mp.setattr(templates, "SAMPLE_PRODUCT_DESCRIPTION", EARLIER_DESCRIPTION)
        mp.setattr(templates, "_free_name", numbered)
        mp.setattr(templates, "SAMPLE_RBD_NAME", templates._EARLIER_RBD_NAME)
        mp.setattr(templates, "SAMPLE_PRODUCT_MODELS", [
            (at, model_id, *templates._EARLIER_MODEL_LABELS[model_id][:1], mode, templates._EARLIER_MODEL_LABELS[model_id][1])
            for at, model_id, _, mode, _ in templates.SAMPLE_PRODUCT_MODELS])
        mp.setattr(templates, "workspace_records", lambda m, db: ({}, []))
        mp.setattr(Maintenance, "mark_template", lambda self, product_id, template: None)
        yield


def _says_sample(value, but=("copy_of", "data", "from_sample", "from_template", "sample_rate")) -> list:
    """Every text in a result or a saved document that says "sample" (whatever the
    case), with where it is: the fields in ``but`` are never shown to anyone."""
    found = []

    def walk(v, path):
        if isinstance(v, dict):
            for k, inner in v.items():
                if k not in but:
                    walk(inner, f"{path}.{k}")
        elif isinstance(v, (list, tuple)):
            for inner in v:
                walk(inner, path + "[]")
        elif isinstance(v, str):
            try:  # a graph row's properties are JSON
                inner = json.loads(v) if v[:1] == "{" else None
            except ValueError:
                inner = None
            if inner is not None:
                walk(inner, path)
            elif "sample" in v.lower():
                found.append((path, v[:80]))

    walk(value, "")
    return found


def test_the_sample_product_is_a_design_with_items_built_and_reports(store, db):
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    assert out["added"] and out["product"]["name"] == "Survey quadcopter"
    pid = out["product"]["id"]
    # The design: 33 positions, the sample's modes on each arm, motor, ESC, propeller and IMU.
    assert {k: out[k] for k in ("positions", "failure_modes", "scored")} == {
        "positions": 33, "failure_modes": 84, "scored": 84}
    [product] = m.products()["products"]
    assert product["id"] == pid and product["rev"] == "C" and product["part"]["part_number"] == "SQ-4"
    assert product["positions"] == 33 and product["items_built"] == 3 and product["open_reports"] == 2
    assert "12 km rural 11 kV distribution feeder" in product["description"]
    # The mission is the top position's operating context: the numbers the standards come from.
    assert m.position(pid)["operating_context"].startswith("Mission: routine corridor inspection of a 12 km")
    tree = m.tree_rows()["positions"]
    names = {p["name"] for p in tree if p.get("design_position_id") is None}
    assert {"Centre frame", "Arm 1", "Arm 4", "Landing gear", "Motor 1", "Motor 4", "ESC 4", "Propeller 4", "IMU 1",
            "IMU 2", "GPS", "Compass", "BMS", "Comms", "Payload gimbal", "Camera"} <= names
    sheet = m.rcm_worksheet(pid, "below")
    motors = [p for p in sheet["positions"] if p["name"].startswith("Motor ")]
    assert len(motors) == 4 and all(p["fmea"]["max_rpn"] == 216 for p in motors)
    arms = [p for p in sheet["positions"] if p["name"].startswith("Arm ")]
    assert len(arms) == 4 and all(p["fmea"]["modes"] == 2 for p in arms)
    assert m.position(arms[0]["id"])["operating_context"].startswith("16 mm carbon tube")

    # Its part and bill of materials: four motors in one quadcopter.
    structure = m.part_structure(product["part"]["id"])
    lines = {c["part_number"]: c["qty"] for c in structure["tree"]["children"]}
    assert lines["SQ-M2210"] == 4 and lines["SQ-IMU9"] == 2 and len(lines) == 11

    # Three items, by serial, with their revisions and flight hours (and a flights counter
    # beside the hours, for the pre-flight check).
    items = m.product_items(pid)["items"]
    assert [(r["serial"], r["rev"], r["hours"]["value"]) for r in items] == [
        ("0007", "C", 212), ("0008", "C", 31), ("0009", "B", 640)]
    assert [r["open_reports"] for r in items] == [1, 0, 1]
    counters = {(pt["name"], pt["unit"]) for pt in m.s.nodes(ORG, "MeasurementPoint")}
    assert {("Flight hours", "hours"), ("Flights", "flights")} <= counters

    # Motor 1 across the items: 0007's first motor failed (bearing seizure) and was replaced.
    motor1 = next(p for p in tree if p["name"] == "Motor 1" and p["parent_id"] and not p.get("design_position_id"))
    rollup = m.design_rollup(motor1["id"])
    assert rollup["counts"] == {"items": 3, "by_rev": {"C": 2, "B": 1}}
    fitted = {r["serial"]: r["fitted"] for r in rollup["items"]}
    assert fitted["0007"]["serial"] == "M-0007b" and fitted["0008"] is None
    assert rollup["life_data"]["failures"] == 1 and rollup["life_data"]["suspensions"] == 1
    assert [(r["title"], r["unit"]["serial"], r["status"]) for r in rollup["reports"]] == [
        ("Motor 1 seized in hover", "0007", "investigating")]
    whole = m.design_rollup(pid)
    assert {(r["unit"]["serial"], tuple(r["level"])) for r in whole["reports"]} == {
        ("0007", ("Propulsion", "Motor 1")), ("0009", ("Flight control", "GPS"))}

    # The RBD: in the workspace's RBDs, every block a placeholder; the IMUs 1 of 2, the arms in series.
    rbd = db.rbds.find_one({"_id": out["rbd"]["id"], "owner_id": ORG})
    assert rbd["name"] == "Survey quadcopter: flight-critical RBD"
    nodes = rbd["graph"]["nodes"]
    blocks = [n for n in nodes if n["type"] == "component"]
    assert len(blocks) == 18 and all(n["data"]["model"]["placeholder"] for n in blocks)
    [vote] = [n for n in nodes if n["type"] == "knode"]
    assert (vote["data"]["n"], vote["data"]["k"]) == (1, 2)
    assert sum(1 for b in blocks if b["data"]["label"].startswith("ESC ")) == 4  # one per motor, none invented
    _rebuilds_the_same(m)


def test_a_prediction_of_the_sample_starts_airborne_and_keeps_every_line(store, db):
    """A parts count on the sample: its environment starts at the handbook's airborne, rotary
    winged (the sample only), a part added to its parts list is one more line beside the bill of
    materials' eleven, and a motor line given NSWC-11's electric motor starts from the sample's
    conditions, so it has a rate at once."""
    from backend.maintenance import position_models as pm
    from backend.services import samples

    samples.seed_samples(db)
    owners = [ORG, "__samples__"]
    m = Maintenance(store, ORG, "Ana")
    out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    first = pm.predict_position(m, db, owners, set(), pid)
    assert first["environment"] == templates.SAMPLE_PRODUCT_ENVIRONMENT == "ARW"
    bom = sorted(row[0] for row in templates.SAMPLE_PRODUCT_BOM)
    assert sorted(ln["reference"] for ln in first["lines"]) == bom and len(bom) == 11
    assert first["source"] == "bill of materials"
    # A position inside it, and a unit built from it, start there too; another product doesn't.
    motor1 = next(p["id"] for p in m.s.nodes(ORG, "Position") if p["name"] == "Motor 1" and not p.get("design_position_id"))
    assert pm.default_environment(m, motor1) == "ARW"
    assert pm.default_environment(m, out["items"][0]["top_position_id"]) == "ARW"
    other = m.create_product("Ground station", part_number="GS-1")["id"]
    assert pm.default_environment(m, other) == "GF"
    # "+ Add a part" on the product: twelve lines, not one.
    light = m.create_part("SQ-LED1", "Navigation light")["id"]
    m.add_position_part(pid, light, role="component", quantity=1)
    more = pm.predict_position(m, db, owners, set(), pid)
    assert more["lines"][0]["reference"] == "SQ-LED1" and more["lines"][0]["listing_id"]
    assert sorted(ln["reference"] for ln in more["lines"][1:]) == bom
    # The motors on NSWC-11's electric motor: the sample's conditions, and a rate straight away.
    motor = pm.predict_position(m, db, owners, set(), pid, assign={"SQ-M2210": {"record_id": samples.SAMPLE_MOTOR_MODEL}})
    line = next(ln for ln in motor["lines"] if ln["reference"] == "SQ-M2210")
    assert line["conditions"] == samples.SAMPLE_MOTOR_CONDITIONS
    assert motor["results"]["counts"].get("needs_conditions", 0) == 0
    counted = next(ln for ln in motor["results"]["lines"] if ln["reference"] == "SQ-M2210")
    assert counted["rate_per_million_hours"] > 0 and counted["quantity"] == templates.ARMS
    # Conditions given on the line are kept as given; another model takes none from the sample.
    own = {**samples.SAMPLE_MOTOR_CONDITIONS, "n": 5500}
    given = pm.predict_position(m, db, owners, set(), pid,
                                assign={"SQ-M2210": {"record_id": samples.SAMPLE_MOTOR_MODEL, "conditions": own}})
    assert next(ln for ln in given["lines"] if ln["reference"] == "SQ-M2210")["conditions"]["n"] == 5500
    geared = pm.predict_position(m, db, owners, set(), pid, assign={"SQ-M2210": {"record_id": "nswc-11:electric-motor-geared"}})
    assert "conditions" not in next(ln for ln in geared["lines"] if ln["reference"] == "SQ-M2210")
    # Renamed, it is the same design (known by its mark): the same starting points.
    m.update_position(pid, name="Inspection drone Mk 2")
    assert pm.default_environment(m, pid) == "ARW"
    # A saved prediction's environment is the next one's, as on any position.
    pm.predict_position(m, db, owners, set(), pid, environment="GM", assign={"SQ-LED1": {"rate_per_million_hours": 1.0}},
                        save=True)
    assert pm.default_environment(m, pid) == "GM"
    _rebuilds_the_same(m)


def test_once_unless_asked_again_and_another_workspace_is_untouched(store, db):
    m = Maintenance(store, ORG, "tester")
    first = templates.add_sample_product(m, db)
    twice = templates.add_sample_product(m, db)
    assert twice["added"] is False and twice["product"] == first["product"]
    assert twice["message"].startswith("The Survey quadcopter is already in your workspace as “Survey quadcopter”. ")
    assert not _says_sample(first) and not _says_sample(twice)
    again = templates.add_sample_product(m, db, again=True)
    assert again["added"] and again["product"]["name"] == "Survey quadcopter 2"
    assert sorted(p["part"]["part_number"] for p in m.products()["products"]) == ["SQ-4", "SQ-4-2"]
    assert db.rbds.count_documents({"owner_id": ORG}) == 2
    other = Maintenance(store, OTHER, "other")
    assert other.products()["products"] == [] and templates.add_sample_product(other, db)["added"]
    _rebuilds_the_same(m)


def _predictions(db, owner=ORG):
    return list(db.maintainability_predictions.find({"owner_id": owner}).sort("created_at", 1))


def test_the_sample_product_has_its_own_maintainability_prediction(store, db):
    """The product comes with a maintainability prediction in the workspace's saved
    predictions, attached to it (product_id), from the shared sample's lines: the same
    numbers. A second plain add makes no duplicate; another copy gets its own."""
    from backend.services import maintainability, samples

    samples._seed_maintainability_predictions(db)
    shared = db.maintainability_predictions.find_one({"_id": "sample-maintainability-quadcopter"})
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    events = m.s.event_count(ORG)
    [doc] = _predictions(db)
    assert out["maintainability"] == {"id": doc["_id"], "name": doc["name"], "added": True}
    assert doc["name"] == "Survey quadcopter — maintainability"
    assert "maintainability prediction “Survey quadcopter — maintainability”" in out["message"]
    # Attached to the product: the id the product page and the prediction's own page go by.
    assert (doc["inputs"]["product_id"], doc["inputs"]["product_name"]) == (pid, "Survey quadcopter")
    assert doc["results"]["product"] == {"id": pid, "name": "Survey quadcopter"}
    # One definition of the lines: everything but the product is the shared sample's.
    assert doc["inputs"]["lines"] == shared["inputs"]["lines"] == samples.SAMPLE_MAINTAINABILITY_INPUTS["lines"]
    assert shared["inputs"] == samples.SAMPLE_MAINTAINABILITY_INPUTS and shared["results"]["product"] is None
    assert "product_id" not in samples.SAMPLE_MAINTAINABILITY_INPUTS
    assert ({k: v for k, v in doc["results"].items() if k != "product"}
            == {k: v for k, v in shared["results"].items() if k != "product"})
    assert doc["results"]["mct"] > 0 and doc["results"]["counts"]["lines"] == len(templates.SAMPLE_PRODUCT_BOM)
    # It is the workspace's own, read and listed like any saved prediction.
    assert maintainability.get_prediction(db, doc["_id"], ORG).name == doc["name"]
    assert [p.id for p in maintainability.list_predictions(db, [ORG])] == [doc["_id"]]

    # Asked again plainly: the product is there, and so is its prediction. No duplicate.
    twice = templates.add_sample_product(m, db)
    assert twice["added"] is False and twice["maintainability"] == {"id": doc["_id"], "name": doc["name"], "added": False}
    assert "maintainability" not in twice["message"] and len(_predictions(db)) == 1
    assert m.s.event_count(ORG) == events  # a saved document, not an event: nothing in the log

    # Another copy: its own prediction, attached to the new product.
    again = templates.add_sample_product(m, db, again=True)
    first, second = _predictions(db)
    assert first["_id"] == doc["_id"] and again["maintainability"]["id"] == second["_id"] != doc["_id"]
    assert second["name"] == "Survey quadcopter 2 — maintainability"
    assert second["inputs"]["product_id"] == again["product"]["id"] != pid
    assert second["results"]["mct"] == doc["results"]["mct"]
    # Another workspace has none of it, and gets its own with its own product.
    other = Maintenance(store, OTHER, "other")
    theirs = templates.add_sample_product(other, db)
    [their_doc] = _predictions(db, OTHER)
    assert their_doc["inputs"]["product_id"] == theirs["product"]["id"] and len(_predictions(db)) == 2
    _rebuilds_the_same(m)


@pytest.mark.parametrize("earlier", [False, True])
def test_a_copy_from_before_gets_its_maintainability_prediction_once(store, db, monkeypatch, earlier):
    """A copy added before it had a maintainability prediction (here: its prediction
    removed) is given one the next time the product is asked for; every copy without one
    is, one under the earlier name ("… (sample)") as much as one added now. A prediction
    of the user's own for the product counts as having one, and an earlier copy made the
    user's own is left alone."""
    m = Maintenance(store, ORG, "tester")
    with _as_before(monkeypatch) if earlier else contextlib.nullcontext():
        first = templates.add_sample_product(m, db)
        second = templates.add_sample_product(m, db, again=True)
    one, two = (("Survey quadcopter (sample)", "Survey quadcopter (sample 2)") if earlier
                else ("Survey quadcopter", "Survey quadcopter 2"))
    assert (first["product"]["name"], second["product"]["name"]) == (one, two)
    db.maintainability_predictions.delete_many({})
    events = m.s.event_count(ORG)

    out = templates.add_sample_product(m, db)
    have = out["product"]  # the copy the seeder answers with, of the two
    assert out["added"] is False and have in (first["product"], second["product"])
    assert out["maintainability"]["added"] and "Added its maintainability prediction" in out["message"]
    assert out["maintainability"]["name"] == f"{have['name']} — maintainability"
    docs = _predictions(db)
    assert {d["inputs"]["product_id"] for d in docs} == {first["product"]["id"], second["product"]["id"]}
    assert {d["name"] for d in docs} == {f"{one} — maintainability", f"{two} — maintainability"}
    assert templates.add_sample_product(m, db)["maintainability"]["added"] is False and len(_predictions(db)) == 2
    assert m.s.event_count(ORG) == events  # nothing written to the log

    # The user's own prediction for the product stands in for it.
    from backend.services import maintainability

    db.maintainability_predictions.delete_many({})
    own = maintainability.save_prediction(
        db, "My repair times", {"product_id": have["id"], "product_name": have["name"],
                                "lines": [{"name": "Motor", "mttr": 1}]}, ORG)
    out = templates.add_sample_product(m, db)
    assert out["maintainability"] == {"id": own.id, "name": "My repair times", "added": False}
    [other_copy] = [x["product"] for x in (first, second) if x["product"] != have]
    assert sorted(d["name"] for d in _predictions(db)) == sorted(["My repair times",
                                                                  f"{other_copy['name']} — maintainability"])

    if not earlier:
        return
    # Made the user's own, an earlier copy is left as it is: nothing is added to it.
    db.maintainability_predictions.delete_many({})
    m.clear_sample(first["product"]["id"])
    m.clear_sample(second["product"]["id"])
    out = templates.add_sample_product(m, db)
    assert out["added"] is False and "maintainability" not in out and _predictions(db) == []
    _rebuilds_the_same(m)


def test_products_and_their_items_stay_off_the_assets_list(store, db):
    m = Maintenance(store, ORG, "tester")
    plant = m.create_position("Pump station")
    m.create_position("Pump 1", parent_id=plant["id"])
    templates.add_sample_product(m, db)
    places = m.places()
    assert places["not_placed"]["positions"] == 2
    assert set(places["not_placed"]["position_ids"]) == {p["id"] for p in m.tree_rows()["positions"]
                                                         if p["name"] in ("Pump station", "Pump 1")}
    assert places["not_placed"]["due"] == 0  # the items' tasks are under Items, not here


def test_a_position_says_which_product_design_it_is_in(store, db):
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    design = {p["name"]: p for p in m.tree_rows()["positions"] if not p.get("design_position_id")}
    product = out["product"]
    assert m.position(design["Motor 2"]["id"])["in_design"] == {"id": product["id"], "name": product["name"]}
    built = out["items"][0]["top_position_id"]
    assert m.position(built)["in_design"] is None


def _modes(sheet: dict) -> list[dict]:
    return [mo for p in sheet["positions"] for fn in p["functions"] for f in fn["failures"] for mo in f["modes"]]


def test_the_design_carries_a_whole_rcm(store, db):
    """Every position has a function with performance standards from the mission, every
    function a functional failure, every mode sits under one, and every mode has a decision
    but the two left undecided on purpose; the performance standards are each breached by a
    functional failure; the higher positions' failures are explained by those below them;
    the decisions that schedule a task have one, and the shared ones read as a programme."""
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    assert {k: out[k] for k in ("functions", "standards", "functional_failures", "failure_modes", "decisions",
                                "causes_linked", "tasks")} == {
        "functions": 47, "standards": 63, "functional_failures": 79, "failure_modes": 84, "decisions": 82,
        "causes_linked": 64, "tasks": 18}
    sheet = m.rcm_worksheet(out["product"]["id"], "below")
    gaps = rcm_graph.gaps(sheet)
    assert gaps["counts"]["functions_without_failure"] == 0 and gaps["counts"]["no_functional_failure"] == 0
    assert gaps["counts"]["standards_without_failure"] == 0 and gaps["counts"]["functional_failures_empty"] == 0
    assert sorted((r["position"]["name"], r["text"]) for r in gaps["undecided"]) == [
        ("Battery pack", "Internal cell short (thermal runaway)"), ("Landing gear", "Landing gear leg breaks on touchdown")]
    # Not analysed: only where an undecided mode is, and the positions above it.
    assert sorted(p["name"] for p in sheet["positions"] if not p["analysed"]) == [
        "Airframe", "Battery pack", "Landing gear", "Power", "Survey quadcopter"]
    # Every position has at least one function; every function has a performance standard
    # but the gimbal's picture function (explained by the camera's).
    assert all(p["functions"] for p in sheet["positions"])
    assert sum(1 for p in sheet["positions"] for fn in p["functions"] if not fn["standards"]) == 1
    propulsion = next(p for p in sheet["positions"] if p["name"] == "Propulsion")
    thrust, hover = propulsion["functions"][0]["failures"]
    assert thrust["modes"] == [] and len(thrust["causes"]) == 12  # four motors, ESCs and propellers (one failure each)
    assert hover["text"] == "Hover throttle above 60 %" and len(hover["causes"]) == 8
    modes = _modes(sheet)
    by_text = {mo["text"]: mo for mo in modes}
    assert "waits on the crushable-foot trial" in by_text["Landing gear leg breaks on touchdown"]["notes"]
    # The whole decision logic: on condition, scheduled discard or restoration, failure finding,
    # run to failure (random and uneconomic), redesign and risk accepted.
    outcomes = {}
    for mo in modes:
        d = mo.get("decision") or {}
        outcomes[d.get("outcome")] = outcomes.get(d.get("outcome"), 0) + 1
    assert outcomes == {"on_condition": 47, "fixed_interval": 9, "failure_finding": 8, "rtf": 7, "redesign": 8,
                        "accept": 3, None: 2}
    assert {(mo["decision"] or {}).get("rtf_basis") for mo in modes if (mo.get("decision") or {}).get("outcome") == "rtf"} \
        == {"random", "uneconomic"}
    # Eight hidden failures (the four failsafes, each IMU failing silently, the BMS cut-off
    # and its state of charge), each with its failure-finding task.
    hidden = [mo for mo in modes if mo["hidden"]]
    assert len(hidden) == 8 and gaps["counts"]["hidden_without_failure_finding"] == 0
    gps = next(p for p in sheet["positions"] if p["name"] == "GPS")
    [fn] = gps["functions"]
    assert [st["text"] for st in fn["standards"]] == ["Horizontal position within 2 m",
                                                      "A fix with at least 12 satellites before take-off"]
    assert [f["text"] for f in fn["failures"]] == ["Position error over 2 m, or no fix",
                                                   "Fewer than 12 satellites at arming"]
    bms = next(p for p in sheet["positions"] if p["name"] == "BMS")
    cutoff = next(mo for mo in _modes({"positions": [bms]}) if mo["text"] == "Cut-off relay welded closed")
    assert cutoff["decision"]["interval"] == 160 and cutoff["decision"]["interval_unit"] == "hours"
    assert [(t["interval"], t["unit"], t["outcome"]) for t in cutoff["tasks"]] == [(160, "hours", "failure_finding")]
    # The programme: shared tasks on the product, each serving the modes that name it, with
    # the modes' checks as its checklist; the four failsafes share one failure-finding test.
    shared = {t["name"]: t for mo in modes for t in mo["tasks"] if t["name"] in templates.SAMPLE_UAV_PROGRAMME_NAMES}
    assert set(shared) == set(templates.SAMPLE_UAV_PROGRAMME_NAMES)
    failsafe = store.node(ORG, shared["Failsafe function tests"]["id"], "Task")
    assert (failsafe["interval"], failsafe["unit"], failsafe["outcome"]) == (1, "months", "failure_finding")
    assert len(failsafe["checklist"]) == 4 and failsafe["checklist"][0].startswith("Link loss:")
    pre_flight = store.node(ORG, shared["Pre-flight check"]["id"], "Task")
    assert (pre_flight["interval"], pre_flight["unit"]) == (1, "flights") and len(pre_flight["checklist"]) == 13
    assert sum(1 for mo in modes if any(t["id"] == pre_flight["id"] for t in mo["tasks"])) == 26
    # New ids everywhere: nothing carries the template's.
    assert not any(n["id"].startswith("sample-") for label in ("Function", "FunctionalFailure", "FailureMode")
                   for n in store.nodes(ORG, label))
    _rebuilds_the_same(m)


def test_the_evidence_check_shows_each_case(store, db):
    """The decisions linked to evidence (the workspace's own copies of the library's
    records, see below): the BMS failure-finding test, the propeller
    replacement, the speed controllers' thermal-pad check (a degradation model), the
    radio's run-to-failure (an exponential fit: random) and the gimbal motor's (a
    replacement analysis with no worthwhile interval) supported; the motors' legacy
    run-to-failure plan contradicted on purpose (the bearing model shows wear-out); the
    battery's retirement inconclusive (its task counts cycles, its analysis flight hours)."""
    from backend.services import samples
    from backend.services.samples import SAMPLE_OWNER

    samples.seed_samples(db)
    m = Maintenance(store, ORG, "tester")
    pid = templates.add_sample_product(m, db)["product"]["id"]
    graph = rcm_graph.resolve(db, m.rcm_worksheet(pid, "below"), [ORG, SAMPLE_OWNER])
    status = {(p["name"], mo["text"]): (mo.get("decision") or {}).get("status")
              for p in graph["positions"] for fn in p["functions"] for f in fn["failures"] for mo in f["modes"]}
    assert status[("BMS", "Cut-off relay welded closed")] == "supported"
    assert status[("Propeller 3", "Blade fatigue crack at the hub")] == "supported"
    assert status[("ESC 4", "Thermal pad dries out; the controller runs hot and limits current")] == "supported"
    assert status[("Comms", "Radio module fails (electronic)")] == "supported"
    assert status[("Payload gimbal", "Gimbal motor stalls on a snagged cable")] == "supported"
    assert status[("Motor 2", "Bearing seizure")] == "contradicted"
    assert status[("Battery pack", "Cell capacity fade")] == "inconclusive"
    assert graph["rollup"] == {"modes": 84, "decided": 82, "supported": 11, "contradicted": 4,
                               "inconclusive": 1, "unevidenced": 55, "stale": 0, "partly": 0,
                               # The motors' legacy run-to-failure plan on a safety consequence breaks the
                               # rules: kept, and counted as needing review (Nov 2026).
                               "needs_review": 4, "undecided": 2, "state": "to_decide"}
    check = rcm_graph.gaps(graph)["evidence_to_check"]
    assert sorted({(r["text"], r["status"]) for r in check}) == [
        ("Bearing seizure", "contradicted"), ("Cell capacity fade", "inconclusive")]
    assert any("wear-out" in r["reason"] for r in check)
    assert any("Unit mismatch" in r["reason"] for r in check)


def test_over_the_route(api):  # noqa: F811
    M = "/api/maintenance"
    r = api.post(f"{M}/sample-product")
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["added"] and len(made["items"]) == 3
    assert api.post(f"{M}/sample-product", json={}).json()["added"] is False
    rbds = api.get("/api/rbds").json()["rbds"]
    assert any(r["id"] == made["rbd"]["id"] for r in rbds)
    # Its maintainability prediction: under the user's own in the list, naming the product, and theirs to change.
    rows = api.get("/api/maintainability/predictions").json()["predictions"]
    [mine] = [p for p in rows if p["id"] == made["maintainability"]["id"]]
    assert mine["product"] == made["product"] and not mine["is_sample"] and not mine["read_only"]
    assert mine["name"] == "Survey quadcopter — maintainability" and mine["lines"] == 11
    [shared] = [p for p in rows if p["is_sample"]]
    assert shared["product"] is None and shared["headline"] == mine["headline"]
    full = api.get(f"/api/maintainability/predictions/{mine['id']}").json()
    assert full["inputs"]["product_id"] == made["product"]["id"] and full["results"]["product"] == made["product"]
    assert len([p for p in rows if not p["is_sample"]]) == 1  # the second plain add made no other
    assert api.get(f"{M}/products").json()["products"][0]["items_built"] == 3
    assert api.get(f"{M}/places").json()["not_placed"]["positions"] == 0
    # The sample truck's route is gone: the sample product is the one sample.
    assert api.post(f"{M}/sample-truck", json={}).status_code in (404, 405)


def test_over_mcp(env):  # noqa: F811
    async def go(client):
        made = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert made["added"] and made["failure_modes"] == 84
        assert made["rbd"]["name"] == "Survey quadcopter: flight-critical RBD"
        assert made["product"]["name"] == "Survey quadcopter" and "sample" not in made["message"].lower()
        assert made["maintainability"]["name"] == "Survey quadcopter — maintainability"
        twice = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert twice["added"] is False and twice["maintainability"]["id"] == made["maintainability"]["id"]
        another = _ok(await _do(client, "maintenance", "products.add_sample", again=True))
        assert another["product"]["name"] == "Survey quadcopter 2"
        assert another["maintainability"]["id"] != made["maintainability"]["id"]
        return True

    assert _session(env["token"], go)


# ---- nothing on it says "sample" (Nov 2026) -------------------------------------------

def _owned(db, owner=ORG) -> dict:
    return {kind: list(db[kind].find({"owner_id": owner}))
            for kind in ("datasets", "models", "degradation_models", "strategy_analyses", "rbds",
                         "maintainability_predictions")}


def test_a_copy_reads_as_a_product_of_your_own(store, seeded):
    """Added now: its name, everything in its graph, every record saved with it and the
    result say "sample" nowhere; it is known by its mark, so the add is still once only;
    and there's nothing to rename on it."""
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, seeded)
    pid = out["product"]["id"]
    assert not _says_sample(out) and "invented" in out["message"]
    assert not _says_sample(m.s.snapshot()) and not _says_sample(_owned(seeded))
    product = m.product(pid)
    assert product["name"] == "Survey quadcopter" and product["sample"] is False
    assert product["template"] == "survey-quadcopter" and product["part"]["name"] == "Survey quadcopter"
    assert [r["name"] for r in m.product_items(pid)["items"]] == [
        f"Survey quadcopter · {serial}" for serial in ("0007", "0008", "0009")]
    [top] = [p for p in m.tree_rows()["positions"] if p["id"] == pid]
    assert "sample" not in top["design"]
    assert out["rbd"]["name"] == "Survey quadcopter: flight-critical RBD"
    assert out["maintainability"]["name"] == "Survey quadcopter — maintainability"
    assert not _says_sample([m.rcm_worksheet(pid, "below"), m.products(), m.failure_reports()])
    # Known by its mark: one event, replayed like the rest.
    marks = m.s.events(ORG, type="design.template_marked")
    assert [e["payload"] for e in marks] == [{"position_id": pid, "template": "survey-quadcopter"}]
    assert m.s.node(ORG, pid)["from_template"] == "survey-quadcopter"
    _rebuilds_the_same(m)
    # Renamed by the user, it is still the copy: asking again adds nothing.
    m.update_position(pid, name="Inspection drone Mk 2")
    twice = templates.add_sample_product(m, seeded)
    assert twice["added"] is False and twice["product"] == {"id": pid, "name": "Inspection drone Mk 2"}
    assert "already in your workspace as “Inspection drone Mk 2”" in twice["message"]
    # Nothing to make your own: it is already.
    with pytest.raises(Exception, match="your own already"):
        templates.make_sample_own(m, seeded, pid)
    with pytest.raises(Exception, match="nothing to rename"):
        templates.make_sample_own(m, seeded)
    # A product of the user's own with that name is not a copy: the Survey quadcopter is still added.
    other = Maintenance(store, OTHER, "other")
    other.create_product("Survey quadcopter", "X-1")
    theirs = templates.add_sample_product(other, seeded)
    assert theirs["added"] and theirs["product"]["name"] == "Survey quadcopter 2"


def test_its_life_models_and_analyses_are_saved_as_the_workspaces_own(store, seeded):
    """The nine library records the product stands on (four life models, the speed
    controller's degradation model, four strategy analyses) and the three datasets behind
    the fitted ones are saved in the workspace under the product's names for them, and
    its positions' links and its decisions' evidence point at those, never the library's.
    A second copy uses the first one's records; one that was deleted is saved again."""
    from backend.services.samples import SAMPLE_OWNER

    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, seeded)
    pid = out["product"]["id"]
    assert out["own_records"] == 9 and out["kept_shared"] == [] and out["kept_note"] == ""
    assert "saved in your workspace as your own (9 records)" in out["message"]
    mine = _owned(seeded)
    assert sorted(d["name"] for d in mine["models"]) == [
        "Bearing life — Weibull", "Quadcopter avionics — Exponential", "Quadcopter battery pack — Weibull",
        "Quadcopter propeller — Weibull"]
    assert [d["name"] for d in mine["degradation_models"]] == ["Quadcopter speed controller — temperature rise"]
    assert sorted(d["name"] for d in mine["strategy_analyses"]) == [
        "Quadcopter BMS cut-off — failure finding", "Quadcopter battery pack — retirement age",
        "Quadcopter gimbal motor — preventive replacement", "Quadcopter propeller — preventive replacement"]
    assert sorted(d["name"] for d in mine["datasets"]) == [
        "Bearing fatigue test", "Quadcopter avionics boards — field failures",
        "Quadcopter speed controller temperature rise"]
    own = {d["copy_of"]: d for kind in ("models", "degradation_models", "strategy_analyses") for d in mine[kind]}
    assert set(own) == {library_id for library_id, _, _ in templates.PRODUCT_RECORDS}
    # The same numbers as the library's record: fitted to the same rows, or the same parameters.
    for library_id, kind, _ in templates.PRODUCT_RECORDS:
        shared = seeded[kind].find_one({"_id": library_id})
        assert shared["owner_id"] == SAMPLE_OWNER and shared["name"].endswith("(sample)")  # the library's is untouched
        if kind == "models":
            assert ([(p["name"], pytest.approx(p["value"])) for p in own[library_id]["results"]["params"]]
                    == [(p["name"], p["value"]) for p in shared["results"]["params"]])
            assert own[library_id]["dataset_id"] in {d["_id"] for d in mine["datasets"]} | {""}
    assert "blade fatigue crack" in own[templates.UAV_PROPELLER_MODEL]["spec"]["notes"]

    # Every link and every piece of evidence in the graph is the workspace's own record.
    ids = {library_id: d["_id"] for library_id, d in own.items()}
    linked = {link["model_id"] for p in m.s.nodes(ORG, "Position") for link in m.position_models(p["id"])}
    assert linked == {ids[x] for x in (templates.UAV_BEARING_MODEL, templates.UAV_PROPELLER_MODEL,
                                       templates.UAV_BATTERY_MODEL, templates.UAV_AVIONICS_MODEL)}
    evidence = {fm["evidence"]["id"] for fm in m.s.nodes(ORG, "FailureMode") if fm.get("evidence")}
    assert evidence == {ids[x] for x in ids if x not in (templates.UAV_PROPELLER_MODEL, templates.UAV_BATTERY_MODEL)}
    assert "sample-" not in json.dumps(m.s.snapshot(), default=str)
    # The template itself still names the library's records: only a copy points away from them.
    assert templates.sample_uav_rcm() == templates.SAMPLE_UAV_RCM
    _rebuilds_the_same(m)

    # A second copy: the same records, none saved twice.
    events = m.s.event_count(ORG)
    again = templates.add_sample_product(m, seeded, again=True)
    assert again["own_records"] == 9 and m.s.event_count(ORG) > events
    after = _owned(seeded)
    assert {k: len(v) for k, v in after.items()} == {
        "datasets": 3, "models": 4, "degradation_models": 1, "strategy_analyses": 4, "rbds": 2,
        "maintainability_predictions": 2}
    assert {link["model_id"] for p in m.s.nodes(ORG, "Position") for link in m.position_models(p["id"])} == linked
    # One the user deleted is saved again for the next copy; the others are reused.
    seeded.models.delete_one({"_id": ids[templates.UAV_BATTERY_MODEL]})
    third = templates.add_sample_product(m, seeded, again=True)
    assert third["own_records"] == 9 and len(_owned(seeded)["models"]) == 4
    # Another workspace gets its own, and sees none of these.
    other = Maintenance(store, OTHER, "other")
    assert templates.add_sample_product(other, seeded)["own_records"] == 9
    assert len(_owned(seeded, OTHER)["models"]) == 4 and len(_owned(seeded)["models"]) == 4
    _rebuilds_the_same(m)


def test_a_full_plan_never_stops_the_add(store, seeded, monkeypatch):
    """On a plan with storage limits (Free: three datasets, three models, one degradation
    model) the records that fit are saved and the rest stay linked to the shared
    library's, named in the result; the product is added whole either way. An operator's
    workspace and a team's have no limit."""
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    m = Maintenance(store, ORG, ORG)
    out = templates.add_sample_product(m, seeded)
    assert out["added"] and out["positions"] == 33 and out["models_linked"] == 10
    # Three models fit (the fourth, the avionics fit, doesn't); strategy analyses have no limit.
    assert out["own_records"] == 8 and out["kept_shared"] == ["Quadcopter avionics — Exponential"]
    # The note the app shows on the product's page once it's added: which, and why.
    assert out["kept_note"] == ("Your plan's storage had no room for Quadcopter avionics — Exponential: that one stays "
                                "linked to the shared library's record.")
    assert out["kept_note"] in out["message"]
    assert ("Your plan's storage had no room for Quadcopter avionics — Exponential: that one stays linked to the "
            "shared library's record.") in out["message"]
    mine = _owned(seeded)
    assert {k: len(v) for k, v in mine.items()} == {
        "datasets": 2, "models": 3, "degradation_models": 1, "strategy_analyses": 4, "rbds": 1,
        "maintainability_predictions": 1}
    assert billing.would_exceed_cap(seeded, ORG, "models")
    links = {link["model_id"] for p in m.s.nodes(ORG, "Position") for link in m.position_models(p["id"])}
    assert templates.UAV_AVIONICS_MODEL in links and len(links) == 4
    _rebuilds_the_same(m)

    # A workspace already at its limits: every capped record stays the library's.
    for n in range(3):
        seeded.models.insert_one({"_id": f"theirs-{n}", "owner_id": OTHER, "name": f"Model {n}"})
    seeded.degradation_models.insert_one({"_id": "theirs-deg", "owner_id": OTHER, "name": "Wear"})
    full = templates.add_sample_product(Maintenance(store, OTHER, OTHER), seeded)
    assert full["added"] and full["own_records"] == 4 and len(full["kept_shared"]) == 5
    assert seeded.datasets.count_documents({"owner_id": OTHER}) == 0

    # An operator and a team: no limit, as for any other save.
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@example.org"})
    seeded.users.insert_one({"_id": "op", "email": "op@example.org", "email_verified": True})
    assert templates.add_sample_product(Maintenance(store, "op", "op"), seeded)["own_records"] == 9
    assert templates.add_sample_product(Maintenance(store, "team:t1", ORG), seeded)["own_records"] == 9


def test_a_record_that_wont_save_never_stops_the_add(store, seeded, monkeypatch):
    from backend.services import strategy_store

    def broken(*args, **kwargs):
        raise RuntimeError("no")

    monkeypatch.setattr(strategy_store, "save_analysis", broken)
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, seeded)
    assert out["added"] and out["own_records"] == 5 and len(out["kept_shared"]) == 4
    assert "couldn't be saved in your workspace: those stay linked to the shared library's records." in out["message"]
    evidence = {fm["evidence"]["id"] for fm in m.s.nodes(ORG, "FailureMode") if fm.get("evidence")}
    assert templates.UAV_GIMBAL_ANALYSIS in evidence and templates.UAV_BEARING_MODEL not in evidence
    _rebuilds_the_same(m)


# ---- a copy added under the earlier name (before Nov 2026) ----------------------------

def _counts(m, pid):
    sheet = m.rcm_worksheet(pid, "below")
    return (len(m._tree_positions(pid)), sum(p["fmea"]["modes"] for p in sheet["positions"]),
            sum(1 for t in m.s.nodes(ORG, "Task") if not t.get("retired")))


def test_an_earlier_copy_is_still_known_by_its_name(store, db, monkeypatch):
    """A copy added as "Survey quadcopter (sample)" replays from the events it was written
    with (none of the new ones), is still the copy the add answers with, and still shows
    as one that can be made the user's own."""
    assert hashlib.sha256(EARLIER_DESCRIPTION.encode()).hexdigest() == templates._EARLIER_DESCRIPTION_SHA256
    m = Maintenance(store, ORG, "tester")
    with _as_before(monkeypatch):
        out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    assert out["product"]["name"] == "Survey quadcopter (sample)"
    assert out["rbd"]["name"] == "Survey quadcopter (sample): flight-critical RBD (placeholder failure rates)"
    types = {e["type"] for e in m.s.events(ORG, limit=100_000)}
    assert len(types) > 10
    assert not types & {"design.template_marked", "position.model_relinked", "position.sample_cleared"}
    assert m.product(pid)["sample"] is True and m.product(pid)["template"] == "survey-quadcopter"
    [top] = [p for p in m.tree_rows()["positions"] if p["id"] == pid]
    assert top["design"]["sample"] is True
    _rebuilds_the_same(m)
    twice = templates.add_sample_product(m, db)
    assert twice["added"] is False and twice["product"] == out["product"]
    assert "already in your workspace as “Survey quadcopter (sample)”" in twice["message"]
    # Asked again, the new copy is added as it is now, beside it.
    fresh = templates.add_sample_product(m, db, again=True)
    assert fresh["product"]["name"] == "Survey quadcopter" and m.product(fresh["product"]["id"])["sample"] is False
    _rebuilds_the_same(m)


def test_make_the_sample_your_own_in_place(store, db, monkeypatch):
    """products.clear_sample: one event renames the copy (no "(sample)") and marks it, its part and built
    items lose the earlier name too; nothing inside changes and every id stays. The add then never puts
    another beside it unless asked, and a fresh copy takes the next free name."""
    m = Maintenance(store, ORG, "tester")
    with _as_before(monkeypatch):
        out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    assert m.product(pid)["sample"] is True
    before_ids = {p["id"] for p in m._tree_positions(pid)}
    before = _counts(m, pid)

    made = m.clear_sample()  # the only copy: no id needed
    assert made["id"] == pid and made["name"] == "Survey quadcopter" and made["sample"] is False
    assert made["was"] == "Survey quadcopter (sample)" and made["part"]["part_number"] == "SQ-4"
    assert made["message"].startswith("“Survey quadcopter (sample)” is “Survey quadcopter” now, a product like any")
    node = m.s.node(ORG, pid)
    assert node["from_sample"] == "survey-quadcopter" and node["design"]
    assert {p["id"] for p in m._tree_positions(pid)} == before_ids and _counts(m, pid) == before
    assert m.s.node(ORG, node["design"]["part_id"])["name"] == "Survey quadcopter"
    items = m.product_items(pid)["items"]
    assert [r["name"] for r in items] == [f"Survey quadcopter · {s}" for s in ("0007", "0008", "0009")]
    assert all(r["item"]["name"] == r["name"] for r in items)
    [top] = [p for p in m.tree_rows()["positions"] if p["id"] == pid]
    assert "sample" not in top["design"]
    _rebuilds_the_same(m)

    # Not twice; and no copy under the earlier name left.
    with pytest.raises(Exception, match="your own already"):
        m.clear_sample(pid)
    with pytest.raises(Exception, match="nothing to rename"):
        m.clear_sample()

    # The add: never a second copy beside it, unless asked.
    again = templates.add_sample_product(m, db)
    assert again["added"] is False and again["product"] == {"id": pid, "name": "Survey quadcopter"}
    assert "renamed as your own" in again["message"] and not _says_sample(again)
    assert len(m.products()["products"]) == 1
    fresh = templates.add_sample_product(m, db, again=True)
    assert fresh["added"] and fresh["product"]["name"] == "Survey quadcopter 2"
    _rebuilds_the_same(m)


def test_make_own_needs_the_copy_when_there_are_two(store, db, monkeypatch):
    m = Maintenance(store, ORG, "tester")
    with _as_before(monkeypatch):
        first = templates.add_sample_product(m, db)
        second = templates.add_sample_product(m, db, again=True)
    with pytest.raises(Exception, match="give product_id"):
        m.clear_sample()
    plain = m.create_product("Pump skid", "PS-1")
    with pytest.raises(Exception, match="doesn't carry “\\(sample\\)” in its name"):
        m.clear_sample(plain["id"])
    assert m.clear_sample(first["product"]["id"])["name"] == "Survey quadcopter"
    assert m.clear_sample(second["product"]["id"])["name"] == "Survey quadcopter 2"


def test_make_own_brings_an_earlier_copy_to_how_it_is_added_now(store, seeded, monkeypatch):
    """templates.make_sample_own on a copy added as "Survey quadcopter (sample)": the
    product, its part, its built items, its RBD, its maintainability prediction and its
    description lose the word; its life models and analyses are saved as the workspace's
    own, and every link (the design's and the built items') and every decision's evidence
    is pointed at them, by events that replay. Afterwards it reads like a copy added now:
    "sample" nowhere, the same evidence verdicts. What the user changed is kept."""
    from backend.services.samples import SAMPLE_OWNER

    m = Maintenance(store, ORG, "tester")
    with _as_before(monkeypatch):
        out = templates.add_sample_product(m, seeded)
    pid = out["product"]["id"]
    assert m.position(pid)["description"] == EARLIER_DESCRIPTION
    assert _owned(seeded)["models"] == [] and _says_sample(m.s.snapshot())
    verdicts = rcm_graph.resolve(seeded, m.rcm_worksheet(pid, "below"), [ORG, SAMPLE_OWNER])["rollup"]
    # The user's own wording on one link stays; it is still pointed at the workspace's model.
    design = m._design_ids()
    named = {p["id"]: p["name"] for p in m.tree_rows()["positions"]}
    [radio] = [link for pos in design if named[pos] == "Comms" for link in m.position_models(pos)]
    m.relink_position_model(radio["id"], radio["model_id"], "Radio life (ours)", "From our returns.")
    ids_before = {n["id"] for n in m.s.snapshot()["nodes"]} if isinstance(m.s.snapshot(), dict) else None

    made = templates.make_sample_own(m, seeded)
    assert made["id"] == pid and made["name"] == "Survey quadcopter" and made["was"] == "Survey quadcopter (sample)"
    assert made["own_records"] == 9 and made["kept_shared"] == [] and made["sample"] is False
    assert made["renamed"] == [
        "part SQ-4", "Survey quadcopter · 0007", "Survey quadcopter · 0008", "Survey quadcopter · 0009",
        "the RBD “Survey quadcopter: flight-critical RBD”", "its description",
        "the maintainability prediction “Survey quadcopter — maintainability”", "40 life-model links on its positions"]
    message = made["message"]
    assert message.startswith("“Survey quadcopter (sample)” is “Survey quadcopter” now")
    assert "Its 9 life model and analysis records are saved in your workspace as your own" in message
    assert not _says_sample({**made, "was": "", "message": message.replace("Survey quadcopter (sample)", "")})
    if ids_before is not None:
        assert {n["id"] for n in m.s.snapshot()["nodes"]} == ids_before  # nothing made, nothing lost

    # Like a copy added now: nothing says "sample", in the graph or in what is saved beside it.
    assert not _says_sample(m.s.snapshot()) and "sample-" not in json.dumps(m.s.snapshot(), default=str)
    mine = _owned(seeded)
    assert not _says_sample(mine)
    assert [d["name"] for d in mine["rbds"]] == ["Survey quadcopter: flight-critical RBD"]
    [prediction] = mine["maintainability_predictions"]
    assert prediction["name"] == "Survey quadcopter — maintainability"
    assert prediction["inputs"]["product_name"] == "Survey quadcopter" == prediction["results"]["product"]["name"]
    assert m.position(pid)["description"] == templates.SAMPLE_PRODUCT_DESCRIPTION
    own = {d["copy_of"]: d["_id"] for kind in ("models", "degradation_models", "strategy_analyses")
           for d in mine[kind]}
    links = [link for p in m.s.nodes(ORG, "Position") for link in m.position_models(p["id"])]
    assert len(links) == 40 and {link["model_id"] for link in links} <= set(own.values())
    assert sum(1 for link in links if link["name"] == "Bearing life — Weibull") == 16
    radios = [link for link in links if link["model_id"] == own[templates.UAV_AVIONICS_MODEL]]
    assert sorted((link["name"], link["note"][:17]) for link in radios) == sorted(
        [("Radio life (ours)", "From our returns.")] + [("Quadcopter avionics — Exponential", "An exponential fi")] * 3)
    after = rcm_graph.resolve(seeded, m.rcm_worksheet(pid, "below"), [ORG])
    assert after["rollup"] == verdicts and after["rollup"]["stale"] == 0
    # The same as a product added now, verdict for verdict.
    fresh = templates.add_sample_product(Maintenance(store, OTHER, "other"), seeded)
    theirs = Maintenance(store, OTHER, "other")
    assert rcm_graph.resolve(seeded, theirs.rcm_worksheet(fresh["product"]["id"], "below"), [OTHER])["rollup"] == verdicts
    _rebuilds_the_same(m)

    # Once: it is the user's own now. The add leaves it be, and its records serve the next copy.
    with pytest.raises(Exception, match="your own already"):
        templates.make_sample_own(m, seeded, pid)
    assert templates.add_sample_product(m, seeded)["added"] is False
    another = templates.add_sample_product(m, seeded, again=True)
    assert another["product"]["name"] == "Survey quadcopter 2" and len(_owned(seeded)["models"]) == 4
    _rebuilds_the_same(m)


def test_make_own_keeps_what_the_user_renamed(store, db, monkeypatch):
    """Only what still carries the name the add gave it is renamed: an RBD, a prediction or
    a description the user rewrote stays as they left it. With no library to copy from,
    the links keep the library's ids and take the names used now."""
    from backend.services import maintainability
    from backend.services import rbds as rbds_service

    m = Maintenance(store, ORG, "tester")
    with _as_before(monkeypatch):
        out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    rbds_service.rename_rbd(db, out["rbd"]["id"], "Flight-critical chain", ORG)
    maintainability.update_prediction(db, out["maintainability"]["id"], ORG, name="Repair times v2")
    m.update_position(pid, description="Our inspection drone.")
    made = templates.make_sample_own(m, db, pid)
    # (The description: the design's is the user's and stays; the built items' tops still carried the earlier one.)
    assert made["renamed"] == ["part SQ-4", "Survey quadcopter · 0007", "Survey quadcopter · 0008",
                               "Survey quadcopter · 0009", "its description", "40 life-model links on its positions"]
    assert made["own_records"] == 0 and "saved in your workspace" not in made["message"]
    mine = _owned(db)
    assert [d["name"] for d in mine["rbds"]] == ["Flight-critical chain"]
    [prediction] = mine["maintainability_predictions"]
    assert prediction["name"] == "Repair times v2" and prediction["inputs"]["product_name"] == "Survey quadcopter"
    assert m.position(pid)["description"] == "Our inspection drone."
    assert not _says_sample([p.get("description") for p in m.s.nodes(ORG, "Position")])
    links = [link for p in m.s.nodes(ORG, "Position") for link in m.position_models(p["id"])]
    assert {link["model_id"] for link in links} == {templates.UAV_BEARING_MODEL, templates.UAV_PROPELLER_MODEL,
                                                    templates.UAV_BATTERY_MODEL, templates.UAV_AVIONICS_MODEL}
    assert not _says_sample([{k: link[k] for k in ("name", "note")} for link in links])
    _rebuilds_the_same(m)


def test_a_designs_tasks_are_its_programme_never_due(store, db):
    """A design is a template: its tasks never fall due, raise no work order and join no package (the LSA
    tab on a design says why); the items built from it carry copies that do, with the LSA records."""
    m = Maintenance(store, ORG, "tester")
    pid = templates.add_sample_product(m, db)["product"]["id"]
    design = m._design_ids()
    def on(t):
        return (_subject(m.s, ORG, t) or {}).get("id")
    calendar = next(t for t in m.s.nodes(ORG, "Task") if t["unit"] in ("days", "weeks", "months", "years")
                    and on(t) in design)
    assert m._task_view(calendar)["next_due"] is None
    m.set_task_resources(calendar["id"], {"labour": [{"trade": "Technician", "hours": 0.5, "people": 1}]})
    table = m.task_table(position_id=pid)
    assert table["design"] is True and table["total"] > 0
    assert all(r["next_due"] is None and not r["overdue"] for r in table["tasks"])
    assert all(r["why_not"] == "a product's design: packaged on the items built from it" for r in table["tasks"])
    assert not [t for t in m.due_tasks(4000) if (t.get("subject") or {}).get("id") in design]
    m.generate(4000)  # the built items' tasks get work orders; the design's none
    assert all(on(w) not in design for w in m.s.nodes(ORG, "WorkOrder"))
    with pytest.raises(Exception, match="product's design"):
        m.open_work_order(None, None, type="preventive", task_id=calendar["id"])
    with pytest.raises(Exception, match="product's design"):
        m.create_package("Design visit", position_id=pid, every=1, unit="months")
    assert all(t["why"].startswith("a product's design") for t in m.propose_packages(position_id=pid)["left_out"])
    # A new item built carries the task with its LSA record, and there it falls due.
    built = m.build_item(pid, "0010", dry_run=False)
    copies = [t for t in m.s.nodes(ORG, "Task") if t["name"] == calendar["name"]
              and on(t) in {r["id"] for r in built["positions"]}]
    assert copies and copies[0]["resources"]["labour"][0]["trade"] == "Technician"
    assert m._task_view(copies[0])["next_due"] is not None
    _rebuilds_the_same(m)


def test_the_programme_has_its_lsa_a_package_and_life_models(store, db):
    """Every programme task has its LSA record (task.resources_set), copied to the items built;
    the calendar tasks are packaged into one monthly visit on the first item; the motors,
    propellers, battery pack and radio carry life models, copied to the items built (here
    the library has no records, so the links name the library's ids)."""
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    design = m._design_ids()

    def on(t):
        return (_subject(m.s, ORG, t) or {}).get("id")

    programme = {t["name"]: t for t in m.s.nodes(ORG, "Task")
                 if t["name"] in templates.SAMPLE_UAV_PROGRAMME_NAMES and on(t) == pid}
    assert set(programme) == set(templates.SAMPLE_UAV_PROGRAMME_NAMES) and out["lsa_records"] == len(programme) == 7
    for task in programme.values():
        r = task["resources"]
        assert r["labour"] and r["tools"] and r["method"] and r["duration_hours"] > 0
    propeller = next(pt for pt in m.s.nodes(ORG, "Part") if pt["part_number"] == "SQ-P1045")
    assert programme["Pre-flight check"]["resources"]["spares"] == [
        {"part_id": propeller["id"], "name": "Propeller 10x4.5", "qty": 4}]
    assert any("Battery analyser" in x["name"] for x in programme["Battery storage check"]["resources"]["tools"])
    # Three calendar tasks, by what they find: a configuration change, a pack draining in storage, age.
    calendar = sorted(name for name, t in programme.items() if t["unit"] in ("days", "weeks", "months", "years"))
    assert calendar == ["Annual inspection", "Battery storage check", "Failsafe function tests"]
    assert (programme["Battery storage check"]["interval"], programme["Battery storage check"]["unit"]) == (3, "months")
    # Each item built carries the programme with its LSA.
    for item in out["items"]:
        copies = [t for t in m.s.nodes(ORG, "Task") if on(t) == item["top_position_id"]
                  and t["name"] in templates.SAMPLE_UAV_PROGRAMME_NAMES]
        assert len(copies) == 7 and all(t.get("resources") for t in copies)

    # One package: the calendar tasks on 0007, monthly, the battery check every third visit and the
    # annual inspection every twelfth.
    [listed] = m.packages()["packages"]
    pkg = m.package(listed["id"])
    assert pkg["name"] == "Monthly maintenance visit" and out["package"]["id"] == pkg["id"]
    assert pkg["subject"]["id"] == out["items"][0]["top_position_id"]
    assert pkg["cadence"]["text"] == "the first Monday of every month"
    assert [(t["name"], t["visit_rule"], t["every_nth"]) for t in pkg["tasks"]] == [
        ("Failsafe function tests", "every", None), ("Battery storage check", "nth", 3),
        ("Annual inspection", "nth", 12)]
    assert pkg["rollup"]["labour_hours"] == 8.5

    # Life models: on the design's motors, propellers, battery pack and radio, each for its failure
    # mode, then copied to the items built (role design).
    named = {p["id"]: p["name"] for p in m.tree_rows()["positions"]}
    links = {named[pos]: m.position_models(pos) for pos in design if m.position_models(pos)}
    assert sorted(links) == ["Battery pack", "Comms", "Motor 1", "Motor 2", "Motor 3", "Motor 4", "Propeller 1",
                             "Propeller 2", "Propeller 3", "Propeller 4"]
    assert out["models_linked"] == 10 and all(len(v) == 1 for v in links.values())
    assert links["Motor 3"][0]["model_id"] == templates.UAV_BEARING_MODEL
    assert [fm["text"] for fm in links["Motor 3"][0]["failure_modes"]] == ["Bearing seizure"]
    assert links["Propeller 2"][0]["model_id"] == templates.UAV_PROPELLER_MODEL
    assert links["Battery pack"][0]["model_id"] == templates.UAV_BATTERY_MODEL
    assert [fm["text"] for fm in links["Comms"][0]["failure_modes"]] == ["Radio module fails (electronic)"]
    assert not _says_sample([{k: link[0][k] for k in ("name", "note")} for link in links.values()])
    assert links["Motor 3"][0]["name"] == "Bearing life — Weibull" and "bench-test bearing lives" in links["Motor 3"][0]["note"]
    built = [link for pos in named if pos not in design for link in m.position_models(pos)]
    assert len(built) == 30 and {link["role"] for link in built} == {"design"}
    _rebuilds_the_same(m)


def test_the_products_life_models_come_from_the_shared_library():
    """The life models the product's records are made from are in the shared library, which
    keeps its own names (the product's are the same without "(sample)"): the bearing and
    avionics fits, and the propeller and battery models from parameters alone, whose notes
    say they're invented."""
    from backend.services import samples

    ids = {s["id"]: s for s in samples.SAMPLE_MODELS}
    own = {library_id: name for library_id, _, name in templates.PRODUCT_RECORDS}
    for _, model_id, name, _, _ in templates.SAMPLE_PRODUCT_MODELS:
        assert ids[model_id]["name"] == f"{name} (sample)" and own[model_id] == name
    for model_id in (templates.UAV_PROPELLER_MODEL, templates.UAV_BATTERY_MODEL):
        assert ids[model_id]["notes"].startswith("Sample values, not field data")
    test_db = mongomock.MongoClient()["shared_samples"]
    samples._seed_params_model(test_db, ids[templates.UAV_PROPELLER_MODEL])
    doc = test_db.models.find_one({"_id": templates.UAV_PROPELLER_MODEL})
    assert samples.is_sample(doc["owner_id"]) and doc["spec"]["params_only"] and doc["dataset_id"] == ""
    assert [(p["name"], p["value"]) for p in doc["results"]["params"]] == [("alpha", 400.0), ("beta", 3.0)]
    assert doc["results"]["unit"] == "Hours"


def test_make_own_over_the_route(api, monkeypatch):  # noqa: F811
    M = "/api/maintenance"
    with _as_before(monkeypatch):
        made = api.post(f"{M}/sample-product").json()
    pid = made["product"]["id"]
    [row] = api.get(f"{M}/products").json()["products"]
    assert row["sample"] is True and row["name"] == "Survey quadcopter (sample)"
    r = api.post(f"{M}/products/{pid}/make-own")
    assert r.status_code == 200, r.text
    own = r.json()
    assert own["name"] == "Survey quadcopter" and own["sample"] is False and own["own_records"] == 9
    assert "the RBD “Survey quadcopter: flight-critical RBD”" in own["renamed"]
    assert [r["name"] for r in api.get("/api/rbds").json()["rbds"] if r["id"] == made["rbd"]["id"]] == [
        "Survey quadcopter: flight-critical RBD"]
    # Its models are the user's own in Models: no "(sample)" name and not flagged as the library's.
    models = [mo for mo in api.get("/api/models").json()["models"] if not mo.get("is_sample")]
    assert sorted(mo["name"] for mo in models) == [
        "Bearing life — Weibull", "Quadcopter avionics — Exponential", "Quadcopter battery pack — Weibull",
        "Quadcopter propeller — Weibull"]
    assert api.post(f"{M}/products/{pid}/make-own").status_code == 422
    assert api.post(f"{M}/sample-product", json={}).json()["added"] is False
    # A copy added now has nothing to make its own.
    fresh = api.post(f"{M}/sample-product", json={"again": True}).json()
    assert fresh["product"]["name"] == "Survey quadcopter 2"
    assert api.post(f"{M}/products/{fresh['product']['id']}/make-own").status_code == 422
    rows = {r["name"]: r for r in api.get(f"{M}/products").json()["products"]}
    assert rows["Survey quadcopter 2"]["sample"] is False and rows["Survey quadcopter 2"]["template"] == "survey-quadcopter"


def test_make_own_over_mcp(env, monkeypatch):  # noqa: F811
    async def go(client):
        with _as_before(monkeypatch):
            made = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert made["product"]["name"] == "Survey quadcopter (sample)"
        own = _ok(await _do(client, "maintenance", "products.add_sample", make_own=True))
        assert own["id"] == made["product"]["id"] and own["name"] == "Survey quadcopter"
        assert "the RBD “Survey quadcopter: flight-critical RBD”" in own["renamed"]
        twice = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert twice["added"] is False and twice["product"]["name"] == "Survey quadcopter"
        return True

    assert _session(env["token"], go)
