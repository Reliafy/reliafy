"""The Data step's column facts: wholly blank rows are skipped (and counted),
and each numeric column says how many of its values are 0 or less."""
from backend import fitting

SHEET = (
    "Idler,Hours,Failed (1=yes)\n"
    "ID-1,1200,1\n"
    "ID-2,0,0\n"
    ",,\n"
    "ID-3,900,1\n"
    "ID-4,2500,0\n"
    "ID-5,1800,1\n"
).encode()


def test_preview_skips_and_counts_wholly_blank_rows():
    out = fitting.preview(SHEET, distinct=True)
    assert out["n_rows"] == 5
    assert out["blank_rows"] == 1
    assert out["blanks"] == [0, 0, 0]


def test_preview_counts_times_of_zero_or_less():
    out = fitting.preview(SHEET, distinct=True)
    assert out["nonpositive"] == [None, 1, 2]


def test_a_fit_skips_a_wholly_blank_row():
    df = fitting.read_dataframe(SHEET.replace(b"ID-2,0,0", b"ID-2,700,0"))
    assert len(df) == 5
    result = fitting.fit("kaplan_meier", df, {"x": "Hours", "c": "Failed (1=yes)"},
                         unit="Hours", options={"c_invert": True})
    assert result["distribution"]


def test_a_file_of_only_blank_rows_is_empty():
    import pytest

    with pytest.raises(fitting.FitError):
        fitting.read_dataframe(b"a,b\n,\n,\n")
