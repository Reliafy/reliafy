"""FME(C)A scoring on the failure modes of the maintenance tree.

The FME(C)A tab and the RCM tab are two views of one set of records: a failure
mode is one FailureMode node, and its scores (severity, occurrence, detection,
the cause and effects, the recommended action, the criticality figures) live
on that node, written by the ``failure_mode.scored`` event. This module holds
what is pure: the field vocabulary and its checks, the risk priority number,
the action priority table, the criticality arithmetic and the per-position
summary. Nothing here reads the graph or the clock.

Everything computed (rpn, ap, cm, a position's cr) is worked out on each read,
never stored, so a change to the table changes every read at once.
"""

from __future__ import annotations

from datetime import date

LONG_TEXT = 4000  # the same ceiling as the service's notes and descriptions
SHORT_TEXT = 200


class FmeaError(ValueError):
    """A score or field that can't be taken as given (user-facing text)."""


# ---- the fields -----------------------------------------------------------------

SCORES = ("severity", "occurrence", "detection")
LONG_FIELDS = ("cause", "effect_local", "effect_next", "effects", "detection_method", "action")
SHORT_FIELDS = ("action_owner", "time_unit")
ACTION_STATUSES = ("open", "in_progress", "done")
RATE_SOURCES = ("entered", "model", "data")
SEVERITY_CLASSES = ("I", "II", "III", "IV")
CRITICALITY = ("failure_rate", "mode_ratio", "loss_probability", "operating_time")

#: Every field the scored event may carry, in the order the worksheet shows them.
#: ``effects`` (the end effect) is the RCM analysis's own field, written by
#: failure_mode.analysed, so it isn't here: the same text shows on both tabs.
FIELDS = (
    "cause", "effect_local", "effect_next", "detection_method",
    "severity", "occurrence", "detection",
    "action", "action_owner", "action_due", "action_status",
    "failure_rate", "time_unit", "rate_source", "mode_ratio", "loss_probability", "operating_time",
    "severity_class",
)

LABELS = {
    "cause": "Cause(s)", "effect_local": "Local effect", "effect_next": "Next higher effect",
    "effects": "End effect", "detection_method": "Detection method / current controls",
    "severity": "Severity", "occurrence": "Occurrence", "detection": "Detection",
    "action": "Recommended action", "action_owner": "Action owner", "action_due": "Action due",
    "action_status": "Action status", "failure_rate": "Failure rate", "time_unit": "Time unit",
    "rate_source": "Rate source", "mode_ratio": "Mode ratio", "loss_probability": "Loss probability",
    "operating_time": "Operating time", "severity_class": "Severity class",
}

ACTION_STATUS_OPTIONS = [
    {"id": "open", "label": "Open"}, {"id": "in_progress", "label": "In progress"}, {"id": "done", "label": "Done"},
]
RATE_SOURCE_OPTIONS = [
    {"id": "entered", "label": "Entered"}, {"id": "model", "label": "From a model"}, {"id": "data", "label": "From own data"},
]
SEVERITY_CLASS_OPTIONS = [
    {"id": "I", "label": "I Catastrophic"}, {"id": "II", "label": "II Critical"},
    {"id": "III", "label": "III Marginal"}, {"id": "IV", "label": "IV Minor"},
]

# One line per rank, shown as a tooltip beside the score: kept generic (no
# standard's wording), the analyst's own scale sheet says more.
SCALES = {
    "severity": [
        "No effect", "Very minor: barely noticed", "Minor: a slight annoyance",
        "Very low: a small loss of performance", "Low: some loss of performance",
        "Moderate: works, at a reduced level", "High: does not work; no safety effect",
        "Very high: does not work; a safety effect is possible", "Hazardous, with warning", "Hazardous, no warning",
    ],
    "occurrence": [
        "Almost never", "Remote: very few failures", "Low: few failures", "Low to moderate: occasional failures",
        "Moderate: occasional failures", "Moderate to high: repeated failures", "High: frequent failures",
        "High: very frequent failures", "Very high: failure almost inevitable", "Almost certain",
    ],
    "detection": [
        "Almost certain to detect", "Very high chance of detection", "High chance of detection",
        "Moderately high chance of detection", "Moderate chance of detection", "Low chance of detection",
        "Very low chance of detection", "Remote chance of detection", "Very remote chance of detection",
        "Cannot detect",
    ],
}

SCORE_MESSAGES = {
    "severity": "Severity is a whole number from 1 (no effect) to 10 (hazardous without warning).",
    "occurrence": "Occurrence is a whole number from 1 (almost never) to 10 (almost certain).",
    "detection": "Detection is a whole number from 1 (almost certain to detect) to 10 (cannot detect).",
}


# ---- the action priority table --------------------------------------------------
# Our own implementation of the publicly known AIAG-VDA (2019) action priority
# rule: severity, occurrence and detection are banded, and each (S band, O band)
# row gives the priority per D band. WRITTEN FROM MEMORY of the public table:
# check it against the handbook before any public claim about conformance. It
# replaces the RPN threshold as the thing to sort by; the RPN is still shown.

