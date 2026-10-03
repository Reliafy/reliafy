"""Share links v2 (#125): passwords, unlock tokens, rate limits, expiry,
several labelled links per artifact, and links made before any of that."""

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.test_public_links import A, B, _save_model, client  # noqa: F401 - fixture
from backend.tests.test_public_rbd_links import _save_rbd


def _link(client, collection, artifact_id, **options):
    r = client.post("/api/public-links", json={"collection": collection, "artifact_id": artifact_id, **options})
    assert r.status_code == 200, r.text
    return r.json()


def _protected_rbd(client, name="Cooling loop"):
    client.act_as(A)
    rbd_id = _save_rbd(client, name=name)
    link = _link(client, "rbds", rbd_id, generate_password=True, label="for the client")
    client.act_as(None)
    return rbd_id, link


def _unlock(client, token, password):
    return client.post(f"/api/public/{token}/unlock", json={"password": password})


def _later(monkeypatch, **delta):
    from backend.services import public_links

    future = datetime.now(timezone.utc) + timedelta(**delta)
    monkeypatch.setattr(public_links, "_now", lambda: future)


# ---- a protected link reveals nothing before unlock ------------------------------

def test_protected_link_reveals_nothing_before_unlock(client):
    _, link = _protected_rbd(client)
    token, phrase = link["token"], link["passphrase"]
    assert link["protected"] is True and link["label"] == "for the client"
    assert len(phrase.split("-")) == 4

    r = client.get(f"/api/public/{token}")
    assert r.status_code == 401
    assert r.json() == {"password_required": True}
    assert "Cooling" not in r.text and "Alice" not in r.text and "rbds" not in r.text
    assert client.get(f"/api/public/{token}/export.py").json() == {"password_required": True}

    # A made-up or stale unlock token is the same 401.
    for bad in ("nonsense", "1.9999999999.abc", ""):
        assert client.get(f"/api/public/{token}", headers={"X-Share-Unlock": bad}).status_code == 401


def test_passphrase_is_returned_once_and_only_its_hash_is_stored(client):
    _, link = _protected_rbd(client)
    phrase = link["passphrase"]
    client.act_as(A)
    listed = client.get("/api/public-links", params={"collection": "rbds", "artifact_id": link["artifact_id"]})
    assert phrase not in listed.text and "passphrase" not in listed.text
    assert "password_hash" not in listed.text and "unlock_key" not in listed.text
    stored = client.db.public_links.find_one({"_id": link["token"]})
    assert phrase not in str(stored)
    assert stored["password_hash"] and stored["password_salt"] and stored["password_version"] == 1


def test_typed_password_is_not_echoed_and_must_be_long_enough(client):
    client.act_as(A)
    model_id = _save_model(client)
    link = _link(client, "models", model_id, password="correct horse")
    assert link["protected"] is True and "passphrase" not in link
    short = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id,
                                                   "password": "short"})
    assert short.status_code == 400
    client.act_as(None)
    assert _unlock(client, link["token"], "correct horse").status_code == 200


# ---- unlocking: view and export ------------------------------------------------------

def test_unlock_opens_the_view_and_the_python_download(client):
    _, link = _protected_rbd(client)
    token = link["token"]

    assert _unlock(client, token, "wrong-password").status_code == 401
    r = _unlock(client, token, link["passphrase"])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    unlock = r.json()["unlock_token"]
    assert r.json()["expires_at"]

    # Header (the app) or query (a plain link) both work, for view and export.
    view = client.get(f"/api/public/{token}", headers={"X-Share-Unlock": unlock})
    assert view.status_code == 200
    assert view.json()["artifact"]["name"] == "Cooling loop" and view.json()["protected"] is True
    assert view.json()["artifact"]["analysis"] is not None
    assert client.get(f"/api/public/{token}", params={"unlock": unlock}).status_code == 200

    for kwargs in ({"headers": {"X-Share-Unlock": unlock}}, {"params": {"unlock": unlock}}):
        script = client.get(f"/api/public/{token}/export.py", **kwargs)
        assert script.status_code == 200 and "attachment" in script.headers["content-disposition"]


