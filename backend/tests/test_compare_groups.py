"""Compare groups of life data (#175): log-rank, RMST difference, Gray's test.

The service against SurPyval directly, the dataset endpoint (and who may call
it), and the ``compare_groups`` MCP tool.
"""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend.services import compare_groups as cg
from backend.services.compare_groups import CompareGroupsError

# The AML maintenance data (R's survival::aml): survdiff gives chi2 = 3.4 on 1 dof.
AML_X = [9, 13, 13, 18, 23, 28, 31, 34, 45, 48, 161, 5, 5, 8, 8, 12, 16, 23, 27, 30, 33, 43, 45]
AML_C = [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
AML_G = ["Maintained"] * 11 + ["Nonmaintained"] * 12


def _aml(**extra) -> pd.DataFrame:
    return pd.DataFrame({"weeks": AML_X, "censored": AML_C, "arm": AML_G, **extra})


def _run(df, **kw):
    prep_keys = ("time_column", "group_column", "censor_column", "count_column", "cause_column", "c_invert")
    prep = {k: kw.pop(k) for k in list(kw) if k in prep_keys}
    data = cg.prepare(df, **prep)
    return cg.compare_groups(data, group_column=prep.get("group_column"), **kw)


# ---- the statistics match SurPyval --------------------------------------------------------

def test_two_groups_match_surpyval_logrank_and_rmst():
    res = _run(_aml(), time_column="weeks", group_column="arm", censor_column="censored", unit="weeks")
    ref = sp.logrank(AML_X, AML_G, c=AML_C)
    assert res["logrank"]["statistic"] == pytest.approx(ref.statistic) == pytest.approx(3.396, abs=1e-3)
    assert res["logrank"]["dof"] == 1 and res["logrank"]["p_value"] == pytest.approx(ref.p_value)
    assert [t["id"] for t in res["tests"]] == ["log-rank", "gehan", "tarone-ware"]
    assert res["tests"][1]["statistic"] == pytest.approx(2.723, abs=1e-3)

    x, c, g = np.array(AML_X), np.array(AML_C), np.array(AML_G)
    km = {k: sp.KaplanMeier.fit(x[g == k], c=c[g == k]) for k in ("Maintained", "Nonmaintained")}
    # Default horizon: the shorter group's longest time.
    assert res["tau"] == 45.0
    d = sp.rmst_diff(km["Nonmaintained"], km["Maintained"], tau=45.0)
    (diff,) = res["rmst_differences"]
    assert diff["reference"] == "Maintained" and diff["group"] == "Nonmaintained"
    for key in ("difference", "lower", "upper", "p_value"):
        assert diff[key] == pytest.approx(d[key])
    groups = {s["group"]: s for s in res["groups"]}
    assert groups["Maintained"]["rmst"] == pytest.approx(km["Maintained"].rmst(tau=45.0)["rmst"])
    assert groups["Maintained"]["units"] == 11 and groups["Maintained"]["failures"] == 7
    assert groups["Nonmaintained"]["censored"] == 1
    # Each curve is the KM step function from (0, 1).
    curve = groups["Maintained"]["curve"]
    assert curve["x"][0] == 0 and curve["R"][0] == 1
    assert curve["R"][1:] == pytest.approx(list(km["Maintained"].R))


def test_verdict_reads_in_plain_words():
    res = _run(_aml(), time_column="weeks", group_column="arm", censor_column="censored", unit="weeks")
    v = res["verdict"]
    assert v["significant"] is False and v["better"] is None  # p = 0.065
    assert v["text"].startswith("No clear difference between Maintained and Nonmaintained: log-rank p = 0.07.")
    assert "Maintained averages" in v["text"] and "weeks more (95% CI" in v["text"]

    # A clear difference names the longer-lived group, the gain and the window.
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"hours": np.r_[rng.weibull(2, 40) * 1000, rng.weibull(2, 40) * 2000],
                       "supplier": ["A"] * 40 + ["B"] * 40})
    res = _run(df, time_column="hours", group_column="supplier", unit="h")
    v = res["verdict"]
    assert v["significant"] and v["better"] == "B" and v["worse"] == "A"
    assert v["text"].startswith("supplier B lasts longer: log-rank p < 0.001; on average ")
    assert "h more over the first " in v["text"]


