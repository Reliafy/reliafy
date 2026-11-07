"""A position's FME(C)A as an Excel workbook (``GET /api/maintenance/positions/{id}/fmea.xlsx``).

One sheet, "FMECA", one row per failure mode (a second row per further task,
as the RCM tab's CSV export writes them; a combination of tasks one row per
member, in its order), the header frozen. The columns are
the RCM export's with the FME(C)A fields after Consequence, named as the
worksheet import's synonyms, so the file imports again adding nothing. A mode
directly under a function (no functional failure yet) has a blank Functional
failure cell; a mode under none has blank function cells too.

Notes and rationale: a function's (Function notes) and a functional
failure's (Functional failure notes) on its first row; a performance
standard's (Standard notes) on its own row; a failure mode's (Failure mode
notes) on its row. The import reads each back. A function's notes hold the
working behind its standard, so the Standard working column stays blank (it
is kept so older files and this one line up).
"""

from __future__ import annotations

import io
import re

from backend.maintenance import fmea, rcm_decisions

HEADER = [
    "Position", "Function", "Function notes", "Performance standard", "Standard notes", "Standard working",
    "Functional failure", "Functional failure notes", "Caused by (below)",
    "Failure mode", "Effects", "Consequence",
    "Cause", "Local effect", "Next higher effect", "Detection method", "Severity", "Occurrence", "Detection", "RPN",
    "Action priority", "Recommended action", "Action owner", "Action due", "Action status", "Failure rate",
    "Time unit", "Rate source", "Mode ratio", "Loss probability", "Operating time", "Mode criticality",
    "Severity class",
    "Decision", "Run-to-failure basis", "Task", "Interval", "Interval unit", "Evidence check", "Failure mode notes",
]
SHEET = "FMECA"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_CONSEQUENCE = {c["id"]: c["label"] for c in rcm_decisions.CONSEQUENCE_OPTIONS}
_OUTCOME = {o["id"]: o["label"] for o in rcm_decisions.OUTCOME_OPTIONS}
_STATUS = {"supported": "Supported", "contradicted": "Contradicted", "inconclusive": "Inconclusive",
           "stale": "Stale link", "partly": "Partly evidenced"}
# Linked, not checked: what's linked says which ("Report linked", "Notes linked": a function's notes and rationale).
_LINKED = {"report": "Report linked", "working": "Notes linked"}
_AP = fmea.AP_LABELS
_FILENAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _caused_by(fail: dict) -> str:
    return "; ".join(f"{(c.get('position') or {}).get('name') or ''} › {c['text']}"
                     for c in fail.get("causes") or [] if c.get("inside") is not False)


def _standard_cell(fn: dict, fail: dict | None) -> str:
    if fn.get("standards"):
        return ((fail or {}).get("standard") or {}).get("text") or ""
    return fn.get("standard") or ""


def _scores(m: dict) -> list:
    return [
        m.get("cause") or "", m.get("effect_local") or "", m.get("effect_next") or "",
        m.get("detection_method") or "", m.get("severity"), m.get("occurrence"), m.get("detection"), m.get("rpn"),
        _AP.get(m.get("ap") or "", ""), m.get("action") or "", m.get("action_owner") or "", m.get("action_due") or "",
        (m.get("action_status") or "").replace("_", " "), m.get("failure_rate"), m.get("time_unit") or "",
        m.get("rate_source") or "", m.get("mode_ratio"), m.get("loss_probability"), m.get("operating_time"),
        m.get("cm"), m.get("severity_class") or "",
    ]


