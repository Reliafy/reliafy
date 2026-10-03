"""Open-PSA MEF import (backend/services/rbd_import/openpsa.py).

All fixtures are hand-written for these tests (the public MEF example
repositories carry no licence, so none of their files are copied here).
"""

import numpy as np
import pytest

from backend.services import rbd_analysis
from backend.services.rbd_graph import normalize_graph
from backend.services.rbd_import import openpsa
from backend.services.rbd_import.types import RbdImportError


def load(xml: str, filename: str = "model.xml"):
    diagrams = openpsa.parse(xml.encode(), filename)
    for d in diagrams:
        normalize_graph(d.graph)
    return diagrams


def one(xml: str):
    (d,) = load(xml)
    return d


def by_label(graph, label):
    (node,) = [n for n in graph["nodes"] if n.get("label") == label]
    return node


def exp_event(name, rate):
    return (f'<define-basic-event name="{name}"><exponential><float value="{rate}"/>'
            f'<system-mission-time/></exponential></define-basic-event>')


# A two-train cooling system: both trains must fail (AND); each train fails if
# its pump or valve fails (OR); a 2-of-3 sensor vote and a support system in
# series; parameters with units; beta-factor common cause on the pumps.
TWO_TRAIN = f"""<?xml version="1.0"?>
<opsa-mef name="cooling">
  <define-fault-tree name="Cooling">
    <define-gate name="Top">
      <label>Loss of cooling</label>
      <or>
        <gate name="BothTrains"/>
        <atleast min="2">
          <basic-event name="Sensor1"/><basic-event name="Sensor2"/><basic-event name="Sensor3"/>
        </atleast>
        <basic-event name="Support"/>
      </or>
    </define-gate>
    <define-gate name="BothTrains">
      <and><gate name="TrainA"/><gate name="TrainB"/></and>
    </define-gate>
    <define-gate name="TrainA"><or><event name="PumpA"/><basic-event name="ValveA"/></or></define-gate>
    <define-gate name="TrainB"><or><event name="PumpB"/><basic-event name="ValveB"/></or></define-gate>
  </define-fault-tree>
  <model-data>
    <define-basic-event name="ValveA"><exponential><parameter name="ValveRate"/><system-mission-time/></exponential></define-basic-event>
    <define-basic-event name="ValveB"><exponential><parameter name="ValveRate"/><system-mission-time/></exponential></define-basic-event>
    {exp_event("Sensor1", 2e-4)}{exp_event("Sensor2", 2e-4)}{exp_event("Sensor3", 2e-4)}
    <define-basic-event name="Support">
      <Weibull><float value="50000"/><float value="1.5"/><float value="0"/><system-mission-time/></Weibull>
    </define-basic-event>
    <define-parameter name="ValveRate" unit="hours-1"><mul><float value="2"/><float value="5e-5"/></mul></define-parameter>
    <define-parameter name="PumpRate" unit="hours-1"><lognormal-deviate><float value="3e-4"/><float value="3"/><float value="0.95"/></lognormal-deviate></define-parameter>
  </model-data>
  <define-CCF-group name="Pumps" model="beta-factor">
    <members><basic-event name="PumpA"/><basic-event name="PumpB"/></members>
    <distribution><exponential><parameter name="PumpRate"/><system-mission-time/></exponential></distribution>
    <factor level="2"><float value="0.1"/></factor>
  </define-CCF-group>
</opsa-mef>
"""


def test_sniff():
    assert openpsa.sniff(b'<?xml version="1.0"?>\n<opsa-mef>', "x.xml")
    assert openpsa.sniff(b"<open-psa pure='true'>", "x")
    assert not openpsa.sniff(b'toplevel "T";', "x.dft")


