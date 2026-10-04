"""OAuth 2.1 authorization server for the MCP endpoint (Claude connectors).

Reliafy is both the authorization server (issuer ``https://reliafy.com``) and
the protected resource (``https://reliafy.com/mcp``). Users sign in with the
normal Firebase login; this module only ever issues opaque tokens for the MCP
resource, and — like the personal API tokens — stores nothing but their
sha256 hashes.

Clients identify themselves one of two ways:

* **Client ID Metadata Document (CIMD)** — the ``client_id`` is an HTTPS URL
  (e.g. Claude Code's ``https://claude.ai/oauth/claude-code-client-metadata``)
  whose JSON we fetch, validate and cache. Claude prefers this.
* **Dynamic Client Registration (RFC 7591)** — ``POST /oauth/register``.

Everything is a public client with mandatory S256 PKCE (DCR clients may also
ask for a secret). Refresh tokens rotate on every use; presenting a rotated
refresh token again revokes the whole grant ("family"), per OAuth 2.1 §4.3.1.

Collections: ``oauth_clients`` (DCR registrations), ``oauth_requests``
(pending consent, 10 min), ``oauth_codes`` (5 min, one-time) and
``oauth_tokens`` (one document per issued access/refresh pair, grouped into a
grant by ``family_id``). TTL indexes are created in :func:`backend.db.init_db`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

from backend import config
from backend.services import email_trust

logger = logging.getLogger(__name__)

# ---- Lifetimes ----------------------------------------------------------------
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=60)
# A rotated refresh token presented again within this window is treated as a
# retried/concurrent refresh (reissue), not theft (revoke). See refresh().
REFRESH_REUSE_GRACE = timedelta(seconds=60)
CODE_TTL = timedelta(minutes=5)
REQUEST_TTL = timedelta(minutes=10)      # the consent page's authorization-request handle
UNUSED_CLIENT_TTL = timedelta(days=1)    # a DCR client that never completes a grant is purged

# ---- Scopes -------------------------------------------------------------------
SCOPE = "mcp"                   # everything the MCP tools can do, as the user
OFFLINE = "offline_access"      # advertised so Claude asks for (and gets) refresh tokens
SUPPORTED_SCOPES = (SCOPE, OFFLINE)

ACCESS_PREFIX = "rlfo_"
REFRESH_PREFIX = "rlfr_"

HOSTED_CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


class OAuthError(Exception):
    """An RFC 6749 error: ``error`` code, human description, HTTP status."""

    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(description or error)
        self.error = error
        self.description = description
        self.status = status

    def body(self) -> dict:
        out = {"error": self.error}
        if self.description:
            out["error_description"] = self.description
        return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    """Mongo returns naive UTC datetimes; make them comparable with _now()."""
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- URLs ---------------------------------------------------------------------

def issuer() -> str:
    """The authorization server's issuer — the site's public origin."""
    return config.PUBLIC_BASE_URL or "https://reliafy.com"


def resource() -> str:
    """The protected resource: exactly the MCP URL users enter in Claude."""
    return f"{issuer()}/mcp"


def resource_metadata_url() -> str:
    return f"{issuer()}/.well-known/oauth-protected-resource"


def protected_resource_metadata() -> dict:
    """RFC 9728 document for the MCP endpoint."""
    return {
        "resource": resource(),
        "authorization_servers": [issuer()],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Reliafy",
        "resource_documentation": f"{issuer()}/api-docs",
    }


def authorization_server_metadata() -> dict:
    """RFC 8414 document."""
    base = issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "scopes_supported": list(SUPPORTED_SCOPES),
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{base}/api-docs",
    }


def www_authenticate(error: str | None = None, description: str | None = None) -> str:
    """The ``WWW-Authenticate`` challenge for a 401 from /mcp."""
    parts = []
    if error:
        parts.append(f'error="{error}"')
    if description:
        parts.append('error_description="%s"' % description.replace('"', "'"))
    parts.append(f'resource_metadata="{resource_metadata_url()}"')
    parts.append(f'scope="{SCOPE}"')
    return "Bearer " + ", ".join(parts)


def _canonical(uri: str) -> str:
    """Lowercase scheme/host, no trailing slash — for comparing resource URIs."""
    p = urlsplit(uri.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, ""))


def check_resource(value: str | None) -> None:
    """RFC 8707: a ``resource`` indicator, when sent, must name our MCP server."""
    if value and _canonical(value) != _canonical(resource()):
        raise OAuthError("invalid_target", f"This server issues tokens only for {resource()}.")


# ---- Redirect URIs --------------------------------------------------------------

def is_loopback(uri: str) -> bool:
    p = urlsplit(uri)
    return p.scheme == "http" and (p.hostname or "").lower() in _LOOPBACK_HOSTS


def valid_redirect_uri(uri: str) -> bool:
    """HTTPS, or an http loopback redirect (native apps, RFC 8252). No fragments."""
    if not isinstance(uri, str) or len(uri) > 2000:
        return False
    try:
        p = urlsplit(uri)
        p.port  # noqa: B018 - raises on a malformed port
    except ValueError:
        return False
    if p.fragment or not p.hostname:
        return False
    if p.scheme == "https":
        return True
    return is_loopback(uri)


def redirect_matches(registered: str, requested: str) -> bool:
    """Exact match, except loopback redirects ignore the port (RFC 8252 §7.3).

    Applied to ``localhost`` as well as the IP literals, because Claude Code
    declares ``http://localhost/callback`` in its metadata document.
    """
    if registered == requested:
        return True
    if not (is_loopback(registered) and is_loopback(requested)):
        return False
    a, b = urlsplit(registered), urlsplit(requested)
    try:
        a.port, b.port  # noqa: B018
    except ValueError:
        return False
    return ((a.hostname or "").lower() == (b.hostname or "").lower()
            and (a.path or "/") == (b.path or "/") and a.query == b.query)


def redirect_host(uri: str) -> str:
    return (urlsplit(uri).hostname or "").lower()


def with_query(uri: str, params: dict) -> str:
    """Append params to a redirect URI, keeping any query it already has."""
    p = urlsplit(uri)
    extra = urlencode({k: v for k, v in params.items() if v is not None})
    query = f"{p.query}&{extra}" if p.query else extra
    return urlunsplit((p.scheme, p.netloc, p.path, query, ""))


# ---- Client ID Metadata Documents ------------------------------------------------

CIMD_TIMEOUT = 5.0            # seconds, connect + read
CIMD_MAX_BYTES = 64 * 1024
CIMD_MIN_CACHE = 60
CIMD_MAX_CACHE = 24 * 3600
CIMD_DEFAULT_CACHE = 3600

_cimd_cache: dict[str, tuple[float, dict]] = {}
_cimd_lock = threading.Lock()


def is_cimd_client_id(client_id: str) -> bool:
    return isinstance(client_id, str) and client_id.startswith("https://")


def _public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not (addr.is_multicast or addr.is_reserved or addr.is_loopback
                                   or addr.is_link_local or addr.is_private or addr.is_unspecified)


def _resolve_public(host: str, port: int) -> str:
    """Resolve ``host`` and return one address — refusing if ANY is non-public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OAuthError("invalid_client", f"Couldn't resolve the client metadata host {host}.") from exc
    ips = [info[4][0] for info in infos]
    if not ips or not all(_public_ip(ip) for ip in ips):
        raise OAuthError("invalid_client", "The client metadata URL must be on a public host.")
    return ips[0]


