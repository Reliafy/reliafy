"""Repairable fits system by system: each system's own end of record, fitting
one system (or a chosen set) by itself, and each system's downtime and cost.

The data: eight gearboxes watched for 1,096 days (G7 never failed, so it has
no row), with G3's record cut at day 995 in the second file. Every number is
checked against the closed form of the power-law (Crow-AMSAA) MLE:

* all systems to one end T: beta = N / sum ln(T / t);
* systems to different ends T_k: beta solves
  N / beta + sum ln t - N * sum T_k^beta ln T_k / sum T_k^beta = 0;
* Laplace U = (mean t - T / 2) / (T / sqrt(12 n)) for one system to T.
"""

from __future__ import annotations

import io
import json
import math

import mongomock
import pandas as pd
import pytest
from scipy.optimize import brentq

from backend import recurrent as rec
from backend import recurrent_systems as per
from backend.fitting import FitError
from backend.tests.test_recurrent import A, _client

FAILURES = {
    "G1": [482, 861, 944],
    "G2": [295, 1016],
    "G3": [292, 548, 654, 744, 807, 808, 845, 889],
    "G4": [509, 525, 613, 717, 1072],
    "G5": [224, 444, 702, 713, 874, 886],
    "G6": [87, 333, 388, 858],
    "G8": [96, 275, 277, 429, 536],
}
T = 1096.0
G3_END = 995.0
MAPPING = {"i": "unit", "x": "days", "tr": "observed_to"}


def _frame(g3_end=T, costs=False):
    rows = []
    for unit, times in FAILURES.items():
        for k, t in enumerate(times):
            row = {"unit": unit, "days": t, "observed_to": g3_end if unit == "G3" else T}
            if costs:  # downtime 2 h + k, cost $1,000 a failure (+ $500 on G3)
                row["downtime"] = 2.0 + k
                row["total cost"] = 1000.0 + (500.0 if unit == "G3" else 0.0)
            rows.append(row)
    return pd.DataFrame(rows)


def _beta_closed_form(systems: dict) -> float:
    """The power-law MLE of beta for systems {id: (failure times, end)}."""
    n = sum(len(t) for t, _ in systems.values())
    s = sum(math.log(x) for t, _ in systems.values() for x in t)
    ends = [e for _, e in systems.values()]

    def score(b):
        return n / b + s - n * sum(e ** b * math.log(e) for e in ends) / sum(e ** b for e in ends)

    return brentq(score, 0.05, 20)


def _beta(payload):
    return next(p["value"] for p in payload["params"] if p["name"] == "beta")


def test_one_end_for_every_system_matches_the_closed_form():
    payload, _ = rec.fit(_frame(), MAPPING, "crow_amsaa", "days")
    n = sum(len(t) for t in FAILURES.values())
    by_hand = n / sum(math.log(T / x) for t in FAILURES.values() for x in t)
    assert by_hand == pytest.approx(1.3311, abs=1e-4)
    assert _beta(payload) == pytest.approx(by_hand, rel=1e-6)
    assert payload["termination"]["ends"] == [{"end": T, "systems": sorted(FAILURES)}]


def test_each_system_keeps_its_own_end_of_record():
    """G3 cut at 995 shortens G3's window only: the other six still run to
    1,096 (beta 1.353, not 1.429 as a single end of 995 for all would give)."""
    payload, _ = rec.fit(_frame(G3_END), MAPPING, "crow_amsaa", "days")
    by_hand = _beta_closed_form({u: (t, G3_END if u == "G3" else T) for u, t in FAILURES.items()})
    assert by_hand == pytest.approx(1.3533, abs=1e-4)
    assert _beta(payload) == pytest.approx(by_hand, rel=1e-6)
    # Not one end for everyone (failures after 995 dropped, all cut at 995).
    one_end = {u: ([x for x in t if x <= G3_END], G3_END) for u, t in FAILURES.items()}
    assert _beta(payload) != pytest.approx(_beta_closed_form(one_end), rel=1e-3)
    ends = payload["termination"]["ends"]
    assert ends == [{"end": T, "systems": ["G1", "G2", "G4", "G5", "G6", "G8"]}, {"end": G3_END, "systems": ["G3"]}]


def test_one_system_fitted_alone_matches_the_closed_form():
    payload, _ = rec.fit(_frame(G3_END), MAPPING, "crow_amsaa", "days", systems=["G3"])
    t = FAILURES["G3"]
    by_hand = len(t) / sum(math.log(G3_END / x) for x in t)
    assert by_hand == pytest.approx(2.4795, abs=1e-4)
    assert _beta(payload) == pytest.approx(by_hand, rel=1e-6)
    assert payload["n_systems"] == 1 and payload["n_events"] == 8
    assert payload["subset"] == {"systems": ["G3"], "of": 7}
    u = (sum(t) / len(t) - G3_END / 2) / (G3_END / math.sqrt(12 * len(t)))
    laplace = next(x for x in payload["trend_tests"] if x["id"] == "laplace")
    assert laplace["statistic"] == pytest.approx(u, rel=1e-6)
    assert u == pytest.approx(1.98, abs=0.005) and laplace["significant"]