def test_two_train_structure_units_ccf_and_approximations():
    d = one(TWO_TRAIN)
    g = d.graph
    assert d.name == "Cooling — Top"
    assert g["unit"] == "hours"
    assert by_label(g, "ValveA")["model"]["params"][0] == {"name": "failure_rate", "value": 1e-4}
    assert by_label(g, "Support")["model"]["distribution_id"] == "weibull"
    # Pump rates come from the CCF group's distribution (mean of the deviate).
    assert by_label(g, "PumpA")["model"]["params"][0]["value"] == 3e-4
    assert any("mean value" in w and "PumpA" in w for w in d.warnings)
    ids = {n["label"]: n["id"] for n in g["nodes"]}
    assert g["ccf_groups"] == [{"members": [ids["PumpA"], ids["PumpB"]], "beta": 0.1}]
    (v,) = [n for n in g["nodes"] if n["type"] == "knode"]
    assert (v["n"], v["k"]) == (2, 3)


def test_two_train_reliability_matches_closed_form_without_ccf():
    d = one(TWO_TRAIN.replace('model="beta-factor"', 'model="MGL"'))
    assert any("MGL" in w for w in d.warnings) and "ccf_groups" not in d.graph
    res = rbd_analysis.analyze(normalize_graph(d.graph), t_max=20000)
    t = np.asarray(res["time"])
    train = np.exp(-(3e-4 + 1e-4) * t)
    both_fail = (1 - train) ** 2
    s = np.exp(-2e-4 * t)
    vote = 3 * s**2 - 2 * s**3
    support = np.exp(-((t / 50000) ** 1.5))
    expected = (1 - both_fail) * vote * support
    assert np.allclose(res["system"]["sf"], expected, rtol=1e-9, atol=1e-12)


def test_ccf_lowers_reliability():
    ccf = rbd_analysis.analyze(normalize_graph(one(TWO_TRAIN).graph), t_max=20000)
    assert ccf["ccf"]["reliability_with"] < ccf["ccf"]["reliability_without"]


def test_glm_gives_repair_and_all_glm_is_repairable():
    xml = """<opsa-mef><define-gate name="T"><or><basic-event name="A"/>
        <atleast min="2"><basic-event name="B1"/><basic-event name="B2"/><basic-event name="B3"/></atleast>
        </or></define-gate>
        <define-basic-event name="A"><GLM><float value="0"/><float value="1e-4"/><float value="0.1"/><system-mission-time/></GLM></define-basic-event>
        <define-basic-event name="B1"><GLM><float value="0"/><float value="1e-3"/><float value="0.5"/><system-mission-time/></GLM></define-basic-event>
        <define-basic-event name="B2"><GLM><float value="0"/><float value="1e-3"/><float value="0.5"/><system-mission-time/></GLM></define-basic-event>
        <define-basic-event name="B3"><GLM><float value="0.01"/><float value="1e-3"/><float value="0.5"/><system-mission-time/></GLM></define-basic-event>
        </opsa-mef>"""
    d = one(xml)
    assert d.graph["repairable"] is True
    assert by_label(d.graph, "A")["repair"]["params"][0]["value"] == 0.1
    assert any("γ" in w and "B3" in w for w in d.warnings)
    assert rbd_analysis.validate_graph(normalize_graph(d.graph))["valid"]
    # A single non-GLM event -> repair dropped with a warning.
    d = one(xml.replace('<define-basic-event name="A"><GLM><float value="0"/><float value="1e-4"/>'
                        '<float value="0.1"/><system-mission-time/></GLM>',
                        '<define-basic-event name="A"><exponential><float value="1e-4"/>'
                        '<system-mission-time/></exponential>'))
    assert not d.graph.get("repairable") and "repair" not in by_label(d.graph, "B1")
    assert any("Repair rates" in w for w in d.warnings)


def test_weibull_offset_periodic_test_and_time_multiple_are_warned():
    d = one("""<opsa-mef><define-gate name="T"><or>
        <basic-event name="W"/><basic-event name="P"/><basic-event name="X"/></or></define-gate>
        <define-basic-event name="W"><Weibull><float value="1000"/><float value="2"/><float value="50"/><system-mission-time/></Weibull></define-basic-event>
        <define-basic-event name="P"><periodic-test><float value="1e-5"/><float value="720"/><float value="0"/><system-mission-time/></periodic-test></define-basic-event>
        <define-basic-event name="X"><exponential><float value="1e-6"/><mul><int value="20"/><system-mission-time/></mul></exponential></define-basic-event>
        </opsa-mef>""")
    assert any("t0" in w and "“W”" in w for w in d.warnings)
    assert any("Periodically tested" in w and "“P”" in w for w in d.warnings)
    assert by_label(d.graph, "X")["model"]["params"][0]["value"] == pytest.approx(2e-5)
    assert by_label(d.graph, "P")["model"]["params"][0]["value"] == 1e-5