def _http_fetch(url: str) -> tuple[int, dict, bytes]:
    """GET a CIMD URL safely: HTTPS only, public IPs only (resolved once and
    pinned, so a DNS rebind can't swap in an internal address between the
    check and the connection), no redirects, 5 s timeout, 64 KB cap.

    Returns ``(status, lower-cased headers, body)``. Tests monkeypatch this.
    """
    import httpx

    p = urlsplit(url)
    host = p.hostname or ""
    port = p.port or 443
    ip = _resolve_public(host, port)
    ip_host = f"[{ip}]" if ":" in ip else ip
    pinned = urlunsplit(("https", f"{ip_host}:{port}", p.path or "/", p.query, ""))
    host_header = host if port == 443 else f"{host}:{port}"
    with httpx.Client(timeout=CIMD_TIMEOUT, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", pinned, headers={"Host": host_header, "Accept": "application/json"},
                           extensions={"sni_hostname": host}) as resp:
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > CIMD_MAX_BYTES:
                    raise OAuthError("invalid_client", "The client metadata document is too large.")
            return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, body


def _cache_seconds(headers: dict) -> int:
    cc = (headers.get("cache-control") or "").lower()
    m = re.search(r"max-age=(\d+)", cc)
    seconds = int(m.group(1)) if m else CIMD_DEFAULT_CACHE
    return max(CIMD_MIN_CACHE, min(CIMD_MAX_CACHE, seconds))


