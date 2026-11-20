"""Times below 0, and failures at 0, in life data.

A distribution refuses them (its probability starts at 0); the non-parametric
estimates assume no distribution, so nothing in the library stopped them and a
time of -50 became the first step of the curve: "B10 -50 hours". Every
estimate now refuses them the same way, naming the rows, and the Data step's
column facts name them before any fit.
"""
import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.fitting import FitError

ESTIMATES = list(fitting.NONPARAMETRIC)
NAMES = {k: v["name"] for k, v in fitting.NONPARAMETRIC.items()}

# A messy export: hours with a -50 and a 0, failed = 1 (read as c = 0).
HOURS = [1200.0, 1850, -50, 0, 2400, 2600, 3100, 5000, 5000]
FAILED = [1, 1, 1, 1, 0, 1, 1, 0, 0]


def _df(hours=HOURS, failed=FAILED):
    return pd.DataFrame({"hours": hours, "c": [1 - f for f in failed]})


@pytest.mark.parametrize("did", ESTIMATES)
def test_a_time_below_0_is_refused_with_both_bad_rows_named(did):
    with pytest.raises(FitError) as exc:
        fitting.fit(did, _df(), {"x": "hours", "c": "c"}, unit="hours")
    msg = str(exc.value)
    assert msg.startswith(f"Row 3 (time -50) is out of range for a {NAMES[did]} estimate: a time can't be below 0")
    assert "Row 4 (time 0) is a failure at 0" in msg
    assert "Correct or remove that row" in msg


def test_kaplan_meier_on_the_messy_export_never_shows_b10_minus_50():
    # Before: B10 -50 hours. Now refused, and with the two rows removed the
    # B10 is the first failure, 1,200 hours (1 of 7 at risk fails: R = 0.857 < 0.9).
    with pytest.raises(FitError, match=r"^Row 3 \(time -50\)"):
        fitting.fit("kaplan_meier", _df(), {"x": "hours", "c": "c"})
    keep = [i for i, h in enumerate(HOURS) if h > 0]
    clean = _df([HOURS[i] for i in keep], [FAILED[i] for i in keep])
    m = fitting.fit("kaplan_meier", clean, {"x": "hours", "c": "c"})["metrics"]
    assert m["b10"] == pytest.approx(1200.0)
    assert m["median"] == pytest.approx(3100.0)


@pytest.mark.parametrize("did", ESTIMATES)
def test_a_failure_at_0_is_refused_with_what_to_do(did):
    df = _df([5.0, 0, 8, 12, 20, 30], [1, 1, 1, 0, 1, 1])
    with pytest.raises(FitError) as exc:
        fitting.fit(did, df, {"x": "hours", "c": "c"})
    msg = str(exc.value)
    assert msg.startswith(f"Row 2 (time 0) is a failure at 0, which a {NAMES[did]} estimate can't use")
    assert "range from 0 to the first check (xl to xr)" in msg
    assert ("use Turnbull" in msg) == (did != "turnbull")


@pytest.mark.parametrize("did", ESTIMATES)
def test_a_unit_still_running_at_0_still_fits(did):
    df = _df([0.0, 5, 8, 12, 20, 30], [0, 1, 1, 0, 1, 1])
    r = fitting.fit(did, df, {"x": "hours", "c": "c"})
    assert r["metrics"]["b10"] is None or r["metrics"]["b10"] > 0


def test_turnbull_takes_a_unit_dead_on_arrival_as_failed_before_its_first_check():
    df = pd.DataFrame({"lo": [0.0, 100, 200, 300, 400], "hi": [50.0, 150, 250, 350, 450]})
    r = fitting.fit("turnbull", df, {"xl": "lo", "xr": "hi"})
    assert r["kind"] == "nonparametric"


def test_turnbull_refuses_a_range_below_0():
    df = pd.DataFrame({"lo": [-10.0, 100, 200, 300], "hi": [50.0, 150, 250, 350]})
    with pytest.raises(FitError, match=r"^Row 1 \(time -10\) is out of range for a Turnbull estimate"):
        fitting.fit("turnbull", df, {"xl": "lo", "xr": "hi"})


def test_a_late_entry_below_0_is_refused():
    df = pd.DataFrame({"t": [5.0, 8, 12, 20, 30], "tl": [0.0, -3, 0, 0, 0]})
    with pytest.raises(FitError, match=r"^Row 2 \(time -3\) is out of range for a Kaplan-Meier estimate"):
        fitting.fit("kaplan_meier", df, {"x": "t", "tl": "tl"})


@pytest.mark.parametrize("did", ESTIMATES)
@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("shift", [False, True])
def test_no_estimate_ever_gives_a_negative_life(did, seed, shift):
    rng = np.random.default_rng(seed)
    t = np.round(rng.normal(200, 400, 30), 1)  # a good share below 0
    if shift:  # the same spread, all above 0: fits, with lives above 0
        t = t - t.min() + 1
    df = pd.DataFrame({"t": t, "c": (rng.random(30) < 0.2).astype(int)})
    try:
        m = fitting.fit(did, df, {"x": "t", "c": "c"})["metrics"]
    except FitError as exc:
        assert "below 0" in str(exc) or "failure at 0" in str(exc)
        return
    for key in ("b10", "median", "mttf"):
        assert m[key] is None or m[key] >= 0