def test_house_events_and_constants_fold():
    d = one("""<opsa-mef><define-gate name="T"><or>
        <basic-event name="A"/>
        <and><basic-event name="B"/><house-event name="Maintenance"/></and>
        <and><basic-event name="C"/><constant value="true"/></and>
        </or></define-gate>
        <define-house-event name="Maintenance"><constant value="false"/></define-house-event>
        """ + exp_event("A", 1e-3) + exp_event("B", 1e-3) + exp_event("C", 1e-3) + "</opsa-mef>")
    labels = {n["label"] for n in d.graph["nodes"]}
    assert labels == {"Input", "Output", "A", "C"}


def test_private_names_are_scoped_to_their_fault_tree():
    xml = "<opsa-mef>" + "".join(f"""
      <define-fault-tree name="{ft}">
        <define-gate name="root" role="private"><or><basic-event name="{ft}-a"/><gate name="sub"/></or></define-gate>
        <define-gate name="sub" role="private"><and><basic-event name="{ft}-b"/><basic-event name="{ft}-c"/></and></define-gate>
      </define-fault-tree>""" for ft in ("Left", "Right")) + "<model-data>" + "".join(
        exp_event(f"{ft}-{x}", 1e-3) for ft in ("Left", "Right") for x in "abc") + "</model-data></opsa-mef>"
    diagrams = load(xml)
    assert sorted(d.name for d in diagrams) == ["Left — Left.root", "Right — Right.root"]
    for d in diagrams:
        side = d.name.split(" ")[0]
        assert {n["label"] for n in d.graph["nodes"] if n["type"] == "component"} == {
            f"{side}-a", f"{side}-b", f"{side}-c"}


def test_xfta_open_psa_root_and_mission_time():
    d = one("""<?xml version="1.0"?><!DOCTYPE open-psa>
        <open-psa pure="true">
          <define-gate name="failed"><or><basic-event name="A.failure"/><basic-event name="B.failure"/></or></define-gate>
          <define-gate name="unused"><true/></define-gate>
          <define-basic-event name="A.failure"><exponential><parameter name="A.lambda"/><mission-time/></exponential></define-basic-event>
          <define-basic-event name="B.failure"><exponential><float value="2e-3"/><mission-time/></exponential></define-basic-event>
          <define-parameter name="A.lambda"><float value="1e-3"/></define-parameter>
        </open-psa>""")
    assert {n["label"] for n in d.graph["nodes"] if n["type"] == "component"} == {"A.failure", "B.failure"}
    assert any("unused" in w for w in d.warnings)  # the other top event, reported


@pytest.mark.parametrize("formula, match", [
    ('<not><basic-event name="A"/></not>', "NOT"),
    ('<xor><basic-event name="A"/><basic-event name="B"/></xor>', "XOR"),
    ('<nand><basic-event name="A"/><basic-event name="B"/></nand>', "NAND"),
    ('<cardinality min="1" max="1"><basic-event name="A"/><basic-event name="B"/></cardinality>', "upper bound"),
])
def test_non_coherent_logic_is_refused(formula, match):
    xml = f'<opsa-mef><define-gate name="T">{formula}</define-gate>{exp_event("A", 1)}{exp_event("B", 1)}</opsa-mef>'
    with pytest.raises(RbdImportError, match=match):
        load(xml)


