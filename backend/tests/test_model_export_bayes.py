"""Download as Python for a saved Bayesian update: the script refits from the
saved recipe (the history and the prior) and prints the page's numbers."""

from __future__ import annotations

import pytest

from backend.tests.python_scripts import close, run
from backend.tests.test_library_user import CSV, PRO, web  # noqa: F401
from backend.tests.test_mcp_plans import env  # noqa: F401

pytestmark = pytest.mark.usefixtures("mcp_on")

WEIBULL_PRIOR = {"kind": "params", "distribution": "weibull", "unit": "hours",
                 "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}]}


def test_a_bayesian_update_prints_its_credible_numbers(web, tmp_path):
    r = web.post("/api/models/fit-with-prior", json={
        "time_column": "time", "censor_column": "c", "unit": "hours", "distribution": "weibull",
        "prior": WEIBULL_PRIOR, "trust": "guide", "content": CSV, "save": True, "name": "Pump with a prior"})
    assert r.status_code == 200, r.text
    saved = r.json()
    res = web.get(f"/api/models/{saved['id']}/export.py")
    assert res.status_code == 200, res.text
    assert "fit_bayes(" in res.text
    printed = run(res.text, tmp_path)
    results = saved["results"]
    for p in results["params"]:
        close(printed[p["name"]]["value"], p["value"])
        close(printed[p["name"]]["low"], p["ci"][0])
        close(printed[p["name"]]["high"], p["ci"][1])
    for b in results["life"]["b_lives"]:
        close(printed[b["label"]]["value"], b["value"])
        close(printed[b["label"]]["bound"], b["lower"])
    close(printed["Mean life"]["value"], results["life"]["mttf"]["value"])
    close(printed["Mean life"]["bound"], results["life"]["mttf"]["lower"])
