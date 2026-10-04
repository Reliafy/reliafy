"""Reliability growth projection (#232) and a repairable system's next
failure (#235): SurPyval 0.23's ``CrowAMSAA.projection`` behind the
recurrent model page, its API and the ``growth_projection`` / ``next_failure``
MCP tools. Numbers are checked against SurPyval called directly."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from surpyval.recurrent import HPP, CrowAMSAA  # noqa: E402

from backend.tests.test_mcp import A, B, _call, _err, _ok, env  # noqa: E402,F401 - env is a fixture
from backend.tests.test_recurrent import _client  # noqa: E402

# SurPyval's own example (CrowAMSAA.projection docstring): one prototype to 400 h.
X = [15, 42, 60, 98, 130, 171, 205, 260, 310, 345, 390]
MODES = ["b1", "a1", "b2", "b1", "b3", "a2", "b2", "b4", "b1", "a1", "b3"]
FEF = {"b1": 0.8, "b2": 0.7, "b3": 0.75, "b4": 0.6}
MAP = {"i": "sys", "x": "t", "mode": "m"}


def _one_system():
    return pd.DataFrame({"sys": "P1", "t": X, "m": MODES})


def _three_systems(seed=3, T=500.0):
    """Three prototypes side by side to T, each row with its window and mode."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in ("P1", "P2", "P3"):
        t = np.sort(rng.uniform(0, T, 14)).round(1)
        for v in t:
            rows.append({"sys": s, "t": float(v), "m": rng.choice(["seal", "pump", "valve", "wiring", "fan"]),
                         "window": T})
    return pd.DataFrame(rows)


# ---- The maths: SurPyval's numbers, Reliafy's inputs ---------------------------------

def test_matches_surpyval_example():
    from backend import recurrent as rec

    out = rec.growth_projection(_one_system(), MAP, FEF, test_end=400)
    ref = CrowAMSAA.projection(X + [400], MODES + [None], FEF, c=[0] * 11 + [1])
    assert out["demonstrated"]["mtbf"] == pytest.approx(ref.demonstrated_mtbf, rel=1e-12)
    assert out["projected"]["mtbf"] == pytest.approx(ref.projected_mtbf, rel=1e-12)
    assert out["growth_potential"]["mtbf"] == pytest.approx(ref.growth_potential_mtbf, rel=1e-12)
    assert out["new_mode_intensity"] == pytest.approx(ref.new_mode_intensity, rel=1e-12)
    assert out["beta_bd"] == pytest.approx(ref.beta, rel=1e-12)
    # The docstring's own figures.
    assert out["demonstrated"]["mtbf"] == pytest.approx(36.36, abs=0.01)
    assert out["projected"]["mtbf"] == pytest.approx(62.8, abs=0.01)
    assert out["growth_potential"]["mtbf"] == pytest.approx(78.43, abs=0.01)
    assert out["failures"] == {"A": 3, "BC": 0, "BD": 8} and out["n_bd_modes"] == 4
    # The projected intensity is the sum of its parts.
    c = out["components"]
    assert c["unfixed"] + c["bd_residual"] + c["unseen_bd"] == pytest.approx(out["projected"]["intensity"])
    b1 = next(m for m in out["modes"] if m["label"] == "b1")
    assert b1 == pytest.approx({"label": "b1", "kind": "BD", "failures": 3, "first": 15.0, "intensity": 3 / 400,
                                "fef": 0.8, "projected": 0.2 * 3 / 400, "removed": 0.8 * 3 / 400})
    assert {m["label"]: m["kind"] for m in out["modes"]}["a2"] == "A"


