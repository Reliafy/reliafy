// The app's menu: Home, then what people work on under three headings
// (Design, Operate, Analyse), then Reports and the Reliability Agent. One menu
// for everyone; a user's roles are a lens over it: the entries their roles use
// come first, in role order, and the rest wait under "More" (no roles:
// everything, as before).
//
// Rules the tests hold it to (navigation.test.js):
// - Design and Operate hold things and records; Analyse holds calculations.
// - An entry shows only where the workspace has it (`needs`), and never as a
//   placeholder for a page that doesn't exist yet, except where a deployment
//   turns the menu preview on (`needs: "preview"`, see plannedPages.js).
// - An entry opens on its own landing page; its children are sub-types or
//   filtered views of it, never a second copy of the landing page.
//
// Everything about roles is in ROLES below, so the menu can change from a
// lens to a per-role structure by changing this file only.
//
// Pure data and functions (no React): the Sidebar draws it, section headers
// take their labels from it, Home reads the roles, and the tests check it.

export const SECTIONS = [
  { id: "design", label: "Design" },
  { id: "operate", label: "Operate" },
  { id: "analyse", label: "Analyse" },
];

// `needs` names what an entry or child needs: "maintenance" (Reliafy
// Maintenance is on and the user may use it), "agent" (the Reliability Agent
// is on), "preview" (the deployment shows the menu's not-yet-built entries as
// blank pages, plannedPages.js; nothing else has them, so they stay hidden).
//
// `landingNeeds`: the entry's own landing page needs that; without it the
// entry opens on its first child instead, and that child isn't repeated
// under it (Maintenance without Reliafy Maintenance is the RCM studies).
//
// An entry is the current one on any page under its `to` (or `match`); a
// child on its own page and the pages under it, or under any of its `also`
// (a non-repairable model's page is under /models/m, not /models/life).
export const ENTRIES = [
  { id: "home", label: "Home", to: "/home" },

  {
    id: "systems", section: "design", label: "Systems", to: "/systems",
    children: [
      { to: "/systems/runs", label: "Simulation runs" },
      { to: "/systems/structure", label: "Product structure", needs: "maintenance" },
      { to: "/systems/fault-trees", label: "Fault trees", needs: "preview" },
      { to: "/systems/fmeca", label: "FMECA", needs: "preview" },
    ],
  },
  { id: "requirements", section: "design", label: "Requirements", to: "/requirements", needs: "preview" },

  // Assets opens on the assets themselves: the top-level places (a house, a
  // site). Positions is every position, Locations the whole tree of places.
  {
    id: "assets", section: "operate", label: "Assets", to: "/asset-register", needs: "maintenance",
    children: [
      { to: "/asset-register/positions", label: "Positions" },
      { to: "/asset-register/items", label: "Items" },
      { to: "/asset-register/locations", label: "Locations" },
      { to: "/asset-register/parts", label: "Parts and stock" },
      { to: "/asset-register/classes", label: "Classes" },
      { to: "/asset-register/fleets", label: "Fleets", needs: "preview" },
    ],
  },
  {
    id: "maintenance", section: "operate", label: "Maintenance", to: "/maintenance", landingNeeds: "maintenance",
    children: [
      { to: "/maintenance/rcm", label: "RCM studies" },
      { to: "/maintenance/inbox", label: "Field inbox", needs: "preview" },
    ],
  },
  { id: "failures", section: "operate", label: "Failures", to: "/failures", needs: "preview" },
  { id: "risk", section: "operate", label: "Risk", to: "/risk", needs: "preview" },

  {
    id: "data", section: "analyse", label: "Data", to: "/data",
    children: [{ to: "/data/library", label: "Library", needs: "preview" }],
  },
  {
    id: "models", section: "analyse", label: "Model", to: "/models",
    children: [
      { to: "/models/life", label: "Non-repairable", also: ["/models/m", "/models/new"] },
      { to: "/models/recurrent", label: "Repairable" },
      { to: "/models/alt", label: "Accelerated life" },
      { to: "/models/degradation", label: "Degradation" },
      { to: "/models/joint", label: "Condition monitoring" },
      { to: "/models/tracking", label: "Degradation tracking" },
    ],
  },
  {
    id: "strategy", section: "analyse", label: "Strategy", to: "/strategy",
    children: [
      { to: "/strategy/replacement", label: "Optimal replacement" },
      { to: "/strategy/compare", label: "Compare two models" },
      { to: "/strategy/failure-finding", label: "Failure finding" },
      { to: "/strategy/test-planning", label: "Test planning" },
    ],
  },
  { id: "forecasts", section: "analyse", label: "Forecasts", to: "/forecasts" },

  { id: "reports", label: "Reports", to: "/reports" },
  { id: "agent", label: "Reliability Agent", to: "/agent", needs: "agent" },
];

