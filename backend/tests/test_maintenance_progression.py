"""Time to the limit: a watched level fitted with SurPyval's degradation processes."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from backend.tests.test_maintenance_mcp import UID, _do, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import UID as API_UID
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401
from backend.tests.test_maintenance_signals_api import _maintenance

pytestmark = pytest.mark.usefixtures("mcp_on")


def _level(m, values, step_days=2.0, above=None, below=None, name="Pump"):
    """A scalar channel with a level whose readings are ``values``, the last one an hour ago."""
    pos = m.create_position(name)
    ch = m.add_signal_channel(pos["id"], None, name, "mm/s", tag=f"{name}.v")
    made = m.add_signal_level(ch["id"], "Overall", "value", None, above, below)
    end = datetime.now(timezone.utc) - timedelta(hours=1)
    n = len(values)
    for i, v in enumerate(values):
        m.add_signal_snapshot((end - timedelta(days=step_days * (n - 1 - i))).isoformat(), None,
                              tag=f"{name}.v", value=float(v))
    return made["point_id"]


def test_too_few_readings_gives_a_message_and_no_dates(env):
    m = _maintenance(UID)
    pid = _level(m, [1, 2, 3], above=10)
    out = m.time_to_limit(pid)
    assert out["status"] == "too_few" and out["time_to_limit"] is None and "at least 6" in out["message"]


def test_steady_drift_with_scatter_recovers_the_known_time(env):
    rng = np.random.default_rng(3)
    rate, step = 0.5, 2.0  # per day; readings every 2 days
    n = 30
    steps = rng.normal(rate * step, 0.8 * np.sqrt(step), n - 1)
    values = 1.0 + np.r_[0.0, np.cumsum(steps)]
    m = _maintenance(UID)
    limit = values[-1] + 40.0  # 40 units to go at 0.5 per day: about 80 days
    pid = _level(m, values, step, above=float(limit))
    out = m.time_to_limit(pid)
    assert out["status"] == "ok"
    ttl = out["time_to_limit"]
    assert ttl["median_days"] == pytest.approx(80, rel=0.25)
    assert ttl["range"]["early_days"] < ttl["median_days"] < ttl["range"]["late_days"]
    wide = ttl["range_allowing_for_the_fit"]
    assert wide["early_days"] <= ttl["range"]["early_days"] * 1.01
    assert wide["late_days"] is None or wide["late_days"] >= ttl["range"]["late_days"] * 0.99
    assert out["trend"]["drift_per_day"] == pytest.approx(rate, rel=0.3)
    assert "random walk" in out["assumption"]


def test_exponential_growth_is_read_as_a_rate_and_says_so(env):
    # Growth that speeds up: the straight-drift model under-reads it. The answer still comes with
    # its assumption, and the drift is the average over the readings.
    t = np.arange(0, 40, 2.0)
    values = 1.0 + 0.2 * np.exp(0.08 * t) + np.random.default_rng(1).normal(0, 0.05, len(t))
    m = _maintenance(UID)
    pid = _level(m, values, 2.0, above=20.0)
    out = m.time_to_limit(pid)
    assert out["status"] == "ok" and "stays the same" in out["assumption"]


def test_a_falling_level_reaches_a_low_limit(env):
    rng = np.random.default_rng(5)
    values = 50 - 0.4 * 2 * np.arange(25) + rng.normal(0, 0.8, 25)
    m = _maintenance(UID)
    pid = _level(m, values, 2.0, below=float(values[-1] - 20))
    out = m.time_to_limit(pid)
    assert out["status"] == "ok" and out["limit"]["direction"] == "falling"
    assert out["time_to_limit"]["median_days"] == pytest.approx(50, rel=0.35)
    assert out["trend"]["drift_per_day"] < 0


def test_flat_and_noise_free_and_past_limit_have_plain_answers(env):
    m = _maintenance(UID)
    flat = m.time_to_limit(_level(m, np.ones(10) + np.random.default_rng(2).normal(0, 1e-9, 10) * 0, above=5, name="Flat"))
    assert flat["status"] == "not_moving" and flat["time_to_limit"] is None
    line = m.time_to_limit(_level(m, 1 + 0.5 * np.arange(10), above=30, name="Line"))
    assert line["status"] == "no_scatter" and line["time_to_limit"] is None
    past = m.time_to_limit(_level(m, [1, 2, 4, 3, 5, 6, 8, 9], above=7, name="Past"))
    assert past["status"] == "already_past"
    none = m.time_to_limit(_level(m, [1, 2, 4, 3, 5, 6, 8, 9], name="NoLimit"))
    assert none["status"] == "no_limit"
    assert m.time_to_limit(_level(m, [1, 2, 4, 3, 5, 6, 8, 9], above=50, name="Given"), limit=40)["limit"]["from"] == "given"


def test_gamma_refuses_a_series_that_falls_and_accepts_a_rising_one(env):
    m = _maintenance(UID)
    bad = m.time_to_limit(_level(m, [1, 3, 2, 5, 4, 7, 6, 9], above=40, name="Wobble"), process="gamma")
    assert bad["status"] == "not_rising_only"
    rng = np.random.default_rng(8)
    good = _level(m, np.cumsum(rng.gamma(2.0, 0.5, 20)), above=60, name="Wear")
    assert m.time_to_limit(good, process="gamma")["status"] == "ok"
    with pytest.raises(Exception):
        m.time_to_limit(good, process="weibull")


def test_since_drops_older_readings_and_series_is_a_copy(env):
    m = _maintenance(UID)
    pid = _level(m, np.arange(1, 13) * 1.0, 2.0, above=100)
    since = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    s = m.progression_series(pid, since=since)
    assert 4 <= s["n_readings"] <= 6 and s["rows"][0]["age_days"] == 0
    assert s["csv"].splitlines()[0] == "unit,age_days,value"
    assert m.time_to_limit(pid, since=since)["status"] == "too_few"
    assert m.progression_series(pid)["n_readings"] == 12


def test_the_routes_and_the_tool_serve_it(api):
    m = _maintenance(API_UID)
    rng = np.random.default_rng(4)
    values = 1 + np.cumsum(rng.normal(1.0, 0.6, 20))
    pid = _level(m, values, 1.0, above=float(values[-1] + 30))
    got = api.get(f"/api/maintenance/signals/bands/{pid}/time-to-limit").json()
    assert got["status"] == "ok" and got["time_to_limit"]["median_days"] > 0
    ser = api.get(f"/api/maintenance/signals/bands/{pid}/degradation-series").json()
    assert ser["n_readings"] == 20
    assert api.get(f"/api/maintenance/signals/bands/{pid}/time-to-limit", params={"process": "x"}).status_code == 422
    assert api.get("/api/maintenance/signals/bands/nope/time-to-limit").status_code == 404


def test_the_maintenance_tool_has_the_actions(env):
    m = _maintenance(UID)
    pid = _level(m, 1 + np.cumsum(np.random.default_rng(6).normal(1, 0.5, 15)), 1.0, above=60)

    async def go(client):
        a = _ok(await _do(client, "maintenance", "progression.time_to_limit", point_id=pid, confidence=0.9))
        b = _ok(await _do(client, "maintenance", "progression.series", point_id=pid))
        return a, b

    a, b = _session(env["token"], go)
    assert a["status"] == "ok" and a["confidence"] == 0.9 and b["n_readings"] == 15
