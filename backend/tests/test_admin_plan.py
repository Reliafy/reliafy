"""The Admin page's Plan tab (backend/services/admin_plan.py): GET/PUT
/api/admin/plan for operators only, the round trip, the size cap, the 404
with nothing stored, and the push_plan script."""

import logging

import mongomock
import pytest
from fastapi.testclient import TestClient

ADMIN = {"uid": "op-1", "email": "op@example.com", "name": "Op", "email_verified": True}
NOT_ADMIN = {"uid": "u-2", "email": "u2@example.com", "name": "U2", "email_verified": True}

SAMPLE = """# Example plan

Some text.

```mermaid
gantt
    title Example plan
    dateFormat YYYY-MM-DD
    section Work
    Task one :a1, 2026-01-05, 10d
    Task two :after a1, 7d
```

~~~ mermaid
graph LR
  A --> B
~~~

```python
print("not a chart")
```
"""


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {ADMIN["email"]})
    test_db = mongomock.MongoClient()["reliafy_plan_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)

    class Env:
        db = test_db
        client = TestClient(app)

        @staticmethod
        def act_as(user):
            if user is None:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = lambda: user

    try:
        yield Env
    finally:
        app.dependency_overrides.clear()


def test_signed_out_is_401(env):
    env.act_as(None)
    assert env.client.get("/api/admin/plan").status_code == 401
    assert env.client.put("/api/admin/plan", json={"markdown": "x"}).status_code == 401


def test_non_admin_is_403_and_stores_nothing(env):
    env.act_as(NOT_ADMIN)
    assert env.client.get("/api/admin/plan").status_code == 403
    res = env.client.put("/api/admin/plan", json={"markdown": "# Mine", "source": "x"})
    assert res.status_code == 403
    assert env.db.app_settings.find_one({"_id": "plan"}) is None


def test_404_when_nothing_is_stored(env):
    env.act_as(ADMIN)
    res = env.client.get("/api/admin/plan")
    assert res.status_code == 404
    body = res.json()
    assert body["code"] == "no_plan" and "No plan stored yet" in body["detail"]
    # Not the framework's own "Not Found": the smoke suite tells the two apart.
    assert body["detail"] != "Not Found"


def test_round_trip(env, caplog):
    env.act_as(ADMIN)
    with caplog.at_level(logging.DEBUG):
        res = env.client.put("/api/admin/plan", json={"markdown": SAMPLE, "source": "  org/repo@abc123  "})
    assert res.status_code == 200
    put = res.json()
    assert put["markdown"] == SAMPLE and put["source"] == "org/repo@abc123"
    assert put["updated_by"] == ADMIN["email"] and put["updated_at"]

    got = env.client.get("/api/admin/plan").json()
    assert got == put
    doc = env.db.app_settings.find_one({"_id": "plan"})
    assert doc["markdown"] == SAMPLE
    # The markdown is never logged.
    assert "Task one" not in caplog.text and "Example plan" not in caplog.text

    # A second PUT replaces it.
    env.client.put("/api/admin/plan", json={"markdown": "# v2"})
    got = env.client.get("/api/admin/plan").json()
    assert got["markdown"] == "# v2" and got["source"] == ""


def test_size_cap(env):
    from backend.services import admin_plan

    env.act_as(ADMIN)
    at_cap = "a" * admin_plan.MAX_BYTES
    assert env.client.put("/api/admin/plan", json={"markdown": at_cap}).status_code == 200
    res = env.client.put("/api/admin/plan", json={"markdown": at_cap + "b"})
    assert res.status_code == 413
    assert "limit" in res.json()["detail"] and "aaaa" not in res.text
    # Multi-byte characters count as bytes.
    res = env.client.put("/api/admin/plan", json={"markdown": "é" * (admin_plan.MAX_BYTES // 2 + 1)})
    assert res.status_code == 413
    assert env.db.app_settings.find_one({"_id": "plan"})["markdown"] == at_cap


def test_body_needs_markdown(env):
    env.act_as(ADMIN)
    assert env.client.put("/api/admin/plan", json={"source": "x"}).status_code == 422


def test_mermaid_block_count():
    from backend.services import admin_plan

    assert admin_plan.mermaid_blocks(SAMPLE) == 2
    assert admin_plan.mermaid_blocks("no charts") == 0
    assert admin_plan.mermaid_blocks("text ```mermaid inline``` text") == 0


# ---- the script ---------------------------------------------------------------------

def test_script_dry_run_prints_size_and_count_only(tmp_path, capsys, monkeypatch):
    from backend import db
    from backend.scripts import push_plan

    # A dry run never touches a database.
    monkeypatch.setattr(db, "get_db", lambda: pytest.fail("dry run opened the database"))
    path = tmp_path / "PLAN.md"
    path.write_text(SAMPLE, encoding="utf-8")
    assert push_plan.main([str(path), "--dry-run", "--source", "org/repo@abc"]) == 0
    out = capsys.readouterr()
    assert f"{len(SAMPLE.encode()):,} bytes, 2 mermaid blocks" in out.out
    assert "Dry run" in out.out
    assert "Example plan" not in out.out + out.err and "Task one" not in out.out + out.err


def test_script_stores_through_the_same_function(tmp_path, capsys, monkeypatch):
    from backend import db
    from backend.scripts import push_plan

    test_db = mongomock.MongoClient()["reliafy_plan_script_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    path = tmp_path / "PLAN.md"
    path.write_text(SAMPLE, encoding="utf-8")
    assert push_plan.main([str(path), "--source", "org/repo@abc"]) == 0
    doc = test_db.app_settings.find_one({"_id": "plan"})
    assert doc["markdown"] == SAMPLE and doc["source"] == "org/repo@abc"
    assert doc["updated_by"] == push_plan.PUSHED_BY
    assert "Example plan" not in capsys.readouterr().out


def test_script_refuses_too_large_and_missing_files(tmp_path, monkeypatch):
    from backend import db
    from backend.scripts import push_plan
    from backend.services import admin_plan

    monkeypatch.setattr(db, "get_db", lambda: pytest.fail("opened the database"))
    big = tmp_path / "BIG.md"
    big.write_text("a" * (admin_plan.MAX_BYTES + 1), encoding="utf-8")
    assert push_plan.main([str(big)]) == 1
    assert push_plan.main([str(tmp_path / "missing.md"), "--dry-run"]) == 2
