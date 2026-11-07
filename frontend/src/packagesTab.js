// The Explorer's Packages tab (Assets › Explorer, ?tab=packages): the work
// packages planned at the picked position or location and inside it (a
// package bundles tasks done on one visit, so each visit raises one work
// order). The logic here; the page is components/PackagesPanel.jsx.

const DAY = 86400000;
const toDay = (s) => Date.parse(`${String(s).slice(0, 10)}T00:00:00Z`);

// What a read is limited to for a row: a position, or a place.
export function packageScope(row) {
  if (row?.type === "pos") return { position_id: row.key };
  if (row?.type === "loc") return { location_id: row.key };
  return null;
}

// "Every Saturday", "The first Saturday of every month", "Every 4 weeks after the last visit".
export function cadenceWords(pkg) {
  const text = pkg?.cadence?.text || pkg?.cadence_text || "";
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

export function ordinal(n) {
  const k = Number(n);
  const tail = k % 100 >= 11 && k % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[k % 10] || "th");
  return `${k}${tail}`;
}

// A member's visit rule in words: "every visit", "every 4th visit".
export function visitRuleText(member) {
  if (member?.visit_rule === "nth" && member.every_nth) return `every ${ordinal(member.every_nth)} visit`;
  return "every visit";
}

// How late a top package is, in days past its tolerance (0: on time). Its open
// work order says (frozen while paused); with none raised yet, a next visit
// already past the tolerance counts too.
export function daysLate(pkg, today) {
  const wo = pkg?.open_work_order;
  if (wo) return wo.late ? Math.max(1, wo.days_late || 0) : 0;
  if (!pkg?.next_visit || !today || pkg.pause) return 0;
  const tol = pkg.tolerance?.enforced ? pkg.tolerance.amount || 0 : 0;
  const over = Math.round((toDay(today) - toDay(pkg.next_visit)) / DAY) - tol;
  return over > 0 ? over : 0;
}

export function lateText(days) {
  return days > 0 ? `Late by ${days} day${days === 1 ? "" : "s"}` : "";
}

// The packages as tops, each with its layers (and theirs) under it, depth set:
// [{pkg, depth, top}] in display order. A layer whose top isn't in the list
// (the read is limited to a branch) stands as a top.
function treeOf(rows) {
  const byId = new Map(rows.map((p) => [p.id, p]));
  const kids = new Map();
  const tops = [];
  for (const p of rows) {
    const parent = p.parent?.id;
    if (parent && byId.has(parent)) {
      if (!kids.has(parent)) kids.set(parent, []);
      kids.get(parent).push(p);
    } else tops.push(p);
  }
  return { tops, kids };
}

// Worst first: late (most days first), then the soonest next visit (or open
// work order's visit), then paused, then retired; A–Z between equals. Layers
// stay under their top, soonest first.
export function packageRows(rows = [], today = null) {
  const { tops, kids } = treeOf(rows);
  const when = (p) => p.open_work_order?.visit_on || p.next_visit || "9999";
  const rank = (p) => (p.status === "retired" ? 3 : p.status === "paused" ? 2 : daysLate(p, today) > 0 ? 0 : 1);
  const cmp = (a, b) => (rank(a) - rank(b)) || (daysLate(b, today) - daysLate(a, today))
    || when(a).localeCompare(when(b)) || a.name.localeCompare(b.name, "en", { sensitivity: "base", numeric: true });
  const out = [];
  const walk = (p, depth, top) => {
    out.push({ pkg: p, depth, top });
    for (const k of [...(kids.get(p.id) || [])].sort(cmp)) walk(k, depth + 1, top);
  };
  for (const t of [...tops].sort(cmp)) walk(t, 0, t);
  return out;
}

// The few words under a package's name: its cadence, trade and how many tasks.
export function packageSubline(pkg) {
  const n = pkg.task_count || 0;
  return [cadenceWords(pkg), pkg.trade || null, `${n} task${n === 1 ? "" : "s"}`].filter(Boolean).join(" · ");
}

// The Package the tasks… table: each draft a row, ticked, with the name it'll
// get; layers know their top.
export function proposalRows(drafts = []) {
  return drafts.map((d) => ({
    ref: d.ref, name: d.name, ticked: true, layerOf: d.layer_of || null, draft: d,
  }));
}

// Tick or untick one row: unticking a top unticks its layers (they visit on
// its visits); ticking a layer ticks its top.
export function toggleRow(rows, ref, on) {
  const row = rows.find((r) => r.ref === ref);
  if (!row) return rows;
  return rows.map((r) => {
    if (r.ref === ref) return { ...r, ticked: on };
    if (!on && r.layerOf === ref) return { ...r, ticked: false };
    if (on && row.layerOf && r.ref === row.layerOf) return { ...r, ticked: true };
    return r;
  });
}

export function renameRow(rows, ref, name) {
  return rows.map((r) => (r.ref === ref ? { ...r, name } : r));
}

// The ticked rows as the batch to make: tops (with the tolerance in days)
// before their layers.
export function proposalBatch(rows, { tolerance = null } = {}) {
  const ticked = rows.filter((r) => r.ticked);
  const tol = tolerance === "" || tolerance == null ? null : Number(tolerance);
  return ticked.map((r) => ({
    ref: r.ref, ...r.draft.create, name: r.name.trim() || r.draft.name,
    ...(!r.layerOf && tol != null && Number.isFinite(tol) && tol > 0 ? { tolerance: Math.round(tol), tolerance_unit: "days" } : {}),
  }));
}

// What's wrong with the table before making it (null: nothing).
export function proposalProblem(rows) {
  const ticked = rows.filter((r) => r.ticked);
  if (!ticked.length) return "Tick at least one package to make.";
  if (ticked.some((r) => !r.name.trim())) return "Give every ticked package a name.";
  return null;
}

// The tasks that could join a package: those in a proposal's drafts (in no
// package, on the calendar, not an item's or a round), A–Z.
export function freeTasks(proposal) {
  const seen = new Map();
  for (const d of proposal?.drafts || []) for (const t of d.tasks || []) if (!seen.has(t.id)) seen.set(t.id, t);
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name, "en", { sensitivity: "base", numeric: true }));
}

// The Summary's "Next visit": the soonest visit of a package any of the
// position's tasks is in, or null.
export function nextVisit(tasks = []) {
  let best = null;
  for (const t of tasks) {
    if (t.due_by !== "package" || !t.package || !t.next_due) continue;
    if (!best || t.next_due < best.on) best = { name: t.package.name, id: t.package.id, on: t.next_due };
  }
  return best;
}

export const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
export const dayName = (d) => d[0].toUpperCase() + d.slice(1);
