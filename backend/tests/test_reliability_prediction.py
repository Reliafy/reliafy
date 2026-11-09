"""Reliability prediction: a parts count from the library's handbook base
rates (backend/services/reliability_prediction.py). The maths by hand, the
roll-up over assemblies, a product's parts list as lines, the app's routes,
the MCP actions (and so REST and the CLI), and the shared sample."""

import math

import mongomock
import pytest

from backend.services import reliability_prediction as rp
from backend.services.reliability_prediction import PredictionError
from backend.tests.test_mcp_plans import FREE, env  # noqa: F401

DIODE = "mil-hdbk-217f-n2:6-1-general-purpose-analog"  # λb 0.0038, πE GF 6, ARW 24; πQ 0.7–8
CAP = "mil-hdbk-217f-n2:10-1-ck-11015"  # λb 0.00099, GF 10
SOLDER = "mil-hdbk-217f-n2:17-1-reflow-solder"  # λb 6.9e-5, GF 2; no πQ in its model
FIELD = "nrc-inl-2020:mdp-fts-ns"  # field data, not a handbook part type
OWNER, OTHER = "user-a", "user-b"


# ---- the maths -------------------------------------------------------------------------------

def test_one_diode_line_by_hand():
    out = rp.compute([{"name": "D1", "record_id": DIODE}], "GF", 1000)
    [line] = out["lines"]
    assert line["base_rate_per_million_hours"] == 0.0038 and line["environment_factor"] == 6
    assert line["quality_factor"] == 1 and line["quantity"] == 1
    assert line["rate_per_million_hours"] == pytest.approx(0.0228)
    assert line["rate_per_hour"] == pytest.approx(2.28e-8)
    assert out["failure_rate_per_million_hours"] == pytest.approx(0.0228)
    assert out["mtbf_hours"] == pytest.approx(1e6 / 0.0228)
    assert out["reliability_at_mission"] == pytest.approx(math.exp(-0.0228e-6 * 1000))
    assert out["unreliability_at_mission"] == pytest.approx(1 - math.exp(-0.0228e-6 * 1000))
    assert line["applied"] == ["λb", "πE", "πQ"]
    assert [f["symbol"] for f in line["not_applied"]] == ["πT", "πS", "πC"]  # πQ is applied, so not listed
    assert line["share"] == 1 and out["counts"] == {"lines": 1, "assigned": 1, "unassigned": 0, "excluded": 0, "parts": 1,
                                                    "parts_assigned": 1}
    assert out["environment"] == {"code": "GF", "name": "Ground, fixed",
                                  "covers": "Permanent racks with adequate cooling, perhaps in unheated buildings."}
    assert out["warnings"] == [] and out["sources"][0]["id"] == "mil-hdbk-217f-n2"
    assert "attribution" in out["sources"][0] and out["records"][DIODE]["version"] == 1


def test_quantity_quality_and_environment_scale_the_line():
    two = rp.compute([{"name": "D", "record_id": DIODE, "quantity": 2}], "GF")
    assert two["failure_rate_per_million_hours"] == pytest.approx(0.0456)
    assert two["lines"][0]["each_per_million_hours"] == pytest.approx(0.0228)
    quality = rp.compute([{"name": "D", "record_id": DIODE, "quality_factor": 2}], "gf")  # any case
    assert quality["failure_rate_per_million_hours"] == pytest.approx(0.0456)
    arw = rp.compute([{"name": "D", "record_id": DIODE}], "ARW")
    assert arw["failure_rate_per_million_hours"] == pytest.approx(0.0038 * 24)
    assert arw["environment"]["name"] == "Airborne, rotary winged"
    assert rp.compute([{"name": "D", "record_id": DIODE}], "GF", 1000)["mission_time_hours"] == 1000


