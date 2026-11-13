// Failure reports (the Explorer's Failure reports tab): the closed loop from a
// report of a failure, through investigation and root cause, to corrective
// action, a check that it worked, and closure. The words, the status flow,
// the counts sentence, a row's level under the row picked, and the list's
// filters as the query the server takes.
//
// Pure functions (no React), tested in failureReports.test.js. The server's
// rules (service: what a status may move to) are repeated here only to say
// what the screen offers; the server checks again and its reason is shown.

import { formatDateTime } from "./dates.js";

// The loop in flow order, then the one outside it.
export const STATUSES = ["reported", "investigating", "corrective_action", "verifying", "closed"];
export const OPEN_STATUSES = STATUSES.slice(0, 4);
export const STATUS_LABELS = {
  reported: "Reported",
  investigating: "Investigating",
  corrective_action: "Corrective action",
  verifying: "Verifying",
  closed: "Closed",
  rejected: "Rejected",
};
export const statusLabel = (s) => STATUS_LABELS[s] || s || "";
export const isOpen = (s) => OPEN_STATUSES.includes(s);

// The next stage of the loop (null at the end, or outside it).
export function nextStatus(status) {
  const i = STATUSES.indexOf(status);
  if (i < 0 || i >= STATUSES.length - 1) return null;
  return STATUSES[i + 1];
}

// Whether the screen offers a move from one status to another: among the
// four open ones any direction; closing needs a verification (the Close
// card, not the stepper); rejecting from any open one; from closed or
// rejected only back into the loop (a reopen).
export function canMoveTo(from, to, { verified = false } = {}) {
  if (from === to || !STATUS_LABELS[to]) return false;
  if (isOpen(from)) {
    if (isOpen(to) || to === "rejected") return true;
    return to === "closed" && verified;
  }
  return isOpen(to);
}

// The status chips over the list: Open first (the usual), then each stage, then All.
export const STATUS_CHIPS = [
  { id: "open", label: "Open" },
  ...STATUSES.map((s) => ({ id: s, label: STATUS_LABELS[s] })),
  { id: "rejected", label: "Rejected" },
  { id: "all", label: "All" },
];

// The consequence of the failure, in the RCM's words (so a report compares
// with its failure mode's decision).
export const CONSEQUENCES = [
  { id: "safety", label: "Safety" },
  { id: "environmental", label: "Environmental" },
  { id: "operational", label: "Operational (output or quality)" },
  { id: "non_operational", label: "Non-operational (cost of repair only)" },
  { id: "hidden", label: "Hidden (no one noticed)" },
  { id: "", label: "Not sure" },
];
export const consequenceLabel = (c) => (CONSEQUENCES.find((x) => x.id === (c || "")) || CONSEQUENCES.at(-1)).label;
// Short, for a pill: the first word or two.
export const consequenceShort = (c) => consequenceLabel(c).replace(/\s*\(.*\)$/, "");

export const ROOT_CAUSES = [
  { id: "design", label: "Design" },
  { id: "material", label: "Material or manufacture" },
  { id: "installation", label: "Installation" },
  { id: "operation", label: "Operation" },
  { id: "maintenance", label: "Maintenance" },
  { id: "wear", label: "Wear" },
  { id: "environment", label: "Environment" },
  { id: "unknown", label: "Unknown" },
  { id: "other", label: "Other" },
];
export const rootCauseLabel = (c) => ROOT_CAUSES.find((x) => x.id === c)?.label || "";

export const RESULTS = [
  { id: "worked", label: "It worked: the failure hasn't come back" },
  { id: "not_worked", label: "It didn't work: the failure came back" },
  { id: "unclear", label: "Too early to say" },
];
export const resultLabel = (r) => ({ worked: "Worked", not_worked: "Didn't work", unclear: "Unclear" })[r] || "";

export const ACTION_STATUSES = { open: "Open", done: "Done", dropped: "Dropped" };
export const MAX_WHYS = 7;

// The stage the loop is at, for which card to fold open: the status, or
// "closed" / "rejected" (nothing to fold open; the sign-off shows instead).
export const stageOf = (report) => report?.status || "reported";

