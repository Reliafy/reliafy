// The Explorer's RCM tab: the asset tree and the RCM are one table. The tree
// (assetTree.js, arranged by positions) is the first column; on this tab each
// position's rows go on into its functions › performance standards ›
// functional failures › failure modes › tasks, nested in the same tree (the same open
// rows, the same selection), and every row has the RCM's columns beside it.
// On the Summary tab the tree is the positions alone, as it always was.
//
// Pure functions (no React), tested in explorerRcm.test.js: the tree with the
// RCM grafted in, which position a row is on, what each row's menu offers
// (right-click, ⋯ or Shift+F10), and the RCM chips.

import {
  COLUMN, COLUMNS, CONSEQUENCE_LABEL, DEFAULT_COLUMNS, blank as rcmBlank, checkValue, decidedWords, decisionCardLines, decisionRows, intervalText,
  isCombination, modeCounts, moreTasks, isHidden, rowText as rcmText, tasksOf,
} from "./rcmWorksheet.js";
import { standardsShown } from "./rcmStandards.js";
import { withPositionDelete } from "./rcmDelete.js";
import { FIELDS as FMEA_FIELDS } from "./fmeaWorksheet.js";

export const RCM_TYPES = new Set(["fn", "std", "nostd", "fail", "mode", "unassigned", "cause", "nofail", "task"]);
export const isRcmRow = (r) => !!r && RCM_TYPES.has(r.type);

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });

