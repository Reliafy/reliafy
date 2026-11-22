"""Spares from a repairable model: the range of how many failures there will
be (chance as well as the fit's uncertainty), not only the expected number's
range, and the stock to hold for a chance of not running out.

The data: one fleet's replacements of a thrown-away part as one counting
process against cumulative fleet hours (12 sets at 6,000 h a year, so
72,000 fleet hours a year), a power-law process with beta 0.6, record ended
at 216,000 h. The check values were worked out by hand: Crow-AMSAA MLE,
20,000 parametric bootstrap refits plus Poisson chance for the count.
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

YEAR = 72000.0
T = 3 * YEAR


def _replacements() -> pd.DataFrame:
    rng = np.random.default_rng(20261135)
    lam = 45 / T ** 0.6
    g = np.cumsum(rng.exponential(1.0, 400))
    t = (g / lam) ** (1 / 0.6)
    t = np.maximum(np.round(t[t <= T], 0), 1.0)
    return pd.DataFrame({"fleet": "fleet", "fleet_hours": t.astype(int)})


@pytest.fixture(scope="module")
def fitted():
    from backend import recurrent as rec

    df = _replacements()
    payload, cid = rec.fit(df, {"i": "fleet", "x": "fleet_hours"}, "crow_amsaa", "hours",
                           record_end=T, gof_test=False)
    return payload, rec.get_live(cid)


def test_the_data_and_fit_match_the_hand_check(fitted):
    payload, _ = fitted
    assert payload["n_events"] == 48
    assert payload["beta"] == pytest.approx(0.588, abs=0.001)


def test_window_range_is_the_count_not_the_expected_number(fitted):
    from backend import recurrent_forecast as rf

    payload, live = fitted
    w = rf.calculate(live, payload, T + YEAR, start=T)["window"]
    assert w["expected"] == pytest.approx(8.85, abs=0.01)
    # How many there will be: 4-15 by hand (parameters and chance).
    assert w["ci"] == [4.0, 15.0]
    assert w["range_kind"] == "count"
    # The expected number's own range is narrower (6.1-12.5 by bootstrap).
    lo, hi = w["mean_ci"]
    assert 5.5 < lo < 6.5 and 11.5 < hi < 12.8
    # The count's range is wider than chance alone at the point estimate (4-14).
    assert w["ci"][1] >= stats.poisson.ppf(0.95, w["expected"])


def test_stock_for_a_ten_percent_chance_of_running_out(fitted):
    from backend import recurrent_forecast as rf

    payload, live = fitted
    w = rf.calculate(live, payload, T + YEAR, start=T, service_level=0.9)["window"]
    s = w["stock"]
    # 14 by bootstrap, 13 on chance alone: the fit's draws give 13 or 14.
    assert s["hold"] in (13.0, 14.0)
    assert s["runout"] <= 0.10 < s["runout_one_less"]
    # A higher chance of not running out needs more stock.
    more = rf.calculate(live, payload, T + YEAR, start=T, service_level=99)["window"]["stock"]
    assert more["level"] == 0.99 and more["hold"] > s["hold"]
    with pytest.raises(Exception, match="0.5 to 0.999"):
        rf.calculate(live, payload, T + YEAR, start=T, service_level=0.2)


def test_constant_rate_side_by_side(fitted):
    from backend import recurrent_forecast as rf

    payload, live = fitted
    w = rf.calculate(live, payload, T + YEAR, start=T)["window"]
    # 48 in 216,000 h: 16 over the next 72,000 h on the average rate.
    assert w["constant_rate"]["expected"] == pytest.approx(16.0)
    assert w["constant_rate"]["failures"] == 48 and w["constant_rate"]["exposure"] == T


def test_from_now_gives_the_same_count_range_and_stock(fitted):
    from backend import recurrent_forecast as rf

    _, live = fitted
    now = rf.from_now(live, YEAR, service_level=0.9)
    assert now["expected"] == pytest.approx(8.85, abs=0.01)
    assert now["interval"] == [4.0, 15.0]
    assert now["mean_interval"][0] < now["expected"] < now["mean_interval"][1]
    assert now["stock"]["hold"] in (13.0, 14.0)
    assert now["constant_rate"]["expected"] == pytest.approx(16.0)
