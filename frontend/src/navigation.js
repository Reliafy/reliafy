// The app's menu (#438): Home, then what people work on (Design, Operate,
// Analyse), then Reports and the Agent. One menu for everyone; a user's roles
// are a lens over it: the entries their roles use come first, in role order,
// and the rest wait under "More" (no roles: everything, as before).
//
// Everything about roles is in ROLES below, so the menu can change from a
// lens to a per-role structure by changing this file only.
//
// Pure data and functions (no React): the Sidebar draws it, Home and the
// Maintenance tabs read it, and navigation.test.js checks it.

export const SECTIONS = [
  { id: "design", label: "Design" },
  { id: "operate", label: "Operate" },
  { id: "analyse", label: "Analyse" },
];

// An entry or child with `needs` shows only where the workspace has it:
// "maintenance" (Reliafy Maintenance is on and the user may use it), "agent"
// (the Reliability Agent is on). "requirements" and "failures" are pages not
// built yet: nothing has them, so their entries stay hidden until they exist.
//
// An entry opens on its first child the user has (or its own `to`). It is
// highlighted on any page under one of its `match` prefixes (default: `to`).
// A child is highlighted on its own page (and the pages under it, unless
// `end`).
export const ENTRIES = [
  { id: "home", label: "Home", to: "/home" },

  {
    id: "systems", section: "design", label: "Systems", to: "/systems",
    children: [
      { to: "/systems", label: "Block diagrams", end: true },
      { to: "/systems/runs", label: "Simulation runs" },
      { to: "/systems/structure", label: "Product structure", needs: "maintenance" },
    ],
  },
  { id: "requirements", section: "design", label: "Requirements", to: "/requirements", needs: "requirements" },

  {
    id: "assets", section: "operate", label: "Assets", to: "/asset-register", needs: "maintenance",
    children: [
      { to: "/asset-register", label: "Positions", end: true },
      { to: "/asset-register/items", label: "Items" },
      { to: "/asset-register/locations", label: "Locations" },
      { to: "/asset-register/parts", label: "Parts & stock" },
      { to: "/asset-register/classes", label: "Classes & conditions" },
    ],
  },
  {
    id: "maintenance", section: "operate", label: "Maintenance", to: "/maintenance",
    children: [
      { to: "/maintenance", label: "Due & work orders", end: true, needs: "maintenance" },
      { to: "/maintenance/rcm", label: "RCM studies" },
    ],
  },
  { id: "failures", section: "operate", label: "Failures", to: "/failures", needs: "failures" },

  { id: "data", section: "analyse", label: "Data", to: "/data" },
  {
    id: "models", section: "analyse", label: "Models", to: "/models",
    children: [
      { to: "/models", label: "All models", end: true },
      { to: "/models/life", label: "Life data" },
      { to: "/models/recurrent", label: "Recurrent" },
      { to: "/models/alt", label: "Accelerated life" },
      { to: "/models/degradation", label: "Degradation" },
      { to: "/models/tracking", label: "Degradation tracking" },
    ],
  },
  {
    id: "strategy", section: "analyse", label: "Strategy", to: "/strategy",
    children: [
      { to: "/strategy", label: "Saved analyses", end: true },
      { to: "/strategy/replacement", label: "Optimal replacement" },
      { to: "/strategy/compare", label: "Compare two models" },
      { to: "/strategy/failure-finding", label: "Failure finding" },
      { to: "/strategy/demonstration-test", label: "Demonstration test" },
    ],
  },
  { id: "forecasts", section: "analyse", label: "Forecasts", to: "/forecasts" },

  { id: "reports", label: "Reports", to: "/reports" },
  { id: "agent", label: "Reliability Agent", to: "/agent", needs: "agent" },
];

// What people do, and the entries each uses, most used first. The order of a
// user's roles is theirs: the first one picked is the primary role, which Home
// leads with (`home`: its cards, see views/HomePage.jsx).
export const ROLES = [
  {
    id: "analyst", label: "Reliability engineer / analyst",
    entries: ["data", "models", "strategy", "forecasts", "systems", "reports", "agent"],
    home: ["recent-models", "recent-data"],
  },
  {
    id: "design", label: "Design engineer",
    entries: ["systems", "requirements", "models", "data", "reports"],
    home: ["recent-systems", "recent-models"],
  },
  {
    id: "planner", label: "Maintenance engineer / planner",
    entries: ["maintenance", "assets", "forecasts", "strategy", "failures", "reports"],
    home: ["due"],
  },
  {
    id: "technician", label: "Technician",
    entries: ["maintenance", "assets"],
    home: ["work-today"],
  },
  {
    id: "logistics", label: "Supportability / logistics",
    entries: ["assets", "forecasts", "systems", "data", "reports"],
    home: ["spares", "due"],
  },
  {
    id: "manager", label: "Manager",
    entries: ["reports", "maintenance", "forecasts", "systems", "strategy"],
    home: ["waiting"],
  },
];

