"""The admin page's Libraries tab: the "what's next" rule, the GitHub / PyPI
gathering (mocked), the cache, and the admin-only endpoint."""

import sys
import types

import pytest

from backend.services import library_status as L
from backend.services import remote_json
from backend.services.remote_json import Result

UP_TO_DATE = {
    "installed_surpyval": "0.23", "installed_repyability": "0.13",
    "latest_surpyval": "0.23", "latest_repyability": "0.13", "repyability_targets": "0.23",
    "accelerators": {"fits": True, "simulations": True}, "ci_main": "success",
    "dev_ahead": 0, "repyability_dev_ahead": 0, "prs": {}, "unknown": [],
}


def steps(**changes):
    return L.next_steps({**UP_TO_DATE, **changes})


# ---- Versions -------------------------------------------------------------------

def test_versions():
    assert L.parse_version("v0.24.0") == (0, 24) == L.parse_version("0.24")
    assert L.parse_version("0.24rc1") is None and L.parse_version("main") is None
    assert L.show_version("v0.18.0") == "0.18" and L.show_version("1") == "1.0"
    assert L.newer("0.24", "v0.23.1") and not L.newer("0.23", "0.23.0") and not L.newer(None, "0.1")
    assert L.latest(["v0.18.0", "v0.24", "0.23", "nightly", None]) == "0.24"


def test_surpyval_requirement():
    assert L.surpyval_requirement(["numpy>=2", "surpyval>=0.23", "tqdm"]) == (">=0.23", "0.23")
    assert L.surpyval_requirement(["surpyval (>=0.24,<0.25)"]) == (">=0.24,<0.25", "0.24")
    assert L.surpyval_requirement(["surpyval==0.23.*"]) == ("==0.23.*", "0.23")
    assert L.surpyval_requirement(['surpyval>=9; extra == "dev"']) == (None, None)
    assert L.surpyval_requirement(None) == (None, None)


# ---- The rule ---------------------------------------------------------------------

def test_up_to_date():
    a = steps()
    assert a["up_to_date"] and a["headline"] == "Up to date" and a["steps"] == []
    assert "RePyability 0.13, the latest, and SurPyval 0.23, the version it targets" in a["note"]


def test_surpyval_released_ahead_of_repyability_is_a_wait_not_a_task():
    a = steps(latest_surpyval="0.24", repyability_dev_ahead=47)
    assert a["up_to_date"] and a["headline"] == "Up to date"
    (wait,) = a["steps"]
    assert wait["kind"] == "wait"
    assert wait["text"].startswith("SurPyval 0.24 released; RePyability 0.13 targets 0.23. When RePyability "
                                   "releases for 0.24: adopt it in Reliafy, move SurPyval to 0.24, rebuild "
                                   "the accelerators for both versions.")
    assert "47 commits ahead" in wait["text"]


def test_new_repyability_on_the_same_surpyval():
    a = steps(latest_repyability="0.14")
    assert not a["up_to_date"]
    assert a["headline"] == ("RePyability 0.14 released: adopt it in Reliafy (requirements, Dockerfile, "
                             "CI pins), then deploy.")


def test_new_repyability_that_moves_surpyval():
    a = steps(latest_repyability="0.14", latest_surpyval="0.24", repyability_targets="0.24")
    assert "move SurPyval to 0.24, rebuild the accelerators for both versions" in a["headline"]
    assert [s["kind"] for s in a["steps"]] == ["do"]  # 0.24 is targeted: nothing to wait for


def test_surpyval_off_its_target():
    a = steps(installed_surpyval="0.24")
    assert a["headline"].startswith("Reliafy runs SurPyval 0.24, but RePyability 0.13 targets 0.23: "
                                    "pin SurPyval to 0.23")


def test_order_ci_and_accelerators_first_then_libraries_then_info():
    a = steps(ci_main="failure", accelerators={"fits": True, "simulations": False},
              latest_repyability="0.14", latest_surpyval="0.24", dev_ahead=3,
              prs={"Reliafy": 2, "SurPyval": 0, "RePyability": 1})
    texts = [s["text"] for s in a["steps"]]
    assert texts[0] == "CI is failing on main: fix it before the next deploy."
    assert texts[1].startswith("Accelerators off for simulations")
    assert texts[2].startswith("RePyability 0.14 released")
    assert texts[3].startswith("SurPyval 0.24 released")
    assert texts[4] == "Reliafy dev is 3 commits ahead of main: release it when ready."
    assert texts[5] == "Open PRs waiting: 2 in Reliafy, 1 in RePyability."
    assert a["headline"] == texts[0]


def test_no_accelerators_in_the_image_is_not_a_task():
    assert steps(accelerators=None)["up_to_date"]


def test_unknowns_are_said():
    a = steps(latest_repyability=None, repyability_targets=None, unknown=["RePyability's releases"])
    assert a["up_to_date"]
    assert a["steps"][-1]["text"].startswith("Couldn't check RePyability's releases")


# ---- Gathering, mocked ------------------------------------------------------------

