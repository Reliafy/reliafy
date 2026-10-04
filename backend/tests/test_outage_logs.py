"""Outage logs (issue #159): import, the observed system history through
RePyability's timelines, models fitted from the log, ownership, the storage
cap, the REST routes and the MCP tools."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.services import outage_logs as ol

A, B = "user-a", "user-b"


def _node(nid, ntype="component", label=None, **data):
    return {"id": nid, "type": ntype, "data": {"label": label or nid, **data}}


# Pump A and Valve B in series, feeding the parallel pair Fan C / Fan D.
GRAPH = {
    "unit": "Hours",
    "nodes": [
        _node("input", "input"), _node("a", label="Pump A"), _node("b", label="Valve B"),
        _node("c", label="Fan C"), _node("d", label="Fan D"), _node("output", "output"),
    ],
    "edges": [{"source": s, "target": t} for s, t in
              [("input", "a"), ("a", "b"), ("b", "c"), ("b", "d"), ("c", "output"), ("d", "output")]],
}

# Hand-worked over a 1000 h window:
#   100-110  Pump A down               -> system down 10 h, caused by Pump A
#   200-230  Valve B down              -> 30 h, Valve B
#   300-400  Fan C down; 350-360 Fan D -> 10 h (350-360), Fan D (the second of the pair to go)
#   500-520  Fan D; 510-530 Fan C      -> 10 h (510-520), Fan C
#   600-605  Pump A; 602-620 Valve B   -> 20 h (600-620), Pump A (first down), restored by Valve B
#   990-     Valve B, still down       -> 10 h to the window end, Valve B
# System downtime 90 h -> availability 0.91, 6 outages, mean 15 h.
# Attributed: Pump A 30 (2), Valve B 40 (2), Fan C 10 (1), Fan D 10 (1).
LOG = """Asset,Outage start,Restored,Reason,Planned
Pump A,100,110,seal leak,no
Valve B,200,230,,no
Fan C,300,400,,no
Fan D,350,360,,no
Fan D,500,520,,no
Fan C,510,530,,no
Pump A,600,605,,no
Valve B,602,620,,no
Valve B,990,,,no
"""


def _history(text=LOG, graph=GRAPH, **kw):
    parsed = ol.parse_log(text, graph, window_start=0, window_end=1000, **kw)
    return parsed, ol.system_history(graph, {**parsed, "_id": "log"})


# ---- analysis: a hand-computed example -----------------------------------------------------

def test_series_and_parallel_history_matches_the_hand_calculation():
    _, h = _history()
    k = h["kpis"]
    assert k["window"] == 1000
    assert k["downtime"] == pytest.approx(90)
    assert k["availability"] == pytest.approx(0.91)
    assert k["outages"] == 6 and k["failures"] == 6 and k["planned_outages"] == 0
    assert k["mean_downtime"] == pytest.approx(15)
    assert k["mtbf"] == pytest.approx(910 / 6, rel=1e-4)
    assert k["ongoing"] is True

    spans = [(o["start"], o["end"], o["cause"]) for o in h["outages"]]
    assert spans == [(100, 110, "a"), (200, 230, "b"), (350, 360, "d"), (510, 520, "c"), (600, 620, "a"),
                     (990, 1000, "b")]
    # The pair's outages: the other fan was already down.
    assert h["outages"][2]["down_with"] == ["c"] and h["outages"][3]["down_with"] == ["d"]
    assert h["outages"][4]["restored_by"] == "b"
    assert h["outages"][5]["ongoing"] is True and h["outages"][5]["restored_by"] is None

    by = {c["node_id"]: c for c in h["components"]}
    assert {n: by[n]["system_downtime"] for n in by} == pytest.approx({"a": 30, "b": 40, "c": 10, "d": 10})
    assert {n: by[n]["system_outages"] for n in by} == {"a": 2, "b": 2, "c": 1, "d": 1}
    assert by["b"]["share"] == pytest.approx(4 / 9, rel=1e-5)
    assert sum(c["share"] for c in h["components"]) == pytest.approx(1, rel=1e-5)
    # Each block's own record.
    assert {n: by[n]["downtime"] for n in by} == pytest.approx({"a": 15, "b": 58, "c": 120, "d": 30})
    assert {n: by[n]["outages"] for n in by} == {"a": 2, "b": 3, "c": 2, "d": 2}
    # Ranked by share of the system's downtime.
    assert [c["node_id"] for c in h["components"]] == ["b", "a", "c", "d"]
    # The step line starts up and alternates.
    assert h["series"]["t"][:3] == [0, 100, 110] and h["series"]["up"][:3] == [1, 0, 1]


def test_planned_outages_are_counted_apart():
    text = "asset,start,end,planned\nPump A,100,110,yes\nValve B,200,230,no\n"
    _, h = _history(text)
    assert h["kpis"]["planned_outages"] == 1 and h["kpis"]["failures"] == 1
    assert h["outages"][0]["planned"] is True


def test_vote_gate_needs_two_of_three():
    graph = {
        "unit": "Hours",
        "nodes": [_node("input", "input"), _node("x"), _node("y"), _node("z"), _node("k", "knode", "2oo3", n=2),
                  _node("output", "output")],
        "edges": [{"source": s, "target": t} for s, t in
                  [("input", "x"), ("input", "y"), ("input", "z"), ("x", "k"), ("y", "k"), ("z", "k"),
                   ("k", "output")]],
    }
    _, h = _history("asset,start,end\nx,10,50\ny,20,30\n", graph)
    assert [(o["start"], o["end"], o["cause"]) for o in h["outages"]] == [(20, 30, "y")]
    assert "k" not in {c["node_id"] for c in h["components"]}


# ---- multi-unit blocks: an asset is one unit, not the whole block (#181) -----------------

def _pump_train(pumps):
    """MCC -> strainer -> ``pumps`` -> check valve."""
    return {
        "unit": "Hours",
        "nodes": [_node("input", "input"), _node("mcc", label="MCC"), _node("str", label="Strainer"), pumps,
                  _node("cv", label="Check valve"), _node("output", "output")],
        "edges": [{"source": s, "target": t} for s, t in
                  [("input", "mcc"), ("mcc", "str"), ("str", "pumps"), ("pumps", "cv"), ("cv", "output")]],
    }


STANDBY = _pump_train(_node("pumps", "standby", "CW pumps A/B", spares=1))
# The issue's 2025 CMMS log: only the 6 h A/B overlap takes the 1+1 standby pair down.
PUMP_LOG = """asset,start,end,reason
P-101A,2025-02-03 06:00,2025-02-04 12:00,seal leak
P-101B,2025-02-04 02:00,2025-02-04 08:00,bearing trip
P-101A,2025-07-11 09:00,2025-07-12 15:00,seal leak
P-101B,2025-12-29 07:00,,awaiting parts
"""


def _pumps(graph=STANDBY, text=PUMP_LOG, **kw):
    parsed = ol.parse_log(text, graph, window_start="2025-01-01 00:00", window_end="2026-01-01 00:00", **kw)
    return parsed, ol.system_history(graph, {**parsed, "_id": "x"})


def test_standby_block_is_down_only_while_both_units_are():
    parsed, h = _pumps(asset_map={"P-101A": "pumps", "P-101B": "pumps"})
    assert [(a["name"], a["unit"]) for a in parsed["assets"]] == [("P-101A", 1), ("P-101B", 2)]
    k = h["kpis"]
    assert k["downtime"] == pytest.approx(6) and k["outages"] == 1
    assert k["availability"] == pytest.approx(1 - 6 / 8760, rel=1e-6)
    pumps = next(c for c in h["components"] if c["node_id"] == "pumps")
    assert pumps["downtime"] == pytest.approx(6) and pumps["share"] == pytest.approx(1)
    assert [(u["unit"], u["assets"], u["downtime"]) for u in pumps["units"]] == [
        (1, ["P-101A"], pytest.approx(60)), (2, ["P-101B"], pytest.approx(71))]
    # The chart draws when the block itself was down, and the notes say how it was read.
    assert [(b["start"], b["end"]) for b in h["bars"]] == [(818, 824)]
    assert any("down only while both units are: P-101A is unit 1; P-101B is unit 2" in n for n in h["notes"])
    assert not any("treated as one unit" in n for n in h["notes"])
    # A fitted model is the units' (their lives pooled), not the block's.
    life_x, life_c = ol.fit_data(STANDBY, {**parsed, "_id": "x"})["pumps"]["life"]
    assert sorted(life_x) == [798, 818, 3765, 4137, 7871] and sum(1 for c in life_c if c == 0) == 4


def test_units_can_be_chosen_or_the_whole_block_taken():
    # An asset standing for the whole block takes it down on its own.
    parsed, h = _pumps(asset_map={"P-101A": "pumps#all", "P-101B": "pumps#2"})
    assert parsed["asset_units"] == {"P-101A": "all", "P-101B": 2}
    assert h["kpis"]["downtime"] == pytest.approx(60)
    # A replacement shares its predecessor's unit; a third asset with no unit is refused.
    text = PUMP_LOG + "P-101C,2025-09-01 00:00,2025-09-01 10:00,new pump\n"
    _, h = _pumps(text=text, asset_map={"P-101A": "pumps#1", "P-101B": "pumps#2", "P-101C": "pumps#1"})
    assert h["kpis"]["downtime"] == pytest.approx(6)
    parsed = ol.parse_log(text, STANDBY, window_start="2025-01-01 00:00", window_end="2026-01-01 00:00",
                          asset_map={"P-101A": "pumps", "P-101B": "pumps", "P-101C": "pumps"})
    assert any("which has 2" in n for n in parsed["notes"])
    with pytest.raises(ol.OutageLogError, match="3 assets are mapped to units of “CW pumps A/B”, which has 2"):
        ol.system_history(STANDBY, {**parsed, "_id": "x"})
    with pytest.raises(ol.OutageLogError, match="which has 2 units"):
        _pumps(asset_map={"P-101A": "pumps#3"})
    with pytest.raises(ol.OutageLogError, match="which is one unit"):
        _pumps(asset_map={"P-101A": "cv#2"})


def test_one_asset_on_a_redundant_block_is_one_unit():
    _, h = _pumps(text="asset,start,end\nP-101A,2025-03-01 00:00,2025-03-02 00:00\n",
                  asset_map={"P-101A": "pumps"})
    assert h["kpis"]["downtime"] == 0
    assert any("map it to 'pumps#all'" in n for n in h["notes"])


def test_count_and_load_sharing_blocks_by_their_units():
    text = "asset,start,end\nU1,10,50\nU2,20,30\nU3,40,60\n"
    m = {"U1": "pumps", "U2": "pumps", "U3": "pumps"}
    # 2 of 3 needed: down while two are out (20-30 and 40-50).
    share = _pump_train(_node("pumps", "loadshare", "Fans", units=3, k=2, load=1))
    parsed = ol.parse_log(text, share, window_start=0, window_end=100, asset_map=m)
    assert ol.system_history(share, {**parsed, "_id": "x"})["kpis"]["downtime"] == pytest.approx(20)
    # A parallel count of 3: down only while all three are (none here); a series count: while any is.
    par = _pump_train(_node("pumps", "parallel", "Fans", n=3))
    parsed = ol.parse_log(text, par, window_start=0, window_end=100, asset_map=m)
    assert ol.system_history(par, {**parsed, "_id": "x"})["kpis"]["downtime"] == 0
    ser = _pump_train(_node("pumps", "series", "Fans", n=3))
    parsed = ol.parse_log(text, ser, window_start=0, window_end=100, asset_map=m)
    assert ol.system_history(ser, {**parsed, "_id": "x"})["kpis"]["downtime"] == pytest.approx(50)


def test_remapping_keeps_an_assets_unit():
    db = mongomock.MongoClient()["outage_units"]
    parsed = ol.parse_log(PUMP_LOG, STANDBY, window_start="2025-01-01 00:00", window_end="2026-01-01 00:00",
                          asset_map={"P-101A": "pumps#2", "P-101B": "pumps#1"})
    log = {"_id": "x", "owner_id": A, **{k: parsed[k] for k in ("rows", "asset_map", "asset_units")}}
    db.outage_logs.insert_one(log)
    # The builder sends plain node ids: an asset left on its block keeps its unit.
    log = ol.update_log(db, log, STANDBY, asset_map={"P-101A": "pumps", "P-101B": "pumps"})
    assert log["asset_units"] == {"P-101A": 2, "P-101B": 1}
    log = ol.update_log(db, log, STANDBY, asset_map={"P-101A": "mcc"})
    assert log["asset_units"] == {"P-101B": 1} and log["asset_map"]["P-101A"] == "mcc"


def test_the_window_clips_and_drops():
    parsed = ol.parse_log("asset,start,end\nPump A,50,150\nPump A,1500,1600\n", GRAPH, window_start=100,
                          window_end=1000)
    h = ol.system_history(GRAPH, {**parsed, "_id": "x"})
    assert h["kpis"]["window"] == 900
    assert h["outages"][0]["start"] == 100 and h["outages"][0]["duration"] == 50
    assert any("outside the observation window" in n for n in h["notes"])


# ---- import: formats, bad rows, merges, unmapped assets ------------------------------------

def test_columns_are_detected_from_headers():
    assert ol.detect_columns(["Equipment", "Failure mode", "Down at", "Back up", "Planned?"]) == {
        "start": "Down at", "end": "Back up", "asset": "Equipment", "planned": "Planned?", "reason": "Failure mode"}
    assert ol.detect_columns(["Tag", "Start", "Duration (h)"]) == {"start": "Start", "duration": "Duration (h)",
                                                                   "asset": "Tag"}


def test_iso_dates_convert_to_the_diagram_unit():
    text = "asset,start,end\nPump A,2024-03-01T00:00:00Z,2024-03-01 06:00\nValve B,2024-03-02 00:00,\n"
    parsed = ol.parse_log(text, GRAPH, window_end="2024-03-03T00:00")
    assert parsed["time_kind"] == "datetime" and parsed["origin"] == "2024-03-01T00:00:00"
    assert parsed["window"] == {"start": 0.0, "end": 48.0}
    assert [(r["start"], r["end"]) for r in parsed["rows"]] == [(0, 6), (24, None)]
    h = ol.system_history(GRAPH, {**parsed, "_id": "x"})
    assert h["kpis"]["downtime"] == pytest.approx(30)
    assert h["outages"][1]["start_at"] == "2024-03-02T00:00"


def test_days_unit_and_tab_separated_text():
    graph = {**GRAPH, "unit": "Days"}
    text = "asset\tstart\tend\nPump A\t2024-01-01 00:00\t2024-01-01 12:00\nPump A\t2024-01-05\t2024-01-06\n"
    parsed = ol.parse_log(text, graph)
    assert parsed["unit"] == "Days"
    assert [(r["start"], r["end"]) for r in parsed["rows"]] == [(0, 0.5), (4, 5)]


def test_day_first_and_month_first_dates():
    text = "asset,start,end\nPump A,13/03/2024 08:00,13/03/2024 10:30\n"
    assert ol.parse_log(text, GRAPH)["rows"][0]["end"] == pytest.approx(2.5)
    us = "asset,start,end\nPump A,03/13/2024 08:00,03/13/2024 10:30\n"
    assert ol.parse_log(us, GRAPH)["rows"][0]["end"] == pytest.approx(2.5)
    # Ambiguous: read day first, and the import says so; month first on request.
    amb = "asset,start,end\nPump A,03/04/2024,05/04/2024\n"
    parsed = ol.parse_log(amb, GRAPH)
    assert parsed["rows"][0]["end"] == pytest.approx(48)
    assert any("day first" in n for n in parsed["notes"])
    assert ol.parse_log(amb, GRAPH, date_order="mdy")["rows"][0]["end"] == pytest.approx(61 * 24)  # 4 March to 4 May


def test_text_month_dates_and_durations():
    text = "asset,start,duration\nPump A,14 Mar 2024 08:00,90\n"
    parsed = ol.parse_log(text, GRAPH, unit="minutes")
    assert parsed["rows"][0]["end"] == pytest.approx(1.5)


def test_numeric_times_convert_from_another_unit():
    parsed = ol.parse_log("asset,start,end\nPump A,1,2\n", GRAPH, unit="days")
    assert (parsed["rows"][0]["start"], parsed["rows"][0]["end"]) == (24, 48)


def test_dates_need_a_clock_unit_on_the_diagram():
    with pytest.raises(ol.OutageLogError, match="isn't a clock unit"):
        ol.parse_log("asset,start,end\nPump A,2024-01-01,2024-01-02\n", {**GRAPH, "unit": "Cycles"})


def test_bad_rows_are_all_listed_in_order():
    text = ("asset,start,end,planned\nPump A,2024-01-02,2024-01-01,no\n,2024-01-01,2024-01-02,no\n"
            "Valve B,someday,2024-01-02,no\nFan C,2024-01-01,2024-01-02,maybe\n")
    with pytest.raises(ol.OutageLogError) as exc:
        ol.parse_log(text, GRAPH)
    errors = exc.value.errors
    assert len(errors) == 4
    assert [e.split(":")[0].split(" (")[0] for e in errors] == ["Row 2", "Row 3", "Row 4", "Row 5"]
    assert "before it starts" in errors[0] and "no asset" in errors[1]
    assert "isn't a date" in errors[2] and "yes/no" in errors[3]
    assert "4 rows of the outage log can't be read" in str(exc.value)


def test_missing_columns_and_empty_logs():
    with pytest.raises(ol.OutageLogError, match="Only one column"):
        ol.parse_log("asset\nPump A\n", GRAPH)
    with pytest.raises(ol.OutageLogError, match="end or a duration|when each outage ended"):
        ol.parse_log("asset,start\nPump A,1\n", GRAPH, mapping={"asset": "asset", "start": "start"})
    with pytest.raises(ol.OutageLogError, match="isn't in the log"):
        ol.parse_log("asset,start,end\nPump A,1,2\n", GRAPH, mapping={"asset": "tag", "start": "start",
                                                                       "end": "end"})
    with pytest.raises(ol.OutageLogError, match="no outages"):
        ol.parse_log("asset,start,end\n", GRAPH)


def test_overlapping_outages_of_one_asset_merge_with_a_note():
    text = "asset,start,end,reason\nPump A,100,150,trip\nPump A,140,200,seal\nPump A,300,,\nPump A,310,320,\n"
    parsed = ol.parse_log(text, GRAPH, window_end=1000)
    rows = [(r["start"], r["end"], r["reason"]) for r in parsed["rows"]]
    assert rows == [(100, 200, "trip; seal"), (300, None, "")]
    merges = [n for n in parsed["notes"] if "merged" in n]
    assert merges == ["Pump A: overlapping outages in rows 2, 3 merged into one.",
                      "Pump A: overlapping outages in rows 4, 5 merged into one."]


def test_unmapped_assets_are_listed_and_left_out():
    text = "asset,start,end\nPump A,10,20\nCompressor 9,30,40\nfan c,50,60\n"
    parsed = ol.parse_log(text, GRAPH, window_start=0, window_end=100)
    assert parsed["unmapped"] == ["Compressor 9"]
    assert parsed["asset_map"] == {"Pump A": "a", "fan c": "c"}  # labels match ignoring case
    h = ol.system_history(GRAPH, {**parsed, "_id": "x"})
    assert h["kpis"]["outages"] == 1  # Fan C alone doesn't stop the system
    assert any("unmapped assets" in n for n in h["notes"])
    # Mapped by hand (to the node id), it counts.
    remapped = ol.parse_log(text, GRAPH, window_start=0, window_end=100, asset_map={"Compressor 9": "b"})
    assert remapped["unmapped"] == [] and remapped["asset_map"]["Compressor 9"] == "b"
    with pytest.raises(ol.OutageLogError, match="isn't a block"):
        ol.parse_log(text, GRAPH, asset_map={"Compressor 9": "nope"})


# ---- fitting life and repair models from the log -------------------------------------------

def test_fit_data_censors_the_last_up_period_and_planned_stops():
    text = ("asset,start,end,planned\nPump A,100,110,no\nPump A,300,320,no\nPump A,500,510,yes\n"
            "Pump A,700,720,no\nPump A,900,,no\n")
    parsed = ol.parse_log(text, GRAPH, window_start=0, window_end=1000)
    data = ol.fit_data(GRAPH, {**parsed, "_id": "x"})
    life_x, life_c = data["a"]["life"]
    assert life_x == [100, 190, 180, 190, 180]
    assert life_c == [0, 0, 1, 0, 0]  # the up period ended by the planned stop is censored
    rep_x, rep_c = data["a"]["repair"]
    assert rep_x == [10, 20, 20, 100] and rep_c == [0, 0, 0, 1]  # planned excluded; the open one censored
    # A block that never went down: one censored life.
    assert data["b"]["life"] == ([1000], [1])


def test_fit_models_returns_block_models():
    import numpy as np

    rng = np.random.default_rng(3)
    t, rows = 0.0, []
    for _ in range(25):
        t += rng.weibull(1.5) * 80
        d = rng.lognormal(1.0, 0.4)
        rows.append(f"Pump A,{t:.3f},{t + d:.3f}")
        t += d
    parsed = ol.parse_log("asset,start,end\n" + "\n".join(rows), GRAPH, window_start=0, window_end=t + 30)
    fit = ol.fit_models(GRAPH, {**parsed, "_id": "x"})
    pump = next(c for c in fit["components"] if c["node_id"] == "a")
    assert pump["life"]["distribution_id"] == "weibull" and pump["life"]["failures"] == 25
    assert pump["life"]["model"]["source"] == "params"
    assert {p["name"] for p in pump["life"]["params"]} == {"alpha", "beta"}
    assert pump["repair"]["distribution_id"] == "lognormal"
    valve = next(c for c in fit["components"] if c["node_id"] == "b")
    assert "at least 2" in valve["life"]["error"]


# ---- REST: owner-only, samples refused, the cap -------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_outage_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    c = TestClient(app)
    c.db = test_db

    def act_as(uid):
        app.dependency_overrides[get_current_user] = lambda: {"uid": uid, "email": f"{uid}@x.com", "name": uid}

    c.act_as = act_as
    yield c
    app.dependency_overrides.clear()


def _save_rbd(client, graph=GRAPH):
    r = client.post("/api/rbds", json={"name": "Plant", "graph": graph})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_rest_import_history_edit_and_delete(client):
    client.act_as(A)
    rid = _save_rbd(client)
    base = f"/api/rbds/{rid}/outage-logs"

    pre = client.post(f"{base}/preview", json={"csv": LOG})
    assert pre.status_code == 200
    body = pre.json()
    assert body["ok"] is True and body["n_outages"] == 9
    assert body["detected"]["asset"] == "Asset" and body["unmapped"] == []
    bad = client.post(f"{base}/preview", json={"csv": "asset,start,end\nPump A,5,1\n"}).json()
    assert bad["ok"] is False and "before it starts" in bad["errors"][0]

    r = client.post(base, json={"csv": LOG, "window_start": 0, "window_end": 1000, "name": "2024 log"})
    assert r.status_code == 201, r.text
    log = r.json()
    assert log["name"] == "2024 log" and log["n_outages"] == 9
    assert log["history"]["kpis"]["availability"] == pytest.approx(0.91)

    assert [x["id"] for x in client.get(base).json()["logs"]] == [log["id"]]
    got = client.get(f"{base}/{log['id']}").json()
    assert len(got["rows"]) == 9 and {a["name"] for a in got["assets"]} >= {"Pump A", "Fan D"}

    h = client.get(f"{base}/{log['id']}/history").json()
    assert h["kpis"]["downtime"] == pytest.approx(90)

    # Move the window and re-map an asset to another block.
    r = client.patch(f"{base}/{log['id']}", json={"window_end": 980, "asset_map": {"Fan D": "c"}})
    assert r.status_code == 200, r.text
    h = client.get(f"{base}/{log['id']}/history").json()
    assert h["kpis"]["window"] == 980
    # Fan C and Fan D both on block c now: the pair never both go down.
    assert all(o["cause"] != "d" for o in h["outages"])
    assert client.patch(f"{base}/{log['id']}", json={"window_start": 2000}).status_code == 400

    fit = client.post(f"{base}/{log['id']}/fit", json={"distribution": "Weibull"})
    assert fit.status_code == 200 and fit.json()["distribution"] == "weibull"

    assert client.post(base, json={"csv": "asset,start,end\nPump A,5,1\n"}).status_code == 400
    assert client.delete(f"{base}/{log['id']}").status_code == 200
    assert client.get(base).json()["logs"] == []


def test_rest_is_owner_only(client):
    client.act_as(A)
    rid = _save_rbd(client)
    lid = client.post(f"/api/rbds/{rid}/outage-logs", json={"csv": LOG}).json()["id"]

    client.act_as(B)
    base = f"/api/rbds/{rid}/outage-logs"
    assert client.get(base).status_code == 404
    assert client.get(f"{base}/{lid}").status_code == 404
    assert client.get(f"{base}/{lid}/history").status_code == 404
    assert client.post(base, json={"csv": LOG}).status_code == 404
    assert client.delete(f"{base}/{lid}").status_code == 404
    # B's own diagram can't reach A's log either.
    other = _save_rbd(client)
    assert client.get(f"/api/rbds/{other}/outage-logs/{lid}").status_code == 404
    # Even with the diagram shared with B, the log stays A's.
    client.db.shares.insert_one({"_id": "s1", "collection": "rbds", "artifact_id": rid, "recipient_uid": B,
                                 "owner_id": A})
    assert client.get(base).status_code == 404

    client.act_as(A)
    assert client.get(f"{base}/{lid}").status_code == 200
    # Deleting the diagram deletes its logs.
    assert client.delete(f"/api/rbds/{rid}").status_code == 200
    assert client.db.outage_logs.count_documents({}) == 0


def test_rest_refuses_samples(client):
    from backend import config

    client.db.rbds.insert_one({"_id": "sample-rbd", "id": "sample-rbd", "name": "Sample",
                               "owner_id": config.SAMPLE_OWNER, "graph": GRAPH})
    client.act_as(A)
    r = client.post("/api/rbds/sample-rbd/outage-logs", json={"csv": LOG})
    assert r.status_code == 403 and r.json()["code"] == "sample"
    assert client.get("/api/rbds/sample-rbd/outage-logs").status_code == 403
    assert client.db.outage_logs.count_documents({}) == 0


def test_free_plan_cap(client, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    client.db.users.insert_one({"_id": A, "email": "a@x.com"})
    client.act_as(A)
    rid = _save_rbd(client)
    assert billing.cap_for("outage_logs", "free") == config.FREE_MAX_OUTAGE_LOGS == 1
    assert billing.cap_for("outage_logs", "agent") == config.AGENT_MAX_OUTAGE_LOGS
    assert billing.cap_for("outage_logs", "pro") is None
    assert client.post(f"/api/rbds/{rid}/outage-logs", json={"csv": LOG}).status_code == 201
    r = client.post(f"/api/rbds/{rid}/outage-logs", json={"csv": LOG})
    assert r.status_code == 402 and r.json()["code"] == "cap"
    assert "1 outage log" in r.json()["detail"]
    bill = client.get("/api/billing").json()
    assert bill["caps"]["outage_logs"] == 1 and bill["usage"]["outage_logs"] == 1
    # Pro lifts it.
    client.db.users.update_one({"_id": A}, {"$set": {"plan": "pro"}})
    assert client.post(f"/api/rbds/{rid}/outage-logs", json={"csv": LOG}).status_code == 201


def test_usage_names_the_routes():
    from backend.services.usage import app_feature

    assert app_feature("POST", "/api/rbds/r1/outage-logs") == "outage_log_upload"
    assert app_feature("POST", "/api/rbds/r1/outage-logs/preview") == "outage_log_preview"
    assert app_feature("GET", "/api/rbds/r1/outage-logs/l1/history") == "outage_history"
    assert app_feature("PATCH", "/api/rbds/r1/outage-logs/l1") == "outage_log_edit"
    assert app_feature("DELETE", "/api/rbds/r1/outage-logs/l1") == "outage_log_delete"
    assert app_feature("POST", "/api/rbds/r1/outage-logs/l1/fit") == "outage_fit"
    assert app_feature("DELETE", "/api/rbds/r1") == "rbd_delete"
