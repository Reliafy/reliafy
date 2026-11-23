// The one search for everything (the header's search box and ⌘K / Ctrl-K; GlobalSearch.jsx).
// The records come from the server (GET /api/search: the register, data, models, diagrams,
// saved analyses, reports, libraries), ranked there. The app's own pages and Explorer tabs
// (with plain synonyms, so "test planning" or "spares" lands on the capability) and the how-to
// guides are part of the bundle, so they're searched here, ranked the same way: exact, then
// starts with, then whole words, then inside, then a near spelling (backend/services/global_search.py).
//
// The pages come from the live menu (navigation.js: what this workspace has), the account pages
// the router has, Test planning's tabs (testPlanning.js) and the Explorer's tabs on offer
// (explorerTabs.js), so a page added there is found without touching this file; SYNONYMS adds
// the words people use for them.
//
// Pure functions (no React), tested in globalSearch.test.js.
import { filterGuideGroups } from "./guideFilter.js";
import { flatEntries } from "./navigation.js";
import { OFFERED_TABS } from "./explorerTabs.js";
import { explorerPath } from "./assetTree.js";
import { TEST_PLAN_TABS, TEST_PLANNING_PATH } from "./testPlanning.js";
import { formatDate } from "./dates.js";

// ---- ranking (the server's, word for word) --------------------------------------------------

const SPLIT = /[\s›/,;:()[\]·|]+/;
const norm = (t) => String(t ?? "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
export const queryWords = (q) => norm(q).split(SPLIT).filter(Boolean).slice(0, 8);

function distance(a, b, most) {
  let prev2 = [];
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i += 1) {
    const cur = [i];
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) cur[j] = Math.min(cur[j], prev2[j - 2] + 1);
    }
    if (Math.min(...cur) > most) return most + 1;
    prev2 = prev;
    prev = cur;
  }
  return prev[b.length];
}

// Whether `b` (or its start, a word still being typed) is a small typo away from `a`. Never for
// a short word or a code (a word with a digit: a tag, a serial, a part number).
// The first letter must match (or be swapped with the second): "mower" isn't "lower".
export function near(a, b) {
  if (a.length < 4 || !b || /\d/.test(a)) return false;
  if (a[0] !== b[0] && !(b.length > 1 && a[0] === b[1] && a[1] === b[0])) return false;
  const most = a.length <= 7 ? 1 : 2;
  return [b, b.slice(0, a.length), b.slice(0, a.length + 1)]
    .some((c) => Math.abs(c.length - a.length) <= most && distance(a, c, most) <= most);
}

// How well a record matches: 0 exact key, 1 a key starts with it, 2 every word starts a word,
// 3 every word inside, 4 near spellings; null for no match.
export function matchTier(q, keys = [], extra = []) {
  const whole = norm(q).slice(0, 200);
  const words = queryWords(q);
  const ks = keys.filter(Boolean).map(norm);
  const text = [...ks, ...extra.filter(Boolean).map(norm)].join(" ");
  if (!words.length || !text) return null;
  if (ks.includes(whole)) return 0;
  if (ks.some((k) => k.startsWith(whole))) return 1;
  const tw = text.split(SPLIT).filter(Boolean);
  if (words.every((w) => tw.some((t) => t.startsWith(w)))) return 2;
  const missing = words.filter((w) => !text.includes(w));
  if (!missing.length) return 3;
  if (missing.every((w) => tw.some((t) => near(w, t)))) return 4;
  return null;
}

const byTier = (a, b) => a.tier - b.tier;

// ---- the app's pages and tabs ---------------------------------------------------------------