def test_rates_add_in_series_with_a_pareto_by_line_and_category():
    out = rp.compute([
        {"name": "D1", "record_id": DIODE, "quantity": 10},  # 0.228
        {"name": "C1", "record_id": CAP, "quantity": 100},  # 0.00099 × 10 × 100 = 0.99
        {"name": "C2", "record_id": CAP, "quantity": 20},  # 0.198
    ], "GF")
    assert out["failure_rate_per_million_hours"] == pytest.approx(0.228 + 0.99 + 0.198)
    by_line = out["pareto"]["by_line"]
    assert [r["name"] for r in by_line] == ["C1", "D1", "C2"]
    assert by_line[0]["share"] == pytest.approx(0.99 / 1.416) and by_line[-1]["cumulative_share"] == pytest.approx(1)
    by_cat = out["pareto"]["by_category"]
    assert [(r["name"], r["lines"], r["parts"]) for r in by_cat] == [("Capacitors", 2, 120),
                                                                      ("Diodes, transistors and other semiconductors", 1, 10)]
    assert by_cat[0]["rate_per_million_hours"] == pytest.approx(1.188)
    # Factors the handbook has that aren't applied: the union, with the same symbol kept apart by meaning.
    symbols = {(f["symbol"], f["name"]) for f in out["factors"]["not_applied"]}
    assert ("πC", "contact construction") in symbols and ("πC", "capacitance") in symbols
    assert [a["symbol"] for a in out["factors"]["applied"]] == ["λb", "πE", "πQ"]
    assert out["assemblies"] == []  # nothing grouped


def test_roll_up_over_a_two_level_product_tree():
    lines = [
        {"name": "Cap", "record_id": CAP, "quantity": 10, "assembly": ["Power", "BMS board"]},  # 0.099
        {"name": "Diode", "record_id": DIODE, "quantity": 1, "assembly": "Power"},  # 0.0228, directly in Power
        {"name": "Cap", "record_id": CAP, "quantity": 30, "assembly": "Flight control › Controller"},  # 0.297
        {"name": "Diode", "record_id": DIODE, "quantity": 2},  # 0.0456, in no assembly
    ]
    out = rp.compute(lines, "GF")
    total = 0.099 + 0.0228 + 0.297 + 0.0456
    assert out["failure_rate_per_million_hours"] == pytest.approx(total)
    rows = {r["label"]: r for r in out["assemblies"]}
    assert [r["label"] for r in out["assemblies"]] == [
        "Power", "Power › BMS board", "Flight control", "Flight control › Controller", ""]
    assert [r["depth"] for r in out["assemblies"]] == [0, 1, 0, 1, 0]
    assert rows["Power"]["rate_per_million_hours"] == pytest.approx(0.099 + 0.0228)
    assert rows["Power"]["lines"] == 2 and rows["Power"]["parts"] == 11
    assert rows["Power › BMS board"]["rate_per_million_hours"] == pytest.approx(0.099)
    assert rows["Power › BMS board"]["name"] == "BMS board" and rows["Power › BMS board"]["path"] == ["Power", "BMS board"]
    assert rows["Flight control"]["rate_per_million_hours"] == pytest.approx(0.297)
    assert rows["Flight control"]["mtbf_hours"] == pytest.approx(1e6 / 0.297)
    assert rows[""]["name"] == "Not in an assembly" and rows[""]["rate_per_million_hours"] == pytest.approx(0.0456)
    # The top-level assemblies and the loose lines add up to the total.
    assert sum(r["rate_per_million_hours"] for r in out["assemblies"] if r["depth"] == 0) == pytest.approx(total)
    assert out["lines"][2]["assembly"] == ["Flight control", "Controller"]


def test_a_line_without_a_part_type_is_listed_and_left_out():
    out = rp.compute([{"name": "Motor", "quantity": 4, "reference": "SQ-M2210"},
                      {"name": "D", "record_id": DIODE}], "GF")
    assert out["failure_rate_per_million_hours"] == pytest.approx(0.0228)
    assert out["counts"] == {"lines": 2, "assigned": 1, "unassigned": 1, "excluded": 0, "parts": 5,
                             "parts_assigned": 1}
    assert out["unassigned"] == [{"name": "Motor", "reference": "SQ-M2210", "quantity": 4, "assembly": []}]
    assert out["lines"][0]["assigned"] is False and out["lines"][0]["rate_per_million_hours"] is None
    assert out["warnings"] == ["1 line has no handbook part type and is left out of the total: Motor (×4)."]
    nothing = rp.compute([{"name": "Motor"}], "GF")
    assert nothing["mtbf_hours"] is None and nothing["reliability_at_mission"] is None
    assert nothing["warnings"][0] == "No line has a handbook part type yet, so there is no total."


