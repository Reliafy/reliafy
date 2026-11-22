"""The reliability data library on the Modelling tab and in Models (library_models.py): a rate record
becomes a cited exponential model; its gamma is an exponential fit's prior exactly (conjugate); on a
Weibull it's a prior on the mean life with the shape bounded; per-demand and handbook records are
refused in words."""

from datetime import date, timedelta

import mongomock
import numpy as np
import pytest
import surpyval as sp

from backend.maintenance import fit_life
from backend.maintenance import library_models as lm
from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "org-lib"
OWNERS = [ORG, "__samples__"]
RATE = "nrc-inl-2020:aov-fc"  # gamma(alpha=1.26, beta=7.17e6) per hour
DEMAND = "nrc-inl-2020:mov-fto"
HANDBOOK = "mil-hdbk-217f-n2:6-1-general-purpose-analog"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod
    from backend.services import samples

    d = mongomock.MongoClient()["lib_models"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    return d


def test_a_rate_record_becomes_a_cited_exponential_model(m, db):
    pump = m.create_position("Valve 1")["id"]
    link = lm.attach(m, db, ORG, pump, RATE)
    assert link["role"] == "library" and link["source"]["library"]["record_id"] == RATE
    doc = db.models.find_one({"_id": link["model_id"]})
    r = doc["results"]
    assert doc["distribution_id"] == "exponential" and r["params"][0]["value"] == pytest.approx(1.75e-07, rel=0.01)
    assert r["params"][0]["ci"] == pytest.approx([1.5e-08, 4.86e-07], rel=0.01) and "across plants" in r["ci_note"]
    assert r["rate_uncertainty"]["shape"] == 1.26
    assert r["library"]["citation"] == "INL/EXT-21-65055, Table 1, p. 6" and doc["spec"]["library_record_id"] == RATE
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert row["source_text"] == ("Library: NRC/INL 2020, Air-operated valve fails to control "
                                  "(INL/EXT-21-65055, Table 1, p. 6)")
    assert lm.recently_used(db, OWNERS)[0]["record_id"] == RATE


def test_a_record_adjusted_for_the_conditions_here(m, db):
    """Adding a record with a hazard ratio saves the record's model, then that model with the ratio
    (SurPyval's hr), and links the adjusted one: 1.5 times the hazard, cited, its parent recorded."""
    valve = m.create_position("Valve 3")["id"]
    link = lm.attach(m, db, ORG, valve, RATE, hazard_ratio=1.5)
    assert link["role"] == "library" and link["source"]["adjusted"]["hazard_ratio"] == 1.5
    doc = db.models.find_one({"_id": link["model_id"]})
    base = db.models.find_one({"_id": link["source"]["adjusted"]["from_model_id"]})
    rate = base["results"]["params"][0]["value"]
    assert doc["results"]["extras"] == {"hr": 1.5} and doc["results"]["params"][0]["value"] == rate
    assert doc["results"]["life"]["mttf"]["value"] == pytest.approx(1 / (1.5 * rate), rel=1e-9)
    assert "rate_uncertainty" not in doc["results"] and doc["results"].get("method") != "library"
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(valve))
    assert row["source_text"].endswith("adjusted for conditions (×1.5 hazard)")
    assert row["source_text"].startswith("Library: NRC/INL 2020")
    hr = next(n for n in row["model"]["numbers"] if n["id"] == "hr")
    assert hr["value"] == 1.5 and not any(n["id"] == "mtbf" for n in row["model"]["numbers"])
    with pytest.raises(Invalid, match="hazard ratio"):
        lm.attach(m, db, ORG, valve, RATE, hazard_ratio=0)


def test_a_saved_model_adjusted_for_conditions_on_a_position(m, db):
    from backend.services import model_adjust
    from backend.services import models as models_service

    base = models_service.import_model(db, ORG, "Pump", "weibull", unit="hours",
                                       params=[{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}])
    hot = model_adjust.adjust(db, base, OWNERS, ORG, hazard_ratio=1.5)
    pump = m.create_position("Pump 1")["id"]
    link = pm.link_saved(m, db, OWNERS, set(), pump, "model", hot.id)
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert row["source_text"] == "From Pump, adjusted for conditions (×1.5 hazard)"
    assert link["source"]["adjusted"]["from_model_id"] == base.id
    b10 = next(n for n in row["model"]["numbers"] if n["id"] == "b10")
    assert b10["value"] == pytest.approx(265.03, abs=0.01)


def test_records_need_their_covariates_and_a_handbook_rate_is_no_prior(m, db):
    """A probability per demand is a model (and a prior) once its demands a year are given, never
    guessed; a handbook rate is a model with its environment, but a point value can't be a prior."""
    pump = m.create_position("Valve 2")["id"]
    with pytest.raises(Invalid, match="Demands a year is needed"):
        lm.attach(m, db, ORG, pump, DEMAND)
    link = lm.attach(m, db, ORG, pump, DEMAND, covariates={"demands_per_year": 12})
    assert link["source"]["library"]["covariates"] == {"demands_per_year": 12.0}
    with pytest.raises(Invalid, match="Environment is needed"):
        lm.save_record_model(db, ORG, HANDBOOK)
    model, _ = lm.save_record_model(db, ORG, HANDBOOK, covariates={"environment": "GF"})
    assert model.results["library"]["covariates"]["environment"] == "GF"
    with pytest.raises(Invalid, match="no spread"):
        lm.prior_base({"record_id": HANDBOOK}, "exponential")
    with pytest.raises(Invalid, match="Demands a year is needed"):
        lm.prior_base({"record_id": DEMAND}, "exponential")
    with pytest.raises(Invalid, match="no library record"):
        lm.attach(m, db, ORG, pump, "nope")


