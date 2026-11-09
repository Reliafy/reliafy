"""Life models on positions (the Explorer's Modelling tab, position_models.py): a link
names a saved model (never a copy), attaching and taking off are events that replay to
the same graph, a position's own history (or its class's) is fitted and attached, a built
item inherits its design's links, the reads describe each model and what uses it, and the
interval calculators start from them."""

from datetime import date, timedelta

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore

ORG = "org-models"
SAMPLE = "sample-model-bearings-weibull"
OWNERS = [ORG, "__samples__"]


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["position_models"]
    samples.seed_samples(d)
    return d


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _history(m, pid, lives, mode_ids=None, start=date(2018, 1, 1)):
    """Items fitted one after another at a position, each failing after its life (by the
    mode given for it, if any)."""
    on = start
    for i, life in enumerate(lives):
        m.fit(pid, new_item={"name": f"Unit {pid[-4:]}-{i}"}, on=on.isoformat())
        on = on + timedelta(days=life)
        mode = (mode_ids or [None] * len(lives))[i]
        m.remove(pid, on=on.isoformat(), reason="failure", failure_mode_id=mode)


def test_link_and_unlink_are_events_that_replay(m, db):
    pump = m.create_position("Pump A")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, [seal], note="Same bearings as the OEM's")
    assert link["role"] == "assigned" and link["model_id"] == SAMPLE and link["name"].startswith("Bearing life")
    assert link["failure_modes"] == [{"id": seal, "text": "Seal leaks", "gone": False}]
    assert [x["id"] for x in m.position(pump)["models"]] == [link["id"]]
    # Linked, never copied: the model store holds the one sample.
    assert db.models.count_documents({"_id": SAMPLE}) == 1
    _same_after_rebuild(m)
    with pytest.raises(Invalid, match="already on Pump A"):
        pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, [seal])
    with pytest.raises(NotFound):
        pm.link_saved(m, db, OWNERS, set(), pump, "model", "no-such-model")
    other = m.create_position("Pump B")["id"]
    elsewhere = m.add_failure_mode(other, "Impeller wear")["id"]
    with pytest.raises(Invalid, match="failure modes of this position"):
        m.link_position_model(pump, "model", SAMPLE, failure_mode_ids=[elsewhere])
    out = m.unlink_position_model(link["id"])
    assert out["unlinked"] == link["id"] and m.position(pump)["models"] == []
    with pytest.raises(Invalid, match="already taken off"):
        m.unlink_position_model(link["id"])
    types = [e["type"] for e in m.s.events(ORG, 100)]
    assert "position.model_linked" in types and "position.model_unlinked" in types
    _same_after_rebuild(m)


def test_replace_swaps_one_model_for_another(m, db):
    pump = m.create_position("Pump A")["id"]
    first = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE)
    second = pm.link_saved(m, db, OWNERS, set(), pump, "model", "sample-model-bearings-lognormal",
                           replace_link_id=first["id"])
    assert [x["id"] for x in m.position_models(pump)] == [second["id"]]
    with pytest.raises(Invalid, match="isn't on this position"):
        pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, replace_link_id="nope")
    _same_after_rebuild(m)


def test_fit_from_the_position_history_then_the_class(m, db):
    pump = m.create_position("Pump A", position_class="Slurry pump")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    bearing = m.add_failure_mode(pump, "Bearing seizes")["id"]
    _history(m, pump, [300, 420, 380, 510], [seal, bearing, seal, seal])
    link = pm.fit_position_model(m, db, pump)
    assert link["role"] == "fitted" and link["source"]["scope"] == "position"
    assert link["source"]["failures"] == 4 and db.models.count_documents({"_id": link["model_id"]}) == 1
    # For one failure mode: the bearing failure censors the row.
    sealed = pm.fit_position_model(m, db, pump, failure_mode_ids=[seal])
    assert sealed["source"]["failures"] == 3 and sealed["failure_modes"][0]["text"] == "Seal leaks"
    # Thin history: the class pools its positions' failures (auto falls back).
    for i in range(3):
        other = m.create_position(f"Pump {i}", position_class="Slurry pump")["id"]
        _history(m, other, [350 + 40 * i, 460])
    thin = m.create_position("Pump new", position_class="Slurry pump")["id"]
    pooled = pm.fit_position_model(m, db, thin)
    assert pooled["source"]["scope"] == "class" and pooled["source"]["class_name"] == "Slurry pump"
    assert pm.source_text(pooled).startswith("Fitted from the class Slurry pump's pooled history")
    assert pm.stale(m, link) is None
    _history(m, pump, [200], start=date(2021, 1, 1))
    assert pm.stale(m, link) == "1 failure since it was fitted: refit it"
    lonely = m.create_position("Odd pump")["id"]
    with pytest.raises(Invalid, match="has 0 failures"):
        pm.fit_position_model(m, db, lonely)
    _same_after_rebuild(m)


