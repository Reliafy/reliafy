// The app's menu: one flat list with no section headings. Home, the things
// people look after (Assets, Maintenance), two groups of calculations
// (Modelling: Data, Models, System models; Decisions: Strategy, Forecasts,
// Risk), then Reports and the Reliability Agent. One menu for everyone; a
// user's roles are a lens over its top level: the entries their roles use are
// shown, in the menu's own order, and the rest wait under "More" (no roles:
// everything, as before).
//
// Three levels at most: a top-level entry; for a group (Modelling,
// Decisions), its entries; and an entry's children.
//
// Rules the tests hold it to (navigation.test.js):
// - An entry shows only where the workspace has it (`needs`), and never as a
//   placeholder for a page that doesn't exist yet, except where a deployment
//   turns the menu preview on (`needs: "preview"`, see plannedPages.js).
// - A group (`entries`) has no page of its own: it opens on its first live
//   entry, and is left out when none is live. It is never a breadcrumb.
// - An entry opens on its own landing page; its children are sub-types or
//   filtered views of it, never a second copy of the landing page. The one
//   exception is an entry that opens on its first child and lists it
//   (`opensOnFirstChild`): System models opens on RBDs and Risk on Condition
//   monitoring, so the word people click is the page's name.
// - A menu word matches the title of the page it opens.
//
// Everything about roles is in ROLES below, so the menu can change from a
// lens to a per-role structure by changing this file only.
//
// Pure data and functions (no React): the Sidebar draws it, section headers
// take their breadcrumbs from it, Home reads the roles, and the tests check it.
import { ORDERS_PATH, PACKAGES_PATH } from "./maintenanceOrders.js";

// System models' block diagrams: the menu's word, the list page's title
// (so the two agree) and its address. Change them here, in this one place.
export const RBDS_LABEL = "RBDs";
export const RBDS_TITLE = "Reliability block diagrams (RBDs)";
export const RBDS_PATH = "/systems/rbds";
export const SYSTEM_MODELS_LABEL = "System models";
// System models' fault trees built by hand: the menu's word, the list page's title and its address.
export const FAULT_TREES_LABEL = "Fault trees";
export const FAULT_TREES_TITLE = "Fault trees";
export const FAULT_TREES_PATH = "/systems/fault-trees";
export const MODELS_LABEL = "Models";
// Maintenance's sub-pages: the menu's words (each page's title) and addresses.
export const ORDERS_LABEL = "Orders";
export const PACKAGES_LABEL = "Packages";
export { ORDERS_PATH, PACKAGES_PATH };

// The Explorer, Assets' tree pane over the register: its name on the page and
// in breadcrumbs (change it here, in this one place) and its address. It isn't
// in the menu: Assets is one flat entry, current on every /asset-register page;
// an asset on its landing page opens the Explorer on it. Parts and stock and
// Classes are tabs of the tree (the Explorer's panel), not pages.
export const EXPLORER_LABEL = "Explorer";
export const EXPLORER_PATH = "/asset-register/explorer";
// The parts catalogue as structures: an earlier address, now the Parts and
// stock tab's Structure view (redirects.js). It lights Assets.
export const STRUCTURE_PATH = "/systems/structure";

// `needs` names what an entry or child needs: "maintenance" (Reliafy
// Maintenance is on and the user may use it), "agent" (the Reliability Agent
// is on), "risk" (the workspace uses it: it tracks items or has a degradation
// or condition-and-life model; or the menu preview is on), "preview" (the
// deployment shows the menu's not-yet-built entries as blank pages,
// plannedPages.js; nothing else has them, so they stay hidden).
//
// `landingNeeds`: the entry's own landing page needs that; without it the
// entry opens on its first live child instead, and that child isn't repeated
// under it; with no live child either, the entry is left out. (Maintenance
// without Reliafy Maintenance opens on RCM studies.)
//
// An entry is the current one on any page under its `to` (or `match`); the
// longest match wins, so a page under two entries' addresses belongs to the
// more specific one. A child is current on its own page and the pages under
// it, or under any of its `also` (a non-repairable model's page is under
// /models/m, not /models/life).
//
// In the full menu an entry with children (or a group) opens its list in
// place rather than navigating (sidebarMenu.js), so its own landing page,
// when that isn't one of its children (/models, /strategy), isn't in the
// menu: it's reached from breadcrumbs, links and the collapsed rail.
const ASSETS_PATH = "/asset-register";

