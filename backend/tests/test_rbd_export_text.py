""""Download as Python" keeps every piece of diagram text inside its own
docstring, comment or string literal: whatever a name, unit, label or note
holds, the generated script has exactly the statements the exporter writes.

Each diagram is exported twice, once with plain text and once with text full
of quotes, backslashes, line breaks and comment markers in every text field;
both scripts must compile to the same top-level statements, and the marker
name in the text must never become code.
"""

import ast
import json

import pytest

from backend.services import rbd_export, rbd_json

MARKER = "TEXT_MARKER"
# Quotes that would end a docstring or string, line breaks that would end a
# comment, a backslash escape and continuation, and a trailing quote.
ODD = (f'Q"""\n{MARKER}()\n"""\r\n{MARKER}() \\N{{x}} \\\n\'\'\' {MARKER}() '
       f' {MARKER}() # =1+2 @x ""{MARKER}()"')
PLAIN = "Plain text"


def _w(alpha, beta, **extra):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}], **extra}


def _ln(mu, sigma):
    return {"source": "params", "distribution": "LogNormal", "distribution_id": "lognormal",
            "params": [{"name": "mu", "value": mu}, {"name": "sigma", "value": sigma}]}


def _node(nid, ntype, label, **data):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "data": {"label": label, **data}}


def _io():
    return [_node("input", "input", "Input"), _node("output", "output", "Output")]


def _chain(*ids):
    seq = ["input", *ids, "output"]
    return [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(zip(seq, seq[1:]))]


def _saved_model(t):
    """A saved-model resolver whose model name and description are ``t``."""
    def resolve(model_id):
        return {"name": t, "kind": "parametric", "distribution_id": "weibull", "distribution": t,
                "params": [{"name": "alpha", "value": 500.0}, {"name": "beta", "value": 1.5}],
                "unit": t}
    return resolve


def _nonrepairable(t):
    """Every non-repairable block type, placeholders, a nested sub-system,
    a repeated block, pins, a schedule, capacities and phases, all named ``t``."""
    odd_id = f"id {t}"
    nodes = [
        *_io(),
        _node(odd_id, "component", t, model=_w(900, 1.4)),
        _node("saved", "component", t, model={"modelId": "m1", "name": t}),
        _node("s1", "series", t, n=2, model=_w(5000, 2.0)),
        _node("p1", "parallel", t, n=2, model=_w(700, 1.5)),
        _node("h1", "standby", t, spares=1, cold=False, model=_w(900, 1.4), standbyModel=_w(600, 1.1)),
        _node("w1", "standby", t, spares=1, dormancy=0.3, model=_w(900, 1.4)),
        _node("c1", "standby", t, spares=1, cold=True, startProb=0.9, model=_w(900, 1.4)),
        _node("sub", "subsystem", t, rbd={"id": "rbd-sub", "name": t}),
        _node("gone", "subsystem", t, rbd={"id": "rbd-gone", "name": t}),
        _node("none", "component", t),
        _node("ph", "component", t, model={**_w(1, 1), "kind": "regression", "distribution": t, "name": t}),
        _node("np", "component", t, model={"kind": "nonparametric", "distribution": t, "name": t}),
        _node("odd", "component", t, model={"distribution_id": t, "distribution": t, "params": []}),
        _node("ls", "loadshare", t, model=_w(1, 1)),
        _node("tvc", "component", t, model=_w(900, 1.4),
              covariate_schedules={t: {"expression": t}, "x": {"table": [{"value": t, "t": 0}]}}),
        _node("pin", "component", t, state="working"),
        _node("rep", "component", t, repeat_of=odd_id),
        _node("k", "knode", t, n=1),
        _node("cap", "component", t, model=_w(900, 1.4), capacity=10),
    ]
    order = [odd_id, "saved", "s1", "p1", "h1", "w1", "c1", "sub", "gone", "none", "ph", "np", "odd", "ls",
             "tvc", "pin", "rep", "k", "cap"]
    graph = {
        "unit": t,
        "nodes": nodes,
        "edges": _chain(*order),
        "ccf_groups": [{"members": [odd_id, "saved"], "beta": 0.1}],
        "production": {"demand": 5, "unit": t[:20], "period": 10},
    }
    sub = {"unit": t, "nodes": [*_io(), _node("n1", "component", t, model=_w(800, 1.2)),
                                 _node("n2", "subsystem", t, rbd={"id": "rbd-sub", "name": t})],
           "edges": _chain("n1", "n2")}
    return graph, {"rbd-sub": sub}.get


def _phased(t):
    graph = {"unit": t, "nodes": [*_io(), _node("a", "component", t, model=_w(900, 1.4)),
                                  _node("b", "component", t, model=_w(500, 1.2))],
             "edges": _chain("a", "b"),
             "phases": [{"name": "1 " + t, "duration": 1.0, "not_needed": ["b"]},
                        {"name": "2 " + t, "duration": 2.0}]}
    return graph, None


def _network(t):
    graph = {"unit": t, "network": {},
             "nodes": [*_io(), _node("a", "component", t, model=_w(900, 1.4)),
                       _node("b", "component", t, model=_w(500, 1.2)),
                       _node("k", "knode", t, n=1)],
             "edges": _chain("a", "b", "k")}
    return graph, None


