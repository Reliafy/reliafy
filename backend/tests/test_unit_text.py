"""Units in running text (#265).

Units are stored and shown canonical ("Hours"), but a sentence reads "in
hours" and "per hour", never "in Hours" or "per Hours". One definition of the
units lives in ``backend.units``; the RBD analysis uses it rather than its own
copy.
"""

import re

from backend import units
from backend.services import rbd_analysis, rbd_intervals, rbd_sensitivity, rcm, strategy, strategy_store
from backend.schema import StrategyAnalysis

# A capitalised known unit after a lower-case word: "in Hours", "about 500 Hours".
_MID_SENTENCE = re.compile(r"[a-z0-9,)] (Seconds|Minutes|Hours|Days|Weeks|Months|Years|Cycles|Hour|Month)\b")


def _clean(text: str) -> None:
    assert not _MID_SENTENCE.search(text), text


def test_one_definition_of_the_units():
    # rbd_analysis uses backend.units' functions, not a copy of the tables.
    assert rbd_analysis.normalize_unit is units.normalize_unit
    assert not hasattr(rbd_analysis, "_UNIT_ALIASES")
    assert not hasattr(rbd_analysis, "_CANONICAL_UNITS")
    assert units.canonical_unit("hrs") == "Hours"
    assert units.canonical_unit("km") == "Kilometres"
    assert units.canonical_unit("Flights") == "Flights"


def test_unit_in_text():
    assert units.unit_in_text("Hours") == "hours"
    assert units.unit_in_text("hrs") == "hrs"
    assert units.unit_in_text("Kilometres") == "kilometres"
    assert units.unit_in_text("kWh") == "kWh"  # not a known time unit: kept as typed
    assert units.unit_in_text(None) == ""
    assert units.unit_in_text(" Months ") == "months"


def test_rbd_unit_warning_reads_lower_case():
    graph = {"unit": "Hours", "nodes": [
        {"id": "a", "data": {"label": "Pump", "model": {"name": "Pump life", "unit": "Months"}}}]}
    (warning,) = rbd_analysis.unit_warnings(graph)
    _clean(warning)
    assert "fitted in months" in warning and "diagram's unit is hours" in warning


def test_strategy_sentences_read_lower_case():
    weibull = [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}]
    out = strategy.optimal_replacement("weibull", weibull, 1.0, 10.0, unit="Hours")
    _clean(out["recommendation"])
    assert " hours." in out["recommendation"]
    assert out["unit"] == "Hours"  # the field itself stays canonical

    ffi = strategy.failure_finding("exponential", [{"name": "failure_rate", "value": 1e-4}], 0.99, unit="Hours")
    _clean(ffi["note"])
    assert " hours to keep" in ffi["note"]

    demo = strategy.demonstration_test(method="mtbf", mtbf=1000, confidence=0.9, unit="Hours")
    _clean(demo["summary"])


def test_headlines_and_verdicts_read_lower_case():
    doc = StrategyAnalysis(id="s1", owner_id="u", name="x", kind="failure_finding",
                           results={"interval": 120.0, "unit": "Hours"})
    head = strategy_store.headline(doc)
    _clean(head)
    assert head.endswith("120 hours")

    mismatch = rcm._unit_mismatch({"interval_unit": "Months"}, "Hours")
    _clean(mismatch["reason"])
    assert "is in months but the linked analysis is in hours" in mismatch["reason"]

    assert rbd_sensitivity._per("Hours") == "per hour"
    msg = rbd_intervals._not_met("", False, None, 5.0, "Hours")
    _clean(msg)
    assert "per hour" in msg
