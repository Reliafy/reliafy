// The Explorer's FME(C)A tab: the asset tree and the FMEA worksheet are one
// table, as the RCM tab's are (explorerRcm.js). The tree, arranged by
// positions, is the first column; under each position its functions, and
// under each function its failure modes, one row each, the way a worksheet
// reads: the modes written directly under the function first, then those
// under any of its functional failures (each carrying the failure's text for
// the read-only Functional failure column); then the position's failure
// modes under no function ("Not under a functional failure"). The same
// records, the same keys (a mode's id) as the RCM tab, so ?sel= and the row
// picked carry across the tabs.
//
// Pure functions (no React), tested in explorerFmea.test.js.

import { modeSums, blankSums, addSums } from "./fmeaWorksheet.js";
import { byCriticality, crOf, matrixOf } from "./fmea.js";
import { withPositionDelete } from "./rcmDelete.js";

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });

// The tree with each position's FMEA in it (from GET /api/maintenance/rcm,
// the same read as the RCM tab). The display given is left as it is;
// position rows gain `rsum` (their own failure modes' counts, RCM and FMEA)
// and `rcmKids` (how many of their kids are worksheet rows).
export function graftFmea(display, rcm) {
  const byPos = new Map((rcm?.positions || []).map((p) => [p.id, p]));
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, rcm: true, fmea: true };
  for (const r of [...rows.values()]) {
    if (r.type !== "pos") continue;
    const p = byPos.get(r.key);
    const keys = [];
    const rsum = blankSums();
    const add = (key, type, ref, parent, depth) => {
      if (rows.has(key)) return null;
      const row = { key, type, ref, parent, kids: [], depth, own: noStatus(), sum: noStatus(), rsum: blankSums() };
      rows.set(key, row);
      if (parent === r.key) keys.push(key);
      else rows.get(parent).kids.push(key);
      return row;
    };
    const modeRow = (m, parent, depth, { fn = null, ff = null } = {}) => {
      const row = add(m.id, "mode", {
        ...m, position_id: r.key, function_id: fn?.id ?? m.function_id ?? null, functional_failure_id: ff?.id ?? null,
        failure_text: ff?.text || "", failure_id: ff?.id || null, direct: !!fn && !ff,
      }, parent, depth);
      if (!row) return;
      row.rsum = modeSums(m);
      for (let up = parent; up != null && up !== r.key; up = rows.get(up).parent) addSums(rows.get(up).rsum, row.rsum);
      addSums(rsum, row.rsum);
    };
    const d = r.depth;
    for (const fn of p?.functions || []) {
      if (!add(fn.id, "fn", { ...fn, position_id: r.key }, r.key, d + 1)) continue;
      for (const m of fn.modes || []) modeRow(m, fn.id, d + 2, { fn });
      for (const ff of fn.failures || []) for (const m of ff.modes || []) modeRow(m, fn.id, d + 2, { fn, ff });
    }
    if ((p?.unassigned || []).length) {
      const u = add(`U:${r.key}`, "unassigned", { id: `U:${r.key}`, text: "Not under a functional failure", position_id: r.key }, r.key, d + 1);
      if (u) for (const m of p.unassigned) modeRow(m, u.key, d + 2);
    }
    r.kids = [...keys, ...r.kids];
    r.rcmKids = keys.length;
    r.rsum = rsum;
    r.fmea = p?.fmea || null;
  }
  return out;
}

// What a row's menu offers on the FME(C)A tab (right-click, its ⋯ button, or
// Shift+F10): adding inside it, and the row's other actions. A function adds
// a failure mode directly under itself (no functional failure yet: the RCM
// tab shows it as such). `canRename`: the description is edited in the table
// (not on a phone, where the details panel edits it).
export function rowActions(r, { canRename = true, viewOnly = null } = {}) {
  if (!r) return [];
  const open = r.type === "fn" || r.type === "mode" ? [{ id: "open", label: "Open…" }] : [];
  const rename = canRename ? [{ id: "rename", label: "Edit description" }] : [];
  // Delete… on any row takes everything under it (a dialog counts it first; Undo brings it back).
  if (r.type === "pos") {
    return withPositionDelete([
      { id: "add-fn", label: "Add function" },
      { id: "import-sheet", label: "Import worksheet…" },
      { id: "export-csv", label: "Export CSV" },
      { id: "print", label: "Print view" },
    ], { viewOnly });
  }
  if (r.type === "fn") {
    return [
      ...open,
      { id: "add-mode", label: "Add failure mode" },
      ...rename,
      { id: "delete", label: "Delete function…", danger: true },
    ];
  }
  if (r.type === "unassigned") return [{ id: "add-mode", label: "Add a failure mode…" }];
  if (r.type === "mode") {
    return [
      ...open,
      { id: "score", label: "Score…" },
      ...rename,
      { id: "delete", label: "Delete failure mode…", danger: true },
    ];
  }
  return [];
}

// The failure modes a position's details count: its own and those of the
// positions inside it (the modes under its rows, any depth), each as the
// server read it.
export function modesUnder(display, positionKey) {
  const out = [];
  const walk = (key) => {
    const r = display.rows.get(key);
    if (!r) return;
    if (r.type === "mode") out.push(r.ref);
    for (const k of r.kids) walk(k);
  };
  walk(positionKey);
  return out;
}

// A position's FMEA summary for its details: the matrix over it and what's
// inside it, the counts, and its own Cr (the server's `fmea` on the position:
// its live modes alone) beside the Cr with everything inside.
export function positionSummary(display, positionKey, opts) {
  const r = display.rows.get(positionKey);
  if (!r) return null;
  const all = modesUnder(display, positionKey);
  const own = r.fmea || null;
  const s = r.rsum || blankSums();
  const inside = (r.kids || []).some((k) => display.rows.get(k)?.type === "pos");
  return {
    matrix: matrixOf(all, opts),
    ranked: byCriticality(all),
    counts: { modes: all.length, scored: all.filter((m) => m.rpn != null || (m.severity && m.occurrence && m.detection)).length,
      high: all.filter((m) => m.ap === "H").length, medium: all.filter((m) => m.ap === "M").length, low: all.filter((m) => m.ap === "L").length },
    own: { modes: s.modes, scored: s.scored, high: s.high, medium: s.medium, low: s.low, cr: own?.cr ?? (s.with_cm ? s.cr : null), crByClass: own?.cr_by_class || null },
    cr: crOf(all),
    inside,
  };
}

// The functions and functional failures on a position, from the RCM read (not
// the display, which on this tab has no functional failure rows), for a
// failure mode's "Under" choice: [{id, text}] and [{id, text, function}].
export function functionsOn(rcm, positionId) {
  const p = (rcm?.positions || []).find((x) => x.id === positionId);
  return (p?.functions || []).map((fn) => ({ id: fn.id, text: fn.text || "" }));
}
export function failuresOn(rcm, positionId) {
  const p = (rcm?.positions || []).find((x) => x.id === positionId);
  const out = [];
  for (const fn of p?.functions || []) for (const ff of fn.failures || []) out.push({ id: ff.id, text: ff.text || "", function: fn.text || "", function_id: fn.id });
  return out;
}
