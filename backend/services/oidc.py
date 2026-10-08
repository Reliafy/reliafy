"""Google-signed OIDC tokens on private internal endpoints.

Cloud Scheduler (and Cloud Tasks) can call a URL with an ``Authorization:
Bearer`` ID token minted for a service account. An internal endpoint accepts
a call only when that token is Google-signed, issued for the endpoint's own
URL (the audience), and belongs to the one service account allowed to call
it. Same check as the compute callback (``compute_queue.verify_callback``).
"""

from __future__ import annotations


class Rejected(Exception):
    """The call isn't from the allowed service account."""


def _verify_token(token: str, audience: str) -> dict:
    from google.oauth2 import id_token

    from backend.services.compute_queue import _google_request

    return id_token.verify_oauth2_token(token, _google_request(), audience=audience)


def verify(authorization: str | None, *, audience: str | None,
           service_account: str | None) -> dict:
    """The token's claims, or :class:`Rejected`. Unconfigured (no audience
    or no service account) rejects every call."""
    if not (audience and service_account):
        raise Rejected("Not configured.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Rejected("Missing bearer token.")
    try:
        claims = _verify_token(token.strip(), audience)
    except Exception as exc:  # noqa: BLE001 - any verification failure
        raise Rejected("Invalid token.") from exc
    claims = claims or {}
    if claims.get("email") != service_account or not claims.get("email_verified", False):
        raise Rejected("Token is not the allowed service account's.")
    return claims
