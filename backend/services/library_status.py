"""Where SurPyval, RePyability and Reliafy stand, and what to do next (the
admin page's Libraries tab).

The founder's rule: **Reliafy runs the latest RePyability, and pins SurPyval
to the version that RePyability release targets** (the lower bound of its
``surpyval`` requirement on PyPI). :func:`next_steps` turns a snapshot of the
facts into "Up to date" or the steps in order; it's pure, so the cases are
unit-tested. :func:`status` gathers the facts: this process's own (installed
versions, Cloud Run revision, whether the accelerators are active) and
GitHub's and PyPI's, through :mod:`remote_json` (cached, 3 s timeouts, never
raising). A part that can't be fetched comes back as ``{"error": ...}`` and
the page shows it as unavailable.
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import sys
import time
from typing import Any, Callable

from backend.services import remote_json

RELIAFY = {"name": "Reliafy", "repo": "Reliafy/reliafy", "release": "main", "integration": "dev"}
SURPYVAL = {"name": "SurPyval", "repo": "derrynknife/SurPyval", "package": "surpyval",
            "release": "master", "integration": "develop"}
REPYABILITY = {"name": "RePyability", "repo": "derrynknife/RePyability", "package": "repyability",
               "release": "master", "integration": "dev"}
LIBRARIES = (SURPYVAL, REPYABILITY)

PR_LIMIT = 30


# ---- Versions -----------------------------------------------------------------

_VERSION = re.compile(r"^[vV]?(\d+(?:\.\d+)*)$")


def parse_version(value: Any) -> tuple[int, ...] | None:
    """``"v0.24.0"`` -> ``(0, 24)``; ``None`` for anything that isn't a plain
    release number (pre-releases, branch-like tags)."""
    m = _VERSION.match(str(value or "").strip())
    if not m:
        return None
    parts = [int(p) for p in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def show_version(value: Any) -> str | None:
    """A version as the page shows it: ``"v0.18.0"`` -> ``"0.18"``."""
    v = parse_version(value)
    if v is None:
        return None
    parts = list(v) + [0] * max(0, 2 - len(v))
    return ".".join(str(p) for p in parts)


def newer(a: Any, b: Any) -> bool:
    """Whether version ``a`` is newer than ``b`` (False when either is unknown)."""
    va, vb = parse_version(a), parse_version(b)
    return va is not None and vb is not None and va > vb


def same(a: Any, b: Any) -> bool:
    va, vb = parse_version(a), parse_version(b)
    return va is not None and va == vb


def latest(versions: list[Any]) -> str | None:
    """The newest of ``versions`` (displayed form), ignoring unparseable ones."""
    known = [v for v in versions if parse_version(v) is not None]
    return show_version(max(known, key=parse_version)) if known else None


_REQ = re.compile(r"^\s*surpyval\s*(\[[^\]]*\])?\s*\(?([^;)]*)\)?\s*(;.*)?$", re.I)


def surpyval_requirement(requires_dist: list[str] | None) -> tuple[str | None, str | None]:
    """RePyability's ``surpyval`` requirement and the version it targets: the
    lower bound (``>=0.23`` / ``==0.23`` / ``~=0.23`` -> ``0.23``)."""
    for req in requires_dist or []:
        m = _REQ.match(str(req))
        if not m or (m.group(3) and "extra" in m.group(3)):
            continue
        spec = m.group(2).strip()
        target = None
        for part in spec.split(","):
            pm = re.match(r"^\s*(>=|==|~=)\s*([\w.]+?)(\.\*)?\s*$", part)
            if pm and parse_version(pm.group(2)) is not None:
                target = show_version(pm.group(2))
        return spec or None, target
    return None, None


# ---- The rule -----------------------------------------------------------------

def _count_prs(prs: dict[str, int | None]) -> str:
    waiting = [f"{n} in {name}" for name, n in prs.items() if n]
    return ", ".join(waiting)


def next_steps(s: dict) -> dict:
    """"Up to date", or what to do next, in order, from a snapshot:

    ``installed_surpyval``, ``installed_repyability`` (this deployment),
    ``latest_surpyval``, ``latest_repyability`` (newest on PyPI or GitHub),
    ``repyability_targets`` (the SurPyval version the latest RePyability
    targets), ``accelerators`` (``None`` when the image has none, else
    ``{"fits": bool, "simulations": bool}``), ``ci_main`` (the latest main
    run's conclusion), ``dev_ahead`` (Reliafy dev's commits ahead of main),
    ``repyability_dev_ahead``, ``prs`` (``{repo name: open count}``) and
    ``unknown`` (what couldn't be checked).

    Each step is ``{"kind": "do" | "wait" | "info", "text": ...}``; "do"
    steps come first. Up to date = no "do" step.
    """
    steps: list[dict] = []
    do = lambda text: steps.append({"kind": "do", "text": text})  # noqa: E731
    inst_sp, inst_rp = s.get("installed_surpyval"), s.get("installed_repyability")
    new_sp, new_rp = s.get("latest_surpyval"), s.get("latest_repyability")
    target = s.get("repyability_targets")

    if s.get("ci_main") == "failure":
        do("CI is failing on main: fix it before the next deploy.")

    acc = s.get("accelerators")
    if acc is not None:
        off = [k for k in ("fits", "simulations") if not acc.get(k)]
        if off:
            do(f"Accelerators off for {' and '.join(off)} in this revision: check its startup logs.")

    repy_behind = newer(new_rp, inst_rp)
    if repy_behind:
        move = target and not same(target, inst_sp)
        if move:
            do(f"RePyability {show_version(new_rp)} released: adopt it in Reliafy (requirements, "
               f"Dockerfile, CI pins), move SurPyval to {target}, rebuild the accelerators for both "
               "versions, then deploy.")
        else:
            do(f"RePyability {show_version(new_rp)} released: adopt it in Reliafy (requirements, "
               "Dockerfile, CI pins), then deploy.")
    elif target and inst_sp and not same(target, inst_sp):
        do(f"Reliafy runs SurPyval {show_version(inst_sp)}, but RePyability {show_version(inst_rp)} "
           f"targets {target}: pin SurPyval to {target}, rebuild the fits accelerator, then deploy.")

    if new_rp and newer(new_sp, target):
        text = (f"SurPyval {show_version(new_sp)} released; RePyability {show_version(new_rp)} targets "
                f"{target}. When RePyability releases for {show_version(new_sp)}: adopt it in Reliafy, "
                f"move SurPyval to {show_version(new_sp)}, rebuild the accelerators for both versions.")
        ahead = s.get("repyability_dev_ahead")
        if ahead:
            text += f" RePyability dev is {ahead} commit{'s' if ahead != 1 else ''} ahead of master."
        steps.append({"kind": "wait", "text": text})

    ahead = s.get("dev_ahead")
    if ahead:
        steps.append({"kind": "info", "text": f"Reliafy dev is {ahead} commit{'s' if ahead != 1 else ''} "
                                              "ahead of main: release it when ready."})
    waiting = _count_prs(s.get("prs") or {})
    if waiting:
        steps.append({"kind": "info", "text": f"Open PRs waiting: {waiting}."})
    unknown = s.get("unknown") or []
    if unknown:
        steps.append({"kind": "info", "text": f"Couldn't check {', '.join(unknown)}: the answer may be incomplete."})

    steps.sort(key=lambda st: {"do": 0, "wait": 1, "info": 2}[st["kind"]])
    up = not any(st["kind"] == "do" for st in steps)
    if up:
        headline = "Up to date"
        if inst_rp and inst_sp:
            note = (f"Reliafy runs RePyability {show_version(inst_rp)}, the latest, and SurPyval "
                    f"{show_version(inst_sp)}" + (", the version it targets." if same(target, inst_sp) else "."))
        else:
            note = ""
    else:
        headline, note = steps[0]["text"], ""
    return {"up_to_date": up, "headline": headline, "note": note, "steps": steps}


# ---- This process ---------------------------------------------------------------

def accelerator_state() -> dict | None:
    """Whether the accelerators are active in this process: ``{"fits": bool,
    "simulations": bool}``, or ``None`` when the image has none.

    The deploy's runtime overlay keeps its state as a module-level dict with
    ``fits`` and ``sims`` entries ("active (...)" or "off: why") and a
    ``status()`` function; the startup log lines ("fits: active" /
    "simulations: active") print the same strings. It's found by that shape,
    so nothing here depends on its name, and only the booleans leave."""
    for mod in list(sys.modules.values()):
        d = getattr(mod, "__dict__", None)
        if not isinstance(d, dict):
            continue
        st, fn = d.get("_state"), d.get("status")
        if not (isinstance(st, dict) and "fits" in st and "sims" in st and callable(fn)):
            continue
        try:
            got = fn()
            st = got if isinstance(got, dict) else st
        except Exception:  # noqa: BLE001 - report what the module already holds
            pass
        return {"fits": str(st.get("fits") or "").startswith("active"),
                "simulations": str(st.get("sims") or "").startswith("active")}
    return None


def _installed(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def runtime_info() -> dict:
    return {
        "surpyval": _installed("surpyval"),
        "repyability": _installed("repyability"),
        "revision": os.environ.get("K_REVISION") or None,
        "commit": (os.environ.get("COMMIT_SHA") or "").strip()[:12] or None,
        "accelerators": accelerator_state(),
    }


# ---- GitHub and PyPI ------------------------------------------------------------

def _urls(repo: dict) -> dict[str, str]:
    r = repo["repo"]
    u = {
        "prs": remote_json.github(f"repos/{r}/pulls?state=open&per_page={PR_LIMIT}"),
        "compare": remote_json.github(f"repos/{r}/compare/{repo['release']}...{repo['integration']}?per_page=1"),
    }
    if repo.get("package"):
        u["releases"] = remote_json.github(f"repos/{r}/releases?per_page=10")
        u["tags"] = remote_json.github(f"repos/{r}/tags?per_page=20")
        u["pypi"] = remote_json.pypi(repo["package"])
    else:
        for branch in (repo["release"], repo["integration"]):
            u[f"ci_{branch}"] = remote_json.github(
                f"repos/{r}/actions/workflows/ci.yml/runs?branch={branch}&event=push&per_page=1")
    return u


def _unavailable(res) -> dict:
    return {"error": res.error or "unavailable"}


def _prs(res) -> dict:
    if res.data is None:
        return _unavailable(res)
    items = [{"number": p.get("number"), "title": p.get("title"), "url": p.get("html_url"),
              "draft": bool(p.get("draft")), "branch": (p.get("head") or {}).get("ref")}
             for p in res.data if isinstance(p, dict)]
    return {"count": len(items), "more": len(items) >= PR_LIMIT, "items": items}


def _compare(res, repo: dict) -> dict:
    if res.data is None:
        return _unavailable(res)
    d = res.data
    return {"integration": repo["integration"], "release": repo["release"],
            "ahead": d.get("ahead_by"), "behind": d.get("behind_by"),
            "url": f"https://github.com/{repo['repo']}/compare/{repo['release']}...{repo['integration']}"}


def _ci(res) -> dict:
    if res.data is None:
        return _unavailable(res)
    runs = res.data.get("workflow_runs") or []
    if not runs:
        return {"status": "none"}
    run = runs[0]
    return {"status": run.get("status"), "conclusion": run.get("conclusion"), "url": run.get("html_url"),
            "at": run.get("created_at"), "sha": (run.get("head_sha") or "")[:7]}


def _github_latest(releases, tags, repo: dict) -> dict:
    """The newest GitHub release or tag (SurPyval's later versions are tags
    with no Release)."""
    if releases.data is None and tags.data is None:
        return _unavailable(releases if releases.error else tags)
    found: list[dict] = []
    for rel in releases.data or []:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        found.append({"version": rel.get("tag_name"), "kind": "release", "url": rel.get("html_url"),
                      "at": rel.get("published_at")})
    for tag in tags.data or []:
        name = tag.get("name")
        found.append({"version": name, "kind": "tag", "at": None,
                      "url": f"https://github.com/{repo['repo']}/tree/{name}"})
    found = [f for f in found if parse_version(f["version"]) is not None]
    if not found:
        return {"error": "no releases"}
    # A release beats a bare tag of the same version (it has notes and a date).
    best = max(found, key=lambda f: (parse_version(f["version"]), f["kind"] == "release"))
    return {**best, "version": show_version(best["version"])}


def _pypi(res, package: str) -> dict:
    if res.data is None:
        return _unavailable(res)
    info = res.data.get("info") or {}
    version = info.get("version")
    files = (res.data.get("releases") or {}).get(version) or []
    out = {"version": show_version(version) or version, "url": f"https://pypi.org/project/{package}/{version}/",
           "at": (files[0].get("upload_time_iso_8601") if files else None)}
    if package == "repyability":
        spec, target = surpyval_requirement(info.get("requires_dist"))
        out["requires_surpyval"] = spec
        out["targets_surpyval"] = target
    return out


_last_refresh = {"at": 0.0}
REFRESH_EVERY = 60  # seconds: the Refresh button is honoured at most this often


def refresh_allowed(now: float | None = None) -> tuple[bool, int]:
    """(allowed, seconds to wait). Records the refresh when allowed."""
    now = time.time() if now is None else now
    wait = int(REFRESH_EVERY - (now - _last_refresh["at"]))
    if wait > 0:
        return False, wait
    _last_refresh["at"] = now
    return True, 0


def status(*, refresh: bool = False, fetch: Callable[..., dict] | None = None,
           runtime: Callable[[], dict] = runtime_info) -> dict:
    """Everything the Libraries tab shows, with the answer first."""
    fetch = fetch or remote_json.get_many
    plan = {repo["name"]: _urls(repo) for repo in (RELIAFY, *LIBRARIES)}
    results = fetch([u for urls in plan.values() for u in urls.values()], refresh=refresh)
    got = {name: {k: results[u] for k, u in urls.items()} for name, urls in plan.items()}

    here = runtime()
    rel = got[RELIAFY["name"]]
    reliafy = {
        "installed": {"surpyval": show_version(here["surpyval"]) or here["surpyval"],
                      "repyability": show_version(here["repyability"]) or here["repyability"]},
        "revision": here.get("revision"),
        "commit": here.get("commit"),
        "accelerators": here.get("accelerators"),
        "prs": _prs(rel["prs"]),
        "branches": _compare(rel["compare"], RELIAFY),
        "ci": {b: _ci(rel[f"ci_{b}"]) for b in (RELIAFY["release"], RELIAFY["integration"])},
        "repo_url": f"https://github.com/{RELIAFY['repo']}",
    }
    libs = {}
    for repo in LIBRARIES:
        g = got[repo["name"]]
        libs[repo["package"]] = {
            "name": repo["name"],
            "repo_url": f"https://github.com/{repo['repo']}",
            "github": _github_latest(g["releases"], g["tags"], repo),
            "pypi": _pypi(g["pypi"], repo["package"]),
            "prs": _prs(g["prs"]),
            "branches": _compare(g["compare"], repo),
        }

    def newest(lib: dict) -> str | None:
        return latest([lib["github"].get("version"), lib["pypi"].get("version")])

    sp, rp = libs["surpyval"], libs["repyability"]
    unknown = [lib["name"] + "'s releases" for lib in (sp, rp)
               if "error" in lib["github"] and "error" in lib["pypi"]]
    if "error" in rp["pypi"]:
        unknown.append("the SurPyval version RePyability targets")
    target = rp["pypi"].get("targets_surpyval")
    # PyPI's metadata is for its own latest; if GitHub is ahead of PyPI the
    # target is that of an older release, so it isn't used.
    if target and newer(rp["github"].get("version"), rp["pypi"].get("version")):
        target = None
    snapshot = {
        "installed_surpyval": here["surpyval"],
        "installed_repyability": here["repyability"],
        "latest_surpyval": newest(sp),
        "latest_repyability": newest(rp),
        "repyability_targets": target,
        "accelerators": here.get("accelerators"),
        "ci_main": reliafy["ci"]["main"].get("conclusion"),
        "dev_ahead": reliafy["branches"].get("ahead"),
        "repyability_dev_ahead": rp["branches"].get("ahead"),
        "prs": {name: part.get("count") for name, part in
                (("Reliafy", reliafy["prs"]), ("SurPyval", sp["prs"]), ("RePyability", rp["prs"]))},
        "unknown": unknown,
    }
    fetched = [r.fetched_at for r in results.values() if r.fetched_at]
    return {
        "answer": next_steps(snapshot),
        "rule": "Reliafy runs the latest RePyability, and pins SurPyval to the version that "
                "RePyability release targets.",
        "reliafy": reliafy,
        "surpyval": sp,
        "repyability": rp,
        "checked_at": min(fetched) if fetched else None,
        "github_authenticated": remote_json.github_authenticated(),
    }
