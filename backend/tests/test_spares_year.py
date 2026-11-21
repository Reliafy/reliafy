"""Spares for the year (Nov 2026): every part a failure or a task uses, its demand over the year
(failures plus planned replacements), the stock to hold over its lead time, the stock usable now and
when it was counted, what to order now and by when, and what to buy over the year.

The figures are checked against hand calculations for a water plant's three critical spares, on
Mon 23 Nov 2026: a seal kit on six mechanical seals (Weibull 483.9 days, shape 2.275), a shutdown
on 12 Dec that changes the seals 200 days old or more; a dosing pump's diaphragm kit, changed every
2,860 run hours (Weibull 8,000 h, shape 3.0); and a drive-end bearing (Weibull 1,173 days, 1.955).
Hand checks are Poisson-binomial counts of each part's chance of failing in the window; the app's
own simulation is held to its mean within 0.15 and to the same hold."""

from types import SimpleNamespace

import pytest

from backend.maintenance import forecast
from backend.maintenance import spares_year as sy
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, class_id
from backend.maintenance.store import GraphStore
from backend.services import spares_year as engine

TODAY = "2026-11-23"
SEALS = {"HLP-01": "2026-05-05", "HLP-02": "2026-04-22", "HLP-03": "2026-08-16", "HLP-04": "2025-08-06",
         "P-101": "2025-08-14", "P-102": "2026-09-25"}
MODELS = {
    "diaphragm": SimpleNamespace(kind="distribution", distribution_id="weibull", dataset_id="", spec={},
                                 results={"distribution_id": "weibull", "unit": "hours",
                                          "params": [{"name": "alpha", "value": 8000.0},
                                                     {"name": "beta", "value": 3.0}]}),
    "bearing": SimpleNamespace(kind="distribution", distribution_id="weibull", dataset_id="d1", spec={},
                               results={"distribution_id": "weibull", "unit": "days",
                                        "params": [{"name": "alpha", "value": 1172.9},
                                                   {"name": "beta", "value": 1.955}]}),
}


def fetch(model_type, model_id):
    return MODELS.get(model_id) if model_type == "model" else None


@pytest.fixture()
def m():
    out = Maintenance(GraphStore(":memory:", PROJECTORS), "user-spy", "tester")
    out.as_of = "2024-07-01"
    return out


def _plant(m, *, raw_water_on_list=False, lead=42, stock=1):
    """The high-lift station (four pumps) and the two raw water pumps: their seals, the seal kit on the
    high-lift seals' parts lists, the bearings, the dosing pump and the store, as on 23 Nov 2026."""
    ids = {}
    m.as_of = "2024-07-01"
    store = m.create_location("Store")["id"]
    ids["store"] = store
    hl = m.create_position("High-lift")["id"]
    ids["hl"] = hl
    sk = m.create_part("SK-75", "Seal kit, cartridge 75", unit_cost=640)["id"]
    dk = m.create_part("DK-40", "Diaphragm kit", unit_cost=180)["id"]
    br = m.create_part("6316-C3", "Bearing 6316-C3", unit_cost=410)["id"]
    m.update_part(sk, lead_time_days=lead, service_level=0.95)
    m.update_part(dk, lead_time_days=14, service_level=0.95)
    m.update_part(br, lead_time_days=5, service_level=0.95)
    ids.update(sk=sk, dk=dk, br=br)
    for tag in SEALS:
        parent = hl if tag.startswith("HLP") else None
        pump = m.create_position(f"Pump {tag}", parent_id=parent)["id"]
        seal = m.create_position(f"{tag} seal", parent_id=pump, position_class="Mechanical seal")["id"]
        ids[f"{tag}-MS"] = seal
        if tag.startswith("HLP"):
            de = m.create_position(f"{tag} DE bearing", parent_id=pump, position_class="Pump bearing")["id"]
            ids[f"{tag}-DE"] = de
    m.as_of = "2024-08-01"
    for tag in ("HLP-01", "HLP-02", "HLP-03", "HLP-04"):
        m.fit(ids[f"{tag}-DE"], new_item={"name": f"{tag} DE bearing"}, on="2024-08-01")
        m.link_position_model(ids[f"{tag}-DE"], "model", "bearing", name="DE bearing life")
        m.add_position_part(ids[f"{tag}-DE"], br, quantity=1)
    for tag, day in sorted(SEALS.items(), key=lambda kv: kv[1]):
        m.as_of = day
        m.fit(ids[f"{tag}-MS"], new_item={"name": f"{tag} seal"}, on=day)
    m.as_of = "2026-11-10"
    m._emit("class.model_fitted", {
        "id": class_id(m.org, "Mechanical seal"), "name": "Mechanical seal", "model_id": "seal",
        "distribution": "weibull", "params": [{"name": "alpha", "value": 483.9}, {"name": "beta", "value": 2.275}],
        "extras": None, "unit": "days", "fitted_on": m.today(), "failures": 42, "suspensions": 6})
    on_list = list(SEALS) if raw_water_on_list else ["HLP-01", "HLP-02", "HLP-03", "HLP-04"]
    for tag in on_list:
        m.add_position_part(ids[f"{tag}-MS"], sk, quantity=1, critical=True)
    if stock:
        m.adjust_stock(sk, store, stock, reason="opening stock")
    # The dosing pump: its data-sheet diaphragm life, a run-hours counter read at the last change.
    cd = m.create_position("Chlorine dosing pump CD-201")["id"]
    ids["cd"] = cd
    m.fit(cd, new_item={"name": "CD-201"}, on="2026-11-10")
    m.link_position_model(cd, "model", "diaphragm", name="CD-201 diaphragm (data sheet)")
    m.as_of = "2026-11-16"
    rh = m.add_point(cd, "CD-201 run hours", kind="counter", unit="hours")["id"]
    m.record_reading(rh, 31250, on="2026-11-16")
    t = m.create_task(cd, "Replace the diaphragm", 2860, "hours", outcome="fixed_interval", point_id=rh)
    m.set_task_resources(t["id"], {"spares": [{"part_id": dk, "qty": 1}]})
    ids["diaphragm_task"] = t["id"]
    m.as_of = "2026-11-21"
    return ids


