// The app's menu: each section, its landing page, and its children.
//
// The rule (#nav): a section opens on its own full list (or, for
// Maintenance, its overview); its children are filtered views or sub-types
// of it, never a second copy of the landing page. A child page shows its
// section's label above its title; a landing page doesn't.
//
// `gate` names the condition a section needs (Sidebar decides it from
// /api/config and, for Maintenance, the operator check).

export const NAV = [
  { key: "home", to: "/home", label: "Home" },
  {
    key: "modelling",
    to: "/modelling",
    label: "Modelling",
    children: [
      { to: "/modelling/data", label: "Data" },
      // A non-repairable model's own page and the fit flow sit outside its list's URL.
      { to: "/modelling/life", label: "Non-repairable models", also: ["/modelling/m", "/modelling/new"] },
      { to: "/modelling/recurrent", label: "Repairable models" },
      { to: "/modelling/alt", label: "Accelerated life" },
      { to: "/modelling/degradation", label: "Degradation" },
      { to: "/modelling/joint", label: "Condition monitoring" },
    ],
  },
  { key: "rbds", to: "/rbds", label: "RBDs" },
  {
    key: "strategy",
    to: "/strategy",
    label: "Strategy",
    children: [
      { to: "/strategy/replacement", label: "Optimal replacement" },
      { to: "/strategy/compare", label: "Compare two models" },
      { to: "/strategy/failure-finding", label: "Failure finding" },
      { to: "/strategy/test-planning", label: "Test planning" },
    ],
  },
  {
    key: "fleet",
    to: "/fleet",
    label: "Fleet",
    children: [{ to: "/fleet/tracking", label: "Degradation tracking" }],
  },
  { key: "rcm", to: "/rcm", label: "RCM" },
  {
    key: "maintenance",
    to: "/maintenance",
    label: "Maintenance",
    gate: "maintenance",
    children: [
      { to: "/maintenance/items", label: "Items" },
      { to: "/maintenance/locations", label: "Locations" },
      { to: "/maintenance/parts", label: "Parts" },
      { to: "/maintenance/classes", label: "Classes" },
    ],
  },
  { key: "agent", to: "/agent", label: "Reliability Agent", gate: "agent" },
];

// Each section's label and landing page, by key (a child page's header
// shows its section from here).
export const SECTIONS = Object.fromEntries(NAV.map((s) => [s.key, { label: s.label, to: s.to }]));

const under = (pathname, to) => pathname === to || pathname.startsWith(to + "/");

// Which menu entry is current for ``pathname``: { section, child } (keys and
// paths), or nulls. A child wins when the page is it or under it; otherwise
// the section, on its landing page and on any detail page under it.
export function activeNav(pathname, nav = NAV) {
  for (const s of nav) {
    const child = (s.children || []).find((c) => [c.to, ...(c.also || [])].some((p) => under(pathname, p)));
    if (child) return { section: s.key, child: child.to };
    if (under(pathname, s.to)) return { section: s.key, child: null };
  }
  return { section: null, child: null };
}

// A dataset's page (Datasets moved into Modelling as "Data"; the old
// /datasets/d/<id> links redirect here).
export const datasetPath = (id) => `/modelling/data/${encodeURIComponent(id)}`;