// The tree with each position's RCM in it (from GET /api/maintenance/rcm:
// {positions: [{id, functions, unassigned}]}). Under a position: its functions
// (each with its performance standards, each with the functional failures
// that breach it, each with its failure modes), then its failure modes under
// no functional failure (an "unassigned" row), then the positions inside it.
// Adding is from each row's menu (rowActions: a position's Add function),
// not from rows in the tree. The display given is left as it is; position
// rows gain `rsum` (the counts of their failure modes and those of every position
// inside them, rollUpPositions), `ownSum` (their own alone) and `rcmKids` (how many
// of their kids are RCM rows).
//
// The standards are a level of the tree, the way classic RCM reads it: each
// functional failure is the loss of a standard. Under a function:
// - its list of standards, one row each (key: the standard's id), with the
//   functional failures that breach it nested under it;
// - a function that still has its one standard text (no list) shows that
//   text as one standard row (key `S:<function>`, `legacy: true`), and every
//   functional failure sits under it: with one standard there is nothing
//   else to breach, so no link is needed (or written) to read it that way;
// - with a list, the functional failures that breach no one standard (a
//   total loss breaches them all, or the link isn't made yet) sit under one
//   muted "No standard" row (key `N:<function>`) after the standards, so
//   every functional failure is at the same depth and every failure mode
//   too, and the rows to re-point stand together;
// - a function with no standard at all has its functional failures right
//   under it, as before.
//
// A functional failure caused by lower ones gets a reference row ("cause", key
// `L:<failure>:<cause>`) after its own failure modes for each lower failure
// linked to it: a view of a row that lives on a position below, with that
// failure's chain rolled up in its cells (the failure modes reachable through
// the links, each once). It is never counted into the failure's, function's or
// position's own counts (rsum), so nothing is counted twice.
//
// Under each failure mode, its tasks (the fifth level, modeTaskRows): one row
// per task of its decision (key `T:<mode>:<task>`), a shared task under every
// mode it serves. They add nothing to the counts (the mode's own say it has a task).
export function graftRcm(display, rcm) {
  const byPos = new Map((rcm?.positions || []).map((p) => [p.id, p]));
  const modeById = new Map();
  for (const p of rcm?.positions || []) {
    for (const m of p.unassigned || []) modeById.set(m.id, m);
    for (const fn of p.functions || []) {
      for (const m of fn.modes || []) modeById.set(m.id, m);
      for (const ff of fn.failures || []) for (const m of ff.modes || []) modeById.set(m.id, m);
    }
  }
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, rcm: true };
  for (const r of [...rows.values()]) {
    if (r.type !== "pos") continue;
    const p = byPos.get(r.key);
    const keys = [];
    const rsum = rcmBlank();
    const add = (key, type, ref, parent, depth) => {
      if (rows.has(key)) return null;
      const row = { key, type, ref, parent, kids: [], depth, own: noStatus(), sum: noStatus(), rsum: rcmBlank() };
      rows.set(key, row);
      if (parent === r.key) keys.push(key);
      else rows.get(parent).kids.push(key);
      return row;
    };
    const modeRow = (m, parent, depth, ffId) => {
      const row = add(m.id, "mode", { ...m, position_id: r.key, functional_failure_id: ffId }, parent, depth);
      if (!row) return;
      // Its tasks, one row each (never counted: the mode's own counts say it has a task).
      for (const t of modeTaskRows(m)) {
        add(taskKey(m.id, t.task.id), "task", {
          id: taskKey(m.id, t.task.id), task_id: t.task.id, mode_id: m.id, mode_text: m.text || "", position_id: r.key,
          text: t.task.name || t.task.text || "", name: t.task.name || "", instructions: t.task.instructions || "",
          outcome: t.outcome, task: t.task, member: t.member, found: t.found, on_found: t.found?.text || "",
        }, m.id, depth + 1);
      }
      row.rsum = modeCounts(m);
      for (let up = parent; up != null && up !== r.key; up = rows.get(up).parent) {
        const u = rows.get(up);
        for (const k of Object.keys(row.rsum)) u.rsum[k] += row.rsum[k];
      }
      for (const k of Object.keys(row.rsum)) rsum[k] += row.rsum[k];
    };
    const d = r.depth;
    for (const fn of p?.functions || []) {
      if (!add(fn.id, "fn", { ...fn, position_id: r.key }, r.key, d + 1)) continue;
      // Its standards, as rows: the list, or its one text as one (legacy) row.
      const shown = standardsShown(fn);
      const legacy = shown.length === 1 && shown[0].legacy;
      const listed = new Set(shown.filter((st) => !st.legacy).map((st) => st.id));
      const stdIds = shown.filter((st) => !st.legacy).map((st) => st.id);
      const stdKey = (st) => (st.legacy ? legacyKey(fn.id) : st.id);
      for (const st of shown) {
        add(stdKey(st), "std", {
          ...st, id: stdKey(st), standard_id: st.legacy ? null : st.id, position_id: r.key, function_id: fn.id,
          function_text: fn.text || "", standard_ids: stdIds,
          // Whether the function has notes and rationale (where the working behind its standards is):
          // the standard's details point at them.
          function_has_notes: !!String(fn.notes || "").trim(),
        }, fn.id, d + 2);
      }
      // Each functional failure under the standard it breaches; the ones
      // under none after the standards (one "No standard" row), or, with no
      // list, right under the function (the one text's row, or the function).
      const failRow = (ff, parent, depth) => {
        const under = rows.get(parent);
        const breach = ff.standard?.id && listed.has(ff.standard.id) ? ff.standard : null;
        if (!add(ff.id, "fail", {
          ...ff, standard: breach, position_id: r.key, function_id: fn.id, has_above: !!r.ref.parent_id,
          has_standards: listed.size > 0,
        }, parent, depth)) return;
        for (const m of ff.modes || []) modeRow(m, ff.id, depth + 1, ff.id);
        for (const c of ff.causes || []) {
          const key = causeKey(ff.id, c.id);
          const row = add(key, "cause", {
            id: key, text: c.text, cause_id: c.id, effect_id: ff.id, position_id: r.key, effect_position: r.ref.name,
            on: c.position?.name || "", cause_position_id: c.position?.id || null, inside: c.inside !== false, covered: !!c.covered,
          }, ff.id, depth + 1);
          if (row) row.rsum = chainCounts(c.chain, modeById);
        }
        if (under?.type === "std") under.ref.failures_here = (under.ref.failures_here || 0) + 1;
      };
      const loose = [];
      for (const ff of fn.failures || []) {
        if (legacy) failRow(ff, legacyKey(fn.id), d + 3);
        else if (ff.standard?.id && listed.has(ff.standard.id)) failRow(ff, ff.standard.id, d + 3);
        else loose.push(ff);
      }
      if (loose.length && listed.size) {
        const n = add(noStdKey(fn.id), "nostd", {
          id: noStdKey(fn.id), text: "No performance standard", position_id: r.key, function_id: fn.id, function_text: fn.text || "",
        }, fn.id, d + 2);
        for (const ff of loose) failRow(ff, n ? n.key : fn.id, n ? d + 3 : d + 2);
      } else {
        for (const ff of loose) failRow(ff, fn.id, d + 2);
      }
      for (const st of shown) {
        const row = rows.get(stdKey(st));
        // The quiet marker: a standard of the list with no functional failure yet.
        if (row) row.ref.no_failure = !st.legacy && !(row.ref.failures_here || 0);
      }
      // Its failure modes placed directly under it (written on the FME(C)A
      // tab): one muted "No functional failure yet" row after its failures,
      // at the standards' depth, with the modes under it; the row's menu adds
      // the functional failure or assigns them to one. The function isn't
      // analysed until they sit under a functional failure.
      if ((fn.modes || []).length) {
        const g = add(noFailKey(fn.id), "nofail", {
          id: noFailKey(fn.id), text: "No functional failure yet", position_id: r.key, function_id: fn.id, function_text: fn.text || "",
          mode_ids: fn.modes.map((m) => m.id),
        }, fn.id, d + 2);
        for (const m of fn.modes) modeRow(m, g ? g.key : fn.id, g ? d + 3 : d + 2, null);
        if (g) for (const k of g.kids) { const mr = rows.get(k); if (mr) mr.ref.function_id = fn.id; }
      }
    }
    if ((p?.unassigned || []).length) {
      const u = add(`U:${r.key}`, "unassigned", { id: `U:${r.key}`, text: "Not under a functional failure", position_id: r.key }, r.key, d + 1);
      if (u) for (const m of p.unassigned) modeRow(m, u.key, d + 2, null);
    }
    r.kids = [...keys, ...r.kids];
    r.rcmKids = keys.length;
    r.rsum = rsum;
  }
  rollUpPositions(rows);
  return out;
}

