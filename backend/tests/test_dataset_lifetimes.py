"""The dataset page's Lifetimes view: one line per unit, read with the
dataset's reading the way a fit reads it, and matching SurPyval's own
``SurpyvalData`` (what ``plot_lifetimes`` draws) row for row."""

import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from surpyval import SurpyvalData

from backend.services import lifetimes as L

U = "user-lifetimes"


def _mixed() -> pd.DataFrame:
    # Failed, still running, found failed at the first look, failed in a
    # window, entered late, and a row standing for three units.
    return pd.DataFrame({
        "lo": [None, None, None, 40, None, None],
        "hi": [None, None, 25, 60, None, None],
        "age": [100, 150, None, None, 80, 120],
        "status": [0, 1, -1, 2, 0, 1],
        "entry": [None, None, None, None, 30, None],
        "count": [1, 1, 1, 1, 1, 3],
    })


def test_lines_match_surpyval_data_for_mixed_censoring():
    df = _mixed()
    reading = {"x": "age", "xl": "lo", "xr": "hi", "c": "status", "tl": "entry", "n": "count"}
    out = L.for_frame(df, reading)
    # The same rows given to SurPyval by hand.
    data = SurpyvalData(xl=[100, 150, 25, 40, 80, 120], xr=[100, 150, 25, 60, 80, 120], c=[0, 1, -1, 2, 0, 1],
                        n=[1, 1, 1, 1, 1, 3], tl=[-np.inf, -np.inf, -np.inf, -np.inf, 30, -np.inf],
                        group_and_sort=False)
    x = np.asarray(data.x, dtype=float)
    assert out["mode"] == "rows" and len(out["lines"]) == len(data.c)
    kinds = {0: "failed", 1: "running", -1: "before", 2: "window"}
    for line, xs, c, n, t in zip(out["lines"], x, data.c, data.n, data.t):
        (mark,) = line["marks"]
        assert mark["kind"] == kinds[int(c)]
        assert mark["at"] == pytest.approx(xs[1])
        if mark["kind"] == "window":
            assert mark["from"] == pytest.approx(xs[0])
        assert line["n"] == int(n)
        assert line["entered"] == (float(t[0]) if np.isfinite(t[0]) else None)
    assert [line["rows"] for line in out["lines"]] == [[1], [2], [3], [4], [5], [6]]
    s = out["summary"]
    assert (s["units"], s["failed"], s["running"], s["before"], s["window"], s["late"]) == (8, 2, 4, 1, 1, 1)


def test_lines_of_reads_a_surpyval_data_as_plot_lifetimes_does():
    data = SurpyvalData([3, 7, 9], c=[0, 1, 0], tl=[0, 2, 1], group_and_sort=False)
    lines = L.lines_of(data)["lines"]
    assert [(ln["start"], ln["end"], ln["entered"]) for ln in lines] == [(0, 3, None), (2, 7, 2), (1, 9, 1)]
    assert [ln["marks"][0]["kind"] for ln in lines] == ["failed", "running", "failed"]


def test_a_status_read_backwards_shows_as_the_fit_reads_it():
    df = pd.DataFrame({"hours": [10, 20, 30, 40], "failed": [1, 1, 0, 1]})
    plain = L.for_frame(df, {"x": "hours", "c": "failed"})["summary"]
    flipped = L.for_frame(df, {"x": "hours", "c": "failed", "c_invert": True})["summary"]
    assert (plain["failed"], plain["running"]) == (1, 3)
    assert (flipped["failed"], flipped["running"]) == (3, 1)
    words = pd.DataFrame({"hours": [10, 20], "state": ["Failed", "Running"]})
    mapped = L.for_frame(words, {"x": "hours", "c": "state", "c_map": {"Failed": 0, "Running": 1}})["summary"]
    assert (mapped["failed"], mapped["running"]) == (1, 1)