// The words people use for a page or a tab (keyed by its address, or "tab:<id>" for an Explorer
// tab), beyond its own name.
export const SYNONYMS = {
  "/home": ["dashboard", "start"],
  "/products": ["designs", "bom", "bom import", "import a bom", "bill of materials", "parts list", "parts"],
  "/asset-register": ["asset register", "sites", "equipment", "hierarchy", "register", "explorer"],
  "/maintenance/work-orders": ["work orders", "jobs", "due work", "overdue"],
  "/maintenance/packages": ["work packages", "maintenance plan", "planned maintenance", "pm"],
  "/maintenance/rcm": ["rcm", "reliability centred maintenance", "reliability centered maintenance", "maintenance strategy"],
  "/data": ["datasets", "upload", "csv", "excel", "import data", "life data"],
  "/models": ["all models", "fit"],
  "/models/life": ["non-repairable models", "life models", "weibull", "fit a distribution", "b10", "b-life"],
  "/models/recurrent": ["repairable models", "recurrent", "crow-amsaa", "reliability growth", "mcf", "repeat failures"],
  "/models/alt": ["accelerated life testing", "alt", "stress", "arrhenius"],
  "/models/degradation": ["degradation", "wear", "p-f"],
  "/models/joint": ["condition and life", "joint model", "condition monitoring", "readings and failures"],
  "/predictions": ["parts count", "handbook", "217f", "failure rate prediction", "mtbf"],
  "/maintainability": ["mttr", "repair time", "availability"],
  "/systems/rbds": ["rbd", "reliability block diagram", "availability", "system reliability", "redundancy", "missions", "phases"],
  "/systems/fault-trees": ["fault tree", "fta", "top event", "cut sets"],
  "/systems/runs": ["simulation", "monte carlo", "simulation runs"],
  "/libraries": ["library", "handbooks", "generic failure rates", "published rates"],
  "/strategy": ["saved analyses", "decisions"],
  "/strategy/replacement": ["preventive replacement", "replacement interval", "age replacement", "pm interval"],
  "/strategy/compare": ["compare models"],
  "/strategy/failure-finding": ["hidden failures", "proof test", "test interval"],
  "/strategy/overhaul-replace": ["overhaul"],
  [TEST_PLANNING_PATH]: ["test planning", "test plan", "demonstration test", "zero-failure test", "success run",
    "sample size", "reliability test"],
  "/forecasts": ["fleet forecast", "forecast", "spares", "spare parts", "demand", "how many failures"],
  "/risk": ["condition monitoring", "remaining life", "rul", "alarms", "tracked items"],
  "/reports": ["report", "share", "export"],
  "/agent": ["ai", "assistant", "chat"],
  "/settings?tab=api": ["api keys", "api key", "tokens", "access token"],
  "/settings?tab=apps": ["oauth", "claude", "mcp connection"],
  "/api-docs": ["api", "rest", "developer"],
  "/api-docs/cli": ["cli", "command line"],
  "/api-docs/mcp": ["mcp", "claude", "agent tools"],
  "/changes": ["history", "activity", "audit"],
  "tab:rcm": ["rcm", "failure modes", "functions", "decisions"],
  "tab:fmea": ["fmea", "fmeca", "criticality", "rpn", "failure modes"],
  "tab:maintenance": ["maintenance tasks", "tasks", "pm", "work packages", "packages", "lsa", "logistic support analysis", "consumables", "spares for the year", "maintenance forecast"],
  "tab:reports": ["failures", "defects", "failure reports"],
  "tab:models": ["life models", "modelling"],
  "tab:missions": ["missions", "mission", "phases", "sortie", "what if"],
  "tab:condition": ["condition monitoring", "risk", "alarms", "remaining life"],
  "tab:forecast": ["fleet forecast", "forecast"],
  "tab:spares": ["spares", "spare parts", "stock"],
  "tab:measurements": ["readings", "meters", "sensors", "measuring points"],
  "tab:lsa": ["lsa", "logistic support analysis", "logistics", "supportability", "consumables"],
  "tab:parts": ["parts", "stock", "inventory"],
  "tab:classes": ["classes", "taxonomy"],
};

// The account and help pages the router has beyond the menu, with the condition each needs.
const OTHER_PAGES = [
  { label: "Settings", path: "/settings" },
  { label: "API access", path: "/settings?tab=api", context: "Settings" },
  { label: "Connected apps", path: "/settings?tab=apps", context: "Settings" },
  { label: "API docs", path: "/api-docs" },
  { label: "Command line (CLI)", path: "/api-docs/cli", context: "API docs" },
  { label: "Python client", path: "/api-docs/python", context: "API docs" },
  { label: "MCP server", path: "/api-docs/mcp", context: "API docs" },
  { label: "What changed", path: "/changes" },
  { label: "Plan and billing", path: "/billing", needs: "billing" },
  { label: "Team settings", path: "/team", needs: "team" },
  { label: "Data model", path: "/data-model", needs: "dataModel" },
];

