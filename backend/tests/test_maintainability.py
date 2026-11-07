"""Maintainability prediction (backend/services/maintainability.py): Mct, M_max,
availability, the Pareto and the roll-up from a parts list's repair times; the
app's routes, the MCP actions with their REST twins, the sample, and a product's
parts list as lines."""

import math

import mongomock
import pytest

from backend.tests.test_mcp import _err, _ok, _run
from backend.tests.test_mcp_plans import FREE, PRO, env  # noqa: F401

A = "user-a"
Z95 = 1.6448536269514722

pytestmark = pytest.mark.usefixtures("mcp_on")


def _line(name, rate=None, quantity=1, **kw):
    out = {"name": name, "quantity": quantity, **kw}
    if rate is not None:
        out["failure_rate"] = rate
    return out


# Two lines: λ 10 and 30 per million hours, MTTR 1 h and 3 h.
TWO = {"unit": "hours", "lines": [_line("A", 10, elements={"replace": 1}),
                                   _line("B", 30, elements={"isolation": 1, "replace": 2})]}


# ---- the numbers, by hand --------------------------------------------------------------

def test_mct_is_the_failure_rate_weighted_mean_of_the_lines_mttrs():
    from backend.services import maintainability as m

    r = m.compute(TWO)
    assert r["mct"] == pytest.approx((10 * 1 + 30 * 3) / 40)  # 2.5 h
    assert r["unit"] == "hours" and r["mct_hours"] == pytest.approx(2.5)
    assert r["weights"]["source"] == "typed" and "as typed" in r["weights"]["note"]
    # The Pareto: B is 90 % of the maintenance time (30·3 of 10·1 + 30·3).
    assert [(p["name"], p["share"], p["cumulative"]) for p in r["pareto"]] == [("B", pytest.approx(0.9), pytest.approx(0.9)),
                                                                                 ("A", pytest.approx(0.1), pytest.approx(1.0))]
    # Where the time goes: isolation 30·1/40 = 0.75 h of the 2.5.
    assert r["elements"]["isolation"]["time"] == pytest.approx(0.75)
    assert r["elements"]["replace"]["time"] == pytest.approx(1.75)
    assert r["elements"]["isolation"]["share"] == pytest.approx(0.3)
    assert "unsplit" not in r["elements"]
    assert r["counts"] == {"lines": 2, "with_rates": 2, "with_spread": 0}


def test_doubling_a_quantity_doubles_that_lines_weight():
    from backend.services import maintainability as m

    two_a = {**TWO, "lines": [dict(TWO["lines"][0], quantity=2), TWO["lines"][1]]}
    r = m.compute(two_a)
    assert r["mct"] == pytest.approx((10 * 2 * 1 + 30 * 3) / (20 + 30))  # 2.2 h
    assert r["system_failure_rate"] == pytest.approx(50)
    assert r["lines"][0]["weight"] == pytest.approx(20)


def test_inherent_availability_from_the_summed_rates_or_a_typed_mtbf():
    from backend.services import maintainability as m

    r = m.compute(TWO)
    # λ = 40 per million hours: MTBF 25,000 h; A = 25,000 / (25,000 + 2.5).
    assert r["mtbf_hours"] == pytest.approx(25_000) and r["mtbf_source"] == "rates"
    assert r["availability"] == pytest.approx(25_000 / 25_002.5)
    assert r["availability_note"] is None
    # In minutes the MTTRs are converted before the availability.
    minutes = m.compute({**TWO, "unit": "minutes"})
    assert minutes["mct"] == pytest.approx(2.5) and minutes["mct_hours"] == pytest.approx(2.5 / 60)
    assert minutes["availability"] == pytest.approx(25_000 / (25_000 + 2.5 / 60))
    # Rates per hour.
    per_hour = m.compute({**TWO, "failure_rate_unit": "per_hour"})
    assert per_hour["mtbf_hours"] == pytest.approx(1 / 40) and per_hour["mct"] == pytest.approx(2.5)
    # A typed MTBF wins.
    typed = m.compute({**TWO, "mtbf": 1000})
    assert typed["mtbf_source"] == "typed" and typed["availability"] == pytest.approx(1000 / 1002.5)


