"""OAuth 2.1 endpoints that let Claude (claude.ai, Desktop, mobile, Claude
Code) connect to the MCP server at ``/mcp`` on a user's behalf.

Discovery:
  GET  /.well-known/oauth-protected-resource[/mcp]   RFC 9728
  GET  /.well-known/oauth-authorization-server       RFC 8414
Flow:
  POST /oauth/register              RFC 7591 dynamic client registration (JSON)
  GET  /oauth/authorize             validate, then hand off to the consent page
  GET  /oauth/consent               the consent page (SPA shell, noindex, no framing)
  GET  /oauth/authorize/request     what the consent page shows (by opaque handle)
  POST /oauth/authorize/decision    approve / deny, as the signed-in Firebase user
  POST /oauth/token                 authorization_code + refresh_token (form-encoded)
  POST /oauth/revoke                RFC 7009
Settings:
  GET    /api/me/oauth-grants       connected apps
  DELETE /api/me/oauth-grants/{id}  disconnect one

The protocol logic lives in :mod:`backend.services.oauth`.
"""

from __future__ import annotations

import base64
import html
import logging
from pathlib import Path
from urllib.parse import unquote_plus

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from backend.auth import get_current_user, upsert_user
from backend.db import get_session
from backend.services import oauth as oauth_service
from backend.services.oauth import OAuthError

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"


def _oauth_error(exc: OAuthError) -> JSONResponse:
    headers = dict(_NO_STORE)
    if exc.status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="reliafy-oauth"'
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


# ---- Discovery -------------------------------------------------------------------

@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata() -> JSONResponse:
    return JSONResponse(oauth_service.protected_resource_metadata(),
                        headers={"Cache-Control": "public, max-age=300"})


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata() -> JSONResponse:
    return JSONResponse(oauth_service.authorization_server_metadata(),
                        headers={"Cache-Control": "public, max-age=300"})


# ---- Registration ------------------------------------------------------------------

# Dynamic client registrations allowed per client IP per window. A connector
# registers once per install; this only stops floods of throwaway clients.
REGISTER_WINDOW_SECONDS = 3600
REGISTER_PER_IP = 20


@router.post("/oauth/register")
async def register(request: Request, db=Depends(get_session)) -> JSONResponse:
    from backend.request_ip import client_ip as _client_ip
    from backend.services import rate_limit

    key = rate_limit.ip_key("oauth-register", _client_ip(request))
    allowed = await run_in_threadpool(rate_limit.consume, db, key, REGISTER_PER_IP, REGISTER_WINDOW_SECONDS)
    if not allowed:
        return JSONResponse(
            {"error": "slow_down", "error_description": "Too many client registrations — try again later."},
            status_code=429,
            headers={**_NO_STORE, "Retry-After": str(rate_limit.retry_after(REGISTER_WINDOW_SECONDS))},
        )
    body = await request.body()
    if len(body) > 16 * 1024:
        return _oauth_error(OAuthError("invalid_client_metadata", "Registration request too large."))
    try:
        import json

        meta = json.loads(body or b"{}")
    except ValueError:
        return _oauth_error(OAuthError("invalid_client_metadata", "The body must be JSON."))
    try:
        out = await run_in_threadpool(oauth_service.register_client, db, meta)
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(out, status_code=201, headers=_NO_STORE)


# ---- Authorization -------------------------------------------------------------------

def _error_page(message: str, status: int = 400) -> HTMLResponse:
    body = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="robots" content="noindex"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Can't connect — Reliafy</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#1f2937}}