def _shutdown(m, ids, seals=("HLP-01", "HLP-02", "HLP-03", "HLP-04"), bearing=False):
    """The high-lift shutdown on 12 Dec 2026, yearly, changing the seals 200 days old or more."""
    m.as_of = "2026-11-21"
    pkg = m.create_package("High-lift shutdown", position_id=ids["hl"], every=1, unit="years", anchor="2026-12-12")
    m.set_package_shutdown(pkg["id"], {"duration_hours": 36, "cost": 6000})
    tasks = {}
    for tag in seals:
        t = m.create_task(ids[f"{tag}-MS"], "Replace the mechanical seal", 12, "months", outcome="fixed_interval")
        m.set_task_older_than(t["id"], {"value": 200, "unit": "days"})
        m.add_package_task(pkg["id"], t["id"])
        tasks[tag] = t["id"]
    if bearing:
        t = m.create_task(ids["HLP-03-DE"], "Replace the DE bearing", 5, "years", outcome="fixed_interval")
        m.add_package_task(pkg["id"], t["id"])
        tasks["bearing"] = t["id"]
    return pkg["id"], tasks


def _row(out, part_number):
    return next(r for r in out["parts"] if r["part"]["part_number"] == part_number)


def _count(m, ids):
    """The stores count of Fri 13 Nov (2, 3, 2), and the diaphragm kit fitted on 16 Nov."""
    m.as_of = TODAY
    m.count_stock(ids["sk"], ids["store"], 2, on="2026-11-13", by="Stores")
    m.count_stock(ids["dk"], ids["store"], 3, on="2026-11-13", by="Stores")
    m.count_stock(ids["br"], ids["store"], 2, on="2026-11-13", by="Stores")
    m.adjust_stock(ids["dk"], ids["store"], -1, reason="CD-201 diaphragm change", on="2026-11-16")


# ---- the seal kit ------------------------------------------------------------------------

def test_the_seal_kit_on_four_seals_failures_only(m):
    ids = _plant(m)
    m.as_of = TODAY
    out = sy.spares_year(m, {"position_class": "Mechanical seal"}, fetch=fetch)
    r = _row(out, "SK-75")
    # Hand check: year mean 3.435 (P10-P90 2-5); over 42 days each seal's chance of failing 0.071, 0.076,
    # 0.033, 0.184: P(<= 1) = 0.961, so hold 1; with 1 usable, a 3.9% chance of running out.
    assert r["demand"]["mean"] == pytest.approx(3.435, abs=0.15)
    assert (r["demand"]["p10"], r["demand"]["p90"]) == (2, 5) and r["demand"]["planned"] == 0
    assert r["hold"] == 1 and r["usable_now"] == 1 and r["lead_time_days"] == 42
    assert r["risk_at_stock"] == pytest.approx(0.039, abs=0.012)
    assert r["positions"]["failures"] == ["HLP-01 seal", "HLP-02 seal", "HLP-03 seal", "HLP-04 seal"]
    # The class's own Spares tab says the same, and that it counts only the positions naming the part.
    fc = forecast.class_forecast(m, "Mechanical seal")
    s = fc["spares"][0]
    assert s["stocking"]["hold"] == 1 and s["expected"] == pytest.approx(r["demand"]["mean"], abs=1e-9)
    assert s["positions"] == 4 and "Counts the 4 positions" in s["summary"]
    assert fc["expected"] == pytest.approx(5.12, abs=0.15)  # the class headline: all six seals


