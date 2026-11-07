"""What error responses say: the app's own refusals go back as written; anything
unexpected is logged and answered with a generic sentence and a reference."""

import logging
import re

import numpy as np
import pytest

from backend.errors import GENERIC, client_message, client_reason, user_facing


class _AppRefusal(Exception):
    pass


_AppRefusal.__module__ = "backend.services.example"


def test_the_apps_own_refusals_keep_their_words():
    assert client_message(_AppRefusal("Name is too long (at most 80 characters).")) == \
        "Name is too long (at most 80 characters)."
    assert client_message(ValueError("x must be positive")) == "x must be positive"
    assert client_message(NotImplementedError("Standby groups need a simulation.")) == \
        "Standby groups need a simulation."


def test_a_key_error_subclass_reads_without_quotes():
    class Missing(KeyError):
        pass

    Missing.__module__ = "backend.services.example"
    assert client_message(Missing("No such model.")) == "No such model."


@pytest.mark.parametrize("exc", [TypeError("unsupported operand type(s) for +: 'int' and 'str'"),
                                 KeyError("graph"), RuntimeError("boom"), ZeroDivisionError("division by zero")])
def test_anything_else_is_logged_and_answered_generically(exc, caplog):
    with caplog.at_level(logging.ERROR, logger="reliafy.errors"):
        text = client_message(exc)
    assert text.startswith(GENERIC) and str(exc) not in text
    ref = re.search(r"reference ([0-9a-f]{10})", text).group(1)
    record = next(r for r in caplog.records if ref in r.getMessage())
    assert record.exc_info[1] is exc


def test_a_fallback_replaces_the_generic_sentence():
    assert client_message(TypeError("internal"), "Invalid schedule.") == "Invalid schedule."
    assert client_message(ValueError(""), "Invalid model.") == "Invalid model."
    assert client_message(ValueError("Bad shape"), "Invalid model.") == "Bad shape"


def test_text_that_looks_like_a_traceback_is_never_relayed():
    exc = ValueError('Traceback (most recent call last):\n  File "/srv/app.py", line 1')
    assert client_message(exc).startswith(GENERIC)
    assert client_message(ValueError("x" * 5000)).startswith(GENERIC)
    assert client_message(ValueError({"not": "text"})).startswith(GENERIC)


def test_a_reason_inside_a_sentence_drops_its_full_stop():
    assert client_reason(ValueError("Too few failures.")) == "Too few failures"
    assert client_reason(RuntimeError("x")).startswith(GENERIC)


def test_extra_types_can_be_named_user_facing():
    class Upload(Exception):
        pass

    Upload.__module__ = "multipart.exceptions"
    assert not user_facing(Upload("Too many files."))
    assert client_message(Upload("Too many files."), also=(Upload,)) == "Too many files."


def test_a_failing_mode_in_grays_test_leaves_no_internal_text(monkeypatch):
    from backend.services import compare_groups as cg

    def fails(*a, **k):
        raise RuntimeError("internal state at 0x7f00")

    monkeypatch.setattr(cg, "gray_test", fails)
    x = np.arange(1.0, 13.0)
    c = np.array([0] * 12)
    n = np.ones(12)
    lab = np.array(["A", "B"] * 6)
    cause = np.array(["seal", "bearing", "seal"] * 4, dtype=object)
    out = cg._gray(x, c, n, lab, cause, ["A", "B"])
    errors = [r["error"] for r in out["results"] if "error" in r]
    assert errors and all(e.startswith(GENERIC) and "0x7f00" not in e for e in errors)


def test_a_refusal_through_a_route_keeps_its_words(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import compute_app
    from backend.services.rbd_analysis import AnalysisError

    def refuse(*a, **k):
        raise AnalysisError("Pump A: a standby group needs at least two units.")

    monkeypatch.setattr(compute_app, "execute", refuse)
    r = TestClient(compute_app.app).post("/compute/availability", json={"graph": {}, "options": {}})
    assert r.status_code == 422
    assert r.json() == {"detail": "Pump A: a standby group needs at least two units."}
