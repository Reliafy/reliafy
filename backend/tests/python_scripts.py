"""Shared by the Download as Python tests: run a generated script in its own
process and read the numbers it printed."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from backend.services.python_export import read_printed


def run(source: str, tmp_path: Path, name: str = "exported.py", timeout: int = 300) -> dict:
    """Run ``source`` as a standalone script (isolated: no repo on the path)
    and return what it printed, read by ``read_printed``; ``_stdout`` holds
    the raw text."""
    assert_checks_versions_first(source)
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    proc = subprocess.run([sys.executable, "-I", str(path)], cwd=tmp_path, capture_output=True, text=True,
                          timeout=timeout)
    assert proc.returncode == 0, f"script failed:\n{proc.stderr[-4000:]}\n--- script ---\n{source[:4000]}"
    out = read_printed(proc.stdout)
    out["_stdout"] = proc.stdout
    return out


_LIBRARY_IMPORT = re.compile(r"^(?:import|from) (?:surpyval|repyability)\b", re.M)


def assert_checks_versions_first(source: str) -> None:
    """The script checks the installed library versions before it imports
    either library (so an older one stops with what to install)."""
    call = re.search(r"^_check_versions\(\)$", source, re.M)
    assert call, "the script doesn't check the installed versions"
    first = _LIBRARY_IMPORT.search(source)
    assert first is None or call.start() < first.start(), "a library is imported before the version check"


def close(printed, expected, rel: float = 2e-5, abs_: float = 1e-9) -> None:
    """A printed number (6 significant figures) equals the page's."""
    if expected is None:
        assert printed is None, (printed, expected)
        return
    assert printed is not None, f"nothing printed for {expected}"
    assert printed == pytest.approx(float(expected), rel=max(rel, 6e-6), abs=abs_), (printed, expected)