// What people do, and the entries each uses, most used first. The order of a
// user's roles is theirs: the first one picked is the primary role, which Home
// leads with (`home`: its cards, see views/HomePage.jsx). Keep the ids in step
// with ROLE_IDS in backend/services/roles.py (a test checks).
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
    entries: ["maintenance", "assets", "risk", "forecasts", "strategy", "failures", "reports"],
    home: ["due"],
  },
  {
    id: "technician", label: "Technician",
    entries: ["maintenance", "assets"],
    home: ["work-today"],
  },
  {
    // Looks after many items in service (trucks, pumps, aircraft): their
    // forecasts, the items' condition, and what's due on them.
    id: "fleet", label: "Fleet manager",
    entries: ["forecasts", "assets", "risk", "maintenance", "models", "data", "reports"],
    home: ["fleets", "due"],
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

const available = (thing, has, key = "needs") => !thing[key] || Boolean(has[thing[key]]);

// The entries this workspace has, each with the children it has and `to` set
// to where it opens.
export function liveEntries(has = {}) {
  return ENTRIES.filter((e) => available(e, has)).map((e) => {
    let children = (e.children || []).filter((c) => available(c, has));
    let to = e.to;
    if (!available(e, has, "landingNeeds")) {
      if (!children.length) return null;
      to = children[0].to;
      children = children.slice(1);
    }
    const out = { ...e, to, match: e.match || [e.to] };
    if (children.length) out.children = children;
    else delete out.children;
    return out;
  }).filter(Boolean);
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

// Entries grouped for drawing: [{ key, section: {id, label} | null, entries }],
// in the order given (Home and the closing group have no heading).
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
  return [child.to, ...(child.also || [])].some((p) => under(pathname, p));
}

// The entry (from `entries`) a page belongs to, if any. The longest match
// wins, so /maintenance/rcm belongs to Maintenance even if another entry's
// address were a prefix of it.
export function activeEntry(entries, pathname) {
  let best = null;
  let bestLen = -1;
  for (const e of entries) {
    for (const p of e.match || [e.to]) {
      if (under(pathname, p) && p.length > bestLen) {
        best = e;
        bestLen = p.length;
      }
    }
  }
  return best;
}

// The breadcrumbs above a page's title: its entry (unless the page is the
// entry's landing page), then its child (unless it's that child's own page).
// `entries` are the live ones, so a link never points at a page the user
// doesn't have (Maintenance without Reliafy Maintenance opens on RCM studies).
export function crumbsFor(entries, entryId, pathname, childTo = null) {
  const entry = entries.find((e) => e.id === entryId);
  if (!entry || pathname === entry.to) return [];
  const crumbs = [{ label: entry.label, to: entry.to }];
  const child = childTo && (entry.children || []).find((c) => c.to === childTo);
  if (child && pathname !== child.to) crumbs.push({ label: child.label, to: child.to });
  return crumbs;
}

// Where each kind of saved item opens in the app, by its collection.
export const COLLECTION_PATHS = {
  models: "/models/m/",
  recurrent_models: "/models/recurrent/",
  degradation_models: "/models/degradation/",
  alt_models: "/models/alt/",
  datasets: "/data/",
  rbds: "/systems/b/",
  strategy_analyses: "/strategy/analyses/",
  rcm_studies: "/maintenance/rcm/",
  fleets: "/forecasts/",
  tracked_fleets: "/models/tracking/",
};

export function itemPath(collection, id) {
  const base = COLLECTION_PATHS[collection];
  return base ? base + encodeURIComponent(id) : null;
}

// A dataset's page.
export const datasetPath = (id) => itemPath("datasets", id);

// Home's role cards for these roles, in order: the primary role's first, then
// the other roles'. Each card once. No roles: none (Home shows what it always
// has: what changed, what needs attention, recent work).
export function homeCards(roles = []) {
  const out = [];
  for (const r of roles) for (const c of roleById.get(r)?.home || []) if (!out.includes(c)) out.push(c);
  return out;
}