// Every page and tab this viewer can open, as search entries {id, label, path, context, words,
// tab?}. `live`: the live menu (navigation.js liveEntries / useRoles().live); `has` its needs;
// `billing`, `team`: the deployment has billing, a team workspace is open.
export function featureList({ live = [], has = {}, billing = false, team = false } = {}) {
  const out = [];
  const seen = new Map();
  const add = (f) => {
    const before = seen.get(f.path);
    if (before) {
      before.words.push(f.label, ...(f.words || []));
      return;
    }
    const entry = { kind: "feature", id: f.path, context: "Page", ...f, words: [...(SYNONYMS[f.path] || []), ...(f.words || [])] };
    seen.set(f.path, entry);
    out.push(entry);
  };
  for (const top of live) {
    const group = top.entries ? top.label : null;
    for (const e of top.entries ? flatEntries(top.entries) : [top]) {
      const where = group ? `${group} › ${e.label}` : e.label;
      // An entry that opens on its first child is that child's page: one entry, both names.
      if (e.opensOnFirstChild && e.children?.[0]?.to === e.to) {
        add({ label: e.children[0].label, path: e.to, context: group ? `Page in ${group}` : "Page", words: [e.label] });
      } else {
        add({ label: e.label, path: e.to, context: group ? `Page in ${group}` : "Page" });
      }
      for (const c of e.children || []) add({ label: c.label, path: c.to, context: `Page in ${where}` });
    }
  }
  if (seen.has("/strategy")) {
    for (const t of TEST_PLAN_TABS.slice(1)) {
      add({ label: t.label, path: t.path, context: "Strategy › Test planning", words: ["test planning", "test plan"] });
    }
  }
  const ok = { billing, team, dataModel: !!(has.graph && has.preview) };
  for (const p of OTHER_PAGES) if (!p.needs || ok[p.needs]) add({ ...p, context: p.context ? `Page in ${p.context}` : "Page" });
  if (has.maintenance) {
    for (const t of OFFERED_TABS) {
      if (t.id === "summary") continue;
      const arrange = t.kinds.includes("pos") ? "positions" : "classes";
      out.push({
        kind: "feature", id: `tab:${t.id}`, label: t.label, tab: t.id, path: explorerPath(arrange, { tab: t.id }),
        context: "Tab in the Explorer, on an asset", words: [...(SYNONYMS[`tab:${t.id}`] || [])], about: t.title,
      });
    }
  }
  return out;
}

// The pages and tabs matching `q`, best first (a tie keeps the menu's order).
export function searchFeatures(features, q, limit = 5) {
  const hits = [];
  features.forEach((f, i) => {
    const tier = matchTier(q, [f.label, ...(f.words || [])], [f.context, f.about]);
    // On a tie, a page named so beats one that only has it among its other words.
    if (tier != null) hits.push({ ...f, name: f.label, tier, i, named: matchTier(q, [f.label]) === tier ? 0 : 1 });
  });
  hits.sort((a, b) => a.tier - b.tier || a.named - b.named || a.i - b.i);
  return { kind: "feature", label: "Pages and tabs", total: hits.length, results: hits.slice(0, limit) };
}

// Where a tab's entry opens from where you are: on the asset open in the Explorer now (its ?root=
// and row kept), else the Explorer's address with the tab, which asks which asset to open it on.
export function featureHref(feature, pathname = "", search = "") {
  if (!feature.tab || pathname !== "/asset-register/explorer") return feature.path;
  const here = new URLSearchParams(search);
  if (!here.get("root")) return feature.path;
  here.set("tab", feature.tab);
  return `${pathname}?${here}`;
}

// ---- the guides -----------------------------------------------------------------------------

