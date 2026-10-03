"""MCP share links (#125): share_link, list_share_links, revoke_share_link.

Through the real MCP mount (helpers and the ``env`` fixture come from
test_mcp.py); the anonymous viewer is a plain TestClient with no auth.
"""

import matplotlib

matplotlib.use("Agg")

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, B, GRAPH, _call, _err, _ok, env  # noqa: F401 - env is a fixture


def _viewer():
    from backend.main import app

    return TestClient(app)


def _rbd(env, name="Pump skid"):
    return _ok(_call(env.token[A], "create_rbd", {"name": name, "unit": "Hours", **GRAPH}))["id"]


def _token(url):
    return url.rsplit("/p/", 1)[1]


def test_share_tools_are_on_every_plan_and_counted():
    from backend.mcp_server import PRO_ONLY_TOOLS, UNGATED_TOOLS

    assert not {"share_link", "list_share_links", "revoke_share_link"} & (PRO_ONLY_TOOLS | UNGATED_TOOLS)


def test_every_public_collection_is_a_share_kind():
    """#89: share_link offers every kind the app can publish (recurrent
    models were missing), and its Literal matches the map."""
    from typing import get_args

    from backend.mcp_server import _SHARE_KINDS, _ShareKind
    from backend.services.public_links import PUBLIC_COLLECTIONS

    assert set(_SHARE_KINDS.values()) == PUBLIC_COLLECTIONS
    assert set(get_args(_ShareKind)) == set(_SHARE_KINDS)


def test_acceptance_protected_expiring_rbd_link(env):
    """Claude creates an RBD, analyses it, shares a password-protected link
    that expires in 30 days; a viewer with no account unlocks it, sees the
    diagram and results and downloads the Python; a wrong password is
    rate-limited; revoking cuts access at once."""
    from backend.services import public_links

    rid = _rbd(env)
    _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    out = _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": rid, "password": True,
                                                  "expires_in_days": 30, "label": "for the client"}))
    assert out["url"].startswith("https://reliafy.com/p/") and out["kind"] == "rbd" and out["id"] == rid
    assert out["name"] == "Pump skid" and out["label"] == "for the client" and out["protected"] is True
    expires = datetime.fromisoformat(out["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(timezone.utc) <= timedelta(days=30)
    phrase = out["passphrase"]
    assert len(phrase.split("-")) == 4 and "separately" in out["note"] and "once" in out["note"]
    token = _token(out["url"])

    viewer = _viewer()
    locked = viewer.get(f"/api/public/{token}")
    assert locked.status_code == 401 and locked.json() == {"password_required": True}
    unlock = viewer.post(f"/api/public/{token}/unlock", json={"password": phrase}).json()["unlock_token"]
    page = viewer.get(f"/api/public/{token}", headers={"X-Share-Unlock": unlock}).json()
    assert page["artifact"]["name"] == "Pump skid"
    assert page["artifact"]["graph"]["nodes"] and page["artifact"]["analysis"] is not None
    script = viewer.get(f"/api/public/{token}/export.py", headers={"X-Share-Unlock": unlock})
    assert script.status_code == 200 and "repyability" in script.text.lower()

    for _ in range(public_links.LINK_ATTEMPTS - 1):
        assert viewer.post(f"/api/public/{token}/unlock", json={"password": "guess-guess"}).status_code == 401
    assert viewer.post(f"/api/public/{token}/unlock", json={"password": phrase}).status_code == 429

    revoked = _ok(_call(env.token[A], "revoke_share_link", {"token": token}))
    assert revoked == {"revoked": True, "token": token, "id": rid, "kind": "rbd"}
    assert viewer.get(f"/api/public/{token}", headers={"X-Share-Unlock": unlock}).status_code == 404


def test_passphrase_is_returned_once(env):
    rid = _rbd(env)
    out = _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": rid, "password": True}))
    listed = _ok(_call(env.token[A], "list_share_links", {}))
    assert out["passphrase"] not in str(listed) and "passphrase" not in str(listed)
    assert out["passphrase"] not in str(env.db.public_links.find_one({"_id": out["token"]}))


def test_open_link_needs_no_password(env):
    rid = _rbd(env)
    out = _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": rid}))
    assert out["protected"] is False and out["expires_at"] is None and "passphrase" not in out
    assert _viewer().get(f"/api/public/{out['token']}").status_code == 200


def test_list_and_revoke_one_of_several_links(env):
    rid = _rbd(env)
    other = _rbd(env, "Other skid")
    client_link = _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": rid, "label": "client"}))
    auditor = _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": rid, "label": "auditor",
                                                     "password": True}))
    _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": other}))

    mine = _ok(_call(env.token[A], "list_share_links", {}))
    assert mine["count"] == 3
    for_rbd = _ok(_call(env.token[A], "list_share_links", {"kind": "rbd", "id": rid}))
    assert [x["label"] for x in for_rbd["links"]] == ["auditor", "client"]
    assert [x["protected"] for x in for_rbd["links"]] == [True, False]
    assert {x["name"] for x in for_rbd["links"]} == {"Pump skid"}
    assert _ok(_call(env.token[A], "list_share_links", {"kind": "model"}))["count"] == 0

    # Revoke by full URL; the other link to the same RBD keeps working.
    _ok(_call(env.token[A], "revoke_share_link", {"token": client_link["url"]}))
    assert _viewer().get(f"/api/public/{client_link['token']}").status_code == 404
    assert _viewer().get(f"/api/public/{auditor['token']}").status_code == 401  # alive, still locked
    assert _ok(_call(env.token[A], "list_share_links", {"kind": "rbd", "id": rid}))["count"] == 1


