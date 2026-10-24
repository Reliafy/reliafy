"""The accelerated life model page's data: each tested level's failures and
own fit, a two-stress model's second life-stress chart, the life-stress line
to the use stress, and the Diagnostics checks (SurPyval's diagnose())."""

import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp
from fastapi.testclient import TestClient

from backend import alt
from backend.fitting import FitError

OWNER = "user-alt-page"


def _one_stress_df(seed=21):
    rng = np.random.default_rng(seed)
    rows = []
    for v in (20.0, 25.0, 30.0, 35.0):
        life = 5e6 * v ** -3.0
        times = life * rng.weibull(1.8, 14)
        for i, t in enumerate(times):
            # Two units at each level still running at the end.
            cens = 1 if i >= 12 else 0
            rows.append({"hours": round(float(t if not cens else times.max() * 1.1), 3), "kV": v, "cens": cens})
    return pd.DataFrame(rows)


def _two_stress_df(seed=12):
    rows = []
    np.random.seed(seed)
    for T in (330.0, 350.0, 370.0):
        for V in (10.0, 20.0):
            life = max(np.exp(3000.0 / T) * (V / 10.0) ** -2.0, 1.0)
            for xv in np.abs(sp.Weibull.random(12, life, 2.0)):
                rows.append({"h": round(float(xv), 2), "T": T, "V": V})
    return pd.DataFrame(rows)


def _fit_one(**kw):
    return alt.fit(_one_stress_df(), {"x": "hours", "c": "cens"}, ["kV"], kw.get("dist", "weibull"),
                   "inverse_power", "hours", ["Voltage"], ["kV"])


def _fit_two():
    return alt.fit(_two_stress_df(), {"x": "h"}, ["T", "V"], "weibull", "power_exponential", "hours",
                   ["Temperature", "Voltage"], ["K", "V"])


# ---- The fit's payload ---------------------------------------------------------------------

def test_levels_carry_their_failures_and_own_fit():
    payload, _ = _fit_one()
    json.dumps(payload)
    assert [lvl["n"] for lvl in payload["levels"]] == [14, 14, 14, 14]
    # The two units still running at each level are not failures.
    assert [lvl["failures"] for lvl in payload["levels"]] == [12, 12, 12, 12]
    assert payload["n_failures"] == 48
    df = _one_stress_df()
    for lvl in payload["levels"]:
        sub = df[df.kV == lvl["stress"][0]]
        own = sp.Weibull.fit(sub.hours.to_numpy(), c=sub.cens.to_numpy())
        assert lvl["own"]["life"] == pytest.approx(own.params[0], rel=1e-6)
        (shape,) = lvl["own"]["shape"]
        assert shape["name"] == "beta" and shape["value"] == pytest.approx(own.params[1], rel=1e-6)
        lo, hi = shape["ci"]
        assert lo < shape["value"] < hi
    # One stress: one chart only.
    assert "life_stress_plot_2" not in payload


def test_a_level_with_fewer_than_two_failures_has_no_own_fit():
    df = _one_stress_df()
    # Every unit at 20 kV but one still running.
    mask = df.kV == 20.0
    df.loc[mask, "cens"] = 1
    df.loc[df.index[mask][0], "cens"] = 0
    payload, _ = alt.fit(df, {"x": "hours", "c": "cens"}, ["kV"], "weibull", "inverse_power", "hours")
    first = payload["levels"][0]
    assert first["stress"] == [20.0] and first["failures"] == 1 and "own" not in first
    assert all("own" in lvl for lvl in payload["levels"][1:])


def test_two_stresses_give_a_chart_along_each():
    payload, cid = _fit_two()
    a, b = payload["life_stress_plot"], payload["life_stress_plot_2"]
    assert a["x_label"] == "Temperature (K)" and a["secondary_label"] == "Voltage (V)"
    assert b["x_label"] == "Voltage (V)" and b["secondary_label"] == "Temperature (K)"
    # A line per tested level of the other stress, and every tested level as a point.
    assert sorted(ln["secondary"] for ln in a["lines"]) == [10.0, 20.0]
    assert sorted(ln["secondary"] for ln in b["lines"]) == [330.0, 350.0, 370.0]
    assert len(a["points"]) == len(b["points"]) == 6
    model = alt.get_live(cid)
    for p in b["points"]:
        z = np.array([[p["secondary"], p["stress"]]])
        assert p["life"] == pytest.approx(float(model.phi(z)[0]), rel=1e-9)
    # Each of chart B's lines is the model's life along the second stress.
    ln = b["lines"][0]
    z = np.column_stack([np.full(len(ln["stress"]), ln["secondary"]), ln["stress"]])
    assert np.allclose(ln["life"], np.ravel(model.phi(z)), rtol=1e-9)
    assert min(ln["stress"]) < 10.0 < 20.0 < max(ln["stress"])


# ---- The life-stress line to the use stress --------------------------------------------------