def test_from_class_needs_a_class_model(m, db):
    from backend.maintenance import loop

    pump = m.create_position("Pump A", position_class="Duty pump")["id"]
    with pytest.raises(Invalid, match="no fitted model yet"):
        pm.link_from_class(m, db, OWNERS, set(), pump)
    _history(m, pump, [300, 420, 380])
    loop.fit_class_model(m, db, "Duty pump")
    link = pm.link_from_class(m, db, OWNERS, set(), pump)
    assert link["role"] == "class" and link["source"] == {"class_name": "Duty pump"}
    assert pm.source_text(link) == "From the class Duty pump"


def test_a_built_item_inherits_its_designs_models(m, db):
    product = m.create_product("Drone", part_number="DR-1")["id"]
    motor = m.create_position("Motor", parent_id=product)["id"]
    wear = m.add_failure_mode(motor, "Bearing wear")["id"]
    pm.link_saved(m, db, OWNERS, set(), motor, "model", SAMPLE, [wear])
    built = m.build_item(product, "SN-1", dry_run=False)
    copy = next(r["id"] for r in built["positions"] if r["design_position_id"] == motor)
    [inherited] = m.position_models(copy)
    assert inherited["role"] == "design" and inherited["model_id"] == SAMPLE
    assert inherited["source"]["design_position_id"] == motor
    assert [f["text"] for f in inherited["failure_modes"]] == ["Bearing wear"]
    assert inherited["failure_modes"][0]["id"] != wear  # the built position's own mode
    assert pm.source_text(inherited) == "From the product's design"
    _same_after_rebuild(m)


def test_the_reads_describe_each_model_and_what_uses_it(m, db):
    pump = m.create_position("Pump A")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", SAMPLE, [seal])
    rec = pm.link_saved(m, db, OWNERS, set(), pump, "recurrent_model", "sample-rec-compressors")
    deg = pm.link_saved(m, db, OWNERS, set(), pump, "degradation_model", "sample-deg-brake-wear")
    m.decide_failure_mode(seal, consequence="operational",
                          decision={"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": SAMPLE}})
    rows = {r["id"]: r for r in pm.describe(m, db, OWNERS, set(), m.all_position_models())}
    weibull = rows[link["id"]]["model"]
    assert weibull["kind"] == "Weibull" and weibull["unit"]
    nums = {n["id"]: n for n in weibull["numbers"]}
    assert nums["char_life"]["lower"] < nums["char_life"]["value"] < nums["char_life"]["upper"]
    assert {"shape", "mean", "b10"} <= set(nums)
    assert weibull["quality"]["word"] == "Good" and weibull["counts"]["failures"] == 30
    assert [d["failure_mode_id"] for d in rows[link["id"]]["used_by"]["decisions"]] == [seal]
    repairable = rows[rec["id"]]["model"]
    assert repairable["kind"].startswith("Repairable") and repairable["trend"] == "Getting worse"
    assert rows[deg["id"]]["model"]["kind"] == "Degradation"
    full = pm.detail(m, db, OWNERS, set(), link["id"])
    assert full["curves"]["x"] and full["curves"]["sf"] and full["params"][0]["name"] == "alpha"
    assert full["origin"].startswith("Age since new") and full["position"]["name"] == "Pump A"
    # A model the reader can't open any more reads as missing, not an error.
    db.models.delete_one({"_id": SAMPLE})
    gone = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert next(r for r in gone if r["id"] == link["id"])["model"] is None


