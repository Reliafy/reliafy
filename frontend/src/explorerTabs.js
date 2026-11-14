// The tabs of the Explorer's detail panel (Assets › Explorer, and a product's
// page, the Explorer on its design): what the panel beside the tree can show
// for the row picked. Summary for every kind of row; RCM for a position (its
// functions, how they fail, the failure modes and their decisions, read from
// the asset tree itself); Failure reports for a position, a location or an
// item (what has failed there and below, and what was done about it); Parts
// and stock (the parts used and kept there and inside it); Classes (the
// classes used there and inside it, and the whole taxonomy); Measurements for
// a position, a location or an item (every measuring point there and inside
// it: the latest reading, its limits and state, read by hand or fed); Maintenance for a position
// or a location (every task there, from the RCM or added directly, with its cost each time); LSA for
// a position or a location (the logistic support analysis: every task there and
// inside it with what it needs to be done, and how the tasks are packaged into
// visits, LsaPanel; it was "Packages" until 9 Nov 2026, and ?tab=packages
// still opens it); Signals for a
// position or an item (sensor snapshots and their spectra); Modelling for a position (the
// life models attached to it and to the positions inside it, a design's too); Condition
// monitoring for an item class (the tree by Classes: the class's positions with their risk now,
// ClassFleet; a class's only tab, so the one it opens on) and for a position on an asset, in
// every arrangement (that position's own risk now, PositionRisk: the same summary and charts a
// class shows for the member chosen). A tab a kind doesn't have isn't shown (never greyed out).
//
// A product is a design, not an operated thing: its rows (a design's
// positions) have no maintenance done to them, so no Measurements, Signals or
// stock. They do have Failure reports (`designKinds`): not filed there, but the
// reports raised on the items built from the product, at the position that
// implements the row on each item and below it, rolled up to the design (the
// list takes a design position as its scope; a report is filed on a built item,
// picked by its serial). They keep RCM and FME(C)A (the design's maintenance programme is a
// design output; the assets built from it carry it out), the LSA (what each of
// the programme's tasks needs, also a design output; packaging tasks into
// visits happens on the built assets, so a design's LSA has no packaging:
// LsaPanel), Classes, and "Parts" (the parts list, with no stock). Its layout's rows (the product's design
// locations, on its page's Locations) are no place you look after either: no
// Failure reports, Signals, or Parts and stock; the Summary gives the design
// facts (what's placed there).
//
// Parts and stock and Classes are hidden for now (EXPLORER_PARTS_CLASSES_TABS
// below): their entries, bodies (TreeDetail) and old addresses (redirects.js)
// stay, so one switch brings them back. Signals is the same
// (EXPLORER_SIGNALS_TAB).
//
// Adding a tab is one entry here (id, label, the kinds of row that have it,
// `asset: true` when a design's rows don't, `designKinds` for the kinds of a
// design's rows that have it all the same, `titleBy` for a kind of row whose
// hover text differs) and its body in TreeDetail. The
// address names the tab (?tab=rcm, left out for Summary); the tab picked stays
// as you walk the tree, shown on every row of a kind that has it, Summary on
// the others. A class shows its one tab without the address naming it; walking
// on from it to a position keeps that tab (tabCarried).

// Derryn, 8 Nov 2026: hidden for now, may come back. Off, `tabsFor` leaves out
// Parts and stock and Classes on every row (an asset's, a product's design),
// so a `?tab=parts` or `?tab=classes` address shows Summary, and the old pages'
// redirects (redirects.js) land on the Explorer with no tab.
export const EXPLORER_PARTS_CLASSES_TABS = false;

// Derryn, 8 Nov 2026: hidden for now. Off, `tabsFor` leaves out Signals on
// every row (positions, items, a product's design), so `?tab=signals` shows
// Summary. Channels are rows of the Measurements tab instead, beside the
// hand-read points; a channel's spectrum, bands and settings open in full in
// that tab (&channel=, signals.js channelPath).
export const EXPLORER_SIGNALS_TAB = false;