def test_preview_names_the_rows_below_0_and_at_0():
    csv = "hours,failed\n" + "\n".join(f"{h:g},{f}" for h, f in zip(HOURS, FAILED)) + "\n"
    out = fitting.preview(csv.encode(), distinct=True)
    assert out["low_rows"][0] == {"negative": 1, "negative_rows": [3], "negative_values": [-50.0],
                                  "zero": 1, "zero_rows": [4]}
    assert out["low_rows"][1]["negative"] == 0
    text = fitting.preview(b"name,hours\na,1\nb,2\n", distinct=True)
    assert text["low_rows"][0] is None


# ---- every other Kaplan-Meier path: the same refusal, rows named -----------------------

def test_compare_groups_names_a_time_below_0_by_its_row_in_the_data():
    from backend.services import compare_groups as cg

    # Row 2 has no group, so it's left out; row numbers still count it.
    df = pd.DataFrame({"t": [10.0, 20, -5, 30, 40, 50, 60], "c": [0, 0, 0, 1, 0, 0, 1],
                       "g": ["A", None, "A", "A", "B", "B", "B"]})
    with pytest.raises(cg.CompareGroupsError,
                       match=r"^Row 3 \(time -5\) is out of range for a comparison of groups: a time can't be below 0"):
        cg.prepare(df, time_column="t", group_column="g", censor_column="c")


def test_compare_groups_refuses_a_failure_at_0_but_takes_a_unit_running_at_0():
    from backend.services import compare_groups as cg

    df = pd.DataFrame({"t": [0.0, 20, 25, 30, 40, 50, 60], "c": [0, 0, 0, 1, 0, 0, 1],
                       "g": ["A", "A", "A", "A", "B", "B", "B"]})
    with pytest.raises(cg.CompareGroupsError) as exc:
        cg.prepare(df, time_column="t", group_column="g", censor_column="c")
    msg = str(exc.value)
    assert msg.startswith("Row 1 (time 0) is a failure at 0, which a comparison of groups can't use")
    assert "xl to xr" not in msg  # one time per unit here: no range to offer
    df.loc[0, "c"] = 1
    data = cg.prepare(df, time_column="t", group_column="g", censor_column="c")
    result = cg.compare_groups(data, group_column="g")
    for g in result.get("groups", []):
        assert g.get("median") is None or g["median"] >= 0


def test_failure_modes_name_a_time_below_0_by_its_row():
    from backend import competing_risks as cr

    df = pd.DataFrame({"hours": [100.0, -50, 300, 400, 500, 600],
                       "mode": ["seal", "bearing", "seal", None, "bearing", "seal"]})
    with pytest.raises(cr.CompetingRisksError,
                       match=r"^Row 2 \(time -50\) is out of range for failure modes: a time can't be below 0"):
        cr.prepare(df, {"x": "hours", "e": "mode"})


def test_failure_modes_refuse_a_failure_at_0_and_take_a_unit_running_at_0():
    from backend import competing_risks as cr

    df = pd.DataFrame({"hours": [0.0, 200, 300, 400, 500, 600],
                       "mode": ["seal", "bearing", "seal", None, "bearing", "seal"]})
    with pytest.raises(cr.CompetingRisksError, match=r"^Row 1 \(time 0\) is a failure at 0"):
        cr.prepare(df, {"x": "hours", "e": "mode"})
    df.loc[0, "mode"] = None  # no mode, no status column: still running at 0
    assert cr.prepare(df, {"x": "hours", "e": "mode"})["x"][0] == 0


def test_comparing_against_field_data_refuses_a_time_below_0():
    from backend.services import strategy as st

    a = {"label": "Spec sheet", "kind": "parametric", "distribution_id": "weibull",
         "params": [{"name": "alpha", "value": 100}, {"name": "beta", "value": 2.0}]}
    b = {"label": "Field data", "kind": "nonparametric", "x": [80.0, -50, 120, 150, 200], "c": [0, 0, 0, 1, 0]}
    with pytest.raises(st.StrategyError,
                       match=r"^Field data: Row 2 \(time -50\) is out of range for a Kaplan-Meier estimate"):
        st.compare_two(a, b)
    b["x"][1] = 0.0
    with pytest.raises(st.StrategyError, match=r"^Field data: Row 2 \(time 0\) is a failure at 0"):
        st.compare_two(a, b)
    b["c"][1] = 1  # still running at 0: fits, and the field life is above 0
    m = st.compare_two(a, b)["b"]["metrics"]
    assert m["b10"] is None or m["b10"] > 0
    assert m["median"] is None or m["median"] > 0
