// Earlier addresses of the app's pages, and where each one lives now.
//
// The menu moved to Design · Operate · Analyse: Modelling became Models and
// Data, RBDs became Systems, Fleet became Forecasts (its degradation tracking
// moved to Models, then to Operate › Risk as Condition monitoring), RCM moved
// under Maintenance, and Reliafy Maintenance's register moved to Assets. Links saved before then (emails, share notices,
// bookmarks, API and MCP results, guides and posts) must keep working, so
// every old address redirects to its page's new one with the same ids, query
// and #hash (AppShell.jsx draws a route for each row).
//
// Pure data: AppShell.jsx, navigation.test.js, the smoke suite
// (smoke/routes.js) and the server's list of app roots
// (backend/tests/test_spa_routes.py) all read it.
//
// A `:name` in `to` takes the value of the same `:name` in `path`.
export const MOVED = [
  // Modelling → Analyse › Models and Analyse › Data.
  { path: "/modelling", to: "/models" },
  { path: "/modelling/models", to: "/models" },
  { path: "/modelling/data", to: "/data" },
  { path: "/modelling/data/:id", to: "/data/:id" },
  { path: "/modelling/life", to: "/models/life" },
  { path: "/modelling/new", to: "/models/new" },
  { path: "/modelling/m/:id", to: "/models/m/:id" },
  { path: "/modelling/degradation", to: "/models/degradation" },
  { path: "/modelling/degradation/:id", to: "/models/degradation/:id" },
  { path: "/modelling/recurrent", to: "/models/recurrent" },
  { path: "/modelling/recurrent/new", to: "/models/recurrent/new" },
  { path: "/modelling/recurrent/:id", to: "/models/recurrent/:id" },
  { path: "/modelling/alt", to: "/models/alt" },
  { path: "/modelling/alt/new", to: "/models/alt/new" },
  { path: "/modelling/alt/:id", to: "/models/alt/:id" },
  { path: "/modelling/joint", to: "/models/joint" },
  { path: "/modelling/joint/new", to: "/models/joint/new" },
  { path: "/modelling/joint/:id", to: "/models/joint/:id" },
  // Datasets (before they moved into Modelling) → Analyse › Data.
  { path: "/datasets", to: "/data" },
  { path: "/datasets/list", to: "/data" },
  { path: "/datasets/d/:id", to: "/data/:id" },
  // RBDs → Design › Systems.
  { path: "/rbds", to: "/systems/rbds" },
  { path: "/rbds/list", to: "/systems/rbds" },
  { path: "/rbds/b", to: "/systems/b" },
  { path: "/rbds/b/:id", to: "/systems/b/:id" },
  { path: "/rbds/runs", to: "/systems/runs" },
  { path: "/rbds/runs/compare", to: "/systems/runs/compare" },
  { path: "/rbds/runs/:runId", to: "/systems/runs/:runId" },
  // Fleet → Analyse › Forecasts; its degradation tracking → Operate › Risk.
  { path: "/fleet", to: "/forecasts" },
  { path: "/fleet/forecasts", to: "/forecasts" },
  { path: "/fleet/forecasts/:id", to: "/forecasts/:id" },
  { path: "/fleet/tracking", to: "/risk" },
  { path: "/fleet/tracking/:fleetId", to: "/risk/:fleetId" },
  // Degradation tracking, once a child of Model → Operate › Risk:
  // the tracked items are a model in use, now Condition monitoring.
  { path: "/models/tracking", to: "/risk" },
  { path: "/models/tracking/:fleetId", to: "/risk/:fleetId" },
  // Older Strategy addresses. Tracking bookmarks carried a MODEL id, and
  // fleets have their own ids now, so they open the tracking list.
  { path: "/strategy/analyses", to: "/strategy" },
  { path: "/strategy/tracking", to: "/risk" },
  { path: "/strategy/tracking/:modelId", to: "/risk" },
  // The Demonstration test page is Test planning's first tab.
  { path: "/strategy/demonstration-test", to: "/strategy/test-planning" },
  // RCM → Operate › Maintenance › RCM studies.
  { path: "/rcm", to: "/maintenance/rcm" },
  { path: "/rcm/studies", to: "/maintenance/rcm" },
  { path: "/rcm/studies/:id", to: "/maintenance/rcm/:id" },
  // Reliafy Maintenance's register → Operate › Assets. (/maintenance itself
  // stays: it's the due tasks and work orders now; the positions tree is
  // Assets › Explorer, and Assets opens on the top-level places.)
  { path: "/maintenance/positions/:id", to: "/asset-register/positions/:id" },
  { path: "/maintenance/items", to: "/asset-register/explorer?arrange=items" },
  { path: "/maintenance/items/:id", to: "/asset-register/items/:id" },
  { path: "/maintenance/locations", to: "/asset-register/explorer?arrange=locations" },
  { path: "/maintenance/locations/:id", to: "/asset-register/locations/:id" },
  { path: "/maintenance/classes", to: "/asset-register/classes" },
  { path: "/maintenance/classes/:name", to: "/asset-register/classes/:name" },
  { path: "/maintenance/parts", to: "/asset-register/parts" },
  { path: "/maintenance/parts/:id", to: "/asset-register/parts/:id" },
  // Design › Systems opens on its RBDs, the list of diagrams, at their own address.
  { path: "/systems", to: "/systems/rbds" },
  // Assets › Positions, Items and Locations → one page, Assets › Explorer,
  // arranged by each (their ?place=, ?sel= and ?arrange=flat come along).
  // Each one's own pages (/asset-register/positions/:id and so on) stay.
  { path: "/asset-register/positions", to: "/asset-register/explorer?arrange=positions" },
  { path: "/asset-register/items", to: "/asset-register/explorer?arrange=items" },
  { path: "/asset-register/locations", to: "/asset-register/explorer?arrange=locations" },
];

// Where an old address goes: `pathname` (no query or hash) matched against
// MOVED, with its ids carried over; null when it hasn't moved.
export function movedTo(pathname) {
  const parts = pathname.replace(/\/+$/, "").split("/");
  for (const m of MOVED) {
    const pattern = m.path.split("/");
    if (pattern.length !== parts.length) continue;
    const params = {};
    const fits = pattern.every((seg, i) => {
      if (!seg.startsWith(":")) return seg === parts[i];
      params[seg.slice(1)] = parts[i];
      return parts[i] !== "";
    });
    if (fits) return fillMoved(m.to, params);
  }
  return null;
}

// `to` with each `:name` replaced by its (already URL-encoded) value.
export function fillMoved(to, params) {
  return to.replace(/:(\w+)/g, (_, name) => params[name] ?? "");
}

// Where an old address lands with its own query (`search`, "?a=1" or "") and
// #hash: `to`'s query first, then the old address's other keys, so
// /asset-register/positions?arrange=flat&sel=p1 lands arranged flat (the old
// Positions page's own arrangement) with p1 picked, and
// /asset-register/locations?sel=l1 arranged by locations with l1 picked.
// A `to` with no query keeps the old query exactly as it was.
export function movedHref(to, search = "", hash = "") {
  const [path, own] = to.split("?");
  if (!own) return to + search + hash;
  const q = new URLSearchParams(own);
  const old = new URLSearchParams(search);
  // The old Positions page's ?arrange=flat was its own arrangement: it wins.
  if (old.get("arrange") === "flat" && q.get("arrange") === "positions") q.set("arrange", "flat");
  for (const [k, v] of old) if (!q.has(k)) q.append(k, v);
  return `${path}?${q}${hash}`;
}
