"""The SPA route only ever serves files from inside the built frontend."""

import pytest
from fastapi.testclient import TestClient

from backend import main


def test_contained_path(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "app.js").write_text("x")
    (tmp_path / "outside.txt").write_text("x")

    assert main.contained_path(root / "assets" / "app.js", root) == (
        root / "assets" / "app.js"
    ).resolve()
    assert main.contained_path(root / "../outside.txt", root) is None
    assert main.contained_path(root / "assets/../../outside.txt", root) is None
    assert main.contained_path(root / "/etc/hostname", root) is None


@pytest.mark.skipif(not main.FRONTEND_DIST.is_dir(), reason="frontend not built")
@pytest.mark.parametrize(
    "path",
    ["/..%2fbackend%2fmain.py", "/..%2f..%2f..%2f..%2fetc%2fhostname",
     "/static/..%2f..%2f..%2fbackend%2fconfig.py"],
)
def test_spa_route_does_not_leave_dist(path):
    r = TestClient(main.app).get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert b"import" not in r.content[:200]