def test_several_systems_windows_and_bc_modes_match_surpyval():
    from backend import recurrent as rec

    df = _three_systems()
    fef = {"seal": 0.8, "pump": 0.6}
    out = rec.growth_projection(df, {**MAP, "tr": "window"}, fef, bc=["valve"])
    # The windows become each system's end-of-test row, as SurPyval takes them.
    x = list(df.t) + [500.0] * 3
    i = list(df.sys) + ["P1", "P2", "P3"]
    c = [0] * len(df) + [1] * 3
    ref = CrowAMSAA.projection(x, list(df.m) + [None] * 3, fef, i=i, c=c, bc=["valve"])
    assert out["systems"] == 3 and out["T"] == 500.0 and out["demonstrated_basis"] == "crow_amsaa"
    assert out["demonstrated"]["intensity"] == pytest.approx(ref.demonstrated_intensity, rel=1e-10)
    assert out["projected"]["intensity"] == pytest.approx(ref.projected_intensity, rel=1e-10)
    assert out["growth_potential"]["intensity"] == pytest.approx(ref.growth_potential_intensity, rel=1e-10)
    assert out["failures"] == ref.failures


def test_counts_are_expanded_and_c1_rows_end_the_test():
    from backend import recurrent as rec

    df = pd.DataFrame({"sys": ["S"] * 4, "t": [50, 120, 300, 400], "m": ["a", "b", "b", None],
                       "c": [0, 0, 0, 1], "n": [2, 1, 1, 1]})
    out = rec.growth_projection(df, {**MAP, "c": "c", "n": "n"}, {"b": 0.7})
    ref = CrowAMSAA.projection([50, 50, 120, 300, 400], ["a", "a", "b", "b", None], {"b": 0.7}, c=[0, 0, 0, 0, 1])
    assert out["projected"]["mtbf"] == pytest.approx(ref.projected_mtbf, rel=1e-12)
    assert out["failures"] == {"A": 2, "BC": 0, "BD": 2}


@pytest.mark.parametrize("fef,bc,end,needle", [
    ({"b1": 1.4}, None, 400, "from 0 to 1"),
    ({"b1": "x"}, None, 400, "must be a number"),
    ({"zz": 0.7}, None, 400, "No failures of 'zz'"),
    ({"b1": 0.7}, ["b1"], 400, "not both"),
    ({"b1": 0.7}, "b2", 400, "list of the modes"),
    ({"b1": 0.7}, None, None, "time-terminated"),
    ({"b1": 0.7}, None, -5, "positive"),
])
def test_bad_settings_say_why(fef, bc, end, needle):
    from backend import recurrent as rec
    from backend.fitting import FitError

    with pytest.raises(FitError, match=needle):
        rec.growth_projection(_one_system(), MAP, fef, bc=bc, test_end=end)


def test_unlabelled_failures_and_censoring_are_refused():
    from backend import recurrent as rec
    from backend.fitting import FitError

    df = _one_system()
    df.loc[3, "m"] = ""
    with pytest.raises(FitError, match="1 failure has no failure mode"):
        rec.growth_projection(df, MAP, FEF, test_end=400)
    df = _one_system().assign(c=[0] * 10 + [-1])
    with pytest.raises(FitError, match="left- or interval-censored"):
        rec.growth_projection(df, {**MAP, "c": "c"}, FEF, test_end=400)
    with pytest.raises(FitError, match="failure-mode column"):
        rec.growth_projection(_one_system(), {"i": "sys", "x": "t"}, FEF, test_end=400)


def test_fit_lists_the_failure_modes_when_mapped():
    from backend import recurrent as rec

    payload, _ = rec.fit(_one_system(), MAP)
    assert payload["failure_modes"][0] == {"label": "b1", "failures": 3, "first": 15.0}
    assert len(payload["failure_modes"]) == 6
    assert "failure_modes" not in rec.fit(_one_system(), {"i": "sys", "x": "t"})[0]


# ---- The API: compute, save with the model, viewers don't write ---------------------