def _repairable(t):
    """Repairable blocks with costs, maintenance, a maintenance group,
    standby, placeholders, pins, common cause and capacities, named ``t``."""
    rep = _ln(1.0, 0.4)
    nodes = [
        *_io(),
        _node("a", "component", t, model=_w(900, 1.4), repair=rep, costs={"repair": 100},
              preventive={"policy": "age", "interval": 300, "cost": 10}, maintenance_group=t, capacity=10),
        _node("b", "component", t, model=_w(900, 1.4), repair=rep, inspection={"interval": 50, "cost": 1}),
        _node("m", "component", t, model=_w(900, 1.4), repair=rep, maintenance_group=t,
              preventive={"policy": "age", "interval": 200}),
        _node("q", "component", t, model=_w(900, 1.4), repair=rep, repair_quality={"model": t, "q": 0.5}),
        _node("sb", "standby", t, spares=1, model=_w(900, 1.4), repair=rep),
        _node("nr", "component", t, model=_w(900, 1.4)),
        _node("sr", "series", t, n=2, model=_w(900, 1.4)),
        _node("saved", "component", t, model={"modelId": "m1", "name": t}, repair=rep),
        _node("pin", "component", t, state="failed"),
        _node("k", "knode", t, n=1),
    ]
    graph = {
        "repairable": True, "unit": t,
        "nodes": nodes,
        "edges": _chain("a", "b", "m", "q", "sb", "nr", "sr", "saved", "pin", "k"),
        "ccf_groups": [{"members": ["a", "b"], "beta": 0.1}],
        "maintenance_groups": {t: {"setup_cost": 50.0}},
        "costs": {"downtime_rate": 10},
        "production": {"demand": 5, "unit": t[:20], "period": 10},
    }
    return graph, None


def _script(build, t):
    graph, resolve_sub = build(t)
    return rbd_export.to_python(graph, t, resolve_model=_saved_model(t), resolve_subsystem=resolve_sub,
                                versions={"surpyval": "0.0", "repyability": "0.0"})


def _shape(tree):
    return [type(s).__name__ for s in tree.body]


@pytest.mark.parametrize("build", [_nonrepairable, _phased, _network, _repairable])
def test_diagram_text_stays_in_docstrings_comments_and_strings(build):
    code = _script(build, ODD)
    tree = ast.parse(compile(code, "diagram.py", "exec", ast.PyCF_ONLY_AST))

    # The text never becomes a name, a call or an attribute.
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not any(MARKER in name for name in names)

    # Only the module docstring is a bare expression; everything else at the
    # top level is an import, a constant, a function or the __main__ guard.
    assert isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value.value, str)
    allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.If, ast.Raise)
    assert all(isinstance(s, allowed) for s in tree.body[1:]), _shape(tree)
    for s in tree.body:
        if isinstance(s, ast.If):
            assert ast.unparse(s.test) == "__name__ == '__main__'"

    # Exactly the statements the same diagram with plain text gets.
    plain = ast.parse(_script(build, PLAIN))
    assert _shape(tree) == _shape(plain)

    # The text is still there, as text.
    assert MARKER in ast.get_docstring(tree)
    assert MARKER in code


def test_header_docstring_neutralises_quotes_and_backslashes():
    graph = {"unit": 'h"""x\\', "nodes": [*_io(), _node("a", "component", 'A"""\\', model={})],
             "edges": _chain("a")}
    code = rbd_export.to_python(graph, 'N"""\\', versions={"surpyval": "0.0", "repyability": "0.0"})
    doc = ast.get_docstring(ast.parse(code))
    assert doc.startswith("N'''/")
    assert "Times are in h'''x/." in doc
    assert "A'''/." in doc  # the placeholder list
    assert '"""' not in code.split('"""', 2)[1]


def test_docstring_text_helper():
    assert rbd_export._doc_text('a"""b') == "a'''b"
    assert rbd_export._doc_text('a""b"c') == "a''b\"c"
    assert rbd_export._doc_text("a\\b\nc\rd") == "a/b c d"


def test_production_unit_stays_on_its_comment_line():
    graph, _ = _repairable(PLAIN)
    graph["production"]["unit"] = f"t\n{MARKER}()"
    code = rbd_export.to_python(graph, "P", versions={"surpyval": "0.0", "repyability": "0.0"})
    tree = ast.parse(code)
    assert MARKER not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert f"(t {MARKER}())" in code


def _json_graph(t, repairable):
    """Blocks the RePyability JSON format holds, every text field ``t``."""
    rep = _ln(1.0, 0.4) if repairable else None
    extra = {"repair": rep} if repairable else {}
    odd_id = f"id {t}"
    nodes = [*_io(),
             _node(odd_id, "component", t, model=_w(900, 1.4), **extra),
             _node("b", "component", t, model=_w(900, 1.4), **extra,
                   **({"maintenance_group": t, "costs": {"repair": 5}} if repairable else {})),
             _node("k", "knode", t, n=1)]
    graph = {"unit": t, "repairable": repairable, "nodes": nodes, "edges": _chain(odd_id, "b", "k"),
             "ccf_groups": [{"members": [odd_id, "b"], "beta": 0.1}]}
    if repairable:
        graph["maintenance_groups"] = {t: {"setup_cost": 5.0}}
    return graph


@pytest.mark.parametrize("repairable", [False, True])
def test_json_export_keeps_text_as_data(repairable):
    doc = rbd_json.to_document(_json_graph(ODD, repairable), ODD)
    back = json.loads(rbd_json.to_json(doc))
    assert back["reliafy"]["name"] == ODD
    assert back["reliafy"]["graph"]["unit"] == ODD
    assert back["reliafy"]["graph"]["nodes"][2]["data"]["label"] == ODD
    # The script for the same diagram compiles to the plain diagram's statements.
    code = rbd_export.to_python(_json_graph(ODD, repairable), ODD)
    plain = rbd_export.to_python(_json_graph(PLAIN, repairable), PLAIN)
    assert _shape(ast.parse(code)) == _shape(ast.parse(plain))
