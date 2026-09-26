"""HTML is always revalidated; hashed assets are immutable.

A stale HTML page references hashed chunks that a later deploy deleted, and the
app crashes on load — so HTML must never be served from a cache without
revalidation, while the content-hashed files under /assets can be kept forever.
"""

import pytest
from fastapi.testclient import TestClient

from backend import main


pytestmark = pytest.mark.skipif(not main.FRONTEND_DIST.is_dir(), reason="frontend not built")


def _client():
    return TestClient(main.app)


def test_spa_shell_and_prerendered_html_are_no_cache():
    c = _client()
    for path in ("/rbds/b/some-diagram", "/", "/blog"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert r.headers["cache-control"] == "no-cache", path


def test_hashed_assets_are_immutable_and_missing_ones_404():
    c = _client()
    assets = sorted((main.FRONTEND_DIST / "assets").glob("*.js"))
    assert assets, "expected built assets"
    r = c.get(f"/assets/{assets[0].name}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    missing = c.get("/assets/AppShell-doesnotexist.css")
    assert missing.status_code == 404
    assert "immutable" not in missing.headers.get("cache-control", "")