def test_the_interval_inputs_start_from_the_positions_model(m, db):
    from backend.services import rcm_intervals

    pump = m.create_position("Pump A")["id"]
    seal = m.add_failure_mode(pump, "Seal leaks")["id"]
    doc = pm.fetcher(db, OWNERS)("model", SAMPLE)
    got = rcm_intervals.starting_inputs(m.rcm_mode(seal), [], lambda *a: None, [("model", doc)])
    assert got["life_model"]["model_id"] == SAMPLE and got["life_model"]["source"] == "position"
    assert got["device"]["model_id"] == SAMPLE and got["onset_rate"]["source"] == "position_model"
    deg = pm.fetcher(db, OWNERS)("degradation_model", "sample-deg-brake-wear")
    got = rcm_intervals.starting_inputs(m.rcm_mode(seal), [], lambda *a: None, [("degradation_model", deg)])
    assert got["pf"]["source"] == "position_model"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router
    from backend.services import samples

    d = mongomock.MongoClient()["position_models_rest"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_link_read_and_unlink_over_rest(client):
    pump = client.post("/api/maintenance/positions", json={"name": "Pump"}).json()["id"]
    r = client.post(f"/api/maintenance/positions/{pump}/models", json={"model_id": SAMPLE})
    assert r.status_code == 200, r.text
    link = r.json()
    listed = client.get("/api/maintenance/position-models", params={"position_ids": pump}).json()["links"]
    assert [x["id"] for x in listed] == [link["id"]] and listed[0]["model"]["kind"] == "Weibull"
    full = client.get(f"/api/maintenance/position-models/{link['id']}").json()
    assert full["curves"]["sf"] and full["source_text"].startswith("Assigned")
    bad = client.post(f"/api/maintenance/positions/{pump}/models", json={"fit": True})
    assert bad.status_code == 422 and "failure" in bad.json()["detail"]
    nope = client.post(f"/api/maintenance/positions/{pump}/models", json={"from_class": True})
    assert nope.status_code == 422 and "no position class" in nope.json()["detail"]
    assert client.delete(f"/api/maintenance/position-models/{link['id']}").status_code == 200
    assert client.get("/api/maintenance/position-models").json()["links"] == []


CAP = "mil-hdbk-217f-n2:10-1-cp-25"
OPTO = "mil-hdbk-217f-n2:6-11-opto-isolator-light-sensitive-resistor-single-device"


def _board(m):
    """A controller with two parts on its own list and one inside it (a consumable left out)."""
    ctl = m.create_position("Controller")["id"]
    psu = m.create_position("Power supply", parent_id=ctl)["id"]
    cap = m.create_part("C-100", "Bypass capacitor")["id"]
    opto = m.create_part("U-7", "Opto-isolator")["id"]
    grease = m.create_part("G-1", "Grease")["id"]
    m.add_position_part(ctl, cap, role="component", quantity=4)
    m.add_position_part(ctl, grease, role="consumable", quantity=1)
    m.add_position_part(psu, opto, role="replacement", quantity=1)
    return ctl, psu


def test_a_prediction_row_from_the_parts_list(m, db):
    from backend.services import reliability_prediction as rp

    ctl, psu = _board(m)
    preview = pm.predict_position(m, db, OWNERS, set(), ctl)
    assert [ln["reference"] for ln in preview["lines"]] == ["C-100", "U-7"]  # the consumable isn't in it
    assert preview["lines"][1]["assembly"] == ["Power supply"] and preview["environment"] == "GF"
    with pytest.raises(Invalid, match="handbook part type"):
        pm.predict_position(m, db, OWNERS, set(), ctl, save=True)
    assign = {"C-100": {"record_id": CAP}, "U-7": {"record_id": OPTO}}
    link = pm.predict_position(m, db, OWNERS, set(), ctl, environment="GM", assign=assign, save=True)
    assert link["role"] == "prediction" and link["source"]["environment"] == "GM"
    rate = link["prediction"]["results"]["failure_rate_per_hour"]
    model = db.models.find_one({"_id": link["model_id"]})
    assert model["distribution_id"] == "exponential" and model["results"]["method"] == "parts_count"
    assert model["results"]["params"][0]["value"] == pytest.approx(rate)
    saved = rp.get_prediction(db, link["source"]["prediction_id"], OWNERS)
    assert saved.inputs["position"] == {"id": ctl, "name": "Controller"}
    # The rate is the parts count's: the lines' rates add (λ = Σ λb πE πQ n).
    lines = saved.results["lines"]
    assert sum(ln["rate_per_hour"] for ln in lines) == pytest.approx(rate)
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(ctl))
    assert row["model"]["kind"] == "Prediction (parts count)" and row["model"]["quality"]["word"] == "Predicted"
    assert row["source_text"].startswith("Predicted from its parts list (parts count")
    full = pm.detail(m, db, OWNERS, set(), link["id"])
    assert full["prediction"]["results"]["counts"]["assigned"] == 2
    # Again: it replaces the last prediction, keeping its part types; the environment carries down.
    again = pm.predict_position(m, db, OWNERS, set(), ctl, save=True)
    assert [x["id"] for x in m.position_models(ctl)] == [again["id"]] and again["source"]["environment"] == "GM"
    assert pm.default_environment(m, psu) == "GM"
    _same_after_rebuild(m)


