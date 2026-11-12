"""A Bayesian update of a baseline with a few failures (backend/services/bayes_life.py, on
SurPyval 0.26's fit_bayes): flat priors and plenty of data give the maximum-likelihood fit;
no data leaves the baseline as given; one early failure pulls the life in; a saved update
is a normal saved model that rebuilds from its recipe; the position flow saves and attaches."""

from datetime import date, timedelta

import mongomock
import numpy as np
import pytest
import surpyval as sp

from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import bayes_life as bl

ORG = "org-bayes"
OWNERS = [ORG, "__samples__"]


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod
    from backend.services import samples

    d = mongomock.MongoClient()["bayes_life"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)  # a saved model's refit reads the app's database
    return d


def test_surpyval_is_the_version_with_bayesian_fitting():
    from importlib.metadata import version

    assert tuple(int(p) for p in version("surpyval").split(".")[:2]) >= (0, 26)


def test_flat_priors_and_plenty_of_data_give_the_mle():
    x = sp.Weibull.random(300, 2000, 1.8, random_state=7)
    rows = bl.given_rows(x.tolist(), [0] * len(x))
    xs, cs = bl.arrays(rows)
    model = bl._fit("weibull", xs, cs, {"alpha": sp.prior.flat(), "beta": sp.prior.flat()}, "hours")
    mle = sp.Weibull.fit(x)
    assert model.params[0] == pytest.approx(mle.alpha, rel=0.01)
    assert model.params[1] == pytest.approx(mle.beta, rel=0.02)


def test_no_data_leaves_the_baseline_as_given():
    base = {"source": "params", "name": "OEM", "distribution": "weibull", "unit": "hours",
            "params": {"alpha": 3000.0, "beta": 2.0}}
    model, result, _ = bl.update(base, "guide", [])
    assert model is None and result["can_save"] is False
    post = {p["name"]: p for p in result["posterior"]}
    assert post["alpha"]["median"] == pytest.approx(3000, rel=1e-6)
    assert post["beta"]["median"] == pytest.approx(2.0, rel=1e-6)
    # "Use it as a guide": each within about 30% (90% of the prior between).
    assert post["alpha"]["lower"] == pytest.approx(3000 / 1.3, rel=0.02)
    assert post["alpha"]["upper"] == pytest.approx(3000 * 1.3, rel=0.02)
    assert "stands as given" in result["words"]


def test_an_early_failure_pulls_the_life_in_and_the_result_says_so():
    base = {"source": "params", "name": "the class model", "distribution": "weibull", "unit": "hours",
            "params": {"alpha": 3000.0, "beta": 2.0}}
    rows = bl.given_rows([1400, 1900, 800, 800], [0, 0, 1, 1])
    model, result, _ = bl.update(base, "start", rows, age=1000)
    post = {p["name"]: p for p in result["posterior"]}
    assert post["alpha"]["median"] < 3000
    assert post["alpha"]["lower"] < post["alpha"]["median"] < post["alpha"]["upper"]
    assert result["counts"] == {"failures": 2, "suspensions": 2}
    assert result["moved"].startswith("2 failures at 1,400 and 1,900 hours pulled the characteristic life from 3,000")
    assert "we're 90% sure it's at least" in result["words"] and "one-sided credible" in result["words"]
    assert "confidence" not in result["words"] and "lies between" not in result["words"]
    assert 0 < result["at_age"]["lower"] < result["at_age"]["reliability"] < result["at_age"]["upper"] < 1
    c = result["curves"]
    assert len(c["x"]) == bl.GRID and c["baseline_sf"][0] == pytest.approx(1)
    # Trusting the baseline closely moves it less.
    _, close, _ = bl.update(base, "close", rows)
    assert {p["name"]: p for p in close["posterior"]}["alpha"]["median"] > post["alpha"]["median"]


