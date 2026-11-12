"""Accelerated life with x and a range mapped together, read per row as the
life fit reads them (fitting.combine_exact_and_ranges): the fit equals one
given the same rows as an xl/xr pair, and rows giving both are left out with
the warning on the result."""

import numpy as np
import pandas as pd
import pytest

from backend import alt


def _sheet():
    rng = np.random.default_rng(3)
    rows = []
    for temp in (350.0, 375.0, 400.0):
        life = rng.weibull(2.0, 12) * 6000 * np.exp(3000 / temp - 3000 / 350)
        for k, t in enumerate(life):
            if k % 3 == 0:  # found failed between two inspections
                hi = float(np.ceil(t / 500) * 500)
                rows.append({"hours": np.nan, "last_ok": hi - 500, "found": hi, "temp_K": temp})
            else:
                rows.append({"hours": round(float(t), 1), "last_ok": np.nan, "found": np.nan, "temp_K": temp})
    return pd.DataFrame(rows)


def _params(payload):
    return [p["value"] for p in payload["params"]]


def test_alt_reads_x_and_a_range_per_row():
    df = _sheet()
    mixed, _ = alt.fit(df, {"x": "hours", "xl": "last_ok", "xr": "found"}, ["temp_K"])
    pair = df.assign(lo=df["hours"].fillna(df["last_ok"]), hi=df["hours"].fillna(df["found"]))
    ref, _ = alt.fit(pair, {"xl": "lo", "xr": "hi"}, ["temp_K"])
    assert _params(mixed) == pytest.approx(_params(ref), rel=1e-6)
    assert "x_and_range_rows" not in mixed


def test_alt_leaves_out_rows_with_both_and_says_so():
    df = _sheet()
    extra = pd.DataFrame([{"hours": 100.0, "last_ok": 50.0, "found": 150.0, "temp_K": 400.0}] * 2)
    both = pd.concat([df, extra], ignore_index=True)
    payload, _ = alt.fit(both, {"x": "hours", "xl": "last_ok", "xr": "found"}, ["temp_K"])
    ref, _ = alt.fit(df, {"x": "hours", "xl": "last_ok", "xr": "found"}, ["temp_K"])
    assert _params(payload) == pytest.approx(_params(ref), rel=1e-6)
    assert payload["x_and_range_rows"]["count"] == 2
    assert any("left out of the fit" in w for w in payload["fit_warnings"])