def test_a_prediction_line_on_an_nswc_model_keeps_its_conditions(m, db):
    """A mechanical part takes an NSWC-11 covariate model with its conditions: counted under them,
    saved with the prediction, and a refresh (no assign given) keeps them."""
    from backend.services import reliability_prediction as rp

    ctl, psu = _board(m)
    bearing = "nswc-11:bearing-rolling-load-rating"
    cond = {"L_S": 5000, "F_R": 1000, "n": 1800}
    # Without its conditions the line is listed and left out, so the preview still works.
    first = pm.predict_position(m, db, OWNERS, set(), ctl, assign={"C-100": {"record_id": CAP}, "U-7": {"record_id": bearing}})
    assert first["results"]["counts"]["needs_conditions"] == 1
    assert first["results"]["needs_conditions"][0]["reference"] == "U-7"
    assign = {"C-100": {"record_id": CAP}, "U-7": {"record_id": bearing, "conditions": cond}}
    link = pm.predict_position(m, db, OWNERS, set(), ctl, assign=assign, save=True)
    res = link["prediction"]["results"]
    line = next(ln for ln in res["lines"] if ln["reference"] == "U-7")
    assert line["handbook"] == "NSWC-11" and line["rate_per_million_hours"] > 0 and line["quality_factor"] is None
    assert [h["short_name"] for h in res["handbooks"]] == ["MIL-HDBK-217F N2", "NSWC-11"]
    assert "NSWC-11 lines (Opto-isolator)" in res["method"] and "did not take part" in res["disclaimer"]
    model = db.models.find_one({"_id": link["model_id"]})
    assert "NSWC-11" in model["spec"]["notes"] and "did not take part" in model["spec"]["notes"]
    saved = rp.get_prediction(db, link["source"]["prediction_id"], OWNERS)
    kept = next(ln for ln in saved.inputs["lines"] if ln["reference"] == "U-7")
    assert kept["conditions"] == {k: float(v) for k, v in cond.items()}
    again = pm.predict_position(m, db, OWNERS, set(), ctl)
    assert again["results"]["failure_rate_per_hour"] == pytest.approx(res["failure_rate_per_hour"])
    _same_after_rebuild(m)