// "3 open · 7 in all, at this position and 12 inside it". `scope` is the
// server's ({kind, positions: n}; a design's: {kind: "design", items: n}); `counts` its totals ({open, ...} over the
// scope with the filters but status applied). `total` is what the status
// filter left. A location or item: "at this location" / "on this item".
export function countsSentence(counts, scope, { kind = "pos" } = {}) {
  const c = counts || {};
  const all = ["reported", "investigating", "corrective_action", "verifying", "closed", "rejected"]
    .reduce((t, k) => t + (c[k] || 0), 0);
  const n = (x, one, many = `${one}s`) => `${(x || 0).toLocaleString("en-AU")} ${x === 1 ? one : many}`;
  const head = `${(c.open || 0).toLocaleString("en-AU")} open · ${all.toLocaleString("en-AU")} in all`;
  const positions = Math.max(0, (scope?.positions ?? 1) - (kind === "pos" ? 1 : 0));
  let where;
  // A product's design position: the reports on the items built from the product.
  if (scope?.kind === "design") {
    const items = scope.items || 0;
    return `${head}, ${items ? `on the ${n(items, "item")} built from this product` : "no items built from this product yet"}`;
  }
  if (kind === "loc") where = positions ? `at this location (${n(positions, "position")})` : "at this location";
  else if (kind === "item") where = "on this item";
  else where = positions ? `at this position and the ${n(positions, "position")} inside it` : "at this position";
  return `${head}, ${where}`;
}

// A row's level under the row picked: the names from the scope's root down
// to the report's position, the root left out ("" when the report is at the
// root itself).
export function levelText(level) {
  return (level || []).filter(Boolean).join(" › ");
}

// The item on a report, in one line: "Pump unit 7 · serial MU-7 · part
// P-1234 KSB Etanorm", with "(no longer in the register)" when it's gone.
// A snapshot taken when the report was filed, so it's what was there then.
export function itemText(item) {
  if (!item) return "";
  const bits = [item.name || "(no name)"];
  if (item.serial) bits.push(`serial ${item.serial}`);
  if (item.part) bits.push(`part ${[item.part.part_number, item.part.name].filter(Boolean).join(" ")}`.trim());
  else if (item.item_class?.name) bits.push(item.item_class.name);
  return bits.join(" · ") + (item.exists === false ? " (no longer in the register)" : "");
}

// The repeat check, in a sentence: "No repeat failure at this position since
// 12 Oct 2026", or "2 repeat failures since 12 Oct 2026, 1 of the same
// failure mode". `fmt` formats a date.
export function repeatSentence(check, fmt = (d) => d) {
  if (!check) return "";
  const since = check.since ? ` since ${fmt(check.since)}` : "";
  const n = check.repeats || 0;
  if (!n) return `No repeat failure at this position${since}.`;
  const same = check.same_mode_repeats || 0;
  const head = `${n} repeat ${n === 1 ? "failure" : "failures"} at this position${since}`;
  if (!same) return `${head}, none of the same failure mode.`;
  return `${head}, ${same} of the same failure mode.`;
}

// Why the report can't be closed now, in words (null: it can). The server's
// own reasons come back in `can.reasons`; without a verification there's
// nothing to sign off.
export function closeBlock(report) {
  if (!report) return null;
  if (report.can?.close) return null;
  const given = report.can?.reasons;
  if (Array.isArray(given) && given.length) return given.join(" ");
  if (typeof given === "string" && given) return given;
  if (!isOpen(report.status)) return "Reopen the report first.";
  if (!report.verification) return "Record a verification first: did the corrective action work?";
  if (report.verification.result === "not_worked") {
    return "The verification says it didn't work. Add another corrective action and verify again, or reject the report.";
  }
  return null;
}

// The list's filters as the server's query. `scope` is the row picked:
// {position_id} (and everything inside it), {location_id} or {item_id}.
export const DEFAULT_FILTERS = { status: "open", consequence: "", failure_mode_id: "", since: "", until: "", q: "", sort: "newest" };
export const SORTS = [
  { id: "newest", label: "Newest first" },
  { id: "oldest", label: "Oldest first" },
  { id: "status", label: "By stage" },
  { id: "consequence", label: "Safety first" },
  { id: "position", label: "By position" },
];
export function queryParams(filters, scope, { limit = 50, offset = 0 } = {}) {
  const f = { ...DEFAULT_FILTERS, ...(filters || {}) };
  const out = {};
  if (scope?.position_id) {
    out.position_id = scope.position_id;
    out.below = scope.below === false ? 0 : 1;
  } else if (scope?.location_id) out.location_id = scope.location_id;
  else if (scope?.item_id) out.item_id = scope.item_id;
  if (f.status && f.status !== "all") out.status = f.status;
  if (f.consequence) out.consequence = f.consequence;
  if (f.failure_mode_id) out.failure_mode_id = f.failure_mode_id;
  if (f.since) out.since = f.since;
  if (f.until) out.until = f.until;
  if (f.q && f.q.trim()) out.q = f.q.trim();
  if (f.sort && f.sort !== "newest") out.sort = f.sort;
  out.limit = limit;
  if (offset) out.offset = offset;
  return out;
}

// A product's design (its Failure reports tab rolls up the items built from it):
// every report, open ones first (in the loop's order), then closed and rejected.
export const DESIGN_FILTERS = { ...DEFAULT_FILTERS, status: "all", sort: "status" };

