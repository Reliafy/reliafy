"""Every Download as Python script checks the installed SurPyval (and, for a
diagram, RePyability) before it imports them, and an older or missing one
stops with a plain message that says exactly what to install."""

import ast
import importlib.metadata
from importlib.metadata import PackageNotFoundError

import pytest

from backend.services import python_export as px
from backend.services import rbd_export
from backend.tests.python_scripts import assert_checks_versions_first
from backend.tests.test_rbd_export_text import PLAIN, _network, _nonrepairable, _phased, _repairable, _script

V = {"surpyval": "0.28", "repyability": "0.19.1"}


def _px_script(**kw) -> str:
    """A script head the way every model kind builds it (life, mixture,
    non-parametric, regression, accelerated life, repairable, degradation,
    test plans all start from ``python_export.header``; each one's own
    script tests run it through ``python_scripts.run``, which asserts the
    check comes first; the joint model's test does the same)."""
    return px.assemble(px.header("Pumps", "a Weibull life model.", **kw),
                       ["import surpyval", "from surpyval import Weibull", ""])


SCRIPTS = {
    "model": lambda: _px_script(),
    "model with repyability": lambda: _px_script(needs_repyability=True),
    **{f"rbd {b.__name__.strip('_')}": (lambda b=b: _script(b, PLAIN)) for b in
       (_nonrepairable, _phased, _network, _repairable)},
}


@pytest.mark.parametrize("kind", list(SCRIPTS))
def test_each_script_kind_checks_versions_before_importing_a_library(kind):
    source = SCRIPTS[kind]()
    assert_checks_versions_first(source)
    tree = ast.parse(source)
    # Straight after the docstring: the check's function, then its call.
    assert isinstance(tree.body[1], ast.FunctionDef) and tree.body[1].name == "_check_versions"
    assert ast.unparse(tree.body[2]) == "_check_versions()"


def _run_check(source: str, installed: dict, monkeypatch):
    """Run only the script's check (its function and call), with
    ``importlib.metadata.version`` answering from ``installed``."""
    def fake(name):
        if installed.get(name) is None:
            raise PackageNotFoundError(name)
        return installed[name]

    monkeypatch.setattr(importlib.metadata, "version", fake)
    tree = ast.parse(source)
    check = ast.Module(body=tree.body[1:3], type_ignores=[])
    exec(compile(check, "exported.py", "exec"), {"__name__": "__main__"})  # noqa: S102 - the app's own script


def test_an_older_surpyval_stops_with_what_to_install(monkeypatch):
    source = _px_script()
    with pytest.raises(SystemExit) as stop:
        _run_check(source, {"surpyval": "0.27.2"}, monkeypatch)
    message = str(stop.value.code)
    assert "This script needs surpyval 0.28 or later (surpyval 0.27.2 is installed)." in message
    assert 'pip install "surpyval>=0.28"' in message


def test_a_diagram_names_both_libraries_and_a_missing_one(monkeypatch):
    source = rbd_export.to_python(_nonrepairable(PLAIN)[0], PLAIN, resolve_model=None, versions=V)
    with pytest.raises(SystemExit) as stop:
        _run_check(source, {"surpyval": "0.11"}, monkeypatch)
    message = str(stop.value.code)
    assert "surpyval 0.11 is installed; repyability isn't installed" in message
    assert 'pip install "surpyval>=0.28" "repyability>=0.19.1"' in message


@pytest.mark.parametrize("installed", [{"surpyval": "0.28"}, {"surpyval": "0.28.1"}, {"surpyval": "1.0rc1"},
                                       {"surpyval": "0.30.dev4"}])
def test_the_version_made_with_or_newer_runs_on(installed, monkeypatch):
    _run_check(_px_script(), installed, monkeypatch)


def test_a_diagram_with_new_enough_libraries_runs_on(monkeypatch):
    source = rbd_export.to_python(_nonrepairable(PLAIN)[0], PLAIN, resolve_model=None, versions=V)
    _run_check(source, {"surpyval": "0.28", "repyability": "0.19.1"}, monkeypatch)
    with pytest.raises(SystemExit):
        _run_check(source, {"surpyval": "0.28", "repyability": "0.19"}, monkeypatch)
