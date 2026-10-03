"""Confidence bands on a non-repairable RBD from its fitted blocks' parameter
uncertainty (#103, RePyability 0.9)."""

import io
import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as surv

from backend.services import rbd_uncertainty
from backend.services.rbd_analysis import AnalysisError, analyze

# A pump population fitted to a handful of failures: a wide covariance.
FIT = surv.Weibull.fit(np.array([90.0, 110, 120, 130, 140, 155, 170, 190, 200, 230, 260]))
# A second, much better-known population (many failures).
FIT_TIGHT = surv.Weibull.fit(
    np.random.default_rng(4).weibull(3.0, 400) * 400.0
)


def _saved(model_id, fit, name="Pump fit"):
    alpha, beta = (float(v) for v in fit.params)
    return {
        "source": "saved", "kind": "distribution", "modelId": model_id, "name": name,
        "distribution_id": "weibull", "distribution": "Weibull",
        "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}],
    }


HAND = {
    "source": "params", "distribution_id": "exponential",
    "params": [{"name": "failure_rate", "value": 1e-4}],
}


def _node(nid, model, ntype="component", **extra):
    return {"id": nid, "type": ntype, "data": {"label": nid.upper(), "model": model, **extra}}


def _io():
    return [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}}]


def _edges(*pairs):
    return [{"id": f"{a}-{b}", "source": a, "target": b} for a, b in pairs]


def _graph(nodes, edges):
    return {"unit": "h", "nodes": _io() + nodes, "edges": edges}


def _resolver(models):
    return lambda model_id: {"model": models[model_id]} if model_id in models else None


def _pumps_and_valve(model_a="m1", model_b="m1"):
    """Two pumps in parallel, then a hand-entered valve in series."""
    return _graph(
        [_node("a", _saved(model_a, FIT)), _node("b", _saved(model_b, FIT)), _node("v", HAND)],
        _edges(("input", "a"), ("input", "b"), ("a", "v"), ("b", "v"), ("v", "output")),
    )


def test_band_is_only_computed_when_asked():
    res = analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}))
    assert "band" not in res


def test_band_brackets_the_point_estimates_and_names_the_blocks():
    graph = _pumps_and_valve()
    res = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={"level": 0.9})
    json.dumps(res)  # JSON-safe
    band = res["band"]
    assert band["level"] == 0.9 and band["n_draws"] == 1000
    assert {b["id"] for b in band["uncertain"]} == {"a", "b"}
    assert band["uncertain"][0]["models"] == ["Pump fit"]
    assert band["fixed"] == [{"id": "v", "label": "V", "reason": "hand-entered parameters"}]

    sf = np.array(res["system"]["sf"])
    lo, hi = np.array(band["sf_lower"]), np.array(band["sf_upper"])
    assert lo.shape == sf.shape == hi.shape
    assert np.all(lo <= hi + 1e-12)
    # The point curve lies inside the band where the system is uncertain.
    mid = (sf > 0.05) & (sf < 0.95)
    assert mid.any()
    assert np.all((lo[mid] <= sf[mid]) & (sf[mid] <= hi[mid]))
    assert np.max(hi - lo) > 0.1  # 11 failures: a genuinely wide band

    assert band["mttf"]["lower"] < res["mttf"] < band["mttf"]["upper"]
    for key in ("b10", "b50"):
        iv = band["blife"][key]
        assert iv["lower"] < res["blife"][key] < iv["upper"]


def test_a_higher_level_gives_a_wider_band():
    graph = _pumps_and_valve()
    narrow = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={"level": 0.5})["band"]
    wide = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={"level": 0.99})["band"]
    assert wide["mttf"]["upper"] - wide["mttf"]["lower"] > narrow["mttf"]["upper"] - narrow["mttf"]["lower"]


def test_blocks_of_one_saved_model_share_its_draw():
    # The same fit under two model ids is drawn independently; under one id the
    # redundant pumps share every draw, so their uncertainty doesn't average
    # out and the band is wider.
    shared = analyze(_pumps_and_valve("m1", "m1"), resolve_model=_resolver({"m1": FIT}), band={})
    independent = analyze(
        _pumps_and_valve("m1", "m2"), resolve_model=_resolver({"m1": FIT, "m2": FIT}), band={}
    )
    width = lambda b: np.array(b["sf_upper"]) - np.array(b["sf_lower"])  # noqa: E731
    assert width(shared["band"]).max() > width(independent["band"]).max()
    assert shared["system"]["sf"] == independent["system"]["sf"]