def test_quality_factor_range_and_parts_without_one():
    out = rp.compute([{"name": "D", "record_id": DIODE, "quality_factor": 20}], "GF")
    assert out["lines"][0]["quality_factor_range"] == [0.7, 8.0]
    assert out["warnings"] == ["'D': πQ 20 is outside the handbook's 0.7–8 for Diode, low frequency, general purpose analog."]
    joints = rp.compute([{"name": "Joints", "record_id": SOLDER, "quantity": 100}], "GF")
    assert joints["lines"][0]["quality_factor_range"] is None
    assert joints["failure_rate_per_million_hours"] == pytest.approx(6.9e-5 * 2 * 100)
    with pytest.raises(PredictionError, match="has no quality factor"):
        rp.compute([{"name": "Joints", "record_id": SOLDER, "quality_factor": 2}], "GF")


def test_refusals_say_what_to_do():
    with pytest.raises(PredictionError, match="Unknown environment 'XX'"):
        rp.compute([{"name": "D", "record_id": DIODE}], "XX")
    with pytest.raises(PredictionError, match="not a handbook part type"):
        rp.compute([{"name": "Pump", "record_id": FIELD}], "GF")
    with pytest.raises(PredictionError, match="no library record 'nope'"):
        rp.compute([{"name": "D", "record_id": "nope"}], "GF")
    with pytest.raises(PredictionError, match="empty"):
        rp.compute([], "GF")
    with pytest.raises(PredictionError, match="Line 1 needs a name"):
        rp.compute([{"record_id": DIODE}], "GF")
    with pytest.raises(PredictionError, match="quantity must be above 0"):
        rp.compute([{"name": "D", "record_id": DIODE, "quantity": 0}], "GF")
    with pytest.raises(PredictionError, match="mission_time"):
        rp.compute([{"name": "D", "record_id": DIODE}], "GF", -5)
    with pytest.raises(PredictionError, match="at most 8 levels"):
        rp.compute([{"name": "D", "record_id": DIODE, "assembly": ["a"] * 9}], "GF")
    # The record without an environment factor: λb × πQ, said so.
    lamp = rp.compute([{"name": "Lamp", "record_id": "mil-hdbk-217f-n2:23-1-neon-lamp"}], "GF")
    assert lamp["lines"][0]["environment_factor"] is None and lamp["lines"][0]["applied"] == ["λb", "πQ"]
    assert lamp["failure_rate_per_million_hours"] == pytest.approx(0.2)
    assert "no environment factor" in lamp["warnings"][0]


def test_words_for_lists():
    assert rp.fmt_sig(480769.2) == "481,000" and rp.fmt_sig(2.0812) == "2.08" and rp.fmt_sig(0.02279) == "0.0228"
    assert rp.fmt_sig(None) == "—" and rp.fmt_sig(float("inf")) == "—" and rp.fmt_sig(0) == "0"
    assert rp.assembly_path("Power › BMS board") == ["Power", "BMS board"]
    assert rp.assembly_path("Power / BMS") == ["Power", "BMS"] and rp.assembly_path(" ") == []


# ---- a product's parts list -------------------------------------------------------------------

