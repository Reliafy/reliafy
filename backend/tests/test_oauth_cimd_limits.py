"""Limits on fetching OAuth client metadata documents (CIMD): a wall-clock
deadline on the whole fetch, a cap on fetches in flight, and a short memory
of failed URLs.

The fetch test runs a local HTTPS server (a throwaway self-signed
certificate) that sends its body a byte at a time; nothing leaves the machine.
"""

import datetime as dt
import ipaddress
import json
import socket
import ssl
import threading
import time

import pytest

from backend.services import oauth as oauth_service
from backend.services.oauth import OAuthError

HOST = "metadata.example"
URL = "https://tool.example/client.json"
DOC = {"client_id": URL, "client_name": "Tool", "redirect_uris": ["http://localhost/callback"],
       "token_endpoint_auth_method": "none"}


@pytest.fixture(autouse=True)
def _clean():
    oauth_service._cimd_cache.clear()
    oauth_service._cimd_failures.clear()
    yield
    oauth_service._cimd_cache.clear()
    oauth_service._cimd_failures.clear()


def _self_signed(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOST),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def _slow_server(cert, key, byte_every: float, stop: threading.Event):
    """An HTTPS server that sends headers at once, then one body byte every
    ``byte_every`` seconds (each gap shorter than the per-read timeout)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.settimeout(5)

    def serve():
        try:
            raw, _ = sock.accept()
            conn = ctx.wrap_socket(raw, server_side=True)
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 60000\r\n\r\n")
            while not stop.is_set():
                time.sleep(byte_every)
                conn.sendall(b" ")
        except OSError:
            pass
        finally:
            sock.close()

    threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()[1]


def test_client_metadata_fetch_has_a_total_deadline(tmp_path, monkeypatch):
    import httpx

    cert, key = _self_signed(tmp_path)
    stop = threading.Event()
    port = _slow_server(cert, key, byte_every=0.2, stop=stop)
    trusting = ssl.create_default_context(cafile=cert)
    real_client = httpx.AsyncClient
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: real_client(verify=trusting, **kw))
    monkeypatch.setattr(oauth_service, "_resolve_public", lambda host, port: "127.0.0.1")
    monkeypatch.setattr(oauth_service, "CIMD_TIMEOUT", 1.0)   # per read: each byte arrives within it
    monkeypatch.setattr(oauth_service, "CIMD_DEADLINE", 1.5)  # the whole fetch
    started = time.monotonic()
    try:
        with pytest.raises(OAuthError, match="too long"):
            oauth_service._http_fetch(f"https://{HOST}:{port}/client.json")
    finally:
        stop.set()
    assert time.monotonic() - started < 3.0


def test_client_metadata_lookup_counts_toward_the_deadline(monkeypatch):
    def slow_lookup(host, port):
        time.sleep(3)
        return "93.184.216.34"

    monkeypatch.setattr(oauth_service, "_resolve_public", slow_lookup)
    monkeypatch.setattr(oauth_service, "CIMD_DEADLINE", 0.3)
    started = time.monotonic()
    with pytest.raises(OAuthError, match="too long"):
        oauth_service._http_fetch("https://slow.example/client.json")
    assert time.monotonic() - started < 2.0


def test_client_metadata_fetches_in_flight_are_capped(monkeypatch):
    release = threading.Event()
    calls = []

    def held_fetch(url):
        calls.append(url)
        release.wait(5)
        return 200, {}, json.dumps({**DOC, "client_id": url}).encode()

    monkeypatch.setattr(oauth_service, "_http_fetch", held_fetch)
    monkeypatch.setattr(oauth_service, "CIMD_FETCH_WAIT", 0.2)
    monkeypatch.setattr(oauth_service, "_cimd_fetches", threading.BoundedSemaphore(2))
    results = {}

    def fetch(i):
        try:
            results[i] = oauth_service.fetch_client_metadata(f"https://tool{i}.example/client.json")
        except OAuthError as exc:
            results[i] = exc

    threads = [threading.Thread(target=fetch, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 5
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    fetch(9)  # a third, while two are in flight
    release.set()
    for t in threads:
        t.join(5)
    assert isinstance(results[9], OAuthError) and results[9].error == "temporarily_unavailable"
    assert results[9].status == 503
    assert all(isinstance(results[i], dict) for i in range(2))
    assert len(calls) == 2
    # Slots are given back: the next fetch goes ahead.
    assert oauth_service.fetch_client_metadata("https://tool9.example/client.json")["client_id"].startswith(
        "https://tool9")


def test_failed_client_metadata_fetch_is_remembered_briefly(monkeypatch):
    calls = []

    def missing(url):
        calls.append(url)
        return 404, {}, b"not found"

    monkeypatch.setattr(oauth_service, "_http_fetch", missing)
    for _ in range(3):
        with pytest.raises(OAuthError, match="HTTP 404"):
            oauth_service.fetch_client_metadata(URL)
    assert calls == [URL]

    # Once the memory lapses, it's fetched again.
    until, exc = oauth_service._cimd_failures[URL]
    oauth_service._cimd_failures[URL] = (time.monotonic() - 1, exc)
    monkeypatch.setattr(oauth_service, "_http_fetch",
                        lambda url: (200, {}, json.dumps(DOC).encode()))
    assert oauth_service.fetch_client_metadata(URL)["client_name"] == "Tool"


def test_remembered_failures_are_bounded(monkeypatch):
    monkeypatch.setattr(oauth_service, "CIMD_MAX_FAILURES", 5)
    monkeypatch.setattr(oauth_service, "_http_fetch", lambda url: (500, {}, b""))
    for i in range(12):
        with pytest.raises(OAuthError):
            oauth_service.fetch_client_metadata(f"https://tool{i}.example/client.json")
    assert len(oauth_service._cimd_failures) <= 5
