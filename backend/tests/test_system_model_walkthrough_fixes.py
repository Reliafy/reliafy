"""Fixes from the system-model walkthroughs (W29 which design, W30 fault tree,
W31 cost of availability): life bounds are one-sided, importance ranks at the
time asked about (agents too), a 1-of-n vote is called an OR, a budget below
the design's own cost says what to enter, and a measure with no exact route
says so in a way the app can act on."""

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import fault_trees as F  # noqa: E402
from backend.services import rbd_design as rd  # noqa: E402
from backend.services import rbd_measures as rm  # noqa: E402
from backend.services.rbd_analysis import analyze  # noqa: E402
from backend.tests.test_fault_trees import _ev, _gate, _tree  # noqa: E402
from backend.tests.test_rbd_design import T, _block, _series  # noqa: E402
from backend.tests.test_rbd_measures import _built, _train  # noqa: E402
from backend.tests.test_rbd_uncertainty import FIT, _pumps_and_valve, _resolver  # noqa: E402


def _band(**band):
    return analyze(_pumps_and_valve(), resolve_model=_resolver({"m1": FIT}), target_reliability=0.9,
                   band={"level": 0.9, **band})


def test_lives_get_a_one_sided_lower_bound():
    """B-lives, the MTTF and the design life: the 10th percentile of the
    draws (at least this long, 90% sure), above the two-sided interval's
    lower end (its 5th percentile) and below the point value."""
    res = _band(b_lives=[1, 10])
    band = res["band"]
    for key, point in (("b10", res["blife"]["b10"]), ("b50", res["blife"]["b50"])):
        iv = band["blife"][key]
        assert iv["bound_side"] == "lower"
        assert iv["lower"] < iv["bound"] < point < iv["upper"]
    assert band["mttf"]["lower"] < band["mttf"]["bound"] < res["mttf"]
    dl = band["design_life"]
    assert dl["lower"] < dl["bound"] < res["design_life"]["time"]
    for row in band["targets"]["b_lives"]:
        assert row["lower"] < row["bound"] < row["value"]
    # The reliability at a time keeps its two-sided interval (no life bound).
    assert "bound" not in (band["targets"]["reliability"] or [{}])[0]


def test_the_life_bound_is_the_draws_lower_percentile():
    from backend.services.rbd_uncertainty import _interval

    draws = np.arange(1.0, 1001.0)
    iv = _interval(draws, 0.9, life=True)
    assert iv["bound"] == np.percentile(draws, 10, method="inverted_cdf")
    assert iv["lower"] == np.percentile(draws, 5, method="inverted_cdf")
    assert "bound" not in _interval(draws, 0.9)


def test_a_one_of_n_vote_is_called_an_or():
    tree = _tree(_gate("top", "vote", ["a", "b", "c"], k=1, label="Pumping lost (2 of 3 down)"),
                 _ev("a", 0.1), _ev("b", 0.1), _ev("c", 0.1))
    r = F.analyse(tree)
    assert r["top_event_probability"] == pytest.approx(1 - 0.9 ** 3)
    assert any("1 of 3: that's an OR gate" in n for n in r["notes"])
    ok = F.analyse(_tree(_gate("top", "vote", ["a", "b", "c"], k=2), _ev("a", 0.1), _ev("b", 0.1), _ev("c", 0.1)))
    assert not any(n.startswith("Vote gate") for n in ok["notes"])


def test_a_budget_below_the_design_says_it_is_the_total():
    with pytest.raises(rd.DesignError) as err:
        rd.design_redundancy(_series((0.002, 0.004)), T, [_block("a", 3000), _block("b", 2000)],
                             budget={"cost": 1200})
    msg = str(err.value)
    assert "total cost of the design" in msg and "already costs 5,000" in msg
    assert "to spend 1,200 more, enter 6,200" in msg
    assert "120" not in msg.replace("1,200", "")  # no raw float like 1200.0


def test_a_measure_with_no_exact_route_is_flagged(monkeypatch):
    graph = _train()

    def refuse(self, *a, **k):
        raise NotImplementedError("No exact route for this diagram: simulate the system.")

    monkeypatch.setattr(type(_built(graph)), "joint_importance", refuse)
    out = rm.analyze_measure(graph, measure="joint")
    assert out["status"] == "refused" and out["needs_exact"] is True


def test_mcp_ranks_importance_at_the_time_asked(monkeypatch):
    import mongomock

    from backend import config, db
    from backend.services import models as models_service
    from backend.services import rbds as rbds_service
    from backend.services import tokens
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_mcp_eval_at"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(models_service, "get_live_model", lambda session, mid, owners: {"model": FIT})
    test_db.users.insert_one({"_id": A, "email": "a@example.org", "name": "A"})
    token = tokens.create_token(test_db, A, "mcp")["token"]
    rbd = rbds_service.save_rbd(test_db, "Pumps", {**_pumps_and_valve(), "repairable": False}, A)
    out = _ok(_call(token, "analyse", {"action": "rbd", "rbd_id": rbd.id, "evaluate_at": 150.0}))
    assert out["importance"]["time"] == 150.0 and out["importance"]["time_basis"] == "given"
    default = _ok(_call(token, "analyse", {"action": "rbd", "rbd_id": rbd.id}))
    assert default["importance"]["time_basis"] == "reliability_90"