def test_lines_left_out_of_a_prediction_stay_on_the_list_and_are_kept(m, db):
    """"Leave out of this prediction": the line stays on the parts list but isn't counted; the saved
    prediction keeps it (with its part type), so refreshing it leaves it out again."""
    from backend.services import reliability_prediction as rp

    ctl, psu = _board(m)
    first = pm.predict_position(m, db, OWNERS, set(), ctl)
    cap_line, opto_line = first["lines"]
    assert cap_line["listing_id"] and cap_line["position"] == {"id": ctl, "name": "Controller"}
    assert opto_line["position"] == {"id": psu, "name": "Power supply"} and not cap_line["left_out"]
    assert first["branch"] == [{"id": ctl, "name": "Controller", "depth": 0}, {"id": psu, "name": "Power supply", "depth": 1}]
    assign = {"C-100": {"record_id": CAP}, "U-7": {"record_id": OPTO}}
    both = pm.predict_position(m, db, OWNERS, set(), ctl, assign=assign)
    out = pm.predict_position(m, db, OWNERS, set(), ctl, assign=assign, left_out=[opto_line["listing_id"]])
    assert [ln["left_out"] for ln in out["lines"]] == [False, True]
    assert [ln["reference"] for ln in out["results"]["lines"]] == ["C-100"]  # the counted lines only
    assert out["results"]["left_out"] == [{"name": "Opto-isolator", "reference": "U-7", "quantity": 1}]
    assert out["results"]["counts"]["left_out"] == 1 and out["results"]["counts"]["lines"] == 1
    assert out["results"]["failure_rate_per_hour"] < both["results"]["failure_rate_per_hour"]
    assert [x["part"]["part_number"] for x in m.position_parts(psu)["parts_list"]] == ["U-7"]  # still listed
    # Every line left out: nothing counted, no error.
    none = pm.predict_position(m, db, OWNERS, set(), ctl, assign=assign,
                               left_out=[ln["listing_id"] for ln in first["lines"]])
    assert none["results"]["failure_rate_per_hour"] == 0 and none["results"]["lines"] == []
    with pytest.raises(Invalid, match="left_out"):
        pm.predict_position(m, db, OWNERS, set(), ctl, left_out="U-7")
    # Saved, the prediction keeps what was left out; a refresh (no left_out given) leaves it out again,
    # with the part type it had.
    link = pm.predict_position(m, db, OWNERS, set(), ctl, assign=assign, left_out=[opto_line["listing_id"]], save=True)
    saved = rp.get_prediction(db, link["source"]["prediction_id"], OWNERS)
    assert [ln["reference"] for ln in saved.inputs["lines"]] == ["C-100"]
    assert saved.inputs["left_out"][0]["listing_id"] == opto_line["listing_id"]
    assert saved.inputs["left_out"][0]["record_id"] == OPTO
    again = pm.predict_position(m, db, OWNERS, set(), ctl)
    assert [ln["left_out"] for ln in again["lines"]] == [False, True] and again["lines"][1]["record_id"] == OPTO
    # Put back: an empty list counts every line.
    back = pm.predict_position(m, db, OWNERS, set(), ctl, left_out=[])
    assert len(back["results"]["lines"]) == 2
    # A position with no parts yet: the preview says so (the pane offers Add a part); saving refuses.
    bare = m.create_position("Bare")["id"]
    empty = pm.predict_position(m, db, OWNERS, set(), bare)
    assert empty["lines"] == [] and empty["results"]["failure_rate_per_hour"] == 0
    with pytest.raises(Invalid, match="no parts list"):
        pm.predict_position(m, db, OWNERS, set(), bare, save=True)
    _same_after_rebuild(m)


def test_left_out_lines_over_rest(client):
    ctl = client.post("/api/maintenance/positions", json={"name": "Controller"}).json()["id"]
    part = client.post("/api/maintenance/parts", json={"part_number": "C-100", "name": "Capacitor"}).json()
    listed = client.post(f"/api/maintenance/positions/{ctl}/parts",
                         json={"part_id": part["id"], "role": "component", "quantity": 3}).json()
    entry = listed["parts_list"][0]["id"]
    r = client.post(f"/api/maintenance/positions/{ctl}/prediction",
                    json={"assign": {"C-100": {"record_id": CAP}}, "left_out": [entry]})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["left_out"] and r.json()["results"]["counts"]["left_out"] == 1
    # Quantity changed on the parts list: the preview follows it.
    client.patch(f"/api/maintenance/position-parts/{entry}", json={"quantity": 5})
    r = client.post(f"/api/maintenance/positions/{ctl}/prediction", json={"assign": {"C-100": {"record_id": CAP}}})
    assert r.json()["lines"][0]["quantity"] == 5 and r.json()["results"]["lines"][0]["quantity"] == 5