SEVERITY_BANDS = [("s1", 1, 1), ("s2", 2, 3), ("s4", 4, 6), ("s7", 7, 8), ("s9", 9, 10)]
OCCURRENCE_BANDS = [("o1", 1, 1), ("o2", 2, 3), ("o4", 4, 5), ("o6", 6, 7), ("o8", 8, 10)]
DETECTION_BANDS = [("d1", 1, 1), ("d2", 2, 4), ("d5", 5, 6), ("d7", 7, 10)]
_D_COLUMNS = ("d7", "d5", "d2", "d1")

# (S band, O band) -> priority for d7, d5, d2, d1.
_AP_ROWS = {
    ("s9", "o8"): "HHHH", ("s9", "o6"): "HHHH", ("s9", "o4"): "HHHM", ("s9", "o2"): "HMLL", ("s9", "o1"): "LLLL",
    ("s7", "o8"): "HHHH", ("s7", "o6"): "HHHM", ("s7", "o4"): "HMMM", ("s7", "o2"): "MMLL", ("s7", "o1"): "LLLL",
    ("s4", "o8"): "HHMM", ("s4", "o6"): "MMML", ("s4", "o4"): "MLLL", ("s4", "o2"): "LLLL", ("s4", "o1"): "LLLL",
    ("s2", "o8"): "MMLL", ("s2", "o6"): "LLLL", ("s2", "o4"): "LLLL", ("s2", "o2"): "LLLL", ("s2", "o1"): "LLLL",
    ("s1", "o8"): "LLLL", ("s1", "o6"): "LLLL", ("s1", "o4"): "LLLL", ("s1", "o2"): "LLLL", ("s1", "o1"): "LLLL",
}
AP_TABLE = {(s, o): dict(zip(_D_COLUMNS, row)) for (s, o), row in _AP_ROWS.items()}
AP_LABELS = {"H": "High", "M": "Medium", "L": "Low"}


def _band(bands, value: int) -> str:
    for name, low, high in bands:
        if low <= value <= high:
            return name
    raise FmeaError(f"{value} is outside 1 to 10.")


def band_of(field: str, value: int) -> str:
    """The band a score falls in ("s9", "o4", "d2"), for the matrix."""
    bands = {"severity": SEVERITY_BANDS, "occurrence": OCCURRENCE_BANDS, "detection": DETECTION_BANDS}[field]
    return _band(bands, value)


def rpn(severity, occurrence, detection):
    """The risk priority number, severity × occurrence × detection (1 to
    1000), or None unless all three are set."""
    if severity is None or occurrence is None or detection is None:
        return None
    return int(severity) * int(occurrence) * int(detection)


def action_priority(severity, occurrence, detection):
    """"H", "M" or "L" from the action priority table, or None unless all
    three scores are set."""
    if severity is None or occurrence is None or detection is None:
        return None
    row = AP_TABLE[(band_of("severity", int(severity)), band_of("occurrence", int(occurrence)))]
    return row[band_of("detection", int(detection))]


def mode_criticality(loss_probability, mode_ratio, failure_rate, operating_time):
    """Cm = β × α × λ × t (MIL-STD-1629A style): the expected number of this
    mode's failures over the operating time that end in the loss the severity
    class names. None unless all four are set."""
    if any(v is None for v in (loss_probability, mode_ratio, failure_rate, operating_time)):
        return None
    return float(loss_probability) * float(mode_ratio) * float(failure_rate) * float(operating_time)


def item_criticality(cms) -> float | None:
    """Cr: the sum of the modes' Cm (None when none has one)."""
    found = [float(c) for c in cms if c is not None]
    return sum(found) if found else None


# ---- validation ------------------------------------------------------------------

def _whole(value, field: str) -> int:
    if isinstance(value, bool):
        raise FmeaError(SCORE_MESSAGES[field])
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise FmeaError(SCORE_MESSAGES[field]) from None
    if not number.is_integer() or not 1 <= number <= 10:
        raise FmeaError(SCORE_MESSAGES[field])
    return int(number)


def _number(value, message: str) -> float:
    if isinstance(value, bool):
        raise FmeaError(message)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise FmeaError(message) from None
    if number != number or number in (float("inf"), float("-inf")):
        raise FmeaError(message)
    return number


def _text(value, field: str, limit: int) -> str:
    text = " ".join(str(value).split("\r")).strip()
    if len(text) > limit:
        raise FmeaError(f"{LABELS[field]} is at most {limit} characters; this one is {len(text)}. Shorten it.")
    return text


