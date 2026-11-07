"""A workspace's currency symbol: the label in front of costs. Personal and
team, "$" unless set, owner-only for a team, nothing converted."""

import mongomock
import pytest

from backend.services import currency

UID = "user-cur"


def test_a_symbol_is_short_visible_text():
    assert currency.clean(" € ") == "€"
    assert currency.clean("AUD") == "AUD" and currency.clean("A$") == "A$"
    assert currency.clean("") is None and currency.clean(None) is None
    for bad in ("DOLLARS", "<b>", "$ ", 5, "a b", "\u0000"):
        if bad == "$ ":
            assert currency.clean(bad) == "$"
            continue
        with pytest.raises(currency.BadCurrency):
            currency.clean(bad)
    assert currency.symbol(None) == "$" and currency.symbol("<script>") == "$" and currency.symbol("£") == "£"


@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["currency_api"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    users = {u: {"uid": u, "email": f"{n}@example.org", "name": n, "email_verified": True}
             for u, n in ((UID, "cur"), ("user-mate", "mate"))}
    for u in users.values():
        test_db.users.insert_one({"_id": u["uid"], "email": u["email"], "name": u["name"], "email_verified": True})
    client = TestClient(app)
    client.act_as = lambda uid: app.dependency_overrides.__setitem__(get_current_user, lambda: users[uid])
    client.act_as(UID)
    try:
        yield client, test_db
    finally:
        app.dependency_overrides.clear()


def test_the_personal_workspace_sets_its_currency_symbol(api):
    client, db = api
    assert client.get("/api/me/currency").json() == {"currency_symbol": "$"}
    assert client.get("/api/me").json()["currency_symbol"] == "$"
    r = client.put("/api/me/currency", json={"currency_symbol": "<img>"})
    assert r.status_code == 422 and "up to 4 characters" in r.json()["detail"]
    assert client.put("/api/me/currency", json={"currency_symbol": "€"}).json() == {"currency_symbol": "€"}
    assert client.get("/api/me/currency").json() == {"currency_symbol": "€"}
    assert client.get("/api/me").json()["currency_symbol"] == "€"
    assert currency.of_owner(db, UID) == "€"
    assert client.put("/api/me/currency", json={"currency_symbol": ""}).json() == {"currency_symbol": "$"}


def test_a_team_owner_sets_the_teams_currency_symbol(api):
    client, db = api
    db.teams.insert_one({"_id": "t1", "name": "Plant", "owner_uid": UID, "invites": [],
                         "members": [{"uid": UID, "role": "owner"}, {"uid": "user-mate", "role": "member"}]})
    assert client.get("/api/teams").json()["teams"][0]["currency_symbol"] == "$"
    r = client.put("/api/teams/t1/currency", json={"currency_symbol": "£"})
    assert r.status_code == 200 and r.json()["currency_symbol"] == "£"
    assert client.put("/api/teams/t1/currency", json={"currency_symbol": "POUNDS"}).status_code == 422
    assert client.get("/api/teams").json()["teams"][0]["currency_symbol"] == "£"
    assert currency.of_owner(db, "team:t1") == "£"
    client.act_as("user-mate")
    assert client.put("/api/teams/t1/currency", json={"currency_symbol": "$"}).status_code == 403