export const ENTRIES = [
  { id: "home", label: "Home", to: "/home" },

  // Products: the designs (each a functional structure and its part), with
  // the items built from each. One entry, no children.
  { id: "products", label: "Products", to: "/products", needs: "maintenance" },

  // Assets: the places you look after (its landing page), the Explorer (one
  // tree pane over the whole register, with Parts and stock and Classes as
  // tabs), and every position's, location's, item's and part's own page. One
  // entry, no children.
  {
    id: "assets", label: "Assets", to: "/asset-register", needs: "maintenance",
    match: ["/asset-register", STRUCTURE_PATH],
  },

  // Items: every serial-numbered thing, and each item's own page
  // (/asset-register/items/:id wins over Assets by the longest match).
  // (The bare /asset-register/items is an earlier address that redirects; its
  // pages below it are each item's own.)
  { id: "items", label: "Items", to: "/items", needs: "maintenance", match: ["/items", `${ASSETS_PATH}/items`] },

  {
    // Maintenance opens on Orders (/maintenance itself redirects there,
    // redirects.js): the work orders, by tab (Open, Due soon, Closed), then
    // the work packages. Both are Reliafy Maintenance's.
    id: "maintenance", label: "Maintenance", to: ORDERS_PATH, match: ["/maintenance"], landingNeeds: "maintenance",
    opensOnFirstChild: true,
    children: [
      { to: ORDERS_PATH, label: ORDERS_LABEL, needs: "maintenance" },
      { to: PACKAGES_PATH, label: PACKAGES_LABEL, needs: "maintenance" },
      // Standalone RCM worksheets, for every account: without Reliafy
      // Maintenance, "Maintenance" opens on them.
      { to: "/maintenance/rcm", label: "RCM studies" },
      { to: "/maintenance/inbox", label: "Requests", needs: "preview" },
    ],
  },

  {
    id: "modelling", label: "Modelling",
    entries: [
      {
        id: "data", label: "Data", to: "/data",
      },
      {
        id: "models", label: MODELS_LABEL, to: "/models",
        children: [
          { to: "/models/life", label: "Non-repairable", also: ["/models/m", "/models/new"] },
          { to: "/models/recurrent", label: "Repairable" },
          { to: "/models/alt", label: "Accelerated life" },
          { to: "/models/degradation", label: "Degradation" },
          { to: "/models/joint", label: "Condition and life" },
          // Published rates and probabilities with their uncertainty: models, not datasets (9 Nov 2026).
          { to: "/models/library", label: "Library" },
        ],
      },
      // Reliability prediction: a parts count from handbook base rates, for a
      // design with no failure data yet. One entry, no children.
      { id: "prediction", label: "Reliability prediction", to: "/predictions" },
      // Maintainability prediction: Mct, M_max and availability from a parts list's repair times.
      { id: "maintainability", label: "Maintainability prediction", to: "/maintainability" },
      {
        // System models opens on its first child, the RBDs (a diagram's page,
        // under /systems/b, is under it).
        id: "systems", label: SYSTEM_MODELS_LABEL, to: RBDS_PATH, match: ["/systems"], opensOnFirstChild: true,
        children: [
          { to: RBDS_PATH, label: RBDS_LABEL, also: ["/systems/b"] },
          { to: FAULT_TREES_PATH, label: FAULT_TREES_LABEL },
          { to: "/systems/runs", label: "Simulation runs" },
        ],
      },
    ],
  },

  {
    id: "decisions", label: "Decisions",
    entries: [
      {
        id: "strategy", label: "Strategy", to: "/strategy",
        children: [
          { to: "/strategy/replacement", label: "Optimal replacement" },
          { to: "/strategy/compare", label: "Compare two models" },
          { to: "/strategy/failure-finding", label: "Failure finding" },
          { to: "/strategy/test-planning", label: "Test planning" },
        ],
      },
      { id: "forecasts", label: "Forecasts", to: "/forecasts" },
      // Risk: models in use on the items in service. It has no landing page of
      // its own: it opens on Condition monitoring (the tracked items' latest
      // condition, remaining life and alarms) and lists it.
      {
        id: "risk", label: "Risk", to: "/risk", needs: "risk", opensOnFirstChild: true,
        children: [{ to: "/risk", label: "Condition monitoring" }],
      },
    ],
  },

  { id: "reports", label: "Reports", to: "/reports" },
  { id: "agent", label: "Reliability Agent", to: "/agent", needs: "agent" },
];