// Each position row's counts take in every position inside it (the review, Nov 2026: a
// closed Propulsion row says its motors' bearings are contradicted, a closed Airframe row
// that its landing gear has a mode to decide), as the server's rollup does; `ownSum` keeps
// its own failure modes' alone. A position's own counts go up to each position above it.
export function rollUpPositions(rows) {
  const pos = [...rows.values()].filter((r) => r.type === "pos");
  for (const r of pos) r.ownSum = { ...(r.rsum || rcmBlank()) };
  for (const r of pos) {
    const own = r.ownSum;
    if (!own.modes) continue;
    const seen = new Set([r.key]);
    for (let up = rows.get(r.parent); up && up.type === "pos" && !seen.has(up.key); up = rows.get(up.parent)) {
      seen.add(up.key);
      if (!up.rsum) up.rsum = rcmBlank();
      for (const k of Object.keys(own)) up.rsum[k] = (up.rsum[k] || 0) + own[k];
    }
  }
  return rows;
}

export const causeKey = (effectId, causeId) => `L:${effectId}:${causeId}`;
// A task's row under a failure mode it serves (a shared task has one under each).
export const taskKey = (modeId, taskId) => `T:${modeId}:${taskId}`;

// The task rows under a failure mode: one per task of its decision (a
// combination's members in order, then any other task linked to it), or the
// tasks linked before any decision. Run to failure, accept and redesign (alone)
// have none: the mode's own row says the decision. Each {task, outcome, member,
// found}: found {at, text} for a check (what's done when it finds it, and which
// part of the decision holds it), else null.
const SCHEDULED_KINDS = new Set(["on_condition", "fixed_interval", "failure_finding"]);
export function modeTaskRows(m) {
  const d = m?.decision || null;
  const tasks = tasksOf(m);
  if (d && !isCombination(d) && !SCHEDULED_KINDS.has(d.outcome)) return [];
  const lines = d ? decisionCardLines(d, tasks) : decisionRows(null, tasks).map((row) => ({ ...row, found: null }));
  const seen = new Set();
  const out = [];
  for (const l of lines) {
    if (!l.task?.id || seen.has(l.task.id)) continue;
    seen.add(l.task.id);
    // A plain decision's own task is of the decision's kind (the task may still say the kind it was made as).
    if (d && !isCombination(d) && l.task.id === d.task_id) {
      const finds = d.outcome === "on_condition" || d.outcome === "failure_finding";
      out.push({ task: l.task, outcome: d.outcome, member: null, found: finds ? { at: 0, text: d.on_found || "" } : null });
      continue;
    }
    out.push({ task: l.task, outcome: l.outcome || l.task.outcome || null, member: l.member || null, found: l.found || null });
  }
  return out;
}

// Every row of a task in the tree (one under each failure mode it serves), with its mode's row.
export function taskServes(whole, taskId) {
  const out = [];
  for (const row of whole.rows.values()) {
    if (row.type !== "task" || row.ref.task_id !== taskId) continue;
    const mode = whole.rows.get(row.ref.mode_id);
    if (mode) out.push({ key: row.key, mode });
  }
  return out;
}
// A function's one standard text, shown as a row; and its "No standard" row.
export const legacyKey = (fnId) => `S:${fnId}`;
export const noStdKey = (fnId) => `N:${fnId}`;
// A function's "No functional failure yet" row (its failure modes placed directly under it).
export const noFailKey = (fnId) => `F:${fnId}`;

// A function row's functional failures, in tree order, through its standard
// rows (and its "No standard" row).
export function failureRows(display, fnRow) {
  const out = [];
  for (const k of fnRow?.kids || []) {
    const c = display.rows.get(k);
    if (!c) continue;
    if (c.type === "fail") out.push(c);
    else if (c.type === "std" || c.type === "nostd") for (const f of c.kids) if (display.rows.get(f)?.type === "fail") out.push(display.rows.get(f));
  }
  return out;
}

// A reference row's counts: the failure modes in the chain it stands for (the
// `chain` the server read with the link), counted as a failure mode's own are;
// the server's own totals when it didn't list them.
function chainCounts(chain, modeById) {
  const out = rcmBlank();
  const ids = chain?.mode_ids;
  if (Array.isArray(ids) && ids.every((id) => modeById.has(id))) {
    for (const id of ids) {
      const c = modeCounts(modeById.get(id));
      for (const k of Object.keys(out)) out[k] += c[k];
    }
    return out;
  }
  for (const k of ["modes", "undecided", "tasks", "hidden", "safety"]) out[k] = chain?.[k] || 0;
  return out;
}