h1{{font-size:1.3rem}}code{{background:#f3f4f6;padding:0 .25rem;border-radius:4px}}</style></head>
<body><h1>This connection request can't be completed</h1><p>{html.escape(message)}</p>
<p>Go back to the app you were connecting and try again. If it keeps happening, email
<code>hello@reliafy.com</code>.</p><p><a href="/">Reliafy</a></p></body></html>"""
    return HTMLResponse(body, status_code=status,
                        headers={**_NO_STORE, "X-Robots-Tag": "noindex", "X-Frame-Options": "DENY"})


@router.get("/oauth/authorize")
def authorize(request: Request, db=Depends(get_session)):
    """Validate the request, park it server-side and send the browser to the
    consent page with an opaque handle. Nothing from the query string is
    trusted after this point: the decision endpoint reads the parked copy."""
    params = dict(request.query_params)
    try:
        handle, error_redirect = oauth_service.start_authorization(db, params)
    except OAuthError as exc:
        # Unknown client / unregistered redirect: never redirect (RFC 6749 §4.1.2.1).
        return _error_page(exc.description or exc.error)
    if error_redirect:
        return RedirectResponse(error_redirect, status_code=302, headers=_NO_STORE)
    return RedirectResponse(f"/oauth/consent?request={handle}", status_code=302, headers=_NO_STORE)


@router.get("/oauth/consent")
def consent_page():
    """The SPA shell for the consent screen, with headers the catch-all lacks:
    never indexed, never framed (clickjacking), never cached."""
    headers = {**_NO_STORE, "X-Robots-Tag": "noindex, nofollow", "X-Frame-Options": "DENY",
               "Content-Security-Policy": "frame-ancestors 'none'", "Referrer-Policy": "no-referrer"}
    if not _FRONTEND_INDEX.is_file():  # pragma: no cover - frontend not built
        return JSONResponse({"detail": "Frontend not built."}, status_code=503, headers=headers)
    return FileResponse(_FRONTEND_INDEX, headers=headers)


@router.get("/oauth/authorize/request")
def authorization_request(request: str = "", db=Depends(get_session)) -> JSONResponse:
    info = oauth_service.describe_request(db, request)
    if info is None:
        return JSONResponse({"detail": "This sign-in request has expired or was already used. "
                                       "Start again from the app you were connecting."},
                            status_code=404, headers=_NO_STORE)
    return JSONResponse(info, headers=_NO_STORE)


@router.post("/oauth/authorize/decision")
def authorization_decision(
    request: str = Body(..., embed=True),
    approve: bool = Body(..., embed=True),
    user: dict = Depends(get_current_user),
    db=Depends(get_session),
) -> JSONResponse:
    upsert_user(db, user)
    try:
        redirect_to = oauth_service.decide(db, request, user, approve)
    except OAuthError as exc:
        return JSONResponse({"detail": exc.description}, status_code=400, headers=_NO_STORE)
    return JSONResponse({"redirect_to": redirect_to}, headers=_NO_STORE)


# ---- Token & revocation ----------------------------------------------------------------

async def _form(request: Request) -> dict:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/x-www-form-urlencoded":
        raise OAuthError("invalid_request", "Send the token request as application/x-www-form-urlencoded.")
    form = await request.form()
    return {k: v for k, v in form.items() if isinstance(v, str)}


def _client_credentials(request: Request, form: dict) -> tuple[str | None, str | None]:
    """client_id/secret from HTTP Basic (RFC 6749 §2.3.1) or the form body."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:].strip()).decode()
            cid, _, secret = decoded.partition(":")
            return unquote_plus(cid), unquote_plus(secret)
        except (ValueError, UnicodeDecodeError):
            raise OAuthError("invalid_client", "Malformed Basic authorization header.", 401)
    return form.get("client_id"), form.get("client_secret")


@router.post("/oauth/token")
async def token(request: Request, db=Depends(get_session)) -> JSONResponse:
    try:
        form = await _form(request)
        client_id, secret = _client_credentials(request, form)
        if form.get("client_id") and client_id != form["client_id"]:
            raise OAuthError("invalid_request", "client_id in the body and the Authorization header differ.")
        grant = form.get("grant_type")
        if grant not in ("authorization_code", "refresh_token"):
            raise OAuthError("unsupported_grant_type", "grant_type must be authorization_code or refresh_token.")

        def run():
            client = oauth_service.authenticate_client(db, client_id, secret)
            if grant == "authorization_code":
                return oauth_service.exchange_code(db, client, form)
            return oauth_service.refresh(db, client, form)

        out = await run_in_threadpool(run)
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(out, headers=_NO_STORE)


@router.post("/oauth/revoke")
async def revoke(request: Request, db=Depends(get_session)) -> JSONResponse:
    try:
        form = await _form(request)
        client_id, secret = _client_credentials(request, form)

        def run():
            client = oauth_service.authenticate_client(db, client_id, secret)
            oauth_service.revoke_token(db, client, form.get("token") or "")

        await run_in_threadpool(run)
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse({}, headers=_NO_STORE)


# ---- Settings: connected apps ------------------------------------------------------------

@router.get("/api/me/oauth-grants")
def list_grants(user: dict = Depends(get_current_user), db=Depends(get_session)) -> dict:
    return {"grants": oauth_service.list_grants(db, user["uid"])}


@router.delete("/api/me/oauth-grants/{grant_id}")
def revoke_grant(grant_id: str, user: dict = Depends(get_current_user), db=Depends(get_session)):
    if not oauth_service.revoke_grant(db, user["uid"], grant_id):
        return JSONResponse({"detail": "Connected app not found."}, status_code=404)
    return {"revoked": True}


# ---- CORS for the machine-facing endpoints ---------------------------------------------

_CORS_PATHS = (
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/oauth/token",
    "/oauth/register",
    "/oauth/revoke",
)


class OAuthCorsMiddleware:
    """Open CORS (``*``, no credentials) on the discovery, registration, token
    and revocation endpoints only, so browser-based MCP clients (e.g. the MCP
    Inspector) can complete the flow. The app-wide CORS policy stays as is for
    everything else. None of these endpoints use cookies, so ``*`` exposes
    nothing a direct request couldn't already get."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(_CORS_PATHS):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            await JSONResponse({}, headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type, MCP-Protocol-Version",
                "Access-Control-Max-Age": "3600",
            })(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if k.lower() != b"access-control-allow-origin"]
                headers.append((b"access-control-allow-origin", b"*"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cors)
