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


# ---- The LinkedIn feed (#367) ------------------------------------------------

SOCIAL = {
    "path": "/social/feed.xml",
    "title": "Reliafy on LinkedIn",
    "link": "https://reliafy.com",
    "description": "Posts for the Reliafy LinkedIn page",
    "utm": {"source": "linkedin", "medium": "social"},
    "items": [
        # A short post linking to a post that goes live a week later: held.
        {"kind": "short", "title": "Tip", "link": "https://reliafy.com/blog/import-rbds",
         "guid": "https://reliafy.com/social/2026-10-14-import-tip", "permalink": False,
         "date": "2026-10-14", "hold_until": "2026-10-19", "campaign": "import-tip",
         "summary": "Line one.\n\nLine two & more.", "image": "https://reliafy.com/blog/card.png"},
        {"kind": "blog", "title": "Import your RBDs", "link": "https://reliafy.com/blog/import-rbds",
         "guid": "https://reliafy.com/blog/import-rbds#linkedin", "permalink": False,
         "date": "2026-10-19", "hold_until": "", "campaign": "import-rbds",
         "summary": "Exact LinkedIn text.", "image": ""},
        {"kind": "short", "title": "No link", "link": "",
         "guid": "https://reliafy.com/social/2026-10-12-no-link", "permalink": False,
         "date": "2026-10-12", "hold_until": "", "campaign": "no-link", "summary": "Words only."},
        {"kind": "whats-new", "title": "What's new: November",
         "link": "https://reliafy.com/whats-new/november-2026",
         "guid": "https://reliafy.com/whats-new/november-2026#linkedin", "permalink": False,
         "date": "2026-11-02", "hold_until": "", "campaign": "november-2026",
         "summary": "What's new: November\n\nLots."},
    ],
}


def _items(xml: str) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for i in root.iter("item"):
        enc = i.find("enclosure")
        out.append({
            "guid": i.findtext("guid"),
            "permalink": i.find("guid").get("isPermaLink"),
            "link": i.findtext("link"),
            "text": i.findtext("description"),
            "image": enc.get("url") if enc is not None else None,
        })
    return out


def test_social_feed_items_appear_on_their_date_and_holds_wait_for_their_page():
    guids = lambda today: [i["guid"] for i in _items(feeds.render_feed(SOCIAL, "https://reliafy.com", today))]
    assert guids("2026-10-11") == []
    assert guids("2026-10-12") == ["https://reliafy.com/social/2026-10-12-no-link"]
    # Dated the 14th, but its link goes live on the 19th.
    assert guids("2026-10-18") == ["https://reliafy.com/social/2026-10-12-no-link"]
    assert guids("2026-10-19") == [
        "https://reliafy.com/blog/import-rbds#linkedin",
        "https://reliafy.com/social/2026-10-14-import-tip",
        "https://reliafy.com/social/2026-10-12-no-link",
    ]
    assert len(guids("2026-11-02")) == 4


def test_social_feed_carries_full_text_tagged_links_and_stable_guids():
    items = {i["guid"]: i for i in _items(feeds.render_feed(SOCIAL, "https://reliafy.com", "2026-12-01"))}
    assert len(items) == 4  # unique guids
    tip = items["https://reliafy.com/social/2026-10-14-import-tip"]
    assert tip["text"] == "Line one.\n\nLine two & more."
    assert tip["link"] == ("https://reliafy.com/blog/import-rbds"
                           "?utm_source=linkedin&utm_medium=social&utm_campaign=import-tip")
    assert tip["permalink"] == "false"
    assert tip["image"] == "https://reliafy.com/blog/card.png"
    blog = items["https://reliafy.com/blog/import-rbds#linkedin"]
    assert blog["link"].endswith("?utm_source=linkedin&utm_medium=social&utm_campaign=import-rbds")
    assert blog["text"] == "Exact LinkedIn text."
    assert blog["image"] is None
    # The guid is never tagged, so a re-tag can't make Zapier repost.
    assert all("utm_" not in g for g in items)
    assert items["https://reliafy.com/social/2026-10-12-no-link"]["link"] in ("", None)


def test_social_feed_route(monkeypatch):
    data = {"site": "https://reliafy.com", "feeds": [*DATA["feeds"], SOCIAL]}
    monkeypatch.setattr(feeds, "_load", lambda *a, **k: data)
    monkeypatch.setattr(feeds, "_today", lambda: "2026-10-19")
    from backend.main import app

    r = TestClient(app).get("/social/feed.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/rss+xml")
    assert len(_items(r.text)) == 3


# ---- UTM tags on the RSS feeds (#353, #367) ----------------------------------

def test_rss_links_are_tagged_and_guids_are_not():
    feed = {**DATA["feeds"][0], "utm": {"source": "rss", "medium": "feed"},
            "items": [{**it, "campaign": it["link"].rsplit("/", 1)[1]} for it in DATA["feeds"][0]["items"]]}
    items = _items(feeds.render_feed(feed, DATA["site"], "2026-12-31"))
    assert [i["link"] for i in items] == [
        "https://reliafy.com/whats-new/future?utm_source=rss&utm_medium=feed&utm_campaign=future",
        "https://reliafy.com/whats-new/past?utm_source=rss&utm_medium=feed&utm_campaign=past",
    ]
    assert [i["guid"] for i in items] == ["https://reliafy.com/whats-new/future",
                                          "https://reliafy.com/whats-new/past"]
    assert all(i["permalink"] == "true" for i in items)


def test_untagged_feed_and_foreign_links_are_left_alone():
    # A feed without utm (an older feeds.json) renders as before.
    assert _items(feeds.render_feed(DATA["feeds"][0], DATA["site"], "2026-12-31"))[1]["link"] == \
        "https://reliafy.com/whats-new/past"
    feed = {"utm": {"source": "rss", "medium": "feed"}}
    assert feeds.item_link(feed, {"link": "https://example.org/x", "campaign": "c"}) == "https://example.org/x"
    assert feeds.item_link(feed, {"link": "https://reliafy.com/x?utm_source=a", "campaign": "c"}) == \
        "https://reliafy.com/x?utm_source=a"