const HIDDEN_WHEN_OFF = { parts: EXPLORER_PARTS_CLASSES_TABS, classes: EXPLORER_PARTS_CLASSES_TABS, signals: EXPLORER_SIGNALS_TAB };
const offered = (t) => HIDDEN_WHEN_OFF[t.id] !== false;

export const TABS = [
  { id: "summary", label: "Summary", title: "What it is, where it is, its work and what's inside it", kinds: ["pos", "loc", "item", "group"] },
  // A place has them too: they open on the top position at that place (the
  // RCM is by position, so the tree arranges by positions).
  { id: "rcm", label: "RCM", title: "What this position (or the positions at this place) does, how it can fail, and the decision for each failure mode", kinds: ["pos", "loc"] },
  { id: "fmea", label: "FME(C)A", title: "The failure modes here as an FMEA worksheet: cause, effects, scores, action priority and criticality", kinds: ["pos", "loc"] },
  // Every maintenance task on the row (Derryn, 12 Nov 2026): from its RCM or added directly here,
  // with how often, its package, when it's next due and what it costs each time (the figure the
  // RCM reads). "Include what's inside" adds the tasks below. A design's rows have it too: their
  // programme (no due dates or packages: those belong to the built items). The LSA tab's table
  // (LsaPanel, variant "maintenance"); a task opens in the panel beside the tree.
  {
    id: "maintenance", label: "Maintenance", title: "Every maintenance task here: from the RCM or added directly, how often, when it's next due and what it costs each time",
    kinds: ["pos", "loc"],
  },
  // A design's positions have it too (designKinds): the reports on the items built from the
  // product, here and below; its design locations don't.
  {
    id: "reports", label: "Failure reports", title: "What has failed here and below, and what was done about it",
    designTitle: "What has failed here and below on the items built from this product, and what was done about it",
    kinds: ["pos", "loc", "item"], asset: true, designKinds: ["pos"],
  },
  {
    id: "parts", label: "Parts and stock", title: "The parts used here and inside it, and what's in stock where",
    designLabel: "Parts", designTitle: "The parts list: the parts used here and inside it", kinds: ["pos", "loc"],
    notDesignLoc: true,
  },
  { id: "classes", label: "Classes", title: "The classes used here and inside it, and every class in the register", kinds: ["pos", "loc"] },
  // The life models on each position (Derryn, 9 Nov 2026): a design's positions carry them too
  // (a built item inherits its design's), so no `asset`. Drawn as a tree-table (explorerModels.js).
  { id: "models", label: "Modelling", title: "The life models on this position and the positions inside it: what each says, where it came from and what uses it", kinds: ["pos"] },
  // The missions flown on each position's RBD (Derryn, 9 Nov 2026: "Products need an RBD tab,
  // called Missions"; "Missions are RBDs, so they belong to positions"): a design's positions too,
  // so no `asset`. Drawn as a tree-table (explorerMissions.js); a mission opens in the table area.
  { id: "missions", label: "Missions", title: "The missions flown on this position's RBD and the positions inside it: each mission's phases and its chance of completing", kinds: ["pos"] },
  // An item class (a row of the tree by Classes) has this one tab and no Summary: its fleet. A
  // position on an asset has it too, in every arrangement: its own risk now (one id and one label,
  // so the tab stays picked from a class to a position and on to the next). Not a design's
  // positions: nothing is fitted or read there.
  {
    id: "condition", label: "Condition monitoring", title: "Each position of this class with its risk now, highest first",
    titleBy: { pos: "This position's risk now: its chance of failing soon and its life left, from its item's age and readings" },
    kinds: ["cls", "pos"], asset: true,
  },
  { id: "measurements", label: "Measurements", title: "Every measuring point here and inside it: the latest reading, its limits and whether it's past them", kinds: ["pos", "loc", "item"], asset: true },
  {
    id: "lsa", label: "LSA", title: "Logistic support analysis: what each task needs to be done, and how the tasks are packaged into visits",
    designTitle: "Logistic support analysis: what each task in the design needs to be done", kinds: ["pos", "loc"],
  },
  { id: "signals", label: "Signals", title: "Vibration and other sensors that send snapshots: spectra, watch bands and how they change", kinds: ["pos", "item"], asset: true },
];
const BY_ID = new Map(TABS.filter(offered).map((t) => [t.id, t]));
export const DEFAULT_TAB = "summary";