def validate_cimd_url(client_id: str) -> None:
    p = urlsplit(client_id)
    if (p.scheme != "https" or not p.hostname or p.path in ("", "/") or p.fragment
            or p.username or p.password or len(client_id) > 2000):
        raise OAuthError("invalid_client", "A URL client_id must be an https URL with a path.")
    host = p.hostname.lower()
    if host in _LOOPBACK_HOSTS or host.endswith(".localhost") or host.endswith(".internal"):
        raise OAuthError("invalid_client", "The client metadata URL must be on a public host.")
    try:
        if not _public_ip(host):
            raise OAuthError("invalid_client", "The client metadata URL must be on a public host.")
    except ValueError:
        pass  # a hostname, not an IP literal — checked at resolution time


def fetch_client_metadata(client_id: str) -> dict:
    """The validated metadata document for a URL ``client_id`` (cached)."""
    validate_cimd_url(client_id)
    with _cimd_lock:
        hit = _cimd_cache.get(client_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    try:
        status, headers, body = _http_fetch(client_id)
    except OAuthError:
        raise
    except Exception as exc:  # network failure, TLS error, timeout
        logger.warning("CIMD fetch failed for %s: %s", client_id, exc)
        raise OAuthError("invalid_client", "Couldn't fetch the client's metadata document.") from exc
    if status != 200:
        raise OAuthError("invalid_client", f"The client's metadata document returned HTTP {status}.")
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OAuthError("invalid_client", "The client's metadata document isn't valid JSON.") from exc
    if not isinstance(doc, dict):
        raise OAuthError("invalid_client", "The client's metadata document must be a JSON object.")
    if doc.get("client_id") != client_id:
        raise OAuthError("invalid_client", "The metadata document's client_id doesn't match its URL.")
    uris = doc.get("redirect_uris")
    if not isinstance(uris, list) or not uris or not all(valid_redirect_uri(u) for u in uris):
        raise OAuthError("invalid_client", "The metadata document needs valid redirect_uris.")
    method = doc.get("token_endpoint_auth_method", "none")
    if method != "none":
        raise OAuthError("invalid_client", "Only public clients (token_endpoint_auth_method 'none') "
                                           "may use a client metadata document here.")
    name = doc.get("client_name")
    client = {
        "client_id": client_id,
        "client_name": (name.strip()[:100] if isinstance(name, str) and name.strip() else redirect_host(client_id)),
        "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "kind": "cimd",
    }
    with _cimd_lock:
        _cimd_cache[client_id] = (time.monotonic() + _cache_seconds(headers), client)
    return client


# ---- Dynamic client registration ---------------------------------------------------

_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")


def register_client(db, meta: dict) -> dict:
    """RFC 7591 registration. Raises OAuthError(invalid_redirect_uri /
    invalid_client_metadata)."""
    if not isinstance(meta, dict):
        raise OAuthError("invalid_client_metadata", "Send the client metadata as a JSON object.")
    uris = meta.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        raise OAuthError("invalid_redirect_uri", "redirect_uris must list 1–10 redirect URIs.")
    for uri in uris:
        if not valid_redirect_uri(uri):
            raise OAuthError("invalid_redirect_uri",
                             f"Redirect URIs must be https, or http on localhost/127.0.0.1: {uri!r}")
    method = meta.get("token_endpoint_auth_method") or "none"
    if method not in _AUTH_METHODS:
        raise OAuthError("invalid_client_metadata", f"token_endpoint_auth_method must be one of {', '.join(_AUTH_METHODS)}.")
    grants = meta.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or "authorization_code" not in grants or \
            any(g not in ("authorization_code", "refresh_token") for g in grants):
        raise OAuthError("invalid_client_metadata", "grant_types may be authorization_code and refresh_token.")
    responses = meta.get("response_types") or ["code"]
    if responses != ["code"]:
        raise OAuthError("invalid_client_metadata", "response_types must be ['code'].")
    scope = meta.get("scope")
    if scope is not None and (not isinstance(scope, str) or any(s not in SUPPORTED_SCOPES for s in scope.split())):
        raise OAuthError("invalid_client_metadata", f"Supported scopes: {' '.join(SUPPORTED_SCOPES)}.")
    name = meta.get("client_name")
    name = name.strip()[:100] if isinstance(name, str) and name.strip() else "MCP client"

    now = _now()
    client_id = "rlfc_" + secrets.token_urlsafe(18)
    doc = {
        "_id": client_id,
        "client_id": client_id,
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": grants,
        "token_endpoint_auth_method": method,
        "created_at": now,
        # Unset once the client completes a grant, so registrations that never
        # get used (Claude registers afresh on every new connection) expire.
        "expires_at": now + UNUSED_CLIENT_TTL,
    }
    out = {
        "client_id": client_id,
        "client_id_issued_at": int(now.timestamp()),
        "client_name": name,
        "redirect_uris": uris,
        "grant_types": grants,
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
    }
    if scope:
        out["scope"] = scope
    if method != "none":
        secret = secrets.token_urlsafe(32)
        doc["secret_hash"] = _hash(secret)
        out["client_secret"] = secret
        out["client_secret_expires_at"] = 0
    db.oauth_clients.insert_one(doc)
    return out


def get_client(db, client_id: str) -> dict:
    """A known client (CIMD or registered), or OAuthError(invalid_client)."""
    if not client_id or not isinstance(client_id, str):
        raise OAuthError("invalid_client", "Missing client_id.")
    if is_cimd_client_id(client_id):
        return fetch_client_metadata(client_id)
    doc = db.oauth_clients.find_one({"_id": client_id})
    if doc is None:
        raise OAuthError("invalid_client", "Unknown client_id — register the client first.", 401)
    return {**doc, "kind": "dcr"}


def authenticate_client(db, client_id: str | None, secret: str | None) -> dict:
    """Token/revocation endpoint client authentication."""
    client = get_client(db, client_id)
    if client.get("token_endpoint_auth_method", "none") != "none":
        if not secret or not hmac.compare_digest(_hash(secret), client.get("secret_hash", "")):
            raise OAuthError("invalid_client", "Client authentication failed.", 401)
    return client


# ---- Authorization requests ----------------------------------------------------------

_PKCE_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


def parse_scopes(scope: str | None) -> list[str]:
    requested = (scope or "").split()
    unknown = [s for s in requested if s not in SUPPORTED_SCOPES]
    if unknown:
        raise OAuthError("invalid_scope", f"Unknown scope: {' '.join(unknown)}. Supported: {' '.join(SUPPORTED_SCOPES)}.")
    # Every grant carries the MCP scope; offline_access is recorded if asked for.
    return [SCOPE] + ([OFFLINE] if OFFLINE in requested else [])


def start_authorization(db, params: dict) -> tuple[str | None, str | None]:
    """Validate an authorization request.

    Returns ``(handle, None)`` for a request the consent page should show, or
    ``(None, error_redirect)`` for an error that goes back to the client. An
    unknown client or unregistered redirect_uri raises OAuthError and must be
    shown to the user, never redirected (RFC 6749 §4.1.2.1).
    """
    client_id = params.get("client_id") or ""
    redirect_uri = params.get("redirect_uri") or ""
    client = get_client(db, client_id)
    if not redirect_uri:
        raise OAuthError("invalid_request", "redirect_uri is required.")
    if not valid_redirect_uri(redirect_uri) or not any(
            redirect_matches(r, redirect_uri) for r in client["redirect_uris"]):
        raise OAuthError("invalid_request", "redirect_uri isn't registered for this client.")

    state = params.get("state")

    def fail(error: str, description: str):
        return None, with_query(redirect_uri, {"error": error, "error_description": description,
                                               "state": state, "iss": issuer()})

    if params.get("response_type") != "code":
        return fail("unsupported_response_type", "Only response_type=code is supported.")
    challenge = params.get("code_challenge") or ""
    if not challenge:
        return fail("invalid_request", "PKCE is required: send code_challenge with code_challenge_method=S256.")
    if params.get("code_challenge_method") != "S256":
        return fail("invalid_request", "code_challenge_method must be S256.")
    if not re.fullmatch(r"[A-Za-z0-9\-_]{43}", challenge):
        return fail("invalid_request", "code_challenge must be a base64url SHA-256 (43 characters).")
    try:
        scopes = parse_scopes(params.get("scope"))
        check_resource(params.get("resource"))
    except OAuthError as exc:
        return fail(exc.error, exc.description)

    handle = secrets.token_urlsafe(32)
    db.oauth_requests.insert_one({
        "_id": _hash(handle),
        "client_id": client["client_id"],
        "client_name": client["client_name"],
        "client_kind": client["kind"],
        "redirect_uri": redirect_uri,
        "state": state,
        "scopes": scopes,
        "code_challenge": challenge,
        "resource": resource(),
        "expires_at": _now() + REQUEST_TTL,
    })
    return handle, None


def _pending(db, handle: str) -> dict | None:
    if not handle or not isinstance(handle, str):
        return None
    doc = db.oauth_requests.find_one({"_id": _hash(handle)})
    if doc is None or _aware(doc["expires_at"]) <= _now():
        return None
    return doc


def describe_request(db, handle: str) -> dict | None:
    """What the consent page shows about a pending request (no secrets)."""
    doc = _pending(db, handle)
    if doc is None:
        return None
    host = redirect_host(doc["redirect_uri"])
    loopback = is_loopback(doc["redirect_uri"])
    return {
        "client_name": doc["client_name"],
        "client_kind": doc["client_kind"],
        # For a metadata-document client, the host that vouches for it.
        "client_host": redirect_host(doc["client_id"]) if doc["client_kind"] == "cimd" else None,
        "redirect_uri": doc["redirect_uri"],
        "redirect_host": host,
        "loopback": loopback,
        "hosted_claude": doc["redirect_uri"] == HOSTED_CLAUDE_REDIRECT,
        "scopes": doc["scopes"],
    }


def decide(db, handle: str, user: dict, approve: bool) -> str:
    """Consume a pending request and return where to send the browser."""
    doc = _pending(db, handle)
    if doc is None or db.oauth_requests.delete_one({"_id": doc["_id"]}).deleted_count != 1:
        raise OAuthError("invalid_request", "This sign-in request has expired or was already used. "
                                            "Start again from the app you were connecting.")
    base = {"state": doc.get("state"), "iss": issuer()}
    if not approve:
        return with_query(doc["redirect_uri"], {"error": "access_denied",
                                                "error_description": "The user declined access.", **base})
    code = secrets.token_urlsafe(32)
    db.oauth_codes.insert_one({
        "_id": _hash(code),
        "client_id": doc["client_id"],
        "client_name": doc["client_name"],
        "redirect_uri": doc["redirect_uri"],
        "uid": user["uid"],
        "scopes": doc["scopes"],
        "code_challenge": doc["code_challenge"],
        "resource": doc["resource"],
        "family_id": uuid.uuid4().hex,
        "used": False,
        "expires_at": _now() + CODE_TTL,
    })
    return with_query(doc["redirect_uri"], {"code": code, **base})


# ---- Tokens -------------------------------------------------------------------------------

def _pkce_ok(verifier: str | None, challenge: str) -> bool:
    if not verifier or not _PKCE_RE.match(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, challenge)


def _issue(db, *, family_id: str, uid: str, client_id: str, client_name: str, scopes: list[str],
           res: str, grant_created_at: datetime) -> dict:
    now = _now()
    access = ACCESS_PREFIX + secrets.token_urlsafe(32)
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    db.oauth_tokens.insert_one({
        "_id": uuid.uuid4().hex,
        "family_id": family_id,
        "uid": uid,
        "client_id": client_id,
        "client_name": client_name,
        "scopes": scopes,
        "resource": res,
        "access_hash": _hash(access),
        "access_expires_at": now + ACCESS_TOKEN_TTL,
        "refresh_hash": _hash(refresh),
        "refresh_expires_at": now + REFRESH_TOKEN_TTL,
        "grant_created_at": grant_created_at,
        "created_at": now,
        "last_used_at": None,
        "rotated": False,
        "revoked": False,
    })
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": " ".join(scopes),
    }


