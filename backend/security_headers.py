"""Security response headers, added to every HTTP response that doesn't
already set them (a route's own value always wins).

The Content-Security-Policy is sent REPORT-ONLY for now: browsers report what
it would block to ``/api/csp-report`` (logged) without blocking anything, so
the policy can be checked against real traffic before it is enforced. Only
``frame-ancestors 'none'`` is enforced from the start (alongside
``X-Frame-Options: DENY``): nothing frames the app.

What the policy allows, and why:

* scripts: our own bundle, plus ``apis.google.com`` (Firebase Auth loads the
  Google API loader for its sign-in popup).
* styles: our own CSS, Google Fonts' stylesheet, and inline styles (React and
  Plotly set ``style`` attributes).
* fonts: Google Fonts (``fonts.gstatic.com``).
* images: our own, ``data:``/``blob:`` (Plotly's PNG export, generated
  images), and any ``https:`` source (Google profile photos; markdown images).
* connections: our own API, the Firebase Auth / Secure Token REST endpoints,
  and ``CSP_CONNECT_EXTRA`` (the cross-origin SSE stream host).
* frames: the Firebase auth domain's sign-in iframe (``CSP_FRAME_EXTRA``).
* workers: ``blob:`` (libraries that spin up inline workers).
* forms post only to ourselves; no plugins; ``<base>`` pinned to ourselves.

Stripe Checkout and the OAuth consent redirect are top-level navigations,
which the policy doesn't restrict.
"""

from __future__ import annotations

from backend import config

CSP_REPORT_PATH = "/api/csp-report"


def content_security_policy() -> str:
    connect = ["'self'", "https://identitytoolkit.googleapis.com",
               "https://securetoken.googleapis.com", "https://www.googleapis.com",
               "https://apis.google.com", *config.CSP_CONNECT_EXTRA]
    frames = ["'self'", "https://accounts.google.com", "https://apis.google.com",
              *config.CSP_FRAME_EXTRA]
    directives = {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://apis.google.com"],
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
        "img-src": ["'self'", "data:", "blob:", "https:"],
        "connect-src": connect,
        "frame-src": frames,
        "worker-src": ["'self'", "blob:"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
        "report-uri": [CSP_REPORT_PATH],
    }
    return "; ".join(f"{k} {' '.join(dict.fromkeys(v))}" for k, v in directives.items())


HSTS = "max-age=31536000; includeSubDomains"


def _is_https(scope) -> bool:
    if scope.get("scheme") == "https":
        return True
    for name, value in scope.get("headers") or ():
        if name == b"x-forwarded-proto":
            return value.split(b",")[0].strip().lower() == b"https"
    return False


class SecurityHeadersMiddleware:
    """Pure ASGI: adds headers on ``http.response.start``; never touches bodies."""

    def __init__(self, app):
        self.app = app
        self._csp = content_security_policy().encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        defaults = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"content-security-policy", b"frame-ancestors 'none'"),
            (b"content-security-policy-report-only", self._csp),
        ]
        if _is_https(scope):
            defaults.append((b"strict-transport-security", HSTS.encode()))

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in defaults if k not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
