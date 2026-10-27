"""The RCM decision rules live in one place (backend/maintenance/rcm_decisions.py):
the vocabulary, the validation of a decision and of a worksheet tree, and the
evidence check, whichever way a decision arrives (by hand on the tree, over
the API or MCP, or from a worksheet import)."""

import mongomock
import pytest

from backend.maintenance import rcm_decisions, rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import access

ORG = "user-a"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rcm_decisions"]
    samples.seed_samples(d)
    return d


def test_the_public_names_are_the_rules():
    assert rcm_decisions.norm_unit is rcm_decisions._norm_unit
    assert rcm_decisions.clean_decision is rcm_decisions._clean_decision
    assert rcm_decisions.check_randomness is rcm_decisions._check_randomness
    options = rcm_decisions.options()
    assert [c["id"] for c in options["consequences"]] == list(rcm_decisions.CONSEQUENCES)
    assert [o["id"] for o in options["outcomes"]] == list(rcm_decisions.OUTCOMES)
    assert [b["id"] for b in options["rtf_bases"]] == list(rcm_decisions.RTF_BASES)
    assert all(o["expected_evidence"] == rcm_decisions.EXPECTED_EVIDENCE[o["id"]] for o in options["outcomes"])


@pytest.mark.parametrize("decision, message", [
    ({"outcome": "maybe"}, "Unknown outcome 'maybe'."),
    ({"outcome": "rtf"}, "A run-to-failure decision needs its basis: 'random' or 'uneconomic'."),
    ({"outcome": "fixed_interval", "interval": "soon"}, "The task interval must be a number."),
    ({"outcome": "fixed_interval", "interval": -4}, "The task interval must be positive."),
    ({"outcome": "fixed_interval", "evidence": {"type": "guess", "id": "x"}}, "Unknown evidence type 'guess'."),
    ({"outcome": "fixed_interval", "evidence": {"type": "model", "id": " "}},
     "Evidence needs the linked artifact's id."),
])
def test_a_bad_decision_is_refused_with_the_same_words_everywhere(m, decision, message):
    with pytest.raises(rcm_decisions.RcmValidationError) as sheet_err:
        rcm_decisions.clean_tree([{"text": "F", "failures": [{"text": "FF", "modes": [
            {"text": "Mode", "decision": decision}]}]}])
    assert str(sheet_err.value) == message
    pid = m.create_position("Pump")["id"]
    mode = m.add_failure_mode(pid, "Bearing seized")
    with pytest.raises(Invalid) as tree_err:
        m.decide_failure_mode(mode["id"], decision=decision)
    assert str(tree_err.value) == message


def test_an_unknown_consequence_is_refused_with_the_same_words_everywhere(m):
    with pytest.raises(rcm_decisions.RcmValidationError) as sheet_err:
        rcm_decisions.clean_tree([{"text": "F", "failures": [{"text": "FF", "modes": [
            {"text": "Mode", "consequence": "cosmic"}]}]}])
    pid = m.create_position("Pump")["id"]
    mode = m.add_failure_mode(pid, "Bearing seized")
    with pytest.raises(Invalid) as tree_err:
        m.decide_failure_mode(mode["id"], consequence="cosmic")
    assert str(tree_err.value) == str(sheet_err.value) == "Unknown consequence 'cosmic'."


def test_a_worksheet_tree_is_normalised():
    tree = [{"text": " Fn ", "standard": "", "failures": [{"id": "keep", "text": "FF", "modes": [
        {"text": "M", "notes": " RPN 96 ", "effects": "", "decision": None}]}]}]
    [fn] = rcm_decisions.clean_tree(tree)
    assert fn["id"] and fn["text"] == "Fn" and "standard" not in fn
    [ff] = fn["failures"]
    assert ff["id"] == "keep"
    [mode] = ff["modes"]
    assert mode["notes"] == "RPN 96" and "effects" not in mode and mode["decision"] is None
    with pytest.raises(rcm_decisions.RcmValidationError):
        rcm_decisions.clean_tree([{"text": " ", "failures": []}])
    with pytest.raises(rcm_decisions.RcmValidationError):
        rcm_decisions.clean_tree({"text": "not a list"})


def test_a_decision_is_checked_the_same_on_the_tree_and_from_the_rules(m, db):
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
        direct = rcm_decisions.resolve_decision(rcm_decisions.clean_decision(decision), fetch)
        for key in ("status", "reason", "summary", "artifact_name", "artifact_link_path", "expected_evidence"):
            assert on_tree.get(key) == direct.get(key), (i, key)


def test_one_decision_names_its_evidence():
    decision = {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": "m1"}}
    assert access.refs_of_decision(decision) == [("models", "m1")]
    assert rcm_graph.evidence_refs(decision) == [("models", "m1")]
    for empty in (None, {}, {"evidence": None}, {"evidence": "x"}, {"evidence": {"type": "photo", "id": "p"}},
                  {"evidence": {"type": "model", "id": ""}}):
        assert access.refs_of_decision(empty) == []
