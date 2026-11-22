"""Life data typed in as text, in SurPyval's notation (backend/services/notation.py): the live reading and
save (POST /api/datasets/notation/read, /api/datasets/notation), "Show as text" (GET
/api/datasets/{id}/notation), and MCP change dataset_upload with notation (so its REST twin and the CLI).
A typed dataset is an ordinary one: its fit equals the same data uploaded as a CSV."""

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")

U = "user-notation"


@pytest.fixture()
def web(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_notation_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": U, "email": "n@example.org", "name": "N", "email_verified": True}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _params(fit):
    return [round(p["value"], 6) for p in fit["params"]]


# ---- the service --------------------------------------------------------------

def test_lives_read_as_the_csv_a_spreadsheet_would_be():
    from backend.services import notation

    out = notation.read("120, 310, [400, 450], 1000+, 1500+", "hours")
    assert out["kind"] == "lives" and out["n_rows"] == 5
    assert out["summary"] == "5 units: 2 failed, 1 in a window 400–450, 2 still running (1,000 to 1,500)"
    assert out["csv"] == "xl,xr,c\n120,120,0\n310,310,0\n400,450,2\n1000,1000,1\n1500,1500,1\n"
    assert out["reading"] == {"xl": "xl", "xr": "xr", "c": "c", "unit": "hours"}
    plain = notation.read("1240.5, 980, 3*1500, 2100+", "cycles")
    assert plain["csv"] == "x,c,n\n1240.5,0,1\n980,0,1\n1500,0,3\n2100,1,1\n"
    assert plain["summary"] == "6 units: 5 failed, 1 still running at 2,100"
    left = notation.read("<50, 60-, 80 | (20, inf]", "h")
    assert left["csv"] == "x,c,tl\n50,-1,\n60,-1,\n80,0,20\n"
    assert left["counts"]["failed_before"] == 2 and left["counts"]["observed_in_window"] == 1


def test_the_reading_rounds_times_to_four_figures_but_saves_them_in_full():
    from backend.services import notation

    out = notation.read("1240.5, 0.01234, 12345.6+", "hours")
    assert out["summary"] == "3 units: 2 failed, 1 still running at 12,350"
    assert out["csv"] == "x,c\n1240.5,0\n0.01234,0\n12345.6,1\n"
    assert notation.read("[1240.5, 1300]", "h")["summary"] == "1 unit: 1 in a window 1,240–1,300"


def test_histories_are_one_row_per_event_with_the_item():
    from backend.services import notation

    out = notation.read("P1: 120, 310, 1000+\nP2: 2*200, 900 | (100, inf]", "hours")
    assert out["kind"] == "histories"
    assert out["csv"] == "i,x,c,tl\nP1,120,0,\nP1,310,0,\nP1,1000,1,\nP2,200,0,100\nP2,200,0,\nP2,900,0,\n"
    assert out["reading"]["i"] == "i"
    assert out["summary"].startswith("2 units' histories: 5 failures")


@pytest.mark.parametrize("text, where, words", [
    ("", None, "Nothing to read yet"),
    ("   \n ", None, "Nothing to read yet"),
    ("10, abc, 30", {"entry": "abc", "line": 1, "column": 5}, "Can't read 'abc'"),
    ("10,\n[450, 400]", {"entry": "[450, 400]", "line": 2, "column": 1}, "must be below its end"),
    ("5, 20+ | (30, 40]", {"entry": "20+ | (30, 40]", "line": 1}, "outside its observation window"),
    ("P1: 10, 20+\n30, 40", {"entry": "30, 40", "line": 2}, "has no unit id"),
    ("P1: 10\nP1: 20", None, "must differ"),
])
def test_text_that_cant_be_read_says_where_and_what_to_write(text, where, words):
    from backend.services import notation

    with pytest.raises(notation.NotationError) as err:
        notation.read(text, "hours")
    assert words in str(err.value)
    got = err.value.payload()
    for key, value in (where or {}).items():
        assert got[key] == value, (key, got)


# ---- the web routes -------------------------------------------------------------

def test_typed_text_saves_a_dataset_whose_fit_equals_the_csvs(web):
    typed = "120, 310, 450, 3*620, 800, 1000+, 1200+"
    live = web.post("/api/datasets/notation/read", json={"text": typed, "unit": "hours"})
    assert live.status_code == 200 and live.json()["summary"].startswith("9 units: 7 failed")
    # Mid-typing, text that can't be read is an answer saying where (not a failed request).
    bad = web.post("/api/datasets/notation/read", json={"text": "120, 31O"})
    assert bad.status_code == 200 and bad.json()["where"]["entry"] == "31O" and "Entry 2" in bad.json()["error"]
    made = web.post("/api/datasets/notation", json={"name": "Seals", "text": typed, "unit": "hours"})
    assert made.status_code == 200, made.text
    ds = made.json()
    assert ds["name"] == "Seals" and [c["name"] for c in ds["columns"]] == ["x", "c", "n"]
    csv = "x,c,n\n120,0,1\n310,0,1\n450,0,1\n620,0,3\n800,0,1\n1000,1,1\n1200,1,1\n"
    up = web.post("/api/datasets", files={"file": ("seals.csv", csv.encode(), "text/csv")},
                  data={"name": "Seals CSV"}).json()
    form = {"x": "x", "c": "c", "n": "n"}
    a = web.post("/api/fit/weibull", data={"dataset_id": ds["id"], **form}).json()
    b = web.post("/api/fit/weibull", data={"dataset_id": up["id"], **form}).json()
    assert _params(a) == _params(b) and len(_params(a)) == 2
    # The reading was saved with it: the dataset reads as typed, not guessed.
    got = web.get(f"/api/datasets/{ds['id']}").json()
    assert got["reading"]["x"] == "x" and got["reading"]["unit"] == "hours"
    assert got["reading_source"] == "saved"


def test_windows_and_truncation_fit_the_same_as_the_csv(web):
    typed = "[100, 200], 250, 300 | (50, inf], <80, 900+, 400"
    ds = web.post("/api/datasets/notation", json={"name": "Inspections", "text": typed, "unit": "hours"}).json()
    csv = "xl,xr,c,tl\n100,200,2,\n250,250,0,\n300,300,0,50\n80,80,-1,\n900,900,1,\n400,400,0,\n"
    up = web.post("/api/datasets", files={"file": ("i.csv", csv.encode(), "text/csv")},
                  data={"name": "Inspections CSV"}).json()
    form = {"xl": "xl", "xr": "xr", "c": "c", "tl": "tl"}
    a = web.post("/api/fit/weibull", data={"dataset_id": ds["id"], **form}).json()
    b = web.post("/api/fit/weibull", data={"dataset_id": up["id"], **form}).json()
    assert "params" in a, a
    assert _params(a) == _params(b)


def test_save_needs_a_name_a_unit_and_readable_text(web):
    r = web.post("/api/datasets/notation", json={"name": "", "text": "10, 20", "unit": "hours"})
    assert r.status_code == 422 and "name" in r.json()["detail"]
    r = web.post("/api/datasets/notation", json={"name": "A", "text": "10, 20", "unit": " "})
    assert r.status_code == 422 and "unit" in r.json()["detail"]
    r = web.post("/api/datasets/notation", json={"name": "A", "text": "10, [5, x]", "unit": "hours"})
    assert r.status_code == 422 and r.json()["where"]["entry"] == "[5, x]"


def test_show_as_text_round_trips(web):
    typed = "3*10, 20+, <3, [5, 10] | (0, 40]"
    ds = web.post("/api/datasets/notation", json={"name": "Mixed", "text": typed, "unit": "hours"}).json()
    out = web.get(f"/api/datasets/{ds['id']}/notation")
    assert out.status_code == 200, out.text
    body = out.json()
    from surpyval import SurpyvalData

    assert SurpyvalData.from_notation(body["text"]).to_notation() == SurpyvalData.from_notation(typed).to_notation()
    assert body["unit"] == "hours" and body["kind"] == "lives"
    # A CSV of words and a status column read through its reading.
    csv = "hours,status\n120,Failed\n340,Failed\n510,Running\n"
    up = web.post("/api/datasets", files={"file": ("b.csv", csv.encode(), "text/csv")},
                  data={"name": "Words", "reading": '{"x": "hours", "c": "status", "c_map": {"Failed": 0, '
                                                    '"Running": 1}, "unit": "hours"}'}).json()
    assert web.get(f"/api/datasets/{up['id']}/notation").json()["text"] == "120, 340, 510+"
    hist = web.post("/api/datasets/notation", json={"name": "Pumps", "text": "P1: 120, 310, 1000+\nP2: 50, 400+",
                                                    "unit": "hours"}).json()
    got = web.get(f"/api/datasets/{hist['id']}/notation").json()
    assert got["kind"] == "histories" and got["text"].splitlines() == ["P1: 120, 310, 1000+", "P2: 50, 400+"]


def test_show_as_text_refuses_big_or_covariate_data_in_words(web):
    big = "\n".join(["h"] + [str(100 + k) for k in range(201)])
    up = web.post("/api/datasets", files={"file": ("big.csv", big.encode(), "text/csv")},
                  data={"name": "Big", "reading": '{"x": "h", "all_failed": true, "unit": "hours"}'}).json()
    r = web.get(f"/api/datasets/{up['id']}/notation")
    assert r.status_code == 422 and "201 rows" in r.json()["detail"]
    cov = "h,c,load\n100,0,1\n200,1,2\n"
    up = web.post("/api/datasets", files={"file": ("cov.csv", cov.encode(), "text/csv")},
                  data={"name": "Cov", "reading": '{"x": "h", "c": "c", "z": ["load"], "unit": "hours"}'}).json()
    r = web.get(f"/api/datasets/{up['id']}/notation")
    assert r.status_code == 422 and "covariates" in r.json()["detail"]


# ---- MCP (and so REST and the CLI) -----------------------------------------------

def test_mcp_dataset_upload_takes_notation(env):
    out = _ok(_call(env.token[A], "change", {"action": "dataset_upload", "name": "Typed seals",
                                             "notation": "120, 310, [400, 450], 1000+", "unit": "hours"}))
    assert out["read_as"] == "4 units: 2 failed, 1 in a window 400–450, 1 still running at 1,000"
    assert out["columns"] == ["xl", "xr", "c"] and out["reading"]["source"] == "saved"
    fit = _ok(_call(env.token[A], "analyse", {"action": "fit", "dataset_id": out["id"], "distribution": "weibull",
                                              "unit": "hours"}))
    assert fit["censoring"]["n_right_censored"] == 1
    msg = _err(_call(env.token[A], "change", {"action": "dataset_upload", "name": "No unit", "notation": "10, 20"}))
    assert "unit" in msg
    msg = _err(_call(env.token[A], "change", {"action": "dataset_upload", "name": "Both", "notation": "10, 20",
                                              "csv": "x\n1\n", "unit": "hours"}))
    assert "on its own" in msg
    msg = _err(_call(env.token[A], "change", {"action": "dataset_upload", "name": "Bad", "notation": "10, 2O",
                                              "unit": "hours"}))
    assert "Entry 2" in msg and "'2O'" in msg


def test_show_as_text_reads_a_flag_the_other_way_round_or_no_flag():
    import pandas as pd

    from backend.services import notation

    df = pd.DataFrame({"h": [10, 20, 30], "f": [1, 1, 0]})
    assert notation.dataset_text(df, {"x": "h", "c": "f", "c_invert": True})["text"] == "10, 20, 30+"
    assert notation.dataset_text(df, {"x": "h", "all_failed": True})["text"] == "10, 20, 30"