def _revoke_family(db, family_id: str) -> None:
    db.oauth_tokens.update_many({"family_id": family_id}, {"$set": {"revoked": True}})


def exchange_code(db, client: dict, form: dict) -> dict:
    code = form.get("code") or ""
    if not code:
        raise OAuthError("invalid_request", "code is required.")
    check_resource(form.get("resource"))
    # Atomically claim the code: a second redemption finds used=True.
    doc = db.oauth_codes.find_one_and_update({"_id": _hash(code), "used": False}, {"$set": {"used": True}})
    if doc is None:
        replay = db.oauth_codes.find_one({"_id": _hash(code)})
        if replay is not None:
            # A replayed code: revoke whatever it was exchanged for (OAuth 2.1 §4.1.3).
            _revoke_family(db, replay["family_id"])
        raise OAuthError("invalid_grant", "The authorization code is invalid, expired or already used.")
    if _aware(doc["expires_at"]) <= _now():
        raise OAuthError("invalid_grant", "The authorization code has expired.")
    if doc["client_id"] != client["client_id"]:
        raise OAuthError("invalid_grant", "The authorization code was issued to another client.")
    redirect_uri = form.get("redirect_uri")
    if redirect_uri is not None and redirect_uri != doc["redirect_uri"]:
        raise OAuthError("invalid_grant", "redirect_uri doesn't match the authorization request.")
    if not _pkce_ok(form.get("code_verifier"), doc["code_challenge"]):
        raise OAuthError("invalid_grant", "PKCE verification failed (code_verifier).")
    if client.get("kind") == "dcr":
        db.oauth_clients.update_one({"_id": client["client_id"]}, {"$unset": {"expires_at": ""}})
    return _issue(db, family_id=doc["family_id"], uid=doc["uid"], client_id=doc["client_id"],
                  client_name=doc["client_name"], scopes=doc["scopes"], res=doc["resource"],
                  grant_created_at=_now())