def _csv(df) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_api_projection_saved_with_the_model(monkeypatch):
    from backend import config
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    user = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: {"uid": user["uid"], "email": "x@x.com", "name": "X"}
    df = _one_system().assign(note="x")
    try:
        r = client.post("/api/recurrent/models", data={"name": "Prototype", "i": "sys", "x": "t", "mode": "m",
                                                       "unit": "hours"},
                        files={"file": ("t.csv", _csv(df), "text/csv")})
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        assert r.json()["spec"]["mapping"]["mode"] == "m"
        assert r.json()["results"]["failure_modes"][0]["label"] == "b1"

        url = f"/api/recurrent/models/{mid}/projection"
        view = client.get(url).json()
        assert view["available"] and view["mode_column"] == "m" and view["can_save"]
        assert view["columns"] == ["m", "note"] and view["default_fef"] == 0.7
        assert [m["label"] for m in view["modes"]][:2] == ["b1", "a1"] and view["result"] is None
        # Another column can be chosen as the mode for the view.
        assert {m["label"] for m in client.get(url, params={"mode_column": "note"}).json()["modes"]} == {"x"}

        assert client.post(url, json={"fef": FEF}).status_code == 422  # no end of test
        r = client.post(url, json={"fef": FEF, "test_end": 400})
        assert r.status_code == 200, r.text
        assert r.json()["saved"] is True
        assert r.json()["result"]["projected"]["mtbf"] == pytest.approx(62.8, abs=0.01)
        assert r.json()["result"]["unit"] == "hours"
        doc = test_db.recurrent_models.find_one({"_id": mid})
        assert doc["spec"]["projection"] == {"mode_column": "m", "fef": FEF, "bc": [], "test_end": 400.0}
        assert doc["results"]["projection"]["projected"]["mtbf"] == pytest.approx(62.8, abs=0.01)
        assert client.get(url).json()["settings"]["fef"] == FEF
        assert client.get(f"/api/recurrent/models/{mid}").json()["results"]["projection"]["T"] == 400.0

        # Another user can't see it; a read-only viewer computes without saving.
        user["uid"] = B
        assert client.post(url, json={"fef": FEF, "test_end": 400}).status_code == 404
        assert client.get(url).status_code == 404
        test_db.recurrent_models.update_one({"_id": mid}, {"$set": {"owner_id": config.SAMPLE_OWNER}})
        test_db.datasets.update_many({}, {"$set": {"owner_id": config.SAMPLE_OWNER}})
        before = test_db.recurrent_models.find_one({"_id": mid})
        assert client.get(url).json()["can_save"] is False
        r = client.post(url, json={"fef": {"b1": 0.5}, "test_end": 400})
        assert r.status_code == 200 and r.json()["saved"] is False
        assert test_db.recurrent_models.find_one({"_id": mid}) == before
    finally:
        app.dependency_overrides.clear()