// The position a row is on (a position: itself; an RCM row: its position).
export function positionOf(r) {
  if (!r) return null;
  if (r.type === "pos") return r.key;
  return isRcmRow(r) ? r.ref.position_id : null;
}

// A row as the RCM's cells read it: a position row's counts are its failure
// modes' and those of the positions inside it (rsum), not the tree's status totals.
export const cellRow = (r) => ({ ...r, sum: r.rsum || rcmBlank() });

// What the one search box matches on an RCM row: its description, standard,
// effects, notes, and the decision's task and notes.
export const rcmRowText = (r) => rcmText(r);

// What a row's menu offers on the RCM tab (right-click, its ⋯ button, or
// Shift+F10 / the Menu key): adding inside it, and the actions the table and
// the details already have for it ([] for a row with none). `canRename`:
// the description is edited in the table (not on a phone, where the details panel edits it). `moves`: a
// standard's Move up / Move down (a wide screen drags them instead, so the page
// passes false there unless the menu was opened from the keyboard).
export function rowActions(r, { canRename = true, moves = true, viewOnly = null } = {}) {
  if (!r) return [];
  // A function, standard, functional failure or failure mode opens its
  // details across the table (a double-click on its name does the same):
  // first, so it's found without the double-click, and on a phone, where
  // there's none (there the details are a sheet).
  const open = opensItem(r) ? [{ id: "open", label: "Open…" }] : [];
  const rename = canRename ? [{ id: "rename", label: "Edit description" }] : [];
  // Delete… on any row takes everything under it (a dialog counts it first; Undo brings it back).
  if (r.type === "pos") {
    return withPositionDelete([
      { id: "add-fn", label: "Add function" },
      { id: "import-sheet", label: "Import worksheet…" },
      { id: "export-csv", label: "Export CSV" },
    ], { viewOnly });
  }
  if (r.type === "fn") {
    return [
      ...open,
      { id: "add-std", label: "Add a performance standard…" },
      { id: "add-fail", label: "Add functional failure" },
      ...rename,
      { id: "delete", label: "Delete function…", danger: true },
    ];
  }
  if (r.type === "std") {
    // The list's rows move up and down; the one text's row (legacy) is alone.
    const ids = r.ref.standard_ids || [];
    const at = ids.indexOf(r.ref.standard_id);
    const move = r.ref.legacy || !moves ? [] : [
      { id: "move-up", label: "Move up", disabled: at <= 0 },
      { id: "move-down", label: "Move down", disabled: at < 0 || at >= ids.length - 1 },
    ];
    return [
      ...open,
      ...(canRename ? [{ id: "rename", label: "Edit text" }] : []),
      { id: "add-fail", label: "Add a functional failure…" },
      ...move,
      // The old single text (legacy) is cleared; a standard of the list goes with the failures breaching it.
      { id: "delete", label: r.ref.legacy ? "Remove performance standard" : "Delete performance standard…", danger: true },
    ];
  }
  if (r.type === "fail") {
    return [
      ...open,
      { id: "add-mode", label: "Add failure mode" },
      { id: "link-cause", label: "Link to a cause…" },
      { id: "link-effect", label: "Link to an effect…" },
      ...rename,
      { id: "delete", label: "Delete functional failure…", danger: true },
    ];
  }
  if (r.type === "cause") return [{ id: "go", label: "Go to it" }, { id: "unlink", label: "Unlink", danger: true }];
  // The group rows: adding inside them (their details open on the add row).
  if (r.type === "nostd") return [{ id: "add-fail", label: "Add a functional failure…" }];
  if (r.type === "unassigned") return [{ id: "add-mode", label: "Add a failure mode…" }];
  // Failure modes directly under a function: write the functional failure
  // they belong under (on the function), or put them under one it has.
  if (r.type === "nofail") {
    return [
      { id: "add-fail", label: "Add a functional failure…" },
      { id: "assign-fail", label: "Assign to a functional failure…" },
    ];
  }
  if (r.type === "task") {
    // Its details have the rest; here what changes the tree: off this failure mode (a shared
    // task stays with the others), or retired when this is the only one it serves.
    const shared = !!r.ref.task?.shared_with;
    // Link to another failure mode…: the picker, the keyboard's way to drag it (a copy, never a move).
    return [...open, { id: "link-task", label: "Link to another failure mode…" },
      { id: "remove-task", label: shared ? "Remove from this failure mode…" : "Retire the task…", danger: true }];
  }
  if (r.type === "mode") {
    return [
      ...open,
      { id: "decide", label: r.ref.decision ? "Change the decision…" : "Decide…" },
      // Another task for the mode (or an existing one linked): the details' Tasks, on their add row.
      { id: "add-task", label: "Add a task…" },
      ...rename,
      { id: "delete", label: "Delete failure mode…", danger: true },
    ];
  }
  return [];
}