def test_evaluate_draws_the_line_to_the_use_stress():
    payload, cid = _fit_one()
    model = alt.get_live(cid)
    ev = alt.evaluate(model, [12.0], "inverse_power")
    (line,) = ev["life_lines"]
    assert line["stress"][0] == pytest.approx(12.0)
    assert line["life"][0] == pytest.approx(ev["metrics"]["characteristic_life"], rel=1e-9)
    assert max(line["stress"]) > 35.0
    # A rehydrated model has no data: the tested levels say where the line runs.
    restored = alt.get_live(alt.restore_live(alt.serialize_live(cid)))
    assert "life_lines" not in alt.evaluate(restored, [12.0], "inverse_power")
    tested = [lvl["stress"] for lvl in payload["levels"]]
    again = alt.evaluate(restored, [12.0], "inverse_power", tested=tested)["life_lines"][0]
    assert np.allclose(again["life"], line["life"], rtol=1e-6)


def test_evaluate_two_stresses_holds_the_other_at_its_use_value():
    _, cid = _fit_two()
    model = alt.get_live(cid)
    ev = alt.evaluate(model, [300.0, 5.0], "power_exponential")
    along_t, along_v = ev["life_lines"]
    assert along_t["stress"][0] == pytest.approx(300.0) and along_v["stress"][0] == pytest.approx(5.0)
    life_use = ev["metrics"]["characteristic_life"]
    assert along_t["life"][0] == pytest.approx(life_use, rel=1e-9)
    assert along_v["life"][0] == pytest.approx(life_use, rel=1e-9)
    z = np.column_stack([np.full(len(along_v["stress"]), 300.0), along_v["stress"]])
    assert np.allclose(along_v["life"], np.ravel(model.phi(z)), rtol=1e-9)


# ---- The Diagnostics checks ------------------------------------------------------------------

def test_diagnose_reads_surpyvals_checks_in_the_apps_words():
    payload, cid = _fit_two()
    model = alt.get_live(cid)
    params, shape = np.array(model.params), np.shape(model.data.Z)
    ref = model.diagnose(use_stress=[300.0, 5.0])
    got = alt.diagnose(model, "power_exponential", payload["stresses"], [300.0, 5.0])
    # The checks refit copies: the live model (shared by the page's calls) is untouched.
    assert np.array_equal(np.array(model.params), params) and np.shape(model.data.Z) == shape
    json.dumps(got)
    table = ref.table
    shape = table[table.check == "common_shape"].iloc[0]
    assert got["shape"]["p"] == pytest.approx(float(shape.p)) and got["shape"]["verdict"] == shape.verdict
    life = table[table.check == "life_stress"].iloc[0]
    assert got["life_stress"]["p"] == pytest.approx(float(life.p)) and got["life_stress"]["computed"]
    # The comparison: the fitted model first, named as the app names it.
    first, *others = got["comparison"]
    assert first["current"] and first["name"] == "Temperature–nonthermal" and first["delta"] == 0
    assert first["life_model_id"] == "power_exponential"
    names = {c["name"]: c for c in others}
    assert {"Dual power", "Dual exponential (temp–humidity)", "General log-linear"} <= set(names)
    assert names["General log-linear"]["life_model_id"] is None
    # Each one's life at the use stress, read from the report.
    life_use = float(np.ravel(model.phi(np.array([[300.0, 5.0]])))[0])
    assert first["life_at_use"] == pytest.approx(life_use, rel=5e-3)
    assert all(c["life_at_use"] and c["life_at_use"] > 0 for c in others)
    # How far the use stress is, per stress, labelled with the stress's own name and unit.
    t, v = got["extrapolation"]
    assert t["label"] == "Temperature (K)" and t["levels"] == 3 and t["low"] == 330.0 and t["high"] == 370.0
    assert v["label"] == "Voltage (V)" and v["levels"] == 2 and v["levels_verdict"] == "warn"
    assert t["use"] == 300.0 and t["distance"] > 0 and t["use_verdict"] in ("ok", "warn")
    assert not any("PowerExponential" in n or "GeneralLogLinear" in n for n in got["notes"])


def test_diagnose_without_a_use_stress_and_with_no_shape():
    payload, cid = _fit_one(dist="exponential")
    got = alt.diagnose(alt.get_live(cid), "inverse_power", payload["stresses"])
    assert got["use_stress"] is None and got["shape"] is None
    (only,) = got["extrapolation"]
    assert only["levels"] == 4 and "distance" not in only
    assert got["comparison"][0]["life_at_use"] is None
    with pytest.raises(FitError, match="Use-stress dimensions"):
        alt.diagnose(alt.get_live(cid), "inverse_power", payload["stresses"], [1.0, 2.0])


def test_diagnose_needs_the_data():
    _, cid = _fit_one()
    restored = alt.get_live(alt.restore_live(alt.serialize_live(cid)))
    with pytest.raises(FitError, match="need the data"):
        alt.diagnose(restored, "inverse_power", [])


