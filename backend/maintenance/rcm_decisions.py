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
from backend.units import unit_in_text, with_unit


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
#: Linked records on the maintenance graph (Nov 2026): a position's (or its class's) failure history,
#: a measuring point's readings and a failure report. The read hands each over (the decision's
#: ``linked``: {name, path, summary} or None once it has gone), as it does a working.
GRAPH_TYPES = ("history", "point", "failure_report")
LINKED_TYPES = ("report", "working") + GRAPH_TYPES
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


def advice(consequence, outcome, outcomes=None, hidden=..., tasks=0) -> str | None:
    """A word on a decision the diagram wouldn't make now (a saved one from
    before, or an import's): never a refusal on read, the analyst changes it
    when they next review the mode. Also asks for a hidden mode's category.
    ``outcomes``: every outcome of a combination of tasks (its members').
    ``hidden``: the mode's first answer; left out, it's read from the
    consequence as mode_consequence reads a saved mode. ``tasks``: how many
    live tasks serve the mode (run to failure and accept stand alone)."""
    return review(consequence, outcome, outcomes, hidden, tasks)[0]


# A decision that breaks the rules: it doesn't count as decided until it's
# looked at again (the rollups' needs_review, the RCM tab's "Needs review").
_STANDS_ALONE = {
    "rtf": "Run to failure stands alone",
    "accept": "Accept stands alone",
    "redesign": "A redesign on its own schedules no task",
}


def review(consequence, outcome, outcomes=None, hidden=..., tasks=0) -> tuple[str | None, bool]:
    """(advice, needs_review): the word advice() gives, and whether the saved
    decision breaks the decision rules (needs a look before it counts as
    decided): a decision with no consequence answered, one the diagram refuses,
    or run to failure, accept or a redesign alone with tasks serving the mode.
    The other words (a hidden mode with no failure-finding task, a combination
    on a cost consequence) are a nudge, not a fault."""
    if hidden is ...:
        hidden, consequence = mode_consequence({"consequence": consequence})
    members = [o for o in (outcomes or [outcome]) if o]
    if hidden and consequence not in CONSEQUENCES:
        return ("This failure is hidden: say what the multiple failure would do (the hidden failure plus the one "
                "it protects against): safety, environmental, operational or non-operational."), bool(members)
    if not members:
        return None, False
    if consequence not in CONSEQUENCES:
        return ("This failure mode is decided but its consequence isn't answered: say what the failure would do "
                "(safety, environmental, operational or non-operational), then check the decision still "
                "follows."), True
    why = refusal(hidden, consequence, members)
    if why:
        return f"{why} This decision is kept as it was saved; change it when you next review this failure mode.", True
    if len(members) == 1 and members[0] in _STANDS_ALONE and tasks:
        n = f"{tasks} task{'s' if tasks != 1 else ''} serve{'s' if tasks == 1 else ''}"
        fix = ("make the decision the task it is (on condition, fixed interval or failure finding), or retire the "
               "task" if members[0] != "redesign" else
               "make the decision the redesign beside its task (a combination), or retire the task")
        return f"{_STANDS_ALONE[members[0]]}, yet {n} this failure mode: {fix}.", True
    if hidden and consequence in CONSEQUENCES and not any(o in SCHEDULED for o in members) and "redesign" not in members:
        return ("A hidden failure gets a failure-finding task before no scheduled maintenance, if one is worth "
                "doing: say in the notes why none is."), False
    if sum(1 for o in members if o in SCHEDULED) > 1 and consequence in ("operational", "non_operational"):
        return ("A combination of tasks on a cost consequence: each task must pay for itself over time (RCM II "
                "reserves combinations for safety and environmental consequences). Say in the notes why both "
                "are worth doing."), False
    return None, False


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
    "fh": "hours", "flight hours": "hours", "flight hour": "hours",
}


def _norm_unit(unit) -> str:
    u = str(unit or "").strip().lower()
    return _UNIT_ALIASES.get(u, u)


