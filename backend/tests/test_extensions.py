"""Optional extensions (backend/extensions.py): discovery through the entry-point
group, who sees which page, and that a page's module is only served to them.

The extension is a tiny fixture package (fixtures/extension_pkg): one route,
a page for operators (with an extra asset), a page for every signed-in user,
and a content-job step."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import extensions

PKG = Path(__file__).parent / "fixtures" / "extension_pkg"
OPS = {"uid": "ops", "email": "ops@example.org", "name": "Ops", "email_verified": True}
USER = {"uid": "u1", "email": "u1@example.org", "name": "User", "email_verified": True}


@pytest.fixture()
def dummy(monkeypatch):
    """The fixture package importable and discoverable; the registry emptied
    before and after."""
    monkeypatch.syspath_prepend(str(PKG))
    extensions.reset()
    yield
    extensions.reset()
    sys.modules.pop("dummy_extension", None)


def _dummy():
    import dummy_extension

    return dummy_extension.extension()


@pytest.fixture()
def client(monkeypatch, dummy):
    """The app with the dummy's pages registered (its pages only: the main
    app's routes aren't changed), operators = OPS."""
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {OPS["email"]})
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["ext_test"])
    ext = _dummy()
    ext.routers = []
    extensions.register(None, ext)
    tc = TestClient(app)

    def act_as(user):
        if user is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    tc.act_as = act_as
    yield tc
    app.dependency_overrides.clear()


# ---- discovery ---------------------------------------------------------------------

def _app_with_catch_all():
    app = FastAPI()

    @app.get("/{full_path:path}")
    def catch_all(full_path: str):
        return {"caught": full_path}

    return app


def test_installed_extensions_are_found_by_entry_point(dummy, monkeypatch):
    monkeypatch.setenv("EXTENSIONS_DISABLED", "false")
    app = _app_with_catch_all()
    assert extensions.load(app) == ["dummy"]
    (ext,) = extensions.installed()
    assert [m.id for m in ext.mounts] == ["ops", "all"]
    # Its routes go in front of the catch-all, so they're reached.
    assert TestClient(app).get("/api/dummy/ping").json() == {"pong": True}
    assert TestClient(app).get("/elsewhere").json() == {"caught": "elsewhere"}


def test_nothing_is_loaded_when_disabled(dummy, monkeypatch):
    monkeypatch.setenv("EXTENSIONS_DISABLED", "true")
    assert extensions.load(FastAPI()) == [] and extensions.installed() == []


def test_a_broken_extension_is_skipped(dummy, monkeypatch, caplog):
    class Broken:
        name = "broken"

        def load(self):
            raise ImportError("missing dependency")

    monkeypatch.setenv("EXTENSIONS_DISABLED", "false")
    monkeypatch.setattr(extensions, "entry_points", lambda group: [Broken()])
    assert extensions.load(FastAPI()) == []
    assert "could not be loaded" in caplog.text


def test_bad_declarations_are_refused(dummy):
    from backend.extensions import Extension, Mount

    with pytest.raises(ValueError):
        extensions.register(None, Extension(name="x", mounts=[Mount(id="p", label="P", path="/a/b", bundle=PKG)]))
    with pytest.raises(ValueError):
        extensions.register(None, Extension(name="x", mounts=[Mount(id="p", label="P", path="/p", bundle=PKG,
                                                                     audience="everyone")]))
    with pytest.raises(ValueError):
        extensions.register(None, Extension(name="x", mounts=[Mount(id="p", label="P", path="/p", bundle=PKG,
                                                                     assets={"../x.js": PKG})]))
    extensions.register(None, _dummy())
    with pytest.raises(ValueError):
        extensions.register(None, _dummy())


# ---- no extensions -------------------------------------------------------------------

def test_without_extensions_the_list_is_empty(monkeypatch):
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    extensions.reset()
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {OPS["email"]})
    app.dependency_overrides[get_current_user] = lambda: OPS
    try:
        tc = TestClient(app)
        assert tc.get("/api/extensions").json() == {"mounts": []}
        assert tc.get("/api/extensions/dummy/ops/bundle.js").status_code == 404
        # The operator API that used to be built in is gone.
        assert tc.get("/api/admin/stats").status_code == 404
    finally:
        app.dependency_overrides.clear()
    from backend import main

    assert not main.is_spa_route("admin") and not main.is_spa_route("admin/x")
    assert extensions.operator_page_path() is None


# ---- who sees what -------------------------------------------------------------------

def test_mounts_are_filtered_by_user(client):
    client.act_as(None)
    assert client.get("/api/extensions").status_code == 401

    client.act_as(USER)
    body = client.get("/api/extensions")
    assert body.headers["cache-control"] == "private, no-store"
    assert [(m["id"], m["path"], m["section"]) for m in body.json()["mounts"]] == [("all", "/dummy-all", "workspace")]

    client.act_as(OPS)
    mounts = client.get("/api/extensions").json()["mounts"]
    assert [m["id"] for m in mounts] == ["ops", "all"]
    assert mounts[0] == {"extension": "dummy", "id": "ops", "label": "Dummy operators", "title": "Dummy operators",
                         "path": "/dummy-ops", "section": "account",
                         "bundle": "/api/extensions/dummy/ops/bundle.js"}


def test_an_unverified_operator_address_is_not_an_operator(client):
    client.act_as({**OPS, "email_verified": False})
    assert [m["id"] for m in client.get("/api/extensions").json()["mounts"]] == ["all"]
    assert client.get("/api/extensions/dummy/ops/bundle.js").status_code == 404


def test_bundle_is_refused_to_anyone_the_page_is_not_for(client):
    url = "/api/extensions/dummy/ops/bundle.js"
    client.act_as(None)
    assert client.get(url).status_code == 401
    client.act_as(USER)
    refused = client.get(url)
    # The same answer as for a page that doesn't exist: nothing given away.
    assert refused.status_code == 404 and refused.json() == {"detail": "Not Found"}
    assert "dummy operators page" not in refused.text
    assert client.get("/api/extensions/dummy/ops/assets/extra.js").status_code == 404

    client.act_as(OPS)
    ok = client.get(url)
    assert ok.status_code == 200 and "dummy operators page" in ok.text
    assert ok.headers["content-type"].startswith("text/javascript")
    assert ok.headers["cache-control"] == "private, no-store"
    assert client.get("/api/extensions/dummy/ops/assets/extra.js").text.strip() == "export const extra = 1;"
    assert client.get("/api/extensions/dummy/ops/assets/other.js").status_code == 404
    assert client.get("/api/extensions/dummy/nope/bundle.js").status_code == 404
    assert client.get("/api/extensions/nope/ops/bundle.js").status_code == 404


def test_a_page_for_everyone_is_served_to_any_signed_in_user(client):
    client.act_as(USER)
    r = client.get("/api/extensions/dummy/all/bundle.js")
    assert r.status_code == 200 and "dummy page" in r.text


# ---- the rest of the app -------------------------------------------------------------

def test_pages_get_the_app_shell_and_extend_the_script_policy(dummy):
    from backend import main
    from backend.security_headers import content_security_policy

    assert "blob:" not in content_security_policy().split("script-src", 1)[1].split(";", 1)[0]
    extensions.register(None, _dummy())
    assert main.is_spa_route("dummy-ops") and main.is_spa_route("dummy-all/sub")
    assert not main.is_spa_route("admin")
    assert "blob:" in content_security_policy().split("script-src", 1)[1].split(";", 1)[0]
    assert extensions.operator_page_path() == "/dummy-ops"


def test_content_job_runs_extension_steps(dummy, monkeypatch):
    from backend import config
    from backend.services import content_jobs

    monkeypatch.setattr(config, "UPDATE_AUTO_SEND", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", False)
    db = mongomock.MongoClient()["ext_jobs"]
    when = datetime(2026, 11, 1, 1, tzinfo=timezone.utc)
    assert content_jobs.run(db, now=when, dry_run=True)["actions"] == []

    extensions.register(None, _dummy())

    def boom(db, local, dry_run):
        raise RuntimeError("no")

    extensions.installed()[0].jobs.append(boom)
    actions = content_jobs.run(db, now=when, dry_run=True)["actions"]
    assert actions[0] == {"step": "dummy", "dry_run": True}
    assert actions[1]["step"] == "extension:dummy" and "RuntimeError" in actions[1]["error"]
