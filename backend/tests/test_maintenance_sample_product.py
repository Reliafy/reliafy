"""The sample product: "Add the sample UAV product" on Products (and "Open the sample
UAV product" on the Explorer) adds an invented quadcopter's design, the one sample for
the RCM and FME(C)A tabs (its RCM, some decisions linked to sample evidence, on every
position the modes belong to),
its part with a bill of materials, three items built from it, a replaced motor, two
failure reports and a flight-critical RBD with placeholder failure rates, through the
ordinary service methods (events), once unless asked again; over the app's route,
MCP (maintenance products.add_sample) and the CLI. Products' trees stay off the
Assets list."""

import mongomock
import pytest

from backend.maintenance import rcm_graph, templates
from backend.maintenance.service import PROJECTORS, Maintenance
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
    # The design: 25 positions, the sample's modes on each motor, ESC, propeller and IMU.
    assert {k: out[k] for k in ("positions", "failure_modes", "scored")} == {
        "positions": 25, "failure_modes": 41, "scored": 41}
    [product] = m.products()["products"]
    assert product["id"] == pid and product["rev"] == "C" and product["part"]["part_number"] == "SQ-4"
    assert product["positions"] == 25 and product["items_built"] == 3 and product["open_reports"] == 2
    tree = m.tree_rows()["positions"]
    names = {p["name"] for p in tree if p.get("design_position_id") is None}
    assert {"Motor 1", "Motor 4", "ESC 4", "Propeller 4", "IMU 1", "IMU 2", "GPS", "BMS", "Comms",
            "Payload gimbal"} <= names
    sheet = m.rcm_worksheet(pid, "below")
    motors = [p for p in sheet["positions"] if p["name"].startswith("Motor ")]
    assert len(motors) == 4 and all(p["fmea"]["max_rpn"] == 216 for p in motors)

    # Its part and bill of materials: four motors in one quadcopter.
    structure = m.part_structure(product["part"]["id"])
    lines = {c["part_number"]: c["qty"] for c in structure["tree"]["children"]}
    assert lines["SQ-M2210"] == 4 and lines["SQ-IMU9"] == 2 and len(lines) == 11

    # Three items, by serial, with their revisions and flight hours.
    items = m.product_items(pid)["items"]
    assert [(r["serial"], r["rev"], r["hours"]["value"]) for r in items] == [
        ("0007", "C", 212), ("0008", "C", 31), ("0009", "B", 640)]
    assert [r["open_reports"] for r in items] == [1, 0, 1]

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
    """Every position has a function, every function a functional failure, every mode sits
    under one, and every mode has a decision but the two left undecided on purpose; the
    performance standards are each breached by a functional failure; the higher positions'
    failures are explained by those below them; the decisions that schedule a task have one."""
    m = Maintenance(store, ORG, "tester")
    out = templates.add_sample_product(m, db)
    assert {k: out[k] for k in ("functions", "standards", "functional_failures", "failure_modes", "decisions",
                                "causes_linked")} == {
        "functions": 25, "standards": 4, "functional_failures": 34, "failure_modes": 41, "decisions": 39,
        "causes_linked": 29}
    sheet = m.rcm_worksheet(out["product"]["id"], "below")
    gaps = rcm_graph.gaps(sheet)
    assert gaps["counts"]["functions_without_failure"] == 0 and gaps["counts"]["no_functional_failure"] == 0
    assert gaps["counts"]["standards_without_failure"] == 0 and gaps["counts"]["functional_failures_empty"] == 0
    assert sorted((r["position"]["name"], r["text"]) for r in gaps["undecided"]) == [
        ("Airframe", "Landing gear leg breaks on touchdown"), ("Battery pack", "Internal cell short (thermal runaway)")]
    # Not analysed: only where an undecided mode is, and the positions above it.
    assert sorted(p["name"] for p in sheet["positions"] if not p["analysed"]) == [
        "Airframe", "Battery pack", "Power", "Survey quadcopter (sample)"]
    propulsion = next(p for p in sheet["positions"] if p["name"] == "Propulsion")
    [thrust] = propulsion["functions"][0]["failures"]
    assert thrust["modes"] == [] and len(thrust["causes"]) == 16  # four motors, ESCs and propellers (two failures each)
    by_text = {mo["text"]: mo for mo in _modes(sheet)}
    assert "waits on the crushable-foot trial" in by_text["Landing gear leg breaks on touchdown"]["notes"]
    # Three hidden failures (the BMS cut-off, each IMU failing silently), each with its failure-finding task.
    hidden = [mo for mo in _modes(sheet) if mo["consequence"] == "hidden"]
    assert len(hidden) == 3 and gaps["counts"]["hidden_without_failure_finding"] == 0
    gps = next(p for p in sheet["positions"] if p["name"] == "GPS")
    [fn] = gps["functions"]
    assert [st["text"] for st in fn["standards"]] == ["Horizontal position within 2 m"]
    assert [f["text"] for f in fn["failures"]] == ["Position error over 2 m, or no fix"]
    bms = next(p for p in sheet["positions"] if p["name"] == "BMS")
    [cutoff] = _modes({"positions": [bms]})
    assert cutoff["decision"]["interval"] == 160 and cutoff["decision"]["interval_unit"] == "hours"
    assert [(t["interval"], t["unit"], t["outcome"]) for t in cutoff["tasks"]] == [(160, "hours", "failure_finding")]
    # New ids everywhere: nothing carries the template's.
    assert not any(n["id"].startswith("sample-") for label in ("Function", "FunctionalFailure", "FailureMode")
                   for n in store.nodes(ORG, label))
    _rebuilds_the_same(m)


def test_the_evidence_check_shows_each_case(store, db):
    """The decisions linked to sample evidence: the BMS failure-finding test and the
    propeller replacement supported; the motors' legacy run-to-failure plan contradicted
    on purpose (the bearing model shows wear-out); the battery's retirement inconclusive
    (its task counts cycles, its analysis flight hours)."""
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
    assert status[("Motor 2", "Bearing seizure")] == "contradicted"
    assert status[("Battery pack", "Cell capacity fade")] == "inconclusive"
    assert graph["rollup"] == {"modes": 41, "decided": 39, "supported": 5, "contradicted": 4,
                               "inconclusive": 1, "unevidenced": 23, "stale": 0}
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
    assert api.get(f"{M}/products").json()["products"][0]["items_built"] == 3
    assert api.get(f"{M}/places").json()["not_placed"]["positions"] == 0
    # The sample truck's route is gone: the sample product is the one sample.
    assert api.post(f"{M}/sample-truck", json={}).status_code in (404, 405)


def test_over_mcp(env):  # noqa: F811
    async def go(client):
        made = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert made["added"] and made["failure_modes"] == 41
        assert made["rbd"]["name"].endswith("(placeholder failure rates)")
        twice = _ok(await _do(client, "maintenance", "products.add_sample"))
        assert twice["added"] is False
        another = _ok(await _do(client, "maintenance", "products.add_sample", again=True))
        assert another["product"]["name"] == "Survey quadcopter (sample 2)"
        return True

    assert _session(env["token"], go)