def test_six_seals_and_a_longer_lead_time(m):
    ids = _plant(m, raw_water_on_list=True, lead=42)
    _count(m, ids)
    out = sy.spares_year(m, {"position_class": "Mechanical seal"}, fetch=fetch)
    r = _row(out, "SK-75")
    # Six seals: 5.120 (3-7); over 42 days P(<= 2) = 0.990: hold 2.
    assert r["demand"]["mean"] == pytest.approx(5.12, abs=0.15) and (r["demand"]["p10"], r["demand"]["p90"]) == (3, 7)
    assert r["hold"] == 2 and r["usable_now"] == 2
    m.update_part(ids["sk"], lead_time_days=112)
    r = _row(sy.spares_year(m, {"position_class": "Mechanical seal"}, fetch=fetch), "SK-75")
    # 16 weeks: P(<= 2) = 0.840, P(<= 3) = 0.971: hold 3; at 2 the chance of running out is 16-17%.
    assert r["hold"] == 3 and r["order_now"] == 1
    assert r["risk_at_stock"] == pytest.approx(0.165, abs=0.025)
    assert r["arrives"] == "2027-03-15"


def test_the_shutdowns_seal_changes_are_in_the_demand_and_the_hold(m):
    ids = _plant(m, raw_water_on_list=True, lead=112)
    _count(m, ids)
    pkg, tasks = _shutdown(m, ids)
    m.as_of = TODAY
    out = sy.spares_year(m, {"position_class": "Mechanical seal"}, fetch=fetch)
    r = _row(out, "SK-75")
    # 12 Dec changes HLP-01 (221 d), HLP-02 (234 d) and HLP-04 (493 d); HLP-03 (118 d) is too young.
    # Year: 3.658 failures + 2.852 planned = 6.511 (5-8); over 112 days 2 for failures + 3 planned: hold 5.
    assert r["demand"]["planned"] == pytest.approx(2.852, abs=0.05)
    assert r["demand"]["failures"] == pytest.approx(3.658, abs=0.15)
    assert r["demand"]["mean"] == pytest.approx(6.511, abs=0.15)
    assert (r["demand"]["p10"], r["demand"]["p90"]) == (5, 8)
    assert r["hold"] == 5
    shut = {j["unit"]: j["chance"] for j in r["jobs"] if j["date"] == "2026-12-12"}
    assert shut["HLP-03 seal"] == 0 and shut["HLP-04 seal"] == pytest.approx(0.92, abs=0.03)  # too young: skipped in every run
    assert shut["HLP-01 seal"] == pytest.approx(0.95, abs=0.03)  # unless it fails before the shut
    # The class forecast's failures drop by the seals the shut renews (5.12 run to failure).
    fc = forecast.class_forecast(m, "Mechanical seal")
    assert fc["expected"] == pytest.approx(3.658, abs=0.15)
    assert fc["spares"][0]["stocking"]["hold"] == 5
    assert fc["spares"][0]["planned_expected"] == pytest.approx(2.852, abs=0.05)

    # The shutdown's parts: three kits needed, two usable, and an order today lands 15 Mar.
    parts = sy.package_parts(m, pkg, fetch=fetch)
    p = next(x for x in parts["parts"] if x["part"]["part_number"] == "SK-75")
    assert parts["visit"]["on"] == "2026-12-12" and p["needed_most"] == 3 and p["usable_now"] == 2 and p["short"]
    assert p["order_today_arrives"] == "2027-03-15" and not p["arrives_before_visit"]
    # The chance a breakdown finds no kit before the order lands: 1.000, 0.660, 0.302, 0.167 for three,
    # two, one or none of the changes at the shut.
    for leave, want in (((), 1.0), (("HLP-01",), 0.660), (("HLP-01", "HLP-02"), 0.302),
                        (("HLP-01", "HLP-02", "HLP-04"), 0.167)):
        got = sy.package_parts(m, pkg, fetch=fetch, leave_out=[tasks[t] for t in leave])
        row = next(x for x in got["parts"] if x["part"]["part_number"] == "SK-75")
        assert row["chance_short_before_arrival"] == pytest.approx(want, abs=0.03), leave