def _unit_mismatch(decision: dict, evidence_unit) -> dict | None:
    """Inconclusive result when the task interval's unit contradicts the
    evidence's time unit. Units are free text, so only a definite
    disagreement (both present, different after normalisation) trips this —
    a missing unit on either side passes. Two units of the same kind (an
    analysis in hours, a task in days) are no mismatch: the evidence is read
    in the task's unit (:func:`_unit_conversion`).
    """
    from backend.services import running_clock

    task_unit = _norm_unit(decision.get("interval_unit"))
    ev_unit = _norm_unit(evidence_unit)
    if _unit_conversion(decision, evidence_unit) is not None:
        return None
    clock = _clock(decision)
    if clock is not None and running_clock.same_clock(decision.get("interval_unit"), evidence_unit):
        return None  # flight hours and hours at a position: both its running hours
    why = running_clock.refusal(evidence_unit, decision.get("interval_unit"), clock, "evidence")
    if why:
        return {"status": "inconclusive", "reason": why}
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


def _clock(decision: dict):
    """The position's clock a decision is checked at (running_clock.Clock), or None off a
    position (an RCM study): set by :func:`resolve_decision`."""
    return decision.get("_clock")


def _unit_conversion(decision: dict, evidence_unit) -> dict | None:
    """``{"from", "to", "factor"}`` when the evidence's unit converts to the task interval's
    (hours, days, weeks, months, years to each other; km and miles); None otherwise. On a
    position, running hours (hours, operating or flight hours) meet the calendar at its duty,
    else all the time (running_clock)."""
    from backend.services import running_clock

    return running_clock.conversion(evidence_unit, decision.get("interval_unit"), _clock(decision))


def _with_conversion(result: dict, decision: dict, evidence_unit, amount=None) -> dict:
    """An evidence check's result with what it converted said: "evidence in hours, task
    interval in days: converted at 1 day = 24 hours" off a position; on one, "1,000 h ≈ 125
    days at this position's duty (8 h a day)" (``amount``: the evidence's interval, in its
    unit) (on the summary too)."""
    conv = _unit_conversion(decision, evidence_unit)
    if conv is None or result.get("status") == "inconclusive":
        return result
    from backend.services import running_clock

    try:
        amount = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount = None
    note = running_clock.note(conv, amount if conv.get("clock") is not None else None, "task interval", "evidence")
    out = {**result, "unit_conversion": note}
    if out.get("summary"):
        out["summary"] = f"{out['summary']} ({note[:1].upper()}{note[1:]}.)"
    return out


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
    out = {"type": etype, "id": eid.strip()}
    window = clean_window(evidence.get("window"))
    if window:
        if etype not in ("model", "history"):
            raise RcmValidationError("A date window goes with a life model or a failure history, the lives it rests on.")
        out["window"] = window
    return out


def clean_window(value) -> dict | None:
    """The lives a fit or a failure history rests on ({since?, until?}: fitment start dates, ISO days,
    with lives? and failures?: the counts it was fitted from), or None for all of them."""
    from datetime import date

    if not value:
        return None
    if not isinstance(value, dict):
        raise RcmValidationError("window is {since?, until?}: the first and last fitment start dates it uses.")
    out: dict = {}
    for key in ("since", "until"):
        v = value.get(key)
        if v in (None, ""):
            continue
        try:
            out[key] = date.fromisoformat(str(v)[:10]).isoformat()
        except ValueError:
            raise RcmValidationError(f"window {key} is a date, e.g. 2022-01-01.") from None
    if out.get("since") and out.get("until") and out["until"] < out["since"]:
        raise RcmValidationError("The window's until date is before its since date.")
    if not out:
        return None
    for key in ("lives", "failures"):
        v = value.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10_000_000:
            out[key] = v
    return out


def _day_words(iso: str) -> str:
    from datetime import date

    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


