"""A status column of words is read with the ``c_map`` option (#291).

CMMS exports mark each unit "Failed" or "Running" (or "F" / "S", "yes" /
"no"). Mapped as the censor column, those words reached SurPyval as NaN and the
fit failed with "Variable 'c' cannot contain NaN values". The Data step now
sends ``c_map`` ({word: 0 | 1}); the server swaps the words for codes before
fitting and stores the map with the fit options so a saved model re-fits the
same way. ``preview`` gives the Data step each column's few values to map.
"""

import io

import pandas as pd
import pytest

from backend import fitting
from backend.fitting import FitError, failure_count, map_censor_column, options_from_form

_CSV = (
    "Pump ID,Operating Hours,Status\n"
    "P-1,1200,Failed\nP-2,2300,failed \nP-3,3100,Running\nP-4,800,Failed\n"
    "P-5,4100,Running\nP-6,1900,Failed\nP-7,2600,Failed\n"
)
_MAPPING = {"x": "Operating Hours", "c": "Status"}
_MAP = {"Failed": 0, "Running": 1}


def _df(csv=_CSV):
    return pd.read_csv(io.StringIO(csv))


def test_words_become_codes_case_and_space_insensitive():
    out = map_censor_column(_df(), "Status", _MAP)
    assert out["Status"].tolist() == [0, 0, 1, 0, 1, 0, 0]
    kwargs = fitting.build_fit_inputs(out, _MAPPING)
    assert failure_count(kwargs) == (5, 7)


def test_fit_with_a_map_matches_the_coded_file_and_is_stored():
    r = fitting.fit("weibull", _df(), _MAPPING, options={"c_map": _MAP})
    coded = _df().assign(Status=[0, 0, 1, 0, 1, 0, 0])
    ref = fitting.fit("weibull", coded, _MAPPING)
    assert [p["value"] for p in r["params"]] == pytest.approx([p["value"] for p in ref["params"]])
    assert r["options"]["c_map"] == _MAP


def test_the_map_replaces_invert():
    # The map already says which way round: c_invert alongside it is ignored.
    r = fitting.fit("weibull", _df(), _MAPPING, options={"c_map": _MAP, "c_invert": True})
    assert "c_invert" not in (r.get("options") or {})


def test_numbers_and_booleans_match_their_labels():
    df = pd.DataFrame({"t": [1.0, 2.0, 3.0], "c": [1.0, 0.0, 1.0]})
    assert map_censor_column(df, "c", {"1": 0, "0": 1})["c"].tolist() == [0, 1, 0]
    df = pd.DataFrame({"t": [1, 2], "failed": [True, False]})
    assert map_censor_column(df, "failed", {"True": 0, "False": 1})["failed"].tolist() == [0, 1]


def test_an_unmapped_word_is_refused_in_plain_words():
    with pytest.raises(FitError, match=r"Say whether .*'Status'.*: Running"):
        map_censor_column(_df(), "Status", {"Failed": 0})


def test_a_blank_status_is_refused_in_plain_words():
    df = _df(_CSV + "P-8,500,\n")
    with pytest.raises(FitError, match="1 row has no value in 'Status'"):
        fitting.fit("weibull", df, _MAPPING, options={"c_map": _MAP})


def test_a_code_other_than_failed_or_running_is_refused():
    with pytest.raises(FitError, match="must mean failed"):
        map_censor_column(_df(), "Status", {"Failed": 0, "Running": 7})


def test_the_form_field_is_json():
    assert options_from_form(c_map='{"F": 0, "S": 1}') == {
        "offset": False, "zi": False, "lfp": False, "c_map": {"F": 0, "S": 1}}
    for bad in ["nope", "[]", "{}"]:
        with pytest.raises(FitError, match="c_map must be a JSON object"):
            options_from_form(c_map=bad)


def test_without_a_censor_column_the_map_is_dropped():
    r = fitting.fit("weibull", _df(), {"x": "Operating Hours"}, options={"c_map": _MAP})
    assert "c_map" not in (r.get("options") or {})


def test_preview_gives_types_blanks_and_few_values():
    csv = _CSV + "P-8,,Running\n"
    p = fitting.preview(csv.encode(), distinct=True)
    by = dict(zip(p["columns"], range(len(p["columns"]))))
    assert p["values"][by["Status"]] == {"Failed": 4, "Running": 3, "failed": 1}
    assert p["values"][by["Pump ID"]] == {f"P-{i}": 1 for i in range(1, 9)}
    assert p["blanks"][by["Operating Hours"]] == 1
    assert p["dtypes"][by["Operating Hours"]].startswith("float")
    # Whole numbers read as "1", not "1.0", even in a float column.
    p = fitting.preview(b"t,c\n1,1\n2,\n3,0\n", distinct=True)
    assert p["values"][1] == {"1": 1, "0": 1}
    # Many distinct values: no list.
    many = "t\n" + "\n".join(str(i) for i in range(20)) + "\n"
    assert fitting.preview(many.encode(), distinct=True)["values"] == [None]


# ---- API round trip ---------------------------------------------------------

OWNER = "user-a"


@pytest.fixture()
def client(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": OWNER, "email": "a@example.com", "name": "A"}
    tc = TestClient(app)
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _upload():
    return {"file": ("pumps.csv", io.BytesIO(_CSV.encode()), "text/csv")}


def test_c_map_travels_through_fit_save_refit_and_the_dataset(client):
    import json

    form = {"x": "Operating Hours", "c": "Status"}

    # The Data step gets the status words to map.
    cols = client.post("/api/columns", files=_upload()).json()
    assert cols["values"][2] == {"Failed": 4, "Running": 2, "failed": 1}
    assert cols["dtypes"][1].startswith("int")

    fit = client.post("/api/fit/weibull", data={**form, "c_map": json.dumps(_MAP)}, files=_upload())
    assert fit.status_code == 200, fit.text
    assert fit.json()["options"] == {"c_map": _MAP}

    saved = client.post(
        "/api/models",
        data={"name": "Pumps", "distribution": "weibull", **form, "c_map": json.dumps(_MAP)},
        files=_upload(),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["spec"]["options"] == {"c_map": _MAP}

    refit = client.put(f"/api/models/{body['id']}/fit",
                       json={"distribution": "weibull", "mapping": form, "c_map": _MAP})
    assert refit.status_code == 200, refit.text
    assert refit.json()["results"]["params"] == body["results"]["params"]

    detail = client.get(f"/api/datasets/{body['dataset_id']}").json()
    assert detail["values"][2] == {"Failed": 4, "Running": 2, "failed": 1}
    assert detail["blanks"] == [0, 0, 0]

    # The saved dataset fits by id with the same map.
    by_id = client.post("/api/fit/weibull",
                        data={**form, "dataset_id": body["dataset_id"], "c_map": json.dumps(_MAP)})
    assert by_id.status_code == 200, by_id.text