def test_lines_from_a_product_follow_its_structure():
    """A product's part has a two-level bill of materials: lowest-level parts
    become lines under their assemblies, with the quantity in one product."""
    from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
    from backend.maintenance.store import GraphStore

    m = Maintenance(GraphStore(":memory:", PROJECTORS), OWNER, "tester")
    product = m.create_product("Controller box", part_number="CB-1", rev="A")
    top = product["part"]["id"]
    board = m.create_part("PCB-1", "Main board")
    psu = m.create_part("PSU-1", "Power supply")
    cap = m.create_part("C-100", "Capacitor 100 nF")
    diode = m.create_part("D-1", "Diode")
    m.add_component(top, board["id"], quantity=2)
    m.add_component(top, psu["id"], quantity=1)
    m.add_component(board["id"], cap["id"], quantity=30)
    m.add_component(psu["id"], diode["id"], quantity=4)
    m.add_component(top, diode["id"], quantity=1)  # one loose diode at the top
    out = rp.lines_from_product(m, product["id"])
    assert out["product"] == {"id": product["id"], "name": "Controller box", "rev": "A", "part_number": "CB-1"}
    lines = {(ln["name"], tuple(ln["assembly"])): ln for ln in out["lines"]}
    assert lines[("Capacitor 100 nF", ("Main board",))]["quantity"] == 60  # 30 in each of 2 boards
    assert lines[("Diode", ("Power supply",))]["quantity"] == 4
    assert lines[("Diode", ())]["quantity"] == 1 and lines[("Diode", ())]["reference"] == "D-1"
    # No quality factor yet: each part type's default applies when one is chosen.
    assert all(ln["record_id"] is None and ln["quality_factor"] is None for ln in out["lines"])
    assert out["assemblies"] == 2 and out["warnings"] == []
    # Computed with part types assigned, the assembly roll-up follows the tree.
    for ln in out["lines"]:
        ln["record_id"] = CAP if ln["name"].startswith("Cap") else DIODE
    res = rp.compute(out["lines"], "GF")
    rows = {r["label"]: r["rate_per_million_hours"] for r in res["assemblies"]}
    assert rows["Main board"] == pytest.approx(0.00099 * 10 * 60)
    assert rows["Power supply"] == pytest.approx(0.0228 * 4) and rows[""] == pytest.approx(0.0228)
    # A product with no part, and a position that isn't a product.
    bare = m.create_product("Bare", rev="A")
    assert rp.lines_from_product(m, bare["id"])["lines"] == []
    assert "no part yet" in rp.lines_from_product(m, bare["id"])["warnings"][0]
    plain = m.create_position("Plant")
    with pytest.raises(Invalid, match="isn't a product"):
        rp.lines_from_product(m, plain["id"])


# ---- the app's routes --------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.com", "name": "A"}
    tc = TestClient(app)
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


LINES = [{"name": "D1", "record_id": DIODE, "quantity": 2, "assembly": "Power"},
         {"name": "C1", "record_id": CAP, "quantity": 10}]


def test_compute_save_list_get_rename_and_delete_over_the_app(client):
    r = client.post("/api/predictions/compute", json={"lines": LINES, "environment": "GF", "mission_time": 500})
    assert r.status_code == 200
    assert r.json()["failure_rate_per_million_hours"] == pytest.approx(0.0456 + 0.099)
    assert r.json()["mission_time_hours"] == 500
    assert client.post("/api/predictions/compute", json={"lines": [], "environment": "GF"}).status_code == 422
    env = client.get("/api/predictions/environments").json()
    assert env["default_environment"] == "GF" and len(env["environments"]) == 14
    assert env["environments"][0] == {"code": "GB", "name": "Ground, benign",
                                      "covers": "Indoors with temperature and humidity controlled: labs, offices, computer rooms."}

    # Saved: results computed on the server, never taken from the body.
    r = client.post("/api/predictions", json={"name": " Box ", "inputs": {
        "lines": LINES, "environment": "GM", "mission_time": 200, "results": {"failure_rate_per_million_hours": 1}}})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["name"] == "Box" and doc["environment"] == "GM" and doc["read_only"] is False
    assert doc["results"]["failure_rate_per_million_hours"] == pytest.approx(0.0038 * 9 * 2 + 0.00099 * 20 * 10)
    assert doc["inputs"]["lines"][0]["assembly"] == ["Power"] and "results" not in doc["inputs"]
    assert doc["headline"].endswith(" h") and doc["lines"] == 2 and doc["assigned"] == 2
    pid = doc["id"]
    assert client.post("/api/predictions", json={"name": "", "inputs": {"lines": LINES}}).status_code == 422

    rows = client.get("/api/predictions").json()["predictions"]
    assert [x["name"] for x in rows] == ["Box", "Survey quadcopter electronics (sample)"]
    assert rows[1]["is_sample"] is True and rows[1]["read_only"] is True and rows[0]["is_sample"] is False
    got = client.get(f"/api/predictions/{pid}").json()
    assert got["results"]["lines"][0]["name"] == "D1" and got["inputs"]["mission_time"] == 200
    assert client.get("/api/predictions/nope").status_code == 404

    # Renamed, then the inputs replaced (results computed again).
    r = client.patch(f"/api/predictions/{pid}", json={"name": "Box A"})
    assert r.json()["name"] == "Box A" and r.json()["results"]["environment"]["code"] == "GM"
    r = client.patch(f"/api/predictions/{pid}", json={"inputs": {"lines": LINES[:1], "environment": "GF"}})
    assert r.json()["results"]["failure_rate_per_million_hours"] == pytest.approx(0.0456)
    assert r.json()["name"] == "Box A" and r.json()["lines"] == 1
    assert client.patch(f"/api/predictions/{pid}", json={"inputs": {"lines": [], "environment": "GF"}}).status_code == 422

    # A sample can't be renamed; deleting it hides it for this user only.
    sample = "sample-prediction-quadcopter"
    assert client.patch(f"/api/predictions/{sample}", json={"name": "Mine"}).status_code in (403, 404)
    assert client.delete(f"/api/predictions/{sample}").json() == {"ok": True}
    assert [x["id"] for x in client.get("/api/predictions").json()["predictions"]] == [pid]
    assert client.get(f"/api/predictions/{sample}").status_code == 404
    assert client.delete(f"/api/predictions/{pid}").json() == {"ok": True}
    assert client.get("/api/predictions").json()["predictions"] == []
    assert client.delete(f"/api/predictions/{pid}").status_code == 404