def test_the_band_is_reproducible():
    graph = _pumps_and_valve()
    one = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={})["band"]
    two = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={})["band"]
    assert one == two


def test_a_well_known_model_gives_a_narrower_band():
    loose = analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}), band={})["band"]
    graph = _pumps_and_valve()
    for n in graph["nodes"]:
        if n["id"] in ("a", "b"):
            n["data"]["model"] = _saved("m1", FIT_TIGHT)
    tight = analyze(graph, resolve_model=_resolver({"m1": FIT_TIGHT}), band={})["band"]
    rel = lambda b: (b["mttf"]["upper"] - b["mttf"]["lower"]) / b["mttf"]["lower"]  # noqa: E731
    assert rel(tight) < rel(loose) / 3


def test_wrapper_blocks_carry_the_uncertainty():
    # A parallel count block and a cold-standby pair, both on the saved fit.
    graph = _graph(
        [
            _node("p", _saved("m1", FIT), "parallel", n=2),
            _node("s", _saved("m1", FIT), "standby", spares=1, cold=True),
        ],
        _edges(("input", "p"), ("p", "s"), ("s", "output")),
    )
    res = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={})
    band = res["band"]
    assert {b["id"] for b in band["uncertain"]} == {"p", "s"}
    assert band["n_draws"] < 1000  # standby blocks are rebuilt per draw: fewer
    assert band["mttf"]["lower"] < res["mttf"] < band["mttf"]["upper"]


def test_sub_system_blocks_share_the_parent_draws():
    sub = _graph([_node("x", _saved("m1", FIT))], _edges(("input", "x"), ("x", "output")))
    graph = _graph(
        [
            _node("a", _saved("m1", FIT)),
            {"id": "sub", "type": "subsystem",
             "data": {"label": "Skid", "rbd": {"id": "r-sub", "name": "Skid"}}},
        ],
        _edges(("input", "a"), ("input", "sub"), ("a", "output"), ("sub", "output")),
    )
    res = analyze(
        graph, resolve_subsystem=lambda rid: sub if rid == "r-sub" else None,
        resolve_model=_resolver({"m1": FIT}), band={}, t_max=300,
    )
    labels = {b["label"] for b in res["band"]["uncertain"]}
    assert labels == {"A", "Skid › X"}
    # Same model inside and outside the sub-system == the shared-draw pair.
    flat = analyze(_graph(
        [_node("a", _saved("m1", FIT)), _node("b", _saved("m1", FIT))],
        _edges(("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")),
    ), resolve_model=_resolver({"m1": FIT}), band={}, t_max=300)
    assert res["band"]["sf_lower"] == pytest.approx(flat["band"]["sf_lower"], abs=1e-12)


def test_conditional_age_band_is_on_the_residual_life():
    graph = _pumps_and_valve()
    res = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={}, conditional_age=100)
    band = res["band"]
    sf = np.array(res["system"]["sf"])
    assert sf[0] == pytest.approx(1.0)
    assert band["sf_lower"][0] == pytest.approx(1.0) and band["sf_upper"][0] == pytest.approx(1.0)
    assert band["mttf"]["lower"] < res["mttf"] < band["mttf"]["upper"]


def test_pinned_blocks_and_ccf_groups():
    graph = _pumps_and_valve()
    graph["ccf_groups"] = [{"members": ["a", "b"], "beta": 0.1}]
    res = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={})
    sf, lo, hi = (np.array(v) for v in (res["system"]["sf"], res["band"]["sf_lower"], res["band"]["sf_upper"]))
    mid = (sf > 0.05) & (sf < 0.95)
    assert np.all((lo[mid] <= sf[mid]) & (sf[mid] <= hi[mid]))

    graph = _pumps_and_valve()
    graph["nodes"][2]["data"]["state"] = "failed"  # pump a pinned failed
    res = analyze(graph, resolve_model=_resolver({"m1": FIT}), band={})
    assert [b["id"] for b in res["band"]["uncertain"]] == ["b"]