// The RCM's own chips (shown on the RCM tab, beside the tree's).
const isMode = (r) => r.type === "mode";
// `tab`: shown on that tab of the tree-table only (the FME(C)A tab has its
// own, fmeaWorksheet.js CHIPS).
export const RCM_CHIPS = [
  { id: "undecided", label: "Needs a decision", rcmOnly: true, tab: "rcm", test: (r) => isMode(r) && !r.ref.decision },
  { id: "hidden", label: "Hidden failures", rcmOnly: true, tab: "rcm", test: (r) => isMode(r) && isHidden(r.ref) },
  // A linked report or working ("linked") isn't checked, so it's never one to look at.
  { id: "check", label: "Evidence to look at", rcmOnly: true, tab: "rcm",
    title: "Linked evidence that contradicts the decision, doesn't settle it, or has gone (a stale link)",
    test: (r) => isMode(r) && ["contradicted", "inconclusive", "stale"].includes(r.ref.decision?.status) },
];

// ---- the Evidence check column -------------------------------------------------
// Most RCM is done from judgement, with no model or analysis linked to its
// decisions; a column of "nothing linked" there says nothing. So the table
// shows the Evidence check column only once some failure mode in the workspace
// has evidence linked, unless it's been ticked on or off in the Columns menu
// (remembered on this device with the other column choices: explorerCheck).

// Does any decision in the workspace's RCM (GET /api/maintenance/rcm) have
// evidence linked (a model, analysis, report or working, even one that has gone since)?
export function hasLinkedEvidence(rcm) {
  const linked = (m) => !!m.decision && (!!m.decision.evidence
    || ["supported", "contradicted", "inconclusive", "stale", "linked"].includes(m.decision.status));
  for (const p of rcm?.positions || []) {
    if ((p.unassigned || []).some(linked)) return true;
    for (const fn of p.functions || []) {
      if ((fn.modes || []).some(linked)) return true;
      for (const ff of fn.failures || []) if ((ff.modes || []).some(linked)) return true;
    }
  }
  return false;
}

// The functions' notes and rationale a failure mode's decision can link
// (evidence type "working", the decision dialog's Function notes): the
// functions with notes on the mode's position, the one it sits under first,
// as {id: the function's, label, meta: the notes' first words}.
export function workingsFor(rcm, modeId) {
  const has = (list) => (list || []).some((m) => m.id === modeId);
  const holds = (fn) => has(fn.modes) || (fn.failures || []).some((ff) => has(ff.modes));
  for (const p of rcm?.positions || []) {
    const fns = p.functions || [];
    if (!fns.some(holds) && !has(p.unassigned)) continue;
    return fns.filter((fn) => String(fn.notes || "").trim())
      .map((fn, i) => ({ fn, i, own: holds(fn) }))
      .sort((a, b) => (b.own - a.own) || (a.i - b.i))
      .map(({ fn }) => ({ id: fn.id, label: fn.text, meta: fn.basis_preview || "" }));
  }
  return [];
}

const inOrder = (ids) => COLUMNS.map((c) => c.id).filter((id) => ids.includes(id));

// A window narrower than this (a 1280 px laptop) gets fewer columns by
// default, so the table fits beside the tree: no Interval (it's folded into
// the Task cell, "Inspect roof tubes · every 12 months") and no Evidence check.
export const NARROW_TABLE = 1400;

// The usual columns for the window's width (`narrow`: under NARROW_TABLE).
export function usualCols({ narrow = false } = {}) {
  return DEFAULT_COLUMNS.filter((id) => id !== "check" && !(narrow && id === "interval"));
}

// The columns the table shows: the ones chosen in a Columns menu (the
// remembered set), else the usual ones for the window's width; with the
// Evidence check as chosen in the Columns menu, else only when evidence is
// linked somewhere (and the window isn't narrow).
export function tableCols(prefs, linked, { narrow = false } = {}) {
  const want = typeof prefs.explorerCheck === "boolean" ? prefs.explorerCheck : linked && !narrow;
  const rest = prefs.colsChosen ? (prefs.cols || DEFAULT_COLUMNS).filter((id) => id !== "check") : usualCols({ narrow });
  return inOrder(want ? [...rest, "check"] : rest);
}

// The prefs after the Columns menu changed what's shown (`next`, from `shown`).
// Ticking the Evidence check on or off is remembered as a choice; the other
// columns are the shared set, now chosen. `reset` (Show the usual columns):
// the usual set again (following the window's width), and the Evidence check
// back to following the evidence. The shared set (rcmWorksheet.js
// DEFAULT_COLUMNS) keeps its own Evidence check.
export function withTableCols(prefs, next, shown, { reset = false } = {}) {
  const had = (prefs.cols || DEFAULT_COLUMNS).includes("check");
  if (reset) {
    const out = { ...prefs, cols: DEFAULT_COLUMNS };
    delete out.explorerCheck;
    delete out.colsChosen;
    return out;
  }
  const cols = inOrder([...next.filter((id) => id !== "check"), ...(had ? ["check"] : [])]);
  const out = { ...prefs, cols, colsChosen: true };
  if (next.includes("check") !== shown.includes("check")) out.explorerCheck = next.includes("check");
  return out;
}