def test_api_projection_needs_data(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
    try:
        r = client.post("/api/recurrent/from-params", data={
            "name": "Typed", "model": "crow_amsaa", "alpha": 100, "beta": 0.8, "horizon": 500})
        mid = r.json()["id"]
        view = client.get(f"/api/recurrent/models/{mid}/projection").json()
        assert view["available"] is False and "built from parameters" in view["reason"]
        r = client.post(f"/api/recurrent/models/{mid}/projection", json={"fef": {"a": 0.7}, "test_end": 9})
        assert r.status_code == 422 and "built from parameters" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---- MCP -----------------------------------------------------------------------------

def _saved(env, df, mapping, name="Prototype", model_id="crow_amsaa"):
    from backend.services import datasets as datasets_service
    from backend.services import recurrent as recurrent_service

    ds = datasets_service.create_dataset(env.db, f"{name}.csv", _csv(df), A)
    return recurrent_service.save_model(env.db, name, ds, {"mapping": mapping, "model_id": model_id,
                                                           "unit": "hours"}, A)


def test_mcp_growth_projection_from_a_saved_model(env):
    doc = _saved(env, _one_system(), MAP)
    out = _ok(_call(env.token[A], "growth_projection", {"model_id": doc.id, "bd_modes": ["b2", "b3"],
                                                        "fef": {"b1": 0.8, "b4": 0.6, "b3": 0.75},
                                                        "test_end": 400}))
    # bd_modes default to 0.7; fef overrides.
    assert out["fef"] == {"b2": 0.7, "b3": 0.75, "b1": 0.8, "b4": 0.6}
    assert out["projected"]["mtbf"] == pytest.approx(62.8, abs=0.01)
    assert "62.8" in out["summary"] and "36.36" in out["summary"] and out["url"].endswith(doc.id)
    # Nothing is saved by the tool...
    assert "projection" not in env.db.recurrent_models.find_one({"_id": doc.id})["spec"]
    # ...and with no settings and none saved it lists the modes to classify.
    msg = _err(_call(env.token[A], "growth_projection", {"model_id": doc.id}))
    assert "b1 (3)" in msg and "fef" in msg
    # With saved settings (the app's), it reuses them, and get_model shows the headline.
    from backend.services import recurrent as recurrent_service

    payload = recurrent_service.run_projection(env.db, doc, fef=FEF, test_end=400)
    recurrent_service.save_projection(env.db, doc, payload, None, A)
    out = _ok(_call(env.token[A], "growth_projection", {"model_id": doc.id}))
    assert out["projected"]["mtbf"] == pytest.approx(62.8, abs=0.01)
    brief = _ok(_call(env.token[A], "get_model", {"model_id": doc.id}))["growth_projection"]
    assert brief["projected_mtbf"] == pytest.approx(62.8, abs=0.01) and brief["demonstrated_mtbf"] == 36.36
    # B can't reach A's model.
    assert "not found" in _err(_call(env.token[B], "growth_projection", {"model_id": doc.id, "fef": FEF}))


def test_mcp_growth_projection_inline(env):
    out = _ok(_call(env.token[A], "growth_projection", {"x": X, "modes": MODES, "fef": FEF, "test_end": 400,
                                                        "unit": "hours"}))
    assert out["growth_potential"]["mtbf"] == pytest.approx(78.43, abs=0.01) and out["unit"] == "hours"
    assert "test_end" in _err(_call(env.token[A], "growth_projection", {"x": X, "modes": MODES, "fef": FEF}))
    assert "same length" in _err(_call(env.token[A], "growth_projection", {"x": X, "modes": MODES[:3],
                                                                           "fef": FEF, "test_end": 400}))
    assert "not both" in _err(_call(env.token[A], "growth_projection", {"fef": FEF}))
    # Inline data is a Crow-AMSAA fit, with no saved model to flag.
    assert out["projected_with"] == "crow_amsaa" and out["saved_model"] is None and "note" not in out


@pytest.mark.parametrize("kind, name", [("duane", "Duane"), ("hpp", "HPP")])
def test_projection_from_a_non_crow_amsaa_model_says_so(env, kind, name):
    """#232: a Duane or HPP model's data projects with a Crow-AMSAA fit — the
    same numbers — and every surface says so; a Crow-AMSAA model's doesn't."""
    from backend.services import recurrent as recurrent_service

    note = f"Projected with a Crow-AMSAA fit to the same data (your saved model is {name})."
    doc = _saved(env, _one_system(), MAP, name=f"Proto {kind}", model_id=kind)
    out = _ok(_call(env.token[A], "growth_projection", {"model_id": doc.id, "fef": FEF, "test_end": 400}))
    assert out["projected"]["mtbf"] == pytest.approx(62.8, abs=0.01)  # the same Crow-AMSAA projection
    assert out["projected_with"] == "crow_amsaa" and out["saved_model"] == kind
    assert out["note"] == note and out["basis_note"] == note and out["summary"].startswith(note)
    assert next(iter(out)) == "note"  # leads the output

    # The app's result and panel view carry it; get_model's headline leads with it.
    payload = recurrent_service.run_projection(env.db, doc, fef=FEF, test_end=400)
    assert payload["saved_model"] == kind and payload["basis_note"] == note
    assert recurrent_service.projection_view(env.db, doc)["basis_note"] == note
    recurrent_service.save_projection(env.db, doc, payload, None, A)
    brief = _ok(_call(env.token[A], "get_model", {"model_id": doc.id}))["growth_projection"]
    assert brief["note"] == note and brief["projected_with"] == "crow_amsaa" and brief["saved_model"] == kind
    assert brief["projected_mtbf"] == pytest.approx(62.8, abs=0.01)

    # A Crow-AMSAA model's projection carries the fields but no note.
    ca = _saved(env, _one_system(), MAP, name="Proto CA")
    out = _ok(_call(env.token[A], "growth_projection", {"model_id": ca.id, "fef": FEF, "test_end": 400}))
    assert out["projected_with"] == "crow_amsaa" and out["saved_model"] == "crow_amsaa"
    assert out["basis_note"] is None and "note" not in out and not out["summary"].startswith("Projected")
    assert recurrent_service.projection_view(env.db, ca)["basis_note"] is None


# ---- next_failure ---------------------------------------------------------------------

def test_next_failure_closed_form_crow_amsaa():
    from backend import recurrent as rec

    alpha, beta, age = 50.0, 1.3, 400.0
    out = rec.next_failure(CrowAMSAA.from_params([alpha, beta]), age, within=[10, 100], quantiles=[0.5])

    def lam(t):
        return (t / alpha) ** beta

    for row, w in zip(out["within"], [10, 100]):
        assert row["expected_failures"] == pytest.approx(lam(age + w) - lam(age), rel=1e-12)
        assert row["prob_failure"] == pytest.approx(1 - np.exp(-(lam(age + w) - lam(age))), rel=1e-12)
    med = out["quantiles"][0]
    assert lam(med["age_at"]) - lam(age) == pytest.approx(np.log(2), rel=1e-9)
    assert out["rocof"] == pytest.approx(beta / alpha * (age / alpha) ** (beta - 1), rel=1e-12)
    # The mean time to the next failure, numerically.
    grid = np.linspace(0, 400, 400001)
    mean = np.trapezoid(np.exp(-(lam(age + grid) - lam(age))), grid)
    assert out["mean_time_to_next_failure"] == pytest.approx(mean, rel=1e-5)


def test_next_failure_hpp_is_exponential():
    from backend import recurrent as rec

    model = HPP.from_params([0.02])
    out = rec.next_failure(model, 1234.0, within=[50])
    assert out["mean_time_to_next_failure"] == pytest.approx(50.0, rel=1e-6)
    assert out["within"][0]["prob_failure"] == pytest.approx(1 - np.exp(-1.0), rel=1e-9)
    assert [q["time_ahead"] for q in out["quantiles"]] == pytest.approx([-50 * np.log(1 - q) for q in (.1, .5, .9)])


@pytest.mark.parametrize("kw,needle", [({"age": -1}, "age"), ({"age": 1, "within": [0]}, "within"),
                                       ({"age": 1, "quantiles": [1.0]}, "Quantiles")])
def test_next_failure_validates(kw, needle):
    from backend import recurrent as rec
    from backend.fitting import FitError

    with pytest.raises(FitError, match=needle):
        rec.next_failure(HPP.from_params([0.02]), **kw)


def test_mcp_next_failure(env):
    from backend.services import recurrent as recurrent_service

    doc = recurrent_service.save_from_params(
        env.db, "Pumps", "crow_amsaa", [{"name": "alpha", "value": 50}, {"name": "beta", "value": 1.3}], 1000,
        "hours", A)
    out = _ok(_call(env.token[A], "next_failure", {"model_id": doc.id, "age": 400, "within": [100]}))
    ref = CrowAMSAA.from_params([50.0, 1.3])
    mu = float(ref.cif(500.0) - ref.cif(400.0))
    assert out["within"][0]["expected_failures"] == pytest.approx(mu, rel=1e-12)
    assert out["unit"] == "hours" and out["model_id"] == doc.id and "Minimal repair" in out["assumption"]
    assert "not found" in _err(_call(env.token[B], "next_failure", {"model_id": doc.id, "age": 400}))
