// Every app page's browser-tab title, so tabs, history and bookmarks can be
// told apart: the page (or the record's name), then where it sits in the
// menu, then "Reliafy": "Feed pump train · RBDs · Reliafy".
//
// The menu part comes from the menu's entries (navigation.js; a group such as
// Modelling is never named), so a renamed menu entry
// renames its tabs too; pages outside the menu are named in PAGES below. A
// detail page adds its record's name with usePageTitle
// (components/usePageTitle.js).
import { EXPLORER_LABEL, EXPLORER_PATH, MENU_ENTRIES, STRUCTURE_PATH, childActive, entryActive } from "./navigation.js";
import { TEST_PLAN_TABS } from "./testPlanning.js";
import { API_DOCS_PAGES } from "./apiDocsPages.js";

export const APP_NAME = "Reliafy";

// "A", "B", "B", "" -> "A · B · Reliafy": blanks and repeats dropped.
export function formatTitle(...parts) {
  const out = [];
  for (const p of parts) {
    const s = typeof p === "string" ? p.trim() : "";
    if (s && out[out.length - 1] !== s) out.push(s);
  }
  if (out[out.length - 1] !== APP_NAME) out.push(APP_NAME);
  return out.join(" · ");
}

// Pages the menu doesn't name, by exact path (or a pattern for one with a
// parameter): the words that go before the menu part.
const PAGES = [
  ["/models/new", "New model"],
  ["/models/recurrent/new", "New model"],
  ["/models/alt/new", "New model"],
  ["/models/joint/new", "New model"],
  ["/maintainability/new", "New prediction"],
  ["/systems/b", "New diagram"],
  // Assets' pages (one menu entry, no children): the Explorer, and each
  // position's, location's and item's page under it; Parts and stock, Classes.
  [EXPLORER_PATH, EXPLORER_LABEL],
  [/^\/asset-register\/(positions|locations)\/[^/]+(\/.*)?$/, EXPLORER_LABEL],
  [/^\/asset-register\/parts(\/[^/]+)?$/, "Parts and stock"],
  [/^\/asset-register\/classes(\/[^/]+)?$/, "Classes"],
  [STRUCTURE_PATH, "Product structure"],
  // Preview-only placeholders with no place in the menu (plannedPages.js).
  ["/requirements", "Requirements"],
  ["/failures", "Failures"],
  ["/asset-register/fleets", "Fleets"],
  ["/systems/runs/compare", "Compare runs"],
  [/^\/systems\/runs\/[^/]+$/, "Run"],
  ...TEST_PLAN_TABS.filter((t) => t.id !== "demonstration").map((t) => [t.path, t.label]),
  ["/data-model", "Data model"],
  ["/settings", "Settings"],
  ["/team", "Team"],
  ["/billing", "Billing"],
  ["/admin", "Admin"],
  ["/changes", "What changed"],
  ...API_DOCS_PAGES.map((p) => [p.slug ? `/api-docs/${p.slug}` : "/api-docs", p.slug ? [p.label, "API docs"] : "API docs"]),
];

// The menu entry a page is under: the longest match wins (as in activeEntry).
function entryFor(path) {
  let best = null;
  let bestLen = -1;
  for (const e of MENU_ENTRIES) {
    for (const p of e.match || [e.to]) {
      if ((path === p || path.startsWith(p + "/")) && p.length > bestLen && entryActive(e, path)) {
        best = e;
        bestLen = p.length;
      }
    }
  }
  return best;
}

// The parts after the record's name for ``pathname``: [page?, child?, entry?].
// An entry that opens on a child (System models on RBDs, Risk on Condition
// monitoring) is named by that child alone, as its breadcrumbs are.
export function titleParts(pathname) {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const page = PAGES.find(([p]) => (typeof p === "string" ? p === path : p.test(path)));
  const parts = page ? [].concat(page[1]) : [];
  const entry = entryFor(path);
  if (!entry) return parts;
  const child = (entry.children || []).find((c) => childActive(c, path));
  if (!child) return [...parts, entry.label];
  if (child.to === entry.to) return [...parts, child.label];
  return [...parts, child.label, entry.label];
}

// The full title: the record's name (when given) first.
export function titleFor(pathname, name = null) {
  return formatTitle(name, ...titleParts(pathname));
}