def test_cardinality_up_to_n_is_atleast():
    xml = ('<opsa-mef><define-gate name="T"><cardinality min="2" max="3"><basic-event name="A"/>'
           '<basic-event name="B"/><basic-event name="C"/></cardinality></define-gate>'
           + exp_event("A", 1) + exp_event("B", 1) + exp_event("C", 1) + "</opsa-mef>")
    (v,) = [n for n in one(xml).graph["nodes"] if n["type"] == "knode"]
    assert (v["n"], v["k"]) == (2, 3)


def test_fixed_probability_events_import_as_flagged_placeholders():
    # #188: a demand failure (fixed probability, no failure-time model) no
    # longer refuses the file — it becomes a placeholder exponential block.
    xml = ('<opsa-mef><define-gate name="T"><or><gate name="Pumps"/><basic-event name="MCC"/>'
           '<basic-event name="Valve"/></or></define-gate>'
           '<define-gate name="Pumps"><and><basic-event name="PA"/><basic-event name="PB"/></and></define-gate>'
           '<define-basic-event name="MCC"><label>Motor control centre</label><float value="0.01"/>'
           '</define-basic-event>'
           '<define-basic-event name="Valve"><parameter name="QV"/></define-basic-event>'
           '<define-parameter name="QV"><float value="0.002"/></define-parameter>'
           + exp_event("PA", 1e-4) + exp_event("PB", 1e-4) + "</opsa-mef>")
    d = one(xml)
    mcc = by_label(d.graph, "Motor control centre")
    assert mcc["type"] == "component"
    assert mcc["model"]["distribution_id"] == "exponential" and mcc["model"]["placeholder"] is True
    # Rate −ln(1−q): the block fails with probability q within one time unit.
    rate = mcc["model"]["params"][0]["value"]
    assert 1 - np.exp(-rate) == pytest.approx(0.01)
    assert by_label(d.graph, "Valve")["model"]["placeholder"] is True
    assert "placeholder" not in by_label(d.graph, "PA")["model"]
    (note,) = [w for w in d.warnings if "fixed failure probability" in w]
    assert "“Motor control centre” (q = 0.01)" in note and "“Valve” (q = 0.002)" in note
    assert "placeholder" in note and "life model" in note
    # The placeholders survive normalisation (and so are listed by the MCP tools).
    from backend.services import rbd_graph
    assert sorted(rbd_graph.placeholder_labels(normalize_graph(d.graph))) == ["Motor control centre", "Valve"]
    # The diagram is analysable as imported.
    res = rbd_analysis.analyze(normalize_graph(d.graph), t_max=10)
    assert res["system"]["sf"][0] == pytest.approx(1.0)


def test_fixed_probabilities_of_0_and_1_fold_and_bad_ones_are_refused():
    def tree(q):
        return ('<opsa-mef><define-gate name="T"><or><basic-event name="A"/><basic-event name="B"/></or>'
                f'</define-gate><define-basic-event name="A"><float value="{q}"/></define-basic-event>'
                + exp_event("B", 1) + "</opsa-mef>")
    d = one(tree(0))
    assert {n.get("label") for n in d.graph["nodes"]} == {"Input", "Output", "B"}
    assert not any("fixed failure probability" in w for w in d.warnings)
    with pytest.raises(RbdImportError, match="certainly occurred"):
        load(tree(1))
    with pytest.raises(RbdImportError, match="between 0 and 1"):
        load(tree(1.5))


def test_exponential_over_a_fixed_time_imports_its_rate():
    xml = ('<opsa-mef><define-gate name="T"><or><basic-event name="A"/><basic-event name="B"/></or>'
           '</define-gate><define-basic-event name="A"><exponential><float value="2e-4"/>'
           '<parameter name="T24"/></exponential></define-basic-event>'
           '<define-parameter name="T24"><float value="24"/></define-parameter>'
           + exp_event("B", 1) + "</opsa-mef>")
    d = one(xml)
    a = by_label(d.graph, "A")["model"]
    assert a == {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 2e-4}]}
    assert any("fixed time" in w and "“A”" in w for w in d.warnings)