// Top-level ids a role may name before their entries exist (none now).
export const RESERVED_IDS = [];

// Every entry with a page (no groups), at any level, in menu order.
export const flatEntries = (entries) => entries.flatMap((e) => (e.entries ? flatEntries(e.entries) : [e]));
export const MENU_ENTRIES = flatEntries(ENTRIES).map((e) => ({ ...e, match: e.match || [e.to] }));

// What people do, and the top-level entries each uses. The order of a user's
// roles is theirs: the first one picked is the primary role, which Home leads
// with (`home`: its cards, see views/HomePage.jsx). Keep the ids in step with
// ROLE_IDS in backend/services/roles.py (a test checks).
export const ROLES = [
  {
    id: "analyst", label: "Reliability engineer / analyst",
    entries: ["modelling", "decisions", "reports", "agent"],
    home: ["recent-models", "recent-data"],
  },
  {
    id: "design", label: "Design engineer",
    entries: ["products", "modelling", "decisions", "reports"],
    home: ["recent-systems", "recent-models"],
  },
  {
    id: "planner", label: "Maintenance engineer / planner",
    entries: ["maintenance", "assets", "items", "decisions", "reports"],
    home: ["due"],
  },
  {
    id: "technician", label: "Technician",
    entries: ["maintenance", "assets", "items"],
    home: ["work-today"],
  },
  {
    // Looks after many items in service (trucks, pumps, aircraft): their
    // forecasts, the items' condition, and what's due on them.
    id: "fleet", label: "Fleet manager",
    entries: ["decisions", "assets", "items", "maintenance", "modelling", "reports"],
    home: ["fleets", "due"],
  },
  {
    id: "logistics", label: "Supportability / logistics",
    entries: ["assets", "products", "items", "decisions", "modelling", "reports"],
    home: ["spares", "due"],
  },
  {
    id: "manager", label: "Manager",
    entries: ["reports", "maintenance", "decisions", "modelling"],
    home: ["waiting"],
  },
];

export const ROLE_IDS = ROLES.map((r) => r.id);
const roleById = new Map(ROLES.map((r) => [r.id, r]));

const available = (thing, has, key = "needs") => !thing[key] || Boolean(has[thing[key]]);

// One entry as this workspace has it (null: not at all): its live children,
// `to` set to where it opens and `match` to the addresses it's current on. A
// group keeps its live entries, opens on the first and matches all of theirs.
function liveEntry(e, has) {
  if (!available(e, has)) return null;
  if (e.entries) {
    const entries = e.entries.map((x) => liveEntry(x, has)).filter(Boolean);
    if (!entries.length) return null;
    return { ...e, entries, to: entries[0].to, match: entries.flatMap((x) => x.match) };
  }
  let children = (e.children || []).filter((c) => available(c, has));
  let to = e.to;
  if (!available(e, has, "landingNeeds")) {
    if (!children.length) return null;
    to = children[0].to;
    children = children.slice(1);
  }
  const out = { ...e, to, match: e.match || [e.to] };
  // No landing page of its own for this user: nothing to list under `landingLabel`,
  // and the child it opened on (the landing page) isn't there to open on.
  if (to !== e.to) {
    delete out.landingLabel;
    delete out.opensOnFirstChild;
  }
  if (children.length) out.children = children;
  else delete out.children;
  return out;
}

// The top-level entries this workspace has (groups holding their entries).
export function liveEntries(has = {}) {
  return ENTRIES.map((e) => liveEntry(e, has)).filter(Boolean);
}

