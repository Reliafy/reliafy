"""Turn an FMEA / RCM spreadsheet into an RCM study worksheet.

Typical FMEA and RCM worksheets are one row per failure mode, with the
function and functional failure written once and left blank (or merged) on
the rows below. :func:`build_tree` reads such a table — from any source, via
:mod:`backend.services.excel` in practice — through a column mapping::

    {"function": "Function", "failure": "Functional failure",
     "mode": "Failure mode", "effects": "Effect", ...}

into the ``functions → failures → modes`` tree that
:func:`backend.services.rcm.clean_tree` validates:

* ``mode`` is the only required column; ``function`` / ``failure`` carry down
  from the row above when blank, and when not mapped at all every mode goes
  under one "Imported" function / functional failure;
* consequence and decision-type cells are free text mapped onto Reliafy's
  categories — by an explicit per-value map from the user, else by
  :func:`guess_consequence` / :func:`guess_outcome` where the wording is
  unambiguous, else left unset (never guessed at random);
* a task / interval with no decision type can't be a decision (a decision
  needs its outcome), so it's kept in the mode's notes instead;
* columns with no home in the worksheet (FMEA severity / occurrence /
  detection / RPN, item, cause…) can be appended to the mode's notes as
  "Severity 8 · Occurrence 4 · …" — there's no FMEA scoring module yet.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.services import rcm
from backend.services.excel import has_words as _has
from backend.services.excel import norm

MAX_MODES = 5000
MAX_TEXT = 2000
MAX_LISTED_VALUES = 100

IMPORTED = "Imported"

# Column-mapping targets, with header synonyms for the auto-guess (see
# backend.services.excel.guess_mapping).
FIELDS = [
    {"id": "function", "label": "Function",
     "help": "What the asset must do. Blank cells carry down from the row above.",
     "synonyms": ["function", "function description", "primary function", "functions", "system function"]},
    {"id": "standard", "label": "Performance standard",
     "help": "Optional: how well it must do it.",
     "synonyms": ["performance standard", "standard", "performance", "performance requirement"]},
    {"id": "failure", "label": "Functional failure",
     "help": "How it fails to do it. Blank cells carry down.",
     "synonyms": ["functional failure", "functional failures", "failure", "failure description", "function failure", "loss of function"]},
    {"id": "mode", "label": "Failure mode", "required": True,
     "help": "What causes the functional failure (one row per mode).",
     "synonyms": ["failure mode", "failure modes", "mode", "potential failure mode", "failure cause", "cause of failure", "cause", "root cause"]},
    {"id": "effects", "label": "Effects",
     "help": "What happens when it fails.",
     "synonyms": ["failure effect", "failure effects", "effect", "effects", "effect of failure", "potential effect", "potential effects of failure", "end effect", "local effect", "consequence description"]},
    {"id": "consequence", "label": "Consequence",
     "help": "Safety / environmental / operational / non-operational / hidden — values are mapped below.",
     "synonyms": ["consequence", "consequences", "consequence category", "failure consequence", "consequence type", "consequence class", "category"]},
    {"id": "outcome", "label": "Decision / task type",
     "help": "On-condition, fixed-interval, run-to-failure… — values are mapped below.",
     "synonyms": ["task type", "decision", "maintenance strategy", "strategy", "task category", "maintenance type", "policy", "maintenance policy", "action type", "task class", "decision outcome"]},
    {"id": "task", "label": "Task",
     "help": "The proposed task or recommended action.",
     "synonyms": ["task", "proposed task", "maintenance task", "recommended action", "recommended actions", "recommended task", "action", "actions", "task description", "pm task", "mitigation"]},
    {"id": "interval", "label": "Interval",
     "help": "A number (with the unit column), or text like “6 months” / “weekly”.",
     "synonyms": ["interval", "task interval", "initial interval", "frequency", "task frequency", "period"]},
    {"id": "interval_unit", "label": "Interval unit",
     "help": "Hours, days, months, cycles…",
     "synonyms": ["interval unit", "unit", "units", "frequency unit", "interval units"]},
    {"id": "notes", "label": "Notes",
     "help": "Comments or remarks, kept on the failure mode.",
     "synonyms": ["notes", "note", "comments", "comment", "remarks", "remark", "rationale", "justification"]},
]
FIELD_IDS = [f["id"] for f in FIELDS]

# Unmapped columns ticked by default for "append to the mode's notes".
EXTRA_SYNONYMS = [
    "severity", "sev", "s", "occurrence", "occ", "o", "probability", "likelihood",
    "detection", "detectability", "det", "d", "rpn", "risk priority number", "risk",
    "criticality", "risk rating", "risk level", "item", "component", "equipment", "part",
    "asset", "sub system", "subsystem", "assembly", "cause", "failure cause", "causes",
    "mechanism", "failure mechanism", "current controls", "detection method", "controls",
    "tag", "item number", "responsibility", "owner",
]

CONSEQUENCE_CHOICES = list(rcm.CONSEQUENCES)
# Decision choices a value can map to: run-to-failure carries its basis.
OUTCOME_CHOICES = [
    "on_condition", "fixed_interval", "rtf:random", "rtf:uneconomic",
    "failure_finding", "redesign", "accept",
]


# ---------------------------------------------------------------------------
# Value guesses
# ---------------------------------------------------------------------------


_CONSEQUENCE_LETTERS = {"h": "hidden", "s": "safety", "e": "environmental",
                        "o": "operational", "n": "non_operational"}
_CONSEQUENCE_WORDS = {
    "hidden": ["hidden", "hidden failure", "not evident", "non evident"],
    "safety": ["safety", "safety hazard", "injury", "personnel", "health and safety", "life safety"],
    "environmental": ["environmental", "environment", "env", "pollution", "spill", "emissions"],
    "operational": ["operational", "operations", "operating", "production", "production loss", "output", "availability", "downtime"],
    "non_operational": ["non operational", "nonoperational", "non operating", "economic", "repair cost", "cost only", "maintenance cost"],
}


def guess_consequence(raw: Any) -> Optional[str]:
    """Reliafy's consequence category for a free-text cell, when unambiguous.

    RCM II letters (H / S / E / O / N) and category words are recognised; a
    cell naming two categories (other than "hidden", which decides the path on
    its own) or a criticality score ("High", "3") isn't guessed."""
    t = norm(raw)
    if not t:
        return None
    if t in _CONSEQUENCE_LETTERS:
        return _CONSEQUENCE_LETTERS[t]
    if t.replace(" ", "_") in rcm.CONSEQUENCES:
        return t.replace(" ", "_")
    found = set()
    for cat, words in _CONSEQUENCE_WORDS.items():
        if any(_has(t, w) for w in words):
            found.add(cat)
    if "non_operational" in found:
        found.discard("operational")  # "non-operational" contains "operational"
    if "hidden" in found:
        return "hidden"
    return found.pop() if len(found) == 1 else None


