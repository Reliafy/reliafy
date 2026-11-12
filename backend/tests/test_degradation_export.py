"""Download as Python for degradation models: the script refits the model
from the readings it embeds and prints the numbers the page shows."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest

from backend.tests import python_scripts
from backend.tests.test_degradation import _deg_csv

A = "user-a"
B = "user-b"
USERS = {u: {"uid": u, "email": f"{u}@x.com", "name": u, "email_verified": True} for u in (A, B)}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    who = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: USERS[who["uid"]]
    c = TestClient(app)
    c.act_as = lambda uid: who.__setitem__("uid", uid)
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _save(client, **extra):
    form = {"name": "Liner wear", "i": "item", "x": "hours", "y": "wear", "threshold": "8.0",
            "unit": "hours", "measurement_unit": "mm", **extra}
    r = client.post("/api/degradation/models", data=form, files={"file": ("wear.csv", _deg_csv(), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _time_at(x, y, target):
    """The page's timeAtValue (lifeResults.js)."""
    if not x or not y:
        return None
    for k in range(1, len(x)):
        a, b = y[k - 1], y[k]
        if a is None or b is None:
            continue
        if a >= target >= b:
            f = 0 if a == b else (a - target) / (a - b)
            return x[k - 1] + f * (x[k] - x[k - 1])
    return None


@pytest.mark.parametrize("options", [
    {},  # best path, Weibull, two-stage moments: the defaults
    {"path": "linear", "distribution": "lognormal", "population_method": "reml"},
    {"path": "power", "distribution": "weibull"},
])
def test_the_script_prints_the_pages_numbers(client, tmp_path, options):
    mid = _save(client, **options)
    py = client.get(f"/api/degradation/models/{mid}/export.py")
    assert py.status_code == 200, py.text
    assert py.headers["content-type"].startswith("text/x-python")
    assert "DegradationAnalysis.fit(" in py.text and "requirements: surpyval==" in py.text
    r = client.get(f"/api/degradation/models/{mid}").json()["results"]
    out = python_scripts.run(py.text, tmp_path)

    assert f"Path shape: {r['path_model']['name']}" in out["_stdout"]
    for name, value in zip(r["path_model"]["param_names"], r["path_param_mean"]):
        python_scripts.close(out[f"Path {name}"]["value"], value)
    python_scripts.close(out["Measurement variance"]["value"], r["measurement_var"])
    for p in r["life_model"]["params"]:
        python_scripts.close(out[f"Life {p['name']}"]["value"], p["value"])
    python_scripts.close(out["Mean life"]["value"], r["life_model"]["mean"])
    c = r["life_model"]["curves"]
    assert c.get("life_lower")
    for label, share in (("B1", 0.01), ("B5", 0.05), ("B10", 0.10), ("B50", 0.50)):
        python_scripts.close(out[label]["value"], _time_at(c["x"], c["sf"], 1 - share))
        python_scripts.close(out[label]["bound"], _time_at(c["x"], c["life_lower"], 1 - share))
        python_scripts.close(out[f"{label} band"]["low"], _time_at(c["x"], c["lower"], 1 - share))
        python_scripts.close(out[f"{label} band"]["high"], _time_at(c["x"], c["upper"], 1 - share))


def test_another_users_model_is_not_found(client):
    mid = _save(client)
    client.act_as(B)
    assert client.get(f"/api/degradation/models/{mid}/export.py").status_code == 404


def test_a_model_whose_data_is_gone_is_refused_plainly(client):
    from backend import db

    mid = _save(client)
    doc = db._db.degradation_models.find_one({"_id": mid})
    db._db.datasets.delete_one({"_id": doc["dataset_id"]})
    r = client.get(f"/api/degradation/models/{mid}/export.py")
    assert r.status_code == 422 and "deleted" in r.json()["detail"]
