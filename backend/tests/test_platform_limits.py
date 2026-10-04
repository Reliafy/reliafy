"""Platform-level request handling: body and CSV limits, sync fit handlers,
calculator access, response headers, the client address, log redaction,
telemetry checks, generic error messages and the single-user-mode startup check."""

import matplotlib

matplotlib.use("Agg")

import inspect
import io
import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.tests.test_public_links import A, B, client  # noqa: F401 - fixture

REPO = Path(__file__).resolve().parents[2]


def _csv(n=40) -> bytes:
    rng = np.random.default_rng(5)
    return pd.DataFrame({"t": np.round(rng.weibull(2.0, n) * 100, 2)}).to_csv(index=False).encode()


def _fit(client, data=None):
    return client.post("/api/fit/weibull", data={"x": "t"},
                       files={"file": ("d.csv", data or _csv(), "text/csv")})


# ---- fit handlers run in the threadpool ------------------------------------------------

@pytest.mark.parametrize("module, name", [
    ("backend.main", "fit_endpoint"), ("backend.main", "columns_endpoint"),
    ("backend.routers.models", "upload_dataset"), ("backend.routers.models", "save_model"),
    ("backend.routers.alt", "fit_preview"), ("backend.routers.alt", "save_model"),
    ("backend.routers.degradation", "fit_preview"), ("backend.routers.degradation", "save_model"),
    ("backend.routers.recurrent", "fit_preview"), ("backend.routers.recurrent", "save_model"),
])
def test_fit_and_upload_handlers_are_sync(module, name):
    import importlib

    handler = getattr(importlib.import_module(module), name)
    assert callable(handler) and not inspect.iscoroutinefunction(handler)


def test_model_import_runs_off_the_event_loop():
    src = inspect.getsource(__import__("backend.routers.ingest", fromlist=["x"]).import_model)
    assert "run_in_threadpool" in src


# ---- request-body caps ------------------------------------------------------------------

def test_declared_oversize_body_gets_413(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 4096)
    client.act_as(A)
    big = b"t\n" + b"1.5\n" * 200_000  # ~800 KB, over the 4 KB + form allowance
    r = _fit(client, big)
    assert r.status_code == 413
    assert "too large" in r.json()["detail"]


