from fastapi.testclient import TestClient

from backend.main import app


def test_api_responses_carry_the_build_id(monkeypatch):
    monkeypatch.setenv("RELIAFY_BUILD_ID", "abc123")
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.headers["X-Reliafy-Build"] == "abc123"
    assert res.json()["build"] == "abc123"


def test_no_build_id_no_header(monkeypatch):
    monkeypatch.delenv("RELIAFY_BUILD_ID", raising=False)
    monkeypatch.setattr("backend.build_id._FILE", __import__("pathlib").Path("/nonexistent/build-id.txt"))
    res = TestClient(app).get("/api/health")
    assert "X-Reliafy-Build" not in res.headers
    assert res.json()["build"] is None
