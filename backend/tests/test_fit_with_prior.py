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
    assert 0 < out["at_age"]["lower"] < out["at_age"]["reliability"] < 1 and out["at_age"]["upper"] is None
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
    # Data in days, the prior typed in hours: the prior moves to days, and so does the result.
    days = web.post("/api/models/fit-with-prior", json=_body(content=flipped, c_invert=True, unit="days")).json()
    assert days.get("refused") is None and days["unit"] == "days"


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


def test_a_prior_in_another_unit_gives_the_result_in_the_datas_unit(web):
    """Data in days, the prior in hours: the prior is moved to days (alpha / 24, a rate x 24, mu - log 24), so
    the fit, its numbers, the curves and the saved model are all in days, and the result says so."""
    hours_rows = "time,c\n" + "\n".join(f"{t},{k}" for t, k in [(240, 0), (480, 0), (720, 1), (960, 0), (1200, 0)])
    days_rows = "time,c\n" + "\n".join(f"{t // 24},{k}" for t, k in [(240, 0), (480, 0), (720, 1), (960, 0), (1200, 0)])
    baseline = _params_model(web, "Hours baseline", params=[{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}])
    prior = {"kind": "model", "model_id": baseline["id"]}
    in_hours = web.post("/api/models/fit-with-prior", json=_body(content=hours_rows, prior=prior)).json()
    in_days = web.post("/api/models/fit-with-prior", json=_body(content=days_rows, prior=prior, unit="days")).json()
    assert in_hours["unit"].lower() == "hours" and in_days["unit"] == "days"
    assert "moved from hours to days" in in_days["prior_note"]
    a_h = next(p["median"] for p in in_hours["posterior"] if p["name"] == "alpha")
    a_d = next(p["median"] for p in in_days["posterior"] if p["name"] == "alpha")
    assert a_d == pytest.approx(a_h / 24, rel=0.03)
    assert in_days["b10"]["point"] == pytest.approx(in_hours["b10"]["point"] / 24, rel=0.03)
    # The prior's own numbers are shown in days too.
    prior_alpha = next(p for p in in_days["prior"] if p["name"] == "alpha")
    assert prior_alpha["median"] == pytest.approx(1000 / 24, rel=0.05)
    saved = web.post("/api/models/fit-with-prior", json=_body(content=days_rows, prior=prior, unit="days", save=True,
                                                              name="Days with an hours prior")).json()
    doc = web.db.models.find_one({"_id": saved["id"]})
    assert doc["results"]["unit"].lower().startswith("day")
    assert doc["results"]["params"][0]["value"] == pytest.approx(a_d, rel=0.03)


def test_scale_param_moves_lives_rates_and_mu():
    import math

    from backend.maintenance.library_models import scale_param

    assert scale_param("alpha", 2400, 24) == pytest.approx(100)
    assert scale_param("failure_rate", 0.001, 24) == pytest.approx(0.024)
    assert scale_param("mu", 7.0, 24) == pytest.approx(7.0 - math.log(24))
    assert scale_param("beta", 2.0, 24) == 2.0 and scale_param("sigma", 0.5, 24) == 0.5


def test_a_library_record_in_hours_fits_data_in_days_in_days(web):
    lid = web.post("/api/library/mine", json={"name": "Priors"}).json()["id"]
    model, _ = _fitted_model(web)
    rec = web.post(f"/api/library/mine/{lid}/records", json={"model_id": model["id"]}).json()["record"]
    days = "time,c\n5,0\n14,0\n21,1\n29,0\n41,0\n50,1\n"
    out = web.post("/api/models/fit-with-prior", json=_body(content=days, unit="days",
                                                            prior={"kind": "library", "record_id": rec["id"]})).json()
    assert out.get("refused") is None and out["unit"] == "days", out
    alpha_prior = next(p for p in out["prior"] if p["name"] == "alpha")
    record_alpha = next(p["value"] for p in rec["distribution"]["params"] if p["name"] == "alpha")
    assert alpha_prior["median"] == pytest.approx(record_alpha / 24, rel=0.1)
    # A rate record (a published gamma on the rate per hour) moves too: the rate per day is 24 times it.
    from backend.maintenance import library_models

    rid = "nrc-inl-2020:aov-fc"
    hours = library_models.prior_base({"kind": "library", "record_id": rid}, "exponential", web.db, [PRO])
    in_days = library_models.prior_base({"kind": "library", "record_id": rid}, "exponential", web.db, [PRO], to_unit="days")
    assert hours["unit"] == "hours" and in_days["unit"] == "days"
    assert in_days["params"]["failure_rate"] == pytest.approx(hours["params"]["failure_rate"] * 24)
    assert in_days["priors"]["failure_rate"].mean() == pytest.approx(hours["priors"]["failure_rate"].mean() * 24, rel=1e-6)