def test_blocks_that_cannot_be_drawn_stay_fixed_with_a_reason():
    frozen = surv.Weibull.from_params([float(v) for v in FIT.params])  # no covariance
    stale = _saved("m3", FIT)
    stale["params"][0]["value"] *= 1.2  # the model was re-fitted since it was picked
    graph = _graph(
        [
            _node("a", _saved("m1", FIT)),
            _node("f", _saved("m2", FIT)),
            _node("s", stale),
            _node("gone", _saved("missing", FIT)),
        ],
        _edges(("input", "a"), ("a", "f"), ("f", "s"), ("s", "gone"), ("gone", "output")),
    )
    band = analyze(
        graph, resolve_model=_resolver({"m1": FIT, "m2": frozen, "m3": FIT}), band={}
    )["band"]
    assert [b["id"] for b in band["uncertain"]] == ["a"]
    reasons = {b["id"]: b["reason"] for b in band["fixed"]}
    assert "covariance" in reasons["f"]
    assert "differ" in reasons["s"]
    assert "couldn't be loaded" in reasons["gone"]


def test_no_fitted_blocks_gives_an_empty_band():
    graph = _graph([_node("v", HAND)], _edges(("input", "v"), ("v", "output")))
    band = analyze(graph, band={})["band"]
    assert band["uncertain"] == [] and band["sf_lower"] is None and band["mttf"] is None
    assert band["fixed"][0]["id"] == "v"


def test_an_invalid_level_is_a_clean_error():
    with pytest.raises(AnalysisError):
        analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}), band={"level": 1.5})


def test_band_is_quick_for_a_plain_diagram():
    import time

    start = time.perf_counter()
    analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}), band={})
    assert time.perf_counter() - start < 5.0


# ---- end to end: a saved model, through the API ------------------------------

A = "user-a"


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _save_model(client, name="Seal fit"):
    rng = np.random.default_rng(9)
    csv = io.BytesIO(pd.DataFrame({"t": rng.weibull(2.0, 15) * 800}).to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": name, "distribution": "weibull", "x": "t", "unit": "hours"},
        files={"file": ("d.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    res = body["results"]
    # The block shape the builder's model picker stores.
    return body["id"], {
        "source": "saved", "kind": body["kind"], "modelId": body["id"], "name": body["name"],
        "distribution": res["distribution"], "distribution_id": res["distribution_id"],
        "params": res["params"], "extras": res.get("extras"),
    }


def test_api_band_from_a_saved_model(client):
    model_id, block = _save_model(client)
    graph = _graph(
        [_node("a", block), _node("b", block)],
        _edges(("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")),
    )
    r = client.post("/api/rbds/analyze", json={"graph": graph, "band": {"level": 0.95}})
    assert r.status_code == 200, r.text
    band = r.json()["band"]
    assert {b["id"] for b in band["uncertain"]} == {"a", "b"}
    assert band["uncertain"][0]["model_ids"] == [model_id]
    assert band["mttf"]["lower"] < r.json()["mttf"] < band["mttf"]["upper"]

    # Without the option the result is unchanged and carries no band.
    plain = client.post("/api/rbds/analyze", json={"graph": graph}).json()
    assert "band" not in plain and plain["mttf"] == r.json()["mttf"]

    # An older saved model (no persisted fit) is refitted once from its dataset.
    from backend.services import models as models_service

    client.db.models.update_one({"_id": model_id}, {"$set": {"serialized": None}})
    models_service._LIVE.clear()
    again = client.post("/api/rbds/analyze", json={"graph": graph, "band": {}}).json()["band"]
    assert again["sf_lower"] == pytest.approx(band["sf_lower"], rel=1e-6)

    bad = client.post("/api/rbds/analyze", json={"graph": graph, "band": {"level": 2}})
    assert bad.status_code == 422


def test_n_draws_sizing():
    assert rbd_uncertainty.n_draws_for(_pumps_and_valve()) == 1000
    standby = _graph(
        [_node(f"s{i}", _saved("m1", FIT), "standby", cold=True) for i in range(3)], []
    )
    assert rbd_uncertainty.n_draws_for(standby) == 200
