"""Adjust for conditions: a life model with a known hazard ratio (SurPyval's ``hr``).

The adjusted model is a new saved model that records its original and the ratio; the
original is unchanged. Its numbers are SurPyval's: B-life bounds hold the ratio fixed,
and the mean life's bound, which SurPyval refuses with a ratio, is said to be missing.
"""
import math

import mongomock
import numpy as np
import pytest

pytestmark = pytest.mark.usefixtures("mcp_on")

WEIBULL = [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]
# Times from a Weibull(1000, 2), with a few still running.
TIMES = [212, 340, 410, 488, 530, 611, 702, 760, 845, 910, 1010, 1140, 1290, 1500]
CSV = "time,c\n" + "\n".join(f"{t},{1 if i % 5 == 4 else 0}" for i, t in enumerate(TIMES)) + "\n"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.main import app
    from backend.services import models as models_service

    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_adjust"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    models_service._LIVE.clear()
    tc = TestClient(app)
    tc.db = test_db
    return tc


def _params_model(client, distribution="weibull", params=WEIBULL, name="Pump"):
    r = client.post("/api/models/from-params",
                    json={"name": name, "distribution": distribution, "unit": "hours", "params": params})
    assert r.status_code == 200, r.text
    return r.json()


def _fitted_model(client, name="Bearings"):
    r = client.post("/api/models", data={"name": name, "distribution": "weibull", "x": "time", "c": "c",
                                         "unit": "hours"},
                    files={"file": ("bearings.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def _b10(life):
    return next(b for b in life["b_lives"] if b["label"] == "B10")


def test_the_hand_check_b10_at_a_hazard_ratio_of_1_5(client):
    # B10 = alpha * (-ln 0.9 / hr) ** (1 / beta): 265.0 h at hr 1.5, against 324.6 h unadjusted.
    m = _params_model(client)
    r = client.post(f"/api/models/{m['id']}/adjust", json={"hazard_ratio": 1.5})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["before"]["b10"] == pytest.approx(1000 * (-math.log(0.9)) ** 0.5, rel=1e-9)
    assert got["before"]["b10"] == pytest.approx(324.59, abs=0.01)
    assert got["after"]["b10"] == pytest.approx(1000 * (-math.log(0.9) / 1.5) ** 0.5, rel=1e-9)
    assert got["after"]["b10"] == pytest.approx(265.03, abs=0.01)
    # A Weibull with hr is the Weibull at scale alpha * hr ** (-1 / beta): its mean in closed form.
    assert got["after"]["mean"] == pytest.approx(1000 * 1.5 ** -0.5 * math.gamma(1.5), rel=1e-9)
    assert got["default_name"] == "Pump (×1.5 hazard)"
    assert "same" in got["assumes"] and got["life_scale_note"] is None
    assert client.db.models.count_documents({}) == 1  # a preview saves nothing


def test_saved_it_is_a_new_model_recording_its_original_and_the_original_is_unchanged(client):
    m = _params_model(client)
    r = client.post(f"/api/models/{m['id']}/adjust", json={"hazard_ratio": 1.5, "save": True})
    assert r.status_code == 200, r.text
    child = r.json()
    assert child["id"] != m["id"] and child["name"] == "Pump (×1.5 hazard)"
    res = child["results"]
    assert res["extras"]["hr"] == 1.5
    assert res["adjusted"]["from_model_id"] == m["id"] and res["adjusted"]["hazard_ratio"] == 1.5
    assert child["spec"]["adjusted"]["from_name"] == "Pump"
    assert _b10(res["life"])["value"] == pytest.approx(265.03, abs=0.01)
    # Its calculator answers with the ratio too.
    ev = client.post(f"/api/models/{child['id']}/evaluate", json={"values": [500]})
    assert ev.status_code == 200, ev.text
    parent = client.get(f"/api/models/{m['id']}").json()
    assert "hr" not in (parent["results"].get("extras") or {})
    assert _b10(parent["results"]["life"])["value"] == pytest.approx(324.59, abs=0.01)


def test_a_fitted_model_keeps_its_fit_and_the_b_life_bounds_hold_the_ratio_fixed(client):
    import surpyval as sp

    m = _fitted_model(client)
    r = client.post(f"/api/models/{m['id']}/adjust", json={"hazard_ratio": 1.5, "save": True})
    assert r.status_code == 200, r.text
    child = r.json()
    res = child["results"]
    assert res["plot"] is None and res["gof"] == []  # the original's fit to its data, not this curve's
    b10 = _b10(res["life"])
    # The same fit with hr set: SurPyval's own Wald bound on the quantile, hr held fixed.
    x = np.array(TIMES, dtype=float)
    c = np.array([1 if i % 5 == 4 else 0 for i in range(len(TIMES))])
    fit = sp.Weibull.fit(x, c=c)
    d = fit.to_dict()
    d["hr"] = 1.5
    hot = sp.from_dict(d)
    assert b10["value"] == pytest.approx(float(hot.qf(0.1)), rel=1e-6)
    assert b10["lower"] == pytest.approx(float(np.ravel(hot.quantile_cb(np.array([0.1]), alpha_ci=0.1,
                                                                       bound="lower"))[0]), rel=1e-4)
    assert b10["lower"] < b10["value"]
    # SurPyval refuses the mean life's bound with a hazard ratio: no number, said in words.
    assert res["life"]["mttf"]["lower"] is None
    assert "hazard ratio" in res["life"]["mttf"]["note"]
    # The calculator's band, from the restored fit.
    cb = client.post(f"/api/models/{child['id']}/confidence", json={"on": "sf", "values": [500]})
    assert cb.status_code == 200, cb.text
    # Brought back from its saved fit, or (with none saved) refitted from the data with the ratio set again.
    from backend.services import models as models_service

    for drop_saved in (False, True):
        models_service._LIVE.clear()
        if drop_saved:
            client.db.models.update_one({"_id": child["id"]}, {"$set": {"serialized": None}})
        life = client.post(f"/api/models/{child['id']}/life", json={}).json()
        assert _b10(life)["value"] == pytest.approx(b10["value"], rel=1e-9)
        assert _b10(life)["lower"] == pytest.approx(b10["lower"], rel=1e-6)
    # Refitting it in place would drop the ratio: refused, saying what to do.
    with pytest.raises(Exception, match="refit the original"):
        models_service.update_fit(client.db, child["id"], child_owner(client, child), "weibull", {"x": "time", "c": "c"}, [], None,
                                  "hours", None)


def test_a_life_scale_is_converted_exactly_for_a_weibull_and_refused_where_it_isnt_exact(client):
    m = _params_model(client)
    got = client.post(f"/api/models/{m['id']}/adjust", json={"life_scale": 2 / 3}).json()
    assert got["hazard_ratio"] == pytest.approx((2 / 3) ** -2)
    # Lasting 2/3 as long: every B-life 2/3 of the original's.
    assert got["after"]["b10"] == pytest.approx(got["before"]["b10"] * 2 / 3, rel=1e-9)
    ln = _params_model(client, "lognormal", [{"name": "mu", "value": 7}, {"name": "sigma", "value": 0.5}], "Seal")
    r = client.post(f"/api/models/{ln['id']}/adjust", json={"life_scale": 0.5})
    assert r.status_code == 422 and "hazard ratio itself" in r.json()["detail"]
    ok = client.post(f"/api/models/{ln['id']}/adjust", json={"hazard_ratio": 2}).json()
    assert ok["life_scale_note"] and ok["after"]["b10"] < ok["before"]["b10"]


@pytest.mark.parametrize("body", [{"hazard_ratio": 0}, {"hazard_ratio": -1}, {}, {"hazard_ratio": 1.5, "life_scale": 0.5}])
def test_bad_ratios_are_refused_in_words(client, body):
    m = _params_model(client)
    r = client.post(f"/api/models/{m['id']}/adjust", json=body)
    assert r.status_code == 422
    assert "hazard ratio" in r.json()["detail"]


def test_an_adjusted_model_goes_into_an_rbd_with_its_ratio(client):
    from backend.services import rbd_analysis, rbd_graph

    m = _params_model(client)
    child = client.post(f"/api/models/{m['id']}/adjust", json={"hazard_ratio": 1.5, "save": True}).json()
    extras = child["results"]["extras"]
    assert rbd_graph._extras(extras, "the block") == {"hr": 1.5}
    built = rbd_analysis._build_distribution({"distribution_id": "weibull", "params": WEIBULL, "extras": extras},
                                             "the block")
    assert float(built.sf(500)) == pytest.approx(math.exp(-1.5 * 0.25), rel=1e-12)
    with pytest.raises(rbd_graph.GraphError):
        rbd_graph._extras({"hr": 0}, "the block")


def test_download_as_python_carries_the_ratio(client, tmp_path):
    import subprocess
    import sys

    m = _fitted_model(client)
    child = client.post(f"/api/models/{m['id']}/adjust", json={"hazard_ratio": 1.5, "save": True}).json()
    r = client.get(f"/api/models/{child['id']}/export.py")
    assert r.status_code == 200, r.text
    script = r.text
    assert 'fitted["hr"] = 1.5' in script
    path = tmp_path / "model.py"
    path.write_text(script)
    out = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "Hazard ratio (hr)   : 1.5" in out.stdout


def child_owner(client, child):
    return client.db.models.find_one({"_id": child["id"]})["owner_id"]
