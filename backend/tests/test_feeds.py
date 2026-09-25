"""RSS feeds are rendered per request from feeds.json, filtered by today's date."""

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from backend.routers import feeds

DATA = {
    "site": "https://reliafy.com",
    "feeds": [
        {
            "path": "/whats-new/feed.xml",
            "title": "Reliafy — What's new",
            "link": "https://reliafy.com/whats-new",
            "description": "Product updates",
            "items": [
                {"title": "Future <b>& co</b>", "link": "https://reliafy.com/whats-new/future",
                 "guid": "https://reliafy.com/whats-new/future", "date": "2026-10-01",
                 "summary": "Not yet"},
                {"title": "Past", "link": "https://reliafy.com/whats-new/past",
                 "guid": "https://reliafy.com/whats-new/past", "date": "2026-09-01",
                 "summary": "Old & gold"},
            ],
        },
        {"path": "/blog/feed.xml", "title": "Blog", "link": "https://reliafy.com/blog",
         "description": "Posts", "items": []},
    ],
}


def _titles(xml: str) -> list[str]:
    root = ET.fromstring(xml)
    return [i.findtext("title") for i in root.iter("item")]


def test_future_items_hidden_until_their_date():
    before = feeds.render_feed(DATA["feeds"][0], DATA["site"], "2026-09-30")
    assert _titles(before) == ["Past"]
    on_day = feeds.render_feed(DATA["feeds"][0], DATA["site"], "2026-10-01")
    # Newest first, and the queued item appears on its date with no rebuild.
    assert _titles(on_day) == ["Future <b>& co</b>", "Past"]


def test_feed_is_well_formed_and_escaped():
    xml = feeds.render_feed(DATA["feeds"][0], DATA["site"], "2026-12-31")
    root = ET.fromstring(xml)  # raises if the escaping were wrong
    ch = root.find("channel")
    assert ch.findtext("title") == "Reliafy — What's new"
    first = ch.find("item")
    assert first.findtext("pubDate") == "Thu, 01 Oct 2026 00:00:00 GMT"
    assert first.find("guid").get("isPermaLink") == "true"
    assert ch.findtext("lastBuildDate") == "Thu, 01 Oct 2026 00:00:00 GMT"


def test_route_serves_date_filtered_xml(monkeypatch):
    monkeypatch.setattr(feeds, "_load", lambda *a, **k: DATA)
    monkeypatch.setattr(feeds, "_today", lambda: "2026-09-30")
    from backend.main import app

    r = TestClient(app).get("/whats-new/feed.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/rss+xml")
    assert "max-age" in r.headers["cache-control"]
    assert _titles(r.text) == ["Past"]

    monkeypatch.setattr(feeds, "_today", lambda: "2026-10-01")
    assert _titles(TestClient(app).get("/whats-new/feed.xml").text)[0].startswith("Future")


def test_empty_feed_and_missing_manifest(monkeypatch):
    from backend.main import app

    monkeypatch.setattr(feeds, "_load", lambda *a, **k: DATA)
    r = TestClient(app).get("/blog/feed.xml")
    assert r.status_code == 200 and _titles(r.text) == []

    monkeypatch.setattr(feeds, "_load", lambda *a, **k: None)
    assert TestClient(app).get("/whats-new/feed.xml").status_code == 404
