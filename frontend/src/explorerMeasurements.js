// The Explorer's Measurements tab as a tree-table (Derryn, 9 Nov 2026: "line up
// with the tree, just like in the RCM table"). The tree, arranged by positions,
// is the first column; under each position hang its measurement rows (condition
// points, counters, settings, sensor channels and consumables, worst first),
// before the positions inside it, and every row has the table's columns beside
// it (Kind, Latest, State, Trend, Next due, Record, ⋯). A position row rolls up
// its own rows ("4 points · 1 needs attention"), and a closed one what's inside
// it too. Pure functions, tested in explorerMeasurements.test.js; the rows'
// cells are measurementsTable.js's (tableRows), drawn by MeasurementCells.jsx.
//
// What can be added under a position on this tab (measAddActions): one list,
// used by both the heading's "…" and a position row's menu (right-click, ⋯,
// Shift+F10), where it comes first, before the tree's own items (New position
// inside, Rename…, …) after a line.

import { sortRows, tableRows } from "./measurementsTable.js";

export const MEAS_TYPE = "meas";
export const isMeasRow = (r) => r?.type === MEAS_TYPE;

// A measurement row's key in the tree (a point's id could be any row's key).
export const measKey = (rowKey) => `M:${rowKey}`;

// Adding under a position: a measuring point, a setting, a consumable, a sensor
// channel ([] for any other row). `viewOnly`: the reason the workspace can't be
// changed (each greyed with it), else null.
export const MEAS_ADDS = [
  { id: "meas-add-point", label: "Add a measuring point…" },
  { id: "meas-add-setting", label: "Add a setting…" },
  { id: "meas-add-consumable", label: "Add a consumable…" },
  { id: "meas-add-channel", label: "Add a sensor channel…" },
];
export function measAddActions(r, { viewOnly = null } = {}) {
  if (r?.type !== "pos") return [];
  return MEAS_ADDS.map((a) => (viewOnly ? { ...a, disabled: true, reason: viewOnly } : { ...a }));
}

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });
const blank = () => ({ n: 0, attention: 0 });

// The ids to ask GET /api/maintenance/points for: every position in the tree,
// and the items fitted to them (their own points and channels hang under the
// position they're fitted to: fittedAt, item id → position key).
export function measurementAsk(display) {
  const positionIds = [];
  const itemIds = [];
  const fittedAt = new Map();
  for (const r of display?.rows?.values() || []) {
    if (r.type !== "pos") continue;
    positionIds.push(r.key);
    const it = r.ref?.item;
    if (it?.id) {
      itemIds.push(it.id);
      fittedAt.set(it.id, r.key);
    }
  }
  return { positionIds, itemIds, fittedAt };
}

// Which position a table row hangs under (null: none in this tree).
function positionKeyOf(row, fittedAt) {
  const x = row.item;
  if (row.type === "consumable") return x.position?.id || null;
  if (x.position?.id) return x.position.id;
  if (x.item?.fitted_to?.id) return x.item.fitted_to.id;
  if (x.item?.id) return fittedAt.get(x.item.id) || null;
  return null;
}

// The tree with each position's measurement rows in it. `data`: the points read
// ({points, channels, consumables}); `fittedAt` as measurementAsk gives it. The
// display given is left as it is; position rows gain `msum` (their own rows'
// counts), `mall` (theirs and every position's inside them) and `measKids`.
export function graftMeasurements(display, data, today, fittedAt = new Map()) {
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, meas: true };
  const names = new Map();
  for (const [itemId, pk] of fittedAt) names.set(itemId, rows.get(pk)?.ref?.name || "");
  const all = tableRows(data?.points || [], data?.channels || [], today, names, data?.consumables || []);
  const byPos = new Map();
  for (const row of all) {
    const pk = positionKeyOf(row, fittedAt);
    if (!pk || rows.get(pk)?.type !== "pos") continue;
    if (!byPos.has(pk)) byPos.set(pk, []);
    byPos.get(pk).push(row);
  }
  for (const r of rows.values()) {
    if (r.type === "pos") Object.assign(r, { msum: blank(), mall: blank(), measKids: 0 });
  }
  for (const [pk, list] of byPos) {
    const p = rows.get(pk);
    const keys = [];
    for (const row of sortRows(list)) {
      const key = measKey(row.key);
      if (rows.has(key)) continue;
      rows.set(key, {
        key, type: MEAS_TYPE, parent: pk, kids: [], depth: p.depth + 1, own: noStatus(), sum: noStatus(),
        ref: {
          name: row.name, tag: row.tag, row, position_id: pk, mkind: row.type === "point" ? row.kind.toLowerCase() : row.type,
          search: [row.name, row.tag, row.kind, row.state.label, row.unit].filter(Boolean).join(" ").toLowerCase(),
        },
      });
      keys.push(key);
      p.msum.n += 1;
      if (row.attention) p.msum.attention += 1;
    }
    p.kids = [...keys, ...p.kids];
    p.measKids = keys.length;
  }
  // Each position's total: its own and everything inside it.
  const total = (k) => {
    const r = rows.get(k);
    if (r.mallDone) return r.mall;
    const t = { ...r.msum };
    for (const c of r.kids) {
      if (rows.get(c)?.type === "pos") {
        const s = total(c);
        t.n += s.n;
        t.attention += s.attention;
      }
    }
    r.mall = t;
    r.mallDone = true;
    return t;
  };
  for (const r of rows.values()) if (r.type === "pos") total(r.key);
  for (const r of rows.values()) delete r.mallDone;
  return out;
}

// A position row's roll-up: its own rows when open, everything inside it when
// closed ("22 points · 14 need attention"); "" with none.
export function rollupText(r, open = false) {
  const s = open ? r.msum : r.mall;
  if (!s?.n) return "";
  const pts = `${s.n.toLocaleString("en-AU")} point${s.n === 1 ? "" : "s"}`;
  return s.attention ? `${pts} · ${s.attention.toLocaleString("en-AU")} need${s.attention === 1 ? "s" : ""} attention` : pts;
}

// The tab's chip: rows that need a look (past or near a limit, a reading due,
// a channel past a band's alarm). The filter opens the way down to them.
export const MEAS_CHIPS = [
  { id: "attention", label: "Needs attention", rcmOnly: true, tab: "measurements",
    title: "Past or near an alarm limit, or a reading due", test: (r) => isMeasRow(r) && !!r.ref.row.attention },
];

// The positions to open when the tab opens: the one picked (so its rows show).
export function openForMeasurements(display, positionKey) {
  const out = [];
  for (let k = positionKey; k != null; k = display.rows.get(k)?.parent) out.push(k);
  return out;
}