def test_a_b10_belief_is_a_baseline_too():
    base = bl.baseline_from(None, OWNERS, set(), {"b10": {"value": 5000, "low": 3000, "high": 8000},
                                                 "shape": {"low": 1.2, "high": 4}, "unit": "hours"})
    _, result, _ = bl.update(base, "guide", [])
    b10 = next(p for p in result["prior"] if p["name"] == "B10")
    assert b10["lower"] == pytest.approx(3000, rel=0.05) and b10["upper"] == pytest.approx(8000, rel=0.05)
    # A belief has no numbers of its own: the prior's medians stand in, so the result draws its curve
    # and says how far the data moved it, with the numbers.
    assert result["baseline"]["params_from"] == "prior"
    assert result["baseline"]["params"]["beta"] == pytest.approx(2.19, rel=0.02)
    _, moved, _ = bl.update(base, "guide", bl.given_rows([1400, 1900, 800, 800], [0, 0, 1, 1]))
    assert moved["moved"].startswith("2 failures at 1,400 and 1,900 hours pulled the characteristic life from the prior's 14,0")
    assert "gave the belief its numbers" not in moved["words"]
    assert moved["curves"]["baseline_sf"][0] == pytest.approx(1) and len(moved["curves"]["baseline_hf"]) == bl.GRID


def test_a_prior_on_the_mean_life_is_summarised_by_sampling_it():
    """A library record's prior on a Weibull: the mean life 90% between two bounds with the shape
    between two more. SurPyval's grid check can't summarise it (the long tail the mean implies), so
    the quantities are drawn and mapped to the parameters: the prior exactly, and the same every run."""
    priors = sp.prior.on_quantities(sp.Weibull, mean=sp.prior.around(5.7e6, between=(2.06e6, 6.67e7)),
                                    beta=sp.prior.between(0.5, 5))
    table = {p["name"]: p for p in bl.prior_table("weibull", priors)}
    assert set(table) == {"alpha", "beta", "B10", "mean"}
    assert table["mean"]["lower"] == pytest.approx(2.06e6, rel=0.03) and table["mean"]["upper"] == pytest.approx(6.67e7, rel=0.03)
    assert table["beta"]["lower"] == pytest.approx(0.5, rel=0.03) and table["beta"]["upper"] == pytest.approx(5, rel=0.03)
    assert table["beta"]["median"] == pytest.approx((0.5 * 5) ** 0.5, rel=0.03)  # the geometric middle
    assert 0 < table["B10"]["lower"] < table["B10"]["median"] < table["B10"]["upper"]
    assert table["alpha"]["median"] > 0
    assert bl.prior_table("weibull", priors) == bl.prior_table("weibull", priors)  # seeded
    # A lognormal's spread, and an exponential's mean alone, are worked out the same way.
    ln = {p["name"]: p for p in bl.prior_table("lognormal", sp.prior.on_quantities(
        sp.LogNormal, mean=sp.prior.between(2.06e6, 6.67e7), sigma=sp.prior.between(0.5, 5)))}
    assert ln["mean"]["lower"] == pytest.approx(2.06e6, rel=0.03) and ln["sigma"]["upper"] == pytest.approx(5, rel=0.03)
    ex = {p["name"]: p for p in bl.prior_table("exponential", sp.prior.on_quantities(
        sp.Exponential, mean=sp.prior.between(1000, 10000)))}
    assert ex["failure_rate"]["median"] == pytest.approx(1 / (1000 * 10000) ** 0.5, rel=0.03)
    # A statement not worked out here gives no table, not a wrong one.
    assert bl._sampled_table("weibull", sp.prior.on_quantities(
        sp.Weibull, B10=sp.prior.between(100, 200), B50=sp.prior.between(300, 900))) == {}