def test_without_rates_every_line_counts_the_same_and_the_result_says_so():
    from backend.services import maintainability as m

    r = m.compute({"unit": "hours", "lines": [_line("A", elements={"replace": 1}), _line("B", 30, mttr=3)]})
    assert r["mct"] == pytest.approx(2.0)
    assert r["weights"]["source"] == "equal" and r["weights"]["missing"] == ["A"]
    assert "1 line has no failure rate (A)" in r["weights"]["note"]
    assert r["availability"] is None and "needs the system's MTBF" in r["availability_note"]
    assert r["system_failure_rate"] is None
    # A typed MTBF still gives availability.
    assert m.compute({"unit": "hours", "mtbf": 100, "lines": [_line("A", mttr=1)]})["availability"] == pytest.approx(100 / 101)
    # A line with only an MTTR: its time isn't split.
    assert r["elements"]["unsplit"]["time"] == pytest.approx(1.5)


def test_m_max_of_one_lognormal_line_is_its_percentile():
    """One line, MTTR (mean) 2 h and sigma 0.5: the lognormal's mu is ln 2 − σ²/2 and
    its 95th percentile exp(mu + 1.645 σ)."""
    from backend.services import maintainability as m

    r = m.compute({"unit": "hours", "lines": [_line("A", mttr=2, sigma=0.5)]})
    want = math.exp(math.log(2) - 0.125 + Z95 * 0.5)
    assert r["m_max"] == pytest.approx(want, rel=1e-6) and want == pytest.approx(4.0172, abs=1e-4)
    assert r["lines"][0]["m_max"] == pytest.approx(want, rel=1e-9)
    assert r["m_max_note"] is None and r["percentile"] == 0.95
    # At 90 %: z = 1.2816.
    r90 = m.compute({"unit": "hours", "percentile": 0.9, "lines": [_line("A", mttr=2, sigma=0.5)]})
    assert r90["m_max"] == pytest.approx(math.exp(math.log(2) - 0.125 + 1.2815515655 * 0.5), rel=1e-6)


def test_a_maximum_gives_the_sigma_whose_percentile_it_is():
    from backend.services import maintainability as m

    r = m.compute({"unit": "hours", "lines": [_line("A", mttr=2, maximum=5)]})
    sigma = r["lines"][0]["sigma"]
    assert math.exp(math.log(2) - sigma ** 2 / 2 + Z95 * sigma) == pytest.approx(5)
    assert r["lines"][0]["m_max"] == pytest.approx(5) and r["m_max"] == pytest.approx(5, rel=1e-6)
    with pytest.raises(m.MaintainabilityError, match="more than the MTTR"):
        m.compute({"unit": "hours", "lines": [_line("A", mttr=2, maximum=2)]})
    with pytest.raises(m.MaintainabilityError, match="can't be more than about 3.9×"):
        m.compute({"unit": "hours", "lines": [_line("A", mttr=2, maximum=20)]})
    with pytest.raises(m.MaintainabilityError, match="not both"):
        m.compute({"unit": "hours", "lines": [_line("A", mttr=2, maximum=4, sigma=0.3)]})


def test_the_system_m_max_is_the_mixtures_percentile():
    """Two equal-weight lines, both lognormal: the mix's 95th percentile is where
    the mean of their CDFs reaches 0.95 — between the two lines' own M_max."""
    from backend.services import maintainability as m

    r = m.compute({"unit": "hours", "lines": [_line("A", 1, mttr=1, sigma=0.4), _line("B", 1, mttr=4, sigma=0.4)]})
    a, b = (ln["m_max"] for ln in r["lines"])
    assert a < r["m_max"] < b
    cdf = sum(0.5 * m._phi((math.log(r["m_max"]) - ln["mu"]) / ln["sigma"])
              for ln in m.check_inputs({"unit": "hours", "lines": [
                  _line("A", 1, mttr=1, sigma=0.4), _line("B", 1, mttr=4, sigma=0.4)]})["lines"])
    assert cdf == pytest.approx(0.95, abs=1e-6)