// Whether anything beyond the usual (open, newest; or a design's `defaults`) is
// filtering the list.
export function filtering(filters, defaults = DEFAULT_FILTERS) {
  const f = { ...defaults, ...(filters || {}) };
  return f.status !== defaults.status || !!f.consequence || !!f.failure_mode_id || !!f.since || !!f.until || !!(f.q && f.q.trim());
}

// The built items a failure report can be filed on from a product's design
// position: the server's design roll-up items (getDesignRollup), each the position
// implementing it on one item. Retired ones left out; by serial.
// [{id (the item's position), name, serial, label}].
export function builtItemChoices(items) {
  return (items || [])
    .filter((it) => it.position?.id && !it.position.retired)
    .map((it) => ({
      id: it.position.id, name: it.position.name || "(no name)", serial: it.serial || "",
      label: it.serial ? `Serial ${it.serial}` : "(no serial)",
    }))
    .sort((a, b) => a.serial.localeCompare(b.serial, "en", { numeric: true, sensitivity: "base" }));
}

// Where a report filed from a design is, for the form's "At …": "Motor 1 on serial 0007";
// an item's own top already says its serial ("Pump skid · 0007"), so that alone.
export function builtItemPlace(choice) {
  if (!choice) return "";
  if (choice.serial && choice.name.includes(choice.serial)) return choice.name;
  return `${choice.name} on ${choice.serial ? `serial ${choice.serial}` : "an item with no serial"}`;
}

// The scope for a row of the tree: a position (and everything inside it), a
// location, or an item. null for a kind with no reports (a heading).
export function scopeOf(row) {
  if (!row) return null;
  if (row.type === "pos") return { position_id: row.key };
  if (row.type === "loc") return { location_id: row.key };
  if (row.type === "item") return { item_id: row.key };
  return null;
}

// The positions a report can be filed at from a row: a position itself (and
// every position inside it); for a location or an item, the positions in
// scope (the tree's rows inside it, and the position an item is fitted to),
// depth first. [{id, name, depth}].
export function positionsInScope(display, row) {
  if (!display || !row) return [];
  const out = [];
  const seen = new Set();
  const walk = (key, depth) => {
    const r = display.rows.get(key);
    if (!r) return;
    if (r.type === "pos" && !seen.has(r.key)) {
      seen.add(r.key);
      out.push({ id: r.key, name: r.ref.name || "(no name)", depth });
    }
    for (const k of r.kids) walk(k, r.type === "pos" ? depth + 1 : depth);
  };
  if (row.type === "item" && row.ref.fitted_to?.id) {
    seen.add(row.ref.fitted_to.id);
    out.push({ id: row.ref.fitted_to.id, name: row.ref.fitted_to.name || "(no name)", depth: 0 });
  }
  walk(row.key, 0);
  return out;
}

// Who found it, by default: the signed-in person's name, else their email.
export function defaultFoundBy(user) {
  return user?.displayName || user?.name || user?.email || "";
}

// The sign-off line for a closed or rejected report: "Closed on 12 Oct 2026
// by Sam: note".
export function signOffText(kind, record, fmt = (d) => d) {
  if (!record) return "";
  const who = record.by ? ` by ${record.by}` : "";
  const when = record.on ? ` on ${fmt(record.on)}` : "";
  const note = record.note ? `: ${record.note}` : "";
  return `${kind}${when}${who}${note}`;
}

// History, newest first.
export function historyRows(history) {
  return [...(history || [])].reverse();
}

// A history line's time, for the page: "1 Nov 2026, 14:05" in the viewer's time zone.
export function fmtWhen(iso) {
  if (!iso) return "";
  return formatDateTime(new Date(iso)) || iso;
}

// Where a report opens from elsewhere (a work order that's its corrective action): its
// position in the Explorer, on the Failure reports tab, opened on it.
export function reportLink(r) {
  const q = new URLSearchParams({ arrange: "positions", tab: "reports", sel: r.position_id || "", report: r.id });
  return `/asset-register/explorer?${q}`;
}

// What a report does to the life data, in words ("" when the server doesn't say).
export function lifeDataText(life, fmt = (d) => d) {
  if (!life) return "";
  if (!life.counts) return life.why ? `Not in the life data: ${life.why}.` : "";
  const item = life.item?.name ? `${life.item.name}${life.item.serial ? ` (${life.item.serial})` : ""}` : "The item";
  return `In the life data: ${item} counts as failed on ${fmt(life.on)}` +
    (life.replaced ? ", the day this report gives (its replacement ends the same life: not a second failure)."
      : ". If it's replaced later for this failure, that ends the same life: not a second failure.");
}
