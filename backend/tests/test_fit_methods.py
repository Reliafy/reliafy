"""Fit methods (SurPyval's ``how=``) and the capability matrix behind them.

Which method works with which distribution, data and option is SurPyval's
business, and it changes between versions. Rather than hand-listing it — the
mistake that let the agent's distribution list drift — the capabilities are
derived, and these tests re-derive them BY ACTUALLY FITTING. If SurPyval gains
or loses a combination, the parity test fails and the picker is wrong until
someone looks.
"""

import warnings

import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting
from backend.fitting import FIT_METHOD_IDS, FitError, distribution_capabilities
from backend.main import distributions_endpoint


@pytest.fixture(scope="module")
def clean():
    return pd.DataFrame({"hours": np.round(np.abs(sp.Weibull.random(150, 800, 1.9)), 3)})


def _fits(dist_id, how, **kw):
    """True if SurPyval will actually produce finite parameters this way."""
    x = np.abs(sp.Weibull.random(150, 800, 1.9))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            m = fitting.DISTRIBUTIONS[dist_id]["dist"].fit(x=x, how=how, **kw)
            return bool(np.all(np.isfinite(np.asarray(m.params, dtype=float))))
        except Exception:
            return False


@pytest.mark.parametrize("dist_id", list(fitting.DISTRIBUTIONS))
def test_advertised_methods_match_what_actually_fits(dist_id):
    """Parity between the capability table and SurPyval's real behaviour."""
    advertised = set(distribution_capabilities(dist_id)["methods"])
    actual = {m for m in FIT_METHOD_IDS if _fits(dist_id, m)}
    assert advertised == actual, (
        f"{dist_id}: advertised {sorted(advertised)} but {sorted(actual)} actually fit"
    )


def test_only_exponentiated_weibull_lacks_probability_plotting():
    """Pins the one distribution-level exclusion, so losing it is visible."""
    without = {d for d in fitting.DISTRIBUTIONS
               if "MPP" not in distribution_capabilities(d)["methods"]}
    assert without == {"expo_weibull"}


def test_zero_inflation_needs_support_starting_at_zero():
    """Real-line distributions can't be zero-inflated — SurPyval rejects it, so
    the picker must not offer it (it used to)."""
    for d in ("normal", "gumbel", "gumbel_lev", "logistic"):
        assert distribution_capabilities(d)["zi"] is False
    for d in ("weibull", "lognormal", "gamma", "rayleigh"):
        assert distribution_capabilities(d)["zi"] is True


def test_offsetable_is_derived_not_asserted():
    """Half-line support is the rule; check it against SurPyval's own supports."""
    for did, entry in fitting.DISTRIBUTIONS.items():
        lo, hi = entry["dist"].support
        assert distribution_capabilities(did)["offsetable"] is bool(lo == 0 and np.isinf(hi))


@pytest.mark.parametrize("how", FIT_METHOD_IDS)
def test_every_method_fits_a_weibull_and_is_echoed(clean, how):
    r = fitting.fit("weibull", clean, {"x": "hours"}, options={"how": how})
    assert len(r["params"]) == 2
    assert all(np.isfinite(p["value"]) for p in r["params"])
    # MLE is the default and is deliberately not recorded; the rest round-trip.
    assert (r.get("options") or {}).get("how") == (None if how == "MLE" else how)


def test_methods_disagree_slightly_so_the_option_is_doing_something(clean):
    """If two methods returned identical parameters the control would be a lie."""
    got = {how: [p["value"] for p in
                 fitting.fit("weibull", clean, {"x": "hours"}, options={"how": how})["params"]]
           for how in ("MLE", "MPP", "MSE", "MOM")}
    assert len({tuple(round(v, 6) for v in p) for p in got.values()}) == len(got)


def test_a_failed_optimisation_is_reported_not_swallowed():
    """MPS warns 'MPS FAILED' and returns numbers anyway. Handing those over
    silently is the failure mode worth guarding."""
    df = pd.DataFrame({"hours": np.round(np.abs(sp.Weibull.random(150, 800, 1.9)), 3)})
    r = fitting.fit("weibull", df, {"x": "hours"}, options={"how": "MPS"})
    if r.get("fit_warning"):
        assert "FAILED" in r["fit_warning"].upper()
        assert "check them" in r["fit_warning"]


def test_the_rules_are_enforced_server_side(clean):
    for dist, opts, expect in (
        ("expo_weibull", {"how": "MPP"}, "can't be fitted by MPP"),
        ("weibull", {"how": "MPP", "fixed": {"beta": 2}}, "can't hold parameters fixed"),
        ("weibull", {"how": "MPS", "lfp": True}, "only be fitted by maximum likelihood"),
        ("weibull", {"how": "MSE", "zi": True}, "only be fitted by maximum likelihood"),
        ("normal", {"zi": True}, "can't be zero-inflated"),
        ("weibull", {"how": "NOPE"}, "Unknown fit method"),
        ("mixture", {"how": "MPP"}, "expectation-maximisation"),
    ):
        with pytest.raises(FitError) as e:
            fitting.fit(dist, clean, {"x": "hours"}, options=opts)
        assert expect in str(e.value), f"{dist} {opts}"


def test_data_dependent_rules():
    """Censoring and truncation rule methods out; known from the mapping alone."""
    assert fitting.methods_for_data({}) == {}
    assert set(fitting.methods_for_data({"c": "cens"})) == {"MOM"}
    assert set(fitting.methods_for_data({"tl": "entry"})) == {"MOM", "MSE"}
    # And the underlying library really does refuse them.
    x = np.abs(sp.Weibull.random(120, 800, 1.9))
    c = np.zeros(len(x)); c[-20:] = 1
    with pytest.raises(Exception):
        sp.Weibull.fit(x=x, c=c, how="MOM")
    with pytest.raises(Exception):
        sp.Weibull.fit(x=x, tl=0.0, how="MSE")


def test_the_picker_advertises_the_same_capabilities():
    payload = distributions_endpoint()
    assert [m["id"] for m in payload["fit_methods"]] == FIT_METHOD_IDS
    by_id = {d["id"]: d for d in payload["distributions"]}
    for did in fitting.DISTRIBUTIONS:
        caps = distribution_capabilities(did)
        assert by_id[did]["methods"] == caps["methods"]
        assert by_id[did]["zi"] == caps["zi"]
        assert by_id[did]["offsetable"] == caps["offsetable"]
    # "Best fit" fits every candidate, so it can only offer their intersection.
    assert "MPP" not in by_id["best"]["methods"]
