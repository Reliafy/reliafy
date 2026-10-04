"""Fault trees whose gates reuse sub-trees are sized before they are drawn,
and Open-PSA parameter expressions are evaluated within a step limit."""

import time
import tracemalloc

from backend.services.rbd_import import RbdImportError, galileo, openpsa


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the caller checks which
        out = exc
    return out, time.perf_counter() - start


def _doubling_galileo(depth: int) -> bytes:
    lines = ['toplevel "g%d";' % depth, '"g0" or "a" "b";', '"a" lambda=0.001;', '"b" lambda=0.002;']
    lines += [f'"g{i}" or "g{i - 1}" "g{i - 1}";' for i in range(1, depth + 1)]
    return "\n".join(lines).encode()


def test_galileo_tree_with_shared_subtrees_is_refused_quickly():
    data = _doubling_galileo(30)
    assert len(data) < 1000
    tracemalloc.start()
    try:
        out, seconds = _timed(galileo.parse, data, "nested.dft")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert isinstance(out, RbdImportError), out
    assert "more than 5000 blocks" in str(out)
    assert seconds < 1.0
    assert peak < 20 * 1024 * 1024


def test_shared_subtrees_within_the_block_limit_still_import():
    (diagram,) = galileo.parse(_doubling_galileo(5), "nested.dft")
    blocks = [n for n in diagram.graph["nodes"] if n["type"] not in ("input", "output")]
    assert len(blocks) == 2 ** 6  # every appearance drawn: 2 events x 2^5


def test_openpsa_tree_with_shared_gates_is_refused_quickly():
    gates = ['<define-gate name="g0"><or><basic-event name="A"/><basic-event name="B"/></or></define-gate>']
    gates += [f'<define-gate name="g{i}"><or><gate name="g{i - 1}"/><gate name="g{i - 1}"/></or></define-gate>'
              for i in range(1, 31)]
    xml = f"""<?xml version="1.0"?><opsa-mef><define-fault-tree name="FT">{''.join(gates)}</define-fault-tree>
      <model-data>
        <define-basic-event name="A"><exponential><float value="1e-3"/><system-mission-time/></exponential></define-basic-event>
        <define-basic-event name="B"><exponential><float value="2e-3"/><system-mission-time/></exponential></define-basic-event>
      </model-data></opsa-mef>""".encode()
    out, seconds = _timed(openpsa.parse, xml, "tree.xml")
    assert isinstance(out, RbdImportError), out
    assert seconds < 1.0


def test_openpsa_parameters_built_from_each_other_are_bounded():
    params = ['<define-parameter name="p0"><float value="1e-6"/></define-parameter>']
    params += [f'<define-parameter name="p{i}"><add><parameter name="p{i - 1}"/><parameter name="p{i - 1}"/>'
               f'</add></define-parameter>' for i in range(1, 60)]
    xml = f"""<?xml version="1.0"?><opsa-mef><define-fault-tree name="FT">
      <define-gate name="Top"><or><basic-event name="A"/><basic-event name="B"/></or></define-gate>
      </define-fault-tree><model-data>{''.join(params)}
        <define-basic-event name="A"><exponential><parameter name="p59"/><system-mission-time/></exponential></define-basic-event>
        <define-basic-event name="B"><exponential><float value="2e-3"/><system-mission-time/></exponential></define-basic-event>
      </model-data></opsa-mef>""".encode()
    out, seconds = _timed(openpsa.parse, xml, "params.xml")
    assert isinstance(out, RbdImportError), out
    assert "too large to evaluate" in str(out)
    assert seconds < 10.0
