"""Late entry (tl) and observed-until (tr) columns, read per row.

tl: a unit observed only from this value; tr: only up to it. A blank cell is
no limit on that row. The fit must give SurPyval's own answer for the same
rows, and a row whose value is above its tr, or whose tr is below its tl,
is refused naming the rows (and said beside tr on the Data step).
"""

import io

import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.fitting import FitError

_ROWS = [
    # hours, status, entered at, observed until
    (420, "Failed", 0, 2000), (610, "Failed", 200, 2000), (780, "Failed", 0, ""),
    (905, "Failed", 300, 2000), (1010, "Failed", 0, 1500), (1180, "Failed", 500, ""),
    (1320, "Failed", 0, 2000), (1490, "Failed", 400, 1500), (1450, "Running", 0, 1500),
    (1650, "Failed", 0, ""), (1800, "Running", 600, 2000), (1950, "Running", 0, 2000),
    (700, "Failed", 0, 2000), (1250, "Failed", 250, ""), (950, "Running", 0, 1500),
]


def _sheet(rows=_ROWS):
    text = "Hours,Status,Entered at (h),Observed until (h)\n" + "\n".join(",".join(map(str, r)) for r in rows)
    return pd.read_csv(io.StringIO(text + "\n"))


_MAP = {"x": "Hours", "c": "Status", "tl": "Entered at (h)", "tr": "Observed until (h)"}
_C_MAP = {"Failed": 0, "Running": 1}


def test_tl_and_tr_fit_as_surpyval_does():
    import surpyval

    r = fitting.fit("weibull", _sheet(), _MAP, options={"c_map": dict(_C_MAP)})
    x = np.array([row[0] for row in _ROWS], dtype=float)
    c = np.array([_C_MAP[row[1]] for row in _ROWS])
    tl = np.array([row[2] for row in _ROWS], dtype=float)
    tr = np.array([np.inf if row[3] == "" else row[3] for row in _ROWS], dtype=float)
    ref = surpyval.Weibull.fit(x, c=c, tl=tl, tr=tr)
    assert [p["value"] for p in r["params"]] == pytest.approx(list(ref.params), rel=1e-6)
    # tr changes the answer: it isn't ignored.
    without = fitting.fit("weibull", _sheet(), {k: v for k, v in _MAP.items() if k != "tr"},
                          options={"c_map": dict(_C_MAP)})
    assert [p["value"] for p in without["params"]] != pytest.approx([p["value"] for p in r["params"]], rel=1e-6)


def test_a_value_above_tr_or_tr_below_tl_is_refused_naming_the_rows():
    rows = list(_ROWS)
    rows[1] = (2610, "Failed", 200, 2000)   # above its tr
    rows[3] = (905, "Failed", 1300, 1000)   # tr below tl
    df = _sheet(rows)
    problem = fitting.truncation_problem(df, _MAP)
    assert problem["count"] == 2 and problem["rows"] == [2, 4]
    assert problem["text"].startswith("1 row has a value above tr ('Observed until (h)'), or still running at it, row 2; "
                                      "1 row has tr below tl ('Entered at (h)'), row 4.")
    with pytest.raises(FitError, match="above tr"):
        fitting.fit("weibull", df, _MAP, options={"c_map": dict(_C_MAP)})
    # The Data step's reading says so without refusing.
    reading = fitting.data_reading(fitting.map_censor_column(df, "Status", _C_MAP), _MAP)
    assert reading["tr_problem"]["count"] == 2


def test_a_blank_tr_is_no_limit_and_a_range_checks_its_upper_value():
    assert fitting.truncation_problem(_sheet(), _MAP) is None
    df = pd.DataFrame({"lo": [100.0, 300.0], "hi": [200.0, np.nan], "until": [150.0, 250.0]})
    p = fitting.truncation_problem(df, {"xl": "lo", "xr": "hi", "tr": "until"})
    # Row 1's range ends above 150; row 2 is running at 300, above 250 (no c: read as values).
    assert p["rows"] == [1, 2]