def test_streamed_oversize_body_gets_413(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_REQUEST_BYTES", 10_000)
    client.act_as(A)

    def chunks():
        for _ in range(50):
            yield b'{"content": "' + b"x" * 1000 + b'"}'

    # No Content-Length: the body is counted as it arrives.
    r = client.post("/api/datasets/paste", content=chunks(),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_file_over_csv_limit_gets_413(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 4096)
    client.act_as(A)
    r = _fit(client, b"t\n" + b"1.5\n" * 2000)  # ~8 KB: inside the form allowance
    assert r.status_code == 413
    assert "too large" in r.json()["detail"]
    # Under the limit still fits.
    assert _fit(client).status_code == 200


def test_body_limits_per_route(monkeypatch):
    from backend import config
    from backend.http_limits import body_limit
    from backend.services import excel

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1000)
    monkeypatch.setattr(config, "MAX_REQUEST_BYTES", 5_000_000)
    assert body_limit("/api/fit/weibull") < 300_000
    assert body_limit("/api/columns") == body_limit("/api/alt/fit") == body_limit("/api/fit/weibull")
    assert body_limit("/api/rbds") == 5_000_000
    assert body_limit("/api/excel/inspect") > excel.MAX_FILE_BYTES
    assert body_limit("/api/datasets") > excel.MAX_FILE_BYTES


def test_wide_csv_is_refused_with_a_clear_error(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_CSV_COLS", 20)
    client.act_as(A)
    wide = (",".join(f"c{i}" for i in range(50)) + "\n" + ",".join("1" for _ in range(50)) + "\n").encode()
    r = client.post("/api/columns", files={"file": ("w.csv", wide, "text/csv")})
    assert r.status_code == 422
    assert "50 columns" in r.json()["detail"] and "20" in r.json()["detail"]
    r = client.post("/api/datasets", files={"file": ("w.csv", wide, "text/csv")})
    assert r.status_code == 422 and "columns" in r.json()["detail"]


def test_long_csv_is_refused_with_a_clear_error(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_CSV_ROWS", 100)
    client.act_as(A)
    r = _fit(client, _csv(150))
    assert r.status_code == 422
    assert "100 rows" in r.json()["detail"]
    assert _fit(client, _csv(100)).status_code == 200


def test_pasted_and_ingested_csv_shape_limits(client, monkeypatch):
    from backend import config
    from backend.services import ingest
    from backend.fitting import FitError
    from backend.services.datasets import normalize_pasted

    monkeypatch.setattr(config, "MAX_CSV_COLS", 10)
    wide = ",".join(f"c{i}" for i in range(30)) + "\n" + ",".join("1" for _ in range(30))
    with pytest.raises(FitError, match="30 columns"):
        normalize_pasted(wide)
    with pytest.raises(ingest.IngestError, match="30 columns"):
        ingest.dataframe_from_request("text/csv", wide.encode())


def test_no_header_dataset_checks_size_first(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    client.act_as(A)
    big = b"1.0\n" * 2000
    r = client.post("/api/datasets", data={"no_header": "true"},
                    files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 422 and "too large" in r.json()["detail"]


# ---- calculator endpoints ---------------------------------------------------------------

def test_calculator_endpoints_need_the_fitting_account(client):
    client.act_as(A)
    fns = _fit(client).json()["functions"]
    evaluate_path, confidence_path = fns["evaluate_path"], fns["confidence_path"]

    assert client.post(evaluate_path, json={}).status_code == 200
    assert client.post(confidence_path, json={"on": "sf"}).status_code == 200

    client.act_as(B)
    assert client.post(evaluate_path, json={}).status_code == 404
    assert client.post(confidence_path, json={"on": "sf"}).status_code == 404

    client.act_as(None)
    assert client.post(evaluate_path, json={}).status_code == 401
    assert client.post(confidence_path, json={"on": "sf"}).status_code == 401


def test_unbound_cache_entries_are_not_served(client):
    from backend import fitting

    client.act_as(A)
    model_id = _fit(client).json()["functions"]["model_id"]
    fitting._MODEL_STORE[model_id].pop("owner")
    assert client.post(f"/api/evaluate/{model_id}", json={}).status_code == 404


# ---- response headers -------------------------------------------------------------------

def test_security_headers_on_api_responses(client):
    r = client.get("/api/health")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert h["content-security-policy"] == "frame-ancestors 'none'"
    csp = h["content-security-policy-report-only"]
    for part in ("default-src 'self'", "https://fonts.googleapis.com", "https://fonts.gstatic.com",
                 "https://identitytoolkit.googleapis.com", "https://securetoken.googleapis.com",
                 "https://apis.google.com", "img-src 'self' data: blob:", "object-src 'none'",
                 "frame-ancestors 'none'", "report-uri /api/csp-report"):
        assert part in csp, part
    # HSTS only over HTTPS (Cloud Run reports the scheme in X-Forwarded-Proto).
    assert "strict-transport-security" not in h
    r = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_route_headers_take_precedence(client):
    r = client.get("/oauth/consent")
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_csp_reports_are_accepted_and_limited(client, monkeypatch):
    from backend.ratelimit import SlidingWindowLimiter
    from backend.routers import telemetry

    monkeypatch.setattr(telemetry, "_CSP_LIMIT", SlidingWindowLimiter(2))
    body = {"csp-report": {"violated-directive": "script-src", "blocked-uri": "https://x.example"}}
    for _ in range(2):
        r = client.post("/api/csp-report", json=body, headers={"Content-Type": "application/csp-report"})
        assert r.status_code == 204
    assert client.post("/api/csp-report", json=body).status_code == 429


# ---- single-user mode on Cloud Run -------------------------------------------------------

def _import_config(**env):
    clean = {k: v for k, v in os.environ.items() if k not in ("AUTH_DISABLED", "K_SERVICE")}
    return subprocess.run([sys.executable, "-c", "import backend.config"], cwd=REPO,
                          env={**clean, **env}, capture_output=True, text=True)


def test_single_user_mode_refused_on_cloud_run():
    r = _import_config(AUTH_DISABLED="true", K_SERVICE="reliafy")
    assert r.returncode != 0 and "AUTH_DISABLED" in r.stderr
    assert _import_config(AUTH_DISABLED="true").returncode == 0
    assert _import_config(K_SERVICE="reliafy").returncode == 0


# ---- client address -----------------------------------------------------------------------

def test_client_address_is_read_from_the_right(monkeypatch):
    from backend import config
    from backend.request_ip import from_forwarded_for

    monkeypatch.setattr(config, "TRUSTED_PROXY_CIDRS", [])
    # A client-supplied entry on the left is ignored.
    assert from_forwarded_for("1.2.3.4, 203.0.113.7") == "203.0.113.7"
    # Internal hops on the right are skipped.
    assert from_forwarded_for("203.0.113.7, 169.254.1.1") == "203.0.113.7"
    assert from_forwarded_for("9.9.9.9, 203.0.113.7, 10.0.0.2") == "203.0.113.7"
    # Configured proxy ranges are skipped too.
    monkeypatch.setattr(config, "TRUSTED_PROXY_CIDRS", ["198.51.100.0/24"])
    assert from_forwarded_for("1.2.3.4, 203.0.113.7, 198.51.100.20") == "203.0.113.7"
    # No header: the peer.
    assert from_forwarded_for("", "192.0.2.1") == "192.0.2.1"


def test_forwarded_header_can_be_ignored(client, monkeypatch):
    from backend import config
    from backend.request_ip import client_ip

    class Req:
        headers = {"x-forwarded-for": "203.0.113.7"}

        class client:
            host = "192.0.2.1"

    assert client_ip(Req) == "203.0.113.7"
    monkeypatch.setattr(config, "TRUST_X_FORWARDED_FOR", False)
    assert client_ip(Req) == "192.0.2.1"


def test_unlock_limit_keys_on_the_proxy_recorded_address(client, monkeypatch):
    from backend.services import public_links
    from backend.tests.test_share_links_protected import _protected_rbd

    monkeypatch.setattr(public_links, "IP_ATTEMPTS", 2)
    _, link = _protected_rbd(client)
    url = f"/api/public/{link['token']}/unlock"
    for i in range(2):
        r = client.post(url, json={"password": "wrong-guess"},
                        headers={"X-Forwarded-For": f"10.{i}.0.1, 203.0.113.50"})
        assert r.status_code == 401
    # Changing the client-supplied part doesn't reset the count.
    r = client.post(url, json={"password": link["passphrase"]},
                    headers={"X-Forwarded-For": "8.8.8.8, 203.0.113.50"})
    assert r.status_code == 429


# ---- access-log redaction ------------------------------------------------------------------

def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                             '%s - "%s %s HTTP/%s" %d', ("203.0.113.7:1", "GET", path, "1.1", 200), None)


@pytest.mark.parametrize("path, secret", [
    ("/api/public/AbCdEf123456", "AbCdEf123456"),
    ("/api/public/AbCdEf123456/export.py?unlock=sekrit.token", "sekrit.token"),
    ("/api/public/AbCdEf123456/unlock", "AbCdEf123456"),
    ("/p/AbCdEf123456", "AbCdEf123456"),
    ("/api/uploads/u1?t=tok123", "tok123"),
])
def test_link_tokens_are_redacted_from_access_log(path, secret):
    from backend.main import _RedactUploadTokens

    record = _access_record(path)
    assert _RedactUploadTokens().filter(record) is True
    line = record.getMessage()
    assert secret not in line and "[redacted]" in line


def test_other_paths_are_logged_unchanged():
    from backend.main import _RedactUploadTokens

    record = _access_record("/api/models/abc123?tab=plot")
    _RedactUploadTokens().filter(record)
    assert "/api/models/abc123?tab=plot" in record.getMessage()


# ---- telemetry ------------------------------------------------------------------------------

def test_unknown_event_names_are_not_stored(client):
    r = client.post("/api/metrics/event", json={"name": "anything-at-all", "path": "/"})
    assert r.status_code == 422
    assert client.db.metrics_events.count_documents({}) == 0
    assert client.post("/api/metrics/event", json={"name": "model_fit", "path": "/"}).status_code == 200
    assert client.db.metrics_events.count_documents({"name": "model_fit"}) == 1


def test_frontend_event_names_are_allowed():
    import re

    from backend.routers.telemetry import CLIENT_EVENTS

    src = (REPO / "frontend" / "src" / "api.js").read_text()
    names = set()
    for m in re.finditer(r"(?<!function )withEvent\(", src):
        depth, i = 1, m.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            i += 1
        names.add(re.findall(r'"([a-z_]+)"', src[m.end():i])[-1])
    names |= {"pageview", "activated"}
    assert names and names <= CLIENT_EVENTS, names - CLIENT_EVENTS


def test_telemetry_is_rate_limited_per_client(client, monkeypatch):
    from backend.ratelimit import SlidingWindowLimiter
    from backend.routers import telemetry

    monkeypatch.setattr(telemetry, "_ERROR_LIMIT", SlidingWindowLimiter(3))
    monkeypatch.setattr(telemetry, "_EVENT_LIMIT", SlidingWindowLimiter(3))
    one = {"X-Forwarded-For": "203.0.113.1"}
    other = {"X-Forwarded-For": "203.0.113.2"}
    for _ in range(3):
        assert client.post("/api/client-error", json={"message": "m"}, headers=one).status_code == 200
        assert client.post("/api/metrics/event", json={"name": "pageview"}, headers=one).status_code == 200
    assert client.post("/api/client-error", json={"message": "m"}, headers=one).status_code == 429
    assert client.post("/api/metrics/event", json={"name": "pageview"}, headers=one).status_code == 429
    assert client.post("/api/client-error", json={"message": "m"}, headers=other).status_code == 200


def test_telemetry_text_stays_on_one_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="reliafy.telemetry"):
        client.post("/api/client-error", json={"message": "a\r\nfake-entry", "path": "/x\n/y"})
        client.post("/api/metrics/event", json={"name": "pageview", "path": "/a\r\nb", "utm_source": "s\nt"})
    for rec in caplog.records:
        assert "\n" not in rec.getMessage() and "\r" not in rec.getMessage()
    doc = client.db.metrics_events.find_one({})
    assert doc["path"] == "/a\\r\\nb" and doc["utm_source"] == "s\\nt"


def test_share_tokens_are_redacted_from_telemetry(client, caplog):
    with caplog.at_level(logging.INFO, logger="reliafy.telemetry"):
        client.post("/api/metrics/event", json={"name": "pageview", "path": "/p/ShareTok123"})
        client.post("/api/client-error", json={
            "message": "failed https://reliafy.com/p/ShareTok123?unlock=UnlockTok9",
            "stack": "at /api/public/ShareTok123/export.py", "path": "/p/ShareTok123"})
    assert client.db.metrics_events.find_one({})["path"] == "/p/[redacted]"
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "ShareTok123" not in logged and "UnlockTok9" not in logged


# ---- error messages ----------------------------------------------------------------------------

def test_unexpected_fit_errors_return_a_generic_message(client, monkeypatch):
    import backend.main as main

    def boom(*a, **k):
        raise RuntimeError("internal detail /srv/path")

    monkeypatch.setattr(main, "fit", boom)
    client.act_as(A)
    r = _fit(client)
    assert r.status_code == 500
    assert "internal detail" not in r.text and "logged" in r.json()["detail"]


def test_fit_validation_errors_keep_their_message(client):
    client.act_as(A)
    r = client.post("/api/fit/weibull", data={"x": "missing"},
                    files={"file": ("d.csv", _csv(), "text/csv")})
    assert r.status_code == 422 and "missing" in r.json()["detail"]


def _broad_handlers_that_echo(source: str) -> list[int]:
    """Line numbers of ``except Exception`` (or bare/BaseException) handlers
    whose body formats the caught exception into a string. Handlers for
    specific error types (FitError, GraphError, ...) carry intentional
    user-facing messages and are not counted."""
    import ast

    def broad(t) -> bool:
        if t is None:
            return True
        if isinstance(t, ast.Tuple):
            return any(broad(e) for e in t.elts)
        return isinstance(t, ast.Name) and t.id in {"Exception", "BaseException"}

    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler) or not broad(node.type) or not node.name:
            continue
        for sub in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if isinstance(sub, ast.FormattedValue) and isinstance(sub.value, ast.Name) \
                    and sub.value.id == node.name:
                lines.append(sub.lineno)
            elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                    and sub.func.id in {"str", "repr"} and sub.args \
                    and isinstance(sub.args[0], ast.Name) and sub.args[0].id == node.name:
                lines.append(sub.lineno)
    return lines


def test_routers_do_not_echo_unexpected_exception_text():
    import re

    # Responses built from an f-string "detail" inside a broad handler.
    pattern = re.compile(r'"detail":\s*f"[^"]*\{exc\}')
    offenders = {}
    for p in [*(REPO / "backend" / "routers").glob("*.py"), REPO / "backend" / "main.py"]:
        text = p.read_text()
        hits = [n for n in _broad_handlers_that_echo(text)
                if pattern.search(text.splitlines()[n - 1])]
        if hits:
            offenders[p.name] = hits
    assert not offenders


def test_payment_and_ai_routes_keep_unexpected_exception_text_in_the_log():
    # Billing, the assistant and the Reliability Agent (router and the service
    # that drives its stream) return or stream fixed messages from broad
    # handlers, whatever the provider raised.
    paths = [REPO / "backend" / "routers" / f for f in ("billing.py", "assistant.py", "reliability_agent.py")]
    paths.append(REPO / "backend" / "services" / "reliability_agent.py")
    offenders = {p.name: hits for p in paths if (hits := _broad_handlers_that_echo(p.read_text()))}
    assert not offenders


def test_billing_portal_failure_returns_a_generic_message(client, monkeypatch):
    from backend.routers import billing as billing_router
    from backend.services import billing as billing_service

    class _Portal:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("provider detail cus_123 /v1/billing_portal")

    class _Stripe:
        billing_portal = type("bp", (), {"Session": _Portal})

    monkeypatch.setattr(billing_router, "_stripe", lambda: _Stripe)
    monkeypatch.setattr(billing_service, "account",
                        lambda session, uid: {"stripe_customer_id": "cus_123"})
    client.act_as(A)
    r = client.post("/api/billing/portal")
    assert r.status_code == 502
    assert "provider detail" not in r.text and "cus_123" not in r.text


def test_unexpected_alt_fit_errors_return_a_generic_message(client, monkeypatch):
    from backend import alt as alt_fit

    def boom(*a, **k):
        raise RuntimeError("internal detail /srv/path")

    monkeypatch.setattr(alt_fit, "fit", boom)
    client.act_as(A)
    df = pd.DataFrame({"t": [10.0, 20, 30, 40, 50, 60], "temp": [300, 300, 350, 350, 400, 400]})
    r = client.post("/api/alt/fit", data={"x": "t", "s1": "temp"},
                    files={"file": ("a.csv", df.to_csv(index=False).encode(), "text/csv")})
    assert r.status_code == 500
    assert "internal detail" not in r.text


# ---- Client address behind Google's front ends --------------------------------------

def test_client_address_skips_google_front_end_hops(monkeypatch):
    from backend import config, request_ip

    monkeypatch.setattr(config, "TRUST_GOOGLE_FRONTENDS", True)
    monkeypatch.setattr(config, "TRUSTED_PROXY_CIDRS", [])
    # Through Firebase Hosting: the visitor, then Hosting's Google egress hop.
    assert request_ip.from_forwarded_for("203.0.113.7, 66.102.8.34") == "203.0.113.7"
    assert request_ip.from_forwarded_for("198.51.100.4, 74.125.215.65, 169.254.1.1") == "198.51.100.4"
    # A client-written entry further left is ignored.
    assert request_ip.from_forwarded_for("1.2.3.4, 203.0.113.7, 66.102.8.34") == "203.0.113.7"
    # A Google Cloud customer address (e.g. a VM) is a visitor, not a hop.
    assert request_ip.from_forwarded_for("34.116.0.10") == "34.116.0.10"
    # Off: the right-most public entry, as before.
    monkeypatch.setattr(config, "TRUST_GOOGLE_FRONTENDS", False)
    assert request_ip.from_forwarded_for("203.0.113.7, 66.102.8.34") == "66.102.8.34"
