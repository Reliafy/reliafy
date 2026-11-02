"""Bad uploads get plain messages that say what to do, never a parser's raw
error ("'utf-8' codec can't decode…", "Error tokenizing data. C error…").
The raw error is logged on the server instead."""

import io
import logging
import zipfile

import mongomock
import pytest

from backend import fitting
from backend.fitting import FitError

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n"
LATIN1 = "hours,site\n100,Montréal\n250,Malmö\n".encode("latin-1")
UTF16 = "hours,failed\n100,0\n".encode("utf-16")
UNCLOSED = b'hours,note\n100,"bent shaft\n200,ok\n300,ok\n'
RAGGED = b"hours,failed\n100,0\n200,0,extra,cells\n300,1\n"
EMPTY = b""
BLANK = b"\n\n  \n"
RAW_BITS = ("codec", "Error tokenizing", "C error", "EOF inside string", "invalid start byte",
            "No columns to parse", "Traceback")


def _corrupt_xlsx() -> bytes:
    """A zip that claims to be a workbook but has no workbook inside."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "not a workbook")
    return buf.getvalue()


def _plain(message: str) -> None:
    for bit in RAW_BITS:
        assert bit not in message, message


def _message(data: bytes) -> str:
    with pytest.raises(FitError) as exc:
        fitting.read_dataframe(data)
    _plain(str(exc.value))
    return str(exc.value)


def test_binary_files_say_what_they_are_and_what_to_do():
    assert _message(PNG) == ("This looks like a PNG image, not a CSV file. "
                             "Save it as CSV UTF-8 (comma delimited) and upload it again.")
    assert "a PDF, not a CSV file" in _message(PDF)
    assert "Excel workbook" in _message(_corrupt_xlsx())
    assert "UTF-16" in _message(UTF16)


def test_latin1_text_is_read_not_refused():
    df = fitting.read_dataframe(LATIN1)
    assert list(df["site"]) == ["Montréal", "Malmö"]


def test_unclosed_quote_names_the_line():
    assert _message(UNCLOSED) == ('Line 2 has a quote mark (") that is never closed. Close it, or remove it, '
                                  "and upload it again.")


def test_ragged_rows_name_the_line_and_the_counts():
    msg = _message(RAGGED)
    assert msg.startswith("Line 3 has 4 values but the header has 2 columns.")


@pytest.mark.parametrize("data", [EMPTY, BLANK])
def test_empty_files(data):
    msg = _message(data)
    assert "empty" in msg and "header row" in msg


def test_the_raw_error_is_logged(caplog):
    caplog.set_level(logging.WARNING, logger="backend.fitting")
    _message(UNCLOSED)
    assert any("EOF inside string" in r.getMessage() for r in caplog.records)


def test_csv_error_message_for_the_python_engine():
    # The paste path uses pandas' python engine, whose unclosed-quote error has no line.
    import pandas as pd

    text = 'hours\tnote\n100\tok\n200\t"oops\n'
    with pytest.raises(Exception) as exc:
        pd.read_csv(io.StringIO(text), sep="\t", engine="python")
    msg = fitting.csv_error_message(exc.value, text, what="the pasted data")
    assert msg.startswith("Line 3 has a quote mark")


# ---- through the HTTP routes ---------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_upload_errors"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _detail(r) -> str:
    body = r.json()
    detail = body.get("detail")
    return detail if isinstance(detail, str) else str(detail)


@pytest.mark.parametrize("data,expect", [
    (PNG, "PNG image"),
    (UNCLOSED, "never closed"),
    (RAGGED, "Line 3 has 4 values"),
    (EMPTY, "empty"),
])
def test_columns_route_gives_plain_messages(client, data, expect):
    r = client.post("/api/columns", files={"file": ("bad.csv", data, "text/csv")})
    assert r.status_code in (400, 422), r.text
    assert expect in _detail(r)
    _plain(_detail(r))


def test_fit_route_gives_plain_messages(client):
    r = client.post("/api/fit/weibull", files={"file": ("bad.csv", PNG, "text/csv")},
                    data={"mapping": '{"x": "hours"}'})
    assert r.status_code in (400, 422), r.text
    _plain(_detail(r))


def test_paste_route_gives_plain_messages(client):
    r = client.post("/api/datasets/paste", json={"name": "x", "content": 'hours,note\n100,"oops\n200,ok'})
    if r.status_code >= 400:
        _plain(_detail(r))


def test_ingest_csv_body_is_plain():
    from backend.services.ingest import IngestError, _read_csv_body

    with pytest.raises(IngestError) as exc:
        _read_csv_body(PNG)
    assert "PNG image" in str(exc.value)
    with pytest.raises(IngestError) as exc:
        _read_csv_body(UNCLOSED)
    assert "never closed" in str(exc.value)


def test_outage_log_is_plain():
    from backend.services.outage_logs import OutageLogError, read_table

    try:
        read_table('asset,start,note\nP1,2024-01-01,"oops\nP2,2024-02-01,ok')
    except OutageLogError as exc:
        _plain(str(exc))


def test_upload_inspect_is_plain():
    from backend.services.uploads import _inspect_text

    out = _inspect_text(b'a,b\n1,"2\n3,4\n5,6,7,8\n')
    _plain(str(out.get("note", "")))