def test_more_than_two_groups_and_numeric_labels():
    from backend.services import samples

    df = pd.read_csv(io.BytesIO(samples._INSULATING_FLUID_CSV))
    res = _run(df, time_column="minutes", group_column="kV", unit="minutes")
    assert [g["group"] for g in res["groups"]] == ["30", "32", "34", "36"]  # 30.0 reads "30"
    assert res["logrank"]["dof"] == 3 and res["logrank"]["p_value"] < 0.001
    assert [d["group"] for d in res["rmst_differences"]] == ["32", "34", "36"]
    assert res["verdict"]["better"] == "30" and res["verdict"]["worse"] == "36"
    assert "kV 30 lasts longest" in res["verdict"]["text"]

    # Pick, order and reference.
    res = _run(df, time_column="minutes", group_column="kV", groups=[36, 30], reference="30", tau=20)
    assert [g["group"] for g in res["groups"]] == ["36", "30"] and res["reference"] == "30"
    assert res["tau"] == 20 and res["rmst_differences"][0]["group"] == "36"


def test_counts_and_inverted_flags():
    base = _run(_aml(), time_column="weeks", group_column="arm", censor_column="censored")
    flipped = _aml(failed=[1 - c for c in AML_C])
    inv = _run(flipped, time_column="weeks", group_column="arm", censor_column="failed", c_invert=True)
    assert inv["logrank"]["statistic"] == pytest.approx(base["logrank"]["statistic"])

    df = pd.DataFrame({"t": [10, 20, 30, 15, 25], "n": [2, 1, 1, 3, 1], "g": ["a", "a", "a", "b", "b"]})
    res = _run(df, time_column="t", group_column="g", count_column="n")
    ref = sp.logrank([10, 20, 30, 15, 25], ["a", "a", "a", "b", "b"], n=[2, 1, 1, 3, 1])
    assert res["logrank"]["statistic"] == pytest.approx(ref.statistic)
    assert {g["group"]: g["units"] for g in res["groups"]} == {"a": 4, "b": 4}


def test_gray_test_per_failure_mode():
    rng = np.random.default_rng(0)
    group = rng.binomial(1, 0.5, 200)
    t_a = rng.exponential(1 / (0.1 * np.exp(0.7 * group)))
    t_b = rng.exponential(1 / 0.05, 200)
    t_c = rng.uniform(0, 20, 200)
    x = np.minimum(np.minimum(t_a, t_b), t_c).round(3)
    censored = (t_c < np.minimum(t_a, t_b)).astype(int)
    mode = np.where(t_a < t_b, "seal", "bearing")
    # A running unit's mode cell is ignored (often blank, sometimes filled in).
    df = pd.DataFrame({"t": x, "c": censored, "site": np.where(group == 1, "North", "South"), "mode": mode})
    res = _run(df, time_column="t", group_column="site", censor_column="c", cause_column="mode")
    cr = res["competing_risks"]
    assert cr["available"]
    by_mode = {r["mode"]: r for r in cr["results"]}
    e = np.where(censored == 1, None, mode)
    ref = sp.gray_test(x, e, np.where(group == 1, "North", "South"), event="seal")
    assert by_mode["seal"]["statistic"] == pytest.approx(ref.statistic)
    assert by_mode["seal"]["significant"] and by_mode["seal"]["dof"] == 1

    one_mode = _run(df.assign(mode="seal"), time_column="t", group_column="site", censor_column="c",
                    cause_column="mode")
    assert one_mode["competing_risks"]["available"] is False
    assert "competing" in one_mode["competing_risks"]["reason"]


# ---- refusals, in words ---------------------------------------------------------------------

@pytest.mark.parametrize("df, kw, expect", [
    (_aml(), {"group_column": "nope"}, "Column 'nope'"),
    (_aml(), {"group_column": "weeks"}, "other than the time column"),
    (_aml(arm="X"), {}, "only one group"),
    (pd.DataFrame({"weeks": range(30), "arm": range(30)}), {}, "at most 12"),
    (_aml(censored=[-1] + AML_C[1:]), {"censor_column": "censored"}, "right-censored data only"),
])
def test_bad_inputs_are_refused_in_words(df, kw, expect):
    with pytest.raises(CompareGroupsError, match=expect):
        _run(df, **{"time_column": "weeks", "group_column": "arm", **kw})


def test_unknown_group_tau_past_the_data_and_dropped_rows():
    with pytest.raises(CompareGroupsError, match="No rows in group"):
        _run(_aml(), time_column="weeks", group_column="arm", groups=["Maintained", "Other"])
    res = _run(_aml(), time_column="weeks", group_column="arm", censor_column="censored", tau=100)
    assert any("extrapolated" in n for n in res["notes"])
    df = _aml()
    df.loc[0, "arm"] = None
    df.loc[1, "weeks"] = None
    res = _run(df, time_column="weeks", group_column="arm", censor_column="censored")
    assert res["rows_dropped"] == 2 and res["rows_used"] == 21
    assert any("2 rows" in n for n in res["notes"])