def test_the_sample_is_seeded_from_the_sample_products_electronics(client):
    from backend.services import samples

    doc = client.get("/api/predictions/sample-prediction-quadcopter").json()
    assert doc["is_sample"] and doc["product"]["name"] == "Survey quadcopter (sample)"
    r = doc["results"]
    assert r["environment"]["code"] == "ARW" and r["mission_time_hours"] == 100
    assert 300 < r["failure_rate_per_million_hours"] < 420 and 0.95 < r["reliability_at_mission"] < 0.975
    # Every line counts but the propellers (not electronic, in neither handbook): the microcircuits on
    # MIL-HDBK-217F's parts-count rates, the motors on NSWC-11's electric motor under their conditions.
    assert r["counts"]["unassigned"] == 0 and r["counts"]["excluded"] == 1 and r["warnings"] == []
    by_name = {line["name"]: line for line in r["lines"]}
    assert by_name["Propeller 10x4.5"]["excluded"]
    motors = by_name["Brushless motor 2210"]
    assert motors["handbook"] == "NSWC-11" and not motors["needs_conditions"] and motors["rate_per_million_hours"] > 0
    micro = [line for line in r["lines"] if (line["part_type"] or "").startswith("Microcircuit")]
    assert len(micro) == 10 and all(line["quality_factor"] == 10 for line in micro)
    labels = [a["label"] for a in r["assemblies"]]
    assert "Power › BMS board" in labels and labels.index("Power") < labels.index("Power › BMS board")
    assert [c["name"] for c in r["pareto"]["by_category"][:2]] == [
        "Electric motors", "Microcircuits (integrated circuits, memories, SAW devices)"]
    # The sample names the sample product as backend/maintenance/templates.py spells it.
    from backend.maintenance import templates

    product = samples.SAMPLE_PREDICTION["inputs"]["product"]
    assert product["name"] == templates.SAMPLE_PRODUCT_NAME and product["part_number"] == templates.SAMPLE_PRODUCT_PART
    assert product["rev"] == templates.SAMPLE_PRODUCT_REV
    from backend.db import get_db

    assert "sample-prediction-quadcopter" in samples.all_sample_ids(get_db())


def test_a_products_parts_list_over_the_app(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.maintenance import templates
    from backend.maintenance.service import PROJECTORS, Maintenance
    from backend.maintenance.store import GraphStore
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@example.com"})
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    store = GraphStore(":memory:", PROJECTORS)
    monkeypatch.setattr(router, "_store", store)
    test_db.users.insert_one({"_id": OWNER, "email": "a@example.com", "name": "A", "email_verified": True})
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.com", "name": "A",
                                                          "email_verified": True}
    try:
        tc = TestClient(app)
        added = templates.add_sample_product(Maintenance(store, OWNER, OWNER), test_db)
        r = tc.get(f"/api/predictions/from-product/{added['product']['id']}")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["product"]["name"] == "Survey quadcopter (sample)" and out["product"]["part_number"] == "SQ-4"
        by_ref = {ln["reference"]: ln for ln in out["lines"]}
        assert by_ref["SQ-M2210"]["quantity"] == 4 and by_ref["SQ-M2210"]["name"] == "Brushless motor 2210"
        assert len(out["lines"]) == 11 and out["assemblies"] == 0  # the sample's bill of materials is one level
        assert tc.get("/api/predictions/from-product/nope").status_code == 404
        # Not a product: refused in the service's words.
        plant = Maintenance(store, OWNER, OWNER).create_position("Plant")
        assert tc.get(f"/api/predictions/from-product/{plant['id']}").status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---- the MCP actions (and so REST and the CLI) -------------------------------------------------

