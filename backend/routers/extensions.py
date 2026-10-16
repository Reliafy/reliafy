"""Pages added by optional extensions (:mod:`backend.extensions`).

* ``GET /api/extensions`` — the pages the signed-in user may see (an empty
  list when nothing is installed).
* ``GET /api/extensions/{extension}/{page}/bundle.js`` — a page's module.
* ``GET /api/extensions/{extension}/{page}/assets/{name}`` — a file the
  module loads.

The module and its assets go only to users the page is for: anyone else gets
the same 404 as for a page that doesn't exist, and a signed-out request a
401. They're never cached by shared caches.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from backend import extensions
from backend.auth import get_current_user

router = APIRouter(prefix="/api/extensions")

_NOT_FOUND = {"detail": "Not Found"}
_NO_STORE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
_TYPES = {
    ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2",
}


@router.get("")
def list_pages(user: dict = Depends(get_current_user)) -> JSONResponse:
    return JSONResponse(content={"mounts": extensions.visible_mounts(user)},
                        headers={"Cache-Control": "private, no-store"})


def _file(path) -> FileResponse | JSONResponse:
    if path is None or not path.is_file():
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return FileResponse(path, media_type=_TYPES.get(path.suffix, "application/octet-stream"), headers=_NO_STORE)


@router.get("/{extension}/{page}/bundle.js")
def bundle(extension: str, page: str, user: dict = Depends(get_current_user)):
    mount = extensions.find_mount(extension, page)
    if mount is None or not extensions.allowed(mount, user):
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return _file(mount.bundle)


@router.get("/{extension}/{page}/assets/{name}")
def asset(extension: str, page: str, name: str, user: dict = Depends(get_current_user)):
    mount = extensions.find_mount(extension, page)
    if mount is None or not extensions.allowed(mount, user):
        return JSONResponse(status_code=404, content=_NOT_FOUND)
    return _file(mount.assets.get(name))