// Earlier tab ids and the tab they open now (Derryn, 9 Nov 2026: Packages became
// the LSA tab, packaging included).
export const TAB_ALIASES = { packages: "lsa" };

// The tab the address asks for, if it's one (else Summary).
export function tabParam(value) {
  const id = TAB_ALIASES[value] || value;
  return BY_ID.has(id) ? id : DEFAULT_TAB;
}

// Is the row part of a product's design (its top position, marked `design`,
// a position inside it, marked `in_design` when the tree is scoped to the
// design: products.js scopeTree, or one of its design locations, `design_of`)?
export function isDesignRow(row) {
  if (row?.type === "loc") return !!(row.ref?.design_of || row.ref?.in_design);
  return row?.type === "pos" && !!(row.ref?.design || row.ref?.in_design);
}

// Is the row a product's top position (the product itself)?
export function isProductRow(row) {
  return row?.type === "pos" && !!row.ref?.design;
}

// The word over a picked row's name: what kind of row it is. A product's own
// row says "Product"; the positions of its design below it stay "Position".
export const ROW_KINDS = { pos: "Position", loc: "Location", item: "Item", cls: "Item class", group: "" };
export function rowKind(row) {
  if (row?.type === "loc" && isDesignRow(row)) return "Design location";
  return isProductRow(row) ? "Product" : ROW_KINDS[row?.type] || "";
}

// The tabs a row has (a design's rows with their own names where they differ).
export function tabsFor(row) {
  if (!row) return [];
  const design = isDesignRow(row);
  return TABS.filter((t) => offered(t) && t.kinds.includes(row.type) && !(design && t.asset && !t.designKinds?.includes(row.type))
    && !(design && row.type === "loc" && t.notDesignLoc))
    .map((t) => (design && (t.designLabel || t.designTitle) ? { ...t, label: t.designLabel || t.label, title: t.designTitle || t.title } : t))
    .map((t) => (t.titleBy?.[row.type] ? { ...t, title: t.titleBy[row.type] } : t));
}

// The tab to show for a row: the one picked if the row has it, else Summary; a row with no
// Summary (an item class) shows its first tab, never a blank panel.
export function shownTab(wanted, row) {
  const tabs = tabsFor(row);
  if (tabs.some((t) => t.id === wanted)) return wanted;
  return tabs.length && !tabs.some((t) => t.id === DEFAULT_TAB) ? tabs[0].id : DEFAULT_TAB;
}

// Does the row's panel have a tab bar? With two tabs or more, and with one that isn't Summary
// (an item class's Condition monitoring): a row with Summary alone (a group) has none.
export function hasTabBar(row) {
  const tabs = tabsFor(row);
  return tabs.length > 1 || (tabs.length === 1 && tabs[0].id !== DEFAULT_TAB);
}

// The tab an address opens on: the one it asks for (tabParam), except with an item class picked
// by Classes (?arrange=classes&sel=cls:…, the key assetTree.js classKey makes). A class has only
// its own tab, so a tab of the tree-tables in the address (RCM and the rest are by position)
// doesn't take the tree off the class: the class shows its Condition monitoring.
export function addressTab(value, { arrange = null, sel = null } = {}) {
  const tab = tabParam(value);
  if (arrange === "classes" && typeof sel === "string" && sel.startsWith("cls:")) return shownTab(tab, { type: "cls" });
  return tab;
}

// The tab to keep in the address when the tree's arrangement changes to `mode`: a tab only an
// item class has is left behind off Classes (the other arrangements have no class rows). None is
// today: Condition monitoring is a position's tab too, so it comes along, shown on the position
// picked there and Summary on any other row (shownTab).
export function tabForArrangement(tab, mode) {
  const only = BY_ID.get(tab)?.kinds;
  if (only && only.every((k) => k === "cls") && mode !== "classes") return DEFAULT_TAB;
  return tab;
}

