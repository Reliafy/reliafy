"""The library pins Reliafy runs: SurPyval 0.27, the version RePyability 0.18
targets (the pin rule: never bump SurPyval on its own).

Bump these with the pins (requirements.txt / the lock, the Dockerfile and its
"RePyability vX.Y" comment, and the CI workflows' commit).
"""

import importlib.metadata as md
import re
from pathlib import Path

import repyability
import surpyval as sp

from backend.services import rbd_export

SURPYVAL = "0.27"
REPYABILITY = "0.18"
_ROOT = Path(__file__).resolve().parents[2]


def test_the_installed_libraries_are_the_pins():
    assert sp.__version__ == SURPYVAL and md.version("surpyval") == SURPYVAL
    assert repyability.__version__ == REPYABILITY and md.version("repyability") == REPYABILITY


def test_download_as_python_installs_the_pinned_tags():
    """The install line users are given names the released tag (v0.18), not
    the commit the Dockerfile pins."""
    assert rbd_export.detect_versions() == {"surpyval": SURPYVAL, "repyability": REPYABILITY}
    assert rbd_export.install_commands()[-1].endswith(f'RePyability.git@v{REPYABILITY}"')


def test_the_dockerfile_names_the_tag_of_the_commit_it_installs():
    """The Dockerfile's "RePyability vX.Y" comment is what the export reads;
    it must agree with the RePyability its commit installs (CI installs the
    same commit), and every workflow installs that commit."""
    docker = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    named = re.findall(r"RePyability v([0-9]+\.[0-9][\w.\-]*)", docker)
    assert named and set(named) == {REPYABILITY}
    (commit,) = set(re.findall(r"RePyability\.git@([0-9a-f]{40})", docker))
    for wf in ("ci.yml", "guide-screenshots.yml"):
        text = (_ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        assert set(re.findall(r"RePyability\.git@([0-9a-f]{40})", text)) == {commit}, wf
