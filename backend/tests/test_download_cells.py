"""CSV files people download keep text as text in a spreadsheet: a cell that
starts like a formula gets a leading ', while numbers, plain text and the
CSV the app reads back itself are unchanged."""

import csv
import io

import pytest

from backend.services import excel, rbd_runs


@pytest.mark.parametrize("text", ["=SUM(A1:A2)", "+2+3", "-2+3", "@SUM(1+1)", "\t=1", "\r=1",
                                  "=A1|' x'!B2", '=CONCAT("a",A1)', "-", "+"])
def test_text_starting_like_a_formula_gets_a_quote(text):
    assert excel.download_cell(text) == "'" + text


@pytest.mark.parametrize("value", ["Pump A", "", " =1", "a=b", "-2.5", "+1e3", "-.5", "7", "1.",
                                   -2.5, 0, 3, None, True])
def test_numbers_and_ordinary_text_are_unchanged(value):
    assert excel.download_cell(value) == value


def _run_view(labels):
    return {"result": {
        "t_simulation": 1000.0,
        "precision": {"window_availability": 0.99, "lower": 0.98, "upper": 1.0},
        "steady_state_availability": 0.995,
        "mean_up_time": -1.0,  # a number stays a number, sign and all
        "curve": {"t": [0.0, 10.0], "availability": [1.0, 0.99]},
        "per_node": [{"label": label, "share": 0.5} for label in labels],
    }}


def test_run_export_keeps_block_labels_as_text():
    labels = ["=A1|' x'!B2", "@SUM(1+1)", "+2+3", "-2+3", "\t=1", "Pump A", "-2.5"]
    text = rbd_runs.export_csv(_run_view(labels))
    rows = list(csv.reader(io.StringIO(text)))
    blocks = [r[1] for r in rows if r[0] == "downtime_share"]
    assert blocks == ["'=A1|' x'!B2", "'@SUM(1+1)", "'+2+3", "'-2+3", "'\t=1", "Pump A", "-2.5"]
    # Numbers are written exactly as before.
    assert ["mean_up_time", "", "", "-1.0", "", ""] in rows
    assert ["window_availability", "", "1000.0", "0.99", "0.98", "1.0"] in rows
    assert rows[0] == ["quantity", "block", "time", "value", "lower", "upper"]


def test_block_id_used_when_there_is_no_label_is_kept_as_text():
    view = _run_view([])
    view["result"]["per_node"] = [{"id": "=1+1", "share": 0.2}]
    rows = list(csv.reader(io.StringIO(rbd_runs.export_csv(view))))
    assert ["downtime_share", "'=1+1", "", "0.2", "", ""] in rows


def test_workbook_csv_for_the_app_keeps_cells_as_they_are():
    # The app parses this CSV itself (a workbook sent where a CSV goes), so
    # its cells are not changed.
    table = excel.Table(sheet="S", header=["name", "x"], rows=[["=a", -1.0], ["-b", 2.0]],
                        row_numbers=[2, 3], header_row=1, notes=[])
    assert excel.to_csv(table) == b"name,x\n=a,-1.0\n-b,2.0\n"