def refresh(db, client: dict, form: dict) -> dict:
    raw = form.get("refresh_token") or ""
    if not raw:
        raise OAuthError("invalid_request", "refresh_token is required.")
    check_resource(form.get("resource"))
    doc = db.oauth_tokens.find_one({"refresh_hash": _hash(raw)})
    if doc is None or doc.get("revoked"):
        raise OAuthError("invalid_grant", "The refresh token is invalid or has been revoked.")
    if doc["client_id"] != client["client_id"]:
        raise OAuthError("invalid_grant", "The refresh token was issued to another client.")
    if _aware(doc["refresh_expires_at"]) <= _now():
        raise OAuthError("invalid_grant", "The refresh token has expired — sign in again.")
    requested = (form.get("scope") or "").split()
    if any(s not in doc["scopes"] for s in requested):
        raise OAuthError("invalid_scope", "A refresh can't widen the granted scopes.")
    # Rotate: claim this refresh token exactly once. A replay of an already-
    # rotated token means it leaked — revoke the grant (OAuth 2.1 §4.3.1) —
    # EXCEPT within a short grace window: Claude refreshes both proactively and
    # on a 401, and a retried or concurrent refresh (a lost response, two
    # requests in flight) must not disconnect the user. Inside the window the
    # replay gets back the SAME pair the rotation issued (idempotent), never a
    # new one. The successor pair is minted first and recorded on the rotated
    # token, sealed under a key only the presented refresh token derives, in
    # the same atomic update that claims the rotation — so a concurrent replay
    # always finds it, and the database never holds a usable token in clear.
    issue = dict(family_id=doc["family_id"], uid=doc["uid"], client_id=doc["client_id"],
                 client_name=doc["client_name"], scopes=doc["scopes"], res=doc["resource"],
                 grant_created_at=_aware(doc.get("grant_created_at")) or _aware(doc["created_at"]))
    pair = _issue(db, **issue)
    claimed = db.oauth_tokens.find_one_and_update(
        {"_id": doc["_id"], "rotated": False, "revoked": False},
        {"$set": {"rotated": True, "rotated_at": _now(), "successor": _seal(raw, pair)}})
    if claimed is not None:
        return pair
    # Someone else rotated this token (or the grant was revoked meanwhile):
    # the pair just minted is never handed out.
    db.oauth_tokens.delete_one({"access_hash": _hash(pair["access_token"])})
    current = db.oauth_tokens.find_one({"_id": doc["_id"]}) or {}
    rotated_at = _aware(current.get("rotated_at"))
    if (not current.get("revoked") and rotated_at is not None
            and _now() - rotated_at <= REFRESH_REUSE_GRACE):
        previous = _unseal(raw, current.get("successor"))
        if previous is not None:
            logger.info("OAuth refresh-token reuse for grant %s within grace window — same pair returned",
                        doc["family_id"])
            return previous
        if not current.get("successor"):
            # Rotated before successor pairs were recorded: the earlier reissue.
            logger.info("OAuth refresh-token reuse for grant %s within grace window — reissuing",
                        doc["family_id"])
            return _issue(db, **issue)
    _revoke_family(db, doc["family_id"])
    logger.warning("OAuth refresh-token reuse for grant %s — grant revoked", doc["family_id"])
    raise OAuthError("invalid_grant",
                     "The refresh token was already used; the grant has been revoked.")


