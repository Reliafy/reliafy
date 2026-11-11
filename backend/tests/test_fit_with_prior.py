"""New model's "With a prior" (POST /api/models/fit-with-prior): a saved dataset or a pasted /
uploaded table, fitted with any prior the Explorer's "Fit a life model…" takes but the class's
history, through the same prior path (fit_life.prior_base / prior_priors, bayes_life.update), and
saved as a Bayesian model that keeps its prior."""

from __future__ import annotations

import pytest

from backend.tests.test_library_user import CSV, PRO, _fitted_model, _params_model, web  # noqa: F401
from backend.tests.test_mcp_plans import env  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")

WEIBULL_PRIOR = {"kind": "params", "distribution": "weibull", "unit": "hours",
                 "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}]}


def _body(**over):
    return {"time_column": "time", "censor_column": "c", "unit": "hours", "distribution": "weibull",
            "prior": WEIBULL_PRIOR, "trust": "guide", **over}


def test_each_prior_kind_fits_a_saved_dataset(web):
    _, dsid = _fitted_model(web)
    baseline = _params_model(web, "Baseline pump")
    priors = {
        "params": WEIBULL_PRIOR,
        "model": {"kind": "model", "model_id": baseline["id"]},
        "around": {"kind": "around", "distribution": "weibull", "unit": "hours",
                   "params": {"alpha": {"about": 1000, "between": [500, 2000]}}},
        "b10": {"kind": "b10", "b10": {"value": 300, "low": 100, "high": 800}, "shape": {"low": 1.2, "high": 4}, "unit": "hours"},
    }
    for kind, prior in priors.items():
        out = web.post("/api/models/fit-with-prior", json=_body(dataset_id=dsid, prior=prior)).json()
        assert out.get("refused") is None, (kind, out)
        assert out["method"] == "bayes" and out["can_save"] and out["prior_kind"] == kind
        assert out["counts"] == {"failures": 8, "suspensions": 2}
        assert out["curves"]["sf_lower"] and out["curves"]["sf_upper"], kind
        # The prior's own curve, dashed beside the fit, wherever the prior names every parameter.
        if kind != "around":
            assert out["curves"]["baseline_sf"], kind
        # A dataset's fit isn't a position's: the words say so.
        assert "position" not in out["words"] and "the best B10 is about" in out["words"]
        assert out["dataset"]["id"] == dsid


def test_pasted_values_fit_with_a_prior_and_save_with_its_provenance(web):
    # Pasted or uploaded data arrives as the table's CSV, nothing saved until Save.
    before = web.db.datasets.count_documents({})
    out = web.post("/api/models/fit-with-prior", json=_body(content=CSV, age=500)).json()
    assert out.get("refused") is None and out["dataset"] is None
    assert 0 < out["at_age"]["reliability"] < 1 and out["at_age"]["lower"] < out["at_age"]["upper"]
    assert web.db.datasets.count_documents({}) == before
    r = web.post("/api/models/fit-with-prior", json=_body(content=CSV, save=True, name="Pump with a prior"))
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["name"] == "Pump with a prior"
    doc = web.db.models.find_one({"_id": saved["id"]})
    assert doc["spec"]["method"] == "bayesian_update"
    bayes = doc["results"]["bayes"]
    assert bayes["baseline"]["source"] == "params" and "Weibull" in bayes["baseline"]["name"]
    assert doc["results"]["credible_level"] == pytest.approx(0.9)


def test_status_words_flipped_flags_and_unit_conversion(web):
    words = "time,state\n120,failed\n340,failed\n510,running\n700,failed\n980,failed\n1200,running\n"
    out = web.post("/api/models/fit-with-prior", json=_body(content=words, censor_column="state",
                                                            c_map={"failed": 0, "running": 1})).json()
    assert out.get("refused") is None and out["counts"] == {"failures": 4, "suspensions": 2}
    # 1 = failed in the sheet: c_invert flips it.
    flipped = "time,c\n120,1\n340,1\n510,0\n700,1\n"
    out = web.post("/api/models/fit-with-prior", json=_body(content=flipped, c_invert=True)).json()
    assert out["counts"] == {"failures": 3, "suspensions": 1}
    # Data in days, the prior in hours: converted to the prior's unit.
    days = web.post("/api/models/fit-with-prior", json=_body(content=flipped, c_invert=True, unit="days")).json()
    assert days.get("refused") is None and days["unit"] == "hours"


def test_refusals_come_back_in_words(web):
    _, dsid = _fitted_model(web)
    # The class's history is a prior only on a position.
    out = web.post("/api/models/fit-with-prior", json=_body(dataset_id=dsid, prior={"kind": "class"})).json()
    assert "only on a position" in out["refused"]
    out = web.post("/api/models/fit-with-prior", json=_body(dataset_id=dsid, prior={"kind": "params"})).json()
    assert out["refused"]
    out = web.post("/api/models/fit-with-prior", json=_body(content="time,c\n100,0\nabc,1\n")).json()
    assert "must hold a number" in out["refused"]
    out = web.post("/api/models/fit-with-prior", json=_body(content="time,c\n100,0\n200,maybe\n")).json()
    assert "maybe" in out["refused"]
    assert web.post("/api/models/fit-with-prior", json=_body(dataset_id="nope")).status_code == 404


def test_the_explorer_path_reads_priors_through_the_same_functions():
    """fit_life.fit and library_models.fit_dataset share prior_base / prior_priors (one prior path)."""
    import inspect

    from backend.maintenance import fit_life, library_models

    assert "prior_base(" in inspect.getsource(fit_life.fit)
    assert "prior_priors(" in inspect.getsource(fit_life._fit_on)
    src = inspect.getsource(library_models.fit_dataset)
    assert "fit_life.prior_base(" in src and "fit_life.prior_priors(" in src