def test_unlock_token_is_bound_to_its_link_and_expires(client, monkeypatch):
    _, first = _protected_rbd(client, "First")
    _, second = _protected_rbd(client, "Second")
    unlock = _unlock(client, first["token"], first["passphrase"]).json()["unlock_token"]
    assert client.get(f"/api/public/{second['token']}", headers={"X-Share-Unlock": unlock}).status_code == 401

    # Tampering with the expiry breaks the signature.
    version, exp, sig = unlock.split(".")
    forged = f"{version}.{int(exp) + 86400}.{sig}"
    assert client.get(f"/api/public/{first['token']}", headers={"X-Share-Unlock": forged}).status_code == 401

    _later(monkeypatch, hours=13)
    assert client.get(f"/api/public/{first['token']}", headers={"X-Share-Unlock": unlock}).status_code == 401


def test_unlock_on_an_open_or_missing_link(client):
    client.act_as(A)
    model_id = _save_model(client)
    open_link = _link(client, "models", model_id)
    client.act_as(None)
    assert _unlock(client, open_link["token"], "anything-at-all").status_code == 400
    assert _unlock(client, "not-a-real-token", "anything-at-all").status_code == 404


# ---- rate limits ----------------------------------------------------------------------

def test_wrong_passwords_are_rate_limited_per_link(client):
    from backend.services import public_links

    _, link = _protected_rbd(client)
    token = link["token"]
    for _ in range(public_links.LINK_ATTEMPTS):
        assert _unlock(client, token, "not-the-password").status_code == 401
    # Locked: even the right password waits for the window to pass.
    r = _unlock(client, token, link["passphrase"])
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert "Too many attempts" in r.json()["detail"]

    # Another link (same viewer) has its own budget.
    _, other = _protected_rbd(client, "Other")
    assert _unlock(client, other["token"], other["passphrase"]).status_code == 200