def test_missing_data_and_undefined_gates_are_refused():
    with pytest.raises(RbdImportError, match="no data"):
        load('<opsa-mef><define-gate name="T"><or><basic-event name="A"/>'
             '<basic-event name="B"/></or></define-gate>' + exp_event("B", 1) + "</opsa-mef>")
    with pytest.raises(RbdImportError, match="isn't defined"):
        load('<opsa-mef><define-gate name="T"><or><gate name="G"/>'
             '<basic-event name="B"/></or></define-gate>' + exp_event("B", 1) + "</opsa-mef>")


def test_repeated_events_import_as_repeated_blocks():
    # A basic event and a whole gate (S) each used under two gates.
    d = one('<opsa-mef><define-gate name="T"><or><gate name="G1"/><gate name="G2"/></or></define-gate>'
            '<define-gate name="G1"><and><basic-event name="A"/><gate name="S"/></and></define-gate>'
            '<define-gate name="G2"><and><basic-event name="A"/><basic-event name="C"/>'
            '<gate name="S"/></and></define-gate>'
            '<define-gate name="S"><or><basic-event name="D"/><basic-event name="E"/></or></define-gate>'
            + "".join(exp_event(n, r) for n, r in zip("ACDE", (1e-3, 2e-3, 5e-4, 7e-4)))
            + "</opsa-mef>")
    copies = [n for n in d.graph["nodes"] if n.get("repeat_of")]
    assert sorted(n["label"] for n in copies) == ["A", "D", "E"]
    res = rbd_analysis.analyze(normalize_graph(d.graph), t_max=2000.0)
    t = np.asarray(res["time"])
    qa, qc, qd, qe = (1 - np.exp(-r * t) for r in (1e-3, 2e-3, 5e-4, 7e-4))
    qs = 1 - (1 - qd) * (1 - qe)
    # T = A·S + A·C·S = A·S
    assert np.allclose(res["system"]["sf"], 1 - qa * qs, rtol=1e-9, atol=1e-12)


def test_unsafe_or_malformed_xml_is_refused():
    bomb = ('<?xml version="1.0"?><!DOCTYPE opsa-mef [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><opsa-mef><define-gate name="&b;">'
            '<or><basic-event name="A"/></or></define-gate></opsa-mef>')
    with pytest.raises(RbdImportError, match="entities"):
        load(bomb)
    xxe = ('<?xml version="1.0"?><!DOCTYPE opsa-mef [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           '<opsa-mef><define-gate name="&x;"><or><basic-event name="A"/></or></define-gate></opsa-mef>')
    with pytest.raises(RbdImportError, match="entities"):
        load(xxe)
    with pytest.raises(RbdImportError, match="well-formed"):
        load("<opsa-mef><define-gate>")
    with pytest.raises(RbdImportError, match="Open-PSA"):
        load("<html/>")
    deep = "<opsa-mef>" + "<and>" * (openpsa.MAX_XML_DEPTH + 5) + "</and>" * (openpsa.MAX_XML_DEPTH + 5) + "</opsa-mef>"
    with pytest.raises(RbdImportError, match="nested"):
        load(deep)


def test_deeply_chained_gates_are_bounded():
    from backend.services.rbd_import import fault_tree as ft

    n = ft.MAX_DEPTH + 10
    gates = "".join(f'<define-gate name="G{i}"><or><gate name="G{i + 1}"/><basic-event name="E{i}"/></or></define-gate>'
                    for i in range(n))
    xml = (f'<opsa-mef>{gates}<define-gate name="G{n}"><or><basic-event name="E{n}"/></or></define-gate>'
           + "".join(exp_event(f"E{i}", 1e-3) for i in range(n + 1)) + "</opsa-mef>")
    with pytest.raises(RbdImportError, match="deep"):
        load(xml)


def test_dispatcher_routes_open_psa(monkeypatch):
    import backend.services.rbd_import as rbd_import

    monkeypatch.setattr(rbd_import, "FORMATS", {"openpsa": "Open-PSA MEF", "galileo": "Galileo DFT"})
    diagrams = rbd_import.import_file(TWO_TRAIN.encode(), "cooling.xml")
    assert [d.source_format for d in diagrams] == ["Open-PSA MEF"]