def test_m_max_needs_spreads_and_says_so():
    from backend.services import maintainability as m

    r = m.compute(TWO)
    assert r["m_max"] is None and "needs a spread" in r["m_max_note"]
    # Some lines without: they count as points, and the note says so.
    half = m.compute({"unit": "hours", "lines": [_line("A", 10, mttr=1), _line("B", 30, mttr=3, sigma=0.5)]})
    assert half["m_max"] is not None and "1 line has no spread" in half["m_max_note"]
    assert half["counts"]["with_spread"] == 1


def test_the_roll_up_over_a_two_level_product():
    from backend.services import maintainability as m

    r = m.compute({"unit": "minutes", "lines": [
        _line("Motor 1", 100, assembly="Propulsion › Arm 1", mttr=30),
        _line("Motor 2", 100, assembly="Propulsion / Arm 2", mttr=30),
        _line("ESC", 50, quantity=2, assembly="Propulsion", mttr=60),
        _line("IMU", 20, assembly="Flight control", mttr=120),
        _line("Loose", 10, mttr=10),
    ]})
    by_path = {a["path"]: a for a in r["assemblies"]}
    assert list(by_path) == ["Flight control", "Propulsion", "Propulsion › Arm 1", "Propulsion › Arm 2"]
    assert by_path["Propulsion"]["level"] == 1 and by_path["Propulsion › Arm 1"]["level"] == 2
    assert by_path["Propulsion"]["lines"] == 3 and by_path["Propulsion"]["failure_rate"] == pytest.approx(300)
    assert by_path["Propulsion"]["mct"] == pytest.approx((100 * 30 + 100 * 30 + 100 * 60) / 300)
    total = 100 * 30 * 2 + 100 * 60 + 20 * 120 + 10 * 10
    assert by_path["Propulsion"]["share"] == pytest.approx((6000 + 6000) / total)
    assert by_path["Propulsion › Arm 1"]["mct"] == pytest.approx(30)
    assert sum(a["share"] for a in r["assemblies"] if a["level"] == 1) == pytest.approx((total - 100) / total)
    assert r["lines"][0]["assembly"] == "Propulsion › Arm 1" and r["lines"][1]["assembly"] == "Propulsion › Arm 2"


def test_refused_inputs_say_what_to_fix():
    from backend.services import maintainability as m

    bad = [
        ({"lines": []}, "at least one line"),
        ({"lines": [{"quantity": 1, "mttr": 1}]}, "needs a name"),
        ({"lines": [_line("A")]}, "MTTR \\(or its repair elements\\)"),
        ({"lines": [_line("A", mttr=0)]}, "more than 0 hours"),
        ({"lines": [_line("A", mttr=1, elements={"nope": 1})]}, "unknown repair element"),
        ({"lines": [_line("A", mttr=5, elements={"replace": 1})]}, "isn't the sum of its elements"),
        ({"lines": [_line("A", mttr=1)], "unit": "days"}, "minutes or hours"),
        ({"lines": [_line("A", mttr=1)], "failure_rate_unit": "per_year"}, "per_million_hours or per_hour"),
        ({"lines": [_line("A", mttr=1)], "percentile": 0.3}, "percentile can't be less than 0.5"),
        ({"lines": [_line("A", 0, mttr=1)]}, "nothing fails"),
        ({"lines": [_line("A", mttr=1, quantity=0)]}, "quantity 0"),
        ({"lines": [_line("A", mttr=1, sigma=5)]}, "sigma can't be more than 3"),
    ]
    for inputs, why in bad:
        with pytest.raises(m.MaintainabilityError, match=why):
            m.compute(inputs)
    assert m.fmt_num(29.912) == "29.9" and m.fmt_num(1234.5) == "1,234" and m.fmt_num(0.00012) == "0.00012"