// The columns' widths narrowed to fit `room` (the pane's width beside the
// tree column): a table wider than its pane gives up the same share of each
// column's slack (its width over its least), never below its least (`min`),
// so it scrolls sideways only when every column is at its least. Never
// widened (the row's last cell fills what's left). {id: width}.
export function fitWidths(ids, widths, room) {
  const out = Object.fromEntries(ids.map((id) => [id, widths[id]]));
  if (!Number.isFinite(room) || room <= 0) return out;
  const total = ids.reduce((t, id) => t + out[id], 0);
  if (total <= room) return out;
  const least = (id) => Math.min(out[id], COLUMN[id]?.min ?? out[id]);
  const slack = ids.reduce((t, id) => t + out[id] - least(id), 0);
  if (slack <= 0) return out;
  const k = Math.min(1, (total - room) / slack);
  let used = 0;
  for (const id of ids) {
    out[id] = Math.max(least(id), Math.floor(out[id] - (out[id] - least(id)) * k));
    used += out[id];
  }
  // Rounding: the pixels the rounding down left over go back, one each, to
  // the columns that gave some up, so the table is exactly as wide as its room.
  for (let spare = room - used; spare > 0;) {
    const back = ids.filter((x) => out[x] < widths[x]);
    if (!back.length) break;
    for (const id of back) {
      if (spare <= 0) break;
      out[id] += 1;
      spare -= 1;
    }
  }
  return out;
}

// The Task cell with the interval folded into it (the Interval column not
// shown): "Inspect roof tubes · every 12 months"; an interval with no task,
// "Every 12 months"; more tasks, "… · +1 task". Other rows: as the Task
// column has them.
export function taskWithInterval(r) {
  if (r.type !== "mode") return COLUMN.task.text(r);
  const d = r.ref.decision;
  const own = tasksOf(r.ref)[0];
  const task = String(d?.task || own?.text || "").trim();
  const every = intervalText(d) || (own?.interval != null && own.unit ? intervalText({ interval: own.interval, interval_unit: own.unit }) : "");
  const more = moreTasks(r.ref);
  const main = !every ? task : task ? `${task} · every ${every}` : `Every ${every}`;
  return [main, more].filter(Boolean).join(" · ");
}

// A second task for a mode whose consequence is only a cost (operational or
// non-operational) should earn its place: on a cost consequence each task of a
// combination must pay for itself over time.
export function secondTaskHint(r) {
  const tasks = tasksOf(r?.ref);
  if (!tasks.length || !["operational", "non_operational"].includes(r.ref.consequence)) return null;
  const first = tasks[0].name || tasks[0].text || "the first task";
  return `What does this catch that “${first}” doesn't? Say why in the notes and rationale.`;
}

// The Task column with its interval (for the table when the Interval column
// isn't shown).
export const TASK_WITH_INTERVAL = {
  ...COLUMN.task,
  title: "What is done and how often, and for run-to-failure the action on failure",
  text: taskWithInterval,
};

// The rows to open when the RCM tab opens on a position: it, and its
// functions, standards and functional failures, so its failure modes show.
export function openFor(display, positionKey) {
  const out = new Set();
  const r = display.rows.get(positionKey);
  if (!r) return out;
  out.add(r.key);
  for (const k of r.kids) {
    const c = display.rows.get(k);
    if (c.type === "fn" || c.type === "unassigned") {
      out.add(k);
      for (const f of c.kids) {
        const x = display.rows.get(f);
        if (x.type === "fail" || x.type === "nofail") out.add(f);
        else if (x.type === "std" || x.type === "nostd") {
          out.add(f);
          for (const g of x.kids) if (display.rows.get(g).type === "fail") out.add(g);
        }
      }
    }
  }
  return out;
}

// The standard rows (and "No standard" rows) that arrived with a read and
// weren't there before, under a function that is open: to open at once, so
// the functional failures that were on show stay on show when they move
// under a new row (a one text split into a list, a first standard added, a
// failure re-pointed to a standard that had none). `seen`: the keys known
// from the read before.
export function newStandardRows(display, seen, open) {
  const out = [];
  for (const r of display.rows.values()) {
    if ((r.type === "std" || r.type === "nostd") && !seen.has(r.key) && open.has(r.parent)) out.push(r.key);
  }
  return out;
}
export const standardKeys = (display) => new Set([...display.rows.values()].filter((r) => r.type === "std" || r.type === "nostd").map((r) => r.key));