def test_a_saved_update_is_a_normal_model_that_rebuilds(db):
    from backend.services import models as models_service

    base = bl.baseline_from(db, OWNERS, set(), {"model_id": "sample-model-bearings-weibull"})
    assert base["source"] == "model" and base["live"] is not None  # its fit: from_model
    rows = bl.given_rows([300.0, 900.0], [0, 1])
    model, result, priors = bl.update(base, "guide", rows)
    doc = bl.save(db, ORG, model, result, priors)
    assert doc.name.startswith("Bayesian update of Bearing life") and doc.name.endswith("1 failure, 1 suspension")
    saved = models_service.get_model(db, doc.id, OWNERS)
    assert saved.results["method"] == "bayesian_update" and saved.results["params"][0]["ci"][0] is not None
    # The page reads how it was fitted and at what level from the doc itself (UX review, Nov 2026).
    assert saved.results["credible_level"] == 0.9 and saved.results["options"]["how"] == bl.HOW
    assert "90% credible" in saved.results["ci_note"]
    life = saved.results["life"]
    b10 = next(b for b in life["b_lives"] if b["label"] == "B10")
    assert life["confidence"] == 0.9 and b10["value"] > 0 and 0 < b10["lower"] < b10["value"]
    assert life["mttf"]["value"] > 0 and life["mttf"]["lower"] is not None and "credible" in life["bounds_note"]
    # One failure can't place probability-plot points: the doc says why instead of hiding the tab.
    assert saved.results["plot"] is None and "at least two failures" in saved.results["plot_note"]
    # The model list says what n means: data added to a prior (UX review, Nov 2026).
    from types import SimpleNamespace

    from backend.routers.models import _model_summary
    ctx = SimpleNamespace(write_owner=ORG, frozen=False, member_view_only=False)
    summary = _model_summary(saved, ctx)
    assert summary["method"] == "bayesian_update" and "params_only" not in summary
    public = models_service.public_results(saved)
    assert "credible" in public["functions"]["bands_note"]
    # The calculator's bands and B-lives come from the posterior's credible intervals.
    assert public["functions"]["confidence_path"].endswith("/confidence")
    band = models_service.confidence(db, doc.id, {"on": "sf", "alpha_ci": 0.1, "bound": "lower"}, OWNERS)
    assert band["upper"] is None and any(v is not None and 0 < v < 1 for v in band["lower"])
    at = models_service.life(db, doc.id, {"reliability": [0.9], "confidence": 0.9, "bound": "lower"}, OWNERS)
    assert at["points"][0]["lower"] is not None and "credible" in at["bounds_note"]
    # The calculator's live model is the rebuilt posterior: its reliability matches the saved curve.
    out = models_service.evaluate_at(db, saved, [500.0], OWNERS)
    assert out is not None
    live = bl.rebuild(saved.spec)
    assert float(np.ravel(live.sf(500.0))[0]) == pytest.approx(float(np.ravel(model.sf(500.0))[0]), rel=1e-6)
    # An update of an update keeps the earlier prior and takes the new history.
    again = bl.baseline_from(db, OWNERS, set(), {"model_id": doc.id})
    assert again["source"] == "update"
    m2, r2, p2 = bl.update(again, "guide", bl.given_rows([300.0, 700.0, 900.0], [0, 0, 1]))
    assert r2["counts"]["failures"] == 2 and r2["trust"]["id"] == "kept"
    # Two failures place the points: the plot's line and band are the updated model's, on Weibull paper.
    plot = bl.save(db, ORG, m2, r2, p2).results["plot"]
    assert len(plot["scatter"]["x"]) == 2 and len(plot["line"]["x"]) == len(plot["bounds"]["lower"]) > 10
    assert all(lo <= hi for lo, hi in zip(plot["bounds"]["lower"], plot["bounds"]["upper"]) if lo is not None and hi is not None)
    assert plot["empirical"]["method"] == "Nelson-Aalen" and len(plot["empirical"]["x"]) == 2


