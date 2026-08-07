"""Fitting refuses impossible censoring with a message that names the cause.

Motivated by a real signup: a user uploaded 8 rows where 1 meant "failed" —
the inverse of the convention — spent 15 minutes in the wizard, and got
"list index out of range" from SurPyval's fitter. Both the all-censored and
the one-failure cases nearly always mean an inverted flag, so both say so.
"""

import io

import pandas as pd
import pytest

from backend import fitting
from backend.fitting import CENSOR_CONVENTION, FitError, failure_count

# The actual file, as uploaded.
_CSV = "Time,Censored\n100,1\n234,1\n500,1\n890,1\n900,1\n1230,1\n2345,1\n3546,0\n"


def _df(csv=_CSV):
    return pd.read_csv(io.StringIO(csv))


def test_the_upload_that_used_to_crash_now_explains_itself():
    with pytest.raises(FitError) as e:
        fitting.fit("weibull", _df(), {"x": "Time", "c": "Censored"})
    msg = str(e.value)
    assert "list index out of range" not in msg
    assert "Only 1 of the 8 rows" in msg
    assert "0 = the unit failed" in msg


def test_all_censored_names_the_convention_too():
    df = _df(); df["Censored"] = 1
    with pytest.raises(FitError, match="nothing for Weibull to fit"):
        fitting.fit("weibull", df, {"x": "Time", "c": "Censored"})
    with pytest.raises(FitError, match="invert it"):
        fitting.fit("weibull", df, {"x": "Time", "c": "Censored"})


def test_inverting_the_flag_fits_and_gives_the_expected_answer():
    """The user had 1,392.14 pencilled in their spreadsheet. Read the right way
    round, their data gives alpha ~1373 — they were 1.4% from their answer."""
    df = _df(); df["Censored"] = 1 - df["Censored"]
    r = fitting.fit("weibull", df, {"x": "Time", "c": "Censored"})
    alpha = next(p["value"] for p in r["params"] if p["name"] == "alpha")
    assert alpha == pytest.approx(1372.92, rel=1e-3)


@pytest.mark.parametrize("dist", ["weibull", "gumbel", "expo_weibull"])
def test_every_distribution_that_needed_two_failures_now_explains(dist):
    """These are the ones SurPyval crashed on with a single failure."""
    with pytest.raises(FitError) as e:
        fitting.fit(dist, _df(), {"x": "Time", "c": "Censored"})
    assert "at least two observed failures" in str(e.value)


@pytest.mark.parametrize("dist", ["exponential", "normal", "lognormal", "rayleigh"])
def test_distributions_that_can_fit_one_failure_still_do(dist):
    """The guard must not block fits SurPyval genuinely supports."""
    r = fitting.fit(dist, _df(), {"x": "Time", "c": "Censored"})
    assert r["params"]


def test_a_mixture_gets_the_same_guard():
    with pytest.raises(FitError, match="0 = the unit failed"):
        fitting.fit("mixture", _df(), {"x": "Time", "c": "Censored"})


def test_failure_count_honours_counts_and_censor_codes():
    df = pd.DataFrame({"t": [10, 20, 30, 40], "c": [0, 1, 0, 1], "n": [3, 5, 1, 1]})
    kwargs = fitting.build_fit_inputs(df, {"x": "t", "c": "c", "n": "n"})
    assert failure_count(kwargs) == (4, 10)          # 3+1 failures of 10 units
    plain = fitting.build_fit_inputs(df, {"x": "t"})
    assert failure_count(plain) == (4, 4)            # no censor column -> all events


def test_the_convention_is_stated_once_and_reused():
    assert "0 = the unit failed" in CENSOR_CONVENTION
    assert "invert it" in CENSOR_CONVENTION