def _successor_key(raw_refresh: str) -> bytes:
    """The key sealing a rotation's successor pair: derived from the rotated
    refresh token itself (distinct from its stored hash), so only a caller
    presenting that token can open it."""
    return hashlib.sha256(b"reliafy-oauth-successor|" + raw_refresh.encode()).digest()


def _seal(raw_refresh: str, pair: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(12)
    sealed = AESGCM(_successor_key(raw_refresh)).encrypt(nonce, json.dumps(pair).encode(), b"successor")
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def _unseal(raw_refresh: str, blob) -> dict | None:
    if not isinstance(blob, str) or not blob:
        return None
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        data = base64.urlsafe_b64decode(blob.encode())
        plain = AESGCM(_successor_key(raw_refresh)).decrypt(data[:12], data[12:], b"successor")
        return json.loads(plain)
    except (InvalidTag, ValueError):
        return None


def revoke_token(db, client: dict, raw: str) -> None:
    """RFC 7009: revoke the grant a token belongs to (unknown tokens are fine)."""
    if not raw:
        return
    doc = db.oauth_tokens.find_one({"$or": [{"access_hash": _hash(raw)}, {"refresh_hash": _hash(raw)}]})
    if doc is not None and doc["client_id"] == client["client_id"]:
        _revoke_family(db, doc["family_id"])


# ---- Resource side --------------------------------------------------------------------------

_LAST_USED_EVERY = timedelta(minutes=1)


def verify_access_token(db, raw: str) -> dict | None:
    """The user an OAuth access token acts for, or None (unknown, expired,
    revoked, or issued for a different resource)."""
    if not raw or not raw.startswith(ACCESS_PREFIX):
        return None
    doc = db.oauth_tokens.find_one({"access_hash": _hash(raw)})
    if doc is None or doc.get("revoked"):
        return None
    now = _now()
    if _aware(doc["access_expires_at"]) <= now:
        return None
    if _canonical(doc.get("resource") or "") != _canonical(resource()):
        return None  # audience check: only tokens minted for this MCP URL
    last = _aware(doc.get("last_used_at"))
    if last is None or now - last > _LAST_USED_EVERY:
        db.oauth_tokens.update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": now}})
    user = db.users.find_one({"_id": doc["uid"]}) or {}
    return {
        "uid": doc["uid"],
        "email": user.get("email"),
        "name": user.get("name"),
        "email_verified": email_trust.profile_flag(db, doc["uid"], user),
        "via_oauth": doc["family_id"],
        "oauth_client": doc["client_name"],
    }


# ---- Settings: connected apps --------------------------------------------------------------

def list_grants(db, uid: str) -> list[dict]:
    """Active grants (one per client connection), newest first."""
    now = _now()
    grants: dict[str, dict] = {}
    for doc in db.oauth_tokens.find({"uid": uid, "revoked": False}):
        if _aware(doc["refresh_expires_at"]) <= now and _aware(doc["access_expires_at"]) <= now:
            continue
        g = grants.setdefault(doc["family_id"], {
            "id": doc["family_id"],
            "client_name": doc["client_name"],
            "client_id": doc["client_id"],
            "created_at": _aware(doc.get("grant_created_at")) or _aware(doc["created_at"]),
            "last_used_at": None,
            "live": False,
        })
        used = _aware(doc.get("last_used_at"))
        if used and (g["last_used_at"] is None or used > g["last_used_at"]):
            g["last_used_at"] = used
        if not doc.get("rotated") and _aware(doc["refresh_expires_at"]) > now:
            g["live"] = True
    out = []
    for g in grants.values():
        if not g.pop("live"):
            continue  # only rotated-away pairs left: nothing usable remains
        host = redirect_host(g["client_id"]) if is_cimd_client_id(g["client_id"]) else None
        out.append({
            "id": g["id"],
            "client_name": g["client_name"],
            "client_host": host,
            "created_at": g["created_at"].isoformat() if g["created_at"] else None,
            "last_used_at": g["last_used_at"].isoformat() if g["last_used_at"] else None,
        })
    out.sort(key=lambda g: g["created_at"] or "", reverse=True)
    return out


def revoke_grant(db, uid: str, grant_id: str) -> bool:
    return db.oauth_tokens.update_many(
        {"uid": uid, "family_id": grant_id, "revoked": False}, {"$set": {"revoked": True}}
    ).modified_count > 0