# ---- failure rates from a saved reliability prediction ---------------------------------

def _reliability_prediction(db, owner, product_id="prod-1", unit="per_million_hours"):
    db.reliability_predictions.insert_one({
        "_id": "rp-1", "name": "Quadcopter rates", "owner_id": owner, "updated_at": "2026-11-01",
        "inputs": {"product_id": product_id, "failure_rate_unit": unit},
        "results": {"lines": [{"ref": "SQ-M2210", "name": "Brushless motor", "failure_rate": 180},
                              {"ref": "SQ-ESC30", "name": "Speed controller", "failure_rate": 120},
                              {"ref": "SQ-X", "name": "No rate here"}]},
    })


def test_rates_come_from_a_saved_reliability_prediction_for_the_product():
    from backend.services import maintainability as m

    db = mongomock.MongoClient()["maint_rates"]
    assert m.prediction_rates(db, "prod-1", [A]) is None  # the collection isn't there yet
    _reliability_prediction(db, A)
    found = m.prediction_rates(db, "prod-1", [A])
    assert found["id"] == "rp-1" and found["rates"]["sq-m2210"] == 180 and found["rates"]["speed controller"] == 120
    assert "sq-x" not in found["rates"] and found["unit"] == "per_million_hours"
    assert m.prediction_rates(db, "prod-2", [A]) is None and m.prediction_rates(db, "prod-1", ["other"]) is None
    inputs = {"unit": "minutes", "product_id": "prod-1", "lines": [
        _line("Brushless motor", ref="SQ-M2210", quantity=4, mttr=45),
        _line("Speed controller", quantity=4, mttr=60),  # by name
        _line("Propeller", 600, quantity=4, mttr=10),  # typed
    ]}
    r = m.compute(inputs, found)
    assert [ln["rate_source"] for ln in r["lines"]] == ["reliability_prediction", "reliability_prediction", "typed"]
    assert [ln["failure_rate"] for ln in r["lines"]] == [180, 120, 600]
    assert r["weights"]["source"] == "mixed" and r["weights"]["prediction"] == {"id": "rp-1", "name": "Quadcopter rates"}
    assert "Quadcopter rates" in r["weights"]["note"]
    # The prediction's unit is converted to the inputs'.
    r2 = m.compute({**inputs, "failure_rate_unit": "per_hour"}, found)
    assert r2["lines"][0]["failure_rate"] == pytest.approx(180e-6)
    # A line it doesn't know keeps the lines equal, and the note names it.
    r3 = m.compute({**inputs, "lines": inputs["lines"] + [_line("Unknown", mttr=5)]}, found)
    assert r3["weights"]["source"] == "equal" and r3["weights"]["missing"] == ["Unknown"]


# ---- the app's routes --------------------------------------------------------------------

