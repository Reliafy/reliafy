"""The queue between the web app and the compute service (#146).

The web app pushes one Cloud Tasks HTTP task per job to the compute service's
``POST /compute/run``. Cloud Tasks attaches an OIDC token for the compute URL,
signed as ``COMPUTE_INVOKER_SA`` (the web service's account, which holds
``run.invoker`` on the private compute service), and retries the task until
the compute service answers 2xx. The compute service reports back to
``POST /internal/compute/callback`` with an ID token of its own account,
verified here.

Talks to the Cloud Tasks REST API with google-auth's ``AuthorizedSession``
(no google-cloud-tasks client). With ``COMPUTE_QUEUE`` unset nothing here is
used: jobs run in-process (see :mod:`backend.services.rbd_jobs`).
"""

from __future__ import annotations

import base64
import json
import logging
import threading

from backend import config

logger = logging.getLogger(__name__)

TASKS_API = "https://cloudtasks.googleapis.com/v2"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# Cloud Tasks caps a task at 1 MB; keep the body comfortably under it.
MAX_BODY_BYTES = 900_000


class QueueError(RuntimeError):
    """The job couldn't be queued."""


class CallbackRejected(PermissionError):
    """A callback without a valid ID token of the compute service."""


def configured() -> bool:
    """Whether heavy jobs go through the queue (else they run in-process)."""
    return bool(config.COMPUTE_QUEUE)


def missing_settings() -> list[str]:
    names = ("COMPUTE_URL", "COMPUTE_QUEUE", "COMPUTE_CALLBACK_URL", "COMPUTE_INVOKER_SA", "COMPUTE_SA")
    return [n for n in names if not getattr(config, n, None)]


_session = None
_session_lock = threading.Lock()


def _authorized_session():
    """An AuthorizedSession on the service's own credentials (cached)."""
    global _session
    with _session_lock:
        if _session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=_SCOPES)
            _session = AuthorizedSession(credentials)
        return _session


def task_body(job_id: str, kind: str, request: dict) -> dict:
    """The Cloud Tasks ``tasks.create`` body for one job. The task is named
    after the job, so enqueueing a job twice creates one task."""
    payload = json.dumps({
        "job_id": job_id,
        "kind": kind,
        "request": request,
        "callback_url": config.COMPUTE_CALLBACK_URL,
    }, separators=(",", ":"), default=float).encode("utf-8")
    if len(payload) > MAX_BODY_BYTES:
        raise QueueError("This diagram is too large to send to the calculation service.")
    return {
        "task": {
            "name": f"{config.COMPUTE_QUEUE}/tasks/{job_id}",
            "dispatchDeadline": f"{int(config.COMPUTE_DISPATCH_DEADLINE_S)}s",
            "httpRequest": {
                "httpMethod": "POST",
                "url": f"{config.COMPUTE_URL}/compute/run",
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(payload).decode("ascii"),
                "oidcToken": {
                    "serviceAccountEmail": config.COMPUTE_INVOKER_SA,
                    "audience": config.COMPUTE_URL,
                },
            },
        }
    }


def enqueue(job_id: str, kind: str, request: dict) -> bool:
    """Create the job's task. True if created, False if a task of that name
    already exists (a double enqueue — nothing to do). Raises
    :class:`QueueError` otherwise."""
    missing = missing_settings()
    if missing:
        logger.error("Compute queue is half-configured; missing %s", ", ".join(missing))
        raise QueueError("The calculation service isn't configured.")
    body = task_body(job_id, kind, request)
    try:
        r = _authorized_session().post(f"{TASKS_API}/{config.COMPUTE_QUEUE}/tasks", json=body, timeout=15)
    except Exception as exc:  # noqa: BLE001 - network / credentials
        logger.warning("Enqueue of job %s failed: %s", job_id, exc)
        raise QueueError("Couldn't reach the calculation queue.") from exc
    if r.status_code == 409:  # ALREADY_EXISTS: this job's task is queued already
        return False
    if not 200 <= r.status_code < 300:
        logger.warning("Enqueue of job %s answered %s: %s", job_id, r.status_code, r.text[:500])
        raise QueueError("Couldn't queue the calculation.")
    return True


# ---- Callback authentication ------------------------------------------------

_certs_request = None


def _google_request():
    """A transport request whose fetches of Google's signing certs are cached
    (per their Cache-Control)."""
    global _certs_request
    if _certs_request is None:
        import google.auth.transport.requests
        import requests

        try:
            import cachecontrol

            session = cachecontrol.CacheControl(requests.Session())
        except Exception:  # noqa: BLE001 - uncached still works
            session = requests.Session()
        _certs_request = google.auth.transport.requests.Request(session=session)
    return _certs_request


def _verify_token(token: str, audience: str) -> dict:
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, _google_request(), audience=audience)


def verify_callback(authorization: str | None) -> dict:
    """The claims of a callback's ``Authorization: Bearer`` ID token, which
    must be Google-signed, for the callback URL, and of the compute service's
    account (``COMPUTE_SA``). Raises :class:`CallbackRejected` otherwise."""
    if not (config.COMPUTE_CALLBACK_URL and config.COMPUTE_SA):
        raise CallbackRejected("Callbacks aren't configured.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise CallbackRejected("Missing bearer token.")
    try:
        claims = _verify_token(token.strip(), config.COMPUTE_CALLBACK_URL)
    except Exception as exc:  # noqa: BLE001 - any verification failure
        raise CallbackRejected("Invalid token.") from exc
    email = (claims or {}).get("email")
    if email != config.COMPUTE_SA or not claims.get("email_verified", False):
        raise CallbackRejected("Token is not the compute service's.")
    return claims
