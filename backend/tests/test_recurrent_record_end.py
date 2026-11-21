"""The end of test on a repairable fit: one prototype's 12 failures in a test
that ran to 1,000 hours. Given the end, the fit is time-terminated and
matches the closed form; without it, it ends at the last failure (940 h) and
says so."""

import json
import math
from pathlib import Path

import mongomock
import pandas as pd
import pytest

from backend import recurrent as rec
from backend.fitting import FitError
from backend.tests.test_recurrent import A, _client

CSV = Path(__file__).parent / "fixtures" / "prototype_growth_test.csv"
MAPPING = {"i": "unit", "x": "hours_at_failure"}
END = 1000.0


def _times() -> list[float]:
    return pd.read_csv(CSV)["hours_at_failure"].astype(float).tolist()


def _closed_form(end: float) -> tuple[float, float]:
    """Crow-AMSAA maximum likelihood for one system: time-terminated at
    ``end`` (failure-terminated when ``end`` is the last failure, whose
    log term is then zero but still counted in n)."""
    t = _times()
    n = len(t)
    beta = n / sum(math.log(end / ti) for ti in t)
    mtbf = end / (n * beta)
    return beta, mtbf


def test_closed_form_hand_check():
    beta, mtbf = _closed_form(END)
    assert beta == pytest.approx(0.511, abs=5e-4)
    assert mtbf == pytest.approx(163.1, abs=0.1)


def test_typed_end_of_test_gives_the_time_terminated_answer():
    df = pd.read_csv(CSV)
    payload, _ = rec.fit(df, MAPPING, "crow_amsaa", "hours", gof_test=False, record_end=END)
    beta, mtbf = _closed_form(END)
    assert payload["beta"] == pytest.approx(beta, rel=1e-4)
    assert payload["mtbf"] == pytest.approx(mtbf, rel=1e-4)
    assert payload["end_of_observation"] == END
    assert payload["termination"] == {"kind": "time", "end": END, "source": "value",
                                     "ends": [{"end": END, "systems": ["P1"]}]}
    assert not any(w["id"] == "no_record_end" for w in payload.get("warnings") or [])


def test_end_of_record_column_gives_the_same_answer():
    df = pd.read_csv(CSV).assign(test_end=END)
    payload, _ = rec.fit(df, {**MAPPING, "tr": "test_end"}, "crow_amsaa", "hours", gof_test=False)
    assert payload["beta"] == pytest.approx(_closed_form(END)[0], rel=1e-4)
    assert payload["termination"] == {"kind": "time", "end": END, "source": "data",
                                     "ends": [{"end": END, "systems": ["P1"]}]}


def test_nothing_given_is_failure_terminated_and_says_so():
    df = pd.read_csv(CSV)
    payload, _ = rec.fit(df, MAPPING, "crow_amsaa", "hours", gof_test=False)
    beta, mtbf = _closed_form(940.0)
    assert payload["beta"] == pytest.approx(beta, rel=1e-4)  # 0.527
    assert payload["mtbf"] == pytest.approx(mtbf, rel=1e-4)  # 148.5 h
    assert payload["termination"] == {"kind": "failure", "end": 940.0}
    assert any(w["id"] == "no_record_end" for w in payload["warnings"])


def test_a_typed_end_fills_only_systems_without_their_own():
    df = pd.DataFrame({"s": ["A", "A", "B", "B"], "t": [10.0, 30.0, 20.0, 50.0], "end": [40.0, 40.0, None, None]})
    out, mapping = rec.with_record_end(df, {"i": "s", "x": "t", "tr": "end"}, 60)
    assert out[mapping["tr"]].tolist() == [40.0, 40.0, 60.0, 60.0]


def test_an_end_before_the_last_failure_is_refused():
    df = pd.read_csv(CSV)
    with pytest.raises(FitError, match="later, at 940"):
        rec.fit(df, MAPPING, "crow_amsaa", "hours", record_end=900)
    with pytest.raises(FitError, match="must be a number"):
        rec.fit(df, MAPPING, "crow_amsaa", "hours", record_end="soon")


def test_api_fit_and_save_keep_the_end_of_test(monkeypatch):
    from backend.auth import get_current_user

    client, app = _client(monkeypatch, mongomock.MongoClient()["reliafy_test"])
    form = {**MAPPING, "model": "crow_amsaa", "unit": "hours", "record_end": "1000"}
    files = {"file": ("growth.csv", CSV.read_bytes(), "text/csv")}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        r = client.post("/api/recurrent/fit", data=form, files=files)
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        assert res["mtbf"] == pytest.approx(_closed_form(END)[1], rel=1e-4)
        assert res["termination"]["kind"] == "time"

        r = client.post("/api/recurrent/models", data={**form, "name": "Prototype growth"},
                        files={"file": ("growth.csv", CSV.read_bytes(), "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["spec"]["record_end"] == END
        mid = r.json()["id"]
        # The saved model refits with it (predict refits on demand).
        pred = client.post(f"/api/recurrent/models/{mid}/predict", json={"horizon": 1500})
        assert pred.status_code == 200, pred.text
        # Download as Python carries it too.
        src = client.get(f"/api/recurrent/models/{mid}/export.py")
        assert src.status_code == 200, src.text
        assert "1000" in src.text

        bad = client.post("/api/recurrent/fit", data={**form, "record_end": "900"},
                          files={"file": ("growth.csv", CSV.read_bytes(), "text/csv")})
        assert bad.status_code == 422 and "940" in json.dumps(bad.json())
    finally:
        app.dependency_overrides.clear()
