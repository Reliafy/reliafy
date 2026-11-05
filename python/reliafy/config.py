"""Where ``reliafy login`` keeps the token and server: ``config.json`` in the
user config directory (``$RELIAFY_CONFIG_DIR``; else ``%APPDATA%\\reliafy`` on
Windows, ``$XDG_CONFIG_HOME/reliafy`` or ``~/.config/reliafy`` elsewhere),
readable by the user only."""

from __future__ import annotations

import json
import os


def config_dir() -> str:
    if os.environ.get("RELIAFY_CONFIG_DIR"):
        return os.environ["RELIAFY_CONFIG_DIR"]
    if os.name == "nt" and os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "reliafy")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "reliafy")


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def load() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> str:
    """Write the config (user-only permissions); returns its path."""
    path = config_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - e.g. some Windows filesystems
        pass
    return path


def clear() -> bool:
    try:
        os.remove(config_path())
        return True
    except OSError:
        return False
