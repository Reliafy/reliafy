"""The build id: one identity per image build, so an open browser tab can tell
that the server has been updated under it.

The Docker build bakes the id into the frontend bundle (``VITE_BUILD_ID``) and
writes the same value to ``frontend/dist/build-id.txt``; the server reads it
from there (or from the ``RELIAFY_BUILD_ID`` environment variable). With no id
(local dev, tst, a plain ``npm run build``) nothing is sent and the browser's
check is off.
"""

from __future__ import annotations

import os
from pathlib import Path

HEADER = "X-Reliafy-Build"
_FILE = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "build-id.txt"


def current_build_id() -> str:
    env = os.environ.get("RELIAFY_BUILD_ID", "").strip()
    if env:
        return env
    try:
        return _FILE.read_text().strip()
    except OSError:
        return ""


class BuildIdMiddleware:
    """Pure ASGI: adds ``X-Reliafy-Build`` to every ``/api/*`` response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        build = current_build_id() if scope["type"] == "http" else ""
        if not build or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        value = build.encode()

        async def send_with_build(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in (message.get("headers") or []) if k.lower() != b"x-reliafy-build"]
                headers.append((b"x-reliafy-build", value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_build)