def _product_with_a_bom(m):
    """A product whose part holds four capacitors and a board with two opto-isolators on it."""
    product = m.create_product("Drone", part_number="DR-3")
    cap = m.create_part("C-300", "Capacitor")["id"]
    board = m.create_part("PCB-1", "Control board")["id"]
    opto = m.create_part("U-9", "Opto-isolator")["id"]
    m.add_component(product["part"]["id"], cap, quantity=4)
    m.add_component(product["part"]["id"], board, quantity=1)
    m.add_component(board, opto, quantity=2)
    return product["id"], cap, board


def test_a_products_prediction_counts_its_parts_lists_and_its_bill_of_materials_together(m, db):
    """A product's design: the parts on its positions' parts lists and the parts of its bill of
    materials that none of them lists. A part added to a parts list never takes the other lines
    away, and a part on both is counted once, from the parts lists."""
    product, cap, board = _product_with_a_bom(m)
    esc = m.create_position("Speed controller", parent_id=product)["id"]
    first = pm.predict_position(m, db, OWNERS, set(), product)
    assert [(ln["reference"], ln["quantity"]) for ln in first["lines"]] == [("C-300", 4), ("U-9", 2)]
    assert first["source"] == "bill of materials" and not any(ln.get("listing_id") for ln in first["lines"])
    assert first["lines"][1]["assembly"] == ["Control board"]
    # A new part on the product's own parts list: one more line, every other one still there.
    light = m.create_part("L-1", "Navigation light")["id"]
    m.add_position_part(product, light, role="component", quantity=1)
    both = pm.predict_position(m, db, OWNERS, set(), product)
    assert [ln["reference"] for ln in both["lines"]] == ["L-1", "C-300", "U-9"]
    assert both["source"] == "parts lists and bill of materials"
    assert both["lines"][0]["listing_id"] and both["lines"][0]["position"]["id"] == product
    assert both["lines"][1]["part_id"] is None and "listing_id" not in both["lines"][1]
    # The rates add over both kinds of line.
    assign = {"L-1": {"rate_per_million_hours": 2.0}, "C-300": {"record_id": CAP}, "U-9": {"record_id": OPTO}}
    counted = pm.predict_position(m, db, OWNERS, set(), product, assign=assign)
    assert [ln["reference"] for ln in counted["results"]["lines"]] == ["L-1", "C-300", "U-9"]
    assert counted["results"]["failure_rate_per_million_hours"] == pytest.approx(
        sum(ln["rate_per_million_hours"] for ln in counted["results"]["lines"]))
    # A consumable on a parts list isn't a prediction line, so the bill of materials still has its part.
    grease = m.create_part("G-3", "Grease")["id"]
    m.add_component(m.product(product)["part"]["id"], grease, quantity=1)
    m.add_position_part(esc, grease, role="consumable", quantity=1)
    assert [ln["reference"] for ln in pm.predict_position(m, db, OWNERS, set(), product)["lines"]] == [
        "L-1", "C-300", "G-3", "U-9"]
    # A part of the bill of materials put on a parts list inside the product: counted once, as listed.
    m.add_position_part(esc, cap, role="component", quantity=3)
    once = pm.predict_position(m, db, OWNERS, set(), product)
    assert [(ln["reference"], ln["quantity"]) for ln in once["lines"]] == [("L-1", 1), ("C-300", 3), ("G-3", 1), ("U-9", 2)]
    assert once["lines"][1]["position"]["id"] == esc and once["lines"][1]["assembly"] == ["Speed controller"]
    # An assembly on a parts list stands for what's inside it.
    m.add_position_part(esc, board, role="replacement", quantity=1)
    listed = pm.predict_position(m, db, OWNERS, set(), product)
    assert [ln["reference"] for ln in listed["lines"]] == ["L-1", "C-300", "PCB-1", "G-3"]
    # A position inside the product counts its own parts lists only: the bill of materials is the product's.
    inside = pm.predict_position(m, db, OWNERS, set(), esc)
    assert [ln["reference"] for ln in inside["lines"]] == ["C-300", "PCB-1"] and inside["source"] == "parts lists"
    # Saved and refreshed: each line keeps its part type, whichever list it came from.
    assign = {"L-1": {"rate_per_million_hours": 2.0}, "C-300": {"record_id": CAP}, "PCB-1": {"excluded": True},
              "G-3": {"excluded": True}}
    link = pm.predict_position(m, db, OWNERS, set(), product, assign=assign, save=True)
    assert link["source"]["parts_source"] == "parts lists and bill of materials"
    again = pm.predict_position(m, db, OWNERS, set(), product)
    assert again["results"]["failure_rate_per_hour"] == pytest.approx(link["prediction"]["results"]["failure_rate_per_hour"])
    assert [ln.get("excluded", False) for ln in again["lines"]] == [False, False, True, True]
    _same_after_rebuild(m)