def test_lean_drops_curves():
    res = _run(_aml(), time_column="weeks", group_column="arm")
    assert "curve" not in cg.lean(res)["groups"][0] and "curve" in cg.lean(res, True)["groups"][0]


# ---- the dataset endpoint -------------------------------------------------------------------

USERS = {
    "user-a": {"uid": "user-a", "email": "a@x.com", "name": "A", "email_verified": True},
    "user-b": {"uid": "user-b", "email": "b@x.com", "name": "B", "email_verified": True},
}


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)  # free to every plan
    test_db = mongomock.MongoClient()["reliafy_compare_groups_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    tc = TestClient(app)
    tc.act_as = lambda uid: app.dependency_overrides.__setitem__(get_current_user, lambda: USERS[uid])
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_endpoint_compares_a_saved_dataset_for_its_readers_only(client):
    client.act_as("user-a")
    csv = _aml().to_csv(index=False)
    ds = client.post("/api/datasets/paste", json={"name": "AML", "content": csv}).json()
    url = f"/api/datasets/{ds['id']}/compare-groups"
    body = {"time_column": "weeks", "group_column": "arm", "censor_column": "censored", "unit": "weeks"}
    r = client.post(url, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["logrank"]["statistic"] == pytest.approx(3.396, abs=1e-3)
    assert out["verdict"]["text"].startswith("No clear difference")

    bad = client.post(url, json={**body, "group_column": "nope"})
    assert bad.status_code == 422 and "Column 'nope'" in bad.json()["detail"]

    client.act_as("user-b")
    assert client.post(url, json=body).status_code == 404


# ---- the MCP tool ---------------------------------------------------------------------------

@pytest.fixture()
def mcp_env(monkeypatch):
    from backend import config, db
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["reliafy_mcp_compare_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    for uid in ("user-a", "user-b"):
        test_db.users.insert_one({"_id": uid, "email": f"{uid}@example.org", "name": uid})

    class Env:
        db = test_db
        token = {uid: tokens.create_token(test_db, uid, "mcp")["token"] for uid in ("user-a", "user-b")}

    return Env


def test_mcp_compare_groups_inline_and_from_a_dataset(mcp_env):
    from backend.tests.test_mcp import _call, _err, _ok

    tok = mcp_env.token["user-a"]
    out = _ok(_call(tok, "compare_groups", {"data": AML_X, "group": AML_G, "censored": AML_C, "unit": "weeks"}))
    assert out["verdict"].startswith("No clear difference") and out["significant"] is False
    assert out["logrank"]["statistic"] == pytest.approx(3.396, abs=1e-3)
    assert "curve" not in out["groups"][0] and "curves_omitted" in out and "url" not in out

    flipped = [1 - c for c in AML_C]
    inv = _ok(_call(tok, "compare_groups", {"data": AML_X, "group": AML_G, "censored": flipped, "c_invert": True}))
    assert inv["logrank"]["statistic"] == pytest.approx(out["logrank"]["statistic"])

    ds = _ok(_call(tok, "upload_dataset", {"name": "AML", "csv": _aml().to_csv(index=False)}))
    msg = _err(_call(tok, "compare_groups", {"dataset_id": ds["id"], "time_column": "weeks"}))
    assert "group_column" in msg and "arm" in msg
    out = _ok(_call(tok, "compare_groups", {"dataset_id": ds["id"], "time_column": "weeks", "group_column": "arm",
                                            "censor_column": "censored", "include_curves": True}))
    assert out["url"].endswith(f"/datasets/d/{ds['id']}?compare=arm")
    assert out["groups"][0]["curve"]["x"][0] == 0

    assert "with dataset_id" in _err(_call(tok, "compare_groups", {"data": AML_X, "group": AML_G,
                                                                   "time_column": "weeks"}))
    assert "Give `group`" in _err(_call(tok, "compare_groups", {"data": AML_X}))
    assert "one group" in _err(_call(tok, "compare_groups", {"data": AML_X, "group": ["A"] * len(AML_X)}))
    # Another user's dataset isn't there.
    assert "Dataset not found" in _err(_call(mcp_env.token["user-b"], "compare_groups", {
        "dataset_id": ds["id"], "time_column": "weeks", "group_column": "arm"}))


def test_compare_groups_is_not_pro_only():
    from backend import mcp_server

    assert "compare_groups" not in mcp_server.PRO_ONLY_TOOLS