def _pr(n, title, branch="feature/x"):
    return {"number": n, "title": title, "html_url": f"https://github.com/x/pull/{n}",
            "draft": False, "head": {"ref": branch}}


def _answers(**overrides):
    gh = remote_json.github
    data = {
        gh("repos/Reliafy/reliafy/pulls?state=open&per_page=30"): [_pr(379, "Content for October", "content/oct")],
        gh("repos/Reliafy/reliafy/compare/main...dev?per_page=1"): {"ahead_by": 0, "behind_by": 1},
        gh("repos/Reliafy/reliafy/actions/workflows/ci.yml/runs?branch=main&event=push&per_page=1"):
            {"workflow_runs": [{"status": "completed", "conclusion": "success", "html_url": "u",
                                "created_at": "2026-10-12T05:35:23Z", "head_sha": "f51ca87abc"}]},
        gh("repos/Reliafy/reliafy/actions/workflows/ci.yml/runs?branch=dev&event=push&per_page=1"):
            {"workflow_runs": []},
        gh("repos/derrynknife/SurPyval/pulls?state=open&per_page=30"): [_pr(858, "Docs")],
        gh("repos/derrynknife/SurPyval/compare/master...develop?per_page=1"): {"ahead_by": 64, "behind_by": 10},
        gh("repos/derrynknife/SurPyval/releases?per_page=10"):
            [{"tag_name": "v0.18.0", "html_url": "r", "published_at": "2026-08-03T00:00:00Z"}],
        gh("repos/derrynknife/SurPyval/tags?per_page=20"): [{"name": "v0.24"}, {"name": "v0.23"}],
        remote_json.pypi("surpyval"): {"info": {"version": "0.24", "requires_dist": []},
                                       "releases": {"0.24": [{"upload_time_iso_8601": "2026-10-09T19:46:38Z"}]}},
        gh("repos/derrynknife/RePyability/pulls?state=open&per_page=30"): [],
        gh("repos/derrynknife/RePyability/compare/master...dev?per_page=1"): {"ahead_by": 47, "behind_by": 2},
        gh("repos/derrynknife/RePyability/releases?per_page=10"):
            [{"tag_name": "v0.13", "html_url": "r13", "published_at": "2026-10-09T11:59:53Z"}],
        gh("repos/derrynknife/RePyability/tags?per_page=20"): [{"name": "v0.13"}],
        remote_json.pypi("repyability"): {"info": {"version": "0.13",
                                                   "requires_dist": ["numpy>=2", "surpyval>=0.23"]},
                                          "releases": {"0.13": []}},
    }
    data.update(overrides)
    calls = []

    def fetch(urls, refresh=False):
        calls.append((list(urls), refresh))
        assert set(urls) == set(data), set(urls) ^ set(data)
        return {u: (data[u] if isinstance(data[u], Result) else Result(data[u], None, 1000.0)) for u in urls}

    return fetch, calls


RUNTIME = {"surpyval": "0.23", "repyability": "0.13", "revision": "reliafy-00130-abc",
           "commit": None, "accelerators": {"fits": True, "simulations": True}}


def test_status_with_mocked_github_and_pypi():
    fetch, calls = _answers()
    s = L.status(fetch=fetch, runtime=lambda: dict(RUNTIME))
    assert len(calls[0][0]) == 14 and calls[0][1] is False  # one batch: 12 GitHub, 2 PyPI
    assert s["answer"]["up_to_date"] and s["answer"]["steps"][0]["kind"] == "wait"
    sp, rp, rel = s["surpyval"], s["repyability"], s["reliafy"]
    assert sp["github"] == {"version": "0.24", "kind": "tag", "at": None,
                            "url": "https://github.com/derrynknife/SurPyval/tree/v0.24"}
    assert sp["pypi"]["version"] == "0.24" and sp["branches"]["ahead"] == 64
    assert rp["github"]["kind"] == "release" and rp["github"]["version"] == "0.13"
    assert rp["pypi"]["requires_surpyval"] == ">=0.23" and rp["pypi"]["targets_surpyval"] == "0.23"
    assert rp["prs"] == {"count": 0, "more": False, "items": []}
    assert rel["installed"] == {"surpyval": "0.23", "repyability": "0.13"}
    assert rel["prs"]["items"][0]["branch"] == "content/oct"
    assert rel["ci"]["main"]["conclusion"] == "success" and rel["ci"]["main"]["sha"] == "f51ca87"
    assert rel["ci"]["dev"] == {"status": "none"}
    assert s["checked_at"] == 1000.0


def test_a_failed_part_is_unavailable_not_an_error():
    gh = remote_json.github
    fetch, _ = _answers(**{
        remote_json.pypi("repyability"): Result(error="timed out"),
        gh("repos/derrynknife/RePyability/releases?per_page=10"): Result(error="rate limited"),
        gh("repos/derrynknife/RePyability/tags?per_page=20"): Result(error="rate limited"),
        gh("repos/Reliafy/reliafy/pulls?state=open&per_page=30"): Result(error="rate limited"),
    })
    s = L.status(fetch=fetch, runtime=lambda: dict(RUNTIME))
    assert s["repyability"]["pypi"] == {"error": "timed out"}
    assert s["repyability"]["github"] == {"error": "rate limited"}
    assert s["reliafy"]["prs"] == {"error": "rate limited"}
    texts = [st["text"] for st in s["answer"]["steps"]]
    assert any(t.startswith("Couldn't check RePyability's releases, the SurPyval version") for t in texts)


