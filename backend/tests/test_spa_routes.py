"""#118: the frontend catch-all serves a real llms.txt, the SPA shell for the
app's own routes only, and a real 404 for every other path (it used to
answer anything with the shell and a 200 — a soft 404 for crawlers and
agents)."""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def site(tmp_path):
    """A built frontend in miniature: the shell, a file, a prerendered page."""
    dist = tmp_path / "dist"
    (dist / "static" / "blog" / "weibull").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>SHELL")
    (dist / "llms.txt").write_text("# Reliafy\n")
    (dist / "static" / "index.html").write_text("LANDING")
    (dist / "static" / "blog" / "weibull" / "index.html").write_text("PRERENDERED POST")
    (tmp_path / "secret.txt").write_text("outside")

    app = FastAPI()

    @app.get("/{full_path:path}")
    def serve(full_path: str):
        return main.spa_response(full_path, dist)

    return TestClient(app)


def test_llms_txt_is_served_as_text(site):
    r = site.get("/llms.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("# Reliafy")


@pytest.mark.parametrize("path", [
    "/modelling", "/modelling/m/abc", "/rbds/b/123", "/datasets/list", "/strategy/replacement",
    "/fleet/tracking/f1", "/rcm/studies/s1", "/settings", "/team", "/admin", "/billing", "/tokens",
    "/login", "/oauth/consent", "/p/sometoken", "/unsubscribe", "/api-docs", "/terms", "/privacy",
    "/blog", "/blog/a-post-not-prerendered-yet", "/learn/weibull", "/guides/x", "/reference/weibull",
    "/whats-new/october-2026", "/rcm-software", "/weibull-analysis-software",
])
def test_app_routes_get_the_shell(site, path):
    r = site.get(path)
    assert r.status_code == 200, path
    assert "SHELL" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_prerendered_pages_win_over_the_shell(site):
    assert site.get("/").text == "LANDING"
    assert site.get("/blog/weibull").text == "PRERENDERED POST"


@pytest.mark.parametrize("path", [
    "/nope", "/llms-full.txt", "/wp-login.php", "/modeling", "/static", "/static/whatever",
    "/.env", "/favicon-old.ico", "/sitemap_index.xml",
])
def test_unknown_paths_are_real_404_pages(site, path):
    r = site.get(path)
    assert r.status_code == 404, path
    assert r.headers["content-type"].startswith("text/html")
    assert "Page not found" in r.text and "SHELL" not in r.text
    assert 'name="robots" content="noindex"' in r.text


@pytest.mark.parametrize("path", ["/api/nope", "/api/v1/nothing-here", "/.well-known/nothing", "/internal/x"])
def test_unknown_machine_paths_are_json_404s(site, path):
    r = site.get(path)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("path", ["/..%2fsecret.txt", "/static/..%2f..%2fsecret.txt", "/blog/..%2f..%2fsecret.txt"])
def test_never_leaves_dist(site, path):
    r = site.get(path)
    assert "outside" not in r.text


def _route_roots() -> set[str]:
    """The first segment of every route path the React app declares."""
    roots = set()
    for name in ("src/App.jsx", "src/AppShell.jsx", "src/productPages.jsx"):
        text = (FRONTEND / name).read_text()
        for path in re.findall(r'path(?:=|:\s*)"(/[^"]*)"', text):
            first = path.strip("/").split("/", 1)[0]
            if first and first != "*":
                roots.add(first)
    return roots


def test_spa_roots_match_the_apps_routes():
    """Every route the app draws gets the shell; nothing else does."""
    roots = _route_roots()
    assert {"modelling", "rbds", "blog", "login", "rcm-software"} <= roots  # the parse works
    assert roots == set(main.SPA_ROOTS)


def test_llms_txt_is_in_the_build():
    """public/ is copied into dist as is, so the file is served at /llms.txt."""
    text = (FRONTEND / "public" / "llms.txt").read_text()
    assert text.startswith("# Reliafy\n\n> ")
    assert "https://reliafy.com/mcp" in text and "https://reliafy.com/api-docs" in text
    assert "https://reliafy.com/openapi.json" in text
    for url in re.findall(r"\]\((https://reliafy\.com/[^)#]*)", text):
        path = url.removeprefix("https://reliafy.com/")
        # Each link is an app route, a feed, a backend route, or a file.
        assert (main.is_spa_route(path) or path.endswith(("feed.xml", "openapi.json", "mcp"))
                or path.startswith(".well-known/")), url


def test_openapi_schema_is_served():
    r = TestClient(main.app).get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "Reliafy"
