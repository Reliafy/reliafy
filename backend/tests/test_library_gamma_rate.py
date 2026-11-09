"""An NRC/INL rate record keeps its gamma on the failure rate when it becomes a model: the
conversion scales the gamma with the model's rate (time unit, pipe length, clock), the saved model
carries it (``rate_uncertainty``), a model saved before this gets it back from its record on load,
and an RBD band draws the rate from it."""

import mongomock
import numpy as np
import pytest
import surpyval as sp

from backend.library import convert
from backend.library import service as library_service
from backend.maintenance import library_models as lm
from backend.services import models as models_service
from backend.services import rbd_uncertainty
from backend.services.rbd_analysis import analyze

PIPE = "nrc-inl-2020:pipe-other-ell"  # gamma(alpha=0.3, beta=1.187e10) per hour per foot, calendar
RATE = "nrc-inl-2020:aov-fc"  # gamma(alpha=1.26, beta=7.17e6) per hour
ORG = "org-gamma"


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod

    d = mongomock.MongoClient()["lib_gamma"]
    monkeypatch.setattr(db_mod, "_db", d)
    return d


def _gamma(unc):
    return sp.Gamma.from_params([unc["shape"], unc["rate"]])


def test_the_gamma_on_the_rate_scales_with_length_unit_and_clock():
    rec = library_service.get(PIPE)
    per_hour = convert.rate_to_exponential(rec, "hours", length_ft=100)
    unc = per_hour["rate_uncertainty"]
    # Same shape; the rate parameter divided by the 100 feet (the mean rate is 100 times the record's).
    assert unc["distribution"] == "gamma" and unc["shape"] == 0.3
    assert unc["rate"] == pytest.approx(1.187e10 / 100)
    assert unc["length_ft"] == 100 and unc["source"]["record_id"] == PIPE
    assert unc["record"]["params"] == {"alpha": 0.3, "beta": 1.187e10} and unc["record"]["units"] == "per hour per foot"
    # Its mean, 5% and 95% are the model's rate and bounds, which are the record's scaled.
    g = _gamma(unc)
    assert g.mean() == pytest.approx(per_hour["failure_rate"], rel=1e-9)
    assert float(g.qf(0.05)) == pytest.approx(unc["p05"], rel=1e-6) == per_hour["bounds"]["p05"]
    assert float(g.qf(0.95)) == pytest.approx(unc["p95"], rel=1e-6) == per_hour["bounds"]["p95"]
    assert unc["p05"] == pytest.approx(2.7e-15 * 100, rel=0.01)
    assert unc["p95"] == pytest.approx(1.16e-10 * 100, rel=0.01)

    # Per year of running, for a pipe in service half the year: 8760 h × (8760 / 4380) per running year.
    yearly = convert.rate_to_exponential(rec, "years", length_ft=100, time_basis="operating",
                                         operating_hours_per_year=4380)
    u2 = yearly["rate_uncertainty"]
    assert u2["shape"] == 0.3 and u2["rate"] == pytest.approx(1.187e10 / (100 * 8760 * 2))
    assert u2["unit"] == "Years" and _gamma(u2).mean() == pytest.approx(yearly["failure_rate"], rel=1e-9)
    assert u2["p95"] == pytest.approx(unc["p95"] * 8760 * 2, rel=1e-9)

    # Not per foot: a plain rate keeps its shape and scales by the time unit only.
    plain = convert.rate_to_exponential(library_service.get(RATE), "days")["rate_uncertainty"]
    assert plain["shape"] == 1.26 and plain["rate"] == pytest.approx(7.17e6 / 24)
    assert "length_ft" not in plain


def test_a_lognormal_rate_moves_its_mu():
    rec = {"id": "x", "version": 1, "label": "X", "kind": "rate", "source": "s",
           "citation": {"report": "R", "table": "T"},
           "distribution": {"family": "lognormal", "params": [{"name": "mu", "value": -14.0},
                                                              {"name": "sigma", "value": 1.2}]},
           "units": {"value": "per_hour", "time_basis": "calendar"}}
    unc = convert.rate_to_exponential(rec, "days")["rate_uncertainty"]
    assert unc["distribution"] == "lognormal" and unc["sigma"] == 1.2
    assert unc["mu"] == pytest.approx(-14.0 + np.log(24))
    assert unc["p95"] == pytest.approx(np.exp(-14.0 + 1.6448536 * 1.2) * 24, rel=1e-5)


