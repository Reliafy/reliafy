// The main feature pages, each of which must be linked from at least one
// how-to guide (frontend/src/content/guides/*.md), in its body or as its
// `related_href`. guideChecks.test.js fails for any entry no guide links to.
//
// Why: guides fell behind the app when features shipped without one. When a
// release adds or moves a main page, add it here; the test then says which
// page needs a guide until one links to it. Keep it to pages a user would
// look for help on, not every route (detail pages, settings tabs, redirects).
// Maintenance is operators-only for now, so it stays off this list.
//
// `href` is a path the router knows (checked too); a query string on it must
// appear on the guide's link (a mode such as ?mode=calendar).
export const GUIDE_COVERAGE = [
  // Where the app opens.
  { feature: "Home", href: "/home" },
  // Life data and the other model types.
  { feature: "Fit a life model (life data)", href: "/modelling/new" },
  { feature: "Repeat failures (repairable systems)", href: "/modelling/recurrent" },
  { feature: "Accelerated life models", href: "/modelling/alt" },
  { feature: "Degradation models", href: "/modelling/degradation" },
  { feature: "Condition monitoring (remaining life from readings)", href: "/modelling/joint" },
  { feature: "Per-demand (one-shot) models", href: "/modelling/new?mode=perdemand" },
  // Data.
  { feature: "Data (datasets)", href: "/modelling/data" },
  // System modelling.
  { feature: "Reliability block diagrams", href: "/rbds" },
  { feature: "RBD builder (targets, design, phases, production, outages)", href: "/rbds/b" },
  { feature: "Simulation run history", href: "/rbds/runs" },
  // Strategy.
  { feature: "Saved strategy analyses", href: "/strategy" },
  { feature: "Optimal replacement by age", href: "/strategy/replacement" },
  { feature: "Replacement over a shutdown calendar", href: "/strategy/replacement?mode=calendar" },
  { feature: "Compare two models", href: "/strategy/compare" },
  { feature: "Failure-finding interval", href: "/strategy/failure-finding" },
  { feature: "Test planning", href: "/strategy/test-planning" },
  { feature: "Test planning: sequential test", href: "/strategy/test-planning/sequential" },
  { feature: "Test planning: life test precision", href: "/strategy/test-planning/life" },
  { feature: "Test planning: accelerated test", href: "/strategy/test-planning/accelerated" },
  { feature: "Test planning: comparison", href: "/strategy/test-planning/comparison" },
  // Fleets.
  { feature: "Fleet failure and spares forecasts", href: "/fleet" },
  { feature: "Degradation tracking", href: "/fleet/tracking" },
  // RCM.
  { feature: "RCM studies", href: "/rcm" },
  // Sharing and teams.
  { feature: "Teams", href: "/team" },
  { feature: "What changed in the workspace", href: "/changes" },
  // Agents, MCP and the API.
  { feature: "Reliability Agent", href: "/agent" },
  { feature: "Claude (MCP) connector", href: "/api-docs/mcp" },
  { feature: "API tokens", href: "/settings?tab=api" },
  { feature: "API reference", href: "/api-docs" },
  { feature: "Command line", href: "/api-docs/cli" },
];
