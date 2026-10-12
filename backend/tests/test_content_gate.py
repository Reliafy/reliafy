"""#367: blog posts and updates are prerendered ahead of their date, and the
server holds each page and its sitemap entry back until the date arrives."""

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import main
from backend.routers import feeds
from backend.services import content_gate

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://reliafy.com/</loc>
  </url>
  <url>
    <loc>https://reliafy.com/blog/past</loc>
    <lastmod>2026-09-22</lastmod>
  </url>
  <url>
    <loc>https://reliafy.com/blog/future</loc>
    <lastmod>2026-10-19</lastmod>
  </url>
  <url>
    <loc>https://reliafy.com/whats-new/november-2026</loc>
    <lastmod>2026-11-02</lastmod>
  </url>
</urlset>
"""


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    for route in ("blog/past", "blog/future", "whats-new/november-2026"):
        (d / "static" / route).mkdir(parents=True)
        (d / "static" / route / "index.html").write_text(f"PRERENDERED {route}")
    (d / "index.html").write_text("<!doctype html><div id=root></div>SHELL")
    (d / "sitemap.xml").write_text(SITEMAP)
    (d / "feeds.json").write_text('{"feeds": []}')
    (d / "content.json").write_text(json.dumps({"pages": {
        "/blog/past": "2026-09-22",
        "/blog/future": "2026-10-19",
        "/whats-new/november-2026": "2026-11-02",
    }}))
    return d


@pytest.fixture
def site(dist):
    app = FastAPI()

    @app.get("/{full_path:path}")
    def serve(full_path: str):
        return main.spa_response(full_path, dist)

    return TestClient(app)


def _on(monkeypatch, day):
    monkeypatch.setattr(content_gate, "today", lambda: day)


def test_future_post_answers_like_an_unknown_path_until_its_date(site, monkeypatch):
    _on(monkeypatch, "2026-10-18")
    unknown = site.get("/blog/never-written")
    held = site.get("/blog/future")
    assert held.status_code == unknown.status_code == 200
    assert held.text == unknown.text and "SHELL" in held.text
    assert held.headers["cache-control"] == unknown.headers["cache-control"]
    # Trailing slash and case don't get round it.
    assert "SHELL" in site.get("/blog/future/").text
    # (On a case-insensitive disk /Blog/Future finds the same file.)
    assert "PRERENDERED" not in site.get("/Blog/Future").text
    # A past post is served prerendered.
    assert site.get("/blog/past").text == "PRERENDERED blog/past"


def test_future_post_is_served_prerendered_on_its_date(site, monkeypatch):
    _on(monkeypatch, "2026-10-19")
    assert site.get("/blog/future").text == "PRERENDERED blog/future"
    assert "SHELL" in site.get("/whats-new/november-2026").text
    _on(monkeypatch, "2026-11-02")
    assert site.get("/whats-new/november-2026").text == "PRERENDERED whats-new/november-2026"


@pytest.mark.parametrize("path", [
    "/static/blog/future/index.html", "/static/blog/past/index.html", "/static",
    "/feeds.json", "/content.json",
])
def test_private_build_files_and_prerendered_paths_are_not_served(site, monkeypatch, path):
    _on(monkeypatch, "2026-10-18")
    r = site.get(path)
    assert r.status_code == 404, path
    assert "PRERENDERED" not in r.text and "feeds" not in r.text


def test_without_a_gate_file_everything_prerendered_is_served(site, dist, monkeypatch):
    (dist / "content.json").unlink()
    _on(monkeypatch, "2000-01-01")
    assert site.get("/blog/future").text == "PRERENDERED blog/future"


def test_gate_file_is_reread_when_it_changes(dist, monkeypatch):
    assert content_gate.held("/blog/future", dist, "2026-10-18")
    (dist / "content.json").write_text(json.dumps({"pages": {"/blog/future": "2026-10-01"}}))
    st = (dist / "content.json").stat()
    os.utime(dist / "content.json", (st.st_atime, st.st_mtime + 5))
    assert not content_gate.held("/blog/future", dist, "2026-10-18")


def test_filter_sitemap_drops_only_pages_not_yet_live():
    dates = {"/blog/past": "2026-09-22", "/blog/future": "2026-10-19",
             "/whats-new/november-2026": "2026-11-02"}
    before = content_gate.filter_sitemap(SITEMAP, dates, "2026-10-18")
    assert "/blog/past" in before and "https://reliafy.com/</loc>" in before
    assert "/blog/future" not in before and "november-2026" not in before
    assert before.rstrip().endswith("</urlset>")
    on_day = content_gate.filter_sitemap(SITEMAP, dates, "2026-10-19")
    assert "/blog/future" in on_day and "november-2026" not in on_day
    assert content_gate.filter_sitemap(SITEMAP, dates, "2026-11-02") == SITEMAP


def test_sitemap_route_is_date_filtered(dist, monkeypatch):
    from backend.main import app

    monkeypatch.setattr(feeds, "DIST", dist)
    monkeypatch.setattr(feeds, "_today", lambda: "2026-10-18")
    r = TestClient(app).get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "/blog/past" in r.text and "/blog/future" not in r.text
    monkeypatch.setattr(feeds, "_today", lambda: "2026-10-19")
    assert "/blog/future" in TestClient(app).get("/sitemap.xml").text