_OUTCOME_WORDS = {
    "on_condition": ["on condition", "oncondition", "condition based", "condition based maintenance",
                     "condition monitoring", "cbm", "predictive", "predictive maintenance", "pdm"],
    "fixed_interval": ["fixed interval", "fixed time", "time based", "time based maintenance", "tbm",
                       "scheduled restoration", "scheduled discard", "scheduled replacement",
                       "hard time", "hard life", "preventive replacement", "periodic replacement",
                       "age based replacement", "block replacement", "scheduled overhaul"],
    "failure_finding": ["failure finding", "failure finding task", "fft", "functional test",
                        "function test", "proof test", "functional check"],
    "rtf": ["run to failure", "run to fail", "rtf", "breakdown maintenance", "corrective maintenance",
            "reactive maintenance", "fix on failure"],
    "redesign": ["redesign", "re design", "design change", "design modification", "modification",
                 "one time change", "engineering change"],
    "accept": ["accept", "accept risk", "risk accepted", "no scheduled maintenance", "no task",
               "no pm", "none", "no action", "nsm", "no scheduled task", "no proactive task"],
}


def guess_outcome(raw: Any) -> Optional[str]:
    """Reliafy's decision outcome for a free-text cell, when unambiguous.

    Run-to-failure is never guessed: Reliafy needs its basis (random failures
    or prevention uneconomic), which the wording doesn't say — the user picks
    it (see :func:`needs_choice`)."""
    t = norm(raw)
    if not t:
        return None
    if t.replace(" ", "_") in rcm.OUTCOMES and t != "rtf":
        return t.replace(" ", "_")
    found = {cat for cat, words in _OUTCOME_WORDS.items() if any(_has(t, w) for w in words)}
    if len(found) != 1:
        return None
    cat = found.pop()
    return None if cat == "rtf" else cat