def test_use_as_a_model_keeps_the_gamma_and_the_length(db):
    model, _ = lm.save_record_model(db, ORG, PIPE, length_ft=250)
    r = model.results
    assert model.distribution_id == "exponential" and model.name.startswith(
        "Pipe: external leak, large (not service water), 250 ft")
    rate = r["params"][0]["value"]
    assert rate == pytest.approx(2.53e-11 * 250, rel=0.01)
    unc = r["rate_uncertainty"]
    assert unc["shape"] == 0.3 and unc["rate"] == pytest.approx(1.187e10 / 250)
    assert unc["source"]["name"] == "NRC/INL 2020" and unc["source"]["citation"] == "INL/EXT-21-65055, Table 1, p. 14"
    assert r["params"][0]["ci"] == pytest.approx([unc["p05"], unc["p95"]])
    assert "across plants" in r["ci_note"] and r["library"]["length_ft"] == 250
    assert "250 feet" in model.spec["notes"]

    # Load: the page's results carry it; the live entry (what an RBD draws from) does too.
    page = models_service.public_results(models_service.get_model(db, model.id))
    assert page["rate_uncertainty"]["rate"] == unc["rate"]
    entry = models_service.get_live_model(db, model.id, ORG)
    assert entry["rate_uncertainty"]["shape"] == 0.3
    assert float(entry["model"].params[0]) == pytest.approx(rate)

    # A per-foot record with no length: one foot, said in the notes; a length on another record is refused.
    one, _ = lm.save_record_model(db, ORG, PIPE)
    assert one.results["params"][0]["value"] == pytest.approx(2.53e-11, rel=0.01)
    assert "no length was given" in one.spec["notes"] and one.results["rate_uncertainty"]["length_ft"] == 1.0
    with pytest.raises(lm._sv().Invalid, match="isn't a rate per foot"):
        lm.save_record_model(db, ORG, RATE, length_ft=10)
    with pytest.raises(lm._sv().Invalid, match="above 0"):
        lm.save_record_model(db, ORG, PIPE, length_ft=0)


def test_a_model_saved_before_gets_its_gamma_back_from_the_record(db):
    model, _ = lm.save_record_model(db, ORG, PIPE)
    # As the old code saved it: the rate per hour (per foot), its range as the interval, no gamma.
    db.models.update_one({"_id": model.id}, {"$unset": {"results.rate_uncertainty": "", "results.library.length_ft": ""},
                                             "$set": {"results.ci_note": "old note"}})
    old = models_service.get_model(db, model.id)
    assert "rate_uncertainty" not in old.results
    page = models_service.public_results(old)
    unc = page["rate_uncertainty"]
    assert unc["shape"] == 0.3 and unc["rate"] == pytest.approx(1.187e10, rel=1e-9)
    assert unc["length_ft"] == 1.0 and unc["source"]["name"] == "NRC/INL 2020"
    assert "across plants" in page["ci_note"]
    # Read-only: nothing written back.
    assert "rate_uncertainty" not in db.models.find_one({"_id": model.id})["results"]
    assert models_service.get_live_model(db, model.id, ORG)["rate_uncertainty"]["shape"] == 0.3

    # An exponential made from parameters by hand (no library) is untouched.
    hand = models_service.import_model(db, ORG, "Hand", "exponential", unit="Hours",
                                       params=[{"name": "failure_rate", "value": 1e-4}])
    assert "rate_uncertainty" not in models_service.public_results(hand)
    assert models_service.rate_uncertainty_of(hand) is None


def _block(model_id, rate):
    return {"source": "saved", "kind": "distribution", "modelId": model_id, "name": "Pipe",
            "distribution_id": "exponential", "distribution": "Exponential",
            "params": [{"name": "failure_rate", "value": rate}]}


def test_an_rbd_band_draws_the_rate_from_the_gamma():
    unc = convert.rate_to_exponential(library_service.get(RATE), "hours")["rate_uncertainty"]
    rate = unc["point"]
    live = sp.Exponential.from_params([rate])
    graph = {"unit": "h", "nodes": [{"id": "input", "type": "input", "data": {}},
                                    {"id": "output", "type": "output", "data": {}},
                                    {"id": "v", "type": "component", "data": {"label": "V", "model": _block("m1", rate)}}],
             "edges": [{"id": "1", "source": "input", "target": "v"}, {"id": "2", "source": "v", "target": "output"}]}
    res = analyze(graph, resolve_model=lambda mid: {"model": live, "rate_uncertainty": unc}, band={"level": 0.9})
    band = res["band"]
    [blk] = band["uncertain"]
    assert blk["id"] == "v" and "across plants" in blk["from_source"] and band["fixed"] == []
    # One block: the 5–95% band on R(t) is exp(-λ95 t) to exp(-λ05 t), from the draws.
    x = np.array(res["time"])
    i = int(np.argmin(np.abs(x - 1 / rate)))
    assert band["sf_lower"][i] == pytest.approx(np.exp(-unc["p95"] * x[i]), abs=0.03)
    assert band["sf_upper"][i] == pytest.approx(np.exp(-unc["p05"] * x[i]), abs=0.03)

    # Without the gamma (no covariance either) the block stays fixed, as before.
    plain = analyze(graph, resolve_model=lambda mid: {"model": live}, band={"level": 0.9})["band"]
    assert plain["uncertain"] == [] and plain["fixed"][0]["id"] == "v"


def test_rate_draws():
    rng = np.random.default_rng(1)
    d = rbd_uncertainty.rate_draws({"distribution": "gamma", "shape": 2.0, "rate": 4.0}, 20000, rng)
    assert d.mean() == pytest.approx(0.5, rel=0.03)
    ln = rbd_uncertainty.rate_draws({"distribution": "lognormal", "mu": -3.0, "sigma": 0.5}, 20000, rng)
    assert np.median(ln) == pytest.approx(np.exp(-3.0), rel=0.03)
    assert rbd_uncertainty.rate_draws({"distribution": "point"}, 5, rng) is None