def window_words(window: dict | None) -> str:
    """"52 lives fitted since 1 Jan 2022 (2 failed)": what a windowed fit or history rests on."""
    if not window:
        return ""
    since, until = window.get("since"), window.get("until")
    span = (f"between {_day_words(since)} and {_day_words(until)}" if since and until
            else f"since {_day_words(since)}" if since else f"up to {_day_words(until)}")
    lives = window.get("lives")
    head = f"{lives:,} li{'fe' if lives == 1 else 'ves'} fitted {span}" if lives is not None else f"lives fitted {span}"
    failed = window.get("failures")
    return head + (f" ({failed:,} failed)" if failed is not None else "")


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

    def prefetch(refs) -> None:
        """Read these (type, id) at once, one query per kind, into the memo: the same
        documents, scoped the same way, as fetching each would."""
        from backend.db import from_doc
        from backend.schema import DegradationModelDoc, Model, StrategyAnalysis

        kinds = {"model": ("models", Model), "strategy_analysis": ("strategy_analyses", StrategyAnalysis),
                 "degradation_model": ("degradation_models", DegradationModelDoc)}
        wanted: dict = {}
        for etype, eid in refs:
            if etype not in kinds or not isinstance(eid, str) or not eid or (etype, eid) in memo:
                continue
            if eid in hidden or (etype == "model" and eid.startswith("repairable:")):
                continue  # looked up one at a time, as before
            wanted.setdefault(etype, set()).add(eid)
        for etype, ids in wanted.items():
            collection, cls = kinds[etype]
            query = {"_id": {"$in": sorted(ids)}}
            if owner_id is not None:
                query["owner_id"] = {"$in": access.owner_in(owner_id)}
            found = {d["_id"]: d for d in db[collection].find(query)}
            for eid in ids:
                memo[(etype, eid)] = from_doc(cls, found.get(eid))

    fetch.prefetch = prefetch
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
    """A rollup's counts. needs_review: decided, but against the decision rules
    (review above), so not counted as all decided."""
    return {"modes": 0, "decided": 0, "supported": 0, "contradicted": 0,
            "inconclusive": 0, "unevidenced": 0, "stale": 0, "partly": 0, "needs_review": 0,
            SHORTER_THAN_EVIDENCE: 0, LONGER_THAN_EVIDENCE: 0}


def rollup_state(rollup: dict) -> str:
    """The status chip's state for a rollup: empty (no failure modes), to_decide
    (some undecided), needs_review (all decided, some against the rules) or
    all_decided."""
    if not rollup.get("modes"):
        return "empty"
    if rollup["modes"] > rollup.get("decided", 0):
        return "to_decide"
    return "needs_review" if rollup.get("needs_review") else "all_decided"


def finish_rollup(rollup: dict) -> dict:
    """A rollup with its undecided count and state worked out."""
    return {**rollup, "undecided": max(0, rollup["modes"] - rollup["decided"]), "state": rollup_state(rollup)}


def resolve_decision(decision: dict, fetch, clock=None) -> dict:
    """A decision's evidence status ({status, reason or summary, artifact_name,
    artifact_link_path, expected_evidence, evidence_kind}) against what
    ``fetch`` finds. A combination of tasks is checked member by member
    (_resolve_combination). ``clock``: the position's (running_clock.for_position),
    so running hours meet a calendar interval at its duty; None off a position."""
    if clock is not None:
        decision = {**decision, "_clock": clock}
    if len(decision.get("outcomes") or []) > 1:
        return _resolve_combination(decision, fetch)
    out = _resolve_decision(decision, fetch)
    evidence = decision.get("evidence") or {}
    kind = evidence_kind(evidence.get("type"))
    if evidence.get("window"):
        # What the evidence rests on, said where the rationale shows it.
        out = out | {"window": evidence["window"], "window_words": window_words(evidence["window"])}
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
        evidence, working, linked, source = own, member.get("working"), member.get("linked"), "own"
    elif shared and outcome != "redesign" and _fits(outcome, shared, fetch):
        evidence, working, linked, source = shared, decision.get("working"), decision.get("linked"), "decision"
    else:
        evidence = working = linked = source = None
    if outcome == "redesign" and not (evidence and evidence["type"] in LINKED_TYPES):
        return {"status": None}
    as_one = {"outcome": outcome, "interval": member.get("interval"), "interval_unit": member.get("interval_unit"),
              "evidence": evidence, "working": working, "linked": linked, "_clock": _clock(decision)}
    out = _resolve_decision(as_one, fetch)
    if evidence:
        out |= {"evidence_kind": evidence_kind(evidence["type"]), "evidence_from": source}
        if evidence.get("window"):
            out |= {"window": evidence["window"], "window_words": window_words(evidence["window"])}
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
    for status in ("contradicted", "stale", "inconclusive", *INTERVAL_DIFFERS):
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