def rows(worksheet: dict) -> list[list]:
    """The header and one row per failure mode of a resolved RCM read
    (rcm_graph.resolve over Maintenance.rcm_worksheet)."""
    out = [list(HEADER)]
    blank_scores = [""] * len(_scores({}))
    path: list[str] = []
    for p in worksheet.get("positions") or []:
        del path[p.get("depth") or 0:]
        path.append(p["name"])
        where = " › ".join(path)
        written: set = set()

        def first_row(fn) -> bool:
            if not fn or fn["id"] in written:
                return False
            written.add(fn["id"])
            return True

        def mode_row(fn, fail, m) -> list:
            first = first_row(fn)
            first_fail = first_row(fail)
            d = (m or {}).get("decision") or {}
            status = d.get("status")
            return [
                where, (fn or {}).get("text") or "", (first and (fn or {}).get("notes")) or "",
                _standard_cell(fn or {}, fail), "",
                "", (fail or {}).get("text") or "",
                (first_fail and (fail or {}).get("notes")) or "",
                _caused_by(fail or {}), (m or {}).get("text") or "", (m or {}).get("effects") or "",
                _CONSEQUENCE.get((m or {}).get("consequence") or "", ""),
                *(_scores(m) if m else blank_scores),
                _OUTCOME.get(d.get("outcome") or "", ""), d.get("rtf_basis") or "", d.get("task") or "",
                d.get("interval") if d.get("interval") is not None else "",
                (d.get("interval_unit") or "") if d.get("interval") else "",
                (_LINKED.get(d.get("evidence_kind"), "Linked") if status == "linked" else _STATUS.get(status, status))
                if status and status != "unevidenced" else "",
                (m or {}).get("notes") or "",
            ]

        def task_row(fn, fail, m, t) -> list:
            return [
                where, (fn or {}).get("text") or "", "", _standard_cell(fn or {}, fail), "", "",
                (fail or {}).get("text") or "", "", _caused_by(fail or {}), m.get("text") or "", "", "", *blank_scores,
                _OUTCOME.get(t.get("outcome") or (m.get("decision") or {}).get("outcome") or "", ""), "",
                t.get("text") or t.get("name") or "", t.get("interval") if t.get("interval") is not None else "",
                (t.get("unit") or "") if t.get("interval") else "", "", "",
            ]

        def mode_rows(fn, fail, m) -> None:
            out.append(mode_row(fn, fail, m))
            d = m.get("decision") or {}
            members = d.get("outcomes") or []
            # A combination of tasks: a row per further member, in its order (a redesign
            # with no task too), so the import builds the same combination; then any
            # task outside the decision.
            for o in members[1:]:
                out.append(task_row(fn, fail, m, {"outcome": o["outcome"], "text": o.get("task") or "",
                                                  "interval": o.get("interval"), "unit": o.get("interval_unit")}))
            in_members = {o.get("task_id") for o in members}
            for t in (d.get("tasks") or [])[1:]:
                if t.get("id") not in in_members:
                    out.append(task_row(fn, fail, m, t))

        for m in p.get("unassigned") or []:
            mode_rows(None, None, m)
        for fn in p.get("functions") or []:
            if fn.get("standards"):
                first = first_row(fn)
                for i, st in enumerate(fn["standards"]):
                    out.append([where, fn.get("text") or "", (first and i == 0 and fn.get("notes")) or "",
                                st.get("text") or "", st.get("notes") or "",
                                "", "", "", "", "", "", "",
                                *blank_scores, "", "", "", "", "", "", ""])
            for m in fn.get("modes") or []:  # directly under the function: no functional failure yet
                mode_rows(fn, None, m)
            if not fn.get("failures") and not fn.get("modes") and not fn.get("standards"):
                out.append(mode_row(fn, None, None))
            for fail in fn.get("failures") or []:
                if not fail.get("modes"):
                    out.append(mode_row(fn, fail, None))
                for m in fail.get("modes") or []:
                    mode_rows(fn, fail, m)
    return out


def workbook(worksheet: dict) -> bytes:
    """The rows as an .xlsx: one sheet, the header row frozen and bold."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    for row in rows(worksheet):
        ws.append(row)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename(name) -> str:
    """"Conveyor C-2 FMECA.xlsx": the position's name without characters a file name can't have."""
    safe = " ".join(_FILENAME_BAD.sub(" ", str(name or "Position")).split()).strip()
    return f"{safe[:80] or 'Position'} FMECA.xlsx"
