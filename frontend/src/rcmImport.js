// A position's RCM in and out as a spreadsheet: the words for an import's
// preview (what an FMEA / RCM worksheet adds to the position, and what's
// there already), and the CSV a position's RCM downloads as. The CSV's
// columns are named as the import reads them, so the file can be edited and
// imported again; importing it onto the same position adds nothing.

import { toCsv } from "./csv.js";
import { CONSEQUENCE_LABEL, OUTCOME_LABEL, checkLabel } from "./rcmWorksheet.js";
import { AP_LABEL, CLASS_LABEL, SOURCE_LABEL, STATUS_LABEL as ACTION_STATUS_LABEL, cmOf, rpnOf } from "./fmea.js";

// The files the import takes: an Excel workbook or a CSV file.
export const WORKSHEET_ACCEPT = ".xlsx,.xlsm,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv";

// CSV has one table and no sheets to pick: the import goes straight to the columns.
export function isCsvFile(file) {
  return /\.(csv|txt)$/i.test(file?.name || "") || file?.type === "text/csv";
}

const n = (count, one, many = `${one}s`) => `${count.toLocaleString("en-AU")} ${count === 1 ? one : many}`;

// What the import adds and what it leaves, from the preview's counts:
// { adds: [...], there: [...], nothing } — `nothing` when it would add nothing.
export function importSummary(counts) {
  const c = counts || {};
  const adds = [
    c.functions ? n(c.functions, "function") : null,
    c.failures ? n(c.failures, "functional failure") : null,
    c.modes ? n(c.modes, "failure mode") : null,
    c.tasks ? n(c.tasks, "task") : null,
    c.combinations ? n(c.combinations, "combination of tasks", "combinations of tasks") : null,
    c.links ? n(c.links, "link between functional failures", "links between functional failures") : null,
  ].filter(Boolean);
  const there = [
    c.functions_existing ? n(c.functions_existing, "function") : null,
    c.failures_existing ? n(c.failures_existing, "functional failure") : null,
    c.modes_existing ? n(c.modes_existing, "failure mode") : null,
    c.links_existing ? n(c.links_existing, "link between functional failures", "links between functional failures") : null,
  ].filter(Boolean);
  return { adds, there, nothing: !c.functions && !c.failures && !c.modes && !c.links };
}

// The FME(C)A's columns come after Consequence, named as the import reads
// them (Owner and Due date are its synonyms for the action's owner and due
// date); RPN, Action priority and Mode criticality are worked out, never
// read back.
export const FMEA_HEADER = [
  "Cause", "Local effect", "Next higher effect", "Detection method", "Severity", "Occurrence", "Detection", "RPN", "Action priority",
  "Recommended action", "Owner", "Due date", "Action status", "Failure rate", "Time unit", "Rate source", "Mode ratio", "Loss probability",
  "Operating time", "Mode criticality", "Severity class",
];
// Every row kind's notes and rationale has its own column: Function notes and
// Functional failure notes on the first row of each (as the working is),
// Standard notes on each standard's own row, Failure mode notes on the mode's.
export const EXPORT_HEADER = [
  "Position", "Function", "Function notes", "Performance standard", "Standard notes", "Standard working",
  "Functional failure", "Functional failure notes", "Caused by (below)", "Failure mode", "Effects", "Consequence",
  ...FMEA_HEADER,
  "Decision", "Run-to-failure basis", "Task", "Interval", "Interval unit", "Evidence check", "Failure mode notes",
];
const BLANK_FMEA = FMEA_HEADER.map(() => "");

// A failure mode's FME(C)A cells, in FMEA_HEADER's order (blank for none).
export function fmeaCells(m) {
  if (!m) return BLANK_FMEA;
  const v = (x) => (x == null ? "" : x);
  const rpn = m.rpn ?? rpnOf(m.severity, m.occurrence, m.detection);
  const cm = m.cm ?? cmOf(m);
  return [
    v(m.cause), v(m.effect_local), v(m.effect_next), v(m.detection_method), v(m.severity), v(m.occurrence), v(m.detection),
    rpn ?? "", AP_LABEL[m.ap] || "", v(m.action), v(m.action_owner), v(m.action_due), ACTION_STATUS_LABEL[m.action_status] || "",
    v(m.failure_rate), m.failure_rate != null ? m.time_unit || "hours" : v(m.time_unit), SOURCE_LABEL[m.rate_source] || "",
    v(m.mode_ratio), v(m.loss_probability), v(m.operating_time), cm ?? "", CLASS_LABEL[m.severity_class] ? m.severity_class : "",
  ];
}

// The "Caused by (below)" cell: the lower failures that cause it (the links that
// count), each as "Position › failure", separated by "; ", in tree order.
export function causedBy(fail) {
  return (fail?.causes || []).filter((c) => c.inside !== false)
    .map((c) => `${c.position?.name || ""} › ${c.text}`).join("; ");
}

