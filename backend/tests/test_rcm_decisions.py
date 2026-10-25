"""The RCM decision rules live in one place (backend/maintenance/rcm_decisions.py).

The maintenance tree owns them and the older RCM study service imports them from
there: the same objects, the same validation messages and the same evidence
check, whichever path a decision takes."""

import ast
import pathlib

import mongomock
import pytest

from backend.maintenance import rcm_decisions, rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import access
from backend.services import rcm as rcm_service

ORG = "user-a"
BACKEND = pathlib.Path(__file__).resolve().parents[1]

SHARED = (
    "CONSEQUENCES", "OUTCOMES", "RTF_BASES", "EVIDENCE_TYPES", "EXPECTED_EVIDENCE", "_UNIT_ALIASES",
    "RcmValidationError", "_norm_unit", "_unit_mismatch", "_clean_decision", "evidence_fetcher",
    "blank_rollup", "resolve_decision", "_resolve_decision", "_check_randomness", "_check_replacement",
    "_type_label", "_link_path",
)


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rcm_decisions"]
    samples.seed_samples(d)
    return d


def test_the_study_service_uses_the_same_rules():
    for name in SHARED:
        assert getattr(rcm_service, name) is getattr(rcm_decisions, name), name
    assert rcm_decisions.norm_unit is rcm_decisions._norm_unit
    assert rcm_decisions.clean_decision is rcm_decisions._clean_decision


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


@pytest.mark.parametrize("module", ["maintenance/service.py", "maintenance/rcm_graph.py",
                                    "maintenance/rcm_decisions.py"])
def test_the_tree_does_not_import_the_study_service(module):
    assert "backend.services.rcm" not in _imports(BACKEND / module)


@pytest.mark.parametrize("decision, message", [
    ({"outcome": "maybe"}, "Unknown outcome 'maybe'."),
    ({"outcome": "rtf"}, "A run-to-failure decision needs its basis: 'random' or 'uneconomic'."),
    ({"outcome": "fixed_interval", "interval": "soon"}, "The task interval must be a number."),
    ({"outcome": "fixed_interval", "interval": -4}, "The task interval must be positive."),
    ({"outcome": "fixed_interval", "evidence": {"type": "guess", "id": "x"}}, "Unknown evidence type 'guess'."),
    ({"outcome": "fixed_interval", "evidence": {"type": "model", "id": " "}},
     "Evidence needs the linked artifact's id."),
])
def test_both_paths_refuse_a_bad_decision_with_the_same_words(m, decision, message):
    with pytest.raises(rcm_service.RcmValidationError) as study_err:
        rcm_service.clean_tree([{"text": "F", "failures": [{"text": "FF", "modes": [
            {"text": "Mode", "decision": decision}]}]}])
    assert str(study_err.value) == message
    pid = m.create_position("Pump")["id"]
    mode = m.add_failure_mode(pid, "Bearing seized")
    with pytest.raises(Invalid) as tree_err:
        m.decide_failure_mode(mode["id"], decision=decision)
    assert str(tree_err.value) == message


def test_both_paths_refuse_an_unknown_consequence_with_the_same_words(m):
    with pytest.raises(rcm_service.RcmValidationError) as study_err:
        rcm_service.clean_tree([{"text": "F", "failures": [{"text": "FF", "modes": [
            {"text": "Mode", "consequence": "cosmic"}]}]}])
    pid = m.create_position("Pump")["id"]
    mode = m.add_failure_mode(pid, "Bearing seized")
    with pytest.raises(Invalid) as tree_err:
        m.decide_failure_mode(mode["id"], consequence="cosmic")
    assert str(tree_err.value) == str(study_err.value) == "Unknown consequence 'cosmic'."


def test_a_decision_is_checked_the_same_on_the_tree_and_in_a_study(m, db):
    from backend.services.samples import SAMPLE_OWNER

    owners = [ORG, SAMPLE_OWNER]
    decisions = [
        {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": "sample-model-bearings-weibull"}},
        {"outcome": "fixed_interval", "interval": 2000, "interval_unit": "hours",
         "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}},
        {"outcome": "fixed_interval", "interval": 3, "interval_unit": "months",
         "evidence": {"type": "strategy_analysis", "id": "sample-strategy-bearing-replacement"}},
        {"outcome": "on_condition", "evidence": {"type": "model", "id": "sample-model-bearings-weibull"}},
        {"outcome": "failure_finding"},
        {"outcome": "redesign"},
        {"outcome": "rtf", "rtf_basis": "uneconomic", "evidence": {"type": "model", "id": "gone"}},
    ]
    pid = m.create_position("Pump")["id"]
    fetch = rcm_decisions.evidence_fetcher(db, owners)
    for i, decision in enumerate(decisions):
        mode = m.add_failure_mode(pid, f"Mode {i}")
        m.decide_failure_mode(mode["id"], decision=decision)
        on_tree = rcm_graph.mode_status(db, m.rcm_mode(mode["id"]), owners)["decision"]
        in_study = rcm_service.resolve_decision(rcm_service._clean_decision(decision), fetch)
        for key in ("status", "reason", "summary", "artifact_name", "artifact_link_path", "expected_evidence"):
            assert on_tree.get(key) == in_study.get(key), (i, key)


def test_one_decision_names_its_evidence_as_a_worksheet_does():
    decision = {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": "m1"}}
    assert access.refs_of_decision(decision) == [("models", "m1")]
    assert rcm_graph.evidence_refs(decision) == [("models", "m1")]
    assert access.evidence_refs([{"failures": [{"modes": [{"decision": decision}]}]}]) == [("models", "m1")]
    for empty in (None, {}, {"evidence": None}, {"evidence": "x"}, {"evidence": {"type": "photo", "id": "p"}},
                  {"evidence": {"type": "model", "id": ""}}):
        assert access.refs_of_decision(empty) == []
