"""OAuth for the MCP server: discovery, registration (DCR + CIMD), consent,
PKCE code exchange, refresh rotation, revocation, and the resource side at
/mcp (including the free-plan behaviour: connect and list, but MCP is Pro).

Everything runs in-process against mongomock; the one outbound HTTP call the
server makes (fetching a Client ID Metadata Document) is monkeypatched, so
nothing here touches the network.
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx2
import mongomock
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE = "https://reliafy.com"
RESOURCE = f"{BASE}/mcp"
CLAUDE_CODE = "https://claude.ai/oauth/claude-code-client-metadata"
CLAUDE_CODE_DOC = {
    "client_id": CLAUDE_CODE, "client_name": "Claude Code", "client_uri": "https://claude.ai",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}
HOSTED = "https://claude.ai/api/mcp/auth_callback"

from backend.services import oauth as _oauth  # noqa: E402

REAL_FETCH = _oauth._http_fetch  # captured before the fixture swaps in a fake

U = "oauth-user"
OTHER = "other-user"


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import ingest as ingest_router
    from backend.services import oauth as oauth_service

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", BASE)
    test_db = mongomock.MongoClient()["reliafy_oauth_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    oauth_service._cimd_cache.clear()
    test_db.users.insert_one({"_id": U, "email": "u@example.org", "name": "U"})
    test_db.users.insert_one({"_id": OTHER, "email": "o@example.org", "name": "O"})

    fetches = []

    def fake_fetch(url):
        fetches.append(url)
        doc = Env.cimd_docs.get(url)
        if doc is None:
            return 404, {}, b"not found"
        return 200, {"cache-control": "max-age=600"}, json.dumps(doc).encode()

    monkeypatch.setattr(oauth_service, "_http_fetch", fake_fetch)

    class Env:
        db = test_db
        client = TestClient(app, follow_redirects=False)
        cimd_docs = {CLAUDE_CODE: CLAUDE_CODE_DOC}
        fetched = fetches
        signed_in = {"uid": U}

    app.dependency_overrides[get_current_user] = lambda: {
        "uid": Env.signed_in["uid"], "email": f"{Env.signed_in['uid']}@example.org", "name": "Test"}
    try:
        yield Env
    finally:
        app.dependency_overrides.clear()


# ---- helpers ------------------------------------------------------------------------

def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _authorize(env, client_id, redirect_uri, challenge, **extra):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
              "code_challenge": challenge, "code_challenge_method": "S256", "state": "st-123",
              "scope": "mcp offline_access", "resource": RESOURCE, **extra}
    return env.client.get("/oauth/authorize", params={k: v for k, v in params.items() if v is not None})


def _query(location):
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def _handle(resp):
    assert resp.status_code == 302, resp.text
    loc = resp.headers["location"]
    assert loc.startswith("/oauth/consent?request="), loc
    return _query(loc)["request"]


def _approve(env, handle, approve=True):
    r = env.client.post("/oauth/authorize/decision", json={"request": handle, "approve": approve})
    assert r.status_code == 200, r.text
    return r.json()["redirect_to"]


def _token(env, **form):
    return env.client.post("/oauth/token", data=form)


def _grant(env, client_id=CLAUDE_CODE, redirect_uri="http://localhost:33418/callback"):
    """Run the whole browser leg and exchange the code: returns the token response."""
    verifier, challenge = _pkce()
    handle = _handle(_authorize(env, client_id, redirect_uri, challenge))
    q = _query(_approve(env, handle))
    r = _token(env, grant_type="authorization_code", code=q["code"], client_id=client_id,
               redirect_uri=redirect_uri, code_verifier=verifier, resource=RESOURCE)
    assert r.status_code == 200, r.text
    return r.json()


def _mcp(token, fn):
    from backend.main import app
    from backend.mcp_server import mcp_http_app

    out = {}

    async def main():
        async with mcp_http_app.lifespan():
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as hc:
                async with Client(streamable_http_client("http://testserver/mcp", http_client=hc),
                                  mode="legacy") as client:
                    out["value"] = await fn(client)

    anyio.run(main)
    return out["value"]


def _post_mcp(env, token=None):
    """A raw tools/list POST to /mcp (with the session manager running)."""
    from backend.main import app
    from backend.mcp_server import mcp_http_app

    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    out = {}

    async def main():
        async with mcp_http_app.lifespan():
            async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app),
                                          base_url="http://testserver") as hc:
                out["r"] = await hc.post("/mcp", json=body, headers=headers)

    anyio.run(main)
    return out["r"]


# ---- discovery -----------------------------------------------------------------------

def test_metadata_documents(env):
    for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        r = env.client.get(path)
        assert r.status_code == 200
        prm = r.json()
        assert prm["resource"] == RESOURCE
        assert prm["authorization_servers"] == [BASE]
        assert prm["scopes_supported"] == ["mcp"]
        assert prm["bearer_methods_supported"] == ["header"]

    asm = env.client.get("/.well-known/oauth-authorization-server").json()
    assert asm["issuer"] == BASE
    assert asm["authorization_endpoint"] == f"{BASE}/oauth/authorize"
    assert asm["token_endpoint"] == f"{BASE}/oauth/token"
    assert asm["registration_endpoint"] == f"{BASE}/oauth/register"
    assert asm["revocation_endpoint"] == f"{BASE}/oauth/revoke"
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert "none" in asm["token_endpoint_auth_methods_supported"]
    assert asm["client_id_metadata_document_supported"] is True
    assert set(asm["grant_types_supported"]) == {"authorization_code", "refresh_token"}
    assert asm["response_types_supported"] == ["code"]
    assert "offline_access" in asm["scopes_supported"] and "mcp" in asm["scopes_supported"]

    # Browser-based clients (MCP Inspector) can read them cross-origin.
    r = env.client.get("/.well-known/oauth-authorization-server", headers={"Origin": "http://localhost:6274"})
    assert r.headers["access-control-allow-origin"] == "*"
    pre = env.client.options("/oauth/token", headers={
        "Origin": "http://localhost:6274", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "*"


def test_unauthenticated_mcp_is_401_with_resource_metadata(env):
    r = _post_mcp(env)
    assert r.status_code == 401
    www = r.headers["www-authenticate"]
    assert www.startswith("Bearer ")
    assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource"' in www
    assert 'scope="mcp"' in www
    assert "error=" not in www  # no token at all: a plain challenge

    r = _post_mcp(env, "rlfo_not-a-token")
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]
    assert "resource_metadata=" in r.headers["www-authenticate"]


# ---- registration --------------------------------------------------------------------

def test_dynamic_client_registration(env):
    r = env.client.post("/oauth/register", json={
        "client_name": "Claude", "redirect_uris": [HOSTED],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none"})
    assert r.status_code == 201, r.text
    reg = r.json()
    assert reg["client_id"].startswith("rlfc_") and reg["redirect_uris"] == [HOSTED]
    assert reg["token_endpoint_auth_method"] == "none" and "client_secret" not in reg
    stored = env.db.oauth_clients.find_one({"_id": reg["client_id"]})
    assert stored["client_name"] == "Claude" and stored["expires_at"]

    # Loopback http is fine; any other http, or garbage, is not.
    assert env.client.post("/oauth/register", json={
        "redirect_uris": ["http://127.0.0.1/callback"]}).status_code == 201
    for bad in (["http://evil.example/cb"], ["https://x.example/cb#frag"], [], "https://x"):
        r = env.client.post("/oauth/register", json={"redirect_uris": bad})
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri", bad
    r = env.client.post("/oauth/register", json={"redirect_uris": [HOSTED], "token_endpoint_auth_method": "private_key_jwt"})
    assert r.json()["error"] == "invalid_client_metadata"
    assert env.client.post("/oauth/register", content=b"nope",
                           headers={"Content-Type": "application/json"}).status_code == 400


def test_dcr_client_full_flow_hosted_claude_and_unused_client_ttl_cleared(env):
    reg = env.client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [HOSTED]}).json()
    verifier, challenge = _pkce()
    handle = _handle(_authorize(env, reg["client_id"], HOSTED, challenge))

    info = env.client.get("/oauth/authorize/request", params={"request": handle}).json()
    assert info["client_name"] == "Claude" and info["client_kind"] == "dcr"
    assert info["redirect_host"] == "claude.ai" and info["hosted_claude"] and not info["loopback"]

    q = _query(_approve(env, handle))
    assert q["state"] == "st-123" and q["iss"] == BASE
    r = _token(env, grant_type="authorization_code", code=q["code"], client_id=reg["client_id"],
               redirect_uri=HOSTED, code_verifier=verifier)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    assert "expires_at" not in env.db.oauth_clients.find_one({"_id": reg["client_id"]})


def test_confidential_dcr_client_needs_its_secret(env):
    reg = env.client.post("/oauth/register", json={
        "redirect_uris": [HOSTED], "token_endpoint_auth_method": "client_secret_basic"}).json()
    assert reg["client_secret"]
    verifier, challenge = _pkce()
    q = _query(_approve(env, _handle(_authorize(env, reg["client_id"], HOSTED, challenge))))
    form = dict(grant_type="authorization_code", code=q["code"], redirect_uri=HOSTED, code_verifier=verifier)
    r = _token(env, client_id=reg["client_id"], **form)
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"
    basic = base64.b64encode(f"{reg['client_id']}:{reg['client_secret']}".encode()).decode()
    # The failed attempt didn't burn the code (client auth runs first).
    r = env.client.post("/oauth/token", data=form, headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200, r.text


# ---- CIMD ----------------------------------------------------------------------------

def test_cimd_client_loopback_port_agnostic_for_localhost_and_127(env):
    for redirect in ("http://localhost:53682/callback", "http://127.0.0.1:1234/callback",
                     "http://localhost/callback"):
        _, challenge = _pkce()
        handle = _handle(_authorize(env, CLAUDE_CODE, redirect, challenge))
        info = env.client.get("/oauth/authorize/request", params={"request": handle}).json()
        assert info["client_name"] == "Claude Code" and info["client_kind"] == "cimd"
        assert info["client_host"] == "claude.ai" and info["loopback"] is True
        assert info["redirect_uri"] == redirect
    # The document is cached (one fetch for three authorizations).
    assert env.fetched == [CLAUDE_CODE]

    # Port-agnostic, but not path- or host-agnostic.
    for bad in ("http://localhost:5555/evil", "http://evil.example:80/callback", HOSTED,
                "https://localhost/callback"):
        _, challenge = _pkce()
        r = _authorize(env, CLAUDE_CODE, bad, challenge)
        assert r.status_code == 400 and "redirect_uri" in r.text, bad
        assert "location" not in r.headers


def test_cimd_full_flow_and_token_works_on_mcp(env):
    tokens = _grant(env, CLAUDE_CODE, "http://127.0.0.1:40111/callback")
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
    assert tokens["access_token"].startswith("rlfo_") and tokens["refresh_token"].startswith("rlfr_")
    assert tokens["scope"] == "mcp offline_access"
    # Only hashes are stored.
    doc = env.db.oauth_tokens.find_one({"uid": U})
    assert tokens["access_token"] not in json.dumps(doc, default=str)
    assert doc["client_name"] == "Claude Code" and doc["resource"] == RESOURCE

    async def use(client):
        tools = await client.list_tools()
        fit = await client.call_tool("fit_distribution", {"data": [100, 200, 300, 400, 500]})
        return tools, fit

    tools, fit = _mcp(tokens["access_token"], use)
    assert "fit_distribution" in {t.name for t in tools.tools}
    assert not fit.is_error and fit.structured_content["saved"] is False
    assert env.db.oauth_tokens.find_one({"uid": U})["last_used_at"] is not None


def test_cimd_document_validation(env):
    from backend.services import oauth as oauth_service

    bad_id = "https://tool.example/client.json"
    env.cimd_docs[bad_id] = {**CLAUDE_CODE_DOC, "client_id": "https://someone-else.example/client.json"}
    _, challenge = _pkce()
    r = _authorize(env, bad_id, "http://localhost:1/callback", challenge)
    assert r.status_code == 400 and "match" in r.text

    missing = "https://tool.example/missing.json"
    r = _authorize(env, missing, "http://localhost:1/callback", challenge)
    assert r.status_code == 400 and "HTTP 404" in r.text

    confidential = "https://tool.example/conf.json"
    env.cimd_docs[confidential] = {**CLAUDE_CODE_DOC, "client_id": confidential,
                                   "token_endpoint_auth_method": "private_key_jwt"}
    assert _authorize(env, confidential, "http://localhost:1/callback", challenge).status_code == 400

    # URL shape / SSRF guards, before any fetch.
    for url in ("https://127.0.0.1/x.json", "https://10.1.2.3/x.json", "https://localhost/x.json",
                "https://tool.example", "https://user:pw@tool.example/x.json"):
        with pytest.raises(oauth_service.OAuthError):
            oauth_service.validate_cimd_url(url)


def test_cimd_fetch_refuses_private_addresses(env, monkeypatch):
    """The real fetcher resolves the host first and refuses internal IPs."""
    from backend.services import oauth as oauth_service

    def refuse_connect(*a, **kw):  # the guard must fire before any connection
        raise AssertionError("tried to connect")

    monkeypatch.setattr("httpx.Client", refuse_connect)
    monkeypatch.setattr(oauth_service.socket, "getaddrinfo",
                        lambda host, port, **kw: [(2, 1, 6, "", ("169.254.169.254", port))])
    with pytest.raises(oauth_service.OAuthError, match="public host"):
        REAL_FETCH("https://metadata.example/client.json")
    monkeypatch.setattr(oauth_service.socket, "getaddrinfo",
                        lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", port)),
                                                  (2, 1, 6, "", ("192.168.0.5", port))])
    with pytest.raises(oauth_service.OAuthError, match="public host"):
        REAL_FETCH("https://mixed.example/client.json")
    monkeypatch.setattr(oauth_service.socket, "getaddrinfo",
                        lambda host, port, **kw: [(10, 1, 6, "", ("::ffff:10.0.0.1", port, 0, 0))])
    with pytest.raises(oauth_service.OAuthError, match="public host"):
        REAL_FETCH("https://mapped.example/client.json")


# ---- authorization request validation ------------------------------------------------------

def test_authorize_validation_errors(env):
    reg = env.client.post("/oauth/register", json={"redirect_uris": [HOSTED]}).json()
    cid = reg["client_id"]
    _, challenge = _pkce()

    # Unknown client / unregistered redirect: an error page, never a redirect.
    r = _authorize(env, "rlfc_nope", HOSTED, challenge)
    assert r.status_code == 400 and "location" not in r.headers and "register" in r.text
    r = _authorize(env, cid, "https://evil.example/cb", challenge)
    assert r.status_code == 400 and "location" not in r.headers

    # Everything else goes back to the (verified) redirect with error + state.
    cases = [
        ({"code_challenge": None}, "invalid_request"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge_method": None}, "invalid_request"),
        ({"code_challenge": "short"}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"scope": "mcp admin"}, "invalid_scope"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
    ]
    for extra, error in cases:
        extra = {"code_challenge": challenge, **extra}
        r = _authorize(env, cid, HOSTED, extra.pop("code_challenge"), **extra)
        assert r.status_code == 302, (extra, r.text)
        loc = r.headers["location"]
        assert loc.startswith(HOSTED + "?"), loc
        q = _query(loc)
        assert q["error"] == error and q["state"] == "st-123", (extra, q)
    assert env.db.oauth_requests.count_documents({}) == 0

    # The resource indicator is optional and tolerant of a trailing slash.
    _handle(_authorize(env, cid, HOSTED, challenge, resource=None))
    _handle(_authorize(env, cid, HOSTED, challenge, resource=RESOURCE + "/"))


def test_redirect_matching_rules():
    from backend.services.oauth import redirect_matches

    assert redirect_matches("http://localhost/callback", "http://localhost:3118/callback")
    assert redirect_matches("http://127.0.0.1/callback", "http://127.0.0.1:65000/callback")
    assert redirect_matches("http://[::1]/callback", "http://[::1]:8080/callback")
    assert not redirect_matches("http://localhost/callback", "http://127.0.0.1:3118/callback")
    assert not redirect_matches("http://localhost/callback", "http://localhost:3118/callback2")
    assert not redirect_matches(HOSTED, "https://claude.ai:444/api/mcp/auth_callback")
    assert not redirect_matches(HOSTED, HOSTED + "/x")
    assert redirect_matches(HOSTED, HOSTED)


# ---- consent ---------------------------------------------------------------------------------

def test_consent_deny_and_single_use_handle(env):
    _, challenge = _pkce()
    handle = _handle(_authorize(env, CLAUDE_CODE, "http://localhost:9/callback", challenge))
    q = _query(_approve(env, handle, approve=False))
    assert q["error"] == "access_denied" and q["state"] == "st-123" and "code" not in q
    assert env.db.oauth_codes.count_documents({}) == 0
    # The handle is gone.
    r = env.client.post("/oauth/authorize/decision", json={"request": handle, "approve": True})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    assert env.client.get("/oauth/authorize/request", params={"request": handle}).status_code == 404


def test_consent_requires_sign_in_and_expires(env):
    from backend.auth import get_current_user
    from backend.main import app

    _, challenge = _pkce()
    handle = _handle(_authorize(env, CLAUDE_CODE, "http://localhost:9/callback", challenge))
    app.dependency_overrides.pop(get_current_user)
    r = env.client.post("/oauth/authorize/decision", json={"request": handle, "approve": True})
    assert r.status_code == 401

    env.db.oauth_requests.update_many({}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert env.client.get("/oauth/authorize/request", params={"request": handle}).status_code == 404


def test_consent_page_is_noindex_and_unframeable(env):
    from backend.routers import oauth as oauth_router

    if not oauth_router._FRONTEND_INDEX.is_file():
        pytest.skip("frontend not built")
    r = env.client.get("/oauth/consent?request=abc")
    assert r.status_code == 200
    assert "noindex" in r.headers["x-robots-tag"] and r.headers["x-frame-options"] == "DENY"


# ---- token endpoint ---------------------------------------------------------------------------

def test_code_exchange_pkce_and_one_time_use(env):
    redirect = "http://localhost:7777/callback"
    verifier, challenge = _pkce()
    q = _query(_approve(env, _handle(_authorize(env, CLAUDE_CODE, redirect, challenge))))
    base = dict(grant_type="authorization_code", code=q["code"], client_id=CLAUDE_CODE, redirect_uri=redirect)

    # JSON bodies are refused; form-encoded is the contract.
    r = env.client.post("/oauth/token", json={**base, "code_verifier": verifier})
    assert r.status_code == 400 and r.json()["error"] == "invalid_request"

    r = _token(env, **base, code_verifier=_pkce()[0])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    # A failed PKCE check burns the code.
    r = _token(env, **base, code_verifier=verifier)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"

    # Fresh code, correct verifier.
    verifier, challenge = _pkce()
    q = _query(_approve(env, _handle(_authorize(env, CLAUDE_CODE, redirect, challenge))))
    base["code"] = q["code"]
    assert _token(env, **base, code_verifier=verifier).status_code == 200
    assert env.db.oauth_tokens.count_documents({"revoked": False}) == 1
    # Replaying the code fails and revokes what it was exchanged for.
    r = _token(env, **base, code_verifier=verifier)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert env.db.oauth_tokens.count_documents({"revoked": False}) == 0

    # Wrong redirect_uri, wrong client, unknown grant type.
    verifier, challenge = _pkce()
    q = _query(_approve(env, _handle(_authorize(env, CLAUDE_CODE, redirect, challenge))))
    r = _token(env, **{**base, "code": q["code"], "redirect_uri": "http://localhost:1/callback"}, code_verifier=verifier)
    assert r.json()["error"] == "invalid_grant"
    assert _token(env, grant_type="password", client_id=CLAUDE_CODE).json()["error"] == "unsupported_grant_type"
    assert _token(env, grant_type="authorization_code", code="x", client_id="rlfc_unknown",
                  code_verifier=verifier).status_code == 401


def test_expired_code_is_rejected(env):
    redirect = "http://localhost:7777/callback"
    verifier, challenge = _pkce()
    q = _query(_approve(env, _handle(_authorize(env, CLAUDE_CODE, redirect, challenge))))
    env.db.oauth_codes.update_many({}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    r = _token(env, grant_type="authorization_code", code=q["code"], client_id=CLAUDE_CODE,
               redirect_uri=redirect, code_verifier=verifier)
    assert r.json()["error"] == "invalid_grant"


def test_refresh_rotation_and_reuse_detection(env):
    first = _grant(env)
    r = _token(env, grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=CLAUDE_CODE,
               resource=RESOURCE)
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]
    assert _post_mcp(env, second["access_token"]).status_code == 200

    # A retried / concurrent refresh with the just-rotated token (inside the
    # grace window) gets a fresh pair and does NOT disconnect the user.
    r = _token(env, grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=CLAUDE_CODE)
    assert r.status_code == 200, r.text
    retry = r.json()
    assert retry["refresh_token"] not in (first["refresh_token"], second["refresh_token"])
    assert _post_mcp(env, second["access_token"]).status_code == 200
    assert _post_mcp(env, retry["access_token"]).status_code == 200

    # After the window, replaying a rotated-away token means it leaked:
    # the whole grant is revoked.
    env.db.oauth_tokens.update_many(
        {"rotated": True},
        {"$set": {"rotated_at": datetime.now(timezone.utc) - timedelta(minutes=5)}})
    r = _token(env, grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=CLAUDE_CODE)
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert _post_mcp(env, second["access_token"]).status_code == 401
    assert _post_mcp(env, retry["access_token"]).status_code == 401
    r = _token(env, grant_type="refresh_token", refresh_token=second["refresh_token"], client_id=CLAUDE_CODE)
    assert r.json()["error"] == "invalid_grant"

    # Garbage, another client's token, expired.
    assert _token(env, grant_type="refresh_token", refresh_token="rlfr_nope",
                  client_id=CLAUDE_CODE).json()["error"] == "invalid_grant"
    third = _grant(env)
    reg = env.client.post("/oauth/register", json={"redirect_uris": [HOSTED]}).json()
    assert _token(env, grant_type="refresh_token", refresh_token=third["refresh_token"],
                  client_id=reg["client_id"]).json()["error"] == "invalid_grant"
    env.db.oauth_tokens.update_many({}, {"$set": {"refresh_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert _token(env, grant_type="refresh_token", refresh_token=third["refresh_token"],
                  client_id=CLAUDE_CODE).json()["error"] == "invalid_grant"


def test_expired_or_foreign_access_token_is_401(env):
    tokens = _grant(env)
    assert _post_mcp(env, tokens["access_token"]).status_code == 200
    env.db.oauth_tokens.update_many({}, {"$set": {"resource": "https://elsewhere.example/mcp"}})
    assert _post_mcp(env, tokens["access_token"]).status_code == 401
    env.db.oauth_tokens.update_many({}, {"$set": {"resource": RESOURCE,
                                                  "access_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    r = _post_mcp(env, tokens["access_token"])
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_rfc7009_revocation(env):
    tokens = _grant(env)
    r = env.client.post("/oauth/revoke", data={"token": tokens["refresh_token"], "client_id": CLAUDE_CODE})
    assert r.status_code == 200
    assert _post_mcp(env, tokens["access_token"]).status_code == 401
    # Unknown tokens are not an error (RFC 7009 §2.2).
    assert env.client.post("/oauth/revoke", data={"token": "whatever", "client_id": CLAUDE_CODE}).status_code == 200


# ---- Settings: connected apps ----------------------------------------------------------------

def test_connected_apps_list_and_revoke(env):
    tokens = _grant(env)
    _post_mcp(env, tokens["access_token"])
    grants = env.client.get("/api/me/oauth-grants").json()["grants"]
    assert len(grants) == 1
    g = grants[0]
    assert g["client_name"] == "Claude Code" and g["client_host"] == "claude.ai"
    assert g["created_at"] and g["last_used_at"]

    # A rotation doesn't create a second connected app.
    r = _token(env, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=CLAUDE_CODE)
    fresh = r.json()
    assert len(env.client.get("/api/me/oauth-grants").json()["grants"]) == 1

    # Someone else can't see or revoke it.
    env.signed_in["uid"] = OTHER
    assert env.client.get("/api/me/oauth-grants").json()["grants"] == []
    assert env.client.delete(f"/api/me/oauth-grants/{g['id']}").status_code == 404
    env.signed_in["uid"] = U

    assert env.client.delete(f"/api/me/oauth-grants/{g['id']}").status_code == 200
    assert env.client.get("/api/me/oauth-grants").json()["grants"] == []
    assert _post_mcp(env, fresh["access_token"]).status_code == 401
    r = _token(env, grant_type="refresh_token", refresh_token=fresh["refresh_token"], client_id=CLAUDE_CODE)
    assert r.json()["error"] == "invalid_grant"


# ---- entitlement -------------------------------------------------------------------------------

def test_free_oauth_user_tries_it_within_the_allowance(env, monkeypatch):
    from backend import config
    from backend.services import tokens as tokens_service

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    tokens = _grant(env)
    assert _post_mcp(env, tokens["access_token"]).status_code == 200

    async def use(client):
        return (await client.list_tools(), await client.call_tool("list_models", {}),
                await client.call_tool("fit_distribution", {"data": [100, 200, 300]}))

    tools, listed, fit = _mcp(tokens["access_token"], use)
    assert len(tools.tools) == 27  # connecting and listing work on Free...
    assert not listed.is_error  # ...as do the allowance's tools...
    assert fit.is_error  # ...but not fitting, which is part of Pro
    text = fit.content[0].text
    assert "Fitting in Reliafy is part of Reliafy Pro (US$19/month)" in text
    assert f"{BASE}/billing" in text and "upgrade_link" in text

    # API tokens keep the transport-level 403 for free users...
    api = tokens_service.create_token(env.db, U, "script")["token"]
    r = _post_mcp(env, api)
    assert r.status_code == 403 and "API token is part of Reliafy Pro" in r.json()["detail"]

    # ...and once Pro, both work, fitting included.
    env.db.users.update_one({"_id": U}, {"$set": {"plan": "pro"}})
    assert _post_mcp(env, api).status_code == 200
    ok = _mcp(tokens["access_token"], lambda c: c.call_tool("fit_distribution", {"data": [100, 200, 300]}))
    assert not ok.is_error


def test_api_tokens_still_work_alongside_oauth(env):
    from backend.services import tokens as tokens_service

    api = tokens_service.create_token(env.db, U, "script")["token"]
    tools = _mcp(api, lambda c: c.list_tools())
    assert "fit_and_save_model" in {t.name for t in tools.tools}
