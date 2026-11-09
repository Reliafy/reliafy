"""The sample product: "Add the sample UAV product" on Products (and "Open the sample
UAV product" on the Explorer) adds an invented inspection quadcopter's design, the one
sample for the RCM and FME(C)A tabs: a complete RCM study for its mission (the operating
context on the top position; functions with performance standards on every position;
functional failures breaching them, the higher ones explained by the lower; failure
modes scored and decided, some decisions linked to sample evidence; the decisions'
tasks as the maintenance programme), its part with a bill of materials, three items
built from it, a replaced motor, two failure reports and a flight-critical RBD with
placeholder failure rates, through the ordinary service methods (events), once unless
asked again; over the app's route, MCP (maintenance products.add_sample) and the CLI.
Products' trees stay off the Assets list."""

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


def test_the_sample_product_is_a_design_with_items_built_and_reports(store, db):
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    assert out["added"] and out["product"]["name"] == "Survey quadcopter (sample)"
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
    assert rbd["name"] == "Survey quadcopter (sample): flight-critical RBD (placeholder failure rates)"
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
    # Made the user's own, it is the same design: the same starting points.
    m.clear_sample(pid)
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
    assert "already in your workspace as “Survey quadcopter (sample)”" in twice["message"]
    again = templates.add_sample_product(m, db, again=True)
    assert again["added"] and again["product"]["name"] == "Survey quadcopter (sample 2)"
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
    assert doc["name"] == "Survey quadcopter (sample) — maintainability"
    assert "maintainability prediction “Survey quadcopter (sample) — maintainability”" in out["message"]
    # Attached to the product: the id the product page and the prediction's own page go by.
    assert (doc["inputs"]["product_id"], doc["inputs"]["product_name"]) == (pid, "Survey quadcopter (sample)")
    assert doc["results"]["product"] == {"id": pid, "name": "Survey quadcopter (sample)"}
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
    assert second["name"] == "Survey quadcopter (sample 2) — maintainability"
    assert second["inputs"]["product_id"] == again["product"]["id"] != pid
    assert second["results"]["mct"] == doc["results"]["mct"]
    # Another workspace has none of it, and gets its own with its own product.
    other = Maintenance(store, OTHER, "other")
    theirs = templates.add_sample_product(other, db)
    [their_doc] = _predictions(db, OTHER)
    assert their_doc["inputs"]["product_id"] == theirs["product"]["id"] and len(_predictions(db)) == 2
    _rebuilds_the_same(m)


