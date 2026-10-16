"""First run (#434): a file with no header row is detected and kept whole, a
column of decimals can't be fitted as counts, and the REST and MCP paths say
what they guessed in one line."""

import io

import mongomock
import pytest

from backend import fitting
from backend.services import datasets as datasets_service

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}

# The upload that started it: no header, so "300" and "544966.3125" became
# the column names and the first row was lost.
HEADERLESS = b"300,544966.3125\n410,612000.5\n520,701234.25\n655,802000.75\n"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_first_run"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _csv(data=HEADERLESS, name="raw.csv"):
    return {"file": (name, data, "text/csv")}


# ---- the guess -------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("300,544966.3125\n1,2\n", True),
    ("﻿1.5;2e3\n", True),          # a byte-order mark, scientific notation
    ("  12 , -4 \n", True),
    ("hours,cost\n1,2\n", False),
    ("300,cost\n", False),              # one name is enough to be a header
    ("300,,5\n", False),                # a blank cell isn't a number
    ("\n\n7\n8\n", True),               # blank lines before the first row
    ("", False),
])
def test_first_row_is_data(text, expected):
    sep = ";" if ";" in text else ","
    assert fitting.first_row_is_data(text, sep) is expected


def test_header_guess_is_a_row_number():
    assert fitting.header_guess(HEADERLESS) == 0
    assert fitting.header_guess(b"hours,failed\n1,0\n") == 1


def test_pasted_guess_uses_the_paste_delimiter():
    assert datasets_service.pasted_header_guess("300\t544966.3125\n1\t2") == 0
    assert datasets_service.pasted_header_guess("hours\tfailed\n1\t0") == 1


# ---- CSV upload ------------------------------------------------------------------------------

def test_headerless_csv_upload_keeps_every_row_and_says_so(client):
    r = client.post("/api/datasets", files=_csv())
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["col 1", "col 2"]
    assert body["n_rows"] == 4  # the first row is data, not names
    assert body["preview"][0] == [300, 544966.3125]
    assert body["header_guess"] == 0
    assert body["hint"] == fitting.HEADER_HINT and "no_header=false" in body["hint"]


def test_no_header_false_keeps_the_numbers_as_names(client):
    r = client.post("/api/datasets", files=_csv(), data={"no_header": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["300", "544966.3125"]
    assert body["n_rows"] == 3 and body["header_guess"] == 0 and "hint" not in body


def test_a_named_header_is_left_alone(client):
    r = client.post("/api/datasets", files=_csv(b"hours,failed\n1,0\n2,1\n"))
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["hours", "failed"]
    assert body["header_guess"] == 1 and "hint" not in body


def test_explicit_no_header_needs_no_hint(client):
    r = client.post("/api/datasets", files=_csv(), data={"no_header": "true"})
    body = r.json()
    assert body["n_rows"] == 4 and "hint" not in body


# ---- paste -----------------------------------------------------------------------------------

def test_headerless_paste_is_detected(client):
    r = client.post("/api/datasets/paste", json={"name": "Pumps", "content": "300\t544966.3125\n410\t612000.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["col 1", "col 2"]
    assert body["n_rows"] == 2 and body["header_guess"] == 0 and body["hint"] == fitting.HEADER_HINT


def test_headerless_paste_with_repeated_first_values_keeps_them(client):
    # pandas would rename a repeated header ("1", "1.1"): read as data, it stays 1, 1.
    r = client.post("/api/datasets/paste", json={"name": "Ones", "content": "1,1\n3,4", "no_header": True})
    assert r.json()["preview"][0] == [1, 1]


def test_paste_with_a_header_is_unchanged(client):
    r = client.post("/api/datasets/paste", json={"name": "B", "content": "hours,failed\n1240,1\n980,1"})
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["hours", "failed"] and "hint" not in body


# ---- Excel -----------------------------------------------------------------------------------

def _xlsx(rows):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_headerless_sheet_is_guessed_and_said(client):
    book = _xlsx([[300, 544966.3125], [410, 612000.5], [520, 701234.25]])
    inspected = client.post("/api/excel/inspect", files={"file": ("b.xlsx", book, XLSX)}).json()
    assert inspected["sheets"][0]["guessed_header_row"] == 0

    r = client.post("/api/datasets", files={"file": ("b.xlsx", book, XLSX)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["col 1", "col 2"] and body["n_rows"] == 3
    assert body["header_guess"] == 0 and body["hint"] == fitting.SHEET_HEADER_HINT

    # A chosen header row is the user's call: no hint.
    r = client.post("/api/datasets", files={"file": ("b.xlsx", book, XLSX)}, data={"header_row": "1"})
    assert [c["name"] for c in r.json()["columns"]] == ["300", "544966.3125"] and "hint" not in r.json()


# ---- /api/columns ----------------------------------------------------------------------------

def test_columns_reports_the_guess_and_a_hint(client):
    body = client.post("/api/columns", files=_csv()).json()
    # A preview reads the file as the fit will: the guess is reported, not applied.
    assert body["columns"] == ["300", "544966.3125"]
    assert body["header_guess"] == 0 and body["hint"] == fitting.HEADER_PREVIEW_HINT

    body = client.post("/api/columns", files=_csv(), data={"no_header": "true"}).json()
    assert body["columns"] == ["col 1", "col 2"] and body["n_rows"] == 4 and "hint" not in body

    body = client.post("/api/columns", files=_csv(b"hours,failed\n1,0\n")).json()
    assert body["header_guess"] == 1 and "hint" not in body


def test_columns_says_which_columns_hold_whole_numbers(client):
    body = client.post("/api/columns", files=_csv(b"t,n,cost,id\n1,2,3.5,a\n2,,4.0,b\n")).json()
    assert body["whole"] == [True, True, False, None]


def test_dataset_detail_carries_whole(client):
    ds = client.post("/api/datasets", files=_csv(b"t,n\n1.5,2\n2.5,3\n")).json()
    assert client.get(f"/api/datasets/{ds['id']}").json()["whole"] == [False, True]


# ---- counts ----------------------------------------------------------------------------------

def test_decimal_count_column_is_refused_in_words(client):
    r = client.post("/api/fit/weibull", files=_csv(b"t,usage\n300,544966.3125\n410,612000.5\n520,7\n"),
                    data={"x": "t", "n": "usage"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "“usage” holds decimals (e.g. 544966.3125)" in detail and "whole numbers" in detail
    assert "Count array" not in detail


def test_whole_number_counts_still_fit(client):
    r = client.post("/api/fit/weibull", files=_csv(b"t,n\n100,2\n200,3.0\n300,1\n400,2\n"),
                    data={"x": "t", "n": "n"})
    assert r.status_code == 200, r.text


# ---- one click saves the model and its data --------------------------------------------------

def test_saving_a_fit_from_an_upload_saves_its_dataset(client):
    data = b"col 1,col 2\n300,544966.3125\n410,612000.5\n520,701234.25\n655,802000.75\n"
    r = client.post("/api/models", files=_csv(data, "raw.csv"),
                    data={"name": "Weibull — raw", "distribution": "weibull", "x": "col 1"})
    assert r.status_code == 200, r.text
    model = r.json()
    ds = client.get(f"/api/datasets/{model['dataset_id']}").json()
    assert ds["n_rows"] == 4 and [c["name"] for c in ds["columns"]] == ["col 1", "col 2"]