def clean_value(field: str, value):
    """One field's value checked and normalised; None (or "") clears it."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if field in SCORES:
        return _whole(value, field)
    if field in LONG_FIELDS:
        return _text(value, field, LONG_TEXT)
    if field in SHORT_FIELDS:
        return _text(value, field, SHORT_TEXT)
    if field == "action_due":
        text = str(value).strip()[:10]
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise FmeaError("The due date is a date (YYYY-MM-DD).") from None
    if field == "action_status":
        status = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        if status not in ACTION_STATUSES:
            raise FmeaError("Action status is open, in_progress or done.")
        return status
    if field == "rate_source":
        source = str(value).strip().lower()
        if source not in RATE_SOURCES:
            raise FmeaError("Rate source is entered, model or data.")
        return source
    if field == "severity_class":
        cls = str(value).strip().upper()
        if cls not in SEVERITY_CLASSES:
            raise FmeaError("Severity class is I, II, III or IV.")
        return cls
    if field == "failure_rate":
        number = _number(value, "The failure rate (λ) is a number of failures per unit of time, 0 or more.")
        if number < 0:
            raise FmeaError("The failure rate (λ) is a number of failures per unit of time, 0 or more.")
        return number
    if field == "mode_ratio":
        number = _number(value, "The mode ratio (α) is a number from 0 to 1: the share of the item's failures that "
                                "are this mode.")
        if not 0 <= number <= 1:
            raise FmeaError("The mode ratio (α) is a number from 0 to 1: the share of the item's failures that are "
                            "this mode.")
        return number
    if field == "loss_probability":
        number = _number(value, "The loss probability (β) is a number from 0 to 1: the chance the mode's effect is "
                                "the loss the severity class names.")
        if not 0 <= number <= 1:
            raise FmeaError("The loss probability (β) is a number from 0 to 1: the chance the mode's effect is the "
                            "loss the severity class names.")
        return number
    if field == "operating_time":
        number = _number(value, "The operating time (t) is a number greater than 0, in the time unit.")
        if number <= 0:
            raise FmeaError("The operating time (t) is a number greater than 0, in the time unit.")
        return number
    raise FmeaError(f"Unknown FME(C)A field '{field}': the fields are {', '.join(FIELDS)}.")


def validate_changes(changes) -> dict:
    """``changes`` ({field: value}) checked: unknown keys refused, every value
    normalised, None or "" meaning "clear". Returns the cleaned dict, with the
    keys given (cleared ones as None)."""
    if not isinstance(changes, dict):
        raise FmeaError("changes is an object of FME(C)A fields and their values.")
    out = {}
    for field, value in changes.items():
        if field not in FIELDS:
            raise FmeaError(f"Unknown FME(C)A field '{field}': the fields are {', '.join(FIELDS)}.")
        out[field] = clean_value(field, value)
    return out


# ---- what a read shows -----------------------------------------------------------

def mode_fields(node: dict) -> dict:
    """The §1 fields of a FailureMode node (absent → None) plus rpn, ap and cm."""
    out = {k: node.get(k) for k in FIELDS}
    out["rpn"] = rpn(out["severity"], out["occurrence"], out["detection"])
    out["ap"] = action_priority(out["severity"], out["occurrence"], out["detection"])
    out["cm"] = mode_criticality(out["loss_probability"], out["mode_ratio"], out["failure_rate"],
                                 out["operating_time"])
    return out


def position_summary(modes) -> dict:
    """A position's FME(C)A at a glance from its live modes' views: how many,
    how many scored (all three of S/O/D), the action priority counts, the
    highest RPN, Cr (the sum of every Cm) and Cr by severity class."""
    scored = [m for m in modes if m.get("rpn") is not None]
    by_ap = {"H": 0, "M": 0, "L": 0}
    for m in scored:
        by_ap[m["ap"]] += 1
    with_cm = [m for m in modes if m.get("cm") is not None]
    by_class: dict = {}
    for m in with_cm:
        cls = m.get("severity_class")
        if cls:
            by_class[cls] = by_class.get(cls, 0.0) + m["cm"]
    return {
        "modes": len(modes), "scored": len(scored),
        "high": by_ap["H"], "medium": by_ap["M"], "low": by_ap["L"],
        "max_rpn": max((m["rpn"] for m in scored), default=None),
        "cr": item_criticality(m["cm"] for m in with_cm),
        "cr_by_class": {cls: by_class[cls] for cls in SEVERITY_CLASSES if cls in by_class},
    }


def _bands_out(bands) -> list[dict]:
    return [{"id": name, "min": low, "max": high, "label": f"{low}" if low == high else f"{low}–{high}"}
            for name, low, high in bands]


def options() -> dict:
    """The FME(C)A vocabulary for the app: the action priority table (by S
    band, then O band, then D band), the bands low to high, the choice lists
    and the ten-line scale hints, so the frontend never hardcodes them."""
    table: dict = {}
    for (s, o), row in AP_TABLE.items():
        table.setdefault(s, {})[o] = dict(row)
    return {
        "ap_table": table,
        "ap_bands": {"severity": _bands_out(SEVERITY_BANDS), "occurrence": _bands_out(OCCURRENCE_BANDS),
                     "detection": _bands_out(DETECTION_BANDS)},
        "ap_labels": dict(AP_LABELS),
        "severity_classes": [dict(x) for x in SEVERITY_CLASS_OPTIONS],
        "action_statuses": [dict(x) for x in ACTION_STATUS_OPTIONS],
        "rate_sources": [dict(x) for x in RATE_SOURCE_OPTIONS],
        "scales": {k: list(v) for k, v in SCALES.items()},
        "fields": list(FIELDS),
        "labels": dict(LABELS),
    }
