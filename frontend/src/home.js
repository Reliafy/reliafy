// Home (#nav): the rows of its "Needs attention" and "Recent" lists, from
// what the existing endpoints return. Each row is
// { key, kind, tone, name, url, detail, at } — the shape the "What changed"
// list draws (components/WhatChanged.jsx), so the three lists look alike.
import { rcmDetail } from "./changes.js";
import { datasetPath } from "./navigation.js";

// Most rows each list shows (the counts above them are complete).
export const ATTENTION_ROWS = 6;
export const RECENT_ROWS = 8;
// Below this many items of its own, a workspace is "near-empty": Home shows
// the "Start here" cards first and large, not last and compact.
export const NEAR_EMPTY = 3;

// "20 Oct 2026" for a workspace date ("2026-10-20"), read as a calendar day.
export function dayText(iso) {
  if (!iso) return "";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? String(iso)
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// What needs the user: fleet alerts that fired and RCM decisions whose
// evidence now contradicts them (from GET /api/changes), tracked items due
// for replacement (the tracked fleets' health), and — for Maintenance
// operators — overdue and due-soon tasks (the Maintenance overview).
// Worst first: danger, then warning, then the rest; newest first within each.
export function attentionRows({ changes = null, tracked = [], maintenance = null } = {}) {
  const rows = [];
  for (const a of changes?.alerts || []) {
    rows.push({ key: `alert-${a.fleet_id}-${a.at}`, kind: "Fleet alert", tone: "warning", name: a.fleet,
      url: a.url, detail: a.text, at: a.at });
  }
  for (const e of (changes?.rcm_evidence || []).filter((x) => x.status === "contradicted")) {
    rows.push({ key: `rcm-${e.study_id}-${e.mode}-${e.evidence_url}`, kind: "RCM evidence", tone: "danger",
      name: e.study, url: e.url, detail: rcmDetail(e), at: e.at });
  }
  for (const f of (tracked || []).filter((x) => !x.is_sample)) {
    const t = f.tracking || {};
    if (t.replace > 0) {
      rows.push({ key: `track-${f.id}`, kind: "Degradation", tone: "danger", name: f.name,
        url: `/risk/${f.id}`, detail: `${plural(t.replace, "item")} to replace now`, at: null });
    } else if (t.plan > 0) {
      rows.push({ key: `track-${f.id}`, kind: "Degradation", tone: "warning", name: f.name,
        url: `/risk/${f.id}`, detail: `${plural(t.plan, "item")} to plan a replacement for`, at: null });
    }
  }
  for (const t of maintenance?.due || []) {
    if (!t.next_due) continue;
    rows.push({
      key: `due-${t.id}`,
      kind: t.overdue ? "Overdue" : "Due soon",
      tone: t.overdue ? "danger" : null,
      name: t.name,
      url: t.open_work_order ? `/maintenance/work-orders/${t.open_work_order.id}` : "/maintenance",
      detail: `Due ${dayText(t.next_due)}${t.open_work_order ? ` · work order #${t.open_work_order.number}` : " · no work order yet"}`,
      at: null,
    });
  }
  const rank = { danger: 0, warning: 1 };
  return rows
    .map((r, i) => ({ r, i }))
    .sort((a, b) => (rank[a.r.tone] ?? 2) - (rank[b.r.tone] ?? 2) || a.i - b.i)
    .map(({ r }) => r);
}

const when = (x) => x.updated_at || x.created_at || null;

// The user's own items, most recently saved or edited first. Reliafy
// doesn't record which items a user opened, so "recent" is by save time.
// ``models`` are allModels.js rows; the rest are the API lists as returned.
export function recentRows({
  models = [], datasets = [], rbds = [], studies = [], forecasts = [], analyses = [], tracked = [],
} = {}) {
  const own = (xs) => (xs || []).filter((x) => !x.is_sample);
  const rows = [
    ...own(models).map((m) => ({ key: `model-${m.type}-${m.id}`, kind: m.kind || "Model", name: m.name, url: m.to,
      detail: m.detail, at: m.created_at })),
    ...own(datasets).map((d) => ({ key: `ds-${d.id}`, kind: "Dataset", name: d.name, url: datasetPath(d.id),
      detail: d.n_rows != null ? plural(d.n_rows, "row") : null, at: when(d) })),
    ...own(rbds).map((r) => ({ key: `rbd-${r.id}`, kind: "Block diagram", name: r.name, url: `/systems/b/${r.id}`,
      detail: r.n_nodes != null ? plural(r.n_nodes, "block") : null, at: when(r) })),
    ...own(studies).map((s) => ({ key: `rcm-${s.id}`, kind: "RCM study", name: s.name, url: `/maintenance/rcm/${s.id}`,
      detail: s.system || null, at: when(s) })),
    ...own(forecasts).map((f) => ({ key: `fleet-${f.id}`, kind: "Failure forecast", name: f.name,
      url: `/forecasts/${f.id}`, detail: f.n_items != null ? plural(f.n_items, "item") : null, at: when(f) })),
    ...own(analyses).map((a) => ({ key: `sa-${a.id}`, kind: "Strategy analysis", name: a.name,
      url: `/strategy/analyses/${a.id}`, detail: a.headline || null, at: when(a) })),
    ...own(tracked).map((f) => ({ key: `track-${f.id}`, kind: "Tracked fleet", name: f.name,
      url: `/risk/${f.id}`, detail: f.model_name || null, at: when(f) })),
  ];
  return rows.map((r) => ({ ...r, tone: null })).sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
}

// ---- Role cards ---------------------------------------------------------------
//
// With roles picked (Settings › What do you do?), Home leads with each role's
// cards (navigation.js ROLES `home`), the primary role's first. Each card is
// rows in the same shape as the lists above, from what Home already loaded.

// The recent rows each "your recent …" card shows, by their key's prefix.
const RECENT_KINDS = {
  "recent-models": ["model-"],
  "recent-data": ["ds-"],
  "recent-systems": ["rbd-"],
  fleets: ["fleet-", "track-"],
};

const ofKinds = (rows, prefixes) => rows.filter((r) => prefixes.some((p) => r.key.startsWith(p)));

// A "your recent …" card's rows.
export function recentFor(card, recent = []) {
  return ofKinds(recent, RECENT_KINDS[card] || []);
}

// The recent work no role card shows already (all of it with no role cards).
export function otherRecent(cards = [], recent = []) {
  const shown = cards.flatMap((c) => RECENT_KINDS[c] || []);
  return recent.filter((r) => !shown.some((p) => r.key.startsWith(p)));
}

// Fleets: forecast alerts and tracked items due for replacement first, then
// the user's forecasts and tracked fleets, most recent first; each fleet once.
export function fleetRows(attention = [], recent = []) {
  const alerts = attention.filter((r) => r.key.startsWith("alert-") || r.key.startsWith("track-"));
  const seen = new Set(alerts.map((r) => r.url));
  return [...alerts, ...recentFor("fleets", recent).filter((r) => !seen.has(r.url))];
}

// Planner: Reliafy Maintenance's tasks overdue or due in the next 30 days.
export function dueRows(maintenance) {
  return attentionRows({ maintenance }).filter((r) => r.key.startsWith("due-"));
}

// Technician: open work orders due today or before, oldest first.
export function workTodayRows(maintenance) {
  const today = maintenance?.today;
  if (!today) return [];
  return (maintenance.open_work_orders || [])
    .filter((w) => w.due && w.due <= today)
    .sort((a, b) => (a.due > b.due ? 1 : a.due < b.due ? -1 : 0))
    .map((w) => ({
      key: `wo-${w.id}`,
      kind: w.due < today ? "Overdue" : "Today",
      tone: w.due < today ? "danger" : null,
      name: `#${w.number} ${w.title}`,
      url: `/maintenance/work-orders/${w.id}`,
      detail: [w.subject?.name, w.location?.name].filter(Boolean).join(" · ") || null,
      at: null,
    }));
}

// Supportability / logistics: critical spares with fewer usable than kept.
export function sparesRows(maintenance) {
  return (maintenance?.critical_spares || []).map((v) => ({
    key: `spare-${v.id}`,
    kind: v.usable_on_hand > 0 ? "Low" : "None left",
    tone: v.usable_on_hand > 0 ? "warning" : "danger",
    name: `${v.part.part_number} ${v.part.name}`,
    url: v.part.id ? `/asset-register/parts/${v.part.id}` : "/asset-register/parts",
    detail: `${v.usable_on_hand} usable, keep ${v.min_on_hand}${v.position?.name ? ` · ${v.position.name}` : ""}`,
    at: null,
  }));
}

// Manager: how the RCM decisions stand against their evidence and, with
// Reliafy Maintenance, what's waiting on someone. Each figure links to where
// it's dealt with; `alert` ones are drawn in the danger colour when above 0.
export function waitingFigures(studies = [], maintenance = null) {
  const own = (studies || []).filter((s) => !s.is_sample);
  const sum = (key) => own.reduce((n, s) => n + (s.rollup?.[key] || 0), 0);
  const figures = [
    { label: "RCM decisions supported", n: sum("supported"), to: "/maintenance/rcm" },
    { label: "contradicted by evidence", n: sum("contradicted"), to: "/maintenance/rcm", alert: true },
    { label: "without evidence", n: sum("unevidenced") + sum("inconclusive"), to: "/maintenance/rcm" },
  ];
  if (maintenance) {
    figures.push(
      { label: "changes to decide", n: (maintenance.proposals || []).length, to: "/maintenance", alert: true },
      { label: "tasks overdue", n: (maintenance.due || []).filter((t) => t.overdue).length, to: "/maintenance", alert: true },
      { label: "open work orders", n: (maintenance.open_work_orders || []).length, to: "/maintenance" },
    );
  }
  return figures;
}