def test_the_position_flow_previews_saves_and_attaches(db):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    pump = m.create_position("Pump A")["id"]
    start = date(2023, 1, 1)
    m.fit(pump, new_item={"name": "P1"}, on=start.isoformat())
    m.remove(pump, on=(start + timedelta(days=60)).isoformat(), reason="failure")
    m.fit(pump, new_item={"name": "P2"}, on=(start + timedelta(days=60)).isoformat())
    # No baseline and no class model: the preview says so in words; saving refuses.
    asked = pm.bayes_position(m, db, OWNERS, set(), pump)
    assert asked["needs_baseline"] is True and "no class model" in asked["words"]
    with pytest.raises(Invalid, match="no class model"):
        pm.bayes_position(m, db, OWNERS, set(), pump, save=True)
    preview = pm.bayes_position(m, db, OWNERS, set(), pump, {"model_id": "sample-model-bearings-weibull"})
    assert preview["counts"]["failures"] == 1 and preview["rows"][0]["x"] == pytest.approx(60 * 24)  # hours
    one = preview["rows"][0]["fitment_id"]
    without = pm.bayes_position(m, db, OWNERS, set(), pump, {"model_id": "sample-model-bearings-weibull"}, exclude=[one])
    assert without["counts"]["failures"] == 0
    link = pm.bayes_position(m, db, OWNERS, set(), pump, {"model_id": "sample-model-bearings-weibull"}, save=True)
    assert link["role"] == "bayesian" and pm.source_text(link).startswith("Bayesian update of Bearing life")
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert row["model"]["kind"] == "Weibull (Bayesian)" and row["model"]["quality"]["word"] == "Bayesian"
    assert {n["id"] for n in row["model"]["numbers"]} >= {"char_life", "shape", "mean", "b10"}
    assert row["model"]["credible_level"] == 0.9
    assert row["source_text"] == "Bayesian update of Bearing life — Weibull (sample) · 1 failure, 1 suspension"
    # The panel's plot carries the posterior-predictive credible band, not confidence bounds.
    full = pm.detail(m, db, OWNERS, set(), link["id"])
    c = full["curves"]
    assert c["band"] == {"kind": "credible", "level": 0.9}
    mid = len(c["x"]) // 3
    assert c["sf_lower"][mid] < c["sf"][mid] < c["sf_upper"][mid]
    assert full["source_text"] == row["source_text"]
    # The same model assigned to another position says its baseline and data too, not "Assigned: …".
    other = m.create_position("Pump B")["id"]
    pm.link_saved(m, db, OWNERS, set(), other, "model", link["model_id"])
    [there] = pm.describe(m, db, OWNERS, set(), m.position_models(other))
    assert there["source_text"] == row["source_text"]
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_unit_of_use_baseline_refuses_the_position_history():
    with pytest.raises(bl.BayesError, match="unit of use"):
        bl.time_factor("cycles")


def test_the_calculators_grid_survives_a_quantile_that_wont_converge():
    # A long-tailed posterior (shape well below 1) can make the predictive quantile's root search
    # fail; the grid then ends at the posterior medians' own 99% time (UX review, Nov 2026).
    class Stubborn:
        params = np.array([2.35e6, 0.445])

        def qf(self, p):
            raise RuntimeError("Failed to converge after 100 iterations.")

    t = bl._upper_time(Stubborn(), "weibull")
    assert t == pytest.approx(float(sp.Weibull.qf(0.99, 2.35e6, 0.445)))
    with pytest.raises(ValueError):
        bl._upper_time(Stubborn(), None)


def test_the_fit_result_gives_the_same_one_sided_b10_bound_as_the_saved_page(db):
    """12 Nov review: the result said the B10 is "between 3,506 and 6,994" (90%
    two-sided) while the saved model's page said "≥ 3,810 at 90% credible". B-lives
    and the mean life are 90% one-sided lower bounds everywhere: the result now
    gives the saved page's number, in its words."""
    base = bl.baseline_from(None, OWNERS, set(), {"b10": {"value": 5000, "low": 3000, "high": 8000},
                                                   "shape": {"low": 1.2, "high": 4}, "unit": "hours"})
    rows = bl.given_rows([4200, 6100, 7900] + [8000] * 7, [0, 0, 0] + [1] * 7)
    model, result, priors = bl.update(base, "guide", rows)
    b10, mean = result["b10"], result["mean"]
    assert b10["upper"] is None and b10["bound"] == "lower" and b10["level"] == 0.9
    assert mean["upper"] is None and mean["bound"] == "lower"
    # The one-sided 90% lower bound is above the two-sided 90% interval's lower end.
    two = np.ravel(model.quantile_cri(0.1, alpha_ci=0.1))
    assert two[0] < b10["lower"] < b10["point"] < two[1]
    saved = bl.save(db, ORG, model, result, priors).results["life"]
    page_b10 = next(b for b in saved["b_lives"] if b["label"] == "B10")
    assert saved["confidence"] == 0.9
    assert b10["lower"] == pytest.approx(page_b10["lower"], rel=1e-6)
    assert mean["lower"] == pytest.approx(saved["mttf"]["lower"], rel=1e-6)
    assert f"at least {bl.num(b10['lower'])} hours (90% one-sided credible bound)" in result["words"]