@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.maintenance.service import PROJECTORS
    from backend.maintenance.store import GraphStore
    from backend.routers import maintenance as router
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@example.org"})
    test_db = mongomock.MongoClient()["maintainability_api"]
    samples.seed_samples(test_db)
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    user = {"uid": A, "email": "a@example.org", "name": "A", "email_verified": True}
    test_db.users.insert_one({"_id": A, **{k: v for k, v in user.items() if k != "uid"}})
    app.dependency_overrides[get_current_user] = lambda: user
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_the_sample_is_seeded_and_listed_as_a_sample(api):
    from backend.services import samples

    rows = api.get("/api/maintainability/predictions").json()["predictions"]
    [sample] = rows
    assert sample["id"] == "sample-maintainability-quadcopter" and sample["is_sample"] and sample["read_only"]
    assert sample["headline"].startswith("Mct ") and "M_max" in sample["headline"] and "A 99" in sample["headline"]
    assert sample["lines"] == 11
    full = api.get(f"/api/maintainability/predictions/{sample['id']}").json()
    assert full["results"]["unit"] == "minutes" and full["results"]["m_max"] > full["results"]["mct"]
    assert {a["path"] for a in full["results"]["assemblies"]} == {
        "Airframe", "Propulsion", "Flight control", "Power", "Comms", "Payload gimbal"}
    assert full["results"]["pareto"][0]["ref"] == "SQ-M2210"  # four motors, often, 45 min each
    assert sample["id"] in samples.all_sample_ids(api.db)
    # "Deleting" a sample hides it for this user only.
    assert api.delete(f"/api/maintainability/predictions/{sample['id']}").json() == {"ok": True}
    assert api.get("/api/maintainability/predictions").json()["predictions"] == []
    assert api.get(f"/api/maintainability/predictions/{sample['id']}").status_code == 404
    assert api.db.maintainability_predictions.count_documents({}) == 1