// The how-to guides matching `q` (guideFilter.js's match: every word in the title, task or
// text), plus near spellings of a title's words; those named in their title first.
export function searchGuides(guides, q, limit = 4) {
  const matched = filterGuideGroups([{ category: "", items: guides }], q)[0]?.items || [];
  const inFilter = new Set(matched.map((g) => g.slug));
  const hits = [];
  guides.forEach((g, i) => {
    let tier = matchTier(q, [g.title], [g.task]);
    if (tier == null && inFilter.has(g.slug)) tier = 3;
    if (tier != null) {
      hits.push({ kind: "guide", id: g.slug, slug: g.slug, name: g.title, context: g.task || "Guide", tier, i,
        body: !inFilter.has(g.slug) || matchTier(q, [g.title], [g.task]) == null });
    }
  });
  hits.sort((a, b) => a.tier - b.tier || Number(a.body) - Number(b.body) || a.i - b.i);
  return { kind: "guide", label: "Guides", total: hits.length, results: hits.slice(0, limit) };
}

// ---- the panel ------------------------------------------------------------------------------

// The server's groups and the pages' and guides' as one list: the group with the best match
// first; on a tie, records, then pages and tabs, then guides. Empty groups drop out.
// Near spellings (tier 4) only when nothing matches as typed: a real match never sits beside
// near-misses.
export function mergeGroups(server = [], features = null, guides = null) {
  let all = [...server, features, guides].filter((g) => g && g.results?.length);
  if (all.some((g) => g.results.some((r) => (r.tier ?? 9) < 4))) {
    all = all.map((g) => {
      const results = g.results.filter((r) => r.tier !== 4);
      return { ...g, results, total: Math.max(results.length, (g.total ?? g.results.length) - (g.results.length - results.length)) };
    }).filter((g) => g.results.length);
  }
  return all
    .map((g, i) => ({ g, i, best: Math.min(...g.results.map((r) => r.tier ?? 9)) }))
    .sort((a, b) => a.best - b.best || a.i - b.i)
    .map(({ g }) => ({ ...g, results: [...g.results].sort(byTier) }));
}

// Every result in panel order, each with its group's index ({group, result, index}).
export function flatResults(groups) {
  const out = [];
  groups.forEach((g, gi) => g.results.forEach((r) => out.push({ group: gi, result: r, index: out.length })));
  return out;
}

// The keyboard on the results (focus stays in the box): ↑ ↓ go one at a time and wrap; Tab and
// Shift+Tab jump to the first result of the next or the previous group. Null: not ours (the key
// does what it always does, so Tab past the last group leaves the box).
export function moveActive(groups, active, key, shift = false) {
  const flat = flatResults(groups);
  if (!flat.length) return null;
  const at = Math.min(Math.max(active ?? 0, 0), flat.length - 1);
  if (key === "ArrowDown") return (at + 1) % flat.length;
  if (key === "ArrowUp") return (at - 1 + flat.length) % flat.length;
  if (key === "Home") return 0;
  if (key === "End") return flat.length - 1;
  if (key === "Tab") {
    const g = flat[at].group + (shift ? -1 : 1);
    const first = flat.find((x) => x.group === g);
    return first ? first.index : null;
  }
  return null;
}

// `text` cut where the words typed are, for highlighting: [{text, hit}].
export function highlight(text, q) {
  const s = String(text ?? "");
  const words = queryWords(q).sort((a, b) => b.length - a.length);
  if (!words.length || !s) return [{ text: s, hit: false }];
  const low = s.toLowerCase();
  const marks = new Array(s.length).fill(false);
  for (const w of words) {
    for (let i = low.indexOf(w); i >= 0; i = low.indexOf(w, i + 1)) marks.fill(true, i, i + w.length);
  }
  const out = [];
  for (let i = 0; i < s.length; i += 1) {
    const last = out[out.length - 1];
    if (last && last.hit === marks[i]) last.text += s[i];
    else out.push({ text: s[i], hit: marks[i] });
  }
  return out;
}

// The line under a result: what it is and where (the server's context), when it last changed,
// whether it's a shared sample.
export function contextLine(r) {
  return [r.context, r.updated_at && `updated ${formatDate(r.updated_at)}`, r.sample && "Sample"]
    .filter(Boolean).join(" · ");
}