def test_a_copy_from_before_gets_its_maintainability_prediction_once(store, db):
    """A copy of the sample added before it had a maintainability prediction (here: its
    prediction removed) is given one the next time the sample is asked for; every copy
    without one is. A prediction of the user's own for the product counts as having one,
    and a copy made the user's own is left alone."""
    m = Maintenance(store, ORG, "tester")
    first = templates.add_sample_product(m, db)
    second = templates.add_sample_product(m, db, again=True)
    db.maintainability_predictions.delete_many({})
    events = m.s.event_count(ORG)

    out = templates.add_sample_product(m, db)
    have = out["product"]  # the copy the seeder answers with, of the two
    assert out["added"] is False and have in (first["product"], second["product"])
    assert out["maintainability"]["added"] and "Added its maintainability prediction" in out["message"]
    assert out["maintainability"]["name"] == f"{have['name']} — maintainability"
    docs = _predictions(db)
    assert {d["inputs"]["product_id"] for d in docs} == {first["product"]["id"], second["product"]["id"]}
    assert {d["name"] for d in docs} == {"Survey quadcopter (sample) — maintainability",
                                         "Survey quadcopter (sample 2) — maintainability"}
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

    # Made the user's own, a copy isn't the sample any more: nothing is added to it.
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
        "Airframe", "Battery pack", "Landing gear", "Power", "Survey quadcopter (sample)"]
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
    """The decisions linked to sample evidence: the BMS failure-finding test, the propeller
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
    assert mine["name"] == "Survey quadcopter (sample) — maintainability" and mine["lines"] == 11
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
        assert made["rbd"]["name"].endswith("(placeholder failure rates)")
        assert made["maintainability"]["name"] == "Survey quadcopter (sample) — maintainability"
        twice = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert twice["added"] is False and twice["maintainability"]["id"] == made["maintainability"]["id"]
        another = _ok(await _do(client, "maintenance", "products.add_sample", again=True))
        assert another["product"]["name"] == "Survey quadcopter (sample 2)"
        assert another["maintainability"]["id"] != made["maintainability"]["id"]
        return True

    assert _session(env["token"], go)


# ---- making the sample your own (9 Nov 2026) -----------------------------------------

def _counts(m, pid):
    sheet = m.rcm_worksheet(pid, "below")
    return (len(m._tree_positions(pid)), sum(p["fmea"]["modes"] for p in sheet["positions"]),
            sum(1 for t in m.s.nodes(ORG, "Task") if not t.get("retired")))


def test_make_the_sample_your_own_in_place(store, db):
    """products.clear_sample: one event renames the copy (no "(sample)") and marks it, its part and built
    items lose the sample's name too; nothing inside changes and every id stays. The seeder then never adds
    the sample beside it unless asked, and a fresh copy made your own takes the next free name."""
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    pid = out["product"]["id"]
    assert m.product(pid)["sample"] is True
    [top] = [p for p in m.tree_rows()["positions"] if p["id"] == pid]
    assert top["design"]["sample"] is True
    before_ids = {p["id"] for p in m._tree_positions(pid)}
    before = _counts(m, pid)

    made = m.clear_sample()  # the only copy: no id needed
    assert made["id"] == pid and made["name"] == "Survey quadcopter" and made["sample"] is False
    assert made["was"] == "Survey quadcopter (sample)" and made["part"]["part_number"] == "SQ-4"
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

    # Not twice; and no sample copy left to make your own.
    with pytest.raises(Exception, match="your own already"):
        m.clear_sample(pid)
    with pytest.raises(Exception, match="no copy of the sample product"):
        m.clear_sample()

    # The seeder: never a second copy beside it, unless asked.
    again = templates.add_sample_product(m, db)
    assert again["added"] is False and again["product"] == {"id": pid, "name": "Survey quadcopter"}
    assert "made the sample product your own" in again["message"]
    assert len(m.products()["products"]) == 1
    fresh = templates.add_sample_product(m, db, again=True)
    assert fresh["added"] and fresh["product"]["name"] == "Survey quadcopter (sample)"
    second = m.clear_sample(fresh["product"]["id"])
    assert second["name"] == "Survey quadcopter 2"
    _rebuilds_the_same(m)


def test_make_own_needs_the_copy_when_there_are_two(store, db):
    m = Maintenance(store, ORG, "tester")
    first = templates.add_sample_product(m, db)
    templates.add_sample_product(m, db, again=True)
    with pytest.raises(Exception, match="give product_id"):
        m.clear_sample()
    plain = m.create_product("Pump skid", "PS-1")
    with pytest.raises(Exception, match="isn't a copy of the sample product"):
        m.clear_sample(plain["id"])
    assert m.clear_sample(first["product"]["id"])["name"] == "Survey quadcopter"


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
    propellers, battery pack and radio carry shared sample life models, each saying it's
    sample values, copied to the items built."""
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
    assert all(v[0]["note"].startswith("Sample values, not field data") for v in links.values())
    built = [link for pos in named if pos not in design for link in m.position_models(pos)]
    assert len(built) == 30 and {link["role"] for link in built} == {"design"}
    _rebuilds_the_same(m)


def test_the_sample_life_models_are_shared_samples():
    """The life models the sample product links are shared samples: the bearing and avionics fits,
    and the propeller and battery models from parameters alone, whose notes say they're invented."""
    from backend.services import samples

    ids = {s["id"]: s for s in samples.SAMPLE_MODELS}
    for _, model_id, name, _, _ in templates.SAMPLE_PRODUCT_MODELS:
        assert ids[model_id]["name"] == name
    for model_id in (templates.UAV_PROPELLER_MODEL, templates.UAV_BATTERY_MODEL):
        assert ids[model_id]["notes"].startswith("Sample values, not field data")
    test_db = mongomock.MongoClient()["shared_samples"]
    samples._seed_params_model(test_db, ids[templates.UAV_PROPELLER_MODEL])
    doc = test_db.models.find_one({"_id": templates.UAV_PROPELLER_MODEL})
    assert samples.is_sample(doc["owner_id"]) and doc["spec"]["params_only"] and doc["dataset_id"] == ""
    assert [(p["name"], p["value"]) for p in doc["results"]["params"]] == [("alpha", 400.0), ("beta", 3.0)]
    assert doc["results"]["unit"] == "Hours"


def test_make_own_over_the_route(api):  # noqa: F811
    M = "/api/maintenance"
    made = api.post(f"{M}/sample-product").json()
    pid = made["product"]["id"]
    assert api.get(f"{M}/products").json()["products"][0]["sample"] is True
    r = api.post(f"{M}/products/{pid}/make-own")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Survey quadcopter" and r.json()["sample"] is False
    assert api.post(f"{M}/products/{pid}/make-own").status_code == 422
    assert api.post(f"{M}/sample-product", json={}).json()["added"] is False


def test_make_own_over_mcp(env):  # noqa: F811
    async def go(client):
        made = _ok(await _do(client, "maintenance", "products.add_sample"))
        own = _ok(await _do(client, "maintenance", "products.add_sample", make_own=True))
        assert own["id"] == made["product"]["id"] and own["name"] == "Survey quadcopter"
        twice = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert twice["added"] is False and twice["product"]["name"] == "Survey quadcopter"
        return True

    assert _session(env["token"], go)