// The tab to name in the address when the selection walks from the row `from` to the row `to`
// and the address names none (`named`: it does). A class shows its one tab without being asked
// for, so walking on from it to a row that has that tab keeps it: from a class's Condition
// monitoring to a position's, and on to the next position's. Null: nothing to add (the address
// names a tab already, which is the one picked; or the row walked to hasn't the class's tab).
export function tabCarried(from, to, { named = false } = {}) {
  if (named || !from || !to || from.type !== "cls" || to.type === "cls") return null;
  const shown = shownTab(DEFAULT_TAB, from);
  return shown !== DEFAULT_TAB && tabsFor(to).some((t) => t.id === shown) ? shown : null;
}

// Every row in a branch: the row's own key and everything inside it in the
// display tree, split by kind ({pos, loc, item}: Sets of keys). For the tabs
// that show a branch's parts and classes.
export function branchOf(display, key) {
  const out = { pos: new Set(), loc: new Set(), item: new Set() };
  if (!display?.rows?.has(key)) return out;
  const stack = [key];
  while (stack.length) {
    const r = display.rows.get(stack.pop());
    if (!r) continue;
    out[r.type]?.add(r.key);
    stack.push(...(r.kids || []));
  }
  return out;
}

// The parts at a branch: kept in stock at a location in it, or on the parts
// list of a position in it. A design's parts list has no stock (`design`).
export function partsInBranch(parts = [], branch, { design = false } = {}) {
  return parts.filter((pt) => (!design && (pt.stock || []).some((st) => branch.loc.has(st.location?.id)))
    || (pt.used_at || []).some((u) => branch.pos.has(u.position?.id)));
}

// The position classes used in a branch, with how many of its positions have
// each: [{position_class, here}], A–Z.
export function classesInBranch(display, branch) {
  const count = new Map();
  for (const k of branch.pos) {
    const c = display.rows.get(k)?.ref?.position_class;
    if (c) count.set(c, (count.get(c) || 0) + 1);
  }
  return [...count].map(([position_class, here]) => ({ position_class, here }))
    .sort((a, b) => a.position_class.localeCompare(b.position_class, "en", { numeric: true, sensitivity: "base" }));
}

// ---- Plain tabs with an overflow (prototype, Derryn 14 Nov 2026) -------------------------------
//
// The panel's tabs as one flat row, ordered by use, the ones that don't fit folded into a last
// "⋯ N" tab (the shared Tabs with `overflow`):
//   Summary · Maintenance · Monitoring · RCM · FME(C)A · Models · History
// Maintenance has inner views Tasks · What it needs (the LSA tab) · Packages · Forecast (a preview,
// only with MENU_PREVIEW); Monitoring has Readings (Measurements) · Life left (Condition
// monitoring: the chance of failing soon and the life left); Models has Life models (the Modelling
// tab) · Missions. History is the Failure reports; on a product's design it's "Field reports" (the
// reports on the items built from the product).
//
// It's a layer over the tabs above, not a new set of them: every view is one of TABS (plus the
// ?mview= the Maintenance and LSA bodies read), so the address still names the tab and every old
// address (?tab=lsa, ?tab=condition, …) opens its tab and inner view (panelView). A view a row
// hasn't (tabsFor) is left out, and a tab with no views for the row isn't shown (never greyed); the
// order never changes. A tab no panel tab names (Parts and stock, Classes, Signals, when switched
// on) stays a tab of its own at the end of the row. Off, the panel shows the flat TABS row.
export const EXPLORER_PANEL_TABS = true;