export const ROLE_IDS = ROLES.map((r) => r.id);
const roleById = new Map(ROLES.map((r) => [r.id, r]));

// Home's cards when no role is picked, in order (each role's lead cards come
// before these; a card shows once).
export const DEFAULT_HOME = ["due", "recent-models", "recent-systems", "recent-data"];

const available = (thing, has) => !thing.needs || Boolean(has[thing.needs]);

// The entries this workspace has, each with the children it has and `to` set
// to where it opens.
export function liveEntries(has = {}) {
  return ENTRIES.filter((e) => available(e, has)).map((e) => {
    const children = e.children?.filter((c) => available(c, has));
    if (!children) return e;
    if (!children.length) return { ...e, children: undefined };
    return { ...e, to: children[0].to, match: e.match || [e.to], children };
  });
}

// The menu for a user with `roles` (role ids, primary first) in a workspace
// that `has` features: `main`, the entries shown, and `more`, the rest (under
// "More"). Home is always shown. Shown entries keep their section; within a
// section (and in the closing group) they're in role order.
export function buildMenu({ roles = [], has = {} } = {}) {
  const live = liveEntries(has);
  const picked = roles.filter((r) => roleById.has(r));
  if (!picked.length) return { main: live, more: [] };
  const rank = new Map();
  for (const r of picked) {
    for (const id of roleById.get(r).entries) if (!rank.has(id)) rank.set(id, rank.size);
  }
  const used = (e) => e.id === "home" || rank.has(e.id);
  const groupOrder = (e) => (e.id === "home" ? -1 : e.section ? SECTIONS.findIndex((s) => s.id === e.section) : SECTIONS.length);
  const main = live.filter(used).sort((a, b) =>
    groupOrder(a) - groupOrder(b) || (rank.get(a.id) ?? -1) - (rank.get(b.id) ?? -1));
  return { main, more: live.filter((e) => !used(e)) };
}

// Entries grouped for drawing: [{ section: {id, label} | null, entries }], in
// the order given (Home and the closing group have no heading).
export function groupBySection(entries) {
  const groups = [];
  for (const e of entries) {
    const key = e.section || (e.id === "home" ? "home" : "end");
    const last = groups[groups.length - 1];
    if (last?.key === key) last.entries.push(e);
    else groups.push({ key, section: SECTIONS.find((s) => s.id === e.section) || null, entries: [e] });
  }
  return groups;
}

const under = (pathname, prefix) => pathname === prefix || pathname.startsWith(prefix + "/");

// Whether `entry` is the one the page at `pathname` belongs to.
export function entryActive(entry, pathname) {
  return (entry.match || [entry.to]).some((p) => under(pathname, p));
}

export function childActive(child, pathname) {
  return child.end ? pathname === child.to : under(pathname, child.to);
}

// The entry (from `entries`) a page belongs to, if any.
export function activeEntry(entries, pathname) {
  return entries.find((e) => entryActive(e, pathname)) || null;
}

// Where each kind of saved item opens in the app, by its collection.
export const COLLECTION_PATHS = {
  models: "/models/m/",
  recurrent_models: "/models/recurrent/",
  degradation_models: "/models/degradation/",
  alt_models: "/models/alt/",
  datasets: "/data/d/",
  rbds: "/systems/b/",
  strategy_analyses: "/strategy/analyses/",
  rcm_studies: "/maintenance/rcm/",
  fleets: "/forecasts/",
};

export function itemPath(collection, id) {
  const base = COLLECTION_PATHS[collection];
  return base ? base + encodeURIComponent(id) : null;
}

// Home's cards for these roles, in order: the primary role's first, then the
// other roles', then the rest of the defaults.
export function homeCards(roles = []) {
  const out = [];
  for (const r of roles) for (const c of roleById.get(r)?.home || []) if (!out.includes(c)) out.push(c);
  for (const c of DEFAULT_HOME) if (!out.includes(c)) out.push(c);
  return out;
}