// A position's RCM (GET /api/maintenance/positions/{id}/rcm) as rows: the
// header, then a row per failure mode with its position's path, function and
// functional failure written out on every row (a function or functional
// failure with no failure modes gets a row of its own). Failure modes under
// no functional failure come first in their position's rows, with those cells
// blank. A failure mode with several tasks gets one row per task: the first
// carries everything, the others repeat the mode with that task and its
// interval (the import reads a repeated mode's row as another task for it,
// or, with another outcome, as the next member of a combination of tasks).
// A function with a list of standards gets a row per standard first (the
// function and the standard alone), and each failure's rows carry the
// standard it breaches, if any; a function with its one text (no list) is
// written as before, the text on every row (the import reads either back).
export function positionRcmRows(worksheet) {
  const rows = [EXPORT_HEADER];
  const path = [];
  for (const p of worksheet?.positions || []) {
    path.length = p.depth || 0;
    path.push(p.name);
    const where = path.join(" › ");
    // The working is long: written on a function's first row only, and read
    // back down its other rows (the import carries a function's cells down).
    const written = new Set();
    const firstRow = (fn) => {
      if (!fn || written.has(fn.id)) return false;
      written.add(fn.id);
      return true;
    };
    // A function's standard cell: its one text, or, with a list (of any
    // length), the standard the failure breaches (blank: the whole function),
    // so a sheet reads back with each failure under its standard, as the
    // Explorer's tree shows it.
    const listed = (fn) => (fn?.standards || []).length > 0;
    const standardCell = (fn, fail) => (listed(fn) ? fail?.standard?.text || "" : fn?.standard || "");
    // A function's notes hold the working behind its standards (Nov 2026), so the Standard
    // working column stays blank: kept so older sheets and this one line up.
    const modeRow = (fn, fail, m) => {
      const first = firstRow(fn);
      const firstFail = firstRow(fail);
      const d = m?.decision || {};
      return [
        where, fn?.text || "", (first && fn.notes) || "", standardCell(fn, fail), "", "",
        fail?.text || "", (firstFail && fail.notes) || "", causedBy(fail), m?.text || "", m?.effects || "",
        CONSEQUENCE_LABEL[m?.consequence] || "", ...fmeaCells(m), OUTCOME_LABEL[d.outcome] || "", d.rtf_basis || "", d.task || "",
        d.interval ?? "", d.interval ? d.interval_unit || "" : "",
        checkLabel(d), m?.notes || "",
      ];
    };
    const standardRows = (fn) => {
      if (!listed(fn)) return;
      const first = firstRow(fn);
      for (const [i, st] of fn.standards.entries()) {
        rows.push([where, fn.text || "", (first && i === 0 && fn.notes) || "", st.text || "", st.notes || "",
          "", "", "", "", "", "", "", ...BLANK_FMEA, "", "", "", "", "", "", ""]);
      }
    };
    const taskRow = (fn, fail, m, t) => [
      where, fn?.text || "", "", standardCell(fn, fail), "", "", fail?.text || "", "", causedBy(fail), m.text || "", "",
      "", ...BLANK_FMEA, OUTCOME_LABEL[t.outcome] || OUTCOME_LABEL[m.decision?.outcome] || "", "", t.text || t.name || "",
      t.interval ?? "", t.interval ? t.unit || "" : "", "", "",
    ];
    // A combination of tasks: a row per further member, in its order (a redesign
    // with no task too), so the import builds the same combination; then any
    // task outside the decision.
    const modeRows = (fn, fail, m) => {
      rows.push(modeRow(fn, fail, m));
      const members = m?.decision?.outcomes || [];
      for (const o of members.slice(1)) {
        rows.push(taskRow(fn, fail, m, { outcome: o.outcome, text: o.task || "", interval: o.interval, unit: o.interval_unit }));
      }
      const inMembers = new Set(members.map((o) => o.task_id).filter(Boolean));
      for (const t of (m?.decision?.tasks || []).slice(1)) if (!inMembers.has(t.id)) rows.push(taskRow(fn, fail, m, t));
    };
    for (const m of p.unassigned || []) modeRows(null, null, m);
    for (const fn of p.functions || []) {
      standardRows(fn);
      // A function's failure modes placed directly under it (the FME(C)A
      // tab): rows with the functional failure cell blank, before its
      // functional failures' rows (the import reads them back the same way).
      const direct = fn.modes || [];
      if (!(fn.failures || []).length && !listed(fn) && !direct.length) rows.push(modeRow(fn, null, null));
      for (const m of direct) modeRows(fn, null, m);
      for (const fail of fn.failures || []) {
        if (!(fail.modes || []).length) rows.push(modeRow(fn, fail, null));
        for (const m of fail.modes || []) modeRows(fn, fail, m);
      }
    }
  }
  return rows;
}

export function positionRcmCsv(worksheet) {
  return toCsv(positionRcmRows(worksheet));
}

// "Conveyor C-2 RCM.csv": the position's name, without characters a file name
// can't have; the FME(C)A tab's file is "… FMECA.csv" (or .xlsx).
export function exportFilename(name, { what = "RCM", ext = "csv" } = {}) {
  const safe = String(name || "Position").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim();
  return `${safe.slice(0, 80) || "Position"} ${what}.${ext}`;
}