def test_owner_only(env):
    rid = _rbd(env)
    link = _ok(_call(env.token[A], "share_link", {"kind": "rbd", "id": rid}))
    assert "No rbd with that id" in _err(_call(env.token[B], "share_link", {"kind": "rbd", "id": rid}))
    assert _ok(_call(env.token[B], "list_share_links", {}))["count"] == 0
    assert "not found" in _err(_call(env.token[B], "revoke_share_link", {"token": link["token"]}))
    assert _viewer().get(f"/api/public/{link['token']}").status_code == 200


def test_samples_are_never_shared(env):
    from backend import config
    from backend.services import rbd_graph, rbds as rbds_service

    sample = rbds_service.save_rbd(env.db, "Sample skid", rbd_graph.normalize_graph({**GRAPH, "unit": "Hours"}),
                                   config.SAMPLE_OWNER).id
    msg = _err(_call(env.token[A], "share_link", {"kind": "rbd", "id": sample, "password": True}))
    assert "shared sample" in msg and "clone_rbd" in msg
    assert env.db.public_links.count_documents({}) == 0


def test_kind_and_expiry_are_validated(env):
    rid = _rbd(env)
    assert _call(env.token[A], "share_link", {"kind": "recurrent_model", "id": rid}).is_error
    assert _call(env.token[A], "share_link", {"kind": "rbd", "id": rid, "expires_in_days": 0}).is_error
    assert _call(env.token[A], "share_link", {"kind": "rbd", "id": rid, "expires_in_days": 400}).is_error
    # The right kind matters: an RBD id isn't a model.
    assert "No model with that id" in _err(_call(env.token[A], "share_link", {"kind": "model", "id": rid}))


def test_a_fitted_model_can_be_shared(env):
    saved = _ok(_call(env.token[A], "save_model", {
        "name": "Bearings", "distribution": "weibull", "unit": "hours",
        "params": [{"name": "alpha", "value": 1200}, {"name": "beta", "value": 2.5}]}))
    out = _ok(_call(env.token[A], "share_link", {"kind": "model", "id": saved["model_id"], "expires_in_days": 7}))
    page = _viewer().get(f"/api/public/{out['token']}")
    assert page.status_code == 200 and page.json()["artifact"]["name"] == "Bearings"