def test_new_repyability_found_on_github():
    gh = remote_json.github
    fetch, _ = _answers(**{gh("repos/derrynknife/RePyability/tags?per_page=20"): [{"name": "v0.14"}]})
    a = L.status(fetch=fetch, runtime=lambda: dict(RUNTIME))["answer"]
    # PyPI's 0.13 metadata doesn't say what 0.14 targets, so it isn't guessed.
    assert a["headline"].startswith("RePyability 0.14 released: adopt it in Reliafy")
    assert "move SurPyval" not in a["headline"]


def test_accelerators_found_by_shape_and_reported_as_booleans(monkeypatch):
    assert L.accelerator_state() is None
    mod = types.ModuleType("overlay_for_test")
    mod._state = {"fits": "active (x, 11 families)", "sims": "off: no kernel"}
    mod.status = lambda: dict(mod._state)
    monkeypatch.setitem(sys.modules, "overlay_for_test", mod)
    assert L.accelerator_state() == {"fits": True, "simulations": False}


def test_runtime_info(monkeypatch):
    monkeypatch.setenv("K_REVISION", "reliafy-00130-abc")
    monkeypatch.setenv("COMMIT_SHA", "f51ca87abcdef0123")
    info = L.runtime_info()
    assert info["revision"] == "reliafy-00130-abc" and info["commit"] == "f51ca87abcde"
    assert L.parse_version(info["surpyval"]) and L.parse_version(info["repyability"])


def test_refresh_is_rate_limited(monkeypatch):
    monkeypatch.setitem(L._last_refresh, "at", 0.0)
    assert L.refresh_allowed(now=1000.0) == (True, 0)
    assert L.refresh_allowed(now=1030.0) == (False, 30)
    assert L.refresh_allowed(now=1061.0) == (True, 0)


# ---- The cache --------------------------------------------------------------------

def test_cache_ttl_etag_and_stale_on_failure(monkeypatch):
    remote_json.clear()
    seen = []
    replies = iter([(200, {"etag": '"v1"'}, {"n": 1}), (304, {}, None), (403, {"x-ratelimit-remaining": "0"}, None)])

    def http_get(url, headers):
        seen.append(headers.get("If-None-Match"))
        return next(replies)

    monkeypatch.setattr(remote_json, "_http_get", http_get)
    url = remote_json.github("repos/a/b")
    t = [1000.0]
    first = remote_json.get(url, now=lambda: t[0])
    assert first.data == {"n": 1} and first.error is None
    t[0] += 60
    assert remote_json.get(url, now=lambda: t[0]).data == {"n": 1} and seen == [None]  # cached
    t[0] += remote_json.TTL
    again = remote_json.get(url, now=lambda: t[0])  # revalidated: 304
    assert again.data == {"n": 1} and seen == [None, '"v1"'] and again.fetched_at == t[0]
    stale = remote_json.get(url, refresh=True, now=lambda: t[0])  # rate limited: last answer, marked
    assert stale.data == {"n": 1} and stale.error == "rate limited" and stale.stale
    remote_json.clear()


def test_cache_failure_without_a_previous_answer(monkeypatch):
    import httpx

    remote_json.clear()

    def boom(url, headers):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(remote_json, "_http_get", boom)
    r = remote_json.get(remote_json.pypi("surpyval"))
    assert r.data is None and r.error == "timed out"


def test_token_is_sent_only_to_github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert remote_json._headers(remote_json.github("x"), None)["Authorization"] == "Bearer t0ken"
    assert "Authorization" not in remote_json._headers(remote_json.pypi("surpyval"), None)
    assert remote_json.github_authenticated()


# ---- The endpoint -----------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    app.dependency_overrides[get_current_user] = lambda: {"uid": "op", "email": "op@ops.example.org",
                                                          "email_verified": True}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_endpoint_is_admin_only_and_rate_limits_refresh(client, monkeypatch):
    from backend import config

    calls = []

    def fake_status(*, refresh=False):
        calls.append(refresh)
        return {"answer": {"up_to_date": True}}

    monkeypatch.setattr(L, "status", fake_status)
    monkeypatch.setitem(L._last_refresh, "at", 0.0)
    assert client.get("/api/admin/libraries").status_code == 403 and calls == []
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@ops.example.org"})
    r = client.get("/api/admin/libraries")
    assert r.status_code == 200 and r.json()["answer"]["up_to_date"] and calls == [False]
    assert client.get("/api/admin/libraries?refresh=true").json()["refresh"]["done"] is True
    limited = client.get("/api/admin/libraries?refresh=true").json()["refresh"]
    assert limited["done"] is False and limited["limited"] is True and limited["retry_in"] > 0
    assert calls == [False, True, False]