def test_a_chosen_set_of_systems_fitted_together():
    others = [u for u in FAILURES if u != "G3"]
    payload, _ = rec.fit(_frame(G3_END), MAPPING, "crow_amsaa", "days", systems=others)
    n = sum(len(FAILURES[u]) for u in others)
    by_hand = n / sum(math.log(T / x) for u in others for x in FAILURES[u])
    assert by_hand == pytest.approx(1.2024, abs=1e-4)
    assert _beta(payload) == pytest.approx(by_hand, rel=1e-6)
    assert payload["subset"]["of"] == 7 and len(payload["subset"]["systems"]) == 6


def test_a_system_not_in_the_data_is_refused():
    with pytest.raises(FitError, match="G9 isn't a system in this data. Pick from its systems: G1, G2"):
        rec.fit(_frame(), MAPPING, "crow_amsaa", "days", systems=["G9"])
    assert per.parse_systems('["G1", "G1", " "]') == ["G1"]
    assert per.parse_systems("G1\nG2") == ["G1", "G2"]
    assert per.parse_systems(None) == []


def test_each_systems_downtime_and_cost_from_columns():
    mapping = {**MAPPING, "downtime": "downtime", "cost": "total cost"}
    payload, _ = rec.fit(_frame(costs=True), mapping, "crow_amsaa", "days")
    sc = payload["system_costs"]
    g3 = sc["systems"][0]
    assert g3["system"] == "G3"  # most cost first
    assert g3["failures"] == 8
    assert g3["downtime"] == pytest.approx(sum(2.0 + k for k in range(8)))  # 44 h
    assert g3["cost"] == pytest.approx(8 * 1500.0)
    assert g3["cost_per_failure"] == pytest.approx(1500.0)
    assert sc["total"]["failures"] == 33
    assert sc["total"]["cost"] == pytest.approx(33 * 1000.0 + 8 * 500.0)
    assert g3["cost_share"] == pytest.approx(12000.0 / 37000.0)
    # Without the columns: nothing guessed.
    payload, _ = rec.fit(_frame(costs=True), MAPPING, "crow_amsaa", "days")
    assert "system_costs" not in payload


def test_downtime_and_cost_are_never_read_out_of_words():
    df = _frame(costs=True).astype({"total cost": object})
    df.loc[0, "total cost"] = "about $900 for parts"
    df.loc[1, "downtime"] = None
    mapping = {**MAPPING, "downtime": "downtime", "cost": "total cost"}
    with pytest.raises(FitError, match="must hold numbers"):
        rec.fit(df, mapping, "crow_amsaa", "days")
    df.loc[0, "total cost"] = None
    payload, _ = rec.fit(df, mapping, "crow_amsaa", "days")
    assert payload["system_costs"]["missing"] == {"downtime": 1, "cost": 1}


def test_api_fits_saves_and_exports_one_system(monkeypatch):
    from backend.auth import get_current_user

    client, app = _client(monkeypatch, mongomock.MongoClient()["reliafy_test"])
    buf = io.BytesIO()
    _frame(G3_END, costs=True).to_csv(buf, index=False)
    csv = buf.getvalue()
    form = {**MAPPING, "model": "crow_amsaa", "unit": "days", "systems": ["G3"],
            "downtime": "downtime", "cost": "total cost"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        r = client.post("/api/recurrent/fit", data=form, files={"file": ("g.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        assert res["n_systems"] == 1 and res["subset"]["systems"] == ["G3"]
        assert res["system_costs"]["systems"][0]["cost"] == pytest.approx(12000.0)
        assert r.json()["spec"]["systems"] == ["G3"]

        r = client.post("/api/recurrent/models", data={**form, "name": "G3 alone"},
                        files={"file": ("g.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        assert r.json()["spec"]["systems"] == ["G3"]
        assert r.json()["results"]["n_systems"] == 1
        pred = client.post(f"/api/recurrent/models/{mid}/predict", json={"horizon": 1200})
        assert pred.status_code == 200, pred.text
        src = client.get(f"/api/recurrent/models/{mid}/export.py")
        assert src.status_code == 200, src.text
        assert "G3" in src.text and "G1" not in src.text  # the script's data is G3's only

        bad = client.post("/api/recurrent/fit", data={**form, "systems": ["G9"]},
                          files={"file": ("g.csv", csv, "text/csv")})
        assert bad.status_code == 422 and "G9" in json.dumps(bad.json())
    finally:
        app.dependency_overrides.clear()
