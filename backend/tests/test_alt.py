import json

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import alt
from backend.fitting import FitError


def _arrhenius_df(seed=11):
    rng = np.random.default_rng(seed)
    rows = []
    for T in (320.0, 340.0, 360.0):
        life = np.exp(3600.0 / T)
        for xv in np.abs(sp.Weibull.random(30, life, 2.1)):
            rows.append({"hours": round(float(xv), 2), "tempK": T, "cens": 0})
    return pd.DataFrame(rows)


def _two_stress_df(seed=12):
    rng = np.random.default_rng(seed)
    rows = []
    for T in (330.0, 350.0):
        for V in (10.0, 20.0):
            life = max(np.exp(3000.0 / T) * (V / 10.0) ** -2.0, 1.0)
            for xv in np.abs(sp.Weibull.random(25, life, 2.0)):
                rows.append({"h": round(float(xv), 2), "T": T, "V": V})
    return pd.DataFrame(rows)


def test_single_stress_arrhenius_fit_and_extrapolate():
    payload, cid = alt.fit(
        _arrhenius_df(), {"x": "hours", "c": "cens"}, ["tempK"],
        "weibull", "arrhenius", "hours",
    )
    json.dumps(payload)  # JSON-safe
    assert payload["kind"] == "alt"
    assert payload["distribution"] == "Weibull"
    assert payload["life_model_id"] == "arrhenius"
    assert {p["name"] for p in payload["params"]} == {"beta"}
    assert {c["name"] for c in payload["coefficients"]} == {"a", "b"}
    # Characteristic life must fall as temperature rises.
    lives = [lvl["characteristic_life"] for lvl in payload["levels"]]
    assert lives == sorted(lives, reverse=True)
    assert len(payload["life_stress_plot"]["lines"]) == 1
    assert payload["life_stress_plot"]["log_y"] is True

    # Probability plot: one series per tested stress level, each with a fitted
    # line and (here, uncensored) scatter points.
    pp = payload["probability_plot"]
    assert pp is not None and pp["distribution"] == "Weibull"
    assert len(pp["series"]) == 3
    for s in pp["series"]:
        assert s["line"]["x"] and s["scatter"]["x"]
    assert pp["y_ticks"]["labels"][0].endswith("%")

    # Extrapolate below the tested stresses.
    ev = alt.evaluate(alt.get_live(cid), [300.0], "arrhenius", ref_stress=[360.0])
    json.dumps(ev)
    m = ev["metrics"]
    assert m["b1"] < m["b10"] < m["b50"] < m["mean_life"]
    # Use life (300 K) exceeds the hottest test life (360 K): AF > 1.
    assert ev["acceleration_factor"]["value"] > 1.0
    assert len(ev["curves"]["sf"]) == 300


def test_serialise_roundtrip_matches():
    payload, cid = alt.fit(_arrhenius_df(), {"x": "hours"}, ["tempK"], "weibull", "arrhenius")
    base = alt.evaluate(alt.get_live(cid), [305.0], "arrhenius")["metrics"]["mean_life"]
    restored = alt.get_live(alt.restore_live(alt.serialize_live(cid)))
    got = alt.evaluate(restored, [305.0], "arrhenius")["metrics"]["mean_life"]
    assert got == pytest.approx(base, rel=1e-9)


def test_two_stress_power_exponential():
    payload, cid = alt.fit(
        _two_stress_df(), {"x": "h"}, ["T", "V"],
        "weibull", "power_exponential", "h", ["Temperature (K)", "Voltage"],
    )
    json.dumps(payload)
    assert len(payload["stresses"]) == 2
    # One fitted line per unique secondary-stress (voltage) level.
    assert len(payload["life_stress_plot"]["lines"]) == 2
    assert payload["life_stress_plot"]["secondary_label"] == "Voltage"
    ev = alt.evaluate(alt.get_live(cid), [300.0, 5.0], "power_exponential", ref_stress=[350.0, 20.0])
    assert ev["metrics"]["mean_life"] > 0
    assert ev["acceleration_factor"]["value"] > 1.0


def test_wrong_stress_count_raises():
    with pytest.raises(FitError, match="stress column"):
        alt.fit(_arrhenius_df(), {"x": "hours"}, ["tempK"], "weibull", "power_exponential")


def test_unknown_ids_raise():
    with pytest.raises(FitError, match="Unknown ALT distribution"):
        alt.fit(_arrhenius_df(), {"x": "hours"}, ["tempK"], "nope", "arrhenius")
    with pytest.raises(FitError, match="life-stress model"):
        alt.fit(_arrhenius_df(), {"x": "hours"}, ["tempK"], "weibull", "nope")


def test_missing_columns_raise():
    df = _arrhenius_df()
    with pytest.raises(FitError, match="failure-time column"):
        alt.fit(df, {}, ["tempK"], "weibull", "arrhenius")
    with pytest.raises(FitError, match="[Ss]tress column"):
        alt.fit(df, {"x": "hours"}, ["missing"], "weibull", "arrhenius")


@pytest.fixture()
def session(monkeypatch):
    import mongomock

    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def test_service_save_persist_rehydrate_evaluate(session, monkeypatch):
    """Saving an ALT model persists the serialised fit; evaluate rehydrates it
    without re-fitting from the dataset."""
    from backend.services import datasets as dsvc
    from backend.services import alt as alt_service

    OWNER = "user-a"
    csv = _arrhenius_df().to_csv(index=False).encode()
    ds = dsvc.create_dataset(session, "alt.csv", csv, OWNER)
    spec = {
        "mapping": {"x": "hours", "c": "cens"},
        "stress_cols": ["tempK"],
        "stress_labels": ["Temperature (K)"],
        "distribution_id": "weibull",
        "life_model_id": "arrhenius",
        "unit": "hours",
    }
    doc = alt_service.save_model(session, "Seal ALT", ds, spec, OWNER)
    assert session.alt_models.find_one({"_id": doc.id})["serialized"], "fit should be persisted"
    assert doc.results["functions"]["evaluate_path"] == f"/api/alt/models/{doc.id}/evaluate"

    base = alt_service.evaluate(session, doc.id, [300.0], OWNER, ref_stress=[360.0])
    assert base["acceleration_factor"]["value"] > 1.0

    # Wipe the live cache and forbid re-fitting — the serialised path must serve.
    alt._STORE.clear()
    alt_service._LIVE.clear()
    monkeypatch.setattr(alt_service, "_refit",
                        lambda *a, **k: pytest.fail("refit called — serialisation path failed"))
    again = alt_service.evaluate(session, doc.id, [300.0], OWNER)
    assert again["metrics"]["mean_life"] == pytest.approx(base["metrics"]["mean_life"], rel=1e-9)