def test_every_part_of_the_bill_of_materials_on_a_parts_list_leaves_only_the_lists(m, db):
    product, cap, board = _product_with_a_bom(m)
    m.add_position_part(product, cap, role="component", quantity=4)
    m.add_position_part(product, board, role="component", quantity=1)
    got = pm.predict_position(m, db, OWNERS, set(), product)
    assert [ln["reference"] for ln in got["lines"]] == ["C-300", "PCB-1"]
    assert got["source"] == "parts lists" and got["warnings"] == []


def test_a_built_items_prediction_follows_its_design(m, db):
    product = m.create_product("Drone", part_number="DR-2")["id"]
    esc = m.create_position("Speed controller", parent_id=product)["id"]
    cap = m.create_part("C-200", "Capacitor")["id"]
    m.add_position_part(esc, cap, role="component", quantity=2)
    link = pm.predict_position(m, db, OWNERS, set(), esc, assign={"C-200": {"record_id": CAP}}, save=True)
    built = m.build_item(product, "SN-9", dry_run=False)
    copy = next(r["id"] for r in built["positions"] if r["design_position_id"] == esc)
    [there] = m.position_models(copy)
    assert there["model_id"] == link["model_id"] and there["source"]["design_role"] == "prediction"


def test_covariate_models_are_attached_as_they_are(m, db):
    pump = m.create_position("Seal")["id"]
    alt = pm.link_saved(m, db, OWNERS, set(), pump, "alt_model", "sample-alt-seal")
    ph = pm.link_saved(m, db, OWNERS, set(), pump, "model", "sample-model-seal-weibull-ph")
    rows = {r["id"]: r for r in pm.describe(m, db, OWNERS, set(), m.position_models(pump))}
    a = rows[alt["id"]]
    assert a["source_text"] == ("Assigned: Valve seal — Weibull ALT on temp & load (sample) (accelerated life, "
                                "stress: temperature, load)")
    ref = next(n for n in a["model"]["numbers"] if n["id"] == "reference")
    assert ref["text"] == "its lowest tested stress (Temperature (°C) 60, Load 0.5)"
    assert "covariates" not in a or a.get("covariates") is None
    p = rows[ph["id"]]
    assert p["source_text"].endswith("(covariate model, covariates: temp_C, load)")
    assert {n["id"] for n in p["model"]["numbers"]} >= {"mean", "b10", "reference"}
    full = pm.detail(m, db, OWNERS, set(), alt["id"])
    assert full["stress_note"].startswith("Shown as fitted") and full["curves"]["sf"]
    assert full["curves"]["what"].startswith("Reliability at its lowest tested stress")


