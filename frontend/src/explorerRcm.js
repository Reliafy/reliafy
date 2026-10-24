// The Explorer's RCM tab: the asset tree and the RCM are one table. The tree
// (assetTree.js, arranged by positions) is the first column; on this tab each
// position's rows go on into its functions › functional failures › failure
// modes, nested in the same tree (the same open rows, the same selection), and
// every row has the RCM's columns beside it. On the Summary tab the tree is the
// positions alone, as it always was.
//
// Pure functions (no React), tested in explorerRcm.test.js: the tree with the
// RCM grafted in, which position a row is on, what each row's menu offers
// (right-click, ⋯ or Shift+F10), and the RCM chips.

import { blank as rcmBlank, modeCounts, rowText as rcmText } from "./rcmWorksheet.js";

export const RCM_TYPES = new Set(["fn", "fail", "mode", "unassigned"]);
export const isRcmRow = (r) => !!r && RCM_TYPES.has(r.type);

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });

// The tree with each position's RCM in it (from GET /api/maintenance/rcm:
// {positions: [{id, functions, unassigned}]}). Under a position: its functions
// (each with its functional failures, each with its failure modes), then its
// failure modes under no functional failure (an "unassigned" row), then the
// positions inside it. Adding is from each row's menu (rowActions) and the
// heading's Add function, not from rows in the tree. The display given is left
// as it is; position rows gain `rsum` (their own failure modes' counts) and
// `rcmKids` (how many of their kids are RCM rows).
export function graftRcm(display, rcm) {
  const byPos = new Map((rcm?.positions || []).map((p) => [p.id, p]));
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
      for (const ff of fn.failures || []) {
        if (!add(ff.id, "fail", { ...ff, position_id: r.key, function_id: fn.id }, fn.id, d + 2)) continue;
        for (const m of ff.modes || []) modeRow(m, ff.id, d + 3, ff.id);
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
  return out;
}

// The position a row is on (a position: itself; an RCM row: its position).
export function positionOf(r) {
  if (!r) return null;
  if (r.type === "pos") return r.key;
  return isRcmRow(r) ? r.ref.position_id : null;
}

// A row as the RCM's cells read it: a position row's counts are its own
// failure modes' (rsum), not the tree's status totals.
export const cellRow = (r) => ({ ...r, sum: r.rsum || rcmBlank() });

// What the one search box matches on an RCM row: its description, standard,
// effects, notes, and the decision's task and notes.
export const rcmRowText = (r) => rcmText(r);

// What a row's menu offers on the RCM tab (right-click, its ⋯ button, or
// Shift+F10 / the Menu key): adding inside it, and the actions the table and
// the details already have for it. [] for a row with none (the "Not under a
// functional failure" heading). `canRename`: the description is edited in
// the table (not on a phone, where the details panel edits it).
export function rowActions(r, { canRename = true } = {}) {
  if (!r) return [];
  const rename = canRename ? [{ id: "rename", label: "Edit description" }] : [];
  if (r.type === "pos") return [{ id: "add-fn", label: "Add function" }];
  if (r.type === "fn") {
    return [{ id: "add-fail", label: "Add functional failure" }, ...rename, { id: "delete", label: "Delete function", danger: true }];
  }
  if (r.type === "fail") {
    return [{ id: "add-mode", label: "Add failure mode" }, ...rename, { id: "delete", label: "Delete functional failure", danger: true }];
  }
  if (r.type === "mode") {
    return [
      { id: "decide", label: r.ref.decision ? "Change the decision…" : "Decide…" },
      ...rename,
      { id: "delete", label: "Delete failure mode", danger: true },
    ];
  }
  return [];
}

// The RCM's own chips (shown on the RCM tab, beside the tree's).
const isMode = (r) => r.type === "mode";
export const RCM_CHIPS = [
  { id: "undecided", label: "Needs a decision", rcmOnly: true, test: (r) => isMode(r) && !r.ref.decision },
  { id: "hidden", label: "Hidden failures", rcmOnly: true, test: (r) => isMode(r) && r.ref.consequence === "hidden" },
  { id: "check", label: "Evidence to look at", rcmOnly: true, title: "Contradicted, inconclusive, not linked yet, or a stale link",
    test: (r) => isMode(r) && ["contradicted", "inconclusive", "unevidenced", "stale"].includes(r.ref.decision?.status) },
];

// The rows to open when the RCM tab opens on a position: it, and its
// functions and functional failures, so its failure modes show.
export function openFor(display, positionKey) {
  const out = new Set();
  const r = display.rows.get(positionKey);
  if (!r) return out;
  out.add(r.key);
  for (const k of r.kids) {
    const c = display.rows.get(k);
    if (c.type === "fn" || c.type === "unassigned") {
      out.add(k);
      for (const f of c.kids) if (display.rows.get(f).type === "fail") out.add(f);
    }
  }
  return out;
}
