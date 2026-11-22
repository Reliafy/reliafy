"""Is it safe to extrapolate an accelerated life model? SurPyval 0.29's own
numbers on the model page: the common-shape test (Diagnostics), the
activation energy, the mean life (MTTF) at the use stress with its two-sided
interval, and the median and B10 lines with their one-sided lower bounds on
the life-stress chart. Each is checked against SurPyval directly."""

import json

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pytest
import surpyval as sp
from fastapi.testclient import TestClient

from backend import alt
from backend.tests.test_alt_model_page import OWNER, _one_stress_df, session  # noqa: F401 - the fixture
from backend.tests.test_alt_temperature import _capacitors, _fit, _spec

USE_K = 313.15  # 40 °C


def _capacitor_model():
    _, payload, cid = _fit(_capacitors(), _spec("temp_C", "°C"))
    return payload, alt.get_live(cid)


def _surpyval_capacitors():
    """The same fit, made with SurPyval alone."""
    df = _capacitors()
    return sp.AcceleratedLife(sp.Weibull, sp.life_models.Arrhenius).fit(
        x=df.hours.to_numpy(), c=df.censored.to_numpy(), Z=df.temp_K.to_numpy())


def test_common_shape_test_is_surpyvals():
    payload, model = _capacitor_model()
    ref = _surpyval_capacitors().common_shape_test()
    got = alt.diagnose(model, "arrhenius", payload["stresses"], [USE_K])
    json.dumps(got)
    s = got["common_shape"]
    assert s["computed"] and s["df"] == ref["df"] == 2
    assert s["statistic"] == pytest.approx(ref["statistic"], rel=1e-6)
    assert s["p"] == pytest.approx(ref["p_value"], rel=1e-6)
    assert s["common_shape"] == pytest.approx(ref["common_shape"], rel=1e-6)
    assert s["parameter"] == "beta" and s["left_out"] == []
    assert [x["stress"] for x in s["shapes"]] == [[378.15], [398.15], [418.15]]
    for x, (_, shape) in zip(s["shapes"], ref["shapes"].items()):
        assert x["shape"] == pytest.approx(shape, rel=1e-6)
    # The same test as diagnose()'s common-shape row.
    assert s["p"] == pytest.approx(got["shape"]["p"], rel=1e-6)


def test_common_shape_test_leaves_out_a_level_with_one_failure():
    df = _capacitors()
    # The coolest level stopped early: one failure there.
    cool = df.temp_C == 105
    first = df[cool & (df.censored == 0)].hours.min()
    df.loc[cool, "censored"] = (df.loc[cool, "hours"] > first).astype(int)
    df.loc[cool & (df.censored == 1), "hours"] = first + 1.0
    _, payload, cid = _fit(df, _spec("temp_C", "°C"))
    s = alt.common_shape(alt.get_live(cid))
    assert s["computed"] and s["df"] == 1
    assert s["left_out"] == [{"stress": [378.15], "failures": 1}]
    assert [x["stress"] for x in s["shapes"]] == [[398.15], [418.15]]


def test_common_shape_test_none_for_an_exponential_and_says_why_it_cannot_run():
    df = _one_stress_df()
    _, cid = alt.fit(df, {"x": "hours", "c": "cens"}, ["kV"], "exponential", "inverse_power", "hours",
                     ["Voltage"], ["kV"])
    assert alt.common_shape(alt.get_live(cid)) is None
    # Only one level with two failures: SurPyval's reason.
    two = df[df.kV.isin([20.0, 25.0])].copy()
    two.loc[two.kV == 25.0, "cens"] = 1
    two.loc[(two.kV == 25.0) & (two.index == two[two.kV == 25.0].index[0]), "cens"] = 0
    _, cid = alt.fit(two, {"x": "hours", "c": "cens"}, ["kV"], "weibull", "inverse_power", "hours",
                     ["Voltage"], ["kV"])
    s = alt.common_shape(alt.get_live(cid))
    assert s == {"computed": False, "detail": s["detail"]} and "two stress levels" in s["detail"]


def test_activation_energy_is_surpyvals_to_four_figures():
    payload, model = _capacitor_model()
    ref = _surpyval_capacitors().activation_energy(alpha_ci=0.1)
    ea = payload["activation_energy"]
    assert ea["value"] == pytest.approx(ref["activation_energy"], rel=1e-9)
    assert ea["ci"] == pytest.approx([ref["lower"], ref["upper"]], rel=1e-9)
    assert ea["level"] == 0.9 and ea["kelvin"] == pytest.approx(ref["kelvin"])
    # The same number, to 3-4 significant figures, as the page's a × k before.
    a = next(c for c in payload["coefficients"] if c["name"] == "a")["value"]
    assert float(f"{ea['value']:.4g}") == float(f"{a * 8.617333262e-5:.4g}")
    # Eyring has one too now; an inverse power law none.
    _, eyring, _ = _fit(_capacitors(), _spec("temp_C", "°C", life_model="eyring"))
    assert eyring["activation_energy"]["value"] > 0
    df = _one_stress_df()
    payload_ip, _ = alt.fit(df, {"x": "hours", "c": "cens"}, ["kV"], "weibull", "inverse_power", "hours",
                            ["Voltage"], ["kV"])
    assert "activation_energy" not in payload_ip


