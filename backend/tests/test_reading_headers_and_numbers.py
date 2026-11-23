"""Reading an upload: number columns written with thousands separators or decimal commas are
read as numbers (and say so), and the first guess of the columns' roles reads inspection and
count headers people write ("Last checked OK", "How many")."""

import pytest

from backend import fitting
from backend.services import dataset_reading


def _read(text: str) -> dict:
    return fitting.preview(text.encode(), distinct=True)


def test_thousands_separators_are_read_as_numbers_and_said():
    p = _read('Pump,Run hrs,Swiss,Thin\nA,"14,010",14\'010,14 010\nB,"8,240",8\'240,8 240\n'
              'C,"1,190,500",11\'190,11 190\nD,950,950,950\n')
    assert p["dtypes"][1:] == ["float64"] * 3
    assert [row[1] for row in p["preview"]] == [14010.0, 8240.0, 1190500.0, 950.0]
    assert [row[2] for row in p["preview"]] == [14010.0, 8240.0, 11190.0, 950.0]
    assert [row[3] for row in p["preview"]] == [14010.0, 8240.0, 11190.0, 950.0]
    assert p["number_notes"][0] == "“Run hrs” is read as numbers, with commas as thousands separators: 14,010 is 14010."
    assert "apostrophes" in p["number_notes"][1] and "thin spaces" in p["number_notes"][2]
    # And it's the time: offered as x, not left over as text.
    assert dataset_reading.guess(p)["x"] == "Run hrs"


def test_decimal_commas_only_when_the_whole_column_uses_them():
    p = _read('Unit,Hours\nA,"12,5"\nB,"3,75"\nC,7\nD,"1.234,5"\n')
    assert [row[1] for row in p["preview"]] == [12.5, 3.75, 7.0, 1234.5]
    assert p["number_notes"] == ["“Hours” is read as numbers, with commas as decimal points and points as thousands "
                                 "separators: 12,5 is 12.5."]
    # Every comma followed by three digits: thousands, not 14.010.
    assert _read('Unit,Hours\nA,"14,010"\nB,"8,240"\n')["preview"][0][1] == 14010.0


@pytest.mark.parametrize("text", [
    'Unit,Hours\nA,"14,010"\nB,"l0,740"\n',       # a typo: not every cell is a number
    'Unit,Hours\nA,"14,010"\nB,"12,5"\nC,1.5\n',  # a decimal point and decimal commas: can't tell
    'Unit,Code\nA,AB-12\nB,"1,2,3"\n',
])
def test_a_column_that_isnt_consistently_a_number_is_left_as_text(text):
    p = _read(text)
    assert p["dtypes"][1] == "str" and p["number_notes"] == []


def test_last_checked_ok_and_found_are_the_interval_not_x():
    p = _read("Pump,Last checked OK (month),Found split (month)\nDP-01,4,5\nDP-02,11,12\nDP-03,10,11\n")
    g = dataset_reading.guess(p)
    assert (g["x"], g["xl"], g["xr"], g["unit"]) == ("", "Last checked OK (month)", "Found split (month)", "Months")
    assert "Found split (month)" not in g["z"]


def test_a_last_inspected_column_is_never_x_beside_a_time():
    p = _read("Unit,Last inspected (h),Hours run,Failed\nA,100,150,1\nB,200,260,0\nC,90,120,1\n")
    assert dataset_reading.guess(p)["x"] == "Hours run"
    p = _read("Unit,Inspection date (days),Days in service,Failed\nA,100,150,1\nB,200,260,0\nC,90,120,1\n")
    assert dataset_reading.guess(p)["x"] == "Days in service"


@pytest.mark.parametrize("header", ["How many", "How many units", "Qty", "count", "n", "Number of units",
                                    "No. of pumps"])
def test_count_columns_are_n_not_a_covariate(header):
    p = _read(f"Months in service,What happened,{header}\n5,replaced - seized,1\n6,replaced - seized,2\n"
              "7,on the belt now,4\n")
    g = dataset_reading.guess(p)
    assert g["n"] == header and header not in g["z"] and g["x"] == "Months in service"
