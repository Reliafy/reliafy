"""Download as Python for accelerated life models: the script refits the
saved model from its data (embedded) and prints the page's numbers, which
must equal the app's — the shape and coefficients with their 90% intervals,
the life at each tested level, and (with a use stress) the Calculator's life
and B-lives."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp
from fastapi.testclient import TestClient

from backend.tests.python_scripts import close, run

OWNER = "user-alt-export"
OTHER = "user-alt-export-other"


@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    who = {"uid": OWNER}
    app.dependency_overrides[get_current_user] = lambda: {"uid": who["uid"], "email": f"{who['uid']}@x.org",
                                                          "name": who["uid"]}
    c = TestClient(app)
    c.who = who
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _volts(seed=21):
    """One stress (kV), some still running, with a count column."""
    rng = np.random.default_rng(seed)
    rows = []
    for v in (20.0, 25.0, 30.0, 35.0):
        life = 5e6 * v ** -3.0
        times = life * rng.weibull(1.8, 12)
        for i, t in enumerate(times):
            cens = 1 if i >= 10 else 0
            rows.append({"hours": round(float(t if not cens else times.max() * 1.1), 3), "kV": v, "cens": cens,
                         "units": 1 + (i % 2)})
    return pd.DataFrame(rows)


def _celsius(seed=11):
    """Temperatures in °C: the app fits them in kelvin."""
    np.random.seed(seed)
    rows = []
    for c in (60.0, 80.0, 100.0):
        life = 0.05 * np.exp(4000.0 / (c + 273.15))
        for xv in np.abs(sp.Weibull.random(15, life, 2.2)):
            rows.append({"hours": round(float(xv), 3), "temp_C": c})
    return pd.DataFrame(rows)


def _two_stress(seed=12):
    np.random.seed(seed)
    rows = []
    for T in (330.0, 350.0, 370.0):
        for V in (10.0, 20.0):
            life = max(np.exp(3000.0 / T) * (V / 10.0) ** -2.0, 1.0)
            for xv in np.abs(sp.Weibull.random(12, life, 2.0)):
                rows.append({"h": round(float(xv), 2), "T": T, "V": V})
    return pd.DataFrame(rows)


def _inspected(seed=5):
    """Inspection data: each failure between two looks; blank upper = running."""
    df = _volts(seed)
    lo = (np.floor(df["hours"] / 50.0) * 50.0).astype(float)
    hi = lo + 50.0
    hi[df["cens"] == 1] = np.nan
    return pd.DataFrame({"lo": lo, "hi": hi, "kV": df["kV"]})


def _truncated(seed=8):
    df = _volts(seed)
    df["entered"] = np.where(np.arange(len(df)) % 5 == 0, 5.0, np.nan)
    return df


CASES = {
    "inverse_power_weibull_counts": (_volts, {"x": "hours", "c": "cens", "n": "units", "s1": "kV",
                                              "s1_label": "Voltage", "s1_unit": "kV",
                                              "life_model": "inverse_power", "distribution": "weibull"}, [12.0]),
    "arrhenius_celsius_lognormal": (_celsius, {"x": "hours", "s1": "temp_C", "s1_unit": "°C",
                                               "life_model": "arrhenius", "distribution": "lognormal"}, [313.15]),
    "eyring_kelvin_gamma": (lambda: _celsius().assign(tK=lambda d: d.temp_C + 273.15),
                            {"x": "hours", "s1": "tK", "s1_unit": "K", "life_model": "eyring",
                             "distribution": "gamma"}, None),
    "two_stress_power_exponential": (_two_stress, {"x": "h", "s1": "T", "s2": "V", "s1_unit": "K", "s2_unit": "V",
                                                   "life_model": "power_exponential", "distribution": "weibull"},
                                     [300.0, 5.0]),
    "dual_power_normal": (_two_stress, {"x": "h", "s1": "T", "s2": "V", "life_model": "dual_power",
                                        "distribution": "normal"}, None),
    "inspection_intervals": (_inspected, {"xl": "lo", "xr": "hi", "s1": "kV", "life_model": "inverse_power",
                                          "distribution": "weibull"}, [15.0]),
    "truncated_exponential_linear": (_truncated, {"x": "hours", "c": "cens", "tl": "entered", "s1": "kV",
                                                  "life_model": "linear", "distribution": "exponential"}, None),
}


def _save(client, make, form) -> dict:
    csv = make().to_csv(index=False).encode()
    r = client.post("/api/alt/models", data={**form, "name": "Bench test", "unit": "hours"},
                    files={"file": ("alt.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_script_prints_the_pages_numbers(client, tmp_path, case):
    make, form, use = CASES[case]
    saved = _save(client, make, form)
    mid = saved["id"]
    page = client.get(f"/api/alt/models/{mid}").json()["results"]

    py = client.get(f"/api/alt/models/{mid}/export.py")
    assert py.status_code == 200, py.text
    assert py.headers["content-disposition"].endswith('.py"')
    source = py.text
    assert "requirements: surpyval==" in source and "AcceleratedLife(" in source
    if use is not None:
        source = source.replace("USE_STRESS = None", f"USE_STRESS = {use!r}", 1)
    out = run(source, tmp_path)

    for p in [*page["params"], *page["coefficients"]]:
        got = out[p["name"]]
        close(got["value"], p["value"])
        if p["ci"] is None:
            assert got["low"] is None
        else:
            close(got["low"], p["ci"][0])
            close(got["high"], p["ci"][1])
    for lvl in page["levels"]:
        names = [s["label"] for s in page["stresses"]]
        where = ", ".join(f"{n} {v:.6g}" for n, v in zip(names, lvl["stress"]))
        close(out[f"Life at {where}"]["value"], lvl["characteristic_life"])

    if use is not None:
        ev = client.post(f"/api/alt/models/{mid}/evaluate", json={"use_stress": use}).json()
        life = out["Life at the use stress"]
        close(life["value"], ev["metrics"]["characteristic_life"])
        ci = ev["bounds"]["characteristic_life"]["ci"]
        close(life["low"], ci[0])
        close(life["high"], ci[1])
        close(out["B50 at the use stress"]["value"], ev["metrics"]["b50"])
        for key, label in (("b10", "B10"), ("b1", "B1")):
            got = out[f"{label} at the use stress"]
            close(got["value"], ev["bounds"]["b_lives"][key]["value"])
            close(got["bound"], ev["bounds"]["b_lives"][key]["lower"])


def test_a_celsius_temperature_is_embedded_in_kelvin_and_says_so(client):
    make, form, _ = CASES["arrhenius_celsius_lognormal"]
    mid = _save(client, make, form)["id"]
    text = client.get(f"/api/alt/models/{mid}/export.py").text
    assert "converted from °C to kelvin" in text
    assert "333.14999" in text or "333.15" in text  # 60 °C


def test_another_users_model_is_not_found_and_a_deleted_dataset_is_refused(client):
    make, form, _ = CASES["inverse_power_weibull_counts"]
    saved = _save(client, make, form)
    client.who["uid"] = OTHER
    assert client.get(f"/api/alt/models/{saved['id']}/export.py").status_code == 404
    client.who["uid"] = OWNER
    from backend import db

    db._db.datasets.delete_many({})
    r = client.get(f"/api/alt/models/{saved['id']}/export.py")
    assert r.status_code == 422 and "deleted" in r.json()["detail"]
