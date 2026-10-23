"""#374: pages that don't exist answer with a real 404, not a 200 (a "soft
404" to search engines). In a cloud build (one with dist/content.json) an
unknown or not-yet-dated content slug gets the SPA shell with a 404 and a
noindex tag, so the app's own "not found" page shows; the app's routes with
ids keep the shell and a 200; a share page whose link is gone is a 404."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import db, main
from backend.routers import feeds
from backend.services import content_gate

API_DOCS_PAGES = ["authentication", "tools", "examples", "cli", "python", "files", "mcp", "v1-routes"]
NOINDEX = '<meta name="robots" content="noindex">'
SHELL = "<!doctype html><html><head><title>Reliafy</title></head><body><div id=root></div>SHELL</body></html>"
PRERENDERED = [
    ".", "blog", "blog/past", "blog/future", "whats-new", "whats-new/october-2026",
    "learn/weibull-analysis", "guides", "guides/repairable-rbd", "reference", "reference/weibull",
    "api-docs", "terms", "privacy", "rcm-software",
    # The API docs' pages (frontend/src/apiDocsPages.js).
    *(f"api-docs/{p}" for p in API_DOCS_PAGES),
]


@pytest.fixture
def dist(tmp_path):
    """A cloud build in miniature: the shell, prerendered pages, the content
    index, a sitemap, robots.txt and the feeds."""
    d = tmp_path / "dist"
    for route in PRERENDERED:
        (d / "static" / route).mkdir(parents=True, exist_ok=True)
        (d / "static" / route / "index.html").write_text(f"PRERENDERED {route}")
    (d / "blog").mkdir()
    (d / "blog" / "chart.png").write_bytes(b"PNG")
    (d / "index.html").write_text(SHELL)
    (d / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    (d / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset>\n'
        "  <url>\n    <loc>https://reliafy.com/blog/past</loc>\n  </url>\n</urlset>\n")
    (d / "feeds.json").write_text(json.dumps({"site": "https://reliafy.com", "feeds": [{
        "path": "/blog/feed.xml", "title": "Reliafy blog", "link": "https://reliafy.com/blog",
        "description": "Posts", "items": [{"title": "Past", "link": "https://reliafy.com/blog/past",
                                           "date": "2026-09-22", "summary": "s", "campaign": "past"}],
    }]}))
    (d / "content.json").write_text(json.dumps({"pages": {
        "/blog/past": "2026-09-22", "/blog/future": "2026-10-19",
        "/whats-new/october-2026": "2026-10-01",
    }}))
    return d


@pytest.fixture
def links(monkeypatch):
    """An in-memory database with a live, an expired and (by absence) a
    revoked share link."""
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    now = datetime.now(timezone.utc)
    test_db.public_links.insert_many([
        {"_id": "LiveToken_abcdefghijklmn", "collection": "models", "artifact_id": "m1"},
        {"_id": "OldToken_abcdefghijklmno", "collection": "models", "artifact_id": "m1",
         "expires_at": now - timedelta(days=1)},
        {"_id": "SoonToken_abcdefghijklmn", "collection": "models", "artifact_id": "m1",
         "expires_at": now + timedelta(days=1)},
    ])
    return test_db


@pytest.fixture
def site(dist, monkeypatch, links):
    monkeypatch.setattr(content_gate, "today", lambda: "2026-10-12")
    app = FastAPI()

    @app.get("/{full_path:path}")
    def serve(full_path: str):
        return main.spa_response(full_path, dist, share_live=main.share_link_live)

    return TestClient(app)


def _is_404_shell(r) -> bool:
    return (r.status_code == 404 and "SHELL" in r.text and NOINDEX in r.text
            and r.headers["content-type"].startswith("text/html")
            and r.headers["cache-control"] == "no-cache")


# ---- unknown roots: the plain 404 page, as since #118 ---------------------------

@pytest.mark.parametrize("path", ["/totally-made-up", "/widgets/abc", "/wp-login.php", "/Bloggs/past"])
def test_unknown_roots_are_404_pages(site, path):
    r = site.get(path)
    assert r.status_code == 404, path
    assert "Page not found" in r.text and NOINDEX in r.text and "SHELL" not in r.text


# ---- content slugs ----------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/blog/no-such-post", "/blog/no-such-post/", "/whats-new/no-such-update", "/learn/nothing",
    "/guides/no-such-guide", "/reference/no-such-family",
])
def test_unknown_content_slugs_are_404s_with_the_shell(site, path):
    assert _is_404_shell(site.get(path)), path


def test_future_dated_post_is_a_404_until_its_date(site, monkeypatch):
    assert _is_404_shell(site.get("/blog/future"))
    monkeypatch.setattr(content_gate, "today", lambda: "2026-10-19")
    r = site.get("/blog/future")
    assert r.status_code == 200 and r.text == "PRERENDERED blog/future"


@pytest.mark.parametrize("path", [
    "/", "/blog", "/blog/past", "/whats-new", "/whats-new/october-2026", "/learn/weibull-analysis",
    "/guides", "/guides/repairable-rbd", "/reference", "/reference/weibull", "/api-docs", "/terms",
    "/privacy", "/rcm-software", *(f"/api-docs/{p}" for p in API_DOCS_PAGES),
])
def test_real_content_is_served_prerendered(site, path):
    r = site.get(path)
    assert r.status_code == 200, path
    assert r.text.startswith("PRERENDERED") and NOINDEX not in r.text
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", [
    "/blog/past/extra", "/terms/x", "/privacy/old", "/rcm-software/x", "/api-docs/v2", "/api-docs/cli/extra",
    "/reference/weibull/params",
])
def test_other_paths_under_content_roots_are_404_pages(site, path):
    r = site.get(path)
    assert r.status_code == 404, path
    assert "Page not found" in r.text and NOINDEX in r.text


def test_files_under_content_roots_are_still_served(site):
    r = site.get("/blog/chart.png")
    assert r.status_code == 200 and r.content == b"PNG"


def test_learn_index_keeps_the_shell(site):
    """/learn redirects to /blog in the browser; it has no prerendered page."""
    r = site.get("/learn")
    assert r.status_code == 200 and "SHELL" in r.text and NOINDEX not in r.text


def test_without_the_content_index_slugs_keep_the_shell(site, dist):
    """Self-host and dev builds don't prerender, so they can't tell."""
    (dist / "content.json").unlink()
    for path in ("/blog/no-such-post", "/learn/nothing", "/terms/x"):
        r = site.get(path)
        assert r.status_code == 200 and "SHELL" in r.text, path


# ---- the app's own routes ---------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/models", "/models/m/abc123", "/models/recurrent/r1", "/systems/b/123", "/systems/runs/run9",
    "/data/d1", "/home", "/models/tracking/f1", "/forecasts/f2", "/strategy/analyses/s1",
    "/maintenance/rcm/s1", "/asset-register/positions/p1", "/reports",
    # Earlier addresses, which the app redirects.
    "/modelling", "/modelling/m/abc123", "/modelling/recurrent/r1", "/rbds/b/123", "/rbds/runs/run9",
    "/datasets/d/d1", "/modelling/data/d1", "/fleet/tracking/f1", "/fleet/forecasts/f2", "/rcm/studies/s1",
    "/settings", "/login", "/oauth/consent", "/unsubscribe",
])
def test_app_routes_with_ids_keep_the_shell_and_a_200(site, path):
    r = site.get(path)
    assert r.status_code == 200, path
    assert "SHELL" in r.text and NOINDEX not in r.text
    assert r.headers["cache-control"] == "no-cache"


# ---- share pages ------------------------------------------------------------------

@pytest.mark.parametrize("token", ["LiveToken_abcdefghijklmn", "SoonToken_abcdefghijklmn"])
def test_live_share_link_gets_the_shell(site, token):
    r = site.get(f"/p/{token}")
    assert r.status_code == 200 and "SHELL" in r.text and NOINDEX not in r.text


@pytest.mark.parametrize("path", [
    "/p/NoSuchToken_abcdefghijk", "/p/OldToken_abcdefghijklmno", "/p/bad.token!", "/p",
    "/p/LiveToken_abcdefghijklmn/extra",
])
def test_unknown_expired_or_revoked_share_link_is_a_404(site, path):
    assert _is_404_shell(site.get(path)), path


def test_revoked_share_link_is_a_404(site, links):
    assert site.get("/p/LiveToken_abcdefghijklmn").status_code == 200
    links.public_links.delete_one({"_id": "LiveToken_abcdefghijklmn"})  # what revoke does
    assert _is_404_shell(site.get("/p/LiveToken_abcdefghijklmn"))


# ---- everything else is unchanged ----------------------------------------------------

def test_built_files_are_unchanged(site):
    r = site.get("/robots.txt")
    assert r.status_code == 200 and r.text.startswith("User-agent")
    for path in ("/feeds.json", "/content.json", "/static/blog/past/index.html"):
        assert site.get(path).status_code == 404, path


def test_noindex_shell_tracks_the_build(site, dist):
    """A rebuild's shell (new hashed chunks) is what the 404 serves."""
    assert "SHELL" in site.get("/blog/nope").text
    dist.joinpath("index.html").write_text(SHELL.replace("SHELL", "REBUILT"))
    st = dist.joinpath("index.html").stat()
    os.utime(dist / "index.html", (st.st_atime, st.st_mtime + 5))
    r = site.get("/blog/nope")
    assert "REBUILT" in r.text and NOINDEX in r.text