def test_an_rbd_built_from_whats_inside_with_placeholders_then_rebuilt(m, db):
    plant = m.create_position("Pump station")["id"]
    a = m.create_position("Pump A", parent_id=plant)["id"]
    m.create_position("Pump B", parent_id=plant)
    pm.link_saved(m, db, OWNERS, set(), a, "model", SAMPLE)
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    assert link["model_type"] == link["role"] == "rbd" and link["placeholders"] == ["Pump B"]
    rbd = db.rbds.find_one({"_id": link["model_id"]})
    assert rbd["name"] == "Pump station (from the tree)"
    blocks = {n["data"]["label"]: n["data"] for n in rbd["graph"]["nodes"] if n["type"] == "component"}
    assert blocks["Pump A"]["model"].get("modelId") == SAMPLE  # the child's model in use, linked
    assert blocks["Pump B"]["model"]["placeholder"] is True  # never invented: flagged
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(plant), age=500)
    assert row["source_text"] == "Built from 2 positions inside · 1 placeholder"
    assert row["model"]["kind"] == "RBD" and row["model"]["quality"]["word"] == "1 placeholder"
    nums = {n["id"]: n for n in row["model"]["numbers"]}
    assert nums["mtbf"]["value"] > 0 and nums["reference"]["text"].startswith("reliability ")
    full = pm.detail(m, db, OWNERS, set(), link["id"])
    assert {b["label"]: b["position"]["name"] for b in full["blocks"]} == {"Pump A": "Pump A", "Pump B": "Pump B"}
    assert next(b for b in full["blocks"] if b["label"] == "Pump B")["placeholder"] is True
    # Rebuild: a new position inside becomes a block; the diagram (and its edits) is kept.
    db.rbds.update_one({"_id": link["model_id"]}, {"$set": {"graph.nodes.1.data.note": "edited"}})
    m.create_position("Pump C", parent_id=plant)
    again = pm.build_rbd(m, db, OWNERS, set(), plant, replace_link_id=link["id"])
    assert again["model_id"] == link["model_id"]
    rbd = db.rbds.find_one({"_id": link["model_id"]})
    labels = [n["data"]["label"] for n in rbd["graph"]["nodes"] if n["type"] == "component"]
    assert sorted(labels) == ["Pump A", "Pump B", "Pump C"]
    assert any((n.get("data") or {}).get("note") == "edited" for n in rbd["graph"]["nodes"])
    _same_after_rebuild(m)


def test_one_model_in_use_per_position(m, db):
    pump = m.create_position("Pump")["id"]
    inner = m.create_position("Impeller", parent_id=pump)["id"]
    pm.link_saved(m, db, OWNERS, set(), inner, "model", SAMPLE)
    life = pm.link_saved(m, db, OWNERS, set(), pump, "model", "sample-model-bearings-lognormal")
    rbd = pm.build_rbd(m, db, OWNERS, set(), pump)
    used = {x["id"]: x["in_use"] for x in m.position_models(pump)}
    assert used == {life["id"]: True, rbd["id"]: False}  # its own life model by default
    assert m.in_use_link(pump)["id"] == life["id"]
    m.use_position_model(pump, rbd["id"])
    assert m.in_use_link(pump)["id"] == rbd["id"]
    assert {x["id"]: x["in_use"] for x in m.all_position_models([pump])} == {life["id"]: False, rbd["id"]: True}
    with pytest.raises(Invalid, match="isn't on this position"):
        m.use_position_model(pump, "nope")
    _same_after_rebuild(m)
    # Taken off, the default comes back.
    m.unlink_position_model(rbd["id"])
    assert m.in_use_link(pump)["id"] == life["id"]


def test_a_parent_rbd_takes_a_childs_rbd_as_a_sub_system(m, db):
    top = m.create_position("Plant")["id"]
    line = m.create_position("Line 1", parent_id=top)["id"]
    m.create_position("Motor", parent_id=line)
    sub = pm.build_rbd(m, db, OWNERS, set(), line)
    m.use_position_model(line, sub["id"])
    parent = pm.build_rbd(m, db, OWNERS, set(), top)
    rbd = db.rbds.find_one({"_id": parent["model_id"]})
    [block] = [n for n in rbd["graph"]["nodes"] if n["type"] == "component"]
    assert (block["data"].get("rbd") or {}).get("id") == sub["model_id"]
    linked = pm.link_rbd(m, db, OWNERS, set(), top, "sample-rbd-pump-station")
    [row] = [r for r in pm.describe(m, db, OWNERS, set(), m.position_models(top)) if r["id"] == linked["id"]]
    assert row["source_text"].startswith("Linked: ")