def test_plain_names_replace_whole_words_only():
    assert alt._plain_text("the InversePower model and Power") == "the Inverse power law model and Inverse power law"
    assert alt._plain_text("PowerExponential beats DualPower") == "Temperature–nonthermal beats Dual power"
    assert alt._plain_text("Exponential, not Exponentials") == "Arrhenius, not Exponentials"


# ---- The service and the route ---------------------------------------------------------------

@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _save(session):
    from backend.services import alt as alt_service
    from backend.services import datasets as dsvc

    ds = dsvc.create_dataset(session, "alt.csv", _one_stress_df().to_csv(index=False).encode(), OWNER)
    spec = {"mapping": {"x": "hours", "c": "cens"}, "stress_cols": ["kV"], "stress_labels": ["Voltage"],
            "stress_units": ["kV"], "distribution_id": "weibull", "life_model_id": "inverse_power",
            "unit": "hours"}
    return alt_service.save_model(session, "Insulation", ds, spec, OWNER)


def test_service_refits_a_rehydrated_model_and_keeps_the_answer(session, monkeypatch):
    from backend.services import alt as alt_service
    from backend.services import datasets as dsvc

    doc = _save(session)
    alt._STORE.clear()
    alt_service._LIVE.clear()
    alt_service._DIAGNOSED.clear()
    first = alt_service.diagnose(session, doc.id, OWNER, use_stress=[15.0])
    assert first["extrapolation"][0]["label"] == "Voltage (kV)" and first["use_stress"] == [15.0]
    # Asked again: answered from memory, nothing refitted.
    monkeypatch.setattr(alt, "diagnose", lambda *a, **k: pytest.fail("diagnosed twice"))
    assert alt_service.diagnose(session, doc.id, OWNER, use_stress=[15.0]) is first
    monkeypatch.undo()
    # The dataset gone: the checks say why they can't run.
    alt._STORE.clear()
    alt_service._LIVE.clear()
    alt_service._DIAGNOSED.clear()
    dsvc.delete_dataset(session, doc.dataset_id, OWNER)
    with pytest.raises(FitError, match="dataset this model was fitted to was deleted"):
        alt_service.diagnose(session, doc.id, OWNER)


def test_service_evaluate_draws_the_line_for_a_rehydrated_model(session):
    from backend.services import alt as alt_service

    doc = _save(session)
    alt._STORE.clear()
    alt_service._LIVE.clear()
    ev = alt_service.evaluate(session, doc.id, [12.0], OWNER)
    assert ev["life_lines"][0]["stress"][0] == pytest.approx(12.0)


def test_route_serves_the_checks(session, monkeypatch):
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    doc = _save(session)
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    try:
        client = TestClient(app)
        r = client.post(f"/api/alt/models/{doc.id}/diagnostics", json={"use_stress": [15.0]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["shape"]["verdict"] in ("ok", "warn", "fail") and body["comparison"][0]["current"]
        r = client.post(f"/api/alt/models/{doc.id}/diagnostics", json={})
        assert r.status_code == 200 and r.json()["use_stress"] is None
        r = client.post(f"/api/alt/models/{doc.id}/diagnostics", json={"use_stress": [1.0, 2.0]})
        assert r.status_code == 422 and "dimensions" in r.json()["detail"]
        assert client.post("/api/alt/models/nope/diagnostics", json={}).status_code == 404
        r = client.post(f"/api/alt/models/{doc.id}/evaluate", json={"use_stress": [12.0]})
        assert r.status_code == 200 and r.json()["life_lines"][0]["stress"][0] == pytest.approx(12.0)
    finally:
        app.dependency_overrides.clear()


def test_a_model_with_no_finite_maximum_is_not_checked(session):
    from backend.services import alt as alt_service

    doc = _save(session)
    session.alt_models.update_one({"_id": doc.id}, {"$set": {"results.no_finite_maximum": {"message": "x"}}})
    with pytest.raises(FitError, match="finite maximum"):
        alt_service.diagnose(session, doc.id, OWNER)


def test_an_older_sample_is_refitted_once_for_the_model_page(session):
    """A sample ALT model seeded before the model page carries no failures per
    level: seeding refits it once, then leaves it be."""
    from backend.services import samples

    samples.seed_samples(session)
    doc = session.alt_models.find_one({"_id": "sample-alt-seal"})
    assert doc["results"]["levels"][0]["failures"] >= 1 and "life_stress_plot_2" in doc["results"]
    old_levels = [{k: v for k, v in lvl.items() if k not in ("failures", "own")} for lvl in doc["results"]["levels"]]
    session.alt_models.update_one({"_id": "sample-alt-seal"}, {"$set": {"results.levels": old_levels},
                                                               "$unset": {"results.life_stress_plot_2": 1}})
    samples.seed_samples(session)
    again = session.alt_models.find_one({"_id": "sample-alt-seal"})
    assert "failures" in again["results"]["levels"][0] and "life_stress_plot_2" in again["results"]