def test_the_seal_kit_answer_with_one_change_at_the_shut(m):
    ids = _plant(m, raw_water_on_list=True, lead=112)
    _count(m, ids)
    _pkg, _tasks = _shutdown(m, ids, seals=("HLP-04",))
    m.as_of = TODAY
    r = _row(sy.spares_year(m, {}, fetch=fetch), "SK-75")
    # 4.483 failures + 0.914 planned = 5.397 (4-7); hold 3 + 1 planned = 4; order 4 - 2 = 2; buy 6 + 4 - 2 = 8.
    assert r["demand"]["mean"] == pytest.approx(5.397, abs=0.15)
    assert r["demand"]["planned"] == pytest.approx(0.914, abs=0.05)
    assert (r["demand"]["p10"], r["demand"]["p90"]) == (4, 7)
    assert (r["hold"], r["order_now"], r["buy_for_year"]) == (4, 2, 8)
    assert r["counted_on"] == "2026-11-13"


# ---- the diaphragm kit: planned changes on a counter ------------------------------------------

def test_a_part_only_a_task_uses_is_in_the_answer_once_the_task_can_be_dated(m):
    ids = _plant(m)
    _count(m, ids)
    out = sy.spares_year(m, {"position_id": ids["cd"]}, fetch=fetch)
    # One reading and no operating plan: the change can't be dated, and the failures have no rate.
    assert any(x["task"]["name"] == "Replace the diaphragm" for x in out["not_dated"])
    assert [r["part"]["part_number"] for r in out["parts"]] == []
    m.set_operating_plan(ids["cd"], {"background": {"kind": "continuous"}}, name="Around the clock",
                         from_="2026-11-16")
    out = sy.spares_year(m, {"position_id": ids["cd"]}, fetch=fetch)
    r = _row(out, "DK-40")
    # Changes due 15 Mar, 12 Jul and 8 Nov 2027; failures 0.137 (the diaphragm counted from its 16 Nov
    # change, renewed at each); hold 0 over 14 days; 2 usable cover March and July; order by 25 Oct.
    assert [j["date"] for j in r["jobs"]] == ["2027-03-15", "2027-07-12", "2027-11-08"]
    assert r["demand"]["planned"] == 3 and r["demand"]["failures"] == pytest.approx(0.137, abs=0.03)
    assert r["demand"]["p90"] == 4 and r["hold"] == 0 and r["usable_now"] == 2
    assert r["order_by"] == [{"qty": 1.0, "by": "2027-10-25", "for": "2027-11-08", "job": "Replace the diaphragm",
                              "unit": "Chlorine dosing pump CD-201"}]
    assert r["buy_for_year"] == 2
    # 7 days at 24 h since the 31,250 h change (not the pump's own hours).
    assert out["units"][0]["age"] == pytest.approx(168, abs=1)


# ---- the bearing, and the table across parts -------------------------------------------------

def test_the_bearings_from_a_saved_model_and_the_change_at_the_shut(m):
    ids = _plant(m)
    _count(m, ids)
    m.as_of = TODAY
    r = _row(sy.spares_year(m, {"position_id": ids["hl"]}, fetch=fetch), "6316-C3")
    # Four bearings at 844 days: 1.720 failures (0-3); over 5 days P(0) = 0.976: hold 0.
    assert r["demand"]["mean"] == pytest.approx(1.72, abs=0.15) and (r["demand"]["p10"], r["demand"]["p90"]) == (0, 3)
    assert r["hold"] == 0 and r["risk_at_stock"] < 0.01
    _shutdown(m, ids, seals=("HLP-04",), bearing=True)
    m.as_of = TODAY
    out = sy.spares_year(m, {"position_id": ids["hl"], "root": ids["hl"]}, fetch=fetch)
    r = _row(out, "6316-C3")
    # With HLP-03's change at the shut: 1.402 + 1 = 2.402 (1-4); buy 3 + 0 - 2 = 1.
    assert r["demand"]["planned"] == 1 and r["demand"]["mean"] == pytest.approx(2.402, abs=0.15)
    assert (r["demand"]["p10"], r["demand"]["p90"]) == (1, 4) and r["buy_for_year"] == 1


