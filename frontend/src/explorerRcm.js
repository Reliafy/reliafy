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

import {
  COLUMN, COLUMNS, DEFAULT_COLUMNS, blank as rcmBlank, intervalText, modeCounts, rowText as rcmText,
} from "./rcmWorksheet.js";

export const RCM_TYPES = new Set(["fn", "fail", "mode", "unassigned", "cause"]);
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
//
// A functional failure caused by lower ones gets a reference row ("cause", key
// `L:<failure>:<cause>`) after its own failure modes for each lower failure
// linked to it: a view of a row that lives on a position below, with that
// failure's chain rolled up in its cells (the failure modes reachable through
// the links, each once). It is never counted into the failure's, function's or
// position's own counts (rsum), so nothing is counted twice.
export function graftRcm(display, rcm) {
  const byPos = new Map((rcm?.positions || []).map((p) => [p.id, p]));
  const modeById = new Map();
  for (const p of rcm?.positions || []) {
    for (const m of p.unassigned || []) modeById.set(m.id, m);
    for (const fn of p.functions || []) for (const ff of fn.failures || []) for (const m of ff.modes || []) modeById.set(m.id, m);
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
        if (!add(ff.id, "fail", { ...ff, position_id: r.key, function_id: fn.id, has_above: !!r.ref.parent_id }, fn.id, d + 2)) continue;
        for (const m of ff.modes || []) modeRow(m, ff.id, d + 3, ff.id);
        for (const c of ff.causes || []) {
          const key = causeKey(ff.id, c.id);
          const row = add(key, "cause", {
            id: key, text: c.text, cause_id: c.id, effect_id: ff.id, position_id: r.key, effect_position: r.ref.name,
            on: c.position?.name || "", cause_position_id: c.position?.id || null, inside: c.inside !== false, covered: !!c.covered,
          }, ff.id, d + 3);
          if (row) row.rsum = chainCounts(c.chain, modeById);
        }
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

export const causeKey = (effectId, causeId) => `L:${effectId}:${causeId}`;

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
  if (r.type === "pos") {
    return [
      { id: "add-fn", label: "Add function" },
      { id: "import-sheet", label: "Import worksheet…" },
      { id: "export-csv", label: "Export CSV" },
    ];
  }
  if (r.type === "fn") {
    return [{ id: "add-fail", label: "Add functional failure" }, ...rename, { id: "delete", label: "Delete function", danger: true }];
  }
  if (r.type === "fail") {
    return [
      { id: "add-mode", label: "Add failure mode" },
      { id: "link-cause", label: "Link to a cause…" },
      ...(r.ref.has_above ? [{ id: "link-effect", label: "Link to an effect…" }] : []),
      ...rename,
      { id: "delete", label: "Delete functional failure", danger: true },
    ];
  }
  if (r.type === "cause") return [{ id: "go", label: "Go to it" }, { id: "unlink", label: "Unlink", danger: true }];
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
  { id: "check", label: "Evidence to look at", rcmOnly: true,
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
// evidence linked (a model or analysis, even one that has gone since)?
export function hasLinkedEvidence(rcm) {
  const linked = (m) => !!m.decision && (!!m.decision.evidence
    || ["supported", "contradicted", "inconclusive", "stale"].includes(m.decision.status));
  for (const p of rcm?.positions || []) {
    if ((p.unassigned || []).some(linked)) return true;
    for (const fn of p.functions || []) for (const ff of fn.failures || []) if ((ff.modes || []).some(linked)) return true;
  }
  return false;
}

// Where the (i) for a function's working sits: at the end of its Performance
// standard cell, or, while that column is hidden (it is by default), at the
// end of the function's name, so a working is never out of sight and no column
// has to appear or change width.
export const basisInName = (colIds) => !colIds.includes("standard");

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
// back to following the evidence. The shared set keeps its own Evidence check
// (the RCM study's worksheet uses it).
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
// "Every 12 months". Other rows: as the Task column has them.
export function taskWithInterval(r) {
  if (r.type !== "mode") return COLUMN.task.text(r);
  const d = r.ref.decision;
  const task = String(d?.task || "").trim();
  const every = intervalText(d);
  if (!every) return task;
  return task ? `${task} · every ${every}` : `Every ${every}`;
}

// The Task column with its interval (for the table when the Interval column
// isn't shown).
export const TASK_WITH_INTERVAL = {
  ...COLUMN.task,
  title: "What is done and how often, and for run-to-failure the action on failure",
  text: taskWithInterval,
};

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

// ---- linking functional failures ----------------------------------------------------
// The picker's lists, from the grafted display (`whole`, not a pinned branch of
// it): for a functional failure's causes, the functional failures on the
// positions inside its own (in tree order, any depth); for its effects, those
// on the positions above it (nearest first). Grouped by position, each with
// its functions (for "New functional failure on a position…"), and each
// failure with a quiet summary and whether it's linked already.
export function linkChoices(whole, ffKey, direction) {
  const rows = whole.rows;
  const ff = rows.get(ffKey);
  if (!ff || ff.type !== "fail") return [];
  const here = ff.ref.position_id;
  const linked = new Set(((direction === "cause" ? ff.ref.causes : ff.ref.effects) || []).map((x) => x.id));
  const order = [];
  if (direction === "cause") {
    const walk = (key, depth) => {
      const p = rows.get(key);
      if (!p || p.type !== "pos") return;
      if (key !== here) order.push({ p, depth });
      for (const k of p.kids) if (rows.get(k)?.type === "pos") walk(k, depth + 1);
    };
    walk(here, -1);
  } else {
    const seen = new Set();
    for (let at = rows.get(here)?.ref.parent_id; at && rows.has(at) && !seen.has(at); at = rows.get(at).ref.parent_id) {
      seen.add(at);
      order.push({ p: rows.get(at), depth: 0 });
    }
  }
  return order.map(({ p, depth }) => {
    const functions = [];
    const items = [];
    for (const fk of p.kids) {
      const fn = rows.get(fk);
      if (fn?.type !== "fn") continue;
      functions.push({ id: fn.key, text: fn.ref.text || "" });
      for (const xk of fn.kids) {
        const x = rows.get(xk);
        if (x?.type !== "fail") continue;
        items.push({
          id: x.key, text: x.ref.text || "", function: fn.ref.text || "", linked: linked.has(x.key),
          summary: failureSummary(x),
        });
      }
    }
    return { id: p.key, name: p.ref.name || "(no name)", depth: Math.max(0, depth), functions, items };
  });
}

// "3 failure modes · all decided", "explained below", "no failure modes yet".
export function failureSummary(x) {
  const s = x.rsum || rcmBlank();
  const n = s.modes;
  const own = n ? `${n} failure mode${n === 1 ? "" : "s"} · ${s.undecided ? `${s.undecided} to decide` : "all decided"}` : "";
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
