"""Gating of the #232/#235 MCP tools: projecting from a saved model and a
system's next failure are exact maths on saved data (Free's allowance);
projecting from inline data fits in Reliafy, so it is Pro, like fitting."""

import io

import pandas as pd

from backend.tests.test_mcp_plans import FREE, FREE_PRO_ONLY, PRO, _call, _err, _ok, env  # noqa: F401 - a fixture

X = [15, 42, 60, 98, 130, 171, 205, 260, 310, 345, 390]
MODES = ["b1", "a1", "b2", "b1", "b3", "a2", "b2", "b4", "b1", "a1", "b3"]
FEF = {"b1": 0.8, "b2": 0.7, "b3": 0.75, "b4": 0.6}


def _model(env, owner):
    from backend.services import datasets as datasets_service
    from backend.services import recurrent as recurrent_service

    buf = io.StringIO()
    pd.DataFrame({"sys": "P1", "t": X, "m": MODES}).to_csv(buf, index=False)
    ds = datasets_service.create_dataset(env.db, "p.csv", buf.getvalue().encode(), owner)
    return recurrent_service.save_model(env.db, "Prototype", ds, {
        "mapping": {"i": "sys", "x": "t", "mode": "m"}, "model_id": "crow_amsaa", "unit": "hours"}, owner)


def test_free_projects_saved_models_but_not_inline_data(env):
    doc = _model(env, FREE)
    out = _ok(_call(env.oauth[FREE], "growth_projection", {"model_id": doc.id, "fef": FEF, "test_end": 400}))
    assert round(out["projected"]["mtbf"], 1) == 62.8
    assert _ok(_call(env.oauth[FREE], "next_failure", {"model_id": doc.id, "age": 400}))["quantiles"]
    msg = _err(_call(env.oauth[FREE], "growth_projection", {"x": X, "modes": MODES, "fef": FEF,
                                                            "test_end": 400}))
    assert FREE_PRO_ONLY in msg and "model's id" in msg
    out = _ok(_call(env.oauth[PRO], "growth_projection", {"x": X, "modes": MODES, "fef": FEF, "test_end": 400}))
    assert round(out["growth_potential"]["mtbf"], 2) == 78.43