export const PANEL_TABS = [
  { id: "summary", label: "Summary", views: [{ id: "summary", tab: "summary" }] },
  {
    id: "maintenance", label: "Maintenance", title: "The maintenance tasks here, what each needs, and how they're packaged into visits",
    designTitle: "The maintenance programme here: its tasks and what each needs",
    views: [
      { id: "tasks", label: "Tasks", tab: "maintenance" },
      { id: "needs", label: "What it needs", tab: "lsa", title: "What each task needs to be done: labour, tools, spares and method" },
      // Packaging happens on the built items, so a design's rows haven't it (asset).
      { id: "packages", label: "Packages", tab: "lsa", mview: "packages", asset: true, title: "The work packages here: tasks done together on one visit" },
      { id: "forecast", label: "Forecast", tab: "maintenance", mview: "forecast", preview: true, title: "Forecast (preview): the forecast's layout, with made-up numbers" },
    ],
  },
  {
    id: "monitoring", label: "Monitoring", title: "Readings at every measuring point, and the life left",
    views: [
      { id: "readings", label: "Readings", tab: "measurements" },
      { id: "risk", label: "Life left", tab: "condition" },
    ],
  },
  { id: "rcm", label: "RCM", views: [{ id: "rcm", tab: "rcm" }] },
  { id: "fmea", label: "FME(C)A", views: [{ id: "fmea", tab: "fmea" }] },
  {
    id: "models", label: "Models", title: "The life models on this position and the positions inside it, and the missions flown on its RBD",
    views: [
      { id: "life", label: "Life models", tab: "models" },
      { id: "missions", label: "Missions", tab: "missions" },
    ],
  },
  { id: "history", label: "History", designLabel: "Field reports", views: [{ id: "reports", label: "Failure reports", tab: "reports" }] },
];

// The tabs a row has: [{id, label, title, views: [{id, label, tab, mview, title}]}], each with
// only the views the row has, and no tab without one. `preview`: MENU_PREVIEW is on (Forecast).
export function panelTabsFor(row, { preview = false } = {}) {
  const tabs = tabsFor(row);
  const has = new Map(tabs.map((t) => [t.id, t]));
  const design = isDesignRow(row);
  const used = new Set();
  const out = [];
  for (const p of PANEL_TABS) {
    const views = p.views.filter((v) => has.has(v.tab) && !(v.preview && !preview) && !(v.asset && design))
      .map((v) => ({ ...v, label: v.label || p.label, title: v.title || has.get(v.tab).title }));
    if (!views.length) continue;
    views.forEach((v) => used.add(v.tab));
    // A tab with one view says what that view is on hover (a design's Field reports: the reports
    // on the items built from the product; a class's Monitoring: its positions' risk).
    const title = views.length === 1 ? views[0].title : (design && p.designTitle) || p.title;
    out.push({ id: p.id, label: (design && p.designLabel) || p.label, title, views });
  }
  // A tab no panel tab names (switched back on): a tab of its own.
  for (const t of tabs) {
    if (!used.has(t.id)) out.push({ id: t.id, label: t.label, title: t.title, views: [{ id: t.id, label: t.label, tab: t.id, title: t.title }] });
  }
  return out;
}

// Where the row's panel is: {tab, view} (panel tab and inner view ids) for the tab shown (shownTab)
// and the ?mview= in the address. A view that names an mview is picked only with that mview; else
// the view for the tab with none. Null for a row with no tabs.
export function panelView(tab, row, { mview = null, preview = false } = {}) {
  const shown = shownTab(tab, row);
  let plain = null;
  for (const p of panelTabsFor(row, { preview })) {
    for (const v of p.views) {
      if (v.tab !== shown) continue;
      if (v.mview && v.mview === mview) return { tab: p.id, view: v.id };
      if (!v.mview && !plain) plain = { tab: p.id, view: v.id };
    }
  }
  return plain;
}

// The address tab and ?mview= that open a panel tab's view: {tab, mview} (mview null: none).
// `view` left out: the tab's first view. Null: the row hasn't that tab.
export function viewTarget(row, tabId, viewId = null, { preview = false } = {}) {
  const p = panelTabsFor(row, { preview }).find((x) => x.id === tabId);
  if (!p) return null;
  const v = (viewId && p.views.find((x) => x.id === viewId)) || p.views[0];
  return { tab: v.tab, mview: v.mview || null };
}

// The words that name where an address tab is, for text that sends you there ("Models › Life
// models"; with the panel tabs off, the old tab's name: "Modelling").
export function tabPlace(tab) {
  const old = TABS.find((t) => t.id === tab)?.label || tab;
  if (!EXPLORER_PANEL_TABS) return old;
  for (const p of PANEL_TABS) {
    const v = p.views.find((x) => x.tab === tab && !x.mview);
    if (v) return p.views.length > 1 ? `${p.label} › ${v.label}` : p.label;
  }
  return old;
}