def _history(m, pid, lives_h, start=date(2015, 1, 1)):
    on = start
    for i, h in enumerate(lives_h):
        m.fit(pid, new_item={"name": f"V{i}"}, on=on.isoformat())
        on = on + timedelta(days=round(h / 24))
        m.remove(pid, on=on.isoformat(), reason="failure")
    m.fit(pid, new_item={"name": "Vrun"}, on=on.isoformat())


def test_the_gamma_is_an_exponential_fits_prior_exactly(m, db):
    pump = m.create_position("Valve 3")["id"]
    _history(m, pump, [24 * 400])
    got = fit_life.fit(m, db, OWNERS, set(), pump, method="bayes", distribution="exponential",
                       prior={"kind": "library", "record_id": RATE})
    assert "closed form (conjugate)" in got["words"] and got["unit"] == "hours"
    rows = [r for r in got["rows"] if r.get("used", True)]
    direct = sp.Exponential.fit_bayes(np.array([r["x"] for r in rows]), c=np.array([r["c"] for r in rows]),
                                      priors={"failure_rate": sp.Gamma.from_params([1.26, 7.17e6])})
    assert got["posterior"][0]["median"] == pytest.approx(direct.params[0], rel=1e-6)
    assert direct.method in ("conjugate", "exact", "closed_form") or "closed form" in str(direct.summary())


def test_on_a_weibull_the_rate_is_a_prior_on_the_mean_life(m, db):
    pump = m.create_position("Valve 4")["id"]
    _history(m, pump, [24 * 400, 24 * 900])
    got = fit_life.fit(m, db, OWNERS, set(), pump, method="bayes", distribution="weibull",
                       prior={"kind": "library", "record_id": RATE, "shape": [0.8, 3]})
    assert "a prior on the mean life" in got["words"] and "between 0.8 and 3 (as given)" in got["words"]
    assert got["distribution"] == "weibull"
    # The prior shows: its implied characteristic life, shape, B10 and mean life as medians with 90% ranges,
    # its numbers on the baseline (so the dashed curve draws), and the summary says how far the data moved it.
    prior = {p["name"]: p for p in got["prior"]}
    assert set(prior) == {"alpha", "beta", "B10", "mean"}
    assert prior["mean"]["lower"] == pytest.approx(1 / 4.86e-7, rel=0.03) and prior["mean"]["upper"] == pytest.approx(1 / 1.5e-8, rel=0.03)
    assert prior["beta"]["lower"] == pytest.approx(0.8, rel=0.03) and prior["beta"]["upper"] == pytest.approx(3, rel=0.03)
    assert all(p["median"] is not None for p in prior.values())
    assert got["baseline"]["params_from"] == "prior" and set(got["baseline"]["params"]) == {"alpha", "beta"}
    assert got["curves"]["baseline_sf"][0] == pytest.approx(1) and got["curves"]["baseline_hf"] is not None
    assert "pulled the characteristic life from the prior's" in got["words"] and "gave the belief its numbers" not in got["words"]
    assert "centred on about" in got["words"]


def test_library_gamma_prior_curves_do_not_overflow():
    """A library gamma on a rate per hour has a huge b (about 1e9 hours): the closed-form predictive's
    curves are worked out on the log scale rather than overflowing."""
    from backend.services import bayes_life as bl

    base = lm.prior_base({"kind": "library", "record_id": "nrc-inl-2020:mov-sop"}, "exponential")
    _, result, _ = bl.update(base, "guide", bl.given_rows([8400.0, 8400.0], [0, 1]), None, base["priors"])
    sf = result["curves"]["sf"]
    assert sf[0] == 1.0 and 0 < sf[-1] < 1 and all(a >= b for a, b in zip(sf, sf[1:]))


def test_a_bound_record_with_every_covariate_fixed_is_adjusted_too(m, db):
    from backend.maintenance import covariate_positions as cp

    valve = m.create_position("Valve 4")["id"]
    link = cp.bind(m, db, ORG, OWNERS, valve, {"source": "library", "ref": DEMAND, "fixed": {"demands_per_year": 12}},
                   hazard_ratio=2)
    assert link["source"]["adjusted"]["hazard_ratio"] == 2.0
    doc = db.models.find_one({"_id": link["model_id"]})
    assert doc["results"]["extras"] == {"hr": 2.0}
    assert [x["id"] for x in m.position_models(valve)] == [link["id"]]  # the unadjusted link was replaced
    with pytest.raises(Invalid, match="fix every covariate"):
        cp.bind(m, db, ORG, OWNERS, valve, {"source": "library", "ref": DEMAND, "fixed": {}}, hazard_ratio=2)
