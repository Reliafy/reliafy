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


def test_per_demand_and_handbook_records_are_refused_in_words(m, db):
    pump = m.create_position("Valve 2")["id"]
    with pytest.raises(Invalid, match="probability per demand .* fitted from counts of demands"):
        lm.attach(m, db, ORG, pump, DEMAND)
    with pytest.raises(Invalid, match="handbook base rate for a parts count"):
        lm.save_record_model(db, ORG, HANDBOOK)
    with pytest.raises(Invalid, match="counts lives, not demands"):
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