@pytest.mark.usefixtures("mcp_on")
def test_the_actions_over_mcp(env):  # noqa: F811
    from backend.mcp_server import DATA_NOTICE
    from backend.services import samples
    from backend.tests.test_mcp import _call, _err, _ok

    samples.seed_samples(env.db)
    token = env.oauth[FREE]  # free: an exact calculation
    out = _ok(_call(token, "analyse", {"action": "prediction", "lines": LINES, "environment": "GF",
                                       "mission_time": 100}))
    assert out["data_notice"] == DATA_NOTICE
    assert out["failure_rate_per_million_hours"] == pytest.approx(0.0456 + 0.099)
    assert out["assemblies"][0]["label"] == "Power"
    assert "needs" in _err(_call(token, "analyse", {"action": "prediction", "environment": "GF"})) or \
        "Give lines" in _err(_call(token, "analyse", {"action": "prediction", "environment": "GF"}))
    assert "Unknown environment" in _err(_call(token, "analyse", {"action": "prediction", "lines": LINES,
                                                                   "environment": "ZZ"}))
    assert "products aren't available" in _err(_call(token, "analyse", {"action": "prediction",
                                                                         "product_id": "x"}))

    saved = _ok(_call(token, "change", {"action": "prediction_save", "name": "Box", "lines": LINES,
                                        "environment": "GM", "notes": "first pass"}))
    assert saved["saved"] and saved["url"].endswith(f"/predictions/{saved['prediction_id']}")
    assert saved["failure_rate_per_million_hours"] == pytest.approx(0.0038 * 9 * 2 + 0.00099 * 20 * 10)
    pid = saved["prediction_id"]
    listed = _ok(_call(token, "list", {"kind": "predictions"}))
    assert listed["data_notice"] == DATA_NOTICE
    assert {p["id"]: p["is_sample"] for p in listed["predictions"]} == {pid: False,
                                                                        "sample-prediction-quadcopter": True}
    got = _ok(_call(token, "get", {"kind": "prediction", "id": pid}))
    assert got["inputs"]["notes"] == "first pass" and got["results"]["environment"]["code"] == "GM"
    assert "not found" in _err(_call(token, "get", {"kind": "prediction", "id": "nope"})).lower()

    up = _ok(_call(token, "change", {"action": "prediction_update", "prediction_id": pid, "environment": "GF",
                                     "mission_time": 50}))
    assert up["updated"] == ["environment", "mission_time"] and up["mission_time_hours"] == 50
    assert up["failure_rate_per_million_hours"] == pytest.approx(0.0456 + 0.099)
    up = _ok(_call(token, "change", {"action": "prediction_update", "prediction_id": pid, "name": "Box B"}))
    assert up["updated"] == ["name"] and up["name"] == "Box B"
    assert "Nothing to change" in _err(_call(token, "change", {"action": "prediction_update", "prediction_id": pid}))
    assert "shared sample" in _err(_call(token, "change", {"action": "prediction_update",
                                                           "prediction_id": "sample-prediction-quadcopter",
                                                           "name": "Mine"}))
    assert "shared sample" in _err(_call(token, "change", {"action": "prediction_delete",
                                                           "prediction_id": "sample-prediction-quadcopter"}))
    gone = _ok(_call(token, "change", {"action": "prediction_delete", "prediction_id": pid}))
    assert gone == {"deleted": True, "prediction_id": pid, "name": "Box B"}
    assert [p["id"] for p in _ok(_call(token, "list", {"kind": "predictions"}))["predictions"]] == [
        "sample-prediction-quadcopter"]
    # The guide has the topic, and the action's full schema.
    guide = _ok(_call(token, "guide", {"topic": "prediction", "action": "analyse.prediction"}))
    assert "λb × πE × πQ" in guide["guide"] and guide["action"]["takes"].startswith("lines?")
    assert "record_id" in guide["action"]["arguments"]["$defs"]["PredictionLine"]["properties"]