_LINKED_LABEL = {"report": "Report", "working": "Function's notes and rationale", "history": "Failure history",
                 "point": "Condition readings", "failure_report": "Failure report"}
_LINKED_WHAT = {"report": "report", "working": "function's notes", "history": "failure history",
                "point": "set of readings", "failure_report": "failure report"}


def _resolve_linked(decision: dict, evidence: dict, fetch) -> dict:
    """A report or a working: linked, not checked. "linked" while it's there to
    open, "stale" once it has gone; never supported or contradicted."""
    kind = evidence["type"]
    if kind in GRAPH_TYPES:
        ref = decision.get("linked")
        if not ref:
            return {"status": "stale", "reason": f"The linked {_LINKED_WHAT[kind]} has gone: it was deleted or "
                                                 "retired."}
        return {"status": "linked", "artifact_name": ref.get("name") or _LINKED_LABEL[kind],
                "artifact_link_path": ref.get("path"),
                "summary": f"{_LINKED_LABEL[kind]} linked{': ' + ref['summary'] if ref.get('summary') else ''}. "
                           f"Open it to read the case; Reliafy doesn't check a {_LINKED_WHAT[kind]} against the "
                           "decision."}
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
    """The evidence check (_resolve_decision_core), and, when the evidence is an Optimise
    analysis whose model has been refitted since, a line saying its optimum may have moved
    (``refitted``): the status stays as it is, and the interval isn't changed by itself."""
    out = _resolve_decision_core(decision, fetch)
    evidence = decision.get("evidence") or {}
    if evidence.get("type") == "strategy_analysis" and evidence.get("id"):
        from backend.maintenance.task_optimise import refitted_note

        artifact = fetch("strategy_analysis", evidence["id"])
        note = refitted_note(artifact, fetch) if artifact is not None else None
        if note:
            out = {**out, "refitted": note,
                   "summary": f"{out.get('summary') or out.get('reason') or ''} {note}".strip()}
    return out


def _resolve_decision_core(decision: dict, fetch) -> dict:
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

    if evidence["type"] == "model" and expected == "strategy_analysis":
        # A fitted life model behind an interval: it says how the item fails, not what interval pays.
        # Linked, not checked (like a report), with what would check it.
        return {
            "status": "linked", "evidence_kind": "model",
            "artifact_name": artifact.name, "artifact_link_path": _link_path("model", artifact.id),
            "summary": "Life model linked: it shows how the item fails, but not which interval pays. To check "
                       "the interval, run Optimal replacement on this model, save it and link the analysis.",
        }

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
        conv = _unit_conversion(decision, (artifact.results or {}).get("unit"))
        checked = _check_replacement(artifact, want_beneficial=True, conv=conv)
        if checked.get("status") == "supported":
            r = artifact.results or {}
            # Far from the cost-optimal age is a fact about the interval, not a verdict on
            # the decision: its own neutral status, with both intervals in the summary.
            checked = _far_shorter(checked, decision, r.get("optimal_time"), r.get("unit"), "the cost-optimal interval",
                                   status=SHORTER_THAN_EVIDENCE)
            checked = _far_longer(checked, decision, r.get("optimal_time"), r.get("unit"), "the cost-optimal interval",
                                  status=LONGER_THAN_EVIDENCE)
        return {**base, **_with_conversion(checked, decision,
                                           (artifact.results or {}).get("unit"),
                                           (artifact.results or {}).get("optimal_time"))}
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
            from backend.services import running_clock

            longest = None
            per = running_clock.days_in(r.get("unit"), _clock(decision))
            if r.get("basis") == "target" and r.get("interval") and per:
                longest = float(r["interval"]) * per
            return {**base, **_interval_summary(r, decision, longest, "the longest that meets the target")}
        interval = r.get("interval")
        if interval is not None:
            unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
            checked = _far_shorter({
                "status": "supported",
                "summary": f"Check every ~{fmt_num(interval)}{unit} for {r.get('target_availability', 0):.0%} availability."},
                decision, interval, r.get("unit"), "the interval that meets the availability target")
            return {**base, **_with_conversion(checked, decision, r.get("unit"), interval)}
        return {**base, "status": "inconclusive", "reason": "The analysis has no computed interval."}
    return {**base, "status": "inconclusive", "reason": "Unrecognised decision."}