// ---- linking functional failures ----------------------------------------------------
// The picker's lists, from the grafted display (`whole`, not a pinned branch of
// it). A cause or an effect may be anywhere on the failure's tree, so every
// position of the tree is listed, the likely ones first: the failure's own
// position, then for its causes the positions inside it (in tree order, any
// depth) or for its effects those above it (nearest first), then the rest of
// the tree in tree order, branch by branch. Each group says which of those it
// is (`section`: here, inside, above or rest), with its functions (for "New
// functional failure…"), and each failure with a quiet summary and whether
// it's linked already. The failure itself is never listed (it can't cause
// itself); a loop is refused by the server, which says so.
export function linkChoices(whole, ffKey, direction) {
  const rows = whole.rows;
  const ff = rows.get(ffKey);
  if (!ff || ff.type !== "fail") return [];
  const here = ff.ref.position_id;
  if (!rows.get(here)) return [];
  const linked = new Set(((direction === "cause" ? ff.ref.causes : ff.ref.effects) || []).map((x) => x.id));
  const isPos = (k) => rows.get(k)?.type === "pos";
  const up = [];
  const seen = new Set([here]);
  for (let at = rows.get(here).ref.parent_id; at && isPos(at) && !seen.has(at); at = rows.get(at).ref.parent_id) {
    seen.add(at);
    up.push(at);
  }
  const top = up.length ? up[up.length - 1] : here;
  const order = [];
  const placed = new Set();
  const add = (key, depth, section) => {
    if (placed.has(key)) return;
    placed.add(key);
    order.push({ p: rows.get(key), depth, section });
  };
  add(here, 0, "here");
  if (direction === "cause") {
    const walk = (key, depth) => {
      for (const k of rows.get(key).kids) {
        if (!isPos(k)) continue;
        add(k, depth, "inside");
        walk(k, depth + 1);
      }
    };
    walk(here, 1);
  } else {
    for (const at of up) add(at, 0, "above");
  }
  const rest = (key, depth, trail) => {
    add(key, depth, "rest");
    for (const k of rows.get(key).kids) if (isPos(k) && !trail.has(k)) rest(k, depth + 1, new Set([...trail, k]));
  };
  rest(top, 0, new Set([top]));
  return order.map(({ p, depth, section }) => {
    const functions = [];
    const items = [];
    for (const fk of p.kids) {
      const fn = rows.get(fk);
      if (fn?.type !== "fn") continue;
      functions.push({ id: fn.key, text: fn.ref.text || "" });
      for (const x of failureRows(whole, fn)) {
        if (x.key === ffKey) continue;
        items.push({
          id: x.key, text: x.ref.text || "", function: fn.ref.text || "", linked: linked.has(x.key),
          summary: failureSummary(x),
        });
      }
    }
    return { id: p.key, name: p.ref.name || "(no name)", depth: Math.max(0, depth), section, functions, items };
  });
}

// The heading over a group of the picker where its section starts: the
// failure's own position, those inside (or above) it, then the rest of the tree.
export function linkSectionTitle(g, before, where) {
  if (before && before.section === g.section) return null;
  if (g.section === "here") return "This position";
  if (g.section === "inside") return `Inside ${where}`;
  if (g.section === "above") return `Above ${where}`;
  return "Elsewhere on the tree";
}

// "3 failure modes · all decided", "explained below", "no failure modes yet".
export function failureSummary(x) {
  const s = x.rsum || rcmBlank();
  const n = s.modes;
  const own = n ? `${n} failure mode${n === 1 ? "" : "s"} · ${decidedWords(s)}` : "";
  if (own) return own;
  return x.ref.explained_below ? "explained below" : "no failure modes yet";
}

// The groups narrowed to a typed filter (position, function or failure text):
// a position whose own name matches keeps all its failures.
export function filterChoices(groups, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return groups;
  const has = (t) => String(t || "").toLowerCase().includes(q);
  return groups.map((g) => (has(g.name) ? g : { ...g, items: g.items.filter((i) => has(i.text) || has(i.function)) }))
    .filter((g) => g.items.length > 0);
}

// Would unlinking make the higher failure not analysed? It has no failure
// modes of its own and the link is its last one that counts.
export function unlinkEmptiesFailure(whole, effectId, causeId) {
  const e = whole.rows.get(effectId);
  if (!e || e.type !== "fail") return false;
  const counted = (e.ref.causes || []).filter((c) => c.inside);
  return !(e.rsum?.modes) && counted.length === 1 && counted[0].id === causeId;
}

// ---- a row opened (double-click its name, or Open… in its menu) ------------------------
// A function, standard, functional failure or failure mode opens its details
// across the table (the tree kept beside them): all of it in one place, each
// field kept as you go.
export const ITEM_KINDS = new Set(["fn", "std", "fail", "mode", "task"]);
export const opensItem = (r) => !!r && ITEM_KINDS.has(r.type);
// A double-click on the table also opens a position's own panel (its operating
// context and functions, or its criticality matrix), expanded like the rest.
// Its menu has no "Open…" (opensItem): a position is picked, not an item.
export const opensPanel = (r) => opensItem(r) || r?.type === "pos";