def test_analyse_save_rename_update_and_delete_over_the_routes(api):
    r = api.post("/api/maintainability/analyse", json=TWO)
    assert r.status_code == 200 and r.json()["mct"] == pytest.approx(2.5)
    r = api.post("/api/maintainability/analyse", json={"lines": []})
    assert r.status_code == 422 and "at least one line" in r.json()["detail"]
    r = api.post("/api/maintainability/predictions", json={"name": "  Two lines ", "inputs": TWO})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["name"] == "Two lines" and saved["results"]["mct"] == pytest.approx(2.5) and not saved["read_only"]
    pid = saved["id"]
    assert api.post("/api/maintainability/predictions", json={"name": "", "inputs": TWO}).status_code == 422
    rows = api.get("/api/maintainability/predictions").json()["predictions"]
    assert [x["name"] for x in rows] == ["Two lines", "Survey quadcopter — maintainability prediction (sample)"]
    assert api.patch(f"/api/maintainability/predictions/{pid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    # New inputs: the results are recomputed on the server.
    r = api.patch(f"/api/maintainability/predictions/{pid}", json={"inputs": {**TWO, "mtbf": 1000}})
    assert r.status_code == 200 and r.json()["results"]["availability"] == pytest.approx(1000 / 1002.5)
    assert r.json()["name"] == "Renamed"
    r = api.patch(f"/api/maintainability/predictions/{pid}", json={"inputs": {"lines": []}})
    assert r.status_code == 422
    assert api.patch("/api/maintainability/predictions/nope", json={"name": "x"}).status_code == 404
    assert api.delete(f"/api/maintainability/predictions/{pid}").json() == {"ok": True}
    assert api.get(f"/api/maintainability/predictions/{pid}").status_code == 404
    # The sample can't be renamed by anyone but its owner.
    assert api.patch("/api/maintainability/predictions/sample-maintainability-quadcopter",
                     json={"name": "Mine"}).status_code in (403, 404)


def test_a_products_parts_list_as_lines(api):
    from backend.maintenance import templates
    from backend.routers import maintenance as router
    from backend.maintenance.service import Maintenance

    made = api.post("/api/maintenance/sample-product").json()
    pid = made["product"]["id"]
    r = api.get(f"/api/maintainability/products/{pid}/lines")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["product"]["name"] == templates.SAMPLE_PRODUCT_NAME and out["part"]["part_number"] == "SQ-4"
    lines = {ln["ref"]: ln for ln in out["lines"]}
    assert len(lines) == 11 and lines["SQ-M2210"]["quantity"] == 4 and lines["SQ-IMU9"]["quantity"] == 2
    assert lines["SQ-M2210"]["name"] == "Brushless motor 2210" and lines["SQ-M2210"]["assembly"] == ""
    assert out["rates"] == {"source": None} and out["note"] is None
    # With a reliability prediction saved for the product, its rates come along.
    _reliability_prediction(api.db, A, product_id=pid)
    out = api.get(f"/api/maintainability/products/{pid}/lines").json()
    assert out["rates"]["source"] == "reliability_prediction" and out["rates"]["matched"] == 2
    assert lines["SQ-M2210"].get("failure_rate") is None and {ln["ref"]: ln.get("failure_rate") for ln in out["lines"]}["SQ-M2210"] == 180
    assert api.get("/api/maintainability/products/nope/lines").status_code == 404
    # A product with no part: no lines, and why.
    m = Maintenance(router.get_store(), A, A)
    bare = m.create_product("Bare design")
    out = api.get(f"/api/maintainability/products/{bare['id']}/lines").json()
    assert out["lines"] == [] and "no part yet" in out["note"]
    # A nested structure: an assembly's parts carry its name as their assembly.
    top = m.create_part("TOP-1", "Top")
    asm = m.create_part("ASM-1", "Drive assembly")
    leaf = m.create_part("LEAF-1", "Bearing")
    m.add_component(top["id"], asm["id"], quantity=2)
    m.add_component(asm["id"], leaf["id"], quantity=3)
    nested = m.create_product("Nested", part_id=top["id"])
    out = api.get(f"/api/maintainability/products/{nested['id']}/lines").json()
    assert out["lines"] == [{"ref": "LEAF-1", "name": "Bearing", "assembly": "Drive assembly", "quantity": 6,
                             "level": ""}]


def test_products_lines_need_maintenance(api, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", False)
    assert api.get("/api/maintainability/products/x/lines").status_code == 404


# ---- MCP and its REST twin ---------------------------------------------------------------

def _mcp(token, tool, args):
    return _run(token, lambda c: c.call_tool(tool, args))


def test_the_mcp_actions_analyse_save_read_update_and_delete(env):  # noqa: F811
    from backend.services import samples

    samples.seed_samples(env.db)
    token = env.oauth[FREE]  # free on every plan
    lines = [{"name": "A", "failure_rate": 10, "elements": {"replace": 1}},
             {"name": "B", "failure_rate": 30, "elements": {"isolation": 1, "replace": 2}, "sigma": 0.5}]
    out = _ok(_mcp(token, "analyse", {"action": "maintainability", "lines": lines}))
    assert out["saved"] is False and out["mct"] == pytest.approx(2.5) and out["availability"] == pytest.approx(25_000 / 25_002.5)
    assert "1 line has no spread" in out["m_max_note"]
    msg = _err(_mcp(token, "analyse", {"action": "maintainability", "lines": [{"name": "A"}]}))
    assert "MTTR (or its repair elements)" in msg
    msg = _err(_mcp(token, "analyse", {"action": "maintainability", "lines": lines, "unit": "days"}))
    assert "unit" in msg
    saved = _ok(_mcp(token, "change", {"action": "maintainability_save", "name": "Two lines", "lines": lines,
                                       "unit": "minutes"}))
    assert saved["saved"] and saved["url"].endswith(f"/maintainability/{saved['prediction_id']}")
    assert saved["results"]["unit"] == "minutes" and saved["mct"] == pytest.approx(2.5)
    pid = saved["prediction_id"]
    listed = _ok(_mcp(token, "list", {"kind": "maintainability_predictions"}))
    assert "data_notice" in listed
    assert {p["name"] for p in listed["predictions"]} == {"Two lines", "Survey quadcopter — maintainability prediction (sample)"}
    got = _ok(_mcp(token, "get", {"kind": "maintainability_prediction", "id": pid}))
    assert got["inputs"]["lines"][1]["sigma"] == 0.5 and got["results"]["mct"] == pytest.approx(2.5)
    assert "data_notice" in got
    assert "Prediction not found" in _err(_mcp(token, "get", {"kind": "maintainability_prediction", "id": "nope"}))
    renamed = _ok(_mcp(token, "change", {"action": "maintainability_update", "prediction_id": pid, "name": "New"}))
    assert renamed["name"] == "New" and renamed["results"]["mct"] == pytest.approx(2.5)
    again = _ok(_mcp(token, "change", {"action": "maintainability_update", "prediction_id": pid,
                                       "lines": lines[:1], "unit": "hours"}))
    assert again["results"]["mct"] == pytest.approx(1.0) and again["results"]["counts"]["lines"] == 1
    assert "Nothing to change" in _err(_mcp(token, "change", {"action": "maintainability_update", "prediction_id": pid}))
    # The sample: read by everyone, changed or deleted by no one.
    sample = "sample-maintainability-quadcopter"
    assert _ok(_mcp(token, "get", {"kind": "maintainability_prediction", "id": sample}))["is_sample"]
    assert "shared sample" in _err(_mcp(token, "change", {"action": "maintainability_update", "prediction_id": sample,
                                                           "name": "x"}))
    assert "shared sample" in _err(_mcp(token, "change", {"action": "maintainability_delete", "prediction_id": sample}))
    assert _ok(_mcp(token, "change", {"action": "maintainability_delete", "prediction_id": pid}))["deleted"]
    assert "Prediction not found" in _err(_mcp(token, "change", {"action": "maintainability_delete", "prediction_id": pid}))
    # Another user can't see it.
    other = _ok(_mcp(env.oauth[PRO], "list", {"kind": "maintainability_predictions"}))
    assert {p["name"] for p in other["predictions"]} == {"Survey quadcopter — maintainability prediction (sample)"}


def test_the_guide_and_the_schema_cover_it(env):  # noqa: F811
    from backend import mcp_guide, mcp_server

    token = env.oauth[FREE]
    page = _ok(_mcp(token, "guide", {"topic": "maintainability"}))
    assert "Σ(λ·q·MTTR)/Σ(λ·q)" in page["guide"] and "maintainability_save" in page["guide"]
    schema = _ok(_mcp(token, "guide", {"action": "analyse.maintainability"}))["action"]
    assert schema["arguments"]["required"] == ["lines"]
    assert "MaintainabilityLine" in schema["arguments"]["$defs"] and "RepairElements" in schema["arguments"]["$defs"]
    assert schema["takes"].startswith("lines, unit?=hours, failure_rate_unit?=per_million_hours, percentile?=0.95")
    assert "maintainability" in mcp_guide.TOPICS
    for key in ("analyse.maintainability", "change.maintainability_save", "change.maintainability_update",
                "change.maintainability_delete", "get.maintainability_prediction", "list.maintainability_predictions"):
        assert key not in mcp_server.PRO_ONLY_TOOLS and key not in mcp_server.HEAVY_TOOLS
    assert {"get.maintainability_prediction", "list.maintainability_predictions"} <= mcp_server.TEXT_RESULT_TOOLS


def test_rest_is_the_mcp_result(env):  # noqa: F811
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import tokens

    token = tokens.create_token(env.db, PRO, "api")["token"]
    lines = [{"name": "A", "failure_rate": 10, "elements": {"replace": 1}, "sigma": 0.4},
             {"name": "B", "failure_rate": 30, "mttr": 3, "sigma": 0.6}]
    via_mcp = _ok(_mcp(env.oauth[PRO], "analyse", {"action": "maintainability", "lines": lines}))
    client = TestClient(app)
    r = client.post("/api/v1/analyse/maintainability", json={"lines": lines},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json() == via_mcp
    r = client.post("/api/v1/change/maintainability_save", json={"name": "Over REST", "lines": lines},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["saved"] and r.json()["name"] == "Over REST"
    r = client.post("/api/v1/list/maintainability_predictions", json={},
                    headers={"Authorization": f"Bearer {token}"})
    assert "Over REST" in {p["name"] for p in r.json()["predictions"]}