// The menu for a user with `roles` (role ids, primary first) in a workspace
// that `has` features: `main`, the top-level entries shown, and `more`, the
// rest (under "More"). Home is always shown. Both keep the menu's own order:
// with no section headings, the menu reads the same for everyone and a role
// only hides what it doesn't use.
export function buildMenu({ roles = [], has = {} } = {}) {
  const live = liveEntries(has);
  const picked = roles.filter((r) => roleById.has(r));
  if (!picked.length) return { main: live, more: [] };
  const usedIds = new Set(picked.flatMap((r) => roleById.get(r).entries));
  const used = (e) => e.id === "home" || usedIds.has(e.id);
  return { main: live.filter(used), more: live.filter((e) => !used(e)) };
}

const under = (pathname, prefix) => pathname === prefix || pathname.startsWith(prefix + "/");

// Whether the page at `pathname` is under `entry`'s addresses (for a group,
// under any of its entries').
export function entryActive(entry, pathname) {
  return (entry.match || [entry.to]).some((p) => under(pathname, p));
}

export function childActive(child, pathname) {
  return [child.to, ...(child.also || [])].some((p) => under(pathname, p));
}

// The entry (from `entries`, one level) a page belongs to, if any. The longest
// match wins, so /systems/structure belongs to Assets, not Modelling (whose
// System models has /systems).
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

// Where a page sits in the menu: its top-level entry, the group's entry when
// that is a group, and the child it's under ({ top, entry, child }, each null
// when there's none).
export function activeTrail(entries, pathname) {
  const top = activeEntry(entries, pathname);
  const entry = top?.entries ? activeEntry(top.entries, pathname) : top;
  const child = (entry?.children || []).find((c) => childActive(c, pathname)) || null;
  return { top, entry, child };
}

// The breadcrumbs above a page's title: its entry (unless the page is the
// entry's landing page), then its child (unless it's that child's own page).
// Never a group: a repairable model's page reads "Models › Repairable".
// `entries` are the live ones, so a link never points at a page the user
// doesn't have (an entry that opens on its first child links to that child).
export function crumbsFor(entries, entryId, pathname, childTo = null) {
  const entry = flatEntries(entries).find((e) => e.id === entryId);
  if (!entry || pathname === entry.to) return [];
  // The child it opens on, when the page is that child's (a sibling's page, such as
  // Maintenance › Packages, is under the entry, not under the child it opens on).
  const first = entry.children?.[0];
  const opensOn = entry.opensOnFirstChild && first?.to === entry.to && childActive(first, pathname) ? first : null;
  const child = (childTo && (entry.children || []).find((c) => c.to === childTo)) || (!childTo && opensOn) || null;
  // An entry that opens on this child: the child's crumb alone (RBDs, not System models › RBDs).
  if (child && child.to === entry.to) return [{ label: child.label, to: child.to }];
  const crumbs = [{ label: entry.label, to: entry.to }];
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
  maintainability_predictions: "/maintainability/",
  fleets: "/forecasts/",
  tracked_fleets: "/risk/",
  reliability_predictions: "/predictions/",
  libraries: "/models/library/",
  rcm_studies: "/maintenance/rcm/",
};

export function itemPath(collection, id) {
  const base = COLLECTION_PATHS[collection];
  return base ? base + encodeURIComponent(id) : null;
}

// A dataset's page.
export const datasetPath = (id) => itemPath("datasets", id);

// What the app uses of a user's saved roles. Where the deployment turns the
// roles on (MENU_ROLES, from /api/config as `menu_roles`): the roles, and
// `offer`, whether to ask a new user once. Off (the default): no roles and no
// question, so the menu is the full list, Home has no role cards and Settings
// no picker; roles already saved stay on the profile, unused.
export function rolesInUse({ roles = [], offer = false } = {}, on = false) {
  return on ? { roles, offer: !!offer, rolesOn: true } : { roles: [], offer: false, rolesOn: false };
}

// Home's role cards for these roles, in order: the primary role's first, then
// the other roles'. Each card once. No roles: none (Home shows what it always
// has: what changed, what needs attention, recent work).
export function homeCards(roles = []) {
  const out = [];
  for (const r of roles) for (const c of roleById.get(r)?.home || []) if (!out.includes(c)) out.push(c);
  return out;
}