def needs_choice(raw: Any) -> Optional[str]:
    """A hint for values the user must map themselves (shown in the UI)."""
    t = norm(raw)
    if any(_has(t, w) for w in _OUTCOME_WORDS["rtf"]):
        return "Run-to-failure — choose the basis (random failures, or prevention isn't economic)."
    return None


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------

_FREQUENCY_WORDS = {
    "daily": (1, "days"), "weekly": (1, "weeks"), "fortnightly": (2, "weeks"),
    "monthly": (1, "months"), "quarterly": (3, "months"), "half yearly": (6, "months"),
    "six monthly": (6, "months"), "semi annually": (6, "months"), "semi annual": (6, "months"),
    "annually": (1, "years"), "annual": (1, "years"), "yearly": (1, "years"),
}
_INTERVAL_RE = re.compile(r"^(?:every\s+)?(\d+(?:\.\d+)?)\s*([a-z][a-z .]*)?$")


def parse_interval(raw: Any) -> tuple[Optional[float], Optional[str]]:
    """``(interval, unit from the text)``; ``(None, None)`` when unreadable."""
    if raw is None or raw == "":
        return None, None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return (float(raw), None) if raw > 0 else (None, None)
    text = str(raw).strip().lower().replace(",", "")
    words = norm(text)
    if words in _FREQUENCY_WORDS:
        n, unit = _FREQUENCY_WORDS[words]
        return float(n), unit
    m = _INTERVAL_RE.match(text)
    if not m:
        return None, None
    value = float(m.group(1))
    unit = (m.group(2) or "").strip(" .") or None
    return (value, unit) if value > 0 else (None, None)


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------