# ---- parts-count part types, rates you give and lines left out --------------------------------

MPU = "mil-hdbk-217f-n2:a-5-1-microprocessors-mos-up-to-16-bits"  # λg GF .17, ARW .40; πQ default 10
MOTOR = "mil-hdbk-217f-n2:a-12-1-motors-general"  # λg ARW 13; no MF, ML, CL; no πQ


def _parts_count_records() -> list[dict]:
    from backend.library import service as library_service

    return [r for r in library_service._library()["records"]
            if (r.get("prediction") or {}).get("method") == "parts_count"]


def test_every_parts_count_record_resolves_for_its_environments():
    from backend.library import schema as library_schema

    recs = _parts_count_records()
    assert len(recs) == 74
    for rec in recs:
        values = rec["generic_rates"]["values"]
        for code in library_schema.ENVIRONMENTS:
            if code in values:
                factor = rp._environment_factor(rec, code, "line")
                assert rec["prediction"]["per_million_hours"] * factor == pytest.approx(values[code], rel=1e-12)
                assert rp._line_rate(rec, code, "line") == (values[code], None)
            else:
                with pytest.raises(rp.PredictionError, match="not normally used there"):
                    rp._environment_factor(rec, code, "line")
        out = rp.compute([{"name": "P", "record_id": rec["id"]}], next(iter(values)))
        assert out["failure_rate_per_million_hours"] > 0


def test_a_parts_count_line_uses_its_generic_rate_and_default_grade():
    out = rp.compute([{"name": "Flight controller MCU", "record_id": MPU}], "ARW", 100)
    [line] = out["lines"]
    assert line["generic_rate"] and line["base_rate_per_million_hours"] == 0.40 and line["environment_factor"] is None
    assert line["quality_factor"] == 10 and line["quality_factor_source"] == "default"
    assert line["quality_level"] == "Other commercial or unknown screening levels"
    assert line["rate_per_million_hours"] == pytest.approx(4.0) and line["applied"] == ["λg", "πQ"]
    assert line["not_applied"] == [] and {f["symbol"] for f in line["held_at_defaults"]} == {"πT", "C1, C2", "πL"}
    assert out["factors"]["held_at_defaults"] and "λg" in [a["symbol"] for a in out["factors"]["applied"]]
    assert out["method"] == rp.METHOD_GENERIC and out["warnings"] == []
    # A grade given wins, 1 too (class B).
    b = rp.compute([{"name": "MCU", "record_id": MPU, "quality_factor": 1}], "ARW")
    assert b["lines"][0]["rate_per_million_hours"] == pytest.approx(0.40) and b["lines"][0]["quality_factor_source"] == "given"
    # No πQ in the handbook for motors; an environment it has no rate for is refused, plainly.
    assert rp.compute([{"name": "M", "record_id": MOTOR, "quantity": 4}], "ARW")["failure_rate_per_million_hours"] == 52
    with pytest.raises(rp.PredictionError, match="no quality factor"):
        rp.compute([{"name": "M", "record_id": MOTOR, "quality_factor": 2}], "ARW")
    with pytest.raises(rp.PredictionError, match=r"no ML \(missile, launch\) rate for 'Motor, general'"):
        rp.compute([{"name": "M", "record_id": MOTOR}], "ML")


