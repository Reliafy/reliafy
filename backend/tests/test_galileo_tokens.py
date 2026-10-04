"""Galileo text is tokenised, comment-stripped and sniffed in linear time."""

import time

import pytest

from backend.services.rbd_import import RbdImportError, galileo


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the caller checks which
        out = exc
    return out, time.perf_counter() - start


@pytest.mark.parametrize("payload", [
    b" " * 200_000,
    b"\n" * 200_000,
    b'toplevel "a";' + b" " * 200_000 + b"=",
    b'"' + b'\\"' * 100_000,
    b"/*" * 100_000,
    b"//" * 100_000,
    b'"A" lambda' + b" " * 200_000 + b"= 1;",
])
def test_galileo_text_is_read_in_linear_time(payload):
    from backend.services import uploads

    out, seconds = _timed(galileo.parse, payload, "x.dft")
    assert isinstance(out, (RbdImportError, list)), out
    assert seconds < 0.1
    _, seconds = _timed(galileo.sniff, payload, "x")
    assert seconds < 0.1
    _, seconds = _timed(uploads.detect_format, payload[:65536])
    assert seconds < 0.1


def test_galileo_statements_have_a_length_limit():
    data = b'toplevel "S";\n"S" or ' + b'"A" ' * 20_000 + b";"
    with pytest.raises(RbdImportError, match="longer than 64 KB"):
        galileo.parse(data, "x.dft")


def test_galileo_tokens_match_the_format():
    toks = galileo._tokens('"Sys" or "A b" "C\\"x" D lambda = 1e-4 repair= 0.1 dorm =0.5')
    assert toks == [("Sys", True), ("or", False), ("A b", True), ('C\\"x', True), ("D", False),
                    ("lambda=1e-4", False), ("repair=0.1", False), ("dorm=0.5", False)]
    assert galileo._tokens('x"y"z') == [("x", False), ("y", True), ("z", False)]
    assert galileo._strip_comments("a /* b */ c // d\ne /* f") == "a   c \ne /* f"
    assert galileo.sniff(b'// model\n  toplevel "S";\n"S" or "A";', "")
    assert galileo.sniff(b'TOPLEVEL "S";', "")
    assert not galileo.sniff(b"toplevelish;", "")