def test_one_table_across_parts_with_its_csv(m):
    ids = _plant(m, raw_water_on_list=True, lead=112)
    _count(m, ids)
    _shutdown(m, ids, seals=("HLP-04",), bearing=True)
    m.set_operating_plan(ids["cd"], {"background": {"kind": "continuous"}}, from_="2026-11-16")
    m.as_of = TODAY
    out = sy.spares_year(m, {}, fetch=fetch)
    got = {r["part"]["part_number"]: (round(r["demand"]["mean"], 1), r["demand"]["p90"], r["hold"], r["usable_now"],
                                      r["order_now"], r["buy_for_year"]) for r in out["parts"]}
    assert got["SK-75"][2:] == (4, 2, 2, 8) and got["SK-75"][1] == 7
    assert got["DK-40"][1:] == (4, 0, 2, 0, 2)
    assert got["6316-C3"][1:] == (4, 0, 2, 0, 1)
    assert out["rule"] == engine.RULE and out["months"] == 12
    csv = sy.csv_text(out).splitlines()
    assert csv[0].split(",")[:4] == ["part_number", "name", "critical", "demand_mean"]
    dk = next(line for line in csv if line.startswith("DK-40"))
    assert ",2027-10-25," in dk and "$" not in dk and " days" not in dk


# ---- the stock count ---------------------------------------------------------------------------

def test_a_stock_count_on_a_date_keeps_what_was_booked_after_it(m):
    ids = _plant(m)
    m.as_of = TODAY
    m.adjust_stock(ids["dk"], ids["store"], 1, on="2026-11-18", reason="received")
    part = m.count_stock(ids["dk"], ids["store"], 3, on="2026-11-13", by="J. Okafor")
    # Counted 3 on 13 Nov; the 1 received on 18 Nov stands: 4.
    assert part["on_hand"] == 4 and part["counted_on"] == "2026-11-13" and part["counted_days_ago"] == 10
    assert part["stock"][0]["counted"] == {"on": "2026-11-13", "quantity": 3, "by": "J. Okafor"}
    assert m.part(ids["sk"])["counted_on"] is None  # never counted
    with pytest.raises(Invalid, match="future"):
        m.count_stock(ids["dk"], ids["store"], 3, on="2026-12-01")
    with pytest.raises(Invalid, match="count"):
        m.count_stock(ids["dk"], ids["store"], -1)
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_count_sheet_is_checked_first_and_all_or_nothing(m):
    ids = _plant(m)
    m.as_of = TODAY
    rows = [{"part_number": "SK-75", "location": "Store", "on_hand": 2, "counted_on": "2026-11-13"},
            {"part_number": "DK-40", "location": "Store", "on_hand": 3, "counted_on": "2026-11-13"},
            {"part_number": "NOPE", "location": "Store", "on_hand": 1, "counted_on": "2026-11-13"}]
    out = m.count_stock_sheet(rows, dry_run=False)
    assert not out["ok"] and out["errors"][0]["row"] == 3 and m.part(ids["sk"])["on_hand"] == 1
    preview = m.count_stock_sheet(rows[:2])
    assert preview["dry_run"] and [r["change"] for r in preview["rows"]] == [1, 3]
    assert m.part(ids["sk"])["on_hand"] == 1
    done = m.count_stock_sheet(rows[:2], dry_run=False)
    assert done["ok"] and m.part(ids["sk"])["on_hand"] == 2 and m.part(ids["dk"])["on_hand"] == 3


def test_a_planned_fleet_of_a_design_not_yet_built(m):
    m.as_of = "2026-11-01"
    product = m.create_product("Dosing skid")
    top = product["id"] if "id" in product else product["product"]["id"]
    pump = m.create_position("Dosing pump", parent_id=top)["id"]
    kit = m.create_part("DK-40", "Diaphragm kit")["id"]
    m.update_part(kit, lead_time_days=14)
    t = m.create_task(pump, "Replace the diaphragm", 4, "months", outcome="fixed_interval")
    m.set_task_resources(t["id"], {"spares": [{"part_id": kit, "qty": 1}]})
    m.as_of = TODAY
    with_none = sy.spares_year(m, sy.scope_of(m, top), fetch=fetch)
    assert with_none["parts"] == [] and with_none["of"]["built"] == 0
    out = sy.spares_year(m, sy.scope_of(m, top, fleet_size=5), fetch=fetch)
    r = _row(out, "DK-40")
    # Five new units, each changed at 4 and 8 months (the third, at 12 x 30.4375 days, is the horizon's end).
    assert r["demand"]["planned"] == 10 and r["demand"]["failures"] == 0 and out["fleet_size"] == 5


def test_bad_requests_are_refused(m):
    _plant(m)
    m.as_of = TODAY
    with pytest.raises(Invalid, match="months"):
        sy.spares_year(m, {}, months=0)
    with pytest.raises(Invalid, match="service level"):
        sy.spares_year(m, {}, service_level=2)