def test_machine_paths_feeds_and_sitemap_are_unchanged(dist, monkeypatch, links):
    """Through the real app: the routers answer before the catch-all."""
    monkeypatch.setattr(feeds, "DIST", dist)
    load = feeds._load
    monkeypatch.setattr(feeds, "_load", lambda: load(dist / "feeds.json"))
    monkeypatch.setattr(feeds, "_today", lambda: "2026-10-12")
    client = TestClient(main.app)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and "/blog/past" in r.text
    r = client.get("/blog/feed.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/rss+xml")
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert client.get("/.well-known/nothing").json() == {"detail": "Not Found"}
    assert client.get("/internal/x").status_code == 404


@pytest.mark.skipif(not main.FRONTEND_DIST.is_dir(), reason="frontend not built")
def test_the_live_catch_all_checks_share_links(links):
    client = TestClient(main.app)
    assert client.get("/p/LiveToken_abcdefghijklmn").status_code == 200
    r = client.get("/p/NoSuchToken_abcdefghijk")
    assert r.status_code == 404 and NOINDEX in r.text and '<div id="root">' in r.text


def test_content_roots_match_the_prerendered_routes():
    """Every root the build prerenders is one the server checks, and the
    checked roots are all app routes."""
    src = Path(__file__).resolve().parents[2] / "frontend" / "src"
    entry = (src / "prerender-entry.jsx").read_text()
    routes = entry[entry.index("export function routes()"):entry.index("export function gatedPages()")]
    collections = set(re.findall(r"path: `/([a-z-]+)/\$\{", routes))
    pages = set(re.findall(r'path: "/([a-z-]+)"', routes))
    pages |= set(re.findall(r'path: "/([a-z-]+)"', (src / "productPages.jsx").read_text()))
    # The API docs' pages come from apiDocsPages.js: /api-docs and pages beneath it.
    if "API_DOCS_PAGES.map" in routes:
        pages.add("api-docs")
    assert collections == set(main.CONTENT_COLLECTIONS)
    assert pages - collections == set(main.CONTENT_PAGES)
    assert (main.CONTENT_COLLECTIONS | main.CONTENT_PAGES) <= main.SPA_ROOTS
