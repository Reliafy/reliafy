"""RCM decisions: the rules every RCM decision on the asset tree follows.

The vocabulary (consequences, outcomes, run-to-failure bases, evidence
types), the validation of a decision (outcome, interval and its unit,
evidence link) and the live evidence check: a decision links the saved model
or analysis that justifies it, and the link is *checked* on every read. A
run-to-failure-because-random decision whose non-repairable model now shows
wear-out is flagged **contradicted**, not silently trusted. Statuses are
therefore never stored; they are recomputed from the linked artifacts each
time the RCM is read.

A decision can also link a report (the app's Reports) or the working behind a
performance standard (a function's notes and rationale, where the working is
written) as the case for it.
Nothing is computed from those: the check says only that one is linked
("linked", with ``evidence_kind`` report or working), or that it has gone
("stale"); it never says supported or contradicted.

The maintenance tree (``backend/maintenance/service.py`` and
``rcm_graph.py``) owns these rules, and a worksheet import
(``backend/services/rcm_import.py``) validates what it builds with them, so
there is one copy.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from backend.maintenance import fmea
from backend.services import access
from backend.services import reports as reports_service
from backend.services import degradation as degradation_service
from backend.services import models as models_service
from backend.services import strategy_store
from backend.services.strategy import fmt_num
from backend.units import unit_in_text


class RcmValidationError(ValueError):
    """Raised when a decision or a worksheet tree fails validation (HTTP 422)."""


# The consequence of a failure mode, as SAE JA1011 and RCM II (Moubray) ask it:
# two questions, in order. First, is the failure evident or hidden (would the
# loss of function on its own become evident to the operating crew under
# normal circumstances)? A mode's ``hidden`` holds the answer. Then the
# category, one of four, walked in order (safety, environmental, operational,
# non-operational; the first that applies). For a hidden failure the category
# is what the multiple failure would do: the hidden failure plus the second
# failure it fails to protect against.
CONSEQUENCES = ("safety", "environmental", "operational", "non_operational")
# The old fifth value. A mode saved with it reads as hidden with its category
# not yet set; a call that sends it sets hidden (a deprecated alias).
HIDDEN_ALIAS = "hidden"
SERIOUS = ("safety", "environmental")
OUTCOMES = ("on_condition", "fixed_interval", "rtf", "failure_finding", "redesign", "accept")
RTF_BASES = ("random", "uneconomic")
# A combination of tasks (RCM II's words): where no one task is good enough on
# its own, a decision holds several scheduled tasks, a regular inspection plus
# a fixed-time replacement, or several of one kind (a weekly top-up and an
# annual deep clean, both fixed interval: Derryn, 9 Nov 2026). Each member that
# schedules work gets a task of its own, and members are told apart by their
# task (task_id), never by their outcome. A redesign may sit beside the
# scheduled tasks, the interim measure until the change is made (one
# redesign); run-to-failure and accept stand alone.
SCHEDULED = ("on_condition", "fixed_interval", "failure_finding")
COMBINES = (
    "A combination is two or more tasks of on_condition, fixed_interval and failure_finding (one kind may come "
    "more than once, each with its own task), optionally with one redesign beside them as the interim measure; "
    "rtf and accept stand alone."
)


def mode_consequence(mode) -> tuple[bool | None, str | None]:
    """A mode's two answers as (hidden, category), however it was saved.

    ``hidden`` when the mode says so; True for the old value consequence
    "hidden" (its category not yet set); False for a mode saved with a category
    and no answer, since under the old five values a category meant the
    failure was evident; None when neither question is answered. A category
    outside the four comes back as saved (free text from an old import)."""
    mode = mode or {}
    raw = mode.get("consequence") or None
    hidden = mode.get("hidden")
    if raw == HIDDEN_ALIAS:
        return True, None
    if isinstance(hidden, bool):
        return hidden, raw
    return (False if raw else None), raw


def consequence_label(hidden, consequence) -> str:
    """"Hidden · Safety", "Operational" (evident: most failures are, so only
    the category), "Hidden" or "Evident" (category not set yet), "" (nothing
    answered): the worksheet's and the exports' words."""
    category = next((c["label"] for c in CONSEQUENCE_OPTIONS if c["id"] == consequence), consequence or "")
    if hidden:
        return " · ".join(x for x in ("Hidden", category) if x)
    return category or ("Evident" if hidden is False else "")


def combination_ok(outcomes) -> bool:
    """Whether a list of outcomes may be one decision (one outcome always may):
    the rules _clean_members holds a combination to (frontend/src/decisionCheck.js
    combinationOk is the same)."""
    if len(outcomes) < 2:
        return True
    if any(o not in (*SCHEDULED, "redesign") for o in outcomes) or outcomes.count("redesign") > 1:
        return False
    scheduled = sum(1 for o in outcomes if o in SCHEDULED)
    return scheduled >= 1 if "redesign" in outcomes else scheduled >= 2


# Evidence that's checked against the decision (a model or a saved analysis),
# then evidence that's only linked: a report, or a function's working, now its notes and rationale (its id is
# the function's whose performance standard the working sits behind).
CHECKED_TYPES = ("model", "strategy_analysis", "degradation_model")
LINKED_TYPES = ("report", "working")
EVIDENCE_TYPES = CHECKED_TYPES + LINKED_TYPES


def evidence_kind(etype) -> str | None:
    """What a linked piece of evidence is, as the RCM tab groups it: a report, a
    working, or a model (any checked kind: a model or a saved analysis)."""
    if etype in LINKED_TYPES:
        return etype
    return "model" if etype in CHECKED_TYPES else None

# The vocabulary as the app shows it (GET /api/maintenance/rcm/options): the
# first question (evident or hidden), each consequence category with what
# makes a task worth doing for it, and each outcome with its hint.
EVIDENT_HIDDEN_OPTIONS = [
    {"id": "evident", "label": "Evident",
     "hint": "The crew would notice the loss of function on its own, in normal operation."},
    {"id": "hidden", "label": "Hidden",
     "hint": "Nobody would notice in normal operation until something else fails too (a standby pump, a trip, "
             "an alarm). The category is then what that multiple failure would do."},
]

CONSEQUENCE_OPTIONS = [
    {"id": "safety", "label": "Safety",
     "hint": "Could hurt or kill someone.",
     "worth_doing": "A task is worth doing only if it makes the risk tolerable; cost isn't the test."},
    {"id": "environmental", "label": "Environmental",
     "hint": "Could breach an environmental standard or regulation.",
     "worth_doing": "A task is worth doing only if it makes the risk tolerable; cost isn't the test."},
    {"id": "operational", "label": "Operational",
     "hint": "Affects output, quality or customer service, plus the repair.",
     "worth_doing": "A task is worth doing only if it costs less over time than the failures it prevents "
                    "(lost output and repairs)."},
    {"id": "non_operational", "label": "Non-operational",
     "hint": "Only the repair costs.",
     "worth_doing": "A task is worth doing only if it costs less over time than the repairs it prevents."},
]

OUTCOME_OPTIONS = [
    {"id": "on_condition", "label": "On condition",
     "expected_evidence": "degradation_model",
     "fields": ["task", "interval"],
     "hint": "Check for a sign the failure is on its way and act before it happens. Link the degradation model "
             "that shows the failure develops measurably."},
    {"id": "fixed_interval", "label": "Fixed interval",
     "expected_evidence": "strategy_analysis",
     "fields": ["task", "interval"],
     "hint": "Scheduled restoration or discard: restore or replace at a fixed age, whatever its condition. Link "
             "the optimal-replacement analysis showing the interval pays."},
    {"id": "rtf", "label": "Run to failure",
     "expected_evidence": None,  # depends on rtf_basis
     "fields": ["rtf_basis", "task"],
     "hint": "No scheduled maintenance: let it fail, then fix it. Justify with either a non-repairable model "
             "showing random failures, or a replacement analysis showing prevention doesn't pay."},
    {"id": "failure_finding", "label": "Failure finding",
     "expected_evidence": "strategy_analysis",
     "fields": ["task", "interval"],
     "hint": "For a hidden failure: check now and then that the protective function still works. Link the "
             "failure-finding interval analysis that sets how often."},
    {"id": "redesign", "label": "Redesign",
     "expected_evidence": None, "fields": ["notes"],
     "hint": "No task is worth doing: change the design, or the way it's operated, instead."},
    {"id": "accept", "label": "Accept",
     "expected_evidence": None, "fields": ["notes"],
     "hint": "No scheduled maintenance, as run to failure, where the consequences allow it. Say why in the notes."},
]

RTF_BASIS_OPTIONS = [
    {"id": "random", "label": "Failures are random",
     "expected_evidence": "model",
     "hint": "Evidence: a Weibull fit whose β confidence interval contains 1, or an Exponential fit."},
    {"id": "uneconomic", "label": "Prevention isn't economic",
     "expected_evidence": "strategy_analysis",
     "hint": "Evidence: an optimal-replacement analysis showing no beneficial interval."},
]


# ---- The decision diagram (SAE JA1011, RCM II) ----------------------------------
# Tasks are considered in order: on condition, then scheduled restoration or
# discard (fixed interval), then, for a hidden failure, failure finding. A
# combination of tasks where no single task is good enough: RCM II reserves it
# for safety and environmental consequences, but a routine dose plus a periodic
# test on one operational mode is common practice, so a combination is allowed
# on any consequence and advice() says what each task must then justify
# (Derryn, 9 Nov 2026). When no task is worth doing, the default action follows
# from the two answers (default_action).

TASK_ORDER = ("on_condition", "fixed_interval", "failure_finding")
# The tasks that check something (a condition, a hidden function): each can say
# what's done when the check finds it (on_found, Nov 2026: "Then, if found").
FINDS = ("on_condition", "failure_finding")
ON_FOUND_MAX = 500



def _category_word(consequence) -> str:
    return {"safety": "A safety", "environmental": "An environmental", "operational": "An operational",
            "non_operational": "A non-operational"}.get(consequence, "This")


def refusal(hidden, consequence, outcomes) -> str | None:
    """Why the decision diagram doesn't allow these outcomes for a mode with
    these answers, or None when it does. A question not answered yet (None)
    allows everything that hangs on it."""
    members = [o for o in outcomes or [] if o]
    if consequence in SERIOUS and any(o in ("rtf", "accept") for o in members):
        what = "the multiple failure" if hidden else "the failure"
        return (f"{_category_word(consequence)} consequence can't be run to failure or accepted: find a task that "
                f"makes the risk of {what} tolerable, or redesign.")
    if "failure_finding" in members and hidden is False:
        return ("Failure finding is for hidden failures only, and this one is evident (the crew would notice it). "
                "Mark it hidden if the loss of function can't be seen in normal operation.")
    return None


def allowed_outcomes(hidden, consequence) -> dict:
    """Each outcome with None (allowed) or why the diagram doesn't allow it on
    its own, for a mode with these answers."""
    return {o: refusal(hidden, consequence, [o]) for o in OUTCOMES}


def default_action(hidden, consequence) -> dict | None:
    """What the diagram prescribes when no task is worth doing: {outcome,
    then (the next default when that one isn't worth doing either),
    redesign: "compulsory" or "desirable", text}. None until the category is
    known (a hidden mode without one gets a word asking for it)."""
    if consequence not in CONSEQUENCES:
        if hidden:
            return {"outcome": None, "then": None, "redesign": None,
                    "text": "Say what the multiple failure would do (the hidden failure plus the one it protects "
                            "against): the default action follows from it."}
        return None
    serious = consequence in SERIOUS
    if not hidden and serious:
        return {"outcome": "redesign", "then": None, "redesign": "compulsory",
                "text": "If no task makes the risk tolerable, redesign is compulsory. It can't be run to failure."}
    if not hidden:
        return {"outcome": "rtf", "then": None, "redesign": "desirable",
                "text": "If no task pays for itself, no scheduled maintenance (run to failure). A redesign may be "
                        "worth it."}
    if serious:
        return {"outcome": "failure_finding", "then": "redesign", "redesign": "compulsory",
                "text": "If no on condition or fixed interval task makes the risk tolerable, a failure finding task "
                        "that makes the multiple-failure risk tolerable; if none does, redesign is compulsory."}
    return {"outcome": "failure_finding", "then": "rtf", "redesign": "desirable",
            "text": "If no on condition or fixed interval task pays, a failure finding task if it costs less than "
                    "the multiple failures it prevents; otherwise no scheduled maintenance. A redesign may be "
                    "worth it."}


def advice(consequence, outcome, outcomes=None, hidden=...) -> str | None:
    """A word on a decision the diagram wouldn't make now (a saved one from
    before, or an import's): never a refusal on read, the analyst changes it
    when they next review the mode. Also asks for a hidden mode's category.
    ``outcomes``: every outcome of a combination of tasks (its members').
    ``hidden``: the mode's first answer; left out, it's read from the
    consequence as mode_consequence reads a saved mode."""
    if hidden is ...:
        hidden, consequence = mode_consequence({"consequence": consequence})
    members = [o for o in (outcomes or [outcome]) if o]
    if hidden and consequence not in CONSEQUENCES:
        return ("This failure is hidden: say what the multiple failure would do (the hidden failure plus the one "
                "it protects against): safety, environmental, operational or non-operational.")
    if not members:
        return None
    why = refusal(hidden, consequence, members)
    if why:
        return f"{why} This decision is kept as it was saved; change it when you next review this failure mode."
    if hidden and consequence in CONSEQUENCES and not any(o in SCHEDULED for o in members) and "redesign" not in members:
        return ("A hidden failure gets a failure-finding task before no scheduled maintenance, if one is worth "
                "doing: say in the notes why none is.")
    if sum(1 for o in members if o in SCHEDULED) > 1 and consequence in ("operational", "non_operational"):
        return ("A combination of tasks on a cost consequence: each task must pay for itself over time (RCM II "
                "reserves combinations for safety and environmental consequences). Say in the notes why both "
                "are worth doing.")
    return None


def options() -> dict:
    """The decision vocabulary with its hints, for the decision dialog."""
    return {"evident_hidden": EVIDENT_HIDDEN_OPTIONS, "consequences": CONSEQUENCE_OPTIONS,
            "outcomes": OUTCOME_OPTIONS, "rtf_bases": RTF_BASIS_OPTIONS, "task_order": list(TASK_ORDER)}

# Common aliases so "hr", "hrs" and "hours" agree. Unmapped units compare
# case-insensitively as-is.
_UNIT_ALIASES = {
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours",
    "d": "days", "day": "days",
    "wk": "weeks", "wks": "weeks", "week": "weeks",
    "mo": "months", "month": "months",
    "y": "years", "yr": "years", "yrs": "years", "year": "years",
    "cycle": "cycles", "cyc": "cycles",
    "kilometre": "km", "kilometres": "km", "kilometer": "km", "kilometers": "km",
    "mile": "miles", "mi": "miles",
    "operating hours": "hours", "op hrs": "hours",
}


def _norm_unit(unit) -> str:
    u = str(unit or "").strip().lower()
    return _UNIT_ALIASES.get(u, u)


def _unit_mismatch(decision: dict, evidence_unit) -> dict | None:
    """Inconclusive result when the task interval's unit contradicts the
    evidence's time unit. Units are free text, so only a definite
    disagreement (both present, different after normalisation) trips this —
    a missing unit on either side passes.
    """
    task_unit = _norm_unit(decision.get("interval_unit"))
    ev_unit = _norm_unit(evidence_unit)
    if task_unit and ev_unit and task_unit != ev_unit:
        return {
            "status": "inconclusive",
            "reason": (
                f"Unit mismatch: the task interval is in {unit_in_text(decision.get('interval_unit'))} "
                f"but the linked analysis is in {unit_in_text(evidence_unit)}. Align the units to validate "
                "this decision."
            ),
        }
    return None


# What each outcome expects as evidence (None = default action, no evidence).
EXPECTED_EVIDENCE = {
    "on_condition": "degradation_model",
    "fixed_interval": "strategy_analysis",
    "rtf": None,  # depends on rtf_basis: random -> model, uneconomic -> strategy_analysis
    "failure_finding": "strategy_analysis",
    "redesign": None,
    "accept": None,
}


def _clean_interval(given: dict, cleaned: dict) -> None:
    """A task's interval (a positive number) and its unit, into ``cleaned``."""
    interval = given.get("interval")
    if interval is not None and interval != "":
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            raise RcmValidationError("The task interval must be a number.")
        if interval <= 0:
            raise RcmValidationError("The task interval must be positive.")
        cleaned["interval"] = interval
        unit = str(given.get("interval_unit") or "").strip()
        if unit:
            cleaned["interval_unit"] = unit


def _clean_evidence(evidence) -> dict | None:
    """A linked piece of evidence ({type, id}), or None for none."""
    if not evidence:
        return None
    if not isinstance(evidence, dict):
        raise RcmValidationError("Evidence is {type, id}: the linked model, analysis, report or function.")
    etype = evidence.get("type")
    eid = evidence.get("id")
    if etype not in EVIDENCE_TYPES:
        raise RcmValidationError(f"Unknown evidence type '{etype}': it's one of {', '.join(EVIDENCE_TYPES)}.")
    if not isinstance(eid, str) or not eid.strip():
        raise RcmValidationError("Evidence needs the linked artifact's id.")
    # A type that doesn't match the outcome is allowed at write time and
    # resolves to 'inconclusive' at read — users can link first, fix later.
    return {"type": etype, "id": eid.strip()}


def _clean_on_found(value, outcome) -> str:
    """What's done when a check finds it ("" clears it): only an on-condition or
    failure-finding task checks something."""
    text = " ".join(str(value or "").split())
    if text and outcome not in FINDS:
        raise RcmValidationError(f"on_found (what's done when the check finds it) goes with an on_condition or "
                                 f"failure_finding task, not {outcome}.")
    if len(text) > ON_FOUND_MAX:
        raise RcmValidationError(f"on_found is {len(text):,} characters; keep it to {ON_FOUND_MAX} (the task's "
                                 "instructions hold the detail).")
    return text


def _clean_members(raw) -> list[dict]:
    """A combination's members ({outcome, task, interval, interval_unit,
    task_id, evidence}), checked against the combination rules, the scheduled
    ones first in the order given and a redesign last. One member is a plain
    decision. A member's own evidence is what's checked for it; one without
    any falls back to the decision's."""
    if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
        raise RcmValidationError("outcomes is a list of {outcome, task, interval, interval_unit, task_id, evidence}, "
                                 "one per task of the combination.")
    members = []
    for given in raw:
        outcome = given.get("outcome")
        if outcome not in OUTCOMES:
            raise RcmValidationError(f"Each of outcomes needs its outcome, one of {', '.join(OUTCOMES)}"
                                     f"{f' (not {outcome!r})' if outcome else ''}.")
        member = {"outcome": outcome}
        if outcome in SCHEDULED:
            _clean_interval(given, member)
            task = str(given.get("task") or "").strip()
            if task:
                member["task"] = task
            tid = given.get("task_id")
            if tid not in (None, ""):
                if not isinstance(tid, str):
                    raise RcmValidationError("A member's task_id is an existing task's id.")
                member["task_id"] = tid.strip()
        elif any(given.get(k) not in (None, "") for k in ("task", "interval", "task_id")):
            raise RcmValidationError(f"Only a task that schedules work takes a task and an interval ({outcome} "
                                     "doesn't): say what's meant in the decision's notes.")
        evidence = _clean_evidence(given.get("evidence"))
        if evidence:
            member["evidence"] = evidence
        if "on_found" in given:  # left out: kept as it was while the member's kind stays
            member["on_found"] = _clean_on_found(given["on_found"], outcome)
        members.append(member)
    if len(members) < 2:
        return members
    said = [m["outcome"] for m in members]
    if not combination_ok(said):
        raise RcmValidationError(f"{' + '.join(said)} can't be combined. {COMBINES}")
    ids = [m["task_id"] for m in members if m.get("task_id")]
    if len(set(ids)) != len(ids):
        raise RcmValidationError("Each task of a combination is its own: one task_id is named twice.")
    for m in members:
        if m["outcome"] in SCHEDULED and not m.get("interval") and not m.get("task_id"):
            raise RcmValidationError(f"Each task of a combination needs its interval (or the task_id of an existing "
                                     f"task): {m['outcome']} has neither.")
    return sorted(members, key=lambda m: m["outcome"] == "redesign")


def _clean_decision(decision) -> dict | None:
    if decision is None:
        return None
    members = single_task = None
    if decision.get("outcomes") not in (None, []):
        members = _clean_members(decision["outcomes"])
        said = decision.get("outcome")
        if said and said not in [m["outcome"] for m in members]:
            raise RcmValidationError(f"outcome is the first of outcomes (or left out): {said} isn't one of them.")
        first = members[0]
        # The first member is the decision's own: its fields are the decision's.
        decision = {k: v for k, v in decision.items() if k not in ("outcomes", "task", "interval", "interval_unit")}
        decision |= {k: first[k] for k in ("outcome", "task", "interval", "interval_unit") if k in first}
        if len(members) == 1:
            # One member is a plain decision; its task_id (if any) is the decision's, and
            # its evidence (and on_found) too when the decision gives none.
            members, single_task = None, first.get("task_id")
            if first.get("evidence") and not decision.get("evidence"):
                decision["evidence"] = first["evidence"]
            if "on_found" in first and "on_found" not in decision:
                decision["on_found"] = first["on_found"]
        elif "on_found" in decision:
            # A combination's on_found is each member's: one given for the decision is its first's.
            given = decision.pop("on_found")
            if "on_found" not in first:
                first["on_found"] = _clean_on_found(given, first["outcome"])
    outcome = decision.get("outcome")
    if not outcome:
        # A decision is replaced whole, so a change to one field still sends the rest.
        raise RcmValidationError(
            f"A decision needs its outcome: {', '.join(OUTCOMES)}. It replaces the whole decision, so send the "
            "current one (outcome, task, interval) with your change."
        )
    if outcome not in OUTCOMES:
        raise RcmValidationError(f"Unknown outcome '{outcome}': it's one of {', '.join(OUTCOMES)}.")
    cleaned = {"outcome": outcome}

    if outcome == "rtf":
        basis = decision.get("rtf_basis")
        if basis not in RTF_BASES:
            raise RcmValidationError(
                "A run-to-failure decision needs its basis: 'random' or 'uneconomic'."
            )
        cleaned["rtf_basis"] = basis

    _clean_interval(decision, cleaned)

    for key in ("task", "notes"):
        value = str(decision.get(key) or "").strip()
        if value:
            cleaned[key] = value
    if members is None and "on_found" in decision:  # left out: kept while the kind of task stays
        cleaned["on_found"] = _clean_on_found(decision["on_found"], outcome)
    if members is not None:
        cleaned["outcomes"] = members
    elif single_task:
        cleaned["task_id"] = single_task  # the decide call's task_id, when it gives none of its own

    cleaned["evidence"] = _clean_evidence(decision.get("evidence"))
    return cleaned


# ---- A worksheet tree ----------------------------------------------------------
# The shape a spreadsheet import builds before it goes onto a position:
# functions › failures › modes, each mode with its consequence and decision.

def _require_text(node: dict, what: str) -> str:
    text = str(node.get("text") or "").strip()
    if not text:
        raise RcmValidationError(f"Every {what} needs a description.")
    return text


def _node_id(node: dict) -> str:
    nid = node.get("id")
    return nid if isinstance(nid, str) and nid.strip() else uuid.uuid4().hex


def clean_consequence(consequence, hidden=None) -> tuple[bool | None, str | None]:
    """A consequence and the evident-or-hidden answer as given, checked:
    (hidden, category). The old value "hidden" is a deprecated alias that sets
    hidden (its category then stays as given elsewhere, so None here)."""
    consequence = consequence or None
    if hidden is not None and not isinstance(hidden, bool):
        raise RcmValidationError("hidden is true (the failure can't be seen in normal operation) or false (evident).")
    if consequence == HIDDEN_ALIAS:
        if hidden is False:
            raise RcmValidationError("consequence 'hidden' says the failure is hidden, but hidden is false: give one.")
        return True, None
    if consequence is not None and consequence not in CONSEQUENCES:
        raise RcmValidationError(
            f"Unknown consequence '{consequence}': it's one of {', '.join(CONSEQUENCES)} (and hidden is a "
            "separate yes or no).")
    return hidden, consequence


def _clean_mode(mode: dict) -> dict:
    hidden, consequence = clean_consequence(mode.get("consequence"), mode.get("hidden"))
    cleaned_mode = {
        "id": _node_id(mode),
        "text": _require_text(mode, "failure mode"),
        "consequence": consequence,
        "decision": _clean_decision(mode.get("decision")),
    }
    if hidden is not None:
        cleaned_mode["hidden"] = hidden
    effects = str(mode.get("effects") or "").strip()
    if effects:
        cleaned_mode["effects"] = effects
    # Free-text notes on the mode itself (columns a spreadsheet import keeps
    # as text); a decision's notes live on it.
    notes = str(mode.get("notes") or "").strip()
    if notes:
        cleaned_mode["notes"] = notes
    # Its FME(C)A fields (scores, cause, effects, the action, the criticality
    # figures), checked as the service checks them.
    for key in fmea.FIELDS:
        if mode.get(key) is not None:
            try:
                cleaned_mode[key] = fmea.clean_value(key, mode[key])
            except fmea.FmeaError as err:
                raise RcmValidationError(str(err)) from None
    return cleaned_mode


def clean_tree(functions) -> list[dict]:
    """Validate and normalise a worksheet tree (functions › failures › modes;
    a function's own ``modes`` sit directly under it, with no functional
    failure yet)."""
    if not isinstance(functions, list):
        raise RcmValidationError("functions must be a list.")
    out = []
    for fn in functions:
        cleaned_fn = {
            "id": _node_id(fn),
            "text": _require_text(fn, "function"),
            "failures": [],
        }
        if fn.get("modes"):
            cleaned_fn["modes"] = [_clean_mode(mode) for mode in fn["modes"]]
        standard = str(fn.get("standard") or "").strip()
        if standard:
            cleaned_fn["standard"] = standard
        for failure in fn.get("failures") or []:
            cleaned_failure = {
                "id": _node_id(failure),
                "text": _require_text(failure, "functional failure"),
                "modes": [_clean_mode(mode) for mode in failure.get("modes") or []],
            }
            cleaned_fn["failures"].append(cleaned_failure)
        out.append(cleaned_fn)
    return out


# ---- Evidence resolution (live validation) -----------------------------------

def evidence_fetcher(db, owner_id, hidden=frozenset()):
    """fetch(type, id): the linked model, analysis or report a reader
    (``owner_id``) can open, or None; each looked up once
    (backend/maintenance/rcm_graph.py reads a whole worksheet with one). A
    working is on the graph, so the read hands it over (the decision's
    ``working``), not this."""
    memo: dict = {}

    def fetch(etype: str, eid: str):
        key = (etype, eid)
        if key not in memo:
            if eid in hidden:
                memo[key] = None
            elif etype == "model":
                memo[key] = models_service.get_model(db, eid, owner_id)
            elif etype == "strategy_analysis":
                memo[key] = strategy_store.get_analysis(db, eid, owner_id)
            elif etype == "degradation_model":
                memo[key] = degradation_service.get_model(db, eid, owner_id)
            elif etype == "report":
                memo[key] = _report(db, eid, owner_id)
            else:
                memo[key] = None
        return memo[key]

    return fetch


def _report(db, report_id, owner_id):
    """A report the reader owns ({id, name}), or None. Reports are their owner's
    only (backend/services/reports.py)."""
    if not isinstance(report_id, str) or not report_id:
        return None
    owners = access.owner_in(owner_id) if owner_id is not None else None
    query = {"_id": report_id} | ({"owner_id": {"$in": owners}} if owners is not None else {})
    doc = db[reports_service.COLLECTION].find_one(query, {"name": 1})
    return SimpleNamespace(id=doc["_id"], name=doc.get("name") or "Untitled report") if doc else None


def blank_rollup() -> dict:
    return {"modes": 0, "decided": 0, "supported": 0, "contradicted": 0,
            "inconclusive": 0, "unevidenced": 0, "stale": 0, "partly": 0}


def resolve_decision(decision: dict, fetch) -> dict:
    """A decision's evidence status ({status, reason or summary, artifact_name,
    artifact_link_path, expected_evidence, evidence_kind}) against what
    ``fetch`` finds. A combination of tasks is checked member by member
    (_resolve_combination)."""
    if len(decision.get("outcomes") or []) > 1:
        return _resolve_combination(decision, fetch)
    out = _resolve_decision(decision, fetch)
    kind = evidence_kind((decision.get("evidence") or {}).get("type"))
    return out | {"evidence_kind": kind} if kind else out


# A combination's members in words ("the fixed-interval task").
_MEMBER_WORD = {"on_condition": "on condition", "fixed_interval": "fixed interval",
                "failure_finding": "failure finding", "redesign": "redesign"}
# The strategy analyses each scheduled outcome takes (their kinds): the interval
# calculators on the task card save on_condition_interval and failure_finding_interval.
_ANALYSIS_KIND = {"fixed_interval": ("optimal_replacement",),
                  "failure_finding": ("failure_finding", "failure_finding_interval"),
                  "on_condition": ("on_condition_interval",)}
# Evidence an outcome takes besides the type it expects: an on-condition task's
# interval from the P-F calculator (a saved analysis), as well as its degradation model.
ALSO_TAKES = {"on_condition": ("strategy_analysis",)}


def _takes(outcome: str, etype: str) -> bool:
    return etype == EXPECTED_EVIDENCE.get(outcome) or etype in ALSO_TAKES.get(outcome, ())


def _member_words(m: dict, members: list[dict]) -> str:
    """A member in words: its kind ("fixed interval"), with its task's name when
    the combination has more than one of that kind ("fixed interval “Deep clean”")."""
    word = _MEMBER_WORD.get(m["outcome"], m["outcome"])
    same = sum(1 for x in members if x["outcome"] == m["outcome"])
    name = str(m.get("task") or "").strip()
    return f"{word} “{name}”" if same > 1 and name else word


def _tasks_words(missing: list[dict], members: list[dict]) -> str:
    """"the fixed interval task", "the on condition and fixed interval tasks",
    "the fixed interval “Deep clean” task"."""
    words = [_member_words(m, members) for m in missing]
    if len(words) == 1:
        return f"the {words[0]} task"
    return f"the {', '.join(words[:-1])} and {words[-1]} tasks"


def _fits(outcome: str, evidence: dict, fetch) -> bool:
    """Whether the decision's evidence could be meant for this member (a
    fallback is tried only on the members it fits): a report or a function's
    notes fit any, a model or analysis only the outcome that expects its kind."""
    if evidence["type"] in LINKED_TYPES:
        return True
    if not _takes(outcome, evidence["type"]):
        return False
    if evidence["type"] == "strategy_analysis":
        artifact = fetch(evidence["type"], evidence["id"])
        if artifact is None:
            return evidence["type"] == EXPECTED_EVIDENCE.get(outcome)
        return getattr(artifact, "kind", None) in _ANALYSIS_KIND[outcome]
    return True


def _resolve_member(member: dict, decision: dict, fetch) -> dict:
    """One member of a combination checked as a decision of its own: its own
    evidence, else the decision's (when it fits this member). A redesign is
    checked only with evidence of its own (a report or notes); it needs none."""
    own = member.get("evidence")
    shared = decision.get("evidence")
    outcome = member["outcome"]
    if own:
        evidence, working, source = own, member.get("working"), "own"
    elif shared and outcome != "redesign" and _fits(outcome, shared, fetch):
        evidence, working, source = shared, decision.get("working"), "decision"
    else:
        evidence = working = source = None
    if outcome == "redesign" and not (evidence and evidence["type"] in LINKED_TYPES):
        return {"status": None}
    as_one = {"outcome": outcome, "interval": member.get("interval"), "interval_unit": member.get("interval_unit"),
              "evidence": evidence, "working": working}
    out = _resolve_decision(as_one, fetch)
    if evidence:
        out |= {"evidence_kind": evidence_kind(evidence["type"]), "evidence_from": source}
    elif shared:
        out["reason"] = (f"No evidence for this task: the decision's {_type_label(shared['type'])} is for another "
                         "of its tasks. Link one for this task.")
    return out


def _resolve_combination(decision: dict, fetch) -> dict:
    """A combination of tasks is evidenced when every scheduled member is:
    each checked on its own (its own evidence, else the decision's where it
    fits), then one status for the whole. Any contradicted, stale or
    inconclusive member makes the whole so (that member named); every member
    supported (or linked) is supported (or linked); some evidenced and some
    not is "partly" ("Partly evidenced: the fixed-interval task has none.");
    none is unevidenced. ``outcomes`` comes back with each member's check."""
    members = []
    for member in decision["outcomes"]:
        members.append({**member, **_resolve_member(member, decision, fetch)})
    counted = [m for m in members if m.get("status")]

    def word(m: dict) -> str:
        return _member_words(m, members).capitalize()

    out: dict = {"outcomes": members}
    for status in ("contradicted", "stale", "inconclusive"):
        hit = next((m for m in counted if m["status"] == status), None)
        if hit is not None:
            out |= {"status": status, "reason": f"{word(hit)} task: {hit.get('summary') or hit.get('reason') or ''}"}
            break
    else:
        missing = [m for m in counted if m["status"] == "unevidenced"]
        evidenced = [m for m in counted if m["status"] in ("supported", "linked")]
        if not counted:
            out["status"] = None
        elif not evidenced:
            first = counted[0]
            return out | {"status": "unevidenced", "reason": "No supporting analysis linked yet for any of its tasks.",
                          "expected_evidence": first.get("expected_evidence")}
        elif missing:
            out |= {"status": "partly",
                    "reason": f"Partly evidenced: {_tasks_words(missing, members)} {'has' if len(missing) == 1 else 'have'} "
                              "none."}
        else:
            out |= {"status": "supported" if all(m["status"] == "supported" for m in evidenced) else "linked",
                    "summary": "Evidenced for each task. " + " ".join(
                        f"{word(m)}: {m.get('summary') or m.get('reason') or ''}" for m in evidenced)}
    # The evidence the chip opens: the member that decided the status, else the first with any.
    lead = next((m for m in counted if m.get("status") == out.get("status") and m.get("artifact_link_path")), None) \
        or next((m for m in counted if m.get("artifact_name")), None)
    if lead is not None:
        out |= {k: lead[k] for k in ("artifact_name", "artifact_link_path", "evidence_kind") if lead.get(k)}
    return out


_LINKED_LABEL = {"report": "Report", "working": "Function's notes and rationale"}


def _resolve_linked(decision: dict, evidence: dict, fetch) -> dict:
    """A report or a working: linked, not checked. "linked" while it's there to
    open, "stale" once it has gone; never supported or contradicted."""
    kind = evidence["type"]
    if kind == "report":
        report = fetch("report", evidence["id"])
        if report is None:
            return {"status": "stale", "reason": "The linked report no longer exists."}
        name, path = report.name, f"/reports?open={report.id}"
    else:
        working = decision.get("working")
        if not working:
            return {"status": "stale", "reason": "The linked working has gone: its function was deleted or its "
                                                 "notes and rationale were cleared."}
        name, path = working.get("text") or "Function", f"/asset-register/explorer?tab=rcm&sel={working['id']}"
    what = "report" if kind == "report" else "function's notes"
    return {"status": "linked", "artifact_name": name, "artifact_link_path": path,
            "summary": f"{_LINKED_LABEL[kind]} linked: open it to read the case. Reliafy doesn't check a {what} "
                       "against the decision."}


def _resolve_decision(decision: dict, fetch) -> dict:
    outcome = decision["outcome"]
    evidence = decision.get("evidence")

    # A report or a working can stand behind any decision, a redesign or an accepted risk too.
    if evidence and evidence.get("type") in LINKED_TYPES:
        return _resolve_linked(decision, evidence, fetch)

    if outcome in ("redesign", "accept"):
        return {"status": None, "reason": "Default action — no supporting analysis required."}

    expected = EXPECTED_EVIDENCE[outcome]
    if outcome == "rtf":
        expected = "model" if decision.get("rtf_basis") == "random" else "strategy_analysis"

    if not evidence:
        return {
            "status": "unevidenced",
            "reason": "No supporting analysis linked yet.",
            "expected_evidence": expected,
        }

    artifact = fetch(evidence["type"], evidence["id"])
    if artifact is None:
        return {"status": "stale", "reason": "The linked analysis no longer exists."}

    if outcome == "on_condition" and evidence["type"] == "strategy_analysis":
        base = {"artifact_name": artifact.name, "artifact_link_path": _link_path(evidence["type"], artifact.id)}
        return {**base, **_check_on_condition_interval(decision, artifact)}

    if evidence["type"] != expected:
        return {
            "status": "inconclusive",
            "reason": f"Linked evidence is a {_type_label(evidence['type'])} — this decision needs a {_type_label(expected)}.",
            "artifact_name": artifact.name,
            "artifact_link_path": _link_path(evidence["type"], artifact.id),
        }

    base = {
        "artifact_name": artifact.name,
        "artifact_link_path": _link_path(evidence["type"], artifact.id),
    }
    if outcome == "rtf" and decision.get("rtf_basis") == "random":
        return {**base, **_check_randomness(artifact)}
    if outcome == "rtf":  # uneconomic
        return {**base, **_check_replacement(artifact, want_beneficial=False)}
    if outcome == "fixed_interval":
        mismatch = _unit_mismatch(decision, (artifact.results or {}).get("unit"))
        if mismatch:
            return {**base, **mismatch}
        return {**base, **_check_replacement(artifact, want_beneficial=True)}
    if outcome == "on_condition":
        mismatch = _unit_mismatch(decision, (artifact.results or {}).get("unit"))
        if mismatch:
            return {**base, **mismatch}
        if artifact.status == "ready":
            r = artifact.results or {}
            unit = f" {r['measurement_unit']}" if r.get("measurement_unit") else ""
            return {**base, "status": "supported",
                    "summary": f"Degradation model (threshold {r.get('threshold')}{unit}) supports condition monitoring."}
        return {**base, "status": "inconclusive", "reason": "The degradation model isn't ready."}
    if outcome == "failure_finding":
        if artifact.kind not in _ANALYSIS_KIND["failure_finding"]:
            return {**base, "status": "inconclusive",
                    "reason": "The linked analysis isn't a failure-finding interval."}
        r = artifact.results or {}
        mismatch = _unit_mismatch(decision, r.get("unit"))
        if mismatch:
            return {**base, **mismatch}
        if artifact.kind == "failure_finding_interval":
            from backend.services.rcm_intervals import DAYS_IN
            from backend.units import normalize_unit

            longest = None
            if r.get("basis") == "target" and r.get("interval") and DAYS_IN.get(normalize_unit(r.get("unit"))):
                longest = float(r["interval"]) * DAYS_IN[normalize_unit(r["unit"])]
            return {**base, **_interval_summary(r, decision, longest, "the longest that meets the target")}
        interval = r.get("interval")
        if interval is not None:
            unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
            return {**base, "status": "supported",
                    "summary": f"Check every ~{fmt_num(interval)}{unit} for {r.get('target_availability', 0):.0%} availability."}
        return {**base, "status": "inconclusive", "reason": "The analysis has no computed interval."}
    return {**base, "status": "inconclusive", "reason": "Unrecognised decision."}


def _task_days(decision: dict):
    """The task's interval in days, or None when it has none or its unit isn't a time."""
    from backend.services.rcm_intervals import DAYS_IN
    from backend.units import normalize_unit

    try:
        interval = float(decision.get("interval"))
    except (TypeError, ValueError):
        return None
    factor = DAYS_IN.get(normalize_unit(decision.get("interval_unit")))
    return interval * factor if factor else None


def _interval_summary(r: dict, decision: dict, longest_days, too_long: str) -> dict:
    """A saved interval calculation (the task card's calculators) as evidence: what it
    found; contradicted when the task's interval is longer than ``longest_days``."""
    if not r.get("recommended"):
        return {"status": "contradicted", "summary": r.get("summary") or "The calculation finds checking never pays."}
    days = _task_days(decision)
    if days is not None and longest_days is not None and days > longest_days * 1.0001:
        return {"status": "contradicted", "summary": f"The task's interval is longer than {too_long}. {r.get('summary') or ''}".strip()}
    return {"status": "supported", "summary": r.get("summary") or "Interval calculated."}


def _check_on_condition_interval(decision: dict, analysis) -> dict:
    """An on-condition task's interval from the P-F calculator (a saved analysis)."""
    if analysis.kind != "on_condition_interval":
        return {"status": "inconclusive",
                "reason": "The linked analysis isn't an on-condition interval (the P-F calculator); an on-condition "
                          "task takes that or a degradation model."}
    r = analysis.results or {}
    mismatch = _unit_mismatch(decision, r.get("unit"))
    if mismatch:
        return mismatch
    from backend.services.rcm_intervals import DAYS_IN
    from backend.units import normalize_unit

    pf_days = None
    factor = DAYS_IN.get(normalize_unit(r.get("pf_unit")))
    if factor and r.get("pf_interval"):
        # The net P-F interval: the warning less the time needed to act on it.
        pf_days = (float(r["pf_interval"]) - float(r.get("act_time") or 0)) * factor
    return _interval_summary(r, decision, pf_days, "the (net) P-F interval: checks that far apart miss warnings")


def _check_randomness(model) -> dict:
    """Evidence check for RTF-because-random against a saved non-repairable model."""
    results = model.results or {}
    if results.get("kind") == "regression":
        return {"status": "inconclusive",
                "reason": "A regression model can't establish randomness — fit a Weibull or Exponential."}
    randomness = results.get("randomness")
    if randomness is None:
        if results.get("distribution_id") in ("weibull", "exponential"):
            return {"status": "inconclusive",
                    "reason": "No confidence interval on this fit — re-save the model to compute it."}
        return {"status": "inconclusive",
                "reason": "This distribution can't establish randomness — fit a Weibull or Exponential."}
    verdict = randomness.get("verdict")
    if randomness.get("basis") == "memoryless":
        return {"status": "supported", "summary": "Exponential fit — memoryless: failures are random."}

    beta = randomness.get("beta")
    ci = randomness.get("beta_ci")
    ci_s = f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""
    beta_s = f"β = {beta:.2f}{ci_s}" if beta is not None else ""
    if verdict == "random":
        return {"status": "supported", "summary": f"{beta_s} — consistent with random (constant-rate) failure."}
    if verdict == "wear_out":
        return {"status": "contradicted",
                "summary": f"{beta_s} — the CI excludes 1: this is wear-out. Run-to-failure is not justified by this model."}
    if verdict == "infant_mortality":
        return {"status": "contradicted",
                "summary": f"{beta_s} — infant mortality, not random failure."}
    return {"status": "inconclusive",
            "reason": "No confidence interval on β — re-save the model to compute it."}


def _check_replacement(analysis, want_beneficial: bool) -> dict:
    """Evidence check against a saved optimal-replacement analysis."""
    if analysis.kind != "optimal_replacement":
        return {"status": "inconclusive",
                "reason": "The linked analysis isn't an optimal-replacement calculation."}
    r = analysis.results or {}
    beneficial = bool(r.get("beneficial"))
    unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
    if beneficial and want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        return {"status": "supported",
                "summary": f"Optimal interval ≈ {fmt_num(t)}{unit} ({savings:.0%} saving vs run-to-failure)."}
    if not beneficial and not want_beneficial:
        return {"status": "supported",
                "summary": "Preventive replacement shows no cost benefit — run-to-failure is optimal."}
    if beneficial and not want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        return {"status": "contradicted",
                "summary": f"The analysis finds replacement at ~{fmt_num(t)}{unit} saves {savings:.0%} — run-to-failure is uneconomic."}
    return {"status": "contradicted",
            "summary": "The analysis finds no beneficial interval — fixed-interval replacement isn't justified."}


def _type_label(etype: str) -> str:
    return {
        "model": "non-repairable model",
        "strategy_analysis": "saved strategy analysis",
        "degradation_model": "degradation model",
        "report": "report",
        "working": "function's notes and rationale",
    }.get(etype, etype)


def _link_path(etype: str, artifact_id: str) -> str:
    return {
        "model": f"/models/m/{artifact_id}",
        "strategy_analysis": f"/strategy/analyses/{artifact_id}",
        "degradation_model": f"/models/degradation/{artifact_id}",
    }[etype]


# Public names for the tree's callers.
norm_unit = _norm_unit
clean_decision = _clean_decision
check_randomness = _check_randomness
