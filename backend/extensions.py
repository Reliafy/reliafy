"""Optional extensions: installed packages that add API routes and pages.

An extension is a Python package that names an object in the
``reliafy.extensions`` entry-point group, for example in its
``pyproject.toml``::

    [project.entry-points."reliafy.extensions"]
    example = "example_package.extension:extension"

The object is an :class:`Extension` (or a callable returning one). It can:

* add FastAPI routers (``routers``), mounted before the app's catch-all;
* add pages (``mounts``): a built ES module that the app downloads with the
  signed-in user's credentials and runs inside its own page at ``path``
  (frontend ``ExtensionPage.jsx``). Each page says which menu section it sits
  in and who may see it (``audience``). Only those users get it in
  ``GET /api/extensions``, and only they can download its module or assets:
  anyone else gets a 404, so a page's code is never served to them;
* add steps to the scheduled content job (``jobs``, see
  :mod:`backend.services.content_jobs`).

With nothing installed the app is unchanged: no extra routes, no extra pages.
A broken extension is logged and skipped; it never stops the app starting.
``EXTENSIONS_DISABLED=true`` skips them all.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

GROUP = "reliafy.extensions"

# Who may see a page.
OPERATORS = "operators"     # ADMIN_EMAILS accounts (billing.is_admin_user)
SIGNED_IN = "signed_in"     # any signed-in account
AUDIENCES = (OPERATORS, SIGNED_IN)

# Menu sections a page can sit in. The frontend places each one; an unknown
# section falls back to "account".
SECTIONS = ("workspace", "account")

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_PATH = re.compile(r"^/[a-z0-9][a-z0-9-]{0,39}$")
_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.(js|mjs|css|json|svg|png|woff2)$")


@dataclass(frozen=True)
class Mount:
    """A page an extension adds to the app.

    ``bundle`` is an ES module exporting ``mount(element, ctx)`` (see
    ``frontend/src/extensions.js`` for ``ctx``). ``assets`` are further files
    the module may load through ``ctx.loadAsset(name)``, served under the same
    access rule. ``path`` is a single top-level segment such as ``/reports``;
    the page also owns everything below it."""

    id: str
    label: str
    path: str
    bundle: Path
    section: str = "account"
    audience: str | Callable[[dict], bool] = OPERATORS
    assets: dict[str, Path] = field(default_factory=dict)
    title: str = ""


@dataclass
class Extension:
    """What one installed package adds. ``jobs`` are callables
    ``step(db, local_now, dry_run) -> dict | None`` run by the content job."""

    name: str
    routers: list = field(default_factory=list)
    mounts: list[Mount] = field(default_factory=list)
    jobs: list[Callable[..., Any]] = field(default_factory=list)


_installed: dict[str, Extension] = {}


def installed() -> list[Extension]:
    return list(_installed.values())


def reset() -> None:
    """Forget every registered extension (tests)."""
    _installed.clear()


def disabled() -> bool:
    return os.environ.get("EXTENSIONS_DISABLED", "").strip().lower() in ("1", "true", "yes")


def _check(ext: Extension) -> None:
    if not isinstance(ext, Extension):
        raise TypeError(f"expected an Extension, got {type(ext).__name__}")
    if not _ID.match(ext.name or ""):
        raise ValueError(f"bad extension name {ext.name!r}")
    seen = set()
    for m in ext.mounts:
        if not _ID.match(m.id) or m.id in seen:
            raise ValueError(f"{ext.name}: bad or repeated mount id {m.id!r}")
        seen.add(m.id)
        if not _PATH.match(m.path):
            raise ValueError(f"{ext.name}/{m.id}: path must be one segment like /reports, got {m.path!r}")
        if not (callable(m.audience) or m.audience in AUDIENCES):
            raise ValueError(f"{ext.name}/{m.id}: unknown audience {m.audience!r}")
        for name in m.assets:
            if not _ASSET.match(name):
                raise ValueError(f"{ext.name}/{m.id}: bad asset name {name!r}")


def _move_before_catch_all(app, first_new: int) -> None:
    """Routes added after the app's catch-all (``/{full_path:path}``) would
    never be reached: move them in front of it."""
    routes = app.router.routes
    new = routes[first_new:]
    old = routes[:first_new]
    at = next((i for i, r in enumerate(old) if getattr(r, "path", "") == "/{full_path:path}"), None)
    if at is None:
        return
    routes[:] = old[:at] + new + old[at:]


def register(app, ext: Extension) -> Extension:
    """Add one extension to ``app`` (its routers) and to the registry."""
    _check(ext)
    if ext.name in _installed:
        raise ValueError(f"extension {ext.name!r} is already registered")
    if app is not None:
        first_new = len(app.router.routes)
        for router in ext.routers:
            app.include_router(router)
        _move_before_catch_all(app, first_new)
    _installed[ext.name] = ext
    return ext


def load(app) -> list[str]:
    """Discover and register every installed extension. Returns the names
    registered. Errors are logged, never raised."""
    if disabled():
        return []
    names = []
    for ep in sorted(entry_points(group=GROUP), key=lambda e: e.name):
        try:
            obj = ep.load()
            ext = obj() if callable(obj) and not isinstance(obj, Extension) else obj
            register(app, ext)
            names.append(ext.name)
            logger.info("extension loaded: %s (%d routers, %d pages)", ext.name, len(ext.routers), len(ext.mounts))
        except Exception:  # noqa: BLE001 - a broken extension never stops the app
            logger.exception("extension %r could not be loaded", ep.name)
    return names


# ---- Who sees what -----------------------------------------------------------------

def allowed(mount: Mount, user: dict | None) -> bool:
    if not user:
        return False
    if callable(mount.audience):
        try:
            return bool(mount.audience(user))
        except Exception:  # noqa: BLE001
            logger.warning("audience check failed for %s", mount.id, exc_info=True)
            return False
    if mount.audience == SIGNED_IN:
        return True
    from backend.services import billing

    return billing.is_admin_user(user)


def visible_mounts(user: dict | None) -> list[dict]:
    """The pages ``user`` may see, as the frontend needs them."""
    out = []
    for ext in installed():
        for m in ext.mounts:
            if allowed(m, user):
                out.append({
                    "extension": ext.name, "id": m.id, "label": m.label, "title": m.title or m.label,
                    "path": m.path, "section": m.section if m.section in SECTIONS else "account",
                    "bundle": f"/api/extensions/{ext.name}/{m.id}/bundle.js",
                })
    return out


def find_mount(ext_name: str, mount_id: str) -> Mount | None:
    ext = _installed.get(ext_name)
    if ext is None:
        return None
    return next((m for m in ext.mounts if m.id == mount_id), None)


def page_roots() -> set[str]:
    """The first path segments of every installed page (for the SPA routes)."""
    return {m.path.strip("/") for ext in installed() for m in ext.mounts}


def operator_page_path() -> str | None:
    """The first installed page for operators, if any (e.g. for a link in
    an operator notification)."""
    return next((m.path for ext in installed() for m in ext.mounts if m.audience == OPERATORS), None)


def has_pages() -> bool:
    return any(ext.mounts for ext in installed())


def job_steps() -> list[tuple[str, Callable[..., Any]]]:
    return [(ext.name, step) for ext in installed() for step in ext.jobs]
