"""Repairable, accelerated-life and test-planning friction fixes: plain
words that follow the numbers, a curve that misses its data said so, a
dataset's repairable column reading kept, a band on the life-stress line."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd

from backend import alt
from backend import recurrent_models as rm
from backend.services import recurrent as recurrent_service
from backend.services import test_planning as tp
from backend.tests.test_alt_temperature import _capacitors, _fit, _spec


def test_a_small_negative_restoration_inside_its_interval_reads_as_a_minimal_repair():
    # q = 1.01 (−1%) with an interval from −8% to 6%: no "older than before".
    rest = rm.restoration("grp_ii", {}, 1.01, [0.94, 1.08])
    assert "older" not in rest["sentence"]
    assert "restores about 0%" in rest["sentence"]
    # Only an interval wholly below 0% says worse than a minimal repair.
    worse = rm.restoration("grp_ii", {}, 1.3, [1.1, 1.5])
    assert "worse than a minimal repair" in worse["sentence"]


def test_ara_and_ari_names_say_their_memory_in_words():
    assert rm.model_name("ara", {"m": 2}) == "Arithmetic reduction of age (ARA, last 2 repairs)"
    assert rm.model_name("ari", {"m": 1}) == "Arithmetic reduction of intensity (ARI, last repair)"
    assert rm.model_name("ara", {"m": "all"}).endswith("(ARA, every repair)")


def test_a_fitted_curve_far_from_the_data_is_said_so():
    observed = {"x": [100.0, 500.0, 1000.0], "mcf": [1.0, 10.0, 27.0], "lower": [0.5, 8.0, 22.0],
                "upper": [1.5, 12.0, 32.0]}
    grid = np.linspace(0, 1000, 11)
    far = rm.mcf_mismatch(observed, grid, grid * 0.08, "Hours")  # 80 per system at 1,000 h
    assert far and "80 failures per system" in far and "27" in far and "1,000 hours" in far
    # Inside the observed band, or within half again: nothing to say.
    assert rm.mcf_mismatch(observed, grid, grid * 0.03, "Hours") is None
    assert rm.mcf_mismatch(None, grid, grid, "") is None


def test_a_dataset_keeps_its_newest_repairable_column_reading():
    db = mongomock.MongoClient().db
    base = {"owner_id": "u1", "dataset_id": "d1"}
    db.recurrent_models.insert_many([
        {**base, "_id": "old", "name": "Old", "created_at": 1,
         "spec": {"mapping": {"i": "truck", "x": "hours"}, "unit": "Hours"}},
        {**base, "_id": "new", "name": "Trucks", "created_at": 2,
         "spec": {"mapping": {"i": "truck", "x": "hours", "tr": "observed_to_hours", "z": ["site"]},
                  "unit": "Hours"}},
    ])
    cols = [{"name": c} for c in ("truck", "hours", "observed_to_hours", "site")]
    got = recurrent_service.last_mapping(db, "d1", "u1", columns=cols)
    assert got == {"mapping": {"i": "truck", "x": "hours", "tr": "observed_to_hours", "z": ["site"]},
                   "unit": "Hours", "model_name": "Trucks"}
    # A column gone from the dataset: the older reading that still fits.
    got = recurrent_service.last_mapping(db, "d1", "u1", columns=cols[:2])
    assert got["model_name"] == "Old"
    assert recurrent_service.last_mapping(db, "d1", "someone-else", columns=cols) is None


def test_the_life_stress_line_carries_a_band_that_widens_away_from_the_tests():
    df = _capacitors()
    _, _, cid = _fit(df, _spec("temp_K"))
    model = alt.get_live(cid)
    lines = alt.life_lines(model, np.array([[313.15]]), np.array([[378.15], [398.15], [418.15]]))
    line = lines[0]
    assert len(line["lower"]) == len(line["life"]) == len(line["upper"])
    assert line["level"] == 0.9
    width = np.log(np.array(line["upper"])) - np.log(np.array(line["lower"]))
    life = np.array(line["life"])
    assert np.all(np.array(line["lower"]) < life) and np.all(life < np.array(line["upper"]))
    # Widest at the use stress (the coolest end), narrowest among the tests.
    stress = np.array(line["stress"])
    assert width[np.argmin(stress)] > width[np.argmin(np.abs(stress - 398.15))]


def test_a_life_test_states_its_precision_as_a_factor_either_way():
    out = tp.life_test(distribution="weibull", params=[{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}],
                       solve_for="precision", units=20, censor_time=800, confidence=0.9)
    assert "÷" in out["summary"] and "×" in out["summary"] and "±" not in out["summary"]
