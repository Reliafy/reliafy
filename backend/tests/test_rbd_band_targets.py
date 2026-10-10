"""Parameter uncertainty at several targets in one run (#325): a
non-repairable diagram's B-lives and reliability at several times, each with
its interval, from the same draws as the band."""

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_uncertainty  # noqa: E402
from backend.services.rbd_analysis import AnalysisError, analyze  # noqa: E402
from backend.tests.test_rbd_uncertainty import FIT, _pumps_and_valve, _resolver  # noqa: E402


def _band(**band):
    return analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}), band={"level": 0.9, **band})


def test_several_b_lives_and_times_in_one_run():
    res = _band(b_lives=[1, 10, 50], times=[100, 200])
    targets = res["band"]["targets"]
    assert [r["fraction"] for r in targets["b_lives"]] == [0.01, 0.1, 0.5]
    # The B10 and B50 intervals are the band's own (the same draws).
    assert {k: targets["b_lives"][1][k] for k in ("lower", "upper")} == res["band"]["blife"]["b10"]
    assert {k: targets["b_lives"][2][k] for k in ("lower", "upper")} == res["band"]["blife"]["b50"]
    for row in targets["b_lives"]:
        assert row["lower"] < row["value"] < row["upper"]
    assert targets["b_lives"][1]["value"] == pytest.approx(res["blife"]["b10"], rel=1e-3)
    # The reliability at each time: its point value exactly, inside its interval.
    exact = analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}), at_times=[100, 200])["at"]["sf"]
    for row, sf in zip(targets["reliability"], exact):
        assert row["value"] == pytest.approx(sf)
        assert row["lower"] <= row["value"] <= row["upper"]
    # Later is less reliable, at both ends of the interval.
    a, b = targets["reliability"]
    assert b["upper"] < a["upper"] and b["lower"] < a["lower"]


def test_the_intervals_are_the_draws_percentiles():
    """The reliability interval at a time is the band's at that time."""
    res = _band(times=[150.0])
    grid = np.asarray(res["time"])
    at = res["band"]["targets"]["reliability"][0]
    i = int(np.argmin(np.abs(grid - 150.0)))
    if abs(grid[i] - 150.0) < 1e-9:
        assert at["lower"] == pytest.approx(res["band"]["sf_lower"][i])
    assert res["band"]["sf_lower"][i] - 0.05 < at["lower"] < res["band"]["sf_upper"][i] + 0.05


def test_without_targets_the_band_is_unchanged():
    plain = _band()
    assert "targets" not in plain["band"]
    with_targets = _band(b_lives=[10])
    assert with_targets["band"]["sf_lower"] == plain["band"]["sf_lower"]


def test_targets_are_checked():
    assert rbd_uncertainty.parse_targets({"b_lives": [1, 0.1, 50]}) == ([0.01, 0.1, 0.5], None)
    assert rbd_uncertainty.parse_targets({"times": [5, 5, 2]}) == (None, [2.0, 5.0])
    assert rbd_uncertainty.parse_targets(None) == (None, None)
    for bad in ({"b_lives": [100]}, {"b_lives": [-1]}, {"times": [0]}, {"times": "5"},
                {"times": list(range(1, 11))}, {"b_lives": [True]}):
        with pytest.raises(AnalysisError):
            rbd_uncertainty.parse_targets(bad)


def test_mcp_analyze_rbd_targets(monkeypatch):
    import mongomock

    from backend import config, db
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service
    from backend.services import tokens
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_targets"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(models_service, "get_live_model", lambda session, mid, owners: {"model": FIT})
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]
    rbd = rbds_service.save_rbd(test_db, "Pumps", {**_pumps_and_valve(), "repairable": False}, A)
    out = _ok(_call(token, "analyze_rbd", {"rbd_id": rbd.id, "confidence": 0.9, "b_lives": [1, 10],
                                           "times": [0, 100, 200]}))
    targets = out["confidence"]["targets"]
    assert [r["fraction"] for r in targets["b_lives"]] == [0.01, 0.1]
    assert [r["t"] for r in targets["reliability"]] == [100.0, 200.0]