// A standard's structured limit, condition and source (its text is "name").
export const STANDARD_FIELDS = ["parameter", "comparator", "value", "unit", "when", "source"];

// The writes that save the checked values, fewest first: one for the
// function, standard or functional failure; for a failure mode, its words in
// one and its consequence in another (the decision keeps everything else).
// [{api, body}], api one of "function", "standard", "function-standard" (a
// function's one text, from its legacy standard row), "failure", "mode",
// "decide".
export function itemWrites(r, values) {
  const pick = (keys, rename = {}) => {
    const body = {};
    for (const k of keys) if (k in values) body[rename[k] || k] = values[k];
    return body;
  };
  const out = [];
  if (r.type === "fn") {
    const body = pick(["name"], { name: "text" });
    if (Object.keys(body).length) out.push({ api: "function", body });
  } else if (r.type === "std" && r.ref.legacy) {
    if ("name" in values) out.push({ api: "function-standard", body: { standard: values.name } });
  } else if (r.type === "std") {
    const body = pick(["name", ...STANDARD_FIELDS], { name: "text" });
    // A value that reads as a number is sent as one (the server keeps either).
    if (typeof body.value === "string" && body.value.trim() !== "" && Number.isFinite(Number(body.value))) body.value = Number(body.value);
    if (Object.keys(body).length) out.push({ api: "standard", body });
  } else if (r.type === "fail") {
    if ("name" in values) out.push({ api: "failure", body: { text: values.name } });
  } else if (r.type === "mode") {
    // Its words, and the FME(C)A's fields (fmeaWorksheet.js FIELDS: the same
    // PATCH takes them), in one write.
    const body = pick(["name", "effects", "notes", ...FMEA_FIELDS], { name: "text" });
    if (Object.keys(body).length) out.push({ api: "mode", body });
    // The two answers in one write (evident or hidden, then the category).
    const answers = {};
    if ("hidden" in values) answers.hidden = values.hidden === "hidden" ? true : values.hidden === "evident" ? false : null;
    if ("consequence" in values) answers.consequence = values.consequence || null;
    if (Object.keys(answers).length) out.push({ api: "decide", body: answers });
  }
  return out;
}

// A functional failure's state, in words, for its details: whether its
// failure modes are decided, and what's explained by links below.
export function failureStatusWords(r) {
  const s = r.rsum || r.sum || rcmBlank();
  const causes = r.ref.causes || [];
  if (s.modes) {
    const own = s.undecided
      ? `${s.undecided.toLocaleString("en-AU")} of its ${s.modes.toLocaleString("en-AU")} failure mode${s.modes === 1 ? "" : "s"} still need${s.undecided === 1 ? "s" : ""} a decision.`
      : `Analysed: ${s.modes === 1 ? "its failure mode has" : `all ${s.modes.toLocaleString("en-AU")} of its failure modes have`} a decision.`;
    return causes.length ? `${own} It is also caused by ${causes.length === 1 ? "a failure" : "failures"} below.` : own;
  }
  if (causes.length) {
    return r.ref.explained_below
      ? "Covered: it is explained by the failures linked below, and their failure modes are decided there."
      : "Not finished: it is linked to failures below, but some of their failure modes still need a decision.";
  }
  return "Not analysed yet: it has no failure modes and nothing linked below.";
}

// A position's functions for its panel on the RCM tab: one entry per function
// row below it, in table order, with what the table's row would say (its
// performance standards, functional failures and failure modes, how many of
// those are decided).
export function functionSummary(display, posRow) {
  const out = [];
  for (const k of posRow?.kids || []) {
    const r = display?.rows?.get(k);
    if (r?.type !== "fn") continue;
    const stds = standardsShown(r.ref);
    const s = r.rsum || rcmBlank();
    out.push({
      key: r.key,
      text: String(r.ref.text || "").trim() || "(no text yet)",
      standards: stds.length,
      standardTexts: stds.map((st) => String(st.text || "").trim()).filter(Boolean),
      failures: (r.ref.failures || []).length,
      modes: s.modes,
      decided: Math.max(0, s.modes - s.undecided),
    });
  }
  return out;
}

// A failure mode's failure reports in its panel (ModeFailureReports.jsx): the words and
// where Open goes, or null with none. `found` {total, first}: the first report, newest.
export function modeReportsLink(found, positionId) {
  const n = found?.total || 0;
  if (!n) return null;
  const one = n === 1 && found.first?.id;
  const where = found.first?.position?.id || positionId;
  return {
    words: `${n.toLocaleString("en-AU")} failure report${n === 1 ? "" : "s"}`,
    query: one ? { sel: where, tab: "reports", report: found.first.id } : { sel: positionId, tab: "reports" },
    title: one ? "Open the failure report" : "Open the failure reports at this position",
  };
}