def test_repairable_systems_get_one_line_each_with_their_events():
    df = pd.DataFrame({"sys": ["A", "A", "B", "A"], "t": [10, 25, 7, 40]})
    out = L.for_frame(df, {"x": "t", "i": "sys", "record_end": 50}, repairable=True)
    assert out["mode"] == "repairable"
    by = {ln["id"]: ln for ln in out["lines"]}
    assert [m["at"] for m in by["A"]["marks"] if m["kind"] == "failed"] == [10, 25, 40]
    assert by["A"]["end"] == 50 and [m["at"] for m in by["A"]["marks"] if m["kind"] == "bound"] == [50]
    assert out["summary"]["units"] == 2 and out["summary"]["events"] == 4


def test_one_stream_is_one_line():
    df = pd.DataFrame({"fleet_hours": [100, 250, 400]})
    out = L.for_frame(df, {"x": "fleet_hours", "all_failed": True, "one_stream": True})
    assert out["mode"] == "repairable" and len(out["lines"]) == 1 and out["summary"]["events"] == 3


def test_start_and_stop_rows_share_an_item_line():
    df = pd.DataFrame({"id": [1, 1, 2], "a": [0, 10, 0], "b": [10, 25, 30], "c": [1, 0, 1]})
    out = L.for_frame(df, {"xl": "a", "xr": "b", "i": "id", "c": "c"})
    by = {ln["id"]: ln for ln in out["lines"]}
    assert [m["kind"] for m in by["1"]["marks"]] == ["step", "failed"]
    assert out["summary"]["units"] == 2 and out["summary"]["failed"] == 1 and out["summary"]["running"] == 1


def test_many_units_are_sampled_evenly_and_counted_in_full():
    df = pd.DataFrame({"t": np.arange(1, 1201), "c": [0, 1] * 600})
    out = L.for_frame(df, {"x": "t", "c": "c"}, limit=100)
    assert out["sampled"] and out["total"] == 1200 and len(out["lines"]) == 100
    assert out["summary"]["units"] == 1200
    ends = [ln["end"] for ln in out["lines"]]
    assert ends[0] == 1 and ends[-1] == 1200


def test_no_time_column_says_what_to_give():
    with pytest.raises(L.LifetimesError, match="x"):
        L.for_frame(pd.DataFrame({"a": [1]}), {"c": "a"})


@pytest.fixture()
def web(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_lifetimes_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": U, "email": "l@example.org", "name": "L", "email_verified": True}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_dataset_route_uses_its_reading_and_a_draft_changes_nothing(web):
    csv = "hours,failed\n10,1\n20,1\n30,0\n40,1\n"
    reading = {"x": "hours", "c": "failed", "unit": "Hours"}
    d = web.post("/api/datasets/paste", json={"name": "Pumps", "content": csv, "reading": reading}).json()
    res = web.get(f"/api/datasets/{d['id']}/lifetimes")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "saved" and body["summary"]["failed"] == 1 and body["unit"] == "Hours"
    draft = web.post(f"/api/datasets/{d['id']}/lifetimes", json={"reading": {**reading, "c_invert": True}})
    assert draft.status_code == 200 and draft.json()["summary"]["failed"] == 3
    assert draft.json()["source"] == "draft"
    # Nothing was kept.
    assert web.get(f"/api/datasets/{d['id']}/lifetimes").json()["summary"]["failed"] == 1
    # A reading the rows can't take says why, in place of the lines.
    bad = web.post(f"/api/datasets/{d['id']}/lifetimes", json={"reading": {"x": "hours", "c": "nope"}})
    assert bad.status_code == 422
    assert web.get("/api/datasets/missing/lifetimes").status_code == 404


def test_a_blank_failure_mode_is_still_running_as_the_count_reads_it():
    df = pd.DataFrame({"hours": [10, 20, 30], "mode": ["wear", None, "seal"]})
    s = L.for_frame(df, {"x": "hours", "e": "mode", "all_failed": True})["summary"]
    assert (s["failed"], s["running"]) == (2, 1)
    words = pd.DataFrame({"hours": [10, 20], "state": ["Failed", "Still running"]})
    s = L.for_frame(words, {"x": "hours", "c": "state"})["summary"]
    assert (s["failed"], s["running"]) == (1, 1)
