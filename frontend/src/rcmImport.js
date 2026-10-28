// A position's RCM in and out as a spreadsheet: the words for an import's
// preview (what an FMEA / RCM worksheet adds to the position, and what's
// there already), and the CSV a position's RCM downloads as. The CSV's
// columns are named as the import reads them, so the file can be edited and
// imported again; importing it onto the same position adds nothing.

import { toCsv } from "./csv.js";
import { CONSEQUENCE_LABEL, OUTCOME_LABEL, STATUS_LABEL } from "./rcmWorksheet.js";

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

export const EXPORT_HEADER = [
  "Position", "Function", "Performance standard", "Standard working", "Functional failure", "Caused by (below)", "Failure mode", "Effects", "Consequence",
  "Decision", "Run-to-failure basis", "Task", "Interval", "Interval unit", "Evidence check", "Notes",
];

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
// interval (the import reads a repeated mode's row as another task for it).
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
    const modeRow = (fn, fail, m) => {
      const first = firstRow(fn);
      const d = m?.decision || {};
      return [
        where, fn?.text || "", fn?.standard || "", (first && fn.standard_basis) || "", fail?.text || "", causedBy(fail), m?.text || "", m?.effects || "",
        CONSEQUENCE_LABEL[m?.consequence] || "", OUTCOME_LABEL[d.outcome] || "", d.rtf_basis || "", d.task || "",
        d.interval ?? "", d.interval ? d.interval_unit || "" : "",
        d.status && d.status !== "unevidenced" ? STATUS_LABEL[d.status] || d.status : "", m?.notes || "",
      ];
    };
    const taskRow = (fn, fail, m, t) => [
      where, fn?.text || "", fn?.standard || "", "", fail?.text || "", causedBy(fail), m.text || "", "",
      "", OUTCOME_LABEL[t.outcome] || OUTCOME_LABEL[m.decision?.outcome] || "", "", t.text || t.name || "",
      t.interval ?? "", t.interval ? t.unit || "" : "", "", "",
    ];
    const modeRows = (fn, fail, m) => {
      rows.push(modeRow(fn, fail, m));
      for (const t of (m?.decision?.tasks || []).slice(1)) rows.push(taskRow(fn, fail, m, t));
    };
    for (const m of p.unassigned || []) modeRows(null, null, m);
    for (const fn of p.functions || []) {
      if (!(fn.failures || []).length) rows.push(modeRow(fn, null, null));
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

// "Conveyor C-2 RCM.csv": the position's name, without characters a file name can't have.
export function exportFilename(name) {
  const safe = String(name || "Position").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim();
  return `${safe.slice(0, 80) || "Position"} RCM.csv`;
}
