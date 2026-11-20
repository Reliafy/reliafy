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