def test_a_rate_you_give_and_a_line_left_out():
    out = rp.compute([
        {"name": "Diode", "record_id": DIODE},
        {"name": "Battery pack", "rate_per_million_hours": 20},
        {"name": "Propeller", "quantity": 4, "excluded": True},
        {"name": "Airframe", "excluded": "true"},
    ], "GF")
    by = {ln["name"]: ln for ln in out["lines"]}
    bat = by["Battery pack"]
    assert bat["assigned"] and bat["user_given"] and bat["rate_per_million_hours"] == 20
    assert bat["part_type"] == "Rate you gave (user-given)" and bat["category"] == "Rates you gave"
    assert by["Propeller"]["excluded"] and not by["Propeller"]["assigned"]
    assert by["Propeller"]["line_warnings"] == [rp.EXCLUDED_NOTE]
    assert out["failure_rate_per_million_hours"] == pytest.approx(20 + 0.0228)
    assert out["counts"]["excluded"] == 2 and out["counts"]["unassigned"] == 0 and out["counts"]["assigned"] == 2
    assert [x["name"] for x in out["excluded"]] == ["Propeller", "Airframe"] and out["unassigned"] == []
    assert out["left_out_note"].startswith("Left out as not electronic parts (2 lines): Propeller (×4), Airframe.")
    assert any("rate you gave" in w for w in out["warnings"])
    assert not any("no handbook part type" in w for w in out["warnings"])
    for bad, says in [
        ({"name": "X", "record_id": DIODE, "rate_per_million_hours": 1}, "not both"),
        ({"name": "X", "rate_per_million_hours": 0}, "must be above 0"),
        ({"name": "X", "rate_per_million_hours": 1, "quality_factor": 2}, "has no quality factor"),
        ({"name": "X", "record_id": DIODE, "excluded": True}, "can't also have"),
    ]:
        with pytest.raises(rp.PredictionError, match=says):
            rp.compute([bad], "GF")


def test_a_quadcopter_parts_list_computes_end_to_end():
    """A quadcopter's bill of materials: its electronics typed from the handbook (microprocessor,
    memory, MOSFETs, motors, crystal, connectors, circuit board), its battery at a rate the user
    gives, its airframe and propellers left out."""
    lines = [
        {"name": "Flight controller MCU", "record_id": MPU, "assembly": "Flight controller"},
        {"name": "Flash memory", "record_id": "mil-hdbk-217f-n2:a-5-2-mos-memories-prom-uveprom-eeprom-eaprom-256k-to-1-mb",
         "assembly": "Flight controller"},
        {"name": "ESC MOSFET", "record_id": "mil-hdbk-217f-n2:6-4-mosfet", "quantity": 24, "assembly": "Speed controllers"},
        {"name": "Brushless motor", "record_id": MOTOR, "quantity": 4},
        {"name": "Crystal", "record_id": "mil-hdbk-217f-n2:a-19-1-quartz-crystals", "assembly": "Flight controller"},
        {"name": "Connector", "record_id": "mil-hdbk-217f-n2:15-1-rectangular", "quantity": 6},
        {"name": "Controller board", "record_id": "mil-hdbk-217f-n2:a-16-2-surface-mount-technology-circuit-boards",
         "assembly": "Flight controller"},
        {"name": "Battery pack", "rate_per_million_hours": 25},
        {"name": "Airframe", "excluded": True},
        {"name": "Propeller", "quantity": 4, "excluded": True},
    ]
    out = rp.compute(lines, "ARW", 2)
    by = {ln["name"]: ln for ln in out["lines"]}
    assert by["Flight controller MCU"]["rate_per_million_hours"] == pytest.approx(0.40 * 10)
    assert by["Brushless motor"]["rate_per_million_hours"] == pytest.approx(13 * 4)
    assert by["Crystal"]["rate_per_million_hours"] == pytest.approx(0.74 * 2.1)  # non-MIL, the default
    assert by["Controller board"]["rate_per_million_hours"] == pytest.approx(6.1)  # no πQ for SMT boards
    assert by["ESC MOSFET"]["environment_factor"] == 24 and not by["ESC MOSFET"]["generic_rate"]
    total = sum(ln["rate_per_million_hours"] for ln in out["lines"] if ln["assigned"])
    assert out["failure_rate_per_million_hours"] == pytest.approx(total) and total > 80
    assert out["counts"] == {"lines": 10, "assigned": 8, "unassigned": 0, "excluded": 2, "parts": 44,
                             "parts_assigned": 39}
    assert out["mtbf_hours"] == pytest.approx(1e6 / total)
    fc = next(a for a in out["assemblies"] if a["name"] == "Flight controller")
    assert fc["lines"] == 4 and fc["assigned"] == 4
    categories = {c["name"] for c in out["pareto"]["by_category"]}
    assert {"Microcircuits (integrated circuits, memories, SAW devices)", "Motors, synchros and resolvers",
            "Printed circuit boards", "Rates you gave"} <= categories
    assert out["left_out_note"].startswith("Left out as not electronic parts (2 lines): Airframe, Propeller (×4).")
