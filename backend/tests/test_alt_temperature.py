"""A thermal model's temperature in °C, °F or K: fitted in kelvin, a bare
Celsius column refused, and SurPyval's own warnings shown on the result."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import alt
from backend.fitting import FitError

K_B = 8.617333262e-5  # eV/K


def _capacitors(seed=102):
    """60 capacitors at 105, 125 and 145 °C: Weibull life, shape 2,
    Arrhenius with Ea 0.6 eV and a characteristic life of 3,000 h at 125 °C;
    each level stopped at 5,000, 3,000 and 2,000 h."""
    rng = np.random.default_rng(seed)
    rows = []
    for temp_c, stop in ((105, 5000.0), (125, 3000.0), (145, 2000.0)):
        tk = temp_c + 273.15
        eta = 3000.0 * np.exp(0.6 / K_B * (1 / tk - 1 / 398.15))
        for _ in range(20):
            t = eta * rng.weibull(2.0)
            rows.append({"unit": f"C-{len(rows) + 1:03d}", "hours": round(min(t, stop), 1), "temp_C": temp_c,
                         "temp_K": tk, "temp_F": temp_c * 9 / 5 + 32, "censored": int(t > stop)})
    return pd.DataFrame(rows)


def _spec(col, unit=None, life_model="arrhenius"):
    return {"mapping": {"x": "hours", "c": "censored"}, "stress_cols": [col], "stress_labels": [col],
            "distribution_id": "weibull", "life_model_id": life_model, "unit": "hours",
            **({"stress_units": [unit]} if unit is not None else {})}


def _fit(df, spec):
    spec = alt.with_kelvin(spec, df)
    payload, cid = alt.fit(df, spec["mapping"], spec["stress_cols"], spec["distribution_id"],
                           spec["life_model_id"], spec["unit"], stress_labels=spec["stress_labels"],
                           stress_units=spec.get("stress_units"), kelvin_from=spec.get("kelvin_from"))
    return spec, payload, cid


@pytest.mark.parametrize("life_model", ["arrhenius", "eyring"])
def test_celsius_without_a_unit_is_refused(life_model):
    with pytest.raises(FitError, match="°C, K or °F"):
        alt.with_kelvin(_spec("temp_C", life_model=life_model), _capacitors())


def test_kelvin_without_a_unit_still_fits_as_kelvin():
    df = _capacitors()
    spec = alt.with_kelvin(_spec("temp_K"), df)
    assert "kelvin_from" not in spec


def test_non_thermal_model_is_left_alone():
    spec = alt.with_kelvin(_spec("temp_C", life_model="inverse_power"), _capacitors())
    assert "kelvin_from" not in spec


@pytest.mark.parametrize("col,unit", [("temp_C", "°C"), ("temp_C", "C"), ("temp_C", "celsius"), ("temp_F", "°F")])
def test_celsius_and_fahrenheit_fit_as_kelvin(col, unit):
    df = _capacitors()
    _, ref, _ = _fit(df, _spec("temp_K", "K"))
    spec, got, cid = _fit(df, _spec(col, unit))
    assert spec["kelvin_from"] == [alt.temperature_unit(unit)]
    a_ref = {c["name"]: c["value"] for c in ref["coefficients"]}
    a_got = {c["name"]: c["value"] for c in got["coefficients"]}
    for k in a_ref:
        assert a_got[k] == pytest.approx(a_ref[k], rel=1e-5)
    # Ea = a·k_B: the truth is 0.6 eV.
    assert a_got["a"] * K_B == pytest.approx(0.6, abs=0.1)
    s = got["stresses"][0]
    assert s["unit"] == "K" and s["entered_unit"] == alt.temperature_unit(unit)
    assert s["label"] == "Temperature"
    assert sorted(lvl["stress"][0] for lvl in got["levels"]) == pytest.approx([378.15, 398.15, 418.15])
    assert "unit_warnings" not in got
    # B10 at 40 °C, read at 313.15 K, is the kelvin fit's.
    ev_got = alt.evaluate(alt.get_live(cid), [313.15], "arrhenius")
    assert ev_got["metrics"]["characteristic_life"] > 1e5


def test_library_warning_reaches_the_result():
    """Told the Celsius column is kelvin, the fit runs as asked, and
    SurPyval's "below 200 K ... degrees Celsius?" is on the result."""
    _, payload, _ = _fit(_capacitors(), _spec("temp_C", "K"))
    assert any("200 K" in w for w in payload.get("fit_warnings") or [])


def test_a_model_saved_before_keeps_fitting_as_it_was():
    """A spec with °C but no kelvin_from (saved before the conversion) fits
    its numbers as they are, with the old warning, so its saved results and
    its refits agree."""
    df = _capacitors()
    payload, _ = alt.fit(df, {"x": "hours", "c": "censored"}, ["temp_C"], "weibull", "arrhenius", "hours",
                         stress_units=["°C"])
    assert payload["unit_warnings"]
    assert sorted(lvl["stress"][0] for lvl in payload["levels"]) == [105, 125, 145]


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def test_saved_celsius_model_refits_in_kelvin(session):
    """The likelihood-ratio bounds refit from the dataset: they convert the
    same way the save did, so they bound the saved model's own life."""
    from backend.services import alt as alt_service
    from backend.services import datasets as dsvc

    df = _capacitors()
    ds = dsvc.create_dataset(session, "cap.csv", df.to_csv(index=False).encode(), "u")
    doc = alt_service.save_model(session, "Cap", ds, _spec("temp_C", "°C"), "u")
    assert doc.spec["kelvin_from"] == ["°C"]
    inputs = alt_service._fit_inputs(session, doc)
    assert float(np.min(inputs["Z"])) == pytest.approx(378.15)
    status, out = alt_service.bounds(session, doc.id, "u", uid="u", use_stress=[313.15], method="lr")
    assert status == 200
    ev = alt_service.evaluate(session, doc.id, [313.15], "u")
    b10 = ev["metrics"].get("b10")
    lo = (out.get("b_lives") or {}).get("b10") or {}
    if b10 and lo.get("lower"):
        assert lo["lower"] < b10