def test_mean_life_at_use_is_surpyvals_with_a_two_sided_interval():
    _, model = _capacitor_model()
    ref = _surpyval_capacitors()
    Z = np.array([[USE_K]])
    ev = alt.evaluate(model, [USE_K], "arrhenius")
    m = ev["mean_life"]
    assert m["value"] == pytest.approx(float(ref.mean(Z)), rel=1e-9)
    assert ev["metrics"]["mean_life"] == m["value"]
    lo, hi = np.ravel(ref.mean_cb(Z, alpha_ci=0.1, bound="two-sided"))
    assert m["ci"] == pytest.approx([lo, hi], rel=1e-9)
    assert m["ci"][0] < m["value"] < m["ci"][1]
    assert m["level"] == 0.9 and m["bound"] == "two-sided"
    # The confidence asked for moves it.
    wide = alt.evaluate(model, [USE_K], "arrhenius", confidence=0.95)["mean_life"]
    assert wide["ci"][0] < m["ci"][0] and wide["ci"][1] > m["ci"][1]


def test_an_infinite_mean_is_never_shown(monkeypatch):
    _, model = _capacitor_model()
    monkeypatch.setattr(model, "mean", lambda Z: np.array([np.inf]))
    assert alt.mean_at_use(model, np.array([[USE_K]])) is None


def test_life_lines_carry_the_median_and_b10_with_one_sided_lower_bounds():
    _, model = _capacitor_model()
    ref = _surpyval_capacitors()
    tested = [[378.15], [398.15], [418.15]]
    ev = alt.evaluate(model, [USE_K], "arrhenius", tested=tested)
    json.dumps(ev)
    (line,) = ev["life_lines"]
    q = line["quantiles"]
    assert q["level"] == 0.9 and q["bound"] == "lower"
    G = np.asarray(line["stress"], dtype=float).reshape(-1, 1)
    for key, p in (("b50", 0.5), ("b10", 0.1)):
        probs = np.full(G.shape[0], p)
        assert q[key]["life"] == pytest.approx(np.ravel(ref.qf(probs, G)).tolist(), rel=1e-6)
        lower = np.ravel(ref.quantile_cb(probs, G, alpha_ci=0.1, bound="lower"))
        assert q[key]["lower"] == pytest.approx(lower.tolist(), rel=1e-6)
        assert all(lo < v for lo, v in zip(q[key]["lower"], q[key]["life"]))
    # The line runs to the use stress, so the B10 at 40 °C is on it.
    assert line["stress"][0] == pytest.approx(USE_K)
    assert q["b10"]["life"][0] == pytest.approx(ev["metrics"]["b10"], rel=1e-6)
    # The tested levels' marks: the median and B10 at each.
    marks = ev["tested_lives"]
    assert [t["stress"] for t in marks] == tested
    for t in marks:
        Z = np.array([t["stress"]])
        assert t["b10"] == pytest.approx(float(np.ravel(ref.qf(np.array([0.1]), Z))[0]), rel=1e-6)
        assert t["b50_lower"] < t["b50"]


def test_routes_serve_the_new_numbers(session, monkeypatch):  # noqa: F811 - the fixture
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import alt as alt_service
    from backend.services import datasets as dsvc

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    ds = dsvc.create_dataset(session, "caps.csv", _capacitors().to_csv(index=False).encode(), OWNER)
    doc = alt_service.save_model(session, "Capacitors", ds, _spec("temp_C", "°C"), OWNER)
    alt._STORE.clear()
    alt_service._LIVE.clear()
    alt_service._DIAGNOSED.clear()
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    try:
        client = TestClient(app)
        r = client.post(f"/api/alt/models/{doc.id}/evaluate", json={"use_stress": [USE_K]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mean_life"]["ci"][0] < body["mean_life"]["value"] < body["mean_life"]["ci"][1]
        assert body["activation_energy"]["value"] == pytest.approx(0.6, abs=0.15)
        assert set(body["life_lines"][0]["quantiles"]) >= {"b50", "b10"} and len(body["tested_lives"]) == 3
        r = client.post(f"/api/alt/models/{doc.id}/diagnostics", json={"use_stress": [USE_K]})
        assert r.status_code == 200, r.text
        s = r.json()["common_shape"]
        assert s["computed"] and s["df"] == 2 and 0 <= s["p"] <= 1
    finally:
        app.dependency_overrides.clear()

