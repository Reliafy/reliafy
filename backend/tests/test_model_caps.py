"""Every saved model kind (non-repairable, repairable and accelerated-life)
counts toward the one Free "saved models" limit, in the web app and over
MCP/REST; shared samples never count; Pro and operators are exempt."""

from __future__ import annotations

import mongomock
import pytest

from backend.tests.test_alt_bounds_interval import _alt_df
from backend.tests.test_mcp import _call, _err, _ok
from backend.tests.test_mcp_plans import AGENT, FREE, PRO, UPGRADE, env  # noqa: F401
from backend.tests.test_mcp_recurrent_fit import _compressors

pytestmark = pytest.mark.usefixtures("mcp_on")

MSG = "You've reached the free-plan limit of 3 saved models. Upgrade to Pro for unlimited models."


def _fill(db, uid, **counts):
    for coll, n in counts.items():
        db[coll].insert_many([{"_id": f"{uid}-{coll}-{i}", "owner_id": uid} for i in range(n)])


@pytest.fixture()
def web(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import samples

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    test_db = mongomock.MongoClient()["model_caps"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    samples.seed_samples(test_db)  # samples of each kind, which must not count
    test_db.users.insert_many([
        {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
        {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro", "email_verified": True},
    ])
    who = {"uid": FREE}
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": who["uid"], "email": f"{who['uid']}@example.org", "name": "U", "email_verified": True}
    tc = TestClient(app)
    tc.who = who
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _recurrent(web, name="R"):
    return web.post("/api/recurrent/from-params", data={"name": name, "alpha": 100, "beta": 1.2, "horizon": 1000})


def _alt(web, name="A"):
    csv = _alt_df().to_csv(index=False).encode()
    return web.post("/api/alt/models", data={"name": name, "x": "hours", "c": "cens", "s1": "tempK", "unit": "hours"},
                    files={"file": ("alt.csv", csv, "text/csv")})


def test_samples_never_count(web):
    from backend.services import billing

    assert web.db.recurrent_models.count_documents({}) >= 1 and web.db.alt_models.count_documents({}) >= 1
    assert billing.owned_count(web.db, FREE, "models") == 0
    assert web.get("/api/billing").json()["usage"]["models"] == 0


@pytest.mark.parametrize("save", [_recurrent, _alt], ids=["recurrent", "alt"])
def test_web_save_refuses_at_the_cap_with_the_same_402(web, save):
    _fill(web.db, FREE, models=3)
    over = save(web)
    assert over.status_code == 402, over.text
    assert over.json() == {"detail": MSG, "code": "cap", "upgrade": True}
    assert web.db.recurrent_models.count_documents({"owner_id": FREE}) == 0
    assert web.db.alt_models.count_documents({"owner_id": FREE}) == 0
    # Pro has no cap.
    web.who["uid"] = PRO
    _fill(web.db, PRO, models=3)
    assert save(web, "P").status_code == 200


def test_the_count_is_all_three_kinds_together(web):
    _fill(web.db, FREE, models=1, alt_models=1)
    assert _recurrent(web).status_code == 200            # the third
    assert web.get("/api/billing").json()["usage"]["models"] == 3
    for save in (_recurrent, _alt):
        r = save(web)
        assert r.status_code == 402 and r.json()["code"] == "cap"
    # A non-repairable save is refused too, and editing what you have is not.
    assert web.post("/api/models/from-params", json={"name": "N", "distribution": "weibull"}).status_code == 402
    mine = web.db.recurrent_models.find_one({"owner_id": FREE})["_id"]
    assert web.patch(f"/api/recurrent/models/{mine}", json={"name": "Renamed"}).status_code == 200
    # Deleting one makes room.
    assert web.delete(f"/api/recurrent/models/{mine}").status_code == 200
    assert _alt(web).status_code == 200


def test_operators_are_exempt(web, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "ADMIN_EMAILS", {"free-user@example.org"})
    _fill(web.db, FREE, models=3)
    assert _recurrent(web).status_code == 200 and _alt(web).status_code == 200


def test_mcp_and_rest_saves_count_for_a_capped_plan(env, monkeypatch):  # noqa: F811
    """Fitting over MCP is Pro-only today, so the Pro gate is lifted here to
    reach the save's own check (a capped plan, Agent, with its own cap); Pro
    stays unlimited. Both saves go through the same check."""
    from backend import config, mcp_server

    monkeypatch.setattr(mcp_server, "PRO_ONLY_TOOLS", frozenset())
    monkeypatch.setattr(config, "AGENT_MAX_MODELS", 2)
    df = _compressors()
    rec = {"action": "model_fit_recurrent", "name": "Compressors", "model": "crow_amsaa", "times": df.hours.tolist(),
           "systems": df.compressor.tolist(), "observed_to": 5000, "unit": "hours"}
    alt_df = _alt_df()
    alt = {"action": "model_fit_alt", "name": "Seal", "life_model": "arrhenius", "data": alt_df["hours"].tolist(),
           "censored": alt_df["cens"].tolist(), "stresses": [[t] for t in alt_df["tempK"]],
           "stress_names": ["Temperature (K)"], "unit": "hours"}
    token = env.oauth[AGENT]
    _fill(env.db, AGENT, models=1)
    assert _ok(_call(token, "change", rec))["saved"]
    for args in (alt, rec):
        msg = _err(_call(token, "change", args))
        assert "Agent plan's limit of 2 saved models" in msg and UPGRADE in msg
    assert env.db.alt_models.count_documents({"owner_id": AGENT}) == 0
    assert env.db.recurrent_models.count_documents({"owner_id": AGENT}) == 1
    assert _ok(_call(token, "get", {"kind": "account"}))["storage"]["models"] == {"used": 2, "limit": 2}

    pro = env.oauth[PRO]
    assert _ok(_call(pro, "change", alt))["saved"] and _ok(_call(pro, "change", rec))["saved"]