def test_unlock_attempts_are_rate_limited_per_ip(client, monkeypatch):
    from backend.services import public_links

    monkeypatch.setattr(public_links, "IP_ATTEMPTS", 3)
    links = [_protected_rbd(client, f"RBD {i}")[1] for i in range(3)]
    for link in links:
        assert _unlock(client, link["token"], "not-the-password").status_code == 401
    # The fourth attempt from this IP is refused, whichever link it targets.
    _, fresh = _protected_rbd(client, "Fresh")
    assert _unlock(client, fresh["token"], fresh["passphrase"]).status_code == 429
    # A different client IP isn't affected.
    r = client.post(f"/api/public/{fresh['token']}/unlock", json={"password": fresh["passphrase"]},
                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200
    # Only a salted hash of the IP is stored.
    assert "203.0.113.9" not in str(list(client.db.public_link_attempts.find()))


# ---- changing or removing the password cuts access ---------------------------------------

def test_rotating_the_password_ends_earlier_unlocks(client):
    _, link = _protected_rbd(client)
    token = link["token"]
    old_unlock = _unlock(client, token, link["passphrase"]).json()["unlock_token"]

    client.act_as(A)
    rotated = client.patch(f"/api/public-links/{token}", json={"generate_password": True}).json()
    assert rotated["passphrase"] != link["passphrase"] and rotated["protected"] is True
    client.act_as(None)

    assert client.get(f"/api/public/{token}", headers={"X-Share-Unlock": old_unlock}).status_code == 401
    assert client.get(f"/api/public/{token}/export.py", params={"unlock": old_unlock}).status_code == 401
    assert _unlock(client, token, link["passphrase"]).status_code == 401
    new_unlock = _unlock(client, token, rotated["passphrase"]).json()["unlock_token"]
    assert client.get(f"/api/public/{token}", headers={"X-Share-Unlock": new_unlock}).status_code == 200


def test_removing_then_re_adding_a_password(client):
    _, link = _protected_rbd(client)
    token = link["token"]
    old_unlock = _unlock(client, token, link["passphrase"]).json()["unlock_token"]

    client.act_as(A)
    opened = client.patch(f"/api/public-links/{token}", json={"remove_password": True}).json()
    assert opened["protected"] is False
    client.act_as(None)
    assert client.get(f"/api/public/{token}").status_code == 200

    # Same password again: the version moved on, so the old unlock stays dead.
    client.act_as(A)
    client.patch(f"/api/public-links/{token}", json={"password": link["passphrase"]})
    client.act_as(None)
    assert client.get(f"/api/public/{token}", headers={"X-Share-Unlock": old_unlock}).status_code == 401
    assert _unlock(client, token, link["passphrase"]).status_code == 200


def test_only_the_owner_can_change_a_link(client):
    _, link = _protected_rbd(client)
    client.act_as(B)
    r = client.patch(f"/api/public-links/{link['token']}", json={"remove_password": True})
    assert r.status_code == 404
    client.act_as(A)
    r = client.patch(f"/api/public-links/{link['token']}", json={"label": "for the auditor"})
    assert r.json()["label"] == "for the auditor" and r.json()["protected"] is True


# ---- expiry ----------------------------------------------------------------------------------

def test_expired_link_behaves_like_a_revoked_one(client, monkeypatch):
    client.act_as(A)
    rbd_id = _save_rbd(client)
    link = _link(client, "rbds", rbd_id, expires_in_days=30)
    expires = datetime.fromisoformat(link["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(timezone.utc) <= timedelta(days=30)
    client.act_as(None)
    assert client.get(f"/api/public/{link['token']}").status_code == 200

    _later(monkeypatch, days=31)
    r = client.get(f"/api/public/{link['token']}")
    assert r.status_code == 404 and "expired" in r.json()["detail"]
    assert client.get(f"/api/public/{link['token']}/export.py").status_code == 404
    assert _unlock(client, link["token"], "whatever-it-was").status_code == 404
    client.act_as(A)
    assert client.get("/api/public-links", params={"collection": "rbds", "artifact_id": rbd_id}).json() == {
        "links": [], "link": None}


@pytest.mark.parametrize("days", [0.5, -1, 366, "soon"])
def test_expiry_must_be_whole_days_within_a_year(client, days):
    client.act_as(A)
    model_id = _save_model(client)
    r = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id,
                                               "expires_in_days": days})
    assert r.status_code in (400, 422)


# ---- several links per artifact, revocable one by one --------------------------------------------

def test_several_labelled_links_each_revocable(client):
    client.act_as(A)
    rbd_id = _save_rbd(client)
    client_link = _link(client, "rbds", rbd_id, label="for the client", generate_password=True)
    auditor = _link(client, "rbds", rbd_id, label="for the auditor", expires_in_days=7)

    listed = client.get("/api/public-links", params={"collection": "rbds", "artifact_id": rbd_id}).json()
    assert [x["label"] for x in listed["links"]] == ["for the auditor", "for the client"]
    assert [x["protected"] for x in listed["links"]] == [False, True]
    assert listed["link"]["token"] == auditor["token"]  # newest, for single-link clients
    # Without a filter: every link the caller owns.
    assert len(client.get("/api/public-links").json()["links"]) == 2

    assert client.delete(f"/api/public-links/{client_link['token']}").status_code == 200
    client.act_as(None)
    assert client.get(f"/api/public/{client_link['token']}").status_code == 404
    assert client.get(f"/api/public/{auditor['token']}").status_code == 200


def test_links_per_artifact_are_capped(client, monkeypatch):
    from backend.services import public_links

    monkeypatch.setattr(public_links, "MAX_LINKS_PER_ARTIFACT", 2)
    client.act_as(A)
    model_id = _save_model(client)
    _link(client, "models", model_id)
    _link(client, "models", model_id)
    r = client.post("/api/public-links", json={"collection": "models", "artifact_id": model_id})
    assert r.status_code == 400 and "at most 2" in r.json()["detail"]


# ---- links made before v2 keep working ---------------------------------------------------------

def test_a_pre_v2_link_still_opens_and_lists(client):
    client.act_as(A)
    model_id = _save_model(client)
    # Exactly what the old create_link stored: no label, expiry or password fields.
    client.db.public_links.insert_one({
        "_id": "legacy-token-abcdefghijklmnop", "collection": "models", "artifact_id": model_id,
        "grantor_uid": A, "created_at": datetime.now(timezone.utc),
    })
    listed = client.get("/api/public-links", params={"collection": "models", "artifact_id": model_id}).json()
    assert listed["link"] == {**listed["links"][0], "label": None, "expires_at": None, "protected": False}
    client.act_as(None)
    r = client.get("/api/public/legacy-token-abcdefghijklmnop")
    assert r.status_code == 200 and r.json()["artifact"]["name"] == "Pump bearings"

    # The owner can still protect it later.
    client.act_as(A)
    r = client.patch("/api/public-links/legacy-token-abcdefghijklmnop", json={"generate_password": True})
    assert r.json()["protected"] is True and r.json()["passphrase"]
    client.act_as(None)
    assert client.get("/api/public/legacy-token-abcdefghijklmnop").status_code == 401