def _task_days(decision: dict):
    """The task's interval in days, or None when it has none or its unit isn't a time (on a
    position, running hours are days at its duty: running_clock)."""
    from backend.services import running_clock

    try:
        interval = float(decision.get("interval"))
    except (TypeError, ValueError):
        return None
    factor = running_clock.days_in(decision.get("interval_unit"), _clock(decision))
    return interval * factor if factor else None


def _interval_summary(r: dict, decision: dict, longest_days, too_long: str) -> dict:
    """A saved interval calculation (the task card's calculators) as evidence: what it
    found; contradicted when the task's interval is longer than ``longest_days``."""
    if not r.get("recommended"):
        return {"status": "contradicted", "summary": r.get("summary") or "The calculation finds checking never pays."}
    days = _task_days(decision)
    if days is not None and longest_days is not None and days > longest_days * 1.0001:
        return {"status": "contradicted", "summary": f"The task's interval is longer than {too_long}. {r.get('summary') or ''}".strip()}
    checked = _far_shorter({"status": "supported", "summary": r.get("summary") or "Interval calculated."},
                           decision, r.get("interval"), r.get("unit"), "the calculated interval")
    # Longer than the (net) longest allowed stays contradicted above (it misses failures);
    # this is only a long interval still inside that limit.
    return _far_longer(checked, decision, r.get("interval"), r.get("unit"), "the calculated interval")


#: A task set at less than this share of the interval its evidence supports is flagged:
#: done that much more often than the evidence needs, it costs work for no reduction in
#: risk the evidence shows. Shorter than that (a 50 h service against a 63 h check
#: interval) is ordinary rounding to a service plan.
FAR_SHORTER = 0.5


def _task_share(decision: dict, interval, evidence_unit):
    """The task's interval as a share of the evidence's (``interval`` in
    ``evidence_unit``), or None when either is missing or they can't be compared.
    A unit missing on either side is read as the same unit, as the unit check does."""
    try:
        task = float(decision.get("interval"))
        supported = float(interval)
    except (TypeError, ValueError):
        return None
    if task <= 0 or supported <= 0:
        return None
    task_unit, ev_unit = _norm_unit(decision.get("interval_unit")), _norm_unit(evidence_unit)
    if not task_unit or not ev_unit or task_unit == ev_unit:
        return task / supported
    conv = _unit_conversion(decision, evidence_unit)
    if conv is None or not conv.get("factor"):
        return None
    return task / (supported * conv["factor"])


#: A fixed-interval task far from its cost-optimal age (under half, or over twice, it):
#: amber, not red. The interval differs from what the evidence supports; whether that's
#: wrong (a warranty, a shutdown plan, a safety margin) is the analyst's call.
SHORTER_THAN_EVIDENCE = "shorter_than_evidence"
LONGER_THAN_EVIDENCE = "longer_than_evidence"
INTERVAL_DIFFERS = (SHORTER_THAN_EVIDENCE, LONGER_THAN_EVIDENCE)