class RcmImportError(ValueError):
    """A mapping or sheet that can't be imported (user-facing text)."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split()) if "\n" not in str(value) else str(value).strip()


def _choice(raw: Any, explicit: dict, guess) -> Optional[str]:
    key = _text(raw)
    if not key:
        return None
    if key in explicit:
        return explicit[key] or None
    return guess(key)


def _values(rows: list[list], col: Optional[int], guess, choices) -> list[dict]:
    """Distinct values of a column with counts and the automatic guess."""
    if col is None:
        return []
    seen: dict[str, int] = {}
    for r in rows:
        v = _text(r[col])
        if v:
            seen[v] = seen.get(v, 0) + 1
    out = []
    for v, n in list(seen.items())[:MAX_LISTED_VALUES]:
        g = guess(v)
        item = {"value": v, "count": n, "guess": g}
        hint = needs_choice(v) if choices is OUTCOME_CHOICES and g is None else None
        if hint:
            item["hint"] = hint
        out.append(item)
    return out


def build_tree(header: list[str], rows: list[list], options: dict,
               row_numbers: Optional[list[int]] = None) -> dict:
    """The worksheet tree a table maps to, plus what the UI shows about it::

        {"functions": [...],             # clean_tree-valid
         "counts": {"functions", "failures", "modes", "decisions", "skipped_rows"},
         "warnings": [str],
         "values": {"consequence": [{value, count, guess}], "outcome": [...]},
         "outcome_source": "outcome" | "task" | None}

    ``options``: ``mapping`` (field id -> column name), ``consequence_map`` /
    ``outcome_map`` (cell text -> category, ``""`` = leave unset; unlisted
    values use the guess), ``extra_columns`` (column names appended to the
    mode's notes).
    """
    options = options or {}
    mapping = {k: v for k, v in (options.get("mapping") or {}).items() if v}
    consequence_map = {str(k): str(v or "") for k, v in (options.get("consequence_map") or {}).items()}
    outcome_map = {str(k): str(v or "") for k, v in (options.get("outcome_map") or {}).items()}
    for v in consequence_map.values():
        if v and v not in CONSEQUENCE_CHOICES:
            raise RcmImportError(f"Unknown consequence “{v}”.")
    for v in outcome_map.values():
        if v and v not in OUTCOME_CHOICES:
            raise RcmImportError(f"Unknown decision type “{v}”.")

    index = {name: i for i, name in enumerate(header)}
    unknown = [f for f in mapping if f not in FIELD_IDS]
    if unknown:
        raise RcmImportError(f"Unknown worksheet field “{unknown[0]}”.")
    for field_id, col in mapping.items():
        if col not in index:
            raise RcmImportError(f"The sheet has no column “{col}” (mapped to {field_id}).")
    if "mode" not in mapping:
        raise RcmImportError("Map a column to Failure mode — it's the one required column.")
    extra = [c for c in (options.get("extra_columns") or []) if c in index and c not in mapping.values()]

    col = {f: index[mapping[f]] if f in mapping else None for f in FIELD_IDS}
    outcome_source = "outcome" if col["outcome"] is not None else "task" if col["task"] is not None else None
    outcome_col = col["outcome"] if col["outcome"] is not None else col["task"]
    numbers = row_numbers or list(range(2, len(rows) + 2))

    def cell(r, f):
        c = col[f]
        return _text(r[c]) if c is not None else ""

    functions: list[dict] = []
    fn_by_key: dict[str, dict] = {}
    warnings: list[str] = []
    skipped: list[int] = []
    truncated = 0
    cur_fn = cur_standard = cur_fail = ""
    n_modes = n_decisions = 0
    stashed_tasks = 0

    def clip(text: str) -> str:
        nonlocal truncated
        if len(text) > MAX_TEXT:
            truncated += 1
            return text[:MAX_TEXT - 1] + "…"
        return text

    for rnum, r in zip(numbers, rows):
        fn_text = cell(r, "function")
        if fn_text and fn_text != cur_fn:
            cur_fn, cur_standard, cur_fail = fn_text, cell(r, "standard"), ""
        elif cell(r, "standard"):
            cur_standard = cell(r, "standard")
        fail_text = cell(r, "failure")
        if fail_text:
            cur_fail = fail_text
        mode_text = cell(r, "mode")
        if not mode_text:
            structural = {"function", "standard", "failure"}
            if any(cell(r, f) for f in FIELD_IDS if f not in structural) or any(_text(r[index[c]]) for c in extra):
                skipped.append(rnum)
            continue
        if n_modes >= MAX_MODES:
            raise RcmImportError(
                f"The sheet has more than {MAX_MODES:,} failure modes — split it into several studies.")

        fn_name = clip(cur_fn or (IMPORTED if col["function"] is None else ""))
        if not fn_name:
            fn_name = IMPORTED
            warnings.append(f"Row {rnum}: no function above this failure mode — it went under “{IMPORTED}”.")
        fn_key = fn_name.lower()
        fn = fn_by_key.get(fn_key)
        if fn is None:
            fn = {"text": fn_name, "failures": [], "_by_key": {}}
            if cur_standard:
                fn["standard"] = clip(cur_standard)
            fn_by_key[fn_key] = fn
            functions.append(fn)
        elif cur_standard and not fn.get("standard"):
            fn["standard"] = clip(cur_standard)

        fail_name = clip(cur_fail or (IMPORTED if col["failure"] is None else ""))
        if not fail_name:
            fail_name = IMPORTED
            warnings.append(f"Row {rnum}: no functional failure above this failure mode — it went under “{IMPORTED}”.")
        failure = fn["_by_key"].get(fail_name.lower())
        if failure is None:
            failure = {"text": fail_name, "modes": []}
            fn["_by_key"][fail_name.lower()] = failure
            fn["failures"].append(failure)

        mode: dict = {"text": clip(mode_text), "consequence": None, "decision": None}
        effects = cell(r, "effects")
        if effects:
            mode["effects"] = clip(effects)
        if col["consequence"] is not None:
            mode["consequence"] = _choice(r[col["consequence"]], consequence_map, guess_consequence)

        notes: list[str] = []
        if cell(r, "notes"):
            notes.append(cell(r, "notes"))

        task = cell(r, "task")
        raw_interval = r[col["interval"]] if col["interval"] is not None else None
        interval, text_unit = parse_interval(raw_interval)
        unit = cell(r, "interval_unit") or text_unit or ""
        outcome = _choice(r[outcome_col], outcome_map, guess_outcome) if outcome_col is not None else None
        if outcome:
            decision: dict = {"outcome": outcome, "evidence": None}
            if outcome.startswith("rtf:"):
                decision["outcome"], decision["rtf_basis"] = "rtf", outcome.split(":", 1)[1]
            if task:
                decision["task"] = clip(task)
            if interval is not None:
                decision["interval"] = interval
                if unit:
                    decision["interval_unit"] = clip(unit)
            elif _text(raw_interval):
                notes.append(f"Interval: {_text(raw_interval)}")
            mode["decision"] = decision
            n_decisions += 1
        else:
            kept = []
            if task:
                kept.append(f"Task: {task}")
            if _text(raw_interval):
                unit_cell = cell(r, "interval_unit")
                kept.append(f"Interval: {_text(raw_interval)}{' ' + unit_cell if unit_cell else ''}")
            if col["outcome"] is not None and _text(r[col["outcome"]]):
                kept.append(f"{mapping['outcome']}: {_text(r[col['outcome']])}")
            if kept:
                notes.append(" · ".join(kept))
                stashed_tasks += 1

        scores = []
        for c in extra:
            v = _text(r[index[c]])
            if v:
                scores.append(f"{c} {v}")
        if scores:
            notes.append(" · ".join(scores))
        if notes:
            mode["notes"] = clip("\n".join(notes))
        failure["modes"].append(mode)
        n_modes += 1

    for fn in functions:
        fn.pop("_by_key", None)

    if n_modes == 0:
        raise RcmImportError(
            f"No failure modes found — the “{mapping['mode']}” column is empty. Check the "
            "header row and the column mapped to Failure mode.")
    if skipped:
        listed = ", ".join(str(n) for n in skipped[:8]) + (" …" if len(skipped) > 8 else "")
        warnings.append(
            f"{len(skipped)} row{'s' if len(skipped) != 1 else ''} with no failure mode "
            f"{'were' if len(skipped) != 1 else 'was'} skipped (row{'s' if len(skipped) != 1 else ''} {listed}).")
    if stashed_tasks:
        warnings.append(
            f"{stashed_tasks} failure mode{'s have' if stashed_tasks != 1 else ' has'} a task but no "
            "decision type, so the task was kept in the mode's notes — map the decision type "
            "values to turn them into decisions.")
    if truncated:
        warnings.append(f"{truncated} very long cell{'s were' if truncated != 1 else ' was'} shortened to {MAX_TEXT:,} characters.")

    try:
        cleaned = rcm.clean_tree(functions)
    except rcm.RcmValidationError as exc:  # pragma: no cover - built to be valid
        raise RcmImportError(str(exc)) from None

    values = {
        "consequence": _values(rows, col["consequence"], guess_consequence, CONSEQUENCE_CHOICES),
        "outcome": _values(rows, outcome_col, guess_outcome, OUTCOME_CHOICES),
    }
    for key in ("consequence", "outcome"):
        c = col["consequence"] if key == "consequence" else outcome_col
        if c is not None and len({_text(r[c]) for r in rows} - {""}) > MAX_LISTED_VALUES:
            warnings.append(
                f"The {key} column has more than {MAX_LISTED_VALUES} different values; only the "
                f"first {MAX_LISTED_VALUES} are listed for mapping (the rest use the automatic guess).")
    return {
        "functions": cleaned,
        "counts": {
            "functions": len(cleaned),
            "failures": sum(len(f["failures"]) for f in cleaned),
            "modes": n_modes,
            "decisions": n_decisions,
            "skipped_rows": len(skipped),
        },
        "warnings": warnings,
        "values": values,
        "outcome_source": outcome_source,
    }


def default_extra_columns(header: list[str], mapping: dict) -> list[str]:
    """Unmapped columns that look like FMEA scoring / item columns."""
    used = {c for c in (mapping or {}).values() if c}
    wanted = set(EXTRA_SYNONYMS)

    def looks_extra(h: str) -> bool:
        n = norm(h)
        return n in wanted or any(len(w) > 2 and _has(n, w) for w in wanted)

    return [h for h in header if h not in used and looks_extra(h)]