def _far_shorter(result: dict, decision: dict, interval, evidence_unit, what: str,
                 status: str = SHORTER_THAN_EVIDENCE) -> dict:
    """A supported check made plain when the task's interval is far shorter than the
    evidence supports (under :data:`FAR_SHORTER` of it): both intervals, how many
    times as often the task is done, then what the evidence found. The status is the
    neutral amber shorter_than_evidence everywhere (cost-optimal age, P-F and
    failure-finding intervals): a fact about the interval, not a verdict. Anything else
    is returned as it is."""
    share = _task_share(decision, interval, evidence_unit)
    if result.get("status") != "supported" or share is None or share >= FAR_SHORTER:
        return result
    task_unit = decision.get("interval_unit") or evidence_unit
    ev_unit = evidence_unit or decision.get("interval_unit")
    set_s = with_unit(fmt_num(float(decision["interval"])), unit_in_text(task_unit))
    ev_s = with_unit(fmt_num(float(interval)), unit_in_text(ev_unit))
    times_s = f"{round(1 / share):,}"  # at least 2: the share is under a half
    found = result.get("summary") or ""
    return {**result, "status": status, "interval_share": round(share, 4),
            "summary": f"The task is set every {set_s}, far shorter than {what} its evidence supports, about "
                       f"{ev_s}: it is done about {times_s} times as often as the evidence needs. {found}".strip()}


def _far_longer(result: dict, decision: dict, interval, evidence_unit, what: str,
                status: str = LONGER_THAN_EVIDENCE) -> dict:
    """The mirror of :func:`_far_shorter`, for a fixed-interval task against its
    cost-optimal age (the calculators flag any interval longer than theirs already):
    a task set at more than 1 / :data:`FAR_SHORTER` times the interval its evidence
    supports reads ``status`` (longer_than_evidence), with both intervals and how many times as long it is,
    then what the evidence found. Anything else is returned as it is."""
    share = _task_share(decision, interval, evidence_unit)
    if result.get("status") != "supported" or share is None or share <= 1 / FAR_SHORTER:
        return result
    task_unit = decision.get("interval_unit") or evidence_unit
    ev_unit = evidence_unit or decision.get("interval_unit")
    set_s = with_unit(fmt_num(float(decision["interval"])), unit_in_text(task_unit))
    ev_s = with_unit(fmt_num(float(interval)), unit_in_text(ev_unit))
    times = round(share)  # at least 2: the share is over 2
    times_s = "twice" if times == 2 else f"{times:,} times"
    found = result.get("summary") or ""
    return {**result, "status": status, "interval_share": round(share, 4),
            "summary": f"The task is set every {set_s}, far longer than {what} its evidence supports, about "
                       f"{ev_s}: about {times_s} as long as the evidence supports. {found}".strip()}


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
    from backend.services import running_clock

    pf_days = None
    factor = running_clock.days_in(r.get("pf_unit"), _clock(decision))
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


def _check_replacement(analysis, want_beneficial: bool, conv: dict | None = None) -> dict:
    """Evidence check against a saved optimal-replacement analysis. ``conv``: the analysis's
    unit converted to the task's, so its interval is also given in the task's unit."""
    if analysis.kind != "optimal_replacement":
        return {"status": "inconclusive",
                "reason": "The linked analysis isn't an optimal-replacement calculation."}
    r = analysis.results or {}
    beneficial = bool(r.get("beneficial"))
    unit = f" {unit_in_text(r['unit'])}" if r.get("unit") else ""
    if beneficial and want_beneficial:
        t = r.get("optimal_time")
        savings = r.get("savings") or 0
        also = ""
        if conv is not None and t is not None:
            also = f", about {fmt_num(float(t) * conv['factor'])} {unit_in_text(conv['to'])}"
        return {"status": "supported",
                "summary": f"Optimal interval ≈ {fmt_num(t)}{unit}{also} ({savings:.0%} saving vs run-to-failure)."}
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
        "history": "failure history",
        "point": "set of condition readings",
        "failure_report": "failure report",
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
